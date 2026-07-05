"""verify_v2_ab.py -- 검증(ii): 신구 소스 정확도 A/B (실측 대비, 사후 확인용).

같은 base 들을 현행 경로(data/cur_<region>.db)와 v2(data/v2_<region>.db)로 수집한
forecast_horizon 을 historical 실측과 대조한다.

비교는 두 층위로:
  [raw]   3h 공유 timestamp 에서 원값끼리 -- 소스 자체의 실력
  [serve] 서빙이 실제로 소비하는 형태 -- 현행은 3h 를 1h 로 보간(limit=4,
          serve 쪽 로직과 동일)한 값, v2 는 네이티브 1h.  ★이게 실전 비교.

대상 변수(지점별): temp / reh(제주 humidity) / wind_spd_10m / radiation.
지표: MAE 와 bias(예측-실측 평균).  기본 horizon = D+1.

사용: python core/temp/verify_v2_ab.py --region land --horizon 1
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

import numpy as np
import pandas as pd

CORE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(CORE))
DATA = CORE.parent / "data"

# forecast 컬럼 접두사 -> historical 실측 컬럼 접두사
VAR_MAP = {
    "temp":         "temp_c",
    "reh":          "humidity",
    "wind_spd_10m": "wind_spd",
    "radiation":    "solar_rad",
}
SFX = {"land": ["daegwallyeong", "wonju", "seosan", "pohang", "yeonggwang"],
       "jeju": ["west", "east", "south"]}


def load_fh(db: Path, horizon: int) -> pd.DataFrame:
    with sqlite3.connect(db) as c:
        df = pd.read_sql(
            "SELECT * FROM forecast_horizon WHERE horizon_d = ?", c,
            params=(horizon,))
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    return df


def load_hist(db: Path, cols: list[str]) -> pd.DataFrame:
    with sqlite3.connect(db) as c:
        have = {r[1] for r in c.execute("PRAGMA table_info(historical)")}
        cols = [x for x in cols if x in have]   # 예: 제주 동쪽은 일사 센서 없음
        df = pd.read_sql(
            f"SELECT timestamp, {', '.join(cols)} FROM historical", c)
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    return df.set_index("timestamp")


def serve_view(df: pd.DataFrame, col: str) -> pd.Series:
    """서빙 소비 형태: base 별로 1h 재색인 + 시간 보간(limit=4, 내부만).
    (수요 model_lt limit=4 / 신재생 limit=3 -- 보수적으로 4 사용.)"""
    parts = []
    for _, g in df.groupby("base"):
        s = g.set_index("timestamp")[col].sort_index()
        idx = pd.date_range(s.index.min(), s.index.max(), freq="h")
        s = s.reindex(idx).interpolate("time", limit=4, limit_area="inside")
        parts.append(s)
    return pd.concat(parts)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--region", choices=["land", "jeju"], required=True)
    ap.add_argument("--horizon", type=int, default=1)
    ap.add_argument("--from", dest="date_from", default=None, metavar="YYYY-MM-DD",
                    help="base 하한 (예: 07-01 정책 이후만)")
    ap.add_argument("--to", dest="date_to", default=None, metavar="YYYY-MM-DD",
                    help="base 상한 (예: 06-30 = 1h 시절 현행과 비교)")
    args = ap.parse_args()

    cur = load_fh(DATA / f"cur_{args.region}.db", args.horizon)
    v2 = load_fh(DATA / f"v2_{args.region}.db", args.horizon)
    shared_bases = sorted(set(cur.base) & set(v2.base))
    if args.date_from:
        shared_bases = [b for b in shared_bases if b[:10] >= args.date_from]
    if args.date_to:
        shared_bases = [b for b in shared_bases if b[:10] <= args.date_to]
    cur = cur[cur.base.isin(shared_bases)]
    v2 = v2[v2.base.isin(shared_bases)]
    print(f"[A/B:{args.region}] D+{args.horizon}, 공유 base {len(shared_bases)}개 "
          f"({shared_bases[0][:10]} ~ {shared_bases[-1][:10]})")

    hist_cols = [f"{h}_{s}" for h in VAR_MAP.values() for s in SFX[args.region]]
    hist = load_hist(DATA / f"input_data_{args.region}.db", hist_cols)

    rows = []
    for fpre, hpre in VAR_MAP.items():
        for sfx in SFX[args.region]:
            fcol, hcol = f"{fpre}_{sfx}", f"{hpre}_{sfx}"
            if fcol not in cur.columns or fcol not in v2.columns:
                continue
            if hcol not in hist.columns:
                continue
            act = hist[hcol].dropna()

            # [raw] 3h 공유 timestamp
            c_raw = cur.set_index("timestamp")[fcol].dropna()
            v_raw = v2.set_index("timestamp")[fcol].dropna()
            ts_raw = c_raw.index.intersection(v_raw.index).intersection(act.index)
            # [serve] 보간 후 1h 전체 (양쪽 다 값이 있는 시각만 -- 공정 비교)
            c_srv = serve_view(cur, fcol).dropna()
            v_srv = serve_view(v2, fcol).dropna()
            ts_srv = c_srv.index.intersection(v_srv.index).intersection(act.index)

            def mae_bias(pred, ts):
                e = pred.loc[ts] - act.loc[ts]
                return float(e.abs().mean()), float(e.mean())

            m_c_raw, b_c_raw = mae_bias(c_raw, ts_raw)
            m_v_raw, b_v_raw = mae_bias(v_raw, ts_raw)
            m_c_srv, b_c_srv = mae_bias(c_srv, ts_srv)
            m_v_srv, b_v_srv = mae_bias(v_srv, ts_srv)
            rows.append({
                "var": fpre, "지점": sfx, "n_raw": len(ts_raw), "n_serve": len(ts_srv),
                "MAE현행raw": m_c_raw, "MAEv2raw": m_v_raw,
                "MAE현행serve": m_c_srv, "MAEv2serve": m_v_srv,
                "개선%serve": (100 * (m_c_srv - m_v_srv) / m_c_srv) if m_c_srv else np.nan,
                "bias현행serve": b_c_srv, "biasv2serve": b_v_srv,
            })
    res = pd.DataFrame(rows)
    pd.set_option("display.width", 240)
    print()
    print(res.round(3).to_string(index=False))
    print()
    agg = res.groupby("var")[["MAE현행serve", "MAEv2serve", "개선%serve"]].mean()
    print("변수별 평균 (serve 층위):")
    print(agg.round(3).to_string())
    out = CORE.parent / "data" / f"ab_result_{args.region}_h{args.horizon}.csv"
    res.to_csv(out, index=False, encoding="utf-8-sig")
    print(f"\n저장: {out}")


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    main()

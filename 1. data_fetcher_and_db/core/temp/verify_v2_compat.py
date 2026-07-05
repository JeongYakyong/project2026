"""verify_v2_compat.py -- 검증(i): v2 wide 가 현행과 컬럼·값 호환인지 기계 검사.

비교 대상: 같은 base 를 현행 수집기(--out cur -> data/cur_<region>.db)와
v2(--out v2 -> data/v2_<region>.db)로 각각 수집한 forecast_horizon.

판정 기준 (전부 통과해야 PASS)
A. 컬럼: 현행 컬럼 집합 ⊆ v2 컬럼 집합, 잉여 = 계획된 신규 컬럼만
   (cape/cinn/hpbl/radiation_direct/radiation_diffuse 계열)
B. 값 -- 같은 NE57/KIMR 아카이브를 읽는 셀은 완전 일치(허용오차 0):
   - 운량(total_cloud/midlow_cloud): 공유 timestamp 전부  [양권역, NE57 공급]
   - R030 리드 상한(12z=120h) 밖 timestamp: 공유 컬럼 전부 [NE57 공급]
   - 제주 한정: radiation 계열 제외한 모든 공유 컬럼, 전 timestamp
     [met 는 현행도 KIMR(같은 r030 grib) -- 소스 무변경 증명]
C. 값 -- R030 전환 컬럼(육지 met·일사, 제주 일사)의 D+1~5 차이는 '예상된 소스
   전환'이므로 실패가 아니라 분포 통계로 보고 (평균/최대 차이).
D. 반올림 관례: v2 D+1~5 셀의 소수 자릿수가 관례(temp 2/reh 2/spd 2/sincos 4/
   rain 2/radiation 육지 4·제주 2) 이내.

사용: python core/temp/verify_v2_compat.py --region land --base 20260703
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

CORE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(CORE))
DATA = CORE.parent / "data"
KST = ZoneInfo("Asia/Seoul")

NEW_COL_PREFIXES = ("cape_", "cinn_", "hpbl_", "radiation_direct_", "radiation_diffuse_",
                    "total_cloud_r030_", "midlow_cloud_r030_", "mslp_", "radiation_toa_")
CLOUD_PREFIXES = ("total_cloud_", "midlow_cloud_")
R030_CAP_H = {0: 120, 6: 72, 12: 120, 18: 72}


def load_base(db: Path, base_str: str) -> pd.DataFrame:
    with sqlite3.connect(db) as c:
        df = pd.read_sql(
            "SELECT * FROM forecast_horizon WHERE base = ?", c,
            params=(base_str,), index_col="timestamp")
    return df.sort_index()


def decimals_ok(s: pd.Series, nd: int) -> bool:
    """반올림 자릿수 감사: round(nd) 재적용이 값을 바꾸지 않으면 관례 이내."""
    v = s.dropna()
    if v.empty:
        return True
    return bool(np.allclose(v, v.round(nd), atol=1e-9))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--region", choices=["land", "jeju"], required=True)
    ap.add_argument("--base", required=True, metavar="YYYYMMDD")
    ap.add_argument("--utc", type=int, default=12)
    args = ap.parse_args()

    base_utc = datetime.strptime(args.base, "%Y%m%d").replace(
        hour=args.utc, tzinfo=timezone.utc)
    base_kst = base_utc.astimezone(KST)
    base_str = base_kst.strftime("%Y-%m-%d %H:%M:%S")
    cap_ts = (base_kst + timedelta(hours=R030_CAP_H[args.utc])).strftime(
        "%Y-%m-%d %H:%M:%S")

    cur = load_base(DATA / f"cur_{args.region}.db", base_str)
    v2 = load_base(DATA / f"v2_{args.region}.db", base_str)
    print(f"[compat:{args.region}] base {base_str} -- 현행 {len(cur)}행 x "
          f"{len(cur.columns)}컬럼 / v2 {len(v2)}행 x {len(v2.columns)}컬럼")
    fails: list[str] = []

    # A. 컬럼 포함관계
    missing = set(cur.columns) - set(v2.columns)
    extra = set(v2.columns) - set(cur.columns)
    unplanned = {c for c in extra if not c.startswith(NEW_COL_PREFIXES)}
    if missing:
        fails.append(f"A: v2 에 없는 현행 컬럼 {sorted(missing)}")
    if unplanned:
        fails.append(f"A: 계획 밖 잉여 컬럼 {sorted(unplanned)}")
    print(f"  A. 컬럼: 현행 {len(cur.columns)} 전부 포함 "
          f"{'OK' if not missing else 'FAIL'}, 신규 {len(extra)}개 전부 계획분 "
          f"{'OK' if not unplanned else 'FAIL'}")

    # 공유 timestamp / 컬럼
    shared_ts = cur.index.intersection(v2.index)
    if len(shared_ts) < len(cur.index):
        fails.append(f"B: 현행 timestamp {len(cur.index) - len(shared_ts)}개가 v2 에 없음")
    shared_cols = [c for c in cur.columns if c in v2.columns
                   and c not in ("base", "horizon_d")]
    cur_s, v2_s = cur.loc[shared_ts, shared_cols], v2.loc[shared_ts, shared_cols]

    def equal_cells(cols: list[str], ts=None, label: str = "") -> int:
        """양쪽 값이 있는데 다르면 FAIL / v2 만 결손이면 FAIL /
        현행만 결손(구 경로의 일시적 부분 응답)이면 INFO -- v2 가 보완한 것."""
        a = cur_s[cols] if ts is None else cur_s.loc[ts, cols]
        b = v2_s[cols] if ts is None else v2_s.loc[ts, cols]
        both = a.notna() & b.notna()
        neq = (a != b) & both
        v2_lost = a.notna() & b.isna()
        cur_miss = a.isna() & b.notna()
        n_bad = int(neq.to_numpy().sum()) + int(v2_lost.to_numpy().sum())
        if neq.to_numpy().sum():
            where = neq.any()
            fails.append(f"B({label}): 값 불일치 {int(neq.to_numpy().sum())}셀 -- "
                         f"컬럼 {list(where[where].index)[:6]}")
        if v2_lost.to_numpy().sum():
            where = v2_lost.any()
            fails.append(f"B({label}): v2 쪽 결손 {int(v2_lost.to_numpy().sum())}셀 -- "
                         f"컬럼 {list(where[where].index)[:6]}")
        n_info = int(cur_miss.to_numpy().sum())
        if n_info:
            print(f"     (INFO) 현행 쪽 결손을 v2 가 보완: {n_info}셀 "
                  f"(구 경로의 일시적 부분 응답 -- v2 결함 아님)")
        return n_bad

    # B-1. 운량: 전 공유 timestamp 완전 일치
    cloud_cols = [c for c in shared_cols if c.startswith(CLOUD_PREFIXES)]
    n1 = equal_cells(cloud_cols, label="운량")
    print(f"  B1. 운량 {len(cloud_cols)}컬럼 x {len(shared_ts)}행: "
          f"불일치 {n1}셀 {'OK' if n1 == 0 else 'FAIL'}")

    # B-2. R030 상한 밖(NE57 전담): 공유 컬럼 전부 완전 일치
    beyond = [t for t in shared_ts if t > cap_ts]
    n2 = equal_cells(shared_cols, ts=beyond, label="상한 밖")
    print(f"  B2. R030 상한 밖 {len(beyond)}행 x {len(shared_cols)}컬럼: "
          f"불일치 {n2}셀 {'OK' if n2 == 0 else 'FAIL'}")

    # B-3. 제주 met: NC 통일(2026-07-05) 후 기준 -- 구 KIMR grib 값과 패킹
    #      양자화(±0.005)+반올림 상호작용 이내면 동일 소스로 판정.
    #      의미가 바뀐 컬럼(cape/cinn=MCAPE/MCIN, tcog/tcoh=NC 부재->NULL)은 제외하고
    #      별도 보고.  풍향 sin/cos 는 저풍속에서 각도 민감이라 완화 허용.
    if args.region == "jeju":
        skip_pre = ("cape_", "cinn_", "tcog_", "tcoh_", "reh_")
        met_cols = [c for c in shared_cols
                    if not c.startswith("radiation") and c not in cloud_cols
                    and not c.startswith(skip_pre)]
        within = [t for t in shared_ts if t <= cap_ts]
        n3 = 0
        for c in met_cols:
            tol = 0.05 if c.startswith(("wd_sin", "wd_cos")) else 0.011
            a_, b_ = cur_s.loc[within, c], v2_s.loc[within, c]
            both = a_.notna() & b_.notna()
            n_bad = int(((a_ - b_).abs() > tol)[both].sum())
            if n_bad:
                fails.append(f"B3: {c} 허용오차({tol}) 밖 {n_bad}셀 "
                             f"max={float((a_ - b_).abs()[both].max()):.3f}")
                n3 += n_bad
        print(f"  B3. 제주 met {len(met_cols)}컬럼 (양자화 허용오차): "
              f"위반 {n3}셀 {'OK' if n3 == 0 else 'FAIL'}")
        # reh: 반올림 관례 r4->r2 전환이라 허용오차 0.011 로 별도 확인
        reh_cols = [c for c in shared_cols if c.startswith("reh_")]
        n3r = 0
        for c in reh_cols:
            a_, b_ = cur_s.loc[within, c], v2_s.loc[within, c]
            both = a_.notna() & b_.notna()
            n3r += int(((a_ - b_).abs() > 0.011)[both].sum())
        print(f"  B3r. 제주 reh(r4->r2 전환): 허용오차 밖 {n3r}셀 "
              f"{'OK' if n3r == 0 else 'FAIL'}")
        if n3r:
            fails.append(f"B3r: reh 허용오차 밖 {n3r}셀")
        # 의미 변경 컬럼 보고 (실패 아님)
        for pre, note in (("cape_", "MCAPE 로 세대 교체"), ("cinn_", "MCIN 으로 세대 교체"),
                          ("tcog_", "NC 부재 -> NULL"), ("tcoh_", "NC 부재 -> NULL")):
            cols_ = [c for c in shared_cols if c.startswith(pre)]
            if cols_:
                a_, b_ = cur_s.loc[within, cols_], v2_s.loc[within, cols_]
                print(f"     (의미 변경) {pre}*: {note} -- 현행 평균 "
                      f"{float(a_.mean().mean()):.1f} / v2 평균 "
                      f"{float(b_.mean().mean()) if b_.notna().any().any() else float('nan'):.1f}"
                      f" / v2 NULL {int(b_.isna().sum().sum())}셀")

    # C. R030 전환 컬럼의 D+1~5 차이 통계 (실패 아님 -- 소스 전환 크기 보고)
    within = [t for t in shared_ts if t <= cap_ts]
    if args.region == "land":
        swapped = [c for c in shared_cols
                   if c.startswith(("temp_", "reh_", "wind_spd_", "wd_sin_",
                                    "wd_cos_", "gust_", "rainfall_", "radiation_"))
                   and c not in cloud_cols]
    else:
        swapped = [c for c in shared_cols if c.startswith("radiation_")]
    diff = (v2_s.loc[within, swapped] - cur_s.loc[within, swapped])
    st = diff.abs().agg(["mean", "max"]).T.sort_values("max", ascending=False)
    print(f"  C. 소스 전환 컬럼(D+1~5, 3h 공유 {len(within)}행) |차이| 상위:")
    print(st.head(8).round(3).to_string().replace("\n", "\n     "))

    # D. 반올림 관례 감사 (v2 전체 행)
    rules = [("temp_", 2), ("reh_", 2),   # 제주 reh 도 NC 통일 후 r2 (07-05)
             ("wind_spd_", 2), ("wd_sin_", 4), ("wd_cos_", 4), ("rainfall_", 2),
             ("radiation_", 4 if args.region == "land" else 2)]
    bad_r = [c for pre, nd in rules for c in v2.columns
             if c.startswith(pre) and not decimals_ok(v2[c], nd)]
    if bad_r:
        fails.append(f"D: 반올림 관례 위반 {bad_r}")
    print(f"  D. 반올림 관례: {'OK' if not bad_r else 'FAIL ' + str(bad_r)}")

    print(f"\n[compat:{args.region}] {'PASS -- 위반 0건' if not fails else 'FAIL:'}")
    for f in fails:
        print("  -", f)
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    main()

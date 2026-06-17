"""
clean_historical.py -- historical 테이블의 결측을 정리해 "깔끔한" DB 를 만든다.

규칙 (2026-06-14 사용자 확정)
- 짧은 결측(<= SHORT_LIMIT 시간): time 보간 (limit=SHORT_LIMIT, 외삽 금지).
- 긴 결측(> SHORT_LIMIT): 7일 전 같은 시각 값으로 복사(없으면 14·21일 폴백).
- 최근 PROVISIONAL_HOURS 시간(미발행 잠정분)은 건드리지 않는다 -- 서버 수집이 진짜
  값으로 채울 자리.
- benign/구조적 컬럼은 제외: 여름 무적설 snow_depth_*, 제주의 미사용/희소 컬럼
  (land_est_demand_da / real_net_load_jeju / smp_jeju_rt / smp_rt_*).

원본은 .bak_* 로 백업하고, 무엇을 어떻게 바꿨는지 report 를 같이 찍는다.
기본은 dry-run(쓰기 없음) -- 실제 적용은 --apply.

사용
    python core/clean_historical.py --region land            # dry-run
    python core/clean_historical.py --region land --apply     # 백업 후 적용
    python core/clean_historical.py --region jeju --apply
"""
from __future__ import annotations

import argparse
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path

import pandas as pd

DATA = Path(__file__).resolve().parent.parent / "data"
MAIN_DB = {"land": DATA / "input_data_land.db", "jeju": DATA / "input_data_jeju.db"}

SHORT_LIMIT = 4          # 시간. 이하 = 보간, 초과 = 7일 복사
PROVISIONAL_HOURS = 48   # 최근 N시간 결측은 잠정으로 보고 건드리지 않음
COPY_FALLBACK_DAYS = (7, 14, 21)


def is_skip(region: str, col: str) -> bool:
    if col.startswith("snow_depth"):
        return True
    if region == "jeju" and col in {
        "land_est_demand_da", "real_net_load_jeju",
        "smp_jeju_rt", "smp_rt_neg_num",
        "smp_rt_g1", "smp_rt_g2", "smp_rt_g3", "smp_rt_g4",
    }:
        return True
    return False


def clean(region: str, apply: bool) -> None:
    db = MAIN_DB[region]
    con = sqlite3.connect(db)
    df = pd.read_sql("SELECT * FROM historical", con, parse_dates=["timestamp"])
    con.close()
    df = df.sort_values("timestamp").set_index("timestamp")

    # 시간축 연속성 확인 (긴-복사가 timestamp 정렬에 의존).
    full = pd.date_range(df.index.min(), df.index.max(), freq="h")
    gap = len(full.difference(df.index))
    if gap:
        print(f"[clean:{region}] ⚠ 시간축 빠진 행 {gap}개 -- 먼저 재수집 권장 "
              f"(7일 복사 정렬이 어긋날 수 있음). 그래도 진행은 가능.")
    cut = df.index.max() - pd.Timedelta(hours=PROVISIONAL_HOURS)

    cols = [c for c in df.columns if not is_skip(region, c)]
    n_interp = n_copy = n_copy_fail = n_provis = 0
    interp_log: list[str] = []
    copy_log: list[tuple] = []

    for col in cols:
        m = df[col].isna()
        if not m.any():
            continue
        # 결측 run 분해
        grp = (m != m.shift()).cumsum()
        for _, run in m[m].groupby(grp[m]):
            s, e = run.index[0], run.index[-1]
            n = int((e - s) / pd.Timedelta(hours=1)) + 1
            if s >= cut:
                n_provis += n
                continue
            if n <= SHORT_LIMIT:
                # time 보간 (내부 한정, 외삽 금지)
                seg = df[col].interpolate(method="time", limit=SHORT_LIMIT,
                                          limit_area="inside")
                df.loc[s:e, col] = seg.loc[s:e]
                n_interp += n
            else:
                # 7일 전 복사 (폴백 14·21일)
                before = df.loc[s:e, col].isna().sum()
                for d in COPY_FALLBACK_DAYS:
                    src = df[col].shift(d * 24)
                    fillable = df.loc[s:e, col].isna() & src.loc[s:e].notna()
                    df.loc[s:e, col] = df.loc[s:e, col].where(~fillable, src.loc[s:e])
                    if not df.loc[s:e, col].isna().any():
                        break
                after = df.loc[s:e, col].isna().sum()
                n_copy += before - after
                n_copy_fail += after
                copy_log.append((col, str(s), str(e), n, before - after, after))

    print(f"\n[clean:{region}] {db.name}  대상컬럼 {len(cols)} (benign/구조적 제외)")
    print(f"  보간(≤{SHORT_LIMIT}h) 채운 셀 : {n_interp}")
    print(f"  7일복사 채운 셀          : {n_copy}")
    print(f"  복사 실패(7/14/21일도 NULL): {n_copy_fail}")
    print(f"  최근{PROVISIONAL_HOURS}h 잠정(미처리)  : {n_provis}")
    if copy_log:
        print("  [7일복사 상세]")
        for col, s, e, n, done, fail in copy_log:
            print(f"    {s}~{e} ({n}h) {col}: 채움 {done}, 실패 {fail}")

    if not apply:
        print("\n  [dry-run] 쓰기 없음. 적용하려면 --apply")
        return

    bak = db.with_suffix(db.suffix + f".bak_clean_{datetime.now():%Y%m%d_%H%M%S}")
    shutil.copy2(db, bak)
    print(f"\n  백업: {bak.name}")

    out = df.reset_index()
    # timestamp 포맷을 원본과 동일하게 ('YYYY-MM-DD HH:MM:SS') -- 다른 테이블/
    # forecast_horizon 와의 JOIN 깨짐 방지.
    out["timestamp"] = out["timestamp"].dt.strftime("%Y-%m-%d %H:%M:%S")

    con = sqlite3.connect(db)
    # 원본 스키마(PRIMARY KEY) + 인덱스를 그대로 보존: 동일 CREATE 로 재생성 후 append.
    create_sql = con.execute(
        "SELECT sql FROM sqlite_master WHERE name='historical'").fetchone()[0]
    idx_sqls = [r[0] for r in con.execute(
        "SELECT sql FROM sqlite_master WHERE type='index' "
        "AND tbl_name='historical' AND sql IS NOT NULL")]
    con.execute("DROP TABLE historical")
    con.execute(create_sql)
    out.to_sql("historical", con, if_exists="append", index=False)
    for s in idx_sqls:
        con.execute(s)
    con.commit()
    con.close()
    print(f"  적용 완료: historical {len(out)}행 재기록 (PK·인덱스 보존, ts 포맷 유지)")


def main() -> None:
    p = argparse.ArgumentParser(description="historical 결측 정리 (보간/7일복사)")
    p.add_argument("--region", choices=["land", "jeju"], required=True)
    p.add_argument("--apply", action="store_true", help="백업 후 실제 쓰기 (기본 dry-run)")
    a = p.parse_args()
    clean(a.region, a.apply)


if __name__ == "__main__":
    main()

"""
collect_forecast_new.py -- 기상예보(KMA) 단일목적 수집기 → forecast_horizon 지평 아카이브.

역할별 재구성(2026-06-15).  cron 한 줄 = 한 역할:
  ① 기상예보 → forecast_horizon   = **이 파일**
  ② 실측      → historical        = collect_data_land_new.py
  ③ 서빙 체인 → est_horizon_land  = serve_chain_land_new.py

기존 collect_forecast_runs.py 가 이미 forecast_horizon(KMA 전용, 12 UTC, base별 지평 태깅)을
정확히 적재한다.  이 파일은 그 **검증된 엔진(upsert_runs / latest_12z / verify / merge /
base 선택)을 그대로 import 재사용**하되, 두 가지만 정리한다:
  - 육지 기상 wide 를 collect_data_land_new.build_forecast_wide() 로 **네이티브하게** 받는다
    (= 기존 disable_kpx() 의 `cl._join_da` no-op 몽키패치를 없앤 깔끔한 경로).  KPX 호출 자체가
    경로에 없으므로 forecast_horizon 에 KPX(*_da)가 섞일 여지가 원천 차단된다.
  - 윈도우 기본값 육지 16일(D+15.5, KIMG 3h 상한 372h)로 운영 cron 과 일치.

제주는 이번 재구성 범위 밖(est_horizon_jeju 미구축)이라 **현행 유지** — `--region jeju` 는 기존
collect_forecast_runs.fetch_one(cj.build + KPX 비활) 경로로 위임한다.  제주 forecast_horizon 은
미래 전환 대비 계속 적재된다.

사용 예
    python core/collect_forecast_new.py                       # 최신 12z, 육지 (default --region land)
    python core/collect_forecast_new.py --region both         # 육지 + 제주
    python core/collect_forecast_new.py --base 20260610       # 2026-06-10 의 12z 발표
    python core/collect_forecast_new.py --backfill 30         # 과거 30일치 12z (resume-skip)
    python core/collect_forecast_new.py --backfill 10 --out bf# data/bf_<region>.db 에 격리 적재
    python core/collect_forecast_new.py --merge bf            # bf_*.db -> 본 DB 병합
    python core/collect_forecast_new.py --verify              # base 별 완전성 검사 (fetch 없음)
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

# 검증된 forecast_horizon 엔진을 그대로 재사용 (수정 없음).  import 시 CORE 가 sys.path 에
# 들어가고 collect_data_jeju/land·_common 도 로드된다.
import collect_forecast_runs as cfr
import collect_data_land_new as cdln

KST = cfr.KST
UTC = cfr.UTC
RUNS_TABLE = cfr.RUNS_TABLE
REGIONS = cfr.REGIONS


# ── fetch: 육지는 네이티브 clean wide, 제주는 기존 경로 위임 ────────────────
def fetch_one(region: str, base_utc: datetime, days: int) -> pd.DataFrame:
    """단일 base 의 기상 wide 를 메모리로 반환 (KMA 전용).

    land : collect_data_land_new.build_forecast_wide (KPX 경로 자체가 없음).
    jeju : collect_forecast_runs.fetch_one 위임 (cj.build + disable_kpx 로 KPX 비활).
    """
    if region == "land":
        return cdln.build_forecast_wide(base=base_utc, forecast_days=days)
    return cfr.fetch_one(region, base_utc, days)


# ── 완결성 기반 skip (육지) ────────────────────────────────────────────────
def expected_timestamps(base_utc: datetime, days: int) -> set[str]:
    """수집기가 실제로 받는 timestamp 집합 = {base_kst + hf : hf ∈ collection_hf_range}.

    collection_hf_range 가 윈도우(forecast_days_override)·1h/3h 해상도 전환·MIN_HF 를 모두
    반영하므로, 완전 base 의 저장 timestamp 집합과 정확히 일치한다(육지 16일=212행 실증).
    """
    base_kst = base_utc.astimezone(KST)
    with cfr.cl.ckl.forecast_days_override(days):
        hfs = list(cfr.ckg.collection_hf_range(base_utc))
    return {(base_kst + timedelta(hours=h)).strftime("%Y-%m-%d %H:%M:%S") for h in hfs}


def base_complete(db_path: Path, base_utc: datetime, days: int) -> bool:
    """그 base 가 완전한가 = (기대 timestamp 전부 존재) AND (지점 sentinel temp* NULL 셀 없음).

    hf 단위 실패는 행 누락(timestamp 부재) 또는 그 지점 컬럼의 NULL 셀로 남으므로 둘 다 본다.
    temp_skin* 은 KIMR 전용(장지평 정상 NULL)이라 sentinel 에서 제외(verify_runs 와 동일).
    """
    if not db_path.exists() or db_path.stat().st_size == 0:
        return False
    base_str = base_utc.astimezone(KST).strftime("%Y-%m-%d %H:%M:%S")
    exp = expected_timestamps(base_utc, days)
    with sqlite3.connect(db_path) as c:
        try:
            cols = [r[1] for r in c.execute(f"PRAGMA table_info({RUNS_TABLE})").fetchall()]
        except sqlite3.OperationalError:
            return False
        if "timestamp" not in cols:
            return False
        present = {r[0] for r in c.execute(
            f"SELECT timestamp FROM {RUNS_TABLE} WHERE base=?", (base_str,)).fetchall()}
        if not exp.issubset(present):
            return False
        sentinels = [col for col in cols
                     if col.startswith("temp") and not col.startswith("temp_skin")]
        if sentinels:
            agg = ", ".join(f'SUM("{s}" IS NULL)' for s in sentinels)
            nullcnt = c.execute(
                f"SELECT {agg} FROM {RUNS_TABLE} WHERE base=?", (base_str,)).fetchone()
            if any((v or 0) > 0 for v in nullcnt):
                return False
    return True


def run_region(
    region: str, bases: list[datetime], days: int, force: bool, db_path: Path,
) -> int:
    """cfr.run_region 의 동일 흐름 + 완결성 기반 skip.

    skip 판정(육지) = base 가 완전(base_complete)하면 건너뛰고, **불완전하면 다시 받는다**.
    쓰기가 (base,timestamp) upsert 라 부분 적재 base 는 재실행만으로 부족분이 채워진다(auto-resume).
    --force 는 "완전해도 다시 받기".  제주는 이번 재구성 범위 밖이라 기존 count 기준 skip 유지.
    """
    have = cfr.existing_base_counts(db_path) if region != "land" else {}
    total = 0
    for i, b in enumerate(bases, 1):
        base_str = b.astimezone(KST).strftime("%Y-%m-%d %H:%M:%S")
        label = f"[runs:{region}] base {b.strftime('%Y%m%d %HZ')} ({base_str} KST)"
        if not force:
            if region == "land":
                if base_complete(db_path, b, days):
                    print(f"{label} -- skip (완전; --force 로 재수집)")
                    continue
            elif have.get(base_str, 0) > 0:   # 제주: 현행 count 기준 (변경 없음)
                print(f"{label} -- skip (already {have[base_str]} rows; --force to redo)")
                continue
        print(f"\n{'='*70}\n{label}  ({i}/{len(bases)}, window={days}d)\n{'='*70}")
        try:
            wide = fetch_one(region, b, days)
        except Exception as e:
            print(f"{label} -- [WARN] fetch failed: {e} (skip)")
            continue
        if wide.empty:
            print(f"{label} -- [WARN] empty wide, nothing to write")
            continue
        n = cfr.upsert_runs(wide, b, db_path)
        total += n
        h = pd.Series(
            [(d - b.astimezone(KST).date()).days
             for d in pd.to_datetime(wide.index).date]
        )
        print(
            f"{label} -- UPSERT {n:,} rows -> {db_path.name}::{RUNS_TABLE} "
            f"(horizon D+{h.min()}~D+{h.max()})"
        )
    return total


# ── CLI ────────────────────────────────────────────────────────────────────
def main() -> None:
    p = argparse.ArgumentParser(
        description=(
            "12 UTC 발표를 horizon-tagged 로 forecast_horizon 에 적재 (KMA 기상 전용). "
            "육지는 clean wide(collect_data_land_new), 제주는 현행 경로 위임."
        ),
    )
    mode = p.add_mutually_exclusive_group()
    mode.add_argument(
        "--base", metavar="YYYYMMDD",
        help="특정 날짜의 12 UTC 발표 (기본: 최신 가용 12z)",
    )
    mode.add_argument(
        "--backfill", type=int, metavar="N_DAYS",
        help="과거 N 일치 12z 발표를 차례로 적재 (resume-skip)",
    )
    mode.add_argument(
        "--merge", metavar="NAME",
        help="data/<NAME>_<region>.db 의 forecast_horizon 를 본 DB 에 병합 (fetch 없음)",
    )
    mode.add_argument(
        "--verify", action="store_true",
        help="base 별 완전성 검사 (행수 + 지점별 NULL 셀) -- fetch 없음",
    )
    p.add_argument(
        "--region", choices=["jeju", "land", "both"], default="land",
        help="대상 권역 (default land -- 이번 재구성은 전국/육지 우선)",
    )
    p.add_argument(
        "--days", type=int, default=None, metavar="N",
        help="윈도우 길이 override (기본: 육지 16 / 제주 7)",
    )
    p.add_argument(
        "--out", metavar="NAME", default=None,
        help="본 DB 대신 data/<NAME>_<region>.db 에 적재 (백필 격리용)",
    )
    p.add_argument(
        "--force", action="store_true",
        help="완전한 base 도 다시 받는다 (기본은 완결성 기반: 불완전 base 는 재실행만으로 부족분 auto-resume)",
    )
    p.add_argument(
        "--min-hf", type=int, default=0, metavar="H",
        help="이 hf(시간) 이상만 수집 -- 장지평 증분 백필용 (예: --region land --min-hf 288)",
    )
    args = p.parse_args()

    if args.min_hf:
        cfr.ckg.MIN_HF = args.min_hf
        print(f"[collect_forecast_new] 증분 모드: hf >= {args.min_hf} 만 수집")

    # 제주 위임 경로(cj.build)를 위해 KPX 호출을 끈다.  육지 clean 경로엔 영향 없음
    # (build_forecast_wide 는 _join_da 를 부르지 않음).  _upsert_df 의 is_non_kma 필터와
    # 이중 안전.
    cfr.disable_kpx()

    regions = ["jeju", "land"] if args.region == "both" else [args.region]

    if args.verify:
        for region in regions:
            cfr.verify_runs(cfr.region_db(region, args.out), region, args.out)
            print()
        return

    if args.merge:
        print(f"[collect_forecast_new] merge '{args.merge}' -> main DBs")
        for region in regions:
            cfr.merge_runs(cfr.region_db(region, args.merge), REGIONS[region]["db"])
        return

    if args.base:
        bases = [datetime.strptime(args.base, "%Y%m%d").replace(hour=12, tzinfo=UTC)]
    elif args.backfill:
        bases = cfr.backfill_12z_bases(args.backfill)
    else:
        bases = [cfr.latest_12z()]

    print(
        f"[collect_forecast_new] regions={regions}  bases={len(bases)} "
        f"({bases[0].strftime('%Y%m%d')}~{bases[-1].strftime('%Y%m%d')} 12Z)  "
        f"out={'main DB' if not args.out else args.out + '_<region>.db'}  "
        f"table='{RUNS_TABLE}' key=(base,timestamp)"
    )

    t0 = time.time()
    for region in regions:
        days = args.days if args.days is not None else REGIONS[region]["days"]
        db_path = cfr.region_db(region, args.out)
        n = run_region(region, bases, days, args.force, db_path)
        print(f"\n[runs:{region}] total UPSERT {n:,} rows -> {db_path.name}")
    print(f"\n[collect_forecast_new] done in {(time.time()-t0)/60:.1f}m")


if __name__ == "__main__":
    main()

"""collect_l010_archive.py -- 국지모델(L010, 1.3km, D+2, 1h) 아카이브 수집기.

사용자 결정(2026-07-04): L010 은 **수집만** 한다 -- 서빙 미연결, EDA 로 가치가
확인되면 그때 체인 편입을 판단.  forecast_horizon 과 같은 wide 규약으로
별도 테이블 `forecast_horizon_l010` 에 쌓는다 (서빙은 forecast_horizon 만 읽으므로
본 DB 에 있어도 무해하지만, 검증 기간에는 기본 격리 DB 로 간다 -- v2 와 동일 원칙).

지점·확장 규약은 api_fetchers_kim2 의 SSOT 를 그대로 쓴다 (지점 추가 = 1줄 +
--points 백필).  upsert 는 컬럼 보존 병합(collect_forecast_v2.upsert_runs_v2).

사용 예
    python core/collect_l010_archive.py --region both             # 최신 12z
    python core/collect_l010_archive.py --backfill 9 --region both
    python core/collect_l010_archive.py --verify --region both
    python core/collect_l010_archive.py --merge --region both     # 격리 -> 본 DB
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

import collect_forecast_runs as cfr
import collect_forecast_new as cfn
import collect_forecast_v2 as cfv2
import api_fetchers_kim2 as k2
import postprocess as pp

KST = cfr.KST
UTC = cfr.UTC
TABLE = "forecast_horizon_l010"
DAYS = 2            # L010 최대 48h = D+2 (4주기 공통, 실측)
DEFAULT_OUT = "v2"  # 격리 기본 (v2_<region>.db 안의 별도 테이블)

REGIONS_L010 = {
    "land": {"points": k2.POINTS_LAND_V2, "radiation_round": None},
    "jeju": {"points": k2.POINTS_JEJU_V2, "radiation_round": 2},
}


def build_l010_wide(region: str, base_utc: datetime,
                    points: list[dict] | None = None) -> pd.DataFrame:
    cfg = REGIONS_L010[region]
    pts = points if points is not None else cfg["points"]
    long = k2.fetch_model_long(
        pts, "KIML", "L010", k2.L010_NAME, base_utc, DAYS,
        k2.L010_MAX_HF, rain_anchor=True)
    suffix_map = {p["name"]: p["sfx"] for p in pts}
    wide = k2.long_to_wide_v2(long, suffix_map,
                              radiation_round=cfg["radiation_round"])
    if wide.empty:
        return wide
    wide = pp.clip_ranges(wide)
    # 윈도우 트림 (rain anchor 행 제거)
    base_kst = base_utc.astimezone(KST)
    start = (base_kst + timedelta(days=1)).replace(hour=0, minute=0, second=0,
                                                   microsecond=0)
    end = start + timedelta(days=DAYS)
    w0, w1 = start.strftime("%Y-%m-%d %H:%M:%S"), end.strftime("%Y-%m-%d %H:%M:%S")
    return wide[(wide.index >= w0) & (wide.index < w1)]


def expected_rows(base_utc: datetime) -> int:
    return len(k2.hf_range_1h(base_utc, DAYS, k2.L010_MAX_HF))


def base_complete(region: str, db_path: Path, base_utc: datetime) -> bool:
    if not db_path.exists() or db_path.stat().st_size == 0:
        return False
    base_str = base_utc.astimezone(KST).strftime("%Y-%m-%d %H:%M:%S")
    with sqlite3.connect(db_path) as c:
        try:
            cols = {r[1] for r in c.execute(f"PRAGMA table_info({TABLE})")}
        except sqlite3.OperationalError:
            return False
        if "timestamp" not in cols:
            return False
        sentinels = [f'temp_{p["sfx"]}' for p in REGIONS_L010[region]["points"]
                     if f'temp_{p["sfx"]}' in cols]
        if len(sentinels) < len(REGIONS_L010[region]["points"]):
            return False
        n = c.execute(f"SELECT COUNT(*) FROM {TABLE} WHERE base=?",
                      (base_str,)).fetchone()[0]
        if n < expected_rows(base_utc):
            return False
        agg = ", ".join(f'SUM("{s}" IS NULL)' for s in sentinels)
        nulls = c.execute(f"SELECT {agg} FROM {TABLE} WHERE base=?",
                          (base_str,)).fetchone()
        return not any((v or 0) > 0 for v in nulls)


def merge_l010(src_db: Path, dst_db: Path) -> int:
    if not src_db.exists():
        print(f"  [merge-l010] {src_db.name} 없음 -- skip")
        return 0
    with sqlite3.connect(src_db) as c:
        try:
            df = pd.read_sql(f"SELECT * FROM {TABLE}", c)
        except Exception as e:
            print(f"  [merge-l010] {src_db.name} 읽기 실패: {e} -- skip")
            return 0
    if df.empty:
        return 0
    df = df.set_index("timestamp")
    n = cfv2.upsert_wide_coalesce(df, dst_db, table=TABLE)
    print(f"  [merge-l010] {src_db.name} -> {dst_db.name}::{TABLE}  {n:,} rows")
    return n


def main() -> None:
    p = argparse.ArgumentParser(
        description="L010(국지 1.3km, D+2 1h) 아카이브 -> forecast_horizon_l010. "
                    "서빙 미연결(EDA 대기).")
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--base", metavar="YYYYMMDD")
    mode.add_argument("--backfill", type=int, metavar="N_DAYS")
    mode.add_argument("--merge", action="store_true")
    mode.add_argument("--verify", action="store_true")
    p.add_argument("--utc", type=int, choices=[0, 6, 12, 18], default=12)
    p.add_argument("--region", choices=["jeju", "land", "both"], default="land")
    p.add_argument("--points", default=None)
    p.add_argument("--out", default=DEFAULT_OUT)
    p.add_argument("--production", action="store_true")
    p.add_argument("--force", action="store_true")
    args = p.parse_args()

    out = None if args.production else args.out
    regions = ["jeju", "land"] if args.region == "both" else [args.region]
    sfx_filter = args.points.split(",") if args.points else None

    if args.verify:
        for region in regions:
            db = cfr.region_db(region, out)
            if not db.exists():
                print(f"[verify-l010:{region}] {db.name} 없음")
                continue
            with sqlite3.connect(db) as c:
                try:
                    bases = [r[0] for r in c.execute(
                        f"SELECT DISTINCT base FROM {TABLE} ORDER BY base")]
                except sqlite3.OperationalError:
                    print(f"[verify-l010:{region}] {TABLE} 테이블 없음")
                    continue
            bad = []
            for bs in bases:
                b_utc = (datetime.strptime(bs, "%Y-%m-%d %H:%M:%S")
                         .replace(tzinfo=KST).astimezone(UTC))
                if not base_complete(region, db, b_utc):
                    bad.append(bs[:10])
            print(f"[verify-l010:{region}] {len(bases)} bases, 불완전 {bad or '없음 (OK)'}")
        return

    if args.merge:
        for region in regions:
            merge_l010(cfr.region_db(region, args.out), cfr.REGIONS[region]["db"])
        return

    if args.base:
        bases = [datetime.strptime(args.base, "%Y%m%d").replace(hour=args.utc,
                                                                tzinfo=UTC)]
    elif args.backfill:
        bases = [cfn.latest_base(args.utc) - timedelta(days=k)
                 for k in range(args.backfill)][::-1]
    else:
        bases = [cfn.latest_base(args.utc)]

    t0 = time.time()
    for region in regions:
        pts = (REGIONS_L010[region]["points"] if not sfx_filter else
               [p_ for p_ in REGIONS_L010[region]["points"] if p_["sfx"] in sfx_filter])
        db_path = cfr.region_db(region, out)
        total = 0
        for b in bases:
            label = f"[l010:{region}] base {b.strftime('%Y%m%d %HZ')}"
            if not args.force and base_complete(region, db_path, b):
                print(f"{label} -- skip (완전)")
                continue
            try:
                wide = build_l010_wide(region, b, points=pts)
            except Exception as e:
                print(f"{label} -- [WARN] fetch failed: {e} (skip)")
                continue
            if wide.empty:
                print(f"{label} -- [WARN] empty wide")
                continue
            n = cfv2.upsert_runs_v2(wide, b, db_path, table=TABLE)
            total += n
            print(f"{label} -- UPSERT {n:,} rows -> {db_path.name}::{TABLE}")
        print(f"[l010:{region}] total {total:,} rows")
    print(f"[collect_l010_archive] done in {(time.time() - t0) / 60:.1f}m")


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    main()

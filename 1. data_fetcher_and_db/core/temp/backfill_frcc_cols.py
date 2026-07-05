"""backfill_frcc_cols.py -- 기존 v2 base 들에 frcc 1h 운량 신규 컬럼만 채운다.

전체 재수집 없이 frcc(지점당 2콜)만 받아 컬럼 보존 upsert 로 끼워넣는다
(upsert_wide_coalesce 라 기존 컬럼 불변).  1회성 -- 이후 base 는 v2 수집기가
수집 시점에 함께 받는다.

사용: python core/temp/backfill_frcc_cols.py --from 20260625 --to 20260702
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

CORE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(CORE))

import pandas as pd

import api_fetchers_kim2 as k2
import collect_forecast_v2 as cfv2
import collect_forecast_runs as cfr


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="d0", required=True, metavar="YYYYMMDD")
    ap.add_argument("--to", dest="d1", required=True, metavar="YYYYMMDD")
    ap.add_argument("--utc", type=int, default=12)
    ap.add_argument("--out", default="v2")
    args = ap.parse_args()

    d = datetime.strptime(args.d0, "%Y%m%d").replace(hour=args.utc,
                                                     tzinfo=timezone.utc)
    end = datetime.strptime(args.d1, "%Y%m%d").replace(hour=args.utc,
                                                       tzinfo=timezone.utc)
    bases = []
    while d <= end:
        bases.append(d)
        d += timedelta(days=1)

    for region in ("land", "jeju"):
        cfg = cfv2.REGIONS_V2[region]
        db = cfr.region_db(region, args.out)
        suffix_map = {p["name"]: p["sfx"] for p in cfg["points"]}
        rr = 2 if region == "jeju" else None
        total = 0
        for b in bases:
            long = k2.fetch_r030_frcc_long(cfg["points"], b, cfg["days"],
                                           k2.R030_MAX_HF)
            if long.empty:
                print(f"[frcc:{region}] {b:%Y%m%d} 비어있음 -- skip")
                continue
            wide = k2.long_to_wide_v2(long, suffix_map, radiation_round=rr)
            w0, w1 = cfv2._window_strs(b, cfg["days"])
            wide = wide[(wide.index >= w0) & (wide.index < w1)].clip(0, 1)
            n = cfv2.upsert_runs_v2(wide, b, db)
            total += n
        print(f"[frcc:{region}] {len(bases)} bases -> {db.name} UPSERT {total:,}행\n")


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    main()

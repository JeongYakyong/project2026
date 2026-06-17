"""
migrate_forecast_horizon.py -- bf_<region>.db 의 forecast_runs 를 본 DB 의
forecast_horizon (KMA 예보 전용 아카이브) 로 통합.

설계 결정 (2026-06-14, 사용자 확정)
- 아카이브 테이블명을 forecast_runs -> forecast_horizon 로 정정.
  KPX 익일(smp_*_da / *_est_demand_da)은 D+1 한계라 지평 아카이브에 해당 없음
  -> historical/forecast 테이블에만 존재.  이 테이블은 KMA 기상 예보 전용.
- 제외 컬럼: smp_land_da, land_est_demand_da (KPX), day_type (달력, timestamp 에서
  재산출 가능).  유지: timestamp, base, horizon_d + KMA 기상 65컬럼.
- historical / forecast(freshest 서빙 뷰) 테이블은 손대지 않는다.
- 기존 forecast_runs 테이블(있으면)은 bf 범위에 포함되는 중복이라 폐기.

사용
    python core/migrate_forecast_horizon.py --region land            # 실행
    python core/migrate_forecast_horizon.py --region land --dry-run  # 계획만
"""
from __future__ import annotations

import argparse
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

CORE = Path(__file__).resolve().parent
DATA = CORE.parent / "data"

SRC_TABLE = "forecast_runs"          # bf_*.db 안의 기존 테이블명
DST_TABLE = "forecast_horizon"   # 본 DB 의 새 아카이브 테이블명
KEY_COLS = ["timestamp", "base", "horizon_d"]

MAIN_DB = {"land": DATA / "input_data_land.db", "jeju": DATA / "input_data_jeju.db"}


def is_kma_weather(col: str) -> bool:
    """KMA 기상 컬럼인가.  제외 = KPX 익일(`*_da`: smp_*_da/*_est_demand_da) +
    달력(`day_type`).  지역 무관(육지 daegwallyeong.. / 제주 east·south·west)."""
    return not (col.endswith("_da") or col == "day_type")


def src_db(region: str) -> Path:
    return DATA / f"bf_{region}.db"


def migrate(region: str, dry_run: bool) -> None:
    src, dst = src_db(region), MAIN_DB[region]
    if not src.exists():
        sys.exit(f"[migrate] {src} 없음")
    if not dst.exists():
        sys.exit(f"[migrate] {dst} 없음")

    # bf 컬럼에서 키 + KMA 기상만 추린다 (출현 순서 유지).
    with sqlite3.connect(src) as c:
        src_cols = [r[1] for r in c.execute(f"PRAGMA table_info({SRC_TABLE})")]
        n_rows = c.execute(f"SELECT COUNT(*) FROM {SRC_TABLE}").fetchone()[0]
        n_base = c.execute(f"SELECT COUNT(DISTINCT base) FROM {SRC_TABLE}").fetchone()[0]
    weather = [x for x in src_cols if x not in KEY_COLS and is_kma_weather(x)]
    keep = KEY_COLS + weather
    dropped = [x for x in src_cols if x not in keep]

    print(f"[migrate:{region}] {src.name}.{SRC_TABLE} -> {dst.name}.{DST_TABLE}")
    print(f"  소스: {n_rows:,}행 / {n_base} base")
    print(f"  유지 {len(keep)}컬럼 = 키 {len(KEY_COLS)} + KMA 기상 {len(weather)}")
    print(f"  제외 {len(dropped)}컬럼: {dropped}")

    with sqlite3.connect(dst) as c:
        existing = {r[0] for r in c.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        print(f"  본 DB 기존 테이블: {sorted(existing)}")

    if dry_run:
        print("  [dry-run] 변경 없음")
        return

    bak = dst.with_suffix(dst.suffix + f".bak_{datetime.now():%Y%m%d_%H%M%S}")
    shutil.copy2(dst, bak)
    print(f"  백업: {bak.name}")

    col_sql = ", ".join(f'"{x}"' for x in keep)
    with sqlite3.connect(dst) as c:
        c.execute(f"ATTACH DATABASE '{src}' AS bf")
        c.execute(f"DROP TABLE IF EXISTS {DST_TABLE}")
        c.execute(
            f"CREATE TABLE {DST_TABLE} AS "
            f"SELECT {col_sql} FROM bf.{SRC_TABLE}"
        )
        c.execute(
            f"CREATE UNIQUE INDEX idx_{DST_TABLE}_base_ts "
            f"ON {DST_TABLE}(base, timestamp)"
        )
        # 기존 forecast_runs(중복) 폐기
        had_old = c.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (SRC_TABLE,)).fetchone()
        if had_old:
            old_n = c.execute(f"SELECT COUNT(*) FROM {SRC_TABLE}").fetchone()[0]
            c.execute(f"DROP TABLE {SRC_TABLE}")
            print(f"  기존 {SRC_TABLE}({old_n}행) 폐기")
        c.execute("DETACH DATABASE bf")

        got = c.execute(f"SELECT COUNT(*), COUNT(DISTINCT base) FROM {DST_TABLE}").fetchone()
        ncol = len(c.execute(f"PRAGMA table_info({DST_TABLE})").fetchall())
    print(f"  완료: {DST_TABLE} = {got[0]:,}행 / {got[1]} base / {ncol}컬럼")


def main() -> None:
    p = argparse.ArgumentParser(description="bf_*.db -> 본 DB forecast_horizon 통합")
    p.add_argument("--region", choices=["land", "jeju"], required=True)
    p.add_argument("--dry-run", action="store_true", help="계획만 출력, 변경 없음")
    a = p.parse_args()
    migrate(a.region, a.dry_run)


if __name__ == "__main__":
    main()

"""
collect_forecast_runs.py -- 12 UTC 발표를 horizon-tagged 로 forecast_runs 테이블에 적재.

배경 (2026-06-11 설계)
기존 forecast 테이블은 timestamp 단일키 + freshest-wins UPSERT 라 "이 행이 어느
발표(몇 일 지평)에서 왔는지"가 소실된다.  지평별 백테스트/평가를 위해 12 UTC
(21 KST 발표, 가용 ~00:10 KST) 발표 하나만 골라, 발표(base)별 윈도우 전체를
(base, timestamp) 복합키로 별도 테이블 `forecast_runs` 에 누적한다.
12 UTC 를 고른 이유: day-aligned 커버리지가 발표 중 최적 (D+1~D+5 전부 1h,
육지 D+12 가 21시까지 -- 22·23시만 결손으로 보간 한계 4h 안).

방침
- 기존 수집기(collect_data_jeju / collect_data_land)는 일절 수정하지 않는다.
  build(save=False) 로 단일 base 의 wide 를 메모리로 받아 이 모듈이 자기 테이블에만
  쓴다.  기존 forecast(freshest) / historical 테이블과 서빙 경로는 영향 없음.
- horizon_d 컬럼을 함께 저장: horizon_d = date(timestamp) - date(base KST 발표일).
  collection_window 가 발표 다음 자정부터 day-aligned 라 D+1..D+N 정수로 떨어진다.
  (base 만으로 파생 가능하지만 SQL 조회 편의를 위해 물리 컬럼으로 둔다.)
- 윈도우 길이 기본값은 운영 cron 과 동일: 제주 7일(D+5 KIMR 1h + D+7 KIMG 3h),
  육지 12일(KIMG, D+6 정오까지 1h / 이후 3h, D+12 의 22~23시는 lead 한계로 결손).
- 같은 base 재실행 시 (base, timestamp) UPSERT 라 idempotent.  --backfill 은 이미
  행이 있는 base 를 통째로 건너뛴다(resume-skip).  부분 수집된 base(쿼터 소진 등)를
  다시 받으려면 --force 또는 --base YYYYMMDD --force.
  정상 행수: 제주 144 (24x5 + 16 + 8), 육지 184 (144 + 8x5).
- API 호출량(base 당): 제주 ~440회, 육지 ~925회 (KMA API Hub 일 한도 감안해
  --backfill 크기를 정할 것).

임시 DB 워크플로 (--out / --merge)
백필을 본 DB 와 분리해 받고 싶으면 --out NAME 으로 data/<NAME>_<region>.db 에
적재한 뒤, 검증 후 --merge NAME 으로 본 DB 의 forecast_runs 에 병합한다.
forecast_runs 는 어차피 독립 테이블이라 본 DB 에 바로 적재해도 기존
forecast/historical 과 섞이지 않지만, 백필 검증 전 격리용으로 제공.

사용 예
    python core/collect_forecast_runs.py                        # 최신 12z, 제주+육지
    python core/collect_forecast_runs.py --region jeju          # 제주만
    python core/collect_forecast_runs.py --base 20260610        # 2026-06-10 의 12z 발표
    python core/collect_forecast_runs.py --backfill 30          # 과거 30일치 12z (resume-skip)
    python core/collect_forecast_runs.py --backfill 10 --out bf # data/bf_{jeju,land}.db 에 적재
    python core/collect_forecast_runs.py --merge bf             # bf_*.db -> 본 DB 병합
    python core/collect_forecast_runs.py --days 2               # 윈도우 2일로 축소 (테스트)
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

CORE = Path(__file__).resolve().parent
if str(CORE) not in sys.path:
    sys.path.insert(0, str(CORE))

import collect_data_jeju as cj
import collect_data_land as cl
from _common import PUBLISH_DELAY_HOURS

KST = ZoneInfo("Asia/Seoul")
UTC = timezone.utc

RUNS_TABLE = "forecast_runs"
DATA_DIR = cj.DEFAULT_DB.parent

# 권역별 본 DB 와 기본 윈도우 길이 (운영 cron 의 12z 실행과 동일).
REGIONS: dict[str, dict] = {
    "jeju": {"db": cj.DEFAULT_DB, "days": 7},
    "land": {"db": cl.DEFAULT_DB, "days": 12},
}


# ── 발표(base) 선택 ──────────────────────────────────────────────────────
def latest_12z(now_utc: datetime | None = None) -> datetime:
    """공개 지연을 감안한 가장 최근 가용 12 UTC 발표."""
    if now_utc is None:
        now_utc = datetime.now(tz=UTC)
    cutoff = now_utc - timedelta(hours=PUBLISH_DELAY_HOURS)
    cand = cutoff.replace(hour=12, minute=0, second=0, microsecond=0)
    if cand > cutoff:
        cand -= timedelta(days=1)
    return cand


def backfill_12z_bases(n_days: int) -> list[datetime]:
    """가장 최근 가용 12z 부터 거꾸로 N 개 (오래된 것부터 적재하도록 reverse)."""
    latest = latest_12z()
    return [latest - timedelta(days=k) for k in range(n_days)][::-1]


# ── DB ───────────────────────────────────────────────────────────────────
def region_db(region: str, out: str | None) -> Path:
    """--out NAME 이면 data/<NAME>_<region>.db, 아니면 권역 본 DB."""
    if out:
        return DATA_DIR / f"{out}_{region}.db"
    return REGIONS[region]["db"]


def existing_base_counts(db_path: Path) -> dict[str, int]:
    """forecast_runs 에 이미 있는 base 별 행 수.  테이블/파일 없으면 빈 dict."""
    if not db_path.exists() or db_path.stat().st_size == 0:
        return {}
    with sqlite3.connect(db_path) as c:
        try:
            rows = c.execute(
                f"SELECT base, COUNT(*) FROM {RUNS_TABLE} GROUP BY base"
            ).fetchall()
        except sqlite3.OperationalError:
            return {}
    return dict(rows)


def _upsert_df(df: pd.DataFrame, db_path: Path) -> int:
    """base + horizon_d 가 이미 붙은 DF 를 forecast_runs 에 (base,timestamp) UPSERT.

    collect_data_jeju.upsert_wide_to 와 같은 temp-table / INSERT OR REPLACE 패턴이되
    키가 복합.  본 테이블이 없으면 생성, 새 컬럼은 ALTER 로 확장.
    """
    if df.empty:
        return 0
    db_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = f"_tmp_{RUNS_TABLE}"
    with sqlite3.connect(db_path) as c:
        df.to_sql(tmp, c, if_exists="replace", index=True)

        existing = {r[1] for r in c.execute(f"PRAGMA table_info({RUNS_TABLE})").fetchall()}
        tmp_cols = [r[1] for r in c.execute(f"PRAGMA table_info({tmp})").fetchall()]
        if not existing:
            c.execute(f"CREATE TABLE {RUNS_TABLE} AS SELECT * FROM {tmp} WHERE 0")
            existing = set(tmp_cols)
        for col in tmp_cols:
            if col not in existing:
                c.execute(f'ALTER TABLE {RUNS_TABLE} ADD COLUMN "{col}"')

        c.execute(
            f"CREATE UNIQUE INDEX IF NOT EXISTS idx_{RUNS_TABLE}_base_ts "
            f"ON {RUNS_TABLE}(base, timestamp)"
        )

        full_cols = [r[1] for r in c.execute(f"PRAGMA table_info({RUNS_TABLE})").fetchall()]
        select_exprs = [f'"{col}"' if col in tmp_cols else "NULL" for col in full_cols]
        col_list = ", ".join(f'"{col}"' for col in full_cols)
        c.execute(
            f"INSERT OR REPLACE INTO {RUNS_TABLE} ({col_list}) "
            f"SELECT {', '.join(select_exprs)} FROM {tmp}"
        )
        n = c.execute("SELECT changes()").fetchone()[0]
        c.execute(f"DROP TABLE {tmp}")
    return n


def upsert_runs(wide: pd.DataFrame, base_utc: datetime, db_path: Path) -> int:
    """wide(단일 base)에 base + horizon_d 태그를 붙여 forecast_runs 에 UPSERT."""
    if wide.empty:
        return 0
    base_kst = base_utc.astimezone(KST)
    base_date = base_kst.date()

    df = wide.copy()
    ts_dates = pd.to_datetime(df.index, format="%Y-%m-%d %H:%M:%S").date
    df.insert(0, "horizon_d", [(d - base_date).days for d in ts_dates])
    df.insert(0, "base", base_kst.strftime("%Y-%m-%d %H:%M:%S"))
    df.index.name = "timestamp"
    return _upsert_df(df, db_path)


def merge_runs(src_db: Path, dst_db: Path) -> int:
    """src 의 forecast_runs 전체를 dst 의 forecast_runs 에 (base,timestamp) UPSERT."""
    if not src_db.exists():
        print(f"  [merge] {src_db.name} 없음 -- skip")
        return 0
    with sqlite3.connect(src_db) as c:
        try:
            df = pd.read_sql(f"SELECT * FROM {RUNS_TABLE}", c)
        except Exception as e:
            print(f"  [merge] {src_db.name} 읽기 실패: {e} -- skip")
            return 0
    if df.empty:
        print(f"  [merge] {src_db.name} 비어있음 -- skip")
        return 0
    df = df.set_index("timestamp")
    n = _upsert_df(df, dst_db)
    print(
        f"  [merge] {src_db.name} -> {dst_db.name}::{RUNS_TABLE}  "
        f"{n:,} rows ({df['base'].nunique()} bases)"
    )
    return n


# ── fetch (기존 빌더 재사용, save=False) ─────────────────────────────────
def disable_kpx() -> None:
    """KPX *_da (smp_*_da / *_est_demand_da) 호출을 끈다 -- 기상청(KIMR/KIMG)만 수집.

    백필 시 KPX(data.go.kr) 429 회피용.  기존 수집기 무수정 원칙대로 이 프로세스
    안에서만 패치: 육지는 _join_da 를 통째로 no-op, 제주는 fetch_kpx_est 가 빈 DF.
    빠진 *_da 컬럼은 partial-upsert 라 기존 행 값을 덮지 않는다.
    """
    cl._join_da = lambda wide, db_path: wide
    cj.kpx.fetch_kpx_est = lambda s, e: pd.DataFrame()
    print("[collect_forecast_runs] --no-kpx: *_da 호출 비활성 (기상청만)")


def fetch_one(region: str, base_utc: datetime, days: int) -> pd.DataFrame:
    """단일 base 의 forecast wide 를 메모리로 반환 (기존 forecast 테이블엔 안 씀)."""
    if region == "jeju":
        return cj.build(base=base_utc, save=False, forecast_days=days)
    return cl.build_forecast(
        base=base_utc, forecast_days=days, save=False, db_path=cl.DEFAULT_DB,
    )


def run_region(
    region: str, bases: list[datetime], days: int, force: bool, db_path: Path,
) -> int:
    have = existing_base_counts(db_path)
    total = 0
    for i, b in enumerate(bases, 1):
        base_str = b.astimezone(KST).strftime("%Y-%m-%d %H:%M:%S")
        label = f"[runs:{region}] base {b.strftime('%Y%m%d %HZ')} ({base_str} KST)"
        if not force and have.get(base_str, 0) > 0:
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
        n = upsert_runs(wide, b, db_path)
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


# ── CLI ──────────────────────────────────────────────────────────────────
def main() -> None:
    p = argparse.ArgumentParser(
        description=(
            "12 UTC 발표를 horizon-tagged 로 forecast_runs 테이블에 적재 "
            "(키 = base + timestamp).  기존 forecast/historical 은 건드리지 않음."
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
        help="data/<NAME>_<region>.db 의 forecast_runs 를 본 DB 에 병합 (fetch 없음)",
    )
    p.add_argument(
        "--region", choices=["jeju", "land", "both"], default="both",
        help="대상 권역 (default both)",
    )
    p.add_argument(
        "--days", type=int, default=None, metavar="N",
        help="윈도우 길이 override (기본: 제주 7 / 육지 12)",
    )
    p.add_argument(
        "--out", metavar="NAME", default=None,
        help="본 DB 대신 data/<NAME>_<region>.db 에 적재 (백필 격리용)",
    )
    p.add_argument(
        "--force", action="store_true",
        help="forecast_runs 에 이미 행이 있는 base 도 다시 받는다",
    )
    p.add_argument(
        "--no-kpx", action="store_true",
        help="KPX *_da 호출 생략 -- 기상청(KIMR/KIMG)만 받는다 (backfill 429 회피)",
    )
    args = p.parse_args()

    if args.no_kpx:
        disable_kpx()

    regions = ["jeju", "land"] if args.region == "both" else [args.region]

    if args.merge:
        print(f"[collect_forecast_runs] merge '{args.merge}' -> main DBs")
        for region in regions:
            merge_runs(region_db(region, args.merge), REGIONS[region]["db"])
        return

    if args.base:
        bases = [datetime.strptime(args.base, "%Y%m%d").replace(hour=12, tzinfo=UTC)]
    elif args.backfill:
        bases = backfill_12z_bases(args.backfill)
    else:
        bases = [latest_12z()]

    print(
        f"[collect_forecast_runs] regions={regions}  bases={len(bases)} "
        f"({bases[0].strftime('%Y%m%d')}~{bases[-1].strftime('%Y%m%d')} 12Z)  "
        f"out={'main DB' if not args.out else args.out + '_<region>.db'}  "
        f"table='{RUNS_TABLE}' key=(base,timestamp)"
    )

    t0 = time.time()
    for region in regions:
        days = args.days if args.days is not None else REGIONS[region]["days"]
        db_path = region_db(region, args.out)
        n = run_region(region, bases, days, args.force, db_path)
        print(f"\n[runs:{region}] total UPSERT {n:,} rows -> {db_path.name}")
    print(f"\n[collect_forecast_runs] done in {(time.time()-t0)/60:.1f}m")


if __name__ == "__main__":
    main()

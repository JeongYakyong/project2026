"""
backfill_jeju_forecast.py -- 제주 forecast_horizon 백필 전용 (KIMR / KIMG 2-패스 분리).

왜 따로 만드나 (2026-06-16)
collect_forecast_new 의 제주 경로는 base 마다 KIMR→KIMG 를 번갈아 호출한다.  장지평
백필(179 base)에서 이 교대가 KMA apihub 에 부담을 줘 KIMR 504(Gateway Timeout)가
잦았다.  또 KIMR 이 펑크 나도 KIMG 가 temp/일사를 채워 행이 써지는 바람에, temp* 만
보는 base_complete 가 그 base 를 "완전"으로 오판해 재실행에도 KIMR 전용 컬럼
(cape/cinn/hpbl/tcog/tcoh/temp_skin)이 영영 빈 채로 남았다.

이 파일은 두 소스를 **완전히 분리된 패스**로 돌린다:
  ① KIMR 패스: 모든 base 의 KIMR 만 순차로 받아 적재 (KIMG 호출 없음).
  ② KIMG 패스: 모든 base 의 KIMG 만 받아 적재.
교대가 사라져 apihub 부담이 줄고, **KIMR 만 따로 재취득**(--kimr-only)이 가능해진다.

병합 의미 (컬럼 클래스별 부분 upsert, (base,timestamp) ON CONFLICT)
  - KIMR 컬럼(temp/wind/gust/reh/rainfall D+1~5 + KIMR 전용)  : "새 값 우선"
    = COALESCE(excluded, 기존).  재취득 시 KIMR 값으로 덮고, KIMR 이 없는 D+6~7 행은
      기존(KIMG)을 보존.
  - KIMG 전용(radiation_*/ *_cloud_*)                         : "새 값 우선" (덮어쓰기).
  - KIMG 겹침(temp/wind/gust/reh/rainfall)                    : "기존 우선"
    = COALESCE(기존, excluded).  D+1~5 에 이미 있는 KIMR 값을 KIMG 가 덮지 않고,
      KIMR 이 없는 D+6~7(기존 NULL)만 KIMG 가 채운다 = combine_first(KIMR 우선) 동치.
  -> 두 패스의 실행 순서와 무관하게 KIMR 우선이 보장된다.

완결성 sentinel (펑크 감지)
  - KIMR : temp_skin_<지점> (KIMR 전용, D+5 꼬리 NULL 회피 위해 D+1~4 만 검사).
  - KIMG : total_cloud_<지점> (KIMG 전용 + clip 의 zero-fill 대상 아님 -- radiation 은
           야간 0 으로 채워져 sentinel 부적합).

KIMR 요청 경량화: KIMR 은 lead 한계 D+5(120h)까지만 데이터가 있어 7일 윈도우의
ef=3,170,1(없는 데이터까지) 요청이 무겁다.  KIMR 패스는 윈도우를 D+5 로 잡아
phantom 구간을 빼고 받는다(KIMG_DAYS=7 은 KIMG 패스에서만).

사용 예
    python core/backfill_jeju_forecast.py --backfill 179            # KIMR 패스 -> KIMG 패스
    python core/backfill_jeju_forecast.py --backfill 179 --kimr-only   # KIMR 만 (펑크 보충)
    python core/backfill_jeju_forecast.py --backfill 179 --kimg-only   # KIMG 만
    python core/backfill_jeju_forecast.py --base 20260105               # 단일 발표(둘 다)
    python core/backfill_jeju_forecast.py --verify                      # base 별 KIMR/KIMG 완결성
    python core/backfill_jeju_forecast.py --merge bf                    # bf_jeju.db -> input_data_jeju.db
    python core/backfill_jeju_forecast.py --backfill 30 --point-workers 2  # KIMG 지점 2 동시(기본 1)
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

CORE = Path(__file__).resolve().parent
if str(CORE) not in sys.path:
    sys.path.insert(0, str(CORE))

import collect_data_jeju as cj
import collect_forecast_runs as cfr
import api_fetchers_jeju as ci
import _common as ckg
import postprocess as pp

KST = cfr.KST
UTC = cfr.UTC
RUNS_TABLE = cfr.RUNS_TABLE  # forecast_horizon

# KIMR 은 lead 한계 D+5(120h)까지만 -- phantom 요청 제거.  KIMG 는 D+7 까지.
KIMR_DAYS = 5
KIMG_DAYS = 7

_SUFFIXES = list(ci.POINT_SUFFIX.values())          # ['west','east','south']
KIMR_SENTINELS = [f"temp_skin_{s}" for s in _SUFFIXES]
KIMG_SENTINELS = [f"total_cloud_{s}" for s in _SUFFIXES]
# KIMG 전용(겹치지 않는) 컬럼 prefix -- 부분 upsert 에서 "새 값 우선".
KIMG_EXCLUSIVE = ("radiation_", "total_cloud_", "midlow_cloud_")


# ── wide 빌더 (단일 base, 소스별) ────────────────────────────────────────
def _normalize_index(wide: pd.DataFrame) -> pd.DataFrame:
    """index(fcst_datetime "%Y-%m-%d %H:%M") -> forecast_horizon 표준 초단위 문자열."""
    wide = wide.sort_index()
    wide.index = pd.to_datetime(wide.index, format="%Y-%m-%d %H:%M").strftime(
        "%Y-%m-%d %H:%M:%S"
    )
    wide.index.name = "timestamp"
    return wide


def kimr_wide_one(base: datetime) -> pd.DataFrame:
    """단일 base 의 KIMR-only wide (지점별 kimr_one_point concat).  KIMG 호출 없음."""
    with cj.forecast_days_override(KIMR_DAYS):
        window_start, window_end = cj._window_for([base])
        kimr_long = cj.fetch_kimr_long([base], workers=1)
    if kimr_long.empty:
        return pd.DataFrame()
    parts = []
    for point, suffix in ci.POINT_SUFFIX.items():
        p = ci.kimr_one_point(kimr_long, point, suffix, window_start, window_end)
        if not p.empty:
            parts.append(p)
    if not parts:
        return pd.DataFrame()
    wide = pd.concat(parts, axis=1)
    wide = _normalize_index(wide)
    return pp.clip_ranges(wide)


def kimg_wide_one(base: datetime, point_workers: int) -> pd.DataFrame:
    """단일 base 의 KIMG-only wide (지점별 kimg_one_point + radiation_<지점>).  KIMR 호출 없음."""
    with cj.forecast_days_override(KIMG_DAYS):
        window_start, window_end = cj._window_for([base])
        kimg_long = cj.fetch_kimg_long([base], point_workers=point_workers)
    if kimg_long.empty:
        return pd.DataFrame()
    start_s = window_start.strftime("%Y-%m-%d %H:%M")
    end_s = window_end.strftime("%Y-%m-%d %H:%M")
    parts = []
    for point, suffix in ci.POINT_SUFFIX.items():
        p = ci.kimg_one_point(kimg_long, point, suffix, window_start, window_end)
        sub = kimg_long[
            (kimg_long["category"] == "SOLAR_RAD") &
            (kimg_long["point_name"] == point) &
            (kimg_long["fcst_datetime"] >= start_s) &
            (kimg_long["fcst_datetime"] < end_s)
        ]
        rad = ci.kimg_solar(sub, suffix)
        if not rad.empty:
            p = rad.to_frame() if p.empty else p.join(rad, how="outer")
        if not p.empty:
            parts.append(p)
    if not parts:
        return pd.DataFrame()
    wide = pd.concat(parts, axis=1)
    wide = _normalize_index(wide)
    return pp.clip_ranges(wide)


# ── 부분 upsert ((base,timestamp) ON CONFLICT, 컬럼 클래스별 병합) ─────────
def _upsert_partial(
    wide: pd.DataFrame, base: datetime, db_path: Path, old_wins: tuple[str, ...] = (),
) -> int:
    """wide 에 base+horizon_d 태그를 붙여 forecast_horizon 에 (base,timestamp) UPSERT.

    old_wins 에 든 컬럼은 "기존 우선"(COALESCE(기존, excluded)), 나머지는 "새 값 우선"
    (COALESCE(excluded, 기존)).  KIMR 패스는 old_wins=() (전부 새 값 우선), KIMG 패스는
    겹침 컬럼을 old_wins 로 넘겨 KIMR D+1~5 값을 보존한다.
    """
    if wide.empty:
        return 0
    base_kst = base.astimezone(KST)
    df = wide.copy()
    ts_dates = pd.to_datetime(df.index, format="%Y-%m-%d %H:%M:%S").date
    df.insert(0, "horizon_d", [(d - base_kst.date()).days for d in ts_dates])
    df.insert(0, "base", base_kst.strftime("%Y-%m-%d %H:%M:%S"))
    df.index.name = "timestamp"

    old = set(old_wins)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = "_tmp_bf_jeju"
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
        data_cols = [col for col in tmp_cols if col not in ("base", "timestamp")]
        set_exprs = []
        for col in data_cols:
            if col in old:
                set_exprs.append(f'"{col}"=COALESCE({RUNS_TABLE}."{col}", excluded."{col}")')
            else:
                set_exprs.append(f'"{col}"=COALESCE(excluded."{col}", {RUNS_TABLE}."{col}")')
        col_list = ", ".join(f'"{col}"' for col in tmp_cols)
        # "WHERE true" = INSERT...SELECT...ON CONFLICT 파서 모호성 회피용 SQLite 관용구.
        c.execute(
            f"INSERT INTO {RUNS_TABLE} ({col_list}) SELECT {col_list} FROM {tmp} WHERE true "
            f"ON CONFLICT(base, timestamp) DO UPDATE SET {', '.join(set_exprs)}"
        )
        n = c.execute("SELECT changes()").fetchone()[0]
        c.execute(f"DROP TABLE {tmp}")
    return n


# ── 완결성 (sentinel 기반) ───────────────────────────────────────────────
def _expected_ts(base: datetime, days: int, max_horizon: int | None = None) -> set[str]:
    """그 base 가 만들 timestamp 집합(초단위).  max_horizon 이 있으면 D+max_horizon 까지만."""
    base_kst = base.astimezone(KST)
    with cj.forecast_days_override(days):
        hfs = list(ckg.collection_hf_range(base))
    out = set()
    for h in hfs:
        ts = base_kst + timedelta(hours=h)
        if max_horizon is not None and (ts.date() - base_kst.date()).days > max_horizon:
            continue
        out.add(ts.strftime("%Y-%m-%d %H:%M:%S"))
    return out


def _complete(
    db_path: Path, base: datetime, days: int, sentinels: list[str],
    max_horizon: int | None = None,
) -> bool:
    """기대 timestamp 전부가 각 sentinel 컬럼에서 non-null 이면 완전."""
    if not db_path.exists() or db_path.stat().st_size == 0:
        return False
    base_str = base.astimezone(KST).strftime("%Y-%m-%d %H:%M:%S")
    exp = _expected_ts(base, days, max_horizon)
    if not exp:
        return False
    with sqlite3.connect(db_path) as c:
        try:
            cols = [r[1] for r in c.execute(f"PRAGMA table_info({RUNS_TABLE})").fetchall()]
        except sqlite3.OperationalError:
            return False
        for s in sentinels:
            if s not in cols:
                return False
            got = {r[0] for r in c.execute(
                f'SELECT timestamp FROM {RUNS_TABLE} WHERE base=? AND "{s}" IS NOT NULL',
                (base_str,),
            ).fetchall()}
            if not exp.issubset(got):
                return False
    return True


def kimr_complete(db_path: Path, base: datetime) -> bool:
    # D+5 꼬리(21시 이후)는 KIMR lead 한계로 정상 NULL -- D+1~4 만 검사.
    return _complete(db_path, base, KIMR_DAYS, KIMR_SENTINELS, max_horizon=4)


def kimg_complete(db_path: Path, base: datetime) -> bool:
    return _complete(db_path, base, KIMG_DAYS, KIMG_SENTINELS)


# ── 패스 ─────────────────────────────────────────────────────────────────
def run_kimr_pass(bases: list[datetime], db_path: Path, force: bool) -> int:
    print(f"\n{'#'*70}\n# KIMR 패스 ({len(bases)} bases, 순차, 윈도우 D+{KIMR_DAYS})\n{'#'*70}")
    total = 0
    for i, b in enumerate(bases, 1):
        label = f"[KIMR] {b.strftime('%Y%m%d %HZ')} ({i}/{len(bases)})"
        if not force and kimr_complete(db_path, b):
            print(f"{label} -- skip (완전; --force 로 재취득)")
            continue
        print(f"\n{label}")
        try:
            wide = kimr_wide_one(b)
        except Exception as e:
            print(f"{label} -- [WARN] fetch 실패: {e} (skip)")
            continue
        if wide.empty:
            print(f"{label} -- [WARN] KIMR 결손 (3 지점 전부 실패?) -- 나중에 --kimr-only 재시도")
            continue
        n = _upsert_partial(wide, b, db_path, old_wins=())
        total += n
        ok = "완전" if kimr_complete(db_path, b) else "여전히 불완전(일부 지점 펑크)"
        print(f"{label} -- UPSERT {n:,} rows ({ok})")
    return total


def run_kimg_pass(bases: list[datetime], db_path: Path, force: bool, point_workers: int) -> int:
    print(f"\n{'#'*70}\n# KIMG 패스 ({len(bases)} bases, point_workers={point_workers}, "
          f"윈도우 D+{KIMG_DAYS})\n{'#'*70}")
    total = 0
    for i, b in enumerate(bases, 1):
        label = f"[KIMG] {b.strftime('%Y%m%d %HZ')} ({i}/{len(bases)})"
        if not force and kimg_complete(db_path, b):
            print(f"{label} -- skip (완전; --force 로 재취득)")
            continue
        print(f"\n{label}")
        try:
            wide = kimg_wide_one(b, point_workers)
        except Exception as e:
            print(f"{label} -- [WARN] fetch 실패: {e} (skip)")
            continue
        if wide.empty:
            print(f"{label} -- [WARN] KIMG 결손 -- skip")
            continue
        # 겹침 컬럼(KIMG 전용이 아닌 것)은 "기존 우선"으로 KIMR D+1~5 보존.
        old_wins = tuple(c for c in wide.columns if not c.startswith(KIMG_EXCLUSIVE))
        n = _upsert_partial(wide, b, db_path, old_wins=old_wins)
        total += n
        ok = "완전" if kimg_complete(db_path, b) else "여전히 불완전"
        print(f"{label} -- UPSERT {n:,} rows ({ok})")
    return total


# ── verify ───────────────────────────────────────────────────────────────
def _bases_in_db(db_path: Path) -> list[datetime]:
    """DB 의 distinct base(KST) -> 12z UTC datetime 리스트 (오래된 순)."""
    if not db_path.exists() or db_path.stat().st_size == 0:
        return []
    with sqlite3.connect(db_path) as c:
        try:
            rows = [r[0] for r in c.execute(
                f"SELECT DISTINCT base FROM {RUNS_TABLE} ORDER BY base").fetchall()]
        except sqlite3.OperationalError:
            return []
    out = []
    for s in rows:
        d = datetime.strptime(s[:10], "%Y-%m-%d")
        out.append(d.replace(hour=12, tzinfo=UTC))  # KST 21시 = 12 UTC 같은 날짜
    return out


def verify(db_path: Path) -> list[datetime]:
    """DB 에 있는 base 별 KIMR/KIMG 완결성 출력.  불완전 base(UTC) 목록 반환."""
    bases = _bases_in_db(db_path)
    if not bases:
        print(f"[verify] {db_path.name} 에 forecast_horizon base 없음")
        return []
    print(f"[verify] {db_path.name}::{RUNS_TABLE} -- {len(bases)} bases")
    bad = []
    for b in bases:
        kr = kimr_complete(db_path, b)
        kg = kimg_complete(db_path, b)
        if not (kr and kg):
            bad.append(b)
            print(f"  {b.strftime('%Y-%m-%d')}  "
                  f"KIMR={'OK ' if kr else 'MISS'}  KIMG={'OK ' if kg else 'MISS'}")
    if bad:
        kimr_bad = [b for b in bad if not kimr_complete(db_path, b)]
        kimg_bad = [b for b in bad if not kimg_complete(db_path, b)]
        print(f"\n[verify] 불완전 {len(bad)} bases "
              f"(KIMR 펑크 {len(kimr_bad)}, KIMG 펑크 {len(kimg_bad)})")
        print("  재취득 예: python core/backfill_jeju_forecast.py "
              "--backfill <N> --kimr-only   (KIMR 펑크만 KIMG 비용 없이 보충)")
    else:
        print("[verify] 모든 base 완전 (KIMR+KIMG OK)")
    return bad


# ── CLI ──────────────────────────────────────────────────────────────────
def main() -> None:
    p = argparse.ArgumentParser(
        description=(
            "제주 forecast_horizon 백필 (KIMR/KIMG 2-패스 분리).  기본은 bf_jeju.db 에 적재 후 "
            "--merge 로 input_data_jeju.db 에 병합."
        ),
    )
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--base", metavar="YYYYMMDD", help="특정 날짜의 12 UTC 발표")
    mode.add_argument("--backfill", type=int, metavar="N_DAYS", help="과거 N 일치 12z (resume-skip)")
    mode.add_argument("--verify", action="store_true", help="DB 의 base 별 KIMR/KIMG 완결성 검사")
    mode.add_argument("--merge", metavar="NAME",
                      help="data/<NAME>_jeju.db 의 forecast_horizon 를 input_data_jeju.db 에 병합")

    src = p.add_mutually_exclusive_group()
    src.add_argument("--kimr-only", action="store_true", help="KIMR 패스만 (펑크 보충, KIMG 비용 없음)")
    src.add_argument("--kimg-only", action="store_true", help="KIMG 패스만")

    p.add_argument("--out", metavar="NAME", default="bf",
                   help="data/<NAME>_jeju.db 에 적재 (기본 bf -> data/bf_jeju.db).  ''=본 DB")
    p.add_argument("--point-workers", type=int, default=1, metavar="N",
                   help="KIMG 지점 동시 수 (기본 1=순차/가장 안전; 504 안 나면 2까지)")
    p.add_argument("--force", action="store_true", help="완전한 base 도 다시 받는다")
    args = p.parse_args()

    db_path = cfr.region_db("jeju", args.out or None)

    if args.verify:
        verify(db_path)
        return

    if args.merge:
        src_db = cfr.region_db("jeju", args.merge)
        print(f"[merge] {src_db.name} -> {cj.DEFAULT_DB.name}::{RUNS_TABLE}")
        cfr.merge_runs(src_db, cj.DEFAULT_DB)
        return

    if args.base:
        bases = [datetime.strptime(args.base, "%Y%m%d").replace(hour=12, tzinfo=UTC)]
    elif args.backfill:
        bases = cfr.backfill_12z_bases(args.backfill)
    else:
        bases = [cfr.latest_12z()]

    print(f"[backfill_jeju_forecast] {len(bases)} bases "
          f"({bases[0].strftime('%Y%m%d')}~{bases[-1].strftime('%Y%m%d')} 12Z) -> {db_path.name}")

    t0 = time.time()
    if not args.kimg_only:
        run_kimr_pass(bases, db_path, args.force)
    if not args.kimr_only:
        run_kimg_pass(bases, db_path, args.force, args.point_workers)
    print(f"\n[backfill_jeju_forecast] done in {(time.time()-t0)/60:.1f}m -> {db_path}")
    print("  검증: python core/backfill_jeju_forecast.py --verify"
          + (f" --out {args.out}" if args.out else ""))
    print("  병합: python core/backfill_jeju_forecast.py --merge "
          + (args.out or "bf"))


if __name__ == "__main__":
    main()

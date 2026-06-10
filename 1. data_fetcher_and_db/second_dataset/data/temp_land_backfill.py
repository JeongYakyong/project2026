"""
temp_land_backfill.py -- (일회성, 임시) 육지 forecast 의 빠진 reh / rainfall 백필.

배경
  input_data_land.db 의 forecast 테이블을 만들 때 KIMG-land 만 받아 습도(REH)·강수
  컬럼을 빠뜨렸다.  KIMG-land 수집기를 정상화하기 전까지의 *임시 1회* 보충으로,
  KIMR(KIM 지역모델, group=KIMR/nwp=r030)에서 REH + RAIN(conv+strat) 만 받아
  육지 5 지점의 reh_<지점> / rainfall_<지점> 컬럼을 forecast 에 partial-UPSERT 한다.

  이 스크립트는 *한 번 돌리고 버리는* 용도다.  이후 정상 경로는 collect_data_land.py
  를 개조해 KIMG 자료로 reh/rainfall 을 채우는 것이고, 그때도 컬럼명은 동일하게
  (reh_<지점> / rainfall_<지점>) 유지하면 이 백필분과 자연히 이어진다.

설계 (기존 라이브러리는 건드리지 않고 import 만 재사용)
  - 격자 변환 : core/kim_r030_latlon (2).nc 의 lat/lon 격자에서 최단거리 격자점
                (X,Y) 를 찾는다 (= k030_latlon_grid.ipynb 의 검증된 변환기).
                위도/경도 -> KIMR API X/Y.  (제주 Gosan 530,251 등 재현 확인.)
  - fetch     : api_fetchers_jeju.fetch_and_prepare (KIMR 단일 (발표,지점) 호출 +
                윈도우 필터) 를 그대로 사용.  POINTS 만 육지 5 지점 X/Y 로 교체.
  - 발표 선택 : day-ahead 만 (00 UTC = 09 KST).  제주 KIMR day-ahead 와 동일 --
                D-1 09 KST 발표가 입찰마감(D-1 11:00) 전 가용한 가장 fresh 한 발표.
  - long->wide: api_fetchers_jeju.kimr_one_point (day_ahead=True) 로 지점별 wide 를
                만들고 reh_<지점> / rainfall_<지점> 두 컬럼만 추린다.  (rainfall 의
                누적->시간차 diff + freshest 로직을 그 함수가 그대로 처리.)
  - 저장      : postprocess.clip_ranges 적용 후 partial_upsert 로 forecast 에 UPSERT.
                기본은 *이미 forecast 에 있는 timestamp* 만 채운다(--only-existing) --
                KIMR 윈도우 가장자리가 새 희소행을 만들지 않도록.

사용
    python core/temp_land_backfill.py                 # 180일, day-ahead, 기존 행만 채움
    python core/temp_land_backfill.py --days 30       # 최근 30일만
    python core/temp_land_backfill.py --no-save       # dry-run (요약 + 샘플만 출력)
    python core/temp_land_backfill.py --all-issues     # 4발표 모두 freshest (기본은 day-ahead만)
    python core/temp_land_backfill.py --include-new     # forecast 에 없는 timestamp 도 INSERT
"""
from __future__ import annotations

import argparse
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

# 기존 모듈 재사용 (core/ 가 sys.path 에 올라오는 `python core/...` 실행 가정).
import api_fetchers_jeju as kim   # KIMR fetch_and_prepare / collection_window / backfill_bases
import api_fetchers_jeju as ci    # kimr_one_point (long->wide, rain diff+freshest)
import postprocess as pp
from _common import partial_upsert

_CORE_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _CORE_DIR.parent
DEFAULT_DB = _REPO_ROOT / "data" / "input_data_land.db"
NC_GRID = _CORE_DIR / "kim_r030_latlon (2).nc"

FORECAST_TABLE = "forecast"

# 육지 5 지점 (collect_data_land / api_fetchers_land 와 동일 lat/lon + suffix).
# X/Y 는 런타임에 NC 격자 최단거리로 채운다 (아래 build_land_points).
LAND_POINTS_LATLON = [
    {"name": "Daegwallyeong(100)", "suffix": "daegwallyeong", "lat": 37.6772, "lon": 128.7185},
    {"name": "Wonju(114)",         "suffix": "wonju",         "lat": 37.3376, "lon": 127.9466},
    {"name": "Seosan(129)",        "suffix": "seosan",        "lat": 36.7766, "lon": 126.4939},
    {"name": "Pohang(138)",        "suffix": "pohang",        "lat": 36.0327, "lon": 129.3799},
    {"name": "Yeonggwang(252)",    "suffix": "yeonggwang",    "lat": 35.2807, "lon": 126.4750},
]

# KIMR fetch 병렬 수 (제주 backfill workers=6 과 동일 취지).
MAX_WORKERS = 6


# ── 격자 변환 (NC 최단거리; k030_latlon_grid.ipynb 검증 로직) ──────────────
def build_land_points() -> list[dict]:
    """LAND_POINTS_LATLON 각 지점의 KIMR API X/Y 를 NC 격자에서 찾아 채운다.

    kim_r030_latlon nc 의 (Y,X) 2차원 lat/lon 격자에서 cos(lat) 보정 유클리드 거리
    최단점을 고르고, API 는 1-기반이라 +1.  (제주 Gosan(33.3474,126.18602)->530,251 등
    기존 api_fetchers_jeju.POINTS 값을 재현함을 확인했다.)
    """
    import xarray as xr  # 무거운 의존성이라 함수 안에서 lazy import.

    if not NC_GRID.exists():
        raise FileNotFoundError(f"KIMR 격자 파일 없음: {NC_GRID}")
    ds = xr.open_dataset(NC_GRID)
    lats = ds["lat"].values
    lons = ds["lon"].values
    ds.close()

    def find_xy(tlat: float, tlon: float) -> tuple[int, int]:
        cos_lat = np.cos(np.radians(tlat))
        dist_sq = (lats - tlat) ** 2 + ((lons - tlon) * cos_lat) ** 2
        yi, xi = np.unravel_index(np.argmin(dist_sq, axis=None), dist_sq.shape)
        return int(xi) + 1, int(yi) + 1

    pts: list[dict] = []
    for p in LAND_POINTS_LATLON:
        x, y = find_xy(p["lat"], p["lon"])
        pts.append({**p, "x": x, "y": y})
        print(f"  grid {p['name']:<20} ({p['lat']},{p['lon']}) -> X={x} Y={y}")
    return pts


# ── 발표(base) 선택 ────────────────────────────────────────────────────
def pick_bases(n_days: int, day_ahead_only: bool) -> list[datetime]:
    """최근 n_days 의 KIMR 발표.  day_ahead_only 면 00 UTC(09 KST) 발표만.

    kim.backfill_bases 는 latest_published_base 부터 6h 간격으로 거꾸로 n_days 치를
    오래된->최신 순으로 준다.  day-ahead 는 그중 hour==0(UTC) 만 남긴다.
    """
    now_kst = datetime.now(tz=kim.KST)
    bases = kim.backfill_bases(n_days, now_kst)
    if day_ahead_only:
        bases = [b for b in bases if b.hour == 0]
    return bases


# ── KIMR fetch -> long DF (REH / RAIN 만) ───────────────────────────────
_WANT_CATS = {"REH", "RAIN_CONV", "RAIN_STRAT"}


def fetch_kimr_land_long(bases: list[datetime], points: list[dict]) -> pd.DataFrame:
    """bases x points 에 대해 KIMR 호출 -> REH/RAIN 만 추린 long DF.

    fetch_and_prepare 는 네트워크 I/O 만 하므로 (base,point) 페어를 워커로 fanout.
    실패 페어는 [WARN] 후 건너뛴다 (제주 fetch_kimr_long 병렬 모드와 동일).
    출력 컬럼: base_datetime / point_name / fcst_datetime / category / fcst_value.
    """
    collected_at = datetime.now(kim.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    tasks = [(b, pt) for b in bases for pt in points]
    rows: list[tuple] = []
    n_ok = n_fail = 0

    kim.warmup()
    print(f"  KIMR-land: {len(tasks)} (base,point) pairs, workers={MAX_WORKERS}")

    def _one(base: datetime, pt: dict):
        return base, pt, kim.fetch_and_prepare(base, pt, collected_at)

    t0 = time.time()
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        fut_to_task = {ex.submit(_one, b, pt): (b, pt) for b, pt in tasks}
        done = 0
        for fut in as_completed(fut_to_task):
            base, pt = fut_to_task[fut]
            done += 1
            try:
                _, _, (pt_rows, *_rest) = fut.result()
            except Exception as e:
                print(f"  [WARN] KIMR {base.strftime('%Y%m%d%H')}UTC {pt['name']}: {e}")
                n_fail += 1
                continue
            # pt_rows: (base_dt, fcst_dt, point_name, x, y, category, value, collected_at)
            for r in pt_rows:
                if r[5] in _WANT_CATS:
                    rows.append(r)
            n_ok += 1
            if done % 50 == 0 or done == len(tasks):
                print(
                    f"    progress {done}/{len(tasks)}  ok={n_ok} fail={n_fail}  "
                    f"({time.time()-t0:.0f}s)"
                )

    if not rows:
        return pd.DataFrame(
            columns=["base_datetime", "point_name", "fcst_datetime", "category", "fcst_value"]
        )
    df = pd.DataFrame(rows, columns=[
        "base_datetime", "fcst_datetime", "point_name", "x", "y",
        "category", "fcst_value", "collected_at",
    ])
    df["fcst_value"] = pd.to_numeric(df["fcst_value"], errors="coerce")
    return df[["base_datetime", "point_name", "fcst_datetime", "category", "fcst_value"]]


# ── long -> wide (reh / rainfall 만) ────────────────────────────────────
def build_reh_rain_wide(
    long_df: pd.DataFrame, points: list[dict],
    window_start: datetime, window_end: datetime, day_ahead: bool,
) -> pd.DataFrame:
    """지점별 kimr_one_point -> reh_<지점> / rainfall_<지점> 두 컬럼만 모은 wide.

    kimr_one_point 는 REH/RAIN 외 카테고리가 없으면 그 컬럼을 안 만들므로, REH/RAIN
    만 담긴 long_df 에서는 reh_<지점> + rainfall_<지점> 만 나온다 (그 둘만 select).
    """
    parts: list[pd.DataFrame] = []
    for pt in points:
        sub = ci.kimr_one_point(
            long_df, pt["name"], pt["suffix"], window_start, window_end,
            day_ahead=day_ahead,
        )
        if sub.empty:
            print(f"  [WARN] no KIMR reh/rain for {pt['name']} -- skipped")
            continue
        keep = [c for c in (f"reh_{pt['suffix']}", f"rainfall_{pt['suffix']}") if c in sub.columns]
        if not keep:
            print(f"  [WARN] {pt['name']} produced no reh/rainfall column -- skipped")
            continue
        parts.append(sub[keep])
        print(f"  {pt['name']:<20} -> {len(sub):4d} rows, cols={keep}")

    if not parts:
        return pd.DataFrame()
    wide = pd.concat(parts, axis=1).sort_index()
    # forecast 테이블과 동일한 timestamp 문자열 (초 포함).
    wide.index = pd.to_datetime(wide.index, format="%Y-%m-%d %H:%M").strftime(
        "%Y-%m-%d %H:%M:%S"
    )
    wide.index.name = "timestamp"
    return wide.sort_index()


def _existing_forecast_timestamps(db_path: Path) -> set[str]:
    if not db_path.exists() or db_path.stat().st_size == 0:
        return set()
    with sqlite3.connect(db_path) as c:
        try:
            rows = c.execute(f"SELECT timestamp FROM {FORECAST_TABLE}").fetchall()
        except sqlite3.OperationalError:
            return set()
    return {r[0] for r in rows}


# ── main ────────────────────────────────────────────────────────────────
def main() -> None:
    p = argparse.ArgumentParser(
        description=(
            "[일회성] 육지 forecast 의 빠진 reh/rainfall 을 KIMR 로 백필 "
            "(reh_<지점> / rainfall_<지점>, partial-UPSERT)."
        ),
    )
    p.add_argument("--days", type=int, default=180, help="최근 N일 백필 (기본 180)")
    p.add_argument("--db", type=Path, default=DEFAULT_DB, help=f"SQLite (기본 {DEFAULT_DB})")
    p.add_argument(
        "--all-issues", action="store_true",
        help="4발표(00/06/12/18 UTC) 모두 받아 freshest (기본: day-ahead 00 UTC 만)",
    )
    p.add_argument(
        "--include-new", action="store_true",
        help="forecast 에 없는 timestamp 도 INSERT (기본: 기존 행만 채움)",
    )
    p.add_argument("--no-save", action="store_true", help="dry-run (DB 안 씀, 샘플 출력)")
    args = p.parse_args()

    day_ahead = not args.all_issues
    t0 = time.time()

    print("[temp_land_backfill] KIMR 격자점 변환")
    points = build_land_points()

    bases = pick_bases(args.days, day_ahead_only=day_ahead)
    if not bases:
        print(f"[backfill] {args.days}일 윈도우에 발표가 없음 -- 종료")
        return
    window_start = min(kim.collection_window(b)[0] for b in bases)
    window_end = max(kim.collection_window(b)[1] for b in bases)
    print(
        f"\n[backfill] days={args.days}  bases={len(bases)} "
        f"({bases[0].strftime('%Y%m%d%H')} ~ {bases[-1].strftime('%Y%m%d%H')} UTC, "
        f"{'day-ahead 00UTC만' if day_ahead else '4발표 freshest'})  "
        f"window=[{window_start:%Y-%m-%d %H:%M} ~ {window_end:%Y-%m-%d %H:%M}) KST"
    )

    print("\n[1/3] fetch KIMR-land (REH / RAIN)")
    long_df = fetch_kimr_land_long(bases, points)
    if long_df.empty:
        print("  [WARN] KIMR-land 결과 없음 -- 종료")
        return
    print(
        f"  long: {len(long_df):,} rows, {long_df['point_name'].nunique()} points, "
        f"cats={sorted(long_df['category'].unique())}, {long_df['base_datetime'].nunique()} bases"
    )

    print("\n[2/3] long -> wide (reh / rainfall)")
    wide = build_reh_rain_wide(long_df, points, window_start, window_end, day_ahead)
    if wide.empty:
        print("  [WARN] wide 비어있음 -- 종료")
        return

    # forecast 의 기존 timestamp 만 채울지(기본) / 새 행도 넣을지.
    if not args.include_new:
        existing = _existing_forecast_timestamps(args.db)
        before = len(wide)
        wide = wide.loc[wide.index.isin(existing)]
        print(
            f"  기존 forecast timestamp 로 제한: {before} -> {len(wide)} rows "
            f"(forecast 행 {len(existing)})"
        )
        if wide.empty:
            print("  [WARN] 겹치는 timestamp 없음 -- 종료")
            return

    print("\n[postprocess] clip_ranges (reh 0~100 / rainfall NaN->0)")
    wide = pp.clip_ranges(wide)
    print(
        f"  최종 wide: {len(wide):,} rows x {len(wide.columns)} cols "
        f"[{wide.index.min()} ~ {wide.index.max()}]\n  컬럼: {list(wide.columns)}"
    )
    # 채움률 요약.
    fill = (wide.notna().mean() * 100).round(1)
    print("  채움률(%):")
    for c in wide.columns:
        print(f"    {c:<26} {fill[c]:5.1f}%")

    if args.no_save:
        print("\n[no-save] dry-run -- DB 미저장.  샘플 5행:")
        print(wide.head().to_string())
        print(f"\n[temp_land_backfill] done (dry-run) in {(time.time()-t0)/60:.1f}m")
        return

    n = partial_upsert(FORECAST_TABLE, wide, args.db)
    print(f"\n  UPSERT forecast: {n:,} rows -> {args.db}")
    print(f"\n[temp_land_backfill] done in {(time.time()-t0)/60:.1f}m")


if __name__ == "__main__":
    main()

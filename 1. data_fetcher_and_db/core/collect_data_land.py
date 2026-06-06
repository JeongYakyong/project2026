"""
collect_data_land.py -- (육지/본토) wide 파이프라인 → data/input_data_land.db.

collect_data_jeju.py 의 육지 짝(mirror).  제주 파이프라인이 KIMR/KIMG/KPX 제주/
ASOS 3지점을 메모리에서 직접 받아 input_data_jeju.db 를 채우듯, 본 모듈도 육지(본토)
5 지점의 예보(KIMG-land) + 관측(ASOS-land) + 전력계통(KPX 육지 수급/발전)을
**메모리에서 바로** 모아 input_data_land.db 의 forecast / historical 테이블에
timestamp-keyed UPSERT 한다 (2026-05-31 육지/제주 분리; 2026-06-01 중간 DB 제거).

2026-06-01 변경 -- kimg_land.db / asos_land.db (중간 산출 DB) 제거.
    이전: api_fetchers_land.collect -> kimg_land.db -> 읽기 -> 피벗  (write-then-read-back).
    지금: _common 의 KIMG core(fetch_one_hf/parse_response/derive_categories) 로
          KIMG-land 를 메모리 long DF 로 바로 받고(fetch_kimg_land_long), ASOS 도
          api_fetchers_land.fetch_asos_land() 로 메모리에서 바로 받는다.
    제주(collect_data_jeju)와 완전히 같은 in-memory 패턴 -- 중간 .db 파일 없음.
    api_fetchers_land 는 순수 fetcher 허브(POINTS + KPX/ASOS fetcher)로만 쓴다.

소스
- forecast  : KIMG-land 5 지점을 _common KIMG core 로 메모리 long DF 로 받아
              (fetch_kimg_land_long) SOLAR_RAD/TCLD/MIDLOW_CLOUD/TEMP_C/WIND_U_V_10M 를
              radiation/total_cloud/midlow_cloud/temp/wind_spd_10m·wd_sin_10m·wd_cos_10m
              로 피벗 (제주와 달리 KIMR-land 가 없어 KIMG temp/wind 도 유일 예보 weather).
              + smp_land_da / land_est_demand_da (ckl.fetch_land_est, KPX API) join.
- historical: 육지 KPX 3종 (api_fetchers_land = ckl) -- sukub 수급 *_land
              (ckl.fetch_kpx_land), 발전원별 실적 gen_*_kr (ckl.fetch_land_power,
              powerSource.es 상세 12종, 전국값), 일전 SMP/예상수요 *_da (ckl.fetch_land_est)
              -- + ASOS-land 5 지점 관측 (*_<지점>) 을 ckl.fetch_asos_land() 로 메모리에서.

육지 5 지점 (KMA ASOS 지점번호; api_fetchers_land.POINTS / LAND_ASOS_STATIONS 와 동일)
    100 대관령  강원 고지대 산악 풍력      -> daegwallyeong
    114 원주    강원 영서 남부 / 충북 완충  -> wonju
    129 서산    충남 서해안 솔라 벨트       -> seosan
    138 포항    경북 동해안 풍력            -> pohang
    252 영광군  전남 북서부 해상풍력        -> yeonggwang
  컬럼 suffix 는 지점 romanized 소문자 (제주의 west/east/south 와 같은 역할의 join 키).

저장
- data/input_data_land.db, 테이블 forecast / historical (둘 다 timestamp UNIQUE).
- partial_upsert (_common 에서 import) 사용 -- 배치에 없는 컬럼은 보존.
- postprocess.clip_ranges + add_day_type 를 모든 write 직전에 적용 (제주와 동일).

사용
    python core/collect_data_land.py                       # 최근 2 발표 forecast + historical (default)
    python core/collect_data_land.py --base 20260525 12    # 특정 UTC 발표 forecast
    python core/collect_data_land.py --bases 4             # 최근 4 발표
    python core/collect_data_land.py --backfill 30         # forecast 30 일 backfill (KIMG-land in-memory)
    python core/collect_data_land.py --backfill 150 --kimg-issues 18 --kimg-days 1  # day-ahead 전용 (hf 절감)
    python core/collect_data_land.py --no-historical       # forecast 만
    python core/collect_data_land.py --no-forecast         # historical 만 (KPX API + ASOS-land)
    python core/collect_data_land.py --historical-days 7   # 최근 7 일치 KPX 육지 + ASOS
    python core/collect_data_land.py --start 2026-04-01 --end 2026-04-30   # historical 기간 지정
    python core/collect_data_land.py --no-save             # dry-run (DB 안 씀)

라이브러리로 사용
    from collect_data_land import build_forecast, build_historical
    fdf = build_forecast()                 # KIMG-land in-memory -> forecast wide + DB 저장
    hdf = build_historical(n_days_back=7)   # KPX 육지 + ASOS-land in-memory -> historical wide
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

# 통합 모듈 (2026-06-01 compaction + in-memory 리팩터).
import _common as kimg            # KIMG http/parse/derive core + 공유 발표시각/윈도우 헬퍼
import api_fetchers_land as ckl   # 육지 POINTS + forecast_days_override + KPX/ASOS fetcher
import postprocess as pp
from _common import freshest, partial_upsert

_REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = _REPO_ROOT / "data" / "input_data_land.db"

FORECAST_TABLE = "forecast"
HISTORICAL_TABLE = "historical"

# backfill 처리 단위(발표 수).  제주 BACKFILL_CHUNK_SIZE 와 동일 취지.
BACKFILL_CHUNK_SIZE = 8

# 육지 5 지점 point_name -> 컬럼 suffix (romanized 소문자).
POINT_SUFFIX = {
    "Daegwallyeong(100)": "daegwallyeong",
    "Wonju(114)":         "wonju",
    "Seosan(129)":        "seosan",
    "Pohang(138)":        "pohang",
    "Yeonggwang(252)":    "yeonggwang",
}

# KIMG-land 카테고리 -> forecast 컬럼 prefix (wind 는 U/V 라 별도 분해).
_KIMG_SCALAR = {
    "SOLAR_RAD":    "radiation",
    "TCLD":         "total_cloud",
    "MIDLOW_CLOUD": "midlow_cloud",
    "TEMP_C":       "temp",
}

# 전국(_kr) 발전 capacity / utilization 파생 컬럼 (historical 전체 기간 누적 max 기반).
# capacity ~= 설비용량 근사 = 발전량의 running cummax (설비 증설로 단조 증가).
# 태양광은 사용자 정의에 따라 전력시장(gen_solar_market_kr)만 사용 -- BTM/PPA 추정 제외
# (renew_gen_total_kr = market + wind 정의와 동일).  풍력은 gen_wind_kr.
_KR_CAPACITY_SPEC = {
    # capacity 컬럼            : 기반 발전 컬럼
    "gen_wind_capacity_kr":   "gen_wind_kr",
    "gen_solar_capacity_kr":  "gen_solar_market_kr",
}
_KR_UTILIZATION_SPEC = {
    # utilization 컬럼          : (발전 컬럼, capacity 컬럼)
    "gen_wind_utilization_kr":  ("gen_wind_kr",         "gen_wind_capacity_kr"),
    "gen_solar_utilization_kr": ("gen_solar_market_kr", "gen_solar_capacity_kr"),
}


# ── KIMG-land in-memory fetch (제주 fetch_kimg_long 의 육지판) ────────────
def fetch_kimg_land_long(bases: list[datetime]) -> pd.DataFrame:
    """주어진 bases × ckl.POINTS(육지 5 지점) 에 대해 hf 별 API 호출 → long DF.

    제주 collect_data_jeju.fetch_kimg_long 과 같은 in-memory 패턴.  (base, point) 마다
    48 hf 를 workers=6 으로 fanout, _common KIMG core(fetch_one_hf/parse_response/
    derive_categories)로 SOLAR_RAD/TEMP_C/WIND_U_V_10M 등을 라벨 그대로 받는다.
    kimg_land.db 를 거치지 않는다.
    """
    kimg.warmup()
    rows: list[tuple] = []
    for base in bases:
        base_kst = base.astimezone(kimg.KST)
        base_dt_str = base_kst.strftime("%Y-%m-%d %H:%M")
        base_label = base.strftime("%Y%m%d%H") + " UTC"
        for pt in ckl.POINTS:
            hf_list = list(kimg.collection_hf_range(base))
            t0 = time.time()
            failed = 0
            empty = 0
            n_kept = 0
            with ThreadPoolExecutor(max_workers=kimg.MAX_WORKERS) as ex:
                fut_to_hf = {
                    ex.submit(kimg.fetch_one_hf, base, pt, hf): hf
                    for hf in hf_list
                }
                for fut in as_completed(fut_to_hf):
                    hf = fut_to_hf[fut]
                    body = fut.result()
                    if body is None:
                        failed += 1
                        continue
                    raw = kimg.parse_response(body)
                    if not raw:
                        empty += 1
                        continue
                    cats = kimg.derive_categories(raw)
                    fcst_kst = base_kst + timedelta(hours=hf)
                    fcst_dt_str = fcst_kst.strftime("%Y-%m-%d %H:%M")
                    for cat, val in cats.items():
                        rows.append(
                            (base_dt_str, pt["name"], fcst_dt_str, cat, float(val))
                        )
                        n_kept += 1
            elapsed = time.time() - t0
            print(
                f"  KIMG-land {base_label} {pt['name']:<22}  hfs={len(hf_list):2d}  "
                f"kept_rows={n_kept:4d}  failed={failed:2d}  empty={empty:2d}  "
                f"({elapsed:.1f}s)"
            )
    if not rows:
        return pd.DataFrame(
            columns=["base_datetime", "point_name", "fcst_datetime",
                     "category", "fcst_value"]
        )
    df = pd.DataFrame(
        rows,
        columns=["base_datetime", "point_name", "fcst_datetime",
                 "category", "fcst_value"],
    )
    df["fcst_value"] = pd.to_numeric(df["fcst_value"], errors="coerce")
    return df


def kimg_land_long_to_wide(df: pd.DataFrame) -> pd.DataFrame:
    """KIMG-land long DF (fetch_kimg_land_long 출력) -> wide forecast.

    입력 컬럼: base_datetime / point_name / fcst_datetime / category / fcst_value.
    (point, fcst_datetime, category) 별 freshest base 를 골라 day-ahead 단일화한 뒤
    지점별로 피벗.  WIND_U/V_10M 은 collect_input 과 같은 식으로 spd/sin/cos 분해.
    (이전 read_kimg_land_forecast 의 DB-read 버전 -- 같은 피벗 로직, 입력만 메모리 DF.)
    """
    if df.empty:
        return pd.DataFrame()
    df = df.copy()
    df["fcst_value"] = pd.to_numeric(df["fcst_value"], errors="coerce")
    fresh = freshest(df, ["point_name", "fcst_datetime", "category"])

    parts: list[pd.DataFrame] = []
    for point, suffix in POINT_SUFFIX.items():
        sub = fresh[fresh["point_name"] == point]
        if sub.empty:
            print(f"  [WARN] no KIMG-land rows for {point} -- skipped")
            continue
        piv = sub.pivot(index="fcst_datetime", columns="category", values="fcst_value")
        out = pd.DataFrame(index=piv.index)
        for cat, prefix in _KIMG_SCALAR.items():
            if cat in piv:
                col = piv[cat]
                out[f"{prefix}_{suffix}"] = col.round(2) if cat == "TEMP_C" else col
        if "WIND_U_10M" in piv and "WIND_V_10M" in piv:
            # 컬럼명은 제주 forecast 와 통일: wind_spd_10m / wd_sin_10m / wd_cos_10m
            # (KIMG-land 은 10m 풍속만 있어 80m 컬럼은 없음).  분해식은 collect_input 동일.
            u, v = piv["WIND_U_10M"], piv["WIND_V_10M"]
            spd = np.sqrt(u**2 + v**2)
            wdir = (270 - np.degrees(np.arctan2(v, u))) % 360
            out[f"wind_spd_10m_{suffix}"] = spd.round(2)
            out[f"wd_sin_10m_{suffix}"]   = np.sin(np.radians(wdir)).round(4)
            out[f"wd_cos_10m_{suffix}"]   = np.cos(np.radians(wdir)).round(4)
        parts.append(out)
        print(f"  pivot {point:<20} -> {len(out):4d} rows x {len(out.columns)} cols")

    if not parts:
        return pd.DataFrame()
    wide = pd.concat(parts, axis=1)
    wide.index = pd.to_datetime(wide.index, format="%Y-%m-%d %H:%M").strftime(
        "%Y-%m-%d %H:%M:%S"
    )
    wide.index.name = "timestamp"
    return wide.sort_index()


# ── DB write (제주와 공통 partial_upsert 재사용) ───────────────────────────
def write_to_forecast(wide: pd.DataFrame, db_path: Path) -> int:
    return partial_upsert(FORECAST_TABLE, wide, db_path)


def write_to_historical(wide: pd.DataFrame, db_path: Path) -> int:
    return partial_upsert(HISTORICAL_TABLE, wide, db_path)


# ── 발표(base) 선택 ────────────────────────────────────────────────────
def _pick_bases(base: datetime | None, n_bases: int) -> list[datetime]:
    """--base 주어졌으면 그것 한 개, 아니면 최근 n_bases 발표 (오래된→최신).

    KIMG-land 도 KIMG 와 동일한 4 발표(UTC 00/06/12/18) 시각이므로 _common 의
    latest_published_base 를 그대로 쓴다.
    """
    if base is not None:
        return [base]
    now_kst = datetime.now(tz=kimg.KST)
    latest = kimg.latest_published_base(now_kst)
    out: list[datetime] = []
    cur = latest
    for _ in range(max(1, n_bases)):
        out.append(cur)
        cur -= timedelta(hours=6)
    out.sort()
    return out


def _expected_timestamps_for(base_utc: datetime) -> set[str]:
    """한 base 의 KIMG-land collection_window 가 만들 timestamp 문자열 집합(KST).

    _common.collection_window 은 호출 시점의 FORECAST_DAYS 를 읽으므로 forecast_days
    override 컨텍스트 안에서 호출하면 줄어든 윈도우가 반영된다.
    """
    ws, we = kimg.collection_window(base_utc)
    n_hours = int((we - ws).total_seconds() // 3600)
    return {
        (ws + timedelta(hours=h)).strftime("%Y-%m-%d %H:%M:%S")
        for h in range(n_hours)
    }


def _existing_timestamps(db_path: Path, table: str = FORECAST_TABLE) -> set[str]:
    """`table` 에 이미 있는 timestamp 집합.  테이블/파일 없으면 빈 set."""
    if not db_path.exists() or db_path.stat().st_size == 0:
        return set()
    with sqlite3.connect(db_path) as c:
        try:
            rows = c.execute(f"SELECT timestamp FROM {table}").fetchall()
        except sqlite3.OperationalError:
            return set()
    return {r[0] for r in rows}


# ── *_da resume-skip (정적인 과거 day-ahead 재요청 방지) ─────────────────
def _missing_da_dates(dates: list[str], db_path: Path) -> list[str]:
    """forecast 테이블에서 smp_land_da / land_est_demand_da 가 그 날짜의 모든 행에
    이미 채워진 날짜를 제외하고, 재요청이 필요한 날짜(YYYY-MM-DD) 목록을 반환.

    과거 day-ahead 값은 정적이므로 한 번 채워지면 재요청하지 않는다(제주 backfill 의
    timestamp resume-skip 과 동일 취지).  부분만 채워진 날짜(예: 당일)는 다시 받는다.
    """
    if not db_path.exists():
        return list(dates)
    with sqlite3.connect(db_path) as c:
        try:
            rows = c.execute(
                f"SELECT substr(timestamp,1,10) AS d, COUNT(*) AS n, "
                f"  COUNT(smp_land_da) AS n_smp, COUNT(land_est_demand_da) AS n_est "
                f"FROM {FORECAST_TABLE} GROUP BY d"
            ).fetchall()
        except sqlite3.OperationalError:
            return list(dates)
    filled = {d for d, n, n_smp, n_est in rows if n_smp >= n and n_est >= n}
    return [d for d in dates if d not in filled]


def _join_da(wide: pd.DataFrame, db_path: Path) -> pd.DataFrame:
    """forecast wide 에 smp_land_da + land_est_demand_da (*_da) 를 left-join.

    이미 두 _da 컬럼이 다 채워진 날짜는 재요청하지 않는다(정적인 과거 day-ahead).
    빈/부분(당일) 날짜만 KPX 에 요청 -- 제주 backfill 의 resume-skip 과 동일.
    건너뛴 날짜의 기존 _da 값은 partial_upsert 가 보존한다.  KPX 실패 시 weather 만.
    """
    print("\n[*_da] smp_land_da + land_est_demand_da (KPX API)")
    all_dates = sorted({ts[:10] for ts in wide.index})
    need = _missing_da_dates(all_dates, db_path)
    if not need:
        print("  [*_da] all forecast dates already filled -- skip KPX fetch")
        return wide
    s_date, e_date = need[0], need[-1]
    print(f"  [*_da] fetch {s_date} ~ {e_date}  ({len(need)} date(s) missing)")
    try:
        est = ckl.fetch_land_est(s_date, e_date)
    except Exception as e:
        print(f"  [WARN] *_da fetch failed: {e}")
        est = pd.DataFrame()
    if not est.empty:
        wide = wide.join(est, how="left")
        print(f"  joined *_da ({len(est)} rows)")
    return wide


# ── 빌더 ──────────────────────────────────────────────────────────────
def build_forecast(
    base: datetime | None = None,
    n_bases: int = 2,
    forecast_days: int | None = None,
    save: bool = True,
    db_path: Path = DEFAULT_DB,
) -> pd.DataFrame:
    """KIMG-land 를 메모리에서 받아 forecast wide -> (선택) input_data_land.db.forecast UPSERT.

    제주 build() 와 같은 in-memory 패턴: fetch_kimg_land_long(bases) 로 long DF 를 받아
    kimg_land_long_to_wide 로 피벗.  kimg_land.db 를 거치지 않는다.

    base/n_bases  : 발표 선택 (--base 단일 / 기본 최근 n_bases 발표).
    forecast_days : 수집 윈도우 길이(일).  None=기본 2일(48h).  1 이면 D+1 만(hf 절반).
    """
    bases = _pick_bases(base, n_bases)
    print(
        f"[collect_data_land] forecast bases={len(bases)} "
        f"({bases[0].strftime('%Y%m%d%H')} ~ {bases[-1].strftime('%Y%m%d%H')} UTC), "
        f"target table='{FORECAST_TABLE}' (UPSERT)"
    )

    print("\n[1/2] fetch KIMG-land (in-memory, 5 points)")
    with ckl.forecast_days_override(forecast_days):
        if forecast_days is not None:
            print(f"  [kimg-land] FORECAST_DAYS override = {forecast_days} day(s)")
        kimg_long = fetch_kimg_land_long(bases)
    if kimg_long.empty:
        print("  [WARN] KIMG-land empty -- nothing to write")
        return pd.DataFrame()
    print(
        f"  KIMG-land long: {len(kimg_long):,} rows, "
        f"{kimg_long['point_name'].nunique()} points, "
        f"{kimg_long['category'].nunique()} categories, "
        f"{kimg_long['base_datetime'].nunique()} bases"
    )

    print("\n[2/2] pivot to wide")
    wide = kimg_land_long_to_wide(kimg_long)
    if wide.empty:
        print("  [WARN] pivot produced no rows -- nothing to write")
        return wide

    wide = _join_da(wide, db_path)

    print("\n[postprocess] range clip + day_type")
    wide = pp.clip_ranges(wide)
    wide = pp.add_day_type(wide)
    print(
        f"  forecast wide: {len(wide):,} rows x {len(wide.columns)} cols "
        f"(NaN ratio = {wide.isna().mean().mean():.2%})  "
        f"[{wide.index.min()} ~ {wide.index.max()}]"
    )
    if save:
        n = write_to_forecast(wide, db_path)
        print(f"\n  UPSERT forecast: {n:,} rows -> {db_path}")
    return wide


def run_backfill(
    n_days: int,
    issue_hours: tuple[int, ...] | None = None,
    forecast_days: int | None = None,
    db_path: Path = DEFAULT_DB,
) -> int:
    """과거 N 일치 KIMG-land forecast 를 메모리에서 받아 forecast 에 UPSERT.

    제주 run_backfill 의 KIMG-only 육지판.  BACKFILL_CHUNK_SIZE 발표씩 fetch →
    pivot → UPSERT.  한 base 가 만들 timestamp 가 이미 forecast 에 다 있으면 그
    base 는 fetch 자체를 건너뛴다 (resume-skip).  *_da 는 chunk 별로 _join_da.

    issue_hours   : 특정 UTC 발표(예: (18,))로 제한 -- hf 호출 수 절감 (day-ahead 전용).
    forecast_days : 윈도우 길이(일).  1 이면 D+1 만 받아 (발표,지점)당 hf 호출 절반.
    """
    now_kst = datetime.now(tz=kimg.KST)
    bases = kimg.backfill_bases(n_days, now_kst, issue_hours=issue_hours)
    if not bases:
        print(f"[backfill] no bases in window for {n_days} days (issues={issue_hours})")
        return 0

    with ckl.forecast_days_override(forecast_days):
        if forecast_days is not None:
            print(f"  [kimg-land] FORECAST_DAYS override = {forecast_days} day(s)")
        existing_ts = _existing_timestamps(db_path, FORECAST_TABLE)
        bases_todo = [
            b for b in bases if not _expected_timestamps_for(b).issubset(existing_ts)
        ]
        skipped = len(bases) - len(bases_todo)
        issues_label = (
            f"issues={','.join(f'{h:02d}' for h in issue_hours)} UTC"
            if issue_hours else "issues=all (00,06,12,18)"
        )
        print(
            f"[backfill] n_days={n_days} ({issues_label}) -> {len(bases)} bases  "
            f"(skipped={skipped} already-in-forecast, todo={len(bases_todo)})"
        )
        if not bases_todo:
            print("[backfill] nothing to do.")
            return 0

        t0 = time.time()
        total_written = 0
        n_chunks = (len(bases_todo) + BACKFILL_CHUNK_SIZE - 1) // BACKFILL_CHUNK_SIZE
        for ci_idx in range(n_chunks):
            chunk = bases_todo[ci_idx * BACKFILL_CHUNK_SIZE:(ci_idx + 1) * BACKFILL_CHUNK_SIZE]
            print(
                f"\n[backfill] chunk {ci_idx + 1}/{n_chunks}: "
                f"{chunk[0].strftime('%Y%m%d%H')} ~ {chunk[-1].strftime('%Y%m%d%H')} UTC "
                f"({len(chunk)} bases)"
            )
            kimg_long = fetch_kimg_land_long(chunk)
            wide = kimg_land_long_to_wide(kimg_long)
            if wide.empty:
                print("  [backfill] chunk produced no rows, skipping")
                continue
            wide = _join_da(wide, db_path)
            wide = pp.clip_ranges(wide)
            wide = pp.add_day_type(wide)
            n = write_to_forecast(wide, db_path)
            total_written += n
            elapsed = time.time() - t0
            print(
                f"  [backfill] chunk done: UPSERT {n:,} rows  "
                f"(total {total_written:,}, elapsed {elapsed/60:.1f}m)"
            )

    print(
        f"\n[backfill] done: {total_written:,} rows total in "
        f"{(time.time()-t0)/60:.1f}m -> {db_path}"
    )
    return total_written


# ── _kr capacity / utilization 파생 (historical 전체 기간 누적 max) ──────
def recompute_kr_capacity(db_path: Path = DEFAULT_DB) -> int:
    """historical 의 gen_wind_kr / gen_solar_market_kr 전체 시계열로 capacity +
    utilization 4개 파생 컬럼을 계산해 historical 에 다시 UPSERT.

    capacity ~= 설비용량 근사 = 발전량의 running max(cummax), 단 첫 해(2020) 전체는
    그 해 peak 로 평탄화(첫 행 야간 저점에서 시작하는 cummax 왜곡 방지).  이후 설비
    증설을 반영해 단조 증가.  utilization = 발전량 / capacity (이용률).

    cummax 는 전체 기간 문맥이 필요하므로 batch 단위 postprocess 가 아니라 여기서
    historical 테이블 전체를 읽어 재계산한다.  backfill 이든 일일 top-up 이든 매번
    전체를 다시 계산하므로 idempotent (cummax 는 단조라 과거 행 값은 안 바뀌고,
    새 발전량이 더 크면 그 시점 이후 capacity 만 갱신).
    """
    if not db_path.exists() or db_path.stat().st_size == 0:
        print("  [kr-capacity] DB 없음 -- skip")
        return 0
    base_cols = sorted(set(_KR_CAPACITY_SPEC.values()))
    with sqlite3.connect(db_path) as c:
        existing = {r[1] for r in c.execute(
            f"PRAGMA table_info({HISTORICAL_TABLE})").fetchall()}
        if not existing:
            print("  [kr-capacity] historical 테이블 없음 -- skip")
            return 0
        avail = [col for col in base_cols if col in existing]
        if not avail:
            print("  [kr-capacity] gen_wind_kr / gen_solar_market_kr 부재 -- skip")
            return 0
        cols_sql = ", ".join(f'"{col}"' for col in ["timestamp", *avail])
        df = pd.read_sql(
            f"SELECT {cols_sql} FROM {HISTORICAL_TABLE} ORDER BY timestamp", c,
        )
    if df.empty:
        print("  [kr-capacity] historical 비어있음 -- skip")
        return 0

    df = df.set_index("timestamp")
    out = pd.DataFrame(index=df.index)
    # capacity = 발전량의 누적 max(cummax).  단, cummax 만 쓰면 첫 행(2020-01-01 00:00)
    # capacity 가 그 시각 값(야간 저점)으로 시작해 초기 utilization 이 1.0 으로 왜곡된다.
    # 따라서 capacity 의 하한을 "첫 해(2020) 발전량 최대값" 으로 깔아 첫 해 전체를 그 해
    # 실제 peak 로 평탄화한다.  이후 연도는 cummax 가 이미 그 하한을 넘으므로 그대로 증가.
    # cummax 는 NaN 위치를 NaN 으로 남기므로 ffill 로 capacity 를 직전 max 로 채운다.
    first_year = df.index[0][:4]                 # 데이터 시작 연도 (timestamp 'YYYY-...')
    in_first_year = df.index.str[:4] == first_year
    for cap_col, gen_col in _KR_CAPACITY_SPEC.items():
        if gen_col not in df.columns:
            continue
        gen = pd.to_numeric(df[gen_col], errors="coerce")
        floor = gen[in_first_year].max()         # 첫 해 peak (하한)
        # cummax 는 NaN 위치를 NaN 으로 남긴다 -> ffill 로 중간 결측을 직전 max 로 채우고,
        # 선두(첫 valid 이전) NaN 은 floor 로 채운 뒤 clip 으로 첫 해를 floor 로 평탄화.
        # (clip 은 NaN 을 올리지 못하고 ffill 은 선두 NaN 을 못 채우므로 순서가 중요.)
        cap = gen.cummax().ffill()
        if pd.notna(floor):
            cap = cap.fillna(floor).clip(lower=floor)
        out[cap_col] = cap
    # utilization = 발전량 / capacity.  capacity<=0 또는 NaN 이면 NaN (0 나눗셈 방지).
    for util_col, (gen_col, cap_col) in _KR_UTILIZATION_SPEC.items():
        if gen_col not in df.columns or cap_col not in out.columns:
            continue
        gen = pd.to_numeric(df[gen_col], errors="coerce")
        cap = out[cap_col]
        out[util_col] = (gen / cap.where(cap > 0)).replace([np.inf, -np.inf], np.nan)

    out = out.dropna(how="all")
    if out.empty:
        print("  [kr-capacity] 계산 결과 없음 -- skip")
        return 0
    out.index.name = "timestamp"
    n = partial_upsert(HISTORICAL_TABLE, out, db_path)
    print(
        f"  [kr-capacity] {list(out.columns)} over {len(out):,} rows -> UPSERT {n:,}"
    )
    return n


def build_historical(
    n_days_back: int = 2,
    start_date: str | None = None,
    end_date: str | None = None,
    save: bool = True,
    db_path: Path = DEFAULT_DB,
) -> pd.DataFrame:
    """KPX 육지 3종(ckl: sukub/power/est) + ASOS-land(메모리) -> historical UPSERT.

    기간: start_date/end_date 가 주어지면 그 범위, 아니면 today-n_days_back ~ today.
    ASOS-land 는 ckl.fetch_asos_land 로 메모리에서 받는다 (asos_land.db 없이).
    """
    today = datetime.now(tz=kimg.KST).date()   # 제주 build_historical 과 동일하게 KST 기준
    if start_date and end_date:
        s_str, e_str = start_date, end_date
    else:
        e = today if end_date is None else datetime.strptime(end_date, "%Y-%m-%d").date()
        s = e - timedelta(days=n_days_back)
        s_str, e_str = s.strftime("%Y-%m-%d"), e.strftime("%Y-%m-%d")

    print(
        f"[collect_data_land] historical window={s_str} ~ {e_str}  "
        f"table='{HISTORICAL_TABLE}' (UPSERT)"
    )

    print("\n[L1/4] fetch *_land cols (sukub, KPX API)")
    try:
        land = ckl.fetch_kpx_land(s_str, e_str)
    except Exception as e:
        print(f"  [WARN] *_land failed: {e}")
        land = pd.DataFrame()
    print(f"  *_land:    {len(land):,} rows x {len(land.columns)} cols")

    print("\n[L2/4] fetch gen_*_kr (powerSource.es, detailed)")
    try:
        pwr_gen = ckl.fetch_land_power(s_str, e_str)
    except Exception as e:
        print(f"  [WARN] gen_*_kr failed: {e}")
        pwr_gen = pd.DataFrame()
    print(f"  gen_*_kr:  {len(pwr_gen):,} rows x {len(pwr_gen.columns)} cols")

    # *_da (smp_land_da + land_est_demand_da) -- DA 예측이지만 제주 정책과 동일하게
    # historical 에도 같은 컬럼명으로 누적 (forecast 에도 build_forecast 가 적재).
    print("\n[L3/4] fetch *_da (smp_land_da + land_est_demand_da)")
    try:
        est = ckl.fetch_land_est(s_str, e_str)
    except Exception as e:
        print(f"  [WARN] *_da failed: {e}")
        est = pd.DataFrame()
    print(f"  *_da:      {len(est):,} rows x {len(est.columns)} cols")

    print("\n[L4/4] fetch ASOS-land (in-memory, 5 stations)")
    try:
        asos = ckl.fetch_asos_land(s_str, e_str)
    except Exception as e:
        print(f"  [WARN] asos-land failed: {e}")
        asos = pd.DataFrame()
    if asos.empty:
        print("  [WARN] ASOS-land empty -- ASOS columns omitted")
    else:
        # historical 은 KPX 기간으로 트림 (ASOS 가 새 timestamp 행을 만들지 않도록).
        asos = asos.loc[(asos.index >= f"{s_str} 00:00:00") & (asos.index <= f"{e_str} 23:00:00")]
    print(f"  asos-land: {len(asos):,} rows x {len(asos.columns)} cols")

    parts = [df for df in (land, pwr_gen, est, asos) if not df.empty]
    if not parts:
        print("  [WARN] all historical sources empty -- nothing to write")
        return pd.DataFrame()

    wide = pd.concat(parts, axis=1).sort_index()
    wide.index.name = "timestamp"
    print(
        f"\n  historical wide: {len(wide):,} rows x {len(wide.columns)} cols "
        f"(NaN ratio = {wide.isna().mean().mean():.2%})"
    )

    print("\n[postprocess] range clip + day_type")
    wide = pp.clip_ranges(wide)
    wide = pp.add_day_type(wide)

    if save:
        n = write_to_historical(wide, db_path)
        print(f"\n  UPSERT historical: {n:,} rows -> {db_path}")
        # 발전실적(gen_*_kr)이 갱신됐으니 capacity/utilization 파생을 전체 기간 기준
        # 재계산 (cummax 는 단조라 과거 행은 그대로, 새 peak 만 이후 capacity 갱신).
        print("\n[kr-capacity] recompute gen_wind/solar capacity + utilization (_kr)")
        recompute_kr_capacity(db_path)
    return wide


# ── CLI ──────────────────────────────────────────────────────────────
def main() -> None:
    p = argparse.ArgumentParser(
        description=(
            "Land (mainland) wide pipeline -> input_data_land.db (in-memory, no "
            "kimg_land.db / asos_land.db).  Forecast: KIMG-land + *_da (KPX).  "
            "Historical: KPX 육지 sukub/power/est (api_fetchers_land) + ASOS-land."
        ),
    )
    # 발표 선택은 셋 중 하나: 최근 N개(default), --base 단일, --backfill N_DAYS.
    mode = p.add_mutually_exclusive_group()
    mode.add_argument(
        "--base", nargs=2, metavar=("YYYYMMDD", "HH"),
        help="single UTC publish for forecast (e.g. --base 20260525 12)",
    )
    mode.add_argument(
        "--backfill", type=int, metavar="N_DAYS",
        help="backfill last N days of KIMG-land publishes (UPSERT, resume-skip)",
    )
    p.add_argument(
        "--bases", type=int, default=2,
        help="when neither --base nor --backfill: how many recent publishes (default 2)",
    )
    p.add_argument("--start", default=None, help="historical start YYYY-MM-DD")
    p.add_argument("--end", default=None, help="historical end YYYY-MM-DD")
    p.add_argument(
        "--historical-days", type=int, default=2,
        help="historical window length in days (default 2; ignored if --start/--end)",
    )
    p.add_argument("--no-forecast", action="store_true", help="skip forecast build")
    p.add_argument("--no-historical", action="store_true", help="skip historical build")
    p.add_argument(
        "--kimg-issues", nargs="+", type=int, default=None, metavar="HH_UTC",
        choices=kimg.ISSUE_HOURS_UTC,
        help="restrict --backfill to these UTC publishes (e.g. --kimg-issues 18). default: all 4",
    )
    p.add_argument(
        "--kimg-days", type=int, default=None, metavar="N",
        help="KIMG-land window length in days (default 2=48h; 1 for D+1-only, halves hf calls)",
    )
    p.add_argument("--db", type=Path, default=DEFAULT_DB, help=f"SQLite path (default {DEFAULT_DB})")
    p.add_argument("--no-save", action="store_true", help="dry-run (don't write DB)")
    args = p.parse_args()

    if args.no_forecast and args.no_historical:
        sys.exit("--no-forecast and --no-historical together means nothing to do")

    t0 = time.time()

    if args.backfill is not None:
        if args.no_save:
            sys.exit("--no-save is not supported with --backfill")
        issue_hours = tuple(sorted(set(args.kimg_issues))) if args.kimg_issues else None
        if not args.no_forecast:
            print(f"\n=== forecast backfill (N={args.backfill}) ===")
            run_backfill(
                args.backfill, issue_hours=issue_hours,
                forecast_days=args.kimg_days, db_path=args.db,
            )
        if not args.no_historical:
            print(f"\n=== historical backfill (N={args.backfill}) ===")
            build_historical(n_days_back=args.backfill, save=True, db_path=args.db)
        print(f"\n[collect_data_land] done in {(time.time()-t0)/60:.1f}m")
        return

    base = None
    if args.base:
        base = datetime.strptime(args.base[0] + args.base[1], "%Y%m%d%H").replace(
            tzinfo=kimg.UTC,
        )

    if not args.no_forecast:
        print("\n=== forecast build (KIMG-land in-memory) ===")
        build_forecast(
            base=base, n_bases=args.bases, forecast_days=args.kimg_days,
            save=not args.no_save, db_path=args.db,
        )
    if not args.no_historical:
        print("\n=== historical build (KPX 육지 + ASOS-land) ===")
        build_historical(
            n_days_back=args.historical_days,
            start_date=args.start, end_date=args.end,
            save=not args.no_save, db_path=args.db,
        )
    print(f"\n[collect_data_land] done in {time.time() - t0:.1f}s")


if __name__ == "__main__":
    main()

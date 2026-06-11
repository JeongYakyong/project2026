"""
collect_data_jeju.py -- (제주) API → 후처리 → input_data_jeju.db 한방 파이프라인.

제주 3 지점(서/동/남) 전용 wide 파이프라인.  육지(본토) 데이터는 별도 모듈
collect_data_land.py + data/input_data_land.db 가 담당한다 (2026-05-31 분리).

기존(legacy) 2-단계 흐름:
    collect_kimr.py / collect_kimg.py → data/kimr.db + data/kimg.db
                                        ↓ collect_input.py
                                        data/model_input/<range>.csv

새(권장) 단방향 흐름:
    collect_data_jeju.py → API 호출 → 메모리 내 후처리
                        → data/input_data_jeju.db (wide, forecast 테이블)
    main 모델 코드는 이 DB 한 곳만 읽음.

DB 테이블 정책 (2026-05-26 재정의 / 2026-05-28 KPX-est 확장 + PwrAmountByGen 추가)
- `forecast`   : KIMR + KIMG + KPX-est (DA SMP, 제주/육지 예상수요) 가 가져온
                 모든 예보 데이터.  default 실행이든 --backfill 이든 전부 여기에
                 timestamp-keyed UPSERT 로 누적.  (예보는 "언제 만들어진 것이든
                 예보다" -- 백필한 2026-02 ~ 05 예보도 같은 테이블에 쌓인다.)
                 KIMR freshest-base-wins 는 build_wide 내부의
                 collect_input.kimr_one_point 가 처리.  KPX-est 는 forecast
                 윈도우의 date 범위로 호출해 left-join 으로 합친다.  KPX-est
                 컬럼은 smp_jeju_da / smp_land_da / jeju_est_demand_da /
                 land_est_demand_da (_da = day-ahead; jeju_/land_ 접두사로 두
                 권역의 예상수요를 충돌 없이 공존시킨다).
- `historical` : KPX 제주(*_jeju) 계통 수급 + KMA ASOS 3지점 관측 (temp/wind/
                 cloud/solar/rain/snow) + KPX-est (smp_*_da / *_est_demand_da)
                 + 제주 실시간시장 RT SMP (smp_rt_g1..g4 / smp_jeju_rt /
                 smp_rt_neg_num, 4단계 타깃) 가 누적되는 테이블.  build_historical() 가 책임진다.  육지(*_land
                 수급 / gen_*_land 발전실적)는 collect_data_land.py 로 분리됨.
                 default 실행 시
                 최근 N 일(--historical-days, 기본 2) fetch -> wide -> UPSERT.
                 --backfill N 은 forecast 와 historical 양쪽 N 일치를 함께
                 채운다.  KPX-est 컬럼(_da)을 양쪽 테이블에 모두 저장하는
                 정책은 legacy ingest 의 historical_data 처리와 정합 -- 같은
                 _da 값이 어느 경로로 들어왔든 forecast / historical 에 동일
                 컬럼명으로 누적.  partial_upsert 사용으로 다른 경로가 채운 컬럼
                 (예: recompute_jeju_capacity 의 real_*_capacity/utilization_jeju)이
                 NULL 되지 않는다.

방침
- 기존 firm 파일(collect_kimr/collect_kimg/collect_input)은 손대지 않는다.
  필요한 함수만 import 해서 재사용.  KPX/ASOS 도 동일 패턴 --
  collect_kpx_asos_data 의 fetcher 함수만 import 해서 wide 결과만 받아 join /
  UPSERT.
- kimr.db / kimg.db 는 통과하지 않음.  매 실행마다 fresh API 호출 → forecast UPSERT.
- 출력 스키마는 wide: timestamp 행, location-suffixed 컬럼 (collect_input.py 의
  CSV 컬럼 명명규칙과 동일).  KPX/관측 컬럼은 추후 join 으로 추가.
- API 호출은 collect_kimr/collect_kimg 의 fetch_* 만 사용 → retry/session/warmup
  스택 동일하게 적용됨.
- Backfill 병렬 정책: KIMR 은 N>3일이면 workers=6 (collect_kimr.workers_for_backfill
  와 동일), KIMG 은 (base,point) 외부 루프는 sequential 유지, 내부 hf 만 workers=6
  (CLAUDE.md 의 KIMG parallel-safe 규칙).

기본 동작 (인자 없이 실행 시 forecast + historical 양쪽 모두 갱신)
- forecast  : 최근 가용 발표 + 직전 발표 (--bases=2) -> KIMR/KIMG/*_da UPSERT.
- historical: 최근 N 일 (--historical-days, 기본 2) -> *_jeju/asos/*_da UPSERT.
- 한쪽만: --no-historical (forecast only) / --no-forecast (historical only).
- 단일 forecast 발표: --base YYYYMMDD HH (옛 발표든 최신이든 그냥 forecast 에).
- 과거 N 일 일괄: --backfill N -> forecast + historical 양쪽 N 일치 UPSERT.
- API 호출만 하고 DB 는 안 쓰고 싶다면 --no-save (--backfill 과는 사용 불가).

사용 예
    python core/collect_data_jeju.py                              # forecast + historical 둘 다 (default)
    python core/collect_data_jeju.py --bases 4                    # 직전 4 발표 + 기본 historical
    python core/collect_data_jeju.py --no-historical              # forecast 만
    python core/collect_data_jeju.py --no-forecast                # historical 만
    python core/collect_data_jeju.py --historical-days 7          # 최근 7 일치 historical
    python core/collect_data_jeju.py --base 20260525 12           # 단일 발표 + 기본 historical
    python core/collect_data_jeju.py --backfill 30                # forecast + historical 30 d
    python core/collect_data_jeju.py --backfill 150               # 150 d (KIMR workers=6)
    python core/collect_data_jeju.py --no-save                    # dry-run (양쪽 모두)

라이브러리로 사용
    from core.collect_data_jeju import build, build_historical, run_backfill
    fdf = build()                          # forecast wide 반환 + DB 저장
    hdf = build_historical(n_days_back=7)  # historical wide 반환 + DB 저장
    build(save=False)                      # 메모리만 (DB 저장 생략)
    run_backfill(n_days=30)                # forecast 만 백필 (historical 은 별도 호출)
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

# 통합 모듈 (2026-06-01 compaction).  별칭은 과거 모듈명을 유지해 호출부 변경 최소화.
# api_fetchers_jeju = (구 kma_fetcher_jeju + kpx_fetcher_jeju): KIMR fetch + 제주 파생
# + fetch_asos + KPX(수급/est).  아래 kim/ci/kpx 는 모두 이 한 모듈을 가리킨다.
import api_fetchers_jeju as kim   # KIMR fetch (fetch_and_prepare 등) + fetch_asos
import api_fetchers_jeju as ci    # 제주 파생 (POINT_SUFFIX / kimr_one_point / kimg_solar)
import api_fetchers_jeju as kpx   # 제주 KPX (fetch_kpx_jeju / fetch_kpx_est)
import _common as kimg            # KIMG http/parse/derive core
import postprocess as pp
from _common import partial_upsert


KST = ZoneInfo("Asia/Seoul")
UTC = timezone.utc

# data/ 는 repo 루트 한 곳만 사용 (모든 collector 공통 규칙).
DEFAULT_DB = Path(__file__).resolve().parent.parent / "data" / "input_data_jeju.db"

# 테이블 두 개를 이 모듈이 책임진다 (둘 다 upsert_wide_to 로 적재).
# - forecast  : KIMR + KIMG (예보 weather) + *_da (DA SMP / jeju_est_demand_da)
# - historical: *_jeju (관측 수급) + asos (관측 weather) + *_da (DA SMP/수요)
FORECAST_TABLE = "forecast"
HISTORICAL_TABLE = "historical"

# Backfill chunk 크기 (한 번에 메모리에 올릴 base 수).  너무 크면 RAM 부담,
# 너무 작으면 SQLite write 오버헤드.  8 base = 2 일치, 메모리 ~수십 MB.
BACKFILL_CHUNK_SIZE = 8

# 제주(_jeju) 발전 capacity / utilization 파생 컬럼 (historical 전체 기간 누적 max 기반).
# 육지 collect_data_land.recompute_kr_capacity 와 동일 로직.  capacity ~= 설비용량 근사
# = 발전량의 running cummax (첫 해는 그 해 peak 로 평탄화).  utilization = 발전량/capacity.
# 제주는 태양광이 단일 컬럼(real_solar_gen_jeju)이라 분해 불필요.  컬럼명은 기반 발전
# 컬럼(real_*_gen_jeju)과 짝이 맞는 real_*_capacity_jeju / real_*_utilization_jeju.
# (구 legacy 추정설비 Solar_Capacity_Est_jeju / *_Utilization_jeju 컬럼은 제거됨.)
_JEJU_CAPACITY_SPEC = {
    # capacity 컬럼              : 기반 발전 컬럼
    "real_wind_capacity_jeju":   "real_wind_gen_jeju",
    "real_solar_capacity_jeju":  "real_solar_gen_jeju",
}
_JEJU_UTILIZATION_SPEC = {
    # utilization 컬럼              : (발전 컬럼, capacity 컬럼)
    "real_wind_utilization_jeju":  ("real_wind_gen_jeju",  "real_wind_capacity_jeju"),
    "real_solar_utilization_jeju": ("real_solar_gen_jeju", "real_solar_capacity_jeju"),
}


class NoUsableForecastRows(Exception):
    """build_wide 가 윈도우 안에서 쓸 만한 KIMR 행을 못 만들었을 때.

    sys.exit 대신 이 예외를 던져 forecast 단계만 건너뛰고 historical 등 후속 단계는
    계속 진행할 수 있게 한다 (일시적 KIMR 결손이 전체 실행을 죽이지 않도록).
    """


# ── API → in-memory long DataFrame ──────────────────────────────────────
def fetch_kimr_long(bases: list[datetime], workers: int = 1) -> pd.DataFrame:
    """주어진 bases × POINTS 에 대해 KIM 지역 모델을 호출하고 long-format DF 반환.

    workers=1 은 순차, workers>1 은 (base,point) 페어 ThreadPoolExecutor.  병렬 모드는
    collect_kimr.run_backfill 의 워커 스택과 동일 (shared Session + warmup + retry).
    실패한 (base, point) 는 경고만 출력하고 건너뛴다 (전체 흐름은 계속).
    """
    collected_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    tasks = [(b, pt) for b in bases for pt in kim.POINTS]
    rows: list[tuple] = []
    n_ok = 0
    n_fail = 0

    def _one(base: datetime, pt: dict):
        return base, pt, kim.fetch_and_prepare(base, pt, collected_at)

    if workers <= 1:
        for base, pt in tasks:
            base_label = base.strftime("%Y%m%d%H") + " UTC"
            try:
                pt_rows, n_fetched, n_unknown, n_window = kim.fetch_and_prepare(
                    base, pt, collected_at,
                )
            except Exception as e:
                print(f"  [WARN] KIMR {base_label} {pt['name']}: {e}")
                n_fail += 1
                continue
            rows.extend(pt_rows)
            n_ok += 1
            print(
                f"  KIMR {base_label} {pt['name']:<18}  "
                f"fetched={n_fetched:4d}  kept={len(pt_rows):4d}  "
                f"dropped(unknown)={n_unknown:3d} (out-of-window)={n_window:4d}"
            )
    else:
        kim.warmup()
        print(f"  KIMR parallel: {len(tasks)} (base,point) pairs, workers={workers}")
        with ThreadPoolExecutor(max_workers=workers) as ex:
            fut_to_task = {ex.submit(_one, b, pt): (b, pt) for b, pt in tasks}
            for fut in as_completed(fut_to_task):
                base, pt = fut_to_task[fut]
                try:
                    _, _, (pt_rows, *_rest) = fut.result()
                except Exception as e:
                    print(f"  [WARN] KIMR {base.strftime('%Y%m%d%H')}UTC {pt['name']}: {e}")
                    n_fail += 1
                    continue
                rows.extend(pt_rows)
                n_ok += 1
        print(f"  KIMR parallel done: ok={n_ok} fail={n_fail}")

    if not rows:
        return pd.DataFrame(
            columns=["base_datetime", "point_name", "fcst_datetime",
                     "category", "fcst_value"]
        )
    df = pd.DataFrame(rows, columns=[
        "base_datetime", "fcst_datetime", "point_name", "x", "y",
        "category", "fcst_value", "collected_at",
    ])
    df["fcst_value"] = pd.to_numeric(df["fcst_value"], errors="coerce")
    return df[["base_datetime", "point_name", "fcst_datetime", "category", "fcst_value"]]


def fetch_kimg_long(bases: list[datetime]) -> pd.DataFrame:
    """주어진 bases × KIMG.POINTS 에 대해 hf 별 API 호출 → long DF.

    collect_kimg.collect_one_point 의 DB-없는 버전.  (base, point) 마다 48 hf 를
    workers=6 으로 fanout, 결과를 메인 스레드에서 모아 리스트로 누적.  실패 hf 는
    [WARN] 후 스킵.  derive_categories 변환식이 그대로 적용되므로 SOLAR_RAD /
    TEMP_C / WIND_U/V_10M 등이 라벨 그대로 나옴.
    """
    kimg.warmup()
    collected_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")  # 미사용 (호환용)
    _ = collected_at

    rows: list[tuple] = []
    for base in bases:
        base_kst = base.astimezone(kimg.KST)
        base_dt_str = base_kst.strftime("%Y-%m-%d %H:%M")
        base_label = base.strftime("%Y%m%d%H") + " UTC"
        for pt in kimg.POINTS:
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
                f"  KIMG {base_label} {pt['name']:<22}  hfs={len(hf_list):2d}  "
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


# ── long → wide 후처리 ──────────────────────────────────────────────────
def build_wide(
    kimr_long: pd.DataFrame, kimg_long: pd.DataFrame,
    window_start: datetime, window_end: datetime,
) -> pd.DataFrame:
    """collect_input 의 후처리 함수들을 그대로 사용해 wide DataFrame 생성.

    출력 컬럼은 collect_input.build_csv 와 정확히 동일 (location-suffixed,
    timestamp index).  KIMG 가 비어있으면 radiation_south 만 빠진다.

    지점별 KIMR + KIMG 병합 (2026-06-13, 장지평 확장):
    KIMR(지역모델, 고해상도)이 있는 시간은 KIMR 값을 쓰고, KIMR lead 한계(120h)
    이후나 결손 시간은 kimg_one_point 가 만든 동일 스키마 컬럼으로 채운다
    (combine_first).  KIMR 전용 변수(cape 등)는 KIMG-only 구간에서 NaN.
    """
    parts: list[pd.DataFrame] = []
    for point, suffix in ci.POINT_SUFFIX.items():
        kimr_part = ci.kimr_one_point(kimr_long, point, suffix, window_start, window_end)
        kimg_part = ci.kimg_one_point(kimg_long, point, suffix, window_start, window_end)
        if kimr_part.empty and kimg_part.empty:
            print(f"  [WARN] no KIMR/KIMG rows for {point} in window -- column group skipped")
            continue
        if kimr_part.empty:
            part = kimg_part
        elif kimg_part.empty:
            part = kimr_part
        else:
            part = kimr_part.combine_first(kimg_part)  # KIMR 우선, KIMG 는 빈 곳만
        parts.append(part)

    if not parts:
        raise NoUsableForecastRows("no usable KIMR/KIMG rows after pivoting")

    wide = pd.concat(parts, axis=1)

    # KIMG SOLAR_RAD → radiation_south 단일 컬럼.  long DF 를 SOLAR_RAD + solar_farm
    # + window 안으로 필터링한 뒤 ci.kimg_solar 에 넘긴다 (그 함수는 freshest 만 함).
    start_s = window_start.strftime("%Y-%m-%d %H:%M")
    end_s = window_end.strftime("%Y-%m-%d %H:%M")
    kimg_solar = kimg_long[
        (kimg_long["category"] == "SOLAR_RAD") &
        (kimg_long["point_name"] == "solar_farm(south)") &
        (kimg_long["fcst_datetime"] >= start_s) &
        (kimg_long["fcst_datetime"] < end_s)
    ]
    rad = ci.kimg_solar(kimg_solar)
    if not rad.empty:
        wide = wide.join(rad, how="left")
        n_rad = wide["radiation_south"].notna().sum()
        print(f"  joined radiation_south ({n_rad}/{len(wide)} hours have value)")
    else:
        print("  [WARN] KIMG SOLAR_RAD empty in window -- radiation_south column omitted")

    # collect_input 과 동일한 timestamp 문자열 (초 단위 포함, downstream 호환).
    wide.index = pd.to_datetime(wide.index, format="%Y-%m-%d %H:%M").strftime(
        "%Y-%m-%d %H:%M:%S"
    )
    wide.index.name = "timestamp"
    wide = wide.sort_index()
    return wide


# ── DB 출력 ─────────────────────────────────────────────────────────────
def upsert_wide_to(table: str, wide: pd.DataFrame, db_path: Path) -> int:
    """wide DataFrame 을 `table` 에 UPSERT (timestamp 키 충돌 시 새 값으로 교체).

    구현: pandas 가 UPSERT 를 직접 지원하지 않으므로 temp 테이블 → INSERT OR REPLACE
    SELECT 패턴.  본 테이블이 없으면 임시 테이블 스키마로 새로 만들고, 있는데 새
    컬럼이 등장했으면 ALTER TABLE ADD COLUMN 으로 확장한다 (KPX/관측 컬럼이 늦게
    추가될 때 마이그레이션 불필요).  반환: UPSERT 된 행 수.

    이 함수는 forecast 외 다른 테이블에도 재사용 가능 — 추후 관측치 collector 가
    'historical' 같은 자기 테이블에 같은 함수로 적재할 수 있다.
    """
    if wide.empty:
        return 0
    db_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = f"_tmp_{table}"
    with sqlite3.connect(db_path) as c:
        # 1) 배치를 임시 테이블로 떨군다 (DataFrame 스키마 그대로).
        wide.to_sql(tmp, c, if_exists="replace", index=True)

        # 2) 본 테이블 스키마 관리.
        existing = {r[1] for r in c.execute(f"PRAGMA table_info({table})").fetchall()}
        tmp_cols = [r[1] for r in c.execute(f"PRAGMA table_info({tmp})").fetchall()]
        if not existing:
            c.execute(f"CREATE TABLE {table} AS SELECT * FROM {tmp} WHERE 0")
            existing = set(tmp_cols)
        for col in tmp_cols:
            if col not in existing:
                c.execute(f'ALTER TABLE {table} ADD COLUMN "{col}"')

        # 3) UNIQUE INDEX 가 있어야 INSERT OR REPLACE 가 row-level UPSERT 로 동작.
        c.execute(
            f"CREATE UNIQUE INDEX IF NOT EXISTS idx_{table}_ts "
            f"ON {table}(timestamp)"
        )

        # 4) 본 테이블 컬럼 전체에 대해 INSERT OR REPLACE.  배치에 없는 컬럼은
        #    SELECT 에서 자연히 NULL (이미 있던 행이면 그 컬럼은 NULL 로 덮어쓰일
        #    수 있음 — UPSERT 의 한계.  배치는 항상 같은 카테고리 셋이라 실무상 OK.)
        full_cols = [r[1] for r in c.execute(f"PRAGMA table_info({table})").fetchall()]
        select_exprs = [
            f'"{col}"' if col in tmp_cols else 'NULL' for col in full_cols
        ]
        col_list = ', '.join(f'"{col}"' for col in full_cols)
        c.execute(
            f"INSERT OR REPLACE INTO {table} ({col_list}) "
            f"SELECT {', '.join(select_exprs)} FROM {tmp}"
        )
        n_written = c.execute("SELECT changes()").fetchone()[0]
        c.execute(f"DROP TABLE {tmp}")
    return n_written


# partial_upsert 는 _common 으로 이동 (제주/육지 공통).  위에서 import.


def write_to_forecast(wide: pd.DataFrame, db_path: Path) -> int:
    """forecast 테이블에 partial UPSERT.

    partial_upsert 사용 이유: 같은 timestamp 행에 다른 ingest 경로가 채워둔 컬럼을
    build() 의 새 batch (KIMR/KIMG/*_da)가 덮어쓰지 않도록 (배치에 없는 컬럼은 보존).
    """
    return partial_upsert(FORECAST_TABLE, wide, db_path)


def write_to_historical(wide: pd.DataFrame, db_path: Path) -> int:
    """historical 테이블에 partial UPSERT.

    partial_upsert 사용 이유: build_historical() 의 새 batch (*_jeju/asos/*_da)가
    같은 timestamp 행의 다른 컬럼 -- 특히 recompute_jeju_capacity 가 별도로 채우는
    real_*_capacity_jeju / real_*_utilization_jeju -- 를 덮어쓰지 않도록 (배치에 없는
    컬럼은 보존).
    """
    return partial_upsert(HISTORICAL_TABLE, wide, db_path)


# ── public entry ────────────────────────────────────────────────────────
@contextmanager
def forecast_days_override(days: int | None):
    """forecast 수집 윈도우 길이를 임시로 바꾼다 (api_fetchers_land 의 동형).

    제주 forecast 는 두 모듈의 FORECAST_DAYS 글로벌을 호출 시점에 읽는다 --
    KIMR 쪽(api_fetchers_jeju: collection_window/ef_param_for)과 KIMG 쪽
    (_common: collection_window/collection_hf_range).  둘 다 바꿔야 윈도우가
    일관되게 늘어난다.  days=None 이면 no-op (기본 2일 유지).

    소스별 lead 한계 (00/12 UTC 발표 probe, 2026-06-12~13):
    - KIMR(지역): 120h=D+5 까지, 전 구간 1h.
    - KIMG(전구): 288h=D+12 까지, 단 1h 는 135h 까지고 이후는 3h 간격만 존재.
    D+5 초과 윈도우에서는 build_wide 가 KIMG 변수(kimg_one_point)로 빈 구간을
    채운다 (KIMR 전용 변수는 NaN, D+6~ 는 3h 행만).
    """
    if days is None:
        yield
        return
    prev_kim, prev_kimg = kim.FORECAST_DAYS, kimg.FORECAST_DAYS
    kim.FORECAST_DAYS = kimg.FORECAST_DAYS = days
    try:
        yield
    finally:
        kim.FORECAST_DAYS, kimg.FORECAST_DAYS = prev_kim, prev_kimg


def _pick_bases(base: datetime | None, n_bases: int) -> list[datetime]:
    """--base 주어졌으면 그것 한 개, 아니면 최근 n_bases 발표 (오래된→최신)."""
    if base is not None:
        return [base]
    now_kst = datetime.now(tz=KST)
    latest = kim.latest_published_base(now_kst)  # KIM/KIMG 공통 publish 시각
    out: list[datetime] = []
    cur = latest
    for _ in range(max(1, n_bases)):
        out.append(cur)
        cur -= timedelta(hours=6)
    out.sort()
    return out


def _window_for(bases: list[datetime]) -> tuple[datetime, datetime]:
    """입력 발표들의 KST 윈도우 합집합 (가장 빠른 start ~ 가장 늦은 end)."""
    starts = [kim.collection_window(b)[0] for b in bases]
    ends = [kim.collection_window(b)[1] for b in bases]
    return min(starts), max(ends)


def build(
    base: datetime | None = None,
    n_bases: int = 2,
    save: bool = True,
    db_path: Path = DEFAULT_DB,
    kim_workers: int = 1,
    forecast_days: int | None = None,
) -> pd.DataFrame:
    """API 호출 → 후처리 → (선택) forecast 테이블 UPSERT.  wide DataFrame 반환.

    파라미터
    - base: 특정 UTC datetime 단일 발표를 지정.  None 이면 최근 n_bases 발표.
    - n_bases: base=None 일 때 직전 몇 발표까지 받을지 (기본 2, safety re-fetch).
    - save: True 면 db_path 의 forecast 테이블에 UPSERT.  False 면 메모리 DF 만 반환.
    - db_path: 출력 SQLite 경로 (기본 data/input_data_jeju.db).
    - kim_workers: KIMR fetch 병렬 수 (1 = sequential).  KIMG 는 항상 hf workers=6.
    - forecast_days: 윈도우 길이(일).  None=기본 2일.  7 이면 D+1~D+5 는
      KIMR 1h + D+6~D+7 은 KIMG 3h 행으로 채워진다 (forecast_days_override 참조).
    """
    with forecast_days_override(forecast_days):
        if forecast_days is not None:
            print(f"  [kim-jeju] FORECAST_DAYS override = {forecast_days} day(s)")
        bases = _pick_bases(base, n_bases)
        window_start, window_end = _window_for(bases)

        print(
            f"[collect_data_jeju] bases={len(bases)} "
            f"({bases[0].strftime('%Y%m%d%H')} ~ {bases[-1].strftime('%Y%m%d%H')} UTC), "
            f"window=[{window_start:%Y-%m-%d %H:%M} ~ {window_end:%Y-%m-%d %H:%M}) KST, "
            f"target table='{FORECAST_TABLE}' (UPSERT)"
        )

        print("\n[1/3] fetch KIMR (regional)")
        kimr_long = fetch_kimr_long(bases, workers=kim_workers)
        print(
            f"  KIMR long: {len(kimr_long):,} rows, "
            f"{kimr_long['point_name'].nunique()} points, "
            f"{kimr_long['category'].nunique()} categories, "
            f"{kimr_long['base_datetime'].nunique()} bases"
        )

        print("\n[2/3] fetch KIMG (global)")
        kimg_long = fetch_kimg_long(bases)
        if kimg_long.empty:
            print("  KIMG long: empty (radiation_south will be MISSING from output)")
        else:
            print(
                f"  KIMG long: {len(kimg_long):,} rows, "
                f"{kimg_long['point_name'].nunique()} points, "
                f"{kimg_long['category'].nunique()} categories, "
                f"{kimg_long['base_datetime'].nunique()} bases"
            )

    print("\n[3/3] pivot to wide + post-processing")
    try:
        wide = build_wide(kimr_long, kimg_long, window_start, window_end)
    except NoUsableForecastRows as e:
        print(f"  [WARN] {e} -- forecast 단계 건너뜀 (historical 등은 계속).")
        return pd.DataFrame()
    print(
        f"  wide: {len(wide):,} rows x {len(wide.columns)} cols "
        f"(NaN ratio = {wide.isna().mean().mean():.2%})"
    )

    # KPX est (DA SMP + 제주 예상수요) 를 forecast 윈도우의 날짜 범위로 호출해
    # left-join.  발행 안 된 미래 일자는 빈 응답 -> 해당 hour 의 컬럼은 NaN 유지
    # (UPSERT 가 그 자리에 NULL 을 쓰지만, 다음 실행에서 발행되면 덮어쓰임).
    # upsert_wide_to 는 ALTER TABLE ADD COLUMN 으로 schema 를 자동 확장하므로
    # 신규 컬럼(smp_jeju_da / smp_land_da / jeju_est_demand_da) 추가 마이그레이션 불필요.
    print("\n[*_da] smp_jeju_da + smp_land_da + jeju_est_demand_da")
    fwin_start_date = window_start.strftime("%Y-%m-%d")
    fwin_end_date = (window_end - timedelta(seconds=1)).strftime("%Y-%m-%d")
    try:
        kpx_est_df = kpx.fetch_kpx_est(fwin_start_date, fwin_end_date)
    except Exception as e:
        print(f"  [WARN] *_da fetch failed: {e}")
        kpx_est_df = pd.DataFrame()
    if not kpx_est_df.empty:
        wide = wide.join(kpx_est_df, how="left")
        n_est = (
            wide["jeju_est_demand_da"].notna().sum()
            if "jeju_est_demand_da" in wide.columns else 0
        )
        print(f"  joined *_da ({n_est}/{len(wide)} hours have jeju_est_demand_da)")
    else:
        print("  [WARN] *_da empty for forecast window -- columns omitted")

    print("\n[postprocess] range clip + day_type")
    wide = pp.clip_ranges(wide)
    wide = pp.add_day_type(wide)

    if save:
        n = write_to_forecast(wide, db_path)
        print(f"\n  UPSERT forecast: {n:,} rows -> {db_path}")
    return wide


# ── _jeju capacity / utilization 파생 (historical 전체 기간 누적 max) ─────
def recompute_jeju_capacity(db_path: Path = DEFAULT_DB) -> int:
    """historical 의 real_wind_gen_jeju / real_solar_gen_jeju 전체 시계열로 capacity +
    utilization 4개 파생 컬럼을 계산해 historical 에 다시 UPSERT.

    육지 collect_data_land.recompute_kr_capacity 와 같은 로직:
    capacity ~= 설비용량 근사 = 발전량의 running max(cummax), 단 첫 해(2020) 전체는
    그 해 peak 로 평탄화(첫 행 야간 저점에서 시작하는 cummax 왜곡 방지).  이후 설비
    증설을 반영해 단조 증가.  utilization = 발전량 / capacity (이용률).

    cummax 는 전체 기간 문맥이 필요하므로 batch postprocess 가 아니라 여기서 historical
    전체를 읽어 재계산한다.  매번 전체 재계산이라 idempotent (cummax 는 단조라 과거 행은
    안 바뀌고, 새 발전량 peak 만 이후 capacity 를 갱신).
    """
    if not db_path.exists() or db_path.stat().st_size == 0:
        print("  [jeju-capacity] DB 없음 -- skip")
        return 0
    base_cols = sorted(set(_JEJU_CAPACITY_SPEC.values()))
    with sqlite3.connect(db_path) as c:
        existing = {r[1] for r in c.execute(
            f"PRAGMA table_info({HISTORICAL_TABLE})").fetchall()}
        if not existing:
            print("  [jeju-capacity] historical 테이블 없음 -- skip")
            return 0
        avail = [col for col in base_cols if col in existing]
        if not avail:
            print("  [jeju-capacity] real_wind_gen_jeju / real_solar_gen_jeju 부재 -- skip")
            return 0
        cols_sql = ", ".join(f'"{col}"' for col in ["timestamp", *avail])
        df = pd.read_sql(
            f"SELECT {cols_sql} FROM {HISTORICAL_TABLE} ORDER BY timestamp", c,
        )
    if df.empty:
        print("  [jeju-capacity] historical 비어있음 -- skip")
        return 0

    df = df.set_index("timestamp")
    out = pd.DataFrame(index=df.index)
    # capacity 하한 = 첫 해(2020) 발전량 최대값 -> 첫 해 전체를 그 해 peak 로 평탄화.
    first_year = df.index[0][:4]
    in_first_year = df.index.str[:4] == first_year
    for cap_col, gen_col in _JEJU_CAPACITY_SPEC.items():
        if gen_col not in df.columns:
            continue
        gen = pd.to_numeric(df[gen_col], errors="coerce")
        floor = gen[in_first_year].max()
        # cummax 는 NaN 위치를 NaN 으로 남긴다 -> ffill 로 중간 결측을 직전 max 로 채우고,
        # 선두(첫 valid 이전) NaN 은 floor 로 채운 뒤 clip 으로 첫 해를 floor 로 평탄화.
        # (clip 은 NaN 을 올리지 못하고 ffill 은 선두 NaN 을 못 채우므로 순서가 중요.)
        cap = gen.cummax().ffill()
        if pd.notna(floor):
            cap = cap.fillna(floor).clip(lower=floor)
        out[cap_col] = cap
    for util_col, (gen_col, cap_col) in _JEJU_UTILIZATION_SPEC.items():
        if gen_col not in df.columns or cap_col not in out.columns:
            continue
        gen = pd.to_numeric(df[gen_col], errors="coerce")
        cap = out[cap_col]
        out[util_col] = (gen / cap.where(cap > 0)).replace([np.inf, -np.inf], np.nan)

    out = out.dropna(how="all")
    if out.empty:
        print("  [jeju-capacity] 계산 결과 없음 -- skip")
        return 0
    out.index.name = "timestamp"
    n = partial_upsert(HISTORICAL_TABLE, out, db_path)
    print(
        f"  [jeju-capacity] {list(out.columns)} over {len(out):,} rows -> UPSERT {n:,}"
    )
    return n


# ── Historical (관측 데이터) ────────────────────────────────────────────
def build_historical(
    n_days_back: int = 2,
    end_date: str | None = None,
    save: bool = True,
    db_path: Path = DEFAULT_DB,
) -> pd.DataFrame:
    """과거 N 일치 관측 + DA 가격/수요 데이터를 wide 로 합쳐 historical 에 UPSERT.

    소스 (collect_kpx_asos_data 의 fetcher 재사용; 제주 전용 — 육지 수급/발전은
    collect_data_land.py 로 분리됨):
        kpx.fetch_kpx_jeju    : 제주(chejusukub) 계통 수급     -> *_jeju cols
        kpx.fetch_asos        : KMA ASOS 3지점 관측             -> *_west/_east/_south
        kpx.fetch_kpx_est     : DA SMP + 예상수요(제주/육지)    -> smp_*_da,
                                *_est_demand_da (forecast 와 동일 컬럼을 historical
                                에도 누적, legacy ingest 정책 정합).
        kpx.fetch_kpx_jeju_rt_smp : 제주 실시간시장 RT SMP      -> smp_rt_g1..g4,
                                smp_jeju_rt, smp_rt_neg_num (4단계 SMP 모델 타깃;
                                구간 원시값 + 파생, historical 전용).

    파라미터
    - n_days_back : end_date 로부터 거꾸로 몇 일치를 받을지.  기본 2 일
                    (D-2 ~ today, daily 탑업).  --backfill N 에서는 N 을 그대로 전달.
    - end_date    : 'YYYY-MM-DD'.  None 이면 KST 기준 today.
    - save        : True 면 historical 테이블에 UPSERT.  False 면 wide 만 반환.
    - db_path     : 기본 data/input_data_jeju.db (forecast 와 같은 파일, 다른 테이블).

    Returns: wide DataFrame (timestamp 인덱스, ~47 cols).
    """
    today_kst = datetime.now(tz=KST).date()
    end = (
        today_kst if end_date is None
        else datetime.strptime(end_date, "%Y-%m-%d").date()
    )
    start = end - timedelta(days=n_days_back)
    s_str = start.strftime("%Y-%m-%d")
    e_str = end.strftime("%Y-%m-%d")

    print(
        f"[collect_data_jeju] historical window={s_str} ~ {e_str}  "
        f"target table='{HISTORICAL_TABLE}' (UPSERT)"
    )

    print("\n[H1/4] fetch *_jeju cols (chejusukub)")
    try:
        jeju = kpx.fetch_kpx_jeju(s_str, e_str)
    except Exception as e:
        print(f"  [WARN] *_jeju failed: {e}")
        jeju = pd.DataFrame()
    print(f"  *_jeju:    {len(jeju):,} rows x {len(jeju.columns)} cols")

    print("\n[H2/4] fetch KMA ASOS (3 stations)")
    try:
        asos = kim.fetch_asos(s_str, e_str)   # ASOS 는 kma_fetcher_jeju 로 이동
    except Exception as e:
        print(f"  [WARN] asos failed: {e}")
        asos = pd.DataFrame()
    print(f"  asos:      {len(asos):,} rows x {len(asos.columns)} cols")

    # *_da (DA SMP + 제주/육지 예상수요) 를 historical 에도 저장.  build() 가
    # forecast 에 저장하는 것과 같은 데이터를 historical 에도 동일 컬럼명으로 누적
    # -- legacy ingest 가 jeju_energy.db::historical_data 의 SMP/est 를 양쪽
    # 테이블에 적재한 정책과 정합.  _da 접미사 덕분에 historical 의 다른 (관측치)
    # 컬럼과 충돌 없음.
    print("\n[H3/4] fetch *_da (smp_*_da + jeju/land_est_demand_da)")
    try:
        kest = kpx.fetch_kpx_est(s_str, e_str)
    except Exception as e:
        print(f"  [WARN] *_da failed: {e}")
        kest = pd.DataFrame()
    print(f"  *_da:      {len(kest):,} rows x {len(kest.columns)} cols")

    # 제주 실시간시장 RT SMP (smp_rt_g1..g4 + smp_jeju_rt + smp_rt_neg_num).  매일
    # 23:00 KST 발행이라 지연·미발행 날짜는 빈 응답(누락) -- partial_upsert COALESCE 가
    # 기존값 보존.  historical 전용 (RT 는 실현치).  4단계 SMP 모델의 타깃.
    print("\n[H4/4] fetch RT SMP (smp_rt_g1..g4 + smp_jeju_rt + smp_rt_neg_num)")
    try:
        rt_smp = kpx.fetch_kpx_jeju_rt_smp(s_str, e_str)
    except Exception as e:
        print(f"  [WARN] rt_smp failed: {e}")
        rt_smp = pd.DataFrame()
    print(f"  rt_smp:    {len(rt_smp):,} rows x {len(rt_smp.columns)} cols")

    parts = [df for df in (jeju, asos, kest, rt_smp) if not df.empty]
    if not parts:
        print("  [WARN] all historical sources empty -- nothing to write")
        return pd.DataFrame()

    # 컬럼이 disjoint 하므로 axis=1 concat 안전.  index(=timestamp 문자열)는
    # outer-aligned -> 일부 소스에만 있는 시간은 다른 컬럼이 NaN 으로 채워짐.
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
        # 제주 발전실적(real_*_gen_jeju)이 갱신됐으니 capacity/utilization 파생을 전체
        # 기간 기준 재계산 (cummax 는 단조라 과거 행은 그대로, 새 peak 만 이후 갱신).
        print("\n[jeju-capacity] recompute wind/solar capacity + utilization (_jeju)")
        recompute_jeju_capacity(db_path)
    return wide


# ── Backfill ────────────────────────────────────────────────────────────
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


def _expected_timestamps_for(base_utc: datetime) -> set[str]:
    """한 base 의 collection_window 가 만들 timestamp 문자열 집합 (KST, 초포함)."""
    ws, we = kim.collection_window(base_utc)
    n_hours = int((we - ws).total_seconds() // 3600)
    return {
        (ws + timedelta(hours=h)).strftime("%Y-%m-%d %H:%M:%S")
        for h in range(n_hours)
    }


def run_backfill(
    n_days: int,
    db_path: Path = DEFAULT_DB,
    kim_workers: int | None = None,
) -> int:
    """과거 N 일치 forecast 데이터 백필.  forecast 테이블에 UPSERT.

    - 처리 단위: BACKFILL_CHUNK_SIZE base 씩 fetch → build_wide → UPSERT.
    - KIMR workers: 지정 없으면 collect_kimr.workers_for_backfill(n_days) 사용
      (N>3 이면 6, 아니면 1).  KIMG 은 외부 sequential / hf workers=6 (firm 규칙).
    - Resume-skip: 한 base 가 만들어낼 모든 timestamp 가 이미 forecast 에 있으면
      그 base 는 fetch 자체를 건너뛴다 (재실행 시 네트워크 절약).
    - 반환: 총 UPSERT 된 행 수.
    """
    now_kst = datetime.now(tz=KST)
    bases = kim.backfill_bases(n_days, now_kst)
    if not bases:
        print(f"[backfill] no bases in window for {n_days} days")
        return 0

    if kim_workers is None:
        kim_workers = kim.workers_for_backfill(n_days)

    existing_ts = _existing_timestamps(db_path, FORECAST_TABLE)
    bases_todo: list[datetime] = []
    for b in bases:
        if _expected_timestamps_for(b).issubset(existing_ts):
            continue
        bases_todo.append(b)
    skipped = len(bases) - len(bases_todo)

    print(
        f"[backfill] n_days={n_days} -> {len(bases)} bases  "
        f"(skipped={skipped} already-in-forecast, todo={len(bases_todo)})"
    )
    print(
        f"           KIMR workers={kim_workers}, KIMG outer=sequential / "
        f"hf workers={kimg.MAX_WORKERS}, chunk={BACKFILL_CHUNK_SIZE} bases"
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
        ws, we = (
            min(kim.collection_window(b)[0] for b in chunk),
            max(kim.collection_window(b)[1] for b in chunk),
        )
        kimr_long = fetch_kimr_long(chunk, workers=kim_workers)
        kimg_long = fetch_kimg_long(chunk)
        try:
            wide = build_wide(kimr_long, kimg_long, ws, we)
        except NoUsableForecastRows:
            print("  [backfill] chunk had no usable KIMR rows, skipping")
            continue
        wide = pp.clip_ranges(wide)
        wide = pp.add_day_type(wide)
        n = write_to_forecast(wide, db_path)
        total_written += n
        elapsed = time.time() - t0
        rate = (ci_idx + 1) / elapsed if elapsed > 0 else 0
        eta_min = (n_chunks - ci_idx - 1) / rate / 60 if rate > 0 else 0
        print(
            f"  [backfill] chunk done: UPSERT {n:,} rows  "
            f"(total {total_written:,}, elapsed {elapsed/60:.1f}m, eta {eta_min:.1f}m)"
        )

    print(
        f"\n[backfill] done: {total_written:,} rows total in "
        f"{(time.time()-t0)/60:.1f}m -> {db_path}"
    )
    return total_written


# ── CLI ─────────────────────────────────────────────────────────────────
def main() -> None:
    p = argparse.ArgumentParser(
        description=(
            "Direct API -> post-processing -> input_data_jeju.db "
            "(forecast + historical tables).  Forecast: KIMR+KIMG+KPX-est.  "
            "Historical: KPX 제주 수급 + KMA ASOS 3지점.  (육지는 collect_data_land.py)"
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
        help=(
            "backfill last N days (UPSERT, resume-skip).  Forecast: per-publish "
            "loop (KIMR workers=6 when N>3).  Historical: single D-N~today fetch."
        ),
    )
    p.add_argument(
        "--bases", type=int, default=2,
        help="when neither --base nor --backfill: how many recent publishes (default 2)",
    )
    p.add_argument(
        "--historical-days", type=int, default=2,
        help="historical window length in days (default 2 = D-2~today top-up)",
    )
    p.add_argument(
        "--no-forecast", action="store_true",
        help="skip forecast build (KIMR + KIMG + *_da)",
    )
    p.add_argument(
        "--no-historical", action="store_true",
        help="skip historical build (*_jeju + asos + *_da)",
    )
    p.add_argument(
        "--db", type=Path, default=DEFAULT_DB,
        help=f"SQLite path (default {DEFAULT_DB})",
    )
    p.add_argument(
        "--kim-workers", type=int, default=None,
        help="KIMR fetch parallelism (default: 6 if --backfill>3, else 1)",
    )
    p.add_argument(
        "--forecast-days", type=int, default=None, metavar="N",
        help=(
            "forecast window length in days (default 2=48h).  7 = long-horizon: "
            "D+1~D+5 from KIMR (1h), D+6~D+7 from KIMG (3h rows only).  Use with "
            "the 00:10 KST cron run (= 12 UTC publish).  Not applied to --backfill."
        ),
    )
    p.add_argument(
        "--no-save", action="store_true",
        help="skip DB write (dry-run, prints summary). Ignored with --backfill.",
    )
    args = p.parse_args()

    if args.no_forecast and args.no_historical:
        sys.exit("--no-forecast and --no-historical together means nothing to do")

    if args.backfill is not None:
        if args.no_save:
            sys.exit("--no-save is not supported with --backfill")
        t0 = time.time()
        if not args.no_forecast:
            print(f"\n=== forecast backfill (N={args.backfill}) ===")
            run_backfill(args.backfill, db_path=args.db, kim_workers=args.kim_workers)
        if not args.no_historical:
            print(f"\n=== historical backfill (N={args.backfill}) ===")
            build_historical(
                n_days_back=args.backfill, save=True, db_path=args.db,
            )
        print(f"\n[collect_data_jeju] done in {(time.time()-t0)/60:.1f}m")
        return

    base = None
    if args.base:
        base = datetime.strptime(args.base[0] + args.base[1], "%Y%m%d%H").replace(
            tzinfo=UTC,
        )

    kim_workers = args.kim_workers if args.kim_workers is not None else 1

    t0 = time.time()
    if not args.no_forecast:
        print("\n=== forecast build ===")
        build(
            base=base, n_bases=args.bases, save=not args.no_save,
            db_path=args.db, kim_workers=kim_workers,
            forecast_days=args.forecast_days,
        )
    if not args.no_historical:
        print(f"\n=== historical build (last {args.historical_days} days) ===")
        build_historical(
            n_days_back=args.historical_days, save=not args.no_save,
            db_path=args.db,
        )
    print(f"\n[collect_data_jeju] done in {time.time() - t0:.1f}s")


if __name__ == "__main__":
    main()

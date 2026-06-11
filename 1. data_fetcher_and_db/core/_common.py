"""
_common.py -- 제주/육지 파이프라인 공통 인프라 (2026-06-01 compaction).

여기 모인 것 (이 모듈은 자체 CLI / DB 적재 진입점이 없다 -- 라이브러리 전용):
  * paths / env       : _REPO_ROOT, load_dotenv, KMA_API_KEY(=AUTH_KEY) / KPX_API_KEY
  * KIMG core         : http(fetch_one_hf) / parse_response / derive_categories /
                        발표시각·윈도우 계산 / open_db·insert_rows / collect_one_point.
                        kma_fetcher_jeju (제주 KIMG) 와 kma_fetcher_land (육지 KIMG)
                        둘 다 이 core 를 import 해 POINTS / 출력 DB 만 바꿔 쓴다.
  * KMA ASOS primitive: _fetch_asos_one_station_chunk (제주 fetch_asos / 육지 ASOS
                        수집기가 공유).
  * KPX helpers       : _chunk_date_range / _decode_kpx / KPX_BASE_HEADERS (kpx_fetcher
                        _jeju·_land 가 공유; SMP/est fetcher 자체는 양쪽에 중복 보유).
  * DB UPSERT         : partial_upsert (제주/육지 파이프라인 공통 write helper).
  * freshest          : (point, fcst_datetime, category) 별 최신 base 한 줄 선택.

구 collect_kimg.py 의 standalone collect()/run_backfill()/CLI 는 제거됐다 -- 육지
수집은 kma_fetcher_land 가, 제주 forecast 는 collect_data_jeju 가 fetch_one_hf 를
직접 호출한다.  아래 KIMG 관련 주석은 구 collect_kimg.py 에서 그대로 가져온 것.

원본(구 KIMG 수집기) 설명:
KMA API Hub 의 KIMG(Korea Integrated Model -- Global) 표면예보 격자점 자료를
받아 두 제주 지점(solar_farm(south) / West(Gosan)) 의 행을 SQLite 에 적재.

이 수집기의 존재 이유
- Village / KIM 지역 모델 둘 다 일사량(downward shortwave radiation)을 제공하지
  않는다. 태양광 발전 예측을 위해 KIMG 가 유일한 선택지. Resolution 은 sparse
  하지만 대안이 없음.
- 동시에 KIMG 의 cloud cover (TCLD / LCLD+MCLD) 도 확보 -- Village 의 SKY 는
  categorical (1-4), 본 변수는 fraction (0~1) 이라 회귀 모델 입력에 유리.

수집 카테고리 (9, 모두 변환 후 저장)
    SOLAR_RAD     (dswrsfc x 0.0036) -> MJ/m^2/h         [핵심, KIMG only]
    TCLD          (tcld 원본)         -> fraction 0~1     [핵심, KIMG only]
    MIDLOW_CLOUD  (lcld + mcld*(1-lcld)) -> fraction 0~1  [핵심, KIMG only]
    TEMP_C        (t2m - 273.15)      -> Celsius          [parity: Village TMP]
    WIND_U_10M    (u10m 원본)         -> m/s              [parity: KIM WIND_U_10M]
    WIND_V_10M    (v10m 원본)         -> m/s              [parity: KIM WIND_V_10M]
    REH           (rh2m 원본)         -> % (0~100)        [육지 reh, 2026-06-08 추가]
    RAIN_CONV     (rainc_acc 원본)    -> kg/m^2 (누적)     [육지 rainfall, 누적 raw]
    RAIN_STRAT    (rainl_acc 원본)    -> kg/m^2 (누적)     [육지 rainfall, 누적 raw]
    * REH/RAIN_* 는 육지 forecast(collect_data_land)에서만 wide 로 쓰인다.  제주
      build_wide 는 KIMG 의 SOLAR_RAD 만 사용하므로 이 카테고리들은 제주에서 무시된다.
      RAIN_* 는 누적값이라 시간당 강수 변환(diff)은 wide 단계에서 한다.

* 다른 collector 들은 "원본 그대로 저장" 규칙이지만, 위 3 변환(SOLAR/TEMP/MIDLOW)
  은 변환식이 표준 / 1-way / 후처리 부담 큼이라 저장 시점에 처리.  WIND U/V 는
  KIM 과 동일 키 이름으로 두 DB cross-join 시 즉시 비교 가능하게 raw 유지.

핵심 규칙
- 발표 시각(UTC): 00, 06, 12, 18  -> 1일 4회 (KST 09, 15, 21, 03 익일)
- 발표 후 데이터 가용까지 지연 ~2시간 -- 안전마진 3시간
- 수집 윈도우 (day-aligned, KST 기준): [D+1 00 KST, D+3 00 KST), 2일치 hourly
  -> 한 발표 / 지점 당 정확히 48 시간 분의 hf 호출 (UTC 발표시각에 따라
     hf=3..50 / 9..56 / 15..62 / 21..68 중 하나)
- INSERT OR IGNORE + per-(base, point, fcst_datetime) skip -- backfill 도중
  중단 시 재실행하면 이미 받은 시간은 호출조차 하지 않음 (네트워크 절약).

KIMG API 의 특별한 점 (KIM 지역과 다른 부분)
- 엔드포인트가 완전히 다름: typ01/.../nph-kim_nc_pt_txt2  (KIM-R 는 typ06).
- 격자 X/Y 없음 -- lat / lon 을 직접 입력.  Resolution 이 sparse 해서 인접
  지점이 같은 셀로 떨어질 수 있음.  본 수집기는 2 지점만 유지:
    solar_farm(south) (33.3284, 126.8366)  -- 태양광 단지 (핵심)
    West(Gosan)       (33.4427, 126.1713)  -- 고산 (KIM 과 join 가능한 풍력 지점)
  East(Seongsan) 은 KIM 지역모델에서 충분히 커버되므로 제외.
- hf 는 단일 시간 (range / step 미지원).  48시간 윈도우 = 48회 호출 / (발표, 지점).
  --> 4 발표 x 2 지점 x 48 hf = 384 호출/일 (ongoing).  Quota 의 ~2%.
- name= 파라미터에 콤마로 여러 변수 (KIM 의 varn= 와 동일 패턴).
- 응답 plaintext 포맷도 동일하나, VARN 은 단일 자리수 ~ 두 자리 정수 (51/25/...).
- 병렬 hf 처리 (workers=6) -- 한 (발표, 지점) 안에서 48 hf 를 동시 호출.
  지속적인 shared Session(HTTPAdapter 풀)+ warmup + retry-on-5xx-backoff 스택
  필수.  바깥 (발표, 지점) 루프는 순차 유지 (peak concurrency 6 으로 cap).
  api_fetchers.py 의 fetch_kma_future_ncm 와 동일 패턴.  단순 ThreadPoolExecutor
  + 별다른 retry 없이 호출하면 transient 504 가 즉시 실패로 전파됨 (2026-05-24
  KIMR 사례).  retry-with-backoff 가 실측 13% 호출에서 작동.

사용 예
    python collect_kimg.py                          # 가장 최근 2 발표 (safety 재수집)
    python collect_kimg.py --base 20260523 12       # 특정 UTC 발표
    python collect_kimg.py --backfill 30            # 최근 30 일 일괄 backfill (~2h, workers=6)
    python collect_kimg.py --backfill 150 --issues 18  # day-ahead 전용 (18 UTC=03 KST 발표만, ~4x 빠름)
    python collect_kimg.py --db ./data/kimg.db

Day-ahead 백필 노트 (--issues)
- 본 프로젝트 모델은 day-ahead 입찰용 (마감 D-1 11:00 KST).  KIMG 는 공개지연이
  ~2-3h 라 D-1 00 UTC(09 KST) 발표는 11:00 마감 전에 reliably 가용하지 못한다.
  마감 전 가용한 가장 fresh 한 KIMG 발표는 D-2 18 UTC(=03 KST, ~05-06 KST 가용)
  -- 그래서 day-ahead 백필은 `--issues 18` 로 18 UTC 발표만 받으면 충분하고,
  4발표 중 1개라 호출수가 ~1/4 (150일 ~12h -> ~3h).  kimg.db 에 18 UTC 발표만
  쌓이므로 collect_input.py 의 freshest() 가 자연히 그 day-ahead 값을 고른다
  (다운스트림 수정 불필요).  KIMR 은 공개지연 ~15분 이라 day-ahead 발표가 00 UTC
  (09 KST) 라 KIMG 와 다르다 -- KIMR 의 day-ahead 선택은 다운스트림(collect_input)
  의 별도 과제.  --issues 미지정 시 4발표 모두 (lead-time EDA 보존, 기존 동작).
"""
from __future__ import annotations

import io
import os
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterator
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from dotenv import load_dotenv

load_dotenv()

# ── 설정 ────────────────────────────────────────────────────────────────
KST = ZoneInfo("Asia/Seoul")
UTC = timezone.utc

_REPO_ROOT = Path(__file__).resolve().parent.parent

# KMA / KPX 인증키 (.env).  AUTH_KEY 는 구 collect_kimg 코드 호환 별칭.
KMA_API_KEY = os.getenv("KMA_API_KEY")
AUTH_KEY = KMA_API_KEY
KPX_API_KEY = os.getenv("KPX_API_KEY")

BASE_URL = "https://apihub.kma.go.kr/api/typ01/cgi-bin/url/nph-kim_nc_pt_txt2"

# 수집 지점 (lat, lon).  KIMG 는 격자 X/Y 가 아니라 lat/lon 직접 입력.
# point_name 은 다른 .db 들과 cross-join 용 -- West(Gosan) 표기는
# data/kimr.db (kimr_forecast) / data/forecast.db (village_forecast) 와 일치시킴.
POINTS = [
    {"name": "solar_farm(south)", "lat": 33.3284, "lon": 126.8366},  # 남쪽 태양광 단지
    {"name": "West(Gosan)",       "lat": 33.4427, "lon": 126.1713},  # 서쪽(고산)
    # East(성산) 은 KIMR 이 커버해 제외했었으나, KIMR lead 한계(120h) 이후의 장지평
    # 구간(D+6~)은 KIMG 만 가용하므로 3지점 구조 유지를 위해 추가 (2026-06-13).
    # 좌표는 ASOS 188(성산) -- KIMR East(553,254) 격자와 같은 일대.
    {"name": "East(Seongsan)",    "lat": 33.3868, "lon": 126.8802},  # 동쪽(성산) -- 풍력
]

# 발표 시각 (UTC).  KST 로는 09 / 15 / 21 / 03(익일).
ISSUE_HOURS_UTC = (0, 6, 12, 18)

# 발표 후 데이터 가용까지의 안전 마진.  관찰상 ~2시간이면 충분하나 여유 3h.
PUBLISH_DELAY_HOURS = 3

# day-aligned 수집 윈도우 길이 (D+1 00 KST 부터 N 일).
FORECAST_DAYS = 2

# API 호출에 묶을 변수 목록 (콤마 구분).  KIM 의 varn= 와 같은 패턴.
# rh2m(2m 습도) / rainc_acc(누적 대류강수) / rainl_acc(누적 대규모강수) 는 2026-06-08
# 추가 -- 육지 forecast 에 reh/rainfall 을 KIMG 로 채우기 위함 (api_fetchers_nouse
# .fetch_kma_future_ncm 의 변수/varn 참조).
# u80m/v80m/gust 는 2026-06-13 추가 -- KIMR lead 한계(120h=D+5) 이후 장지평 구간의
# 풍력 입력을 KIMG 로 잇기 위함.  cape/cinn/hpbl/tcog/tcoh 는 KIMG 에 없음
# ("Variable not found", probe 2026-06-13).
NAME_PARAM = "dswrsfc,t2m,tcld,mcld,lcld,u10m,v10m,rh2m,rainc_acc,rainl_acc,u80m,v80m,gust"

# 응답 varn 코드 -> 내부 raw 이름.  derive_categories 가 이 dict 으로부터
# 최종 카테고리(저장 형식)를 생성한다.  여기에 없는 varn 은 무시.
RAW_VARN_MAP = {
    51: "dswrsfc",    # downward shortwave at surface (W/m^2) -- 일사량
    25: "t2m",        # 2m 기온 (K)
    37: "tcld",       # total cloud cover (fraction 0~1)
    35: "mcld",       # mid cloud (fraction)
    34: "lcld",       # low cloud (fraction)
    20: "u10m",       # 10m U wind (m/s)
    21: "v10m",       # 10m V wind (m/s)
    22: "u80m",       # 80m U wind (m/s)           -> WIND_U_80M
    23: "v80m",       # 80m V wind (m/s)           -> WIND_V_80M
    24: "gust",       # gust (m/s)                 -> GUST
    26: "rh2m",       # 2m 상대습도 (%)            -> REH
    65: "rainc_acc",  # 누적 대류 강수 (kg/m^2)     -> RAIN_CONV (누적, raw)
    66: "rainl_acc",  # 누적 대규모 강수 (kg/m^2)   -> RAIN_STRAT (누적, raw)
}

# 병렬 호출 설정.  probe_kim_parallel.py 결과상 6 이 안정 상한 (3.2x 실측 속도향상,
# 효과적 서버측 동시성 ~3).  RETRY_MAX 3 회, exponential backoff (2s, 4s).
MAX_WORKERS = 6
RETRY_MAX = 3


# ── HTTP session (TCP/TLS 재사용 + 풀) ──────────────────────────────────
# 모듈 레벨 single Session 으로 connection-pool keep-alive 유지.  병렬 burst 직전에
# warmup() 으로 TLS handshake 를 미리 확보하면 cold burst 의 ~500ms 페널티가 사라진다.
_kma_session = requests.Session()
_kma_session.mount(
    "https://apihub.kma.go.kr/",
    HTTPAdapter(pool_connections=4, pool_maxsize=20),
)


def warmup() -> None:
    """병렬 burst 전에 TCP+TLS handshake 를 미리 확보.  실패는 무시."""
    if not AUTH_KEY:
        return
    try:
        _kma_session.get(
            BASE_URL,
            params={"help": "1", "authKey": AUTH_KEY},
            timeout=10,
        )
    except Exception:
        pass


# ── 스키마 ──────────────────────────────────────────────────────────────
# Village/VSRT/KIM 과 동일한 컬럼 shape.  격자 좌표는 lat/lon (REAL).
# category 가 height 까지 인코딩하므로 별도 level 컬럼 없음.
SCHEMA = """
CREATE TABLE IF NOT EXISTS kimg_forecast (
    base_datetime  TEXT NOT NULL,
    fcst_datetime  TEXT NOT NULL,
    point_name     TEXT NOT NULL,
    lat            REAL NOT NULL,
    lon            REAL NOT NULL,
    category       TEXT NOT NULL,
    fcst_value     TEXT NOT NULL,
    collected_at   TEXT NOT NULL,
    PRIMARY KEY (base_datetime, fcst_datetime, point_name, category)
);
CREATE INDEX IF NOT EXISTS idx_kimg_fcst_dt_cat ON kimg_forecast(fcst_datetime, category);
CREATE INDEX IF NOT EXISTS idx_kimg_base_dt     ON kimg_forecast(base_datetime);
"""


# ── 시간 계산 ──────────────────────────────────────────────────────────
def latest_published_base(now_kst: datetime) -> datetime:
    """공개 지연(PUBLISH_DELAY_HOURS)을 감안한 가장 최근 가용 발표 (UTC datetime)."""
    now_utc = now_kst.astimezone(UTC)
    cutoff = now_utc - timedelta(hours=PUBLISH_DELAY_HOURS)
    candidates = []
    for day_offset in (0, -1):
        day = (cutoff + timedelta(days=day_offset)).date()
        for h in ISSUE_HOURS_UTC:
            issue = datetime(day.year, day.month, day.day, h, tzinfo=UTC)
            if issue <= cutoff:
                candidates.append(issue)
    return max(candidates)


def previous_issue(base_utc: datetime) -> datetime:
    """주어진 발표 직전 발표 (6h 전, UTC)."""
    return base_utc - timedelta(hours=6)


def backfill_bases(
    days: int, now_kst: datetime, issue_hours: tuple[int, ...] | None = None,
) -> list[datetime]:
    """가장 최근 가용 발표부터 N 일치 거꾸로.  가장 오래된 것부터 적재하도록 reverse.

    issue_hours 가 주어지면 그 UTC 발표시각만 남긴다 (예: (18,) 면 18 UTC 발표만).
    day-ahead 모델에서 마감(예: D-1 11:00 KST) 전에 가용한 KIMG 발표만 받기 위함 --
    KIMG 는 공개지연 ~2-3h 라 D-1 00 UTC(09 KST) 발표는 11:00 마감 전에 못 받고,
    D-2 18 UTC(03 KST) 발표가 마감 전 reliably 가용한 가장 fresh 한 발표.  18 UTC 만
    받으면 4개 중 1개라 backfill 호출수가 ~1/4 로 준다.  None 이면 4발표 모두(EDA용).
    """
    hours = issue_hours if issue_hours is not None else ISSUE_HOURS_UTC
    latest = latest_published_base(now_kst)
    cutoff = latest - timedelta(days=days)
    out: list[datetime] = []
    cur = latest
    while cur >= cutoff:
        if cur.hour in hours:
            out.append(cur)
        cur -= timedelta(hours=6)
    out.reverse()
    return out


def collection_window(base_utc: datetime) -> tuple[datetime, datetime]:
    """day-aligned 수집 윈도우 [start, end) KST 기준.
    base 시각의 KST 다음 자정부터 FORECAST_DAYS 일.
    """
    base_kst = base_utc.astimezone(KST)
    next_midnight = (base_kst + timedelta(days=1)).replace(
        hour=0, minute=0, second=0, microsecond=0,
    )
    return next_midnight, next_midnight + timedelta(days=FORECAST_DAYS)


# KIMG 의 1h 해상도 상한 (probe 2026-06-13, 00/12 UTC 발표 동일): hf<=135 는 매시간,
# 그 이후 ~288h 까지는 3의 배수 hf 만 데이터가 존재한다 (나머지는 빈 응답).
KIMG_HOURLY_MAX_HF = 135

def collection_hf_range(base_utc: datetime) -> list[int]:
    """day-aligned KST 윈도우를 hf(forecast offset, 시간) 리스트로 환산.
    UTC 00 / 06 / 12 / 18 발표에 대해 각각 hf=15.. / 9.. / 3.. / 21.. 시작 (기본 48개).
    hf > KIMG_HOURLY_MAX_HF(135) 구간은 3h 간격만 존재하므로 3의 배수가 아닌 hf 를
    건너뛰어 빈 호출을 만들지 않는다 (장지평 윈도우에서 호출 ~2/3 절감).
    """
    base_kst = base_utc.astimezone(KST)
    start_kst, end_kst = collection_window(base_utc)
    start_hf = int((start_kst - base_kst).total_seconds() // 3600)
    end_hf = int((end_kst - base_kst).total_seconds() // 3600)
    return [
        hf for hf in range(start_hf, end_hf)
        if hf <= KIMG_HOURLY_MAX_HF or hf % 3 == 0
    ]


# ── DB ─────────────────────────────────────────────────────────────────
def open_db(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)
    return conn


def insert_rows(conn: sqlite3.Connection, rows: list[tuple]) -> int:
    cur = conn.executemany(
        """
        INSERT OR IGNORE INTO kimg_forecast
            (base_datetime, fcst_datetime, point_name, lat, lon, category, fcst_value, collected_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )
    conn.commit()
    return cur.rowcount


def existing_fcst_datetimes(
    conn: sqlite3.Connection, base_dt_str: str, point_name: str,
) -> set[str]:
    """(base, point) 에 대해 이미 DB 에 있는 fcst_datetime 집합.
    backfill 재개 시 이미 받은 hf 의 API 호출을 생략하기 위해 사용.
    """
    rows = conn.execute(
        "SELECT DISTINCT fcst_datetime FROM kimg_forecast "
        "WHERE base_datetime = ? AND point_name = ?",
        (base_dt_str, point_name),
    ).fetchall()
    return {r[0] for r in rows}


# ── KIMG API ───────────────────────────────────────────────────────────
def parse_response(body: str) -> dict[int, float]:
    """plaintext body -> {varn_code: value}.  단일 timestep 응답 가정.
    헤더는 '#' 로 시작.  필요 없는 varn 은 RAW_VARN_MAP 단계에서 자연 필터링.
    """
    out: dict[int, float] = {}
    for ln in body.splitlines():
        s = ln.strip()
        if not s or s.startswith("#"):
            continue
        parts = s.split()
        if len(parts) < 5:
            continue
        try:
            varn = int(parts[2])
            value = float(parts[4])
        except ValueError:
            continue
        if varn in RAW_VARN_MAP:
            out[varn] = value
    return out


def derive_categories(raw: dict[int, float]) -> dict[str, float]:
    """raw {varn: value} -> {category: 저장값}.  변환식은 모듈 docstring 참조.
    누락된 입력 varn 은 해당 category 도 빠진다 (downstream 에서 NULL 처리).
    """
    out: dict[str, float] = {}
    if 51 in raw:
        # W/m^2 -> MJ/m^2/h.  1 W/m^2 = 3600 J/m^2/h = 0.0036 MJ/m^2/h.
        out["SOLAR_RAD"] = round(raw[51] * 0.0036, 4)
    if 25 in raw:
        out["TEMP_C"] = round(raw[25] - 273.15, 2)
    if 37 in raw:
        out["TCLD"] = round(raw[37], 4)
    if 34 in raw and 35 in raw:
        # random-overlap 가정의 표준 결합식.  lcld 가 mcld 일부를 가린다고 보정.
        out["MIDLOW_CLOUD"] = round(raw[34] + raw[35] * (1 - raw[34]), 4)
    if 20 in raw:
        out["WIND_U_10M"] = round(raw[20], 3)
    if 21 in raw:
        out["WIND_V_10M"] = round(raw[21], 3)
    if 22 in raw:
        out["WIND_U_80M"] = round(raw[22], 3)   # KIMR 와 동일 카테고리명 (cross-join)
    if 23 in raw:
        out["WIND_V_80M"] = round(raw[23], 3)
    if 24 in raw:
        out["GUST"] = round(raw[24], 3)
    if 26 in raw:
        out["REH"] = round(raw[26], 2)          # 2m 상대습도 (%)
    # 강수: convective + 대규모 누적값(kg/m^2)을 raw 그대로 저장한다.  시간당 강수로의
    # 변환(누적->시간차 diff)은 wide 단계(collect_data_land.kimg_land_long_to_wide)에서
    # per-base diff 로 처리 (KIMR rain 과 동일 패턴).  여기선 누적 원시값만 보존.
    if 65 in raw:
        out["RAIN_CONV"] = round(raw[65], 4)
    if 66 in raw:
        out["RAIN_STRAT"] = round(raw[66], 4)
    return out


def fetch_one_hf(base_utc: datetime, point: dict, hf: int) -> str | None:
    """단일 (publish, point, hf) 호출.  plaintext body 반환 (실패 시 None).

    내부에서 5xx + timeout/connection error 에 대해 exponential backoff (2s, 4s)
    로 최대 RETRY_MAX 회 재시도.  4xx 는 즉시 포기 (transient 가 아님).
    워커 스레드에서 호출돼도 안전 (DB / 공유 mutable state 없음).
    """
    params = {
        "group":   "KIMG",
        "nwp":     "NE57",
        "data":    "U",
        "name":    NAME_PARAM,
        "tmfc":    base_utc.strftime("%Y%m%d%H"),
        "hf":      str(hf),
        "lat":     f"{point['lat']:.4f}",
        "lon":     f"{point['lon']:.4f}",
        "disp":    "A",
        "help":    "0",
        "authKey": AUTH_KEY,
    }
    for attempt in range(RETRY_MAX):
        try:
            r = _kma_session.get(BASE_URL, params=params, timeout=30)
            if r.status_code == 200:
                return r.text
            # 5xx -> backoff then retry.  4xx -> 즉시 포기.
            if 500 <= r.status_code < 600 and attempt < RETRY_MAX - 1:
                time.sleep(2 ** (attempt + 1))
                continue
            return None
        except (requests.Timeout, requests.ConnectionError):
            if attempt < RETRY_MAX - 1:
                time.sleep(2 ** (attempt + 1))
                continue
            return None
    return None


# ── 수집 본체 ─────────────────────────────────────────────────────────
def collect_one_point(
    conn: sqlite3.Connection, base_utc: datetime, point: dict, collected_at: str,
) -> dict:
    """단일 (publish, point) 수집.  per-hf skip + per-hf 실패 허용.

    병렬 hf 처리: MAX_WORKERS 동시 fetch -> as_completed 로 메인 스레드가 결과를
    하나씩 받아 DB 에 commit.  SQLite single-writer 유지.  Ctrl-C 시 in-flight hf
    1 개만 손실 (다음 실행에서 skip-existing 으로 자동 보충).

    리턴: 통계 dict (expected/fetched/skipped/failed hf 개수, inserted 행 수).
    """
    base_kst = base_utc.astimezone(KST)
    base_dt_str = base_kst.strftime("%Y-%m-%d %H:%M")

    hf_full = list(collection_hf_range(base_utc))
    existing = existing_fcst_datetimes(conn, base_dt_str, point["name"])

    hf_to_fetch: list[int] = []
    for hf in hf_full:
        fcst_kst = base_kst + timedelta(hours=hf)
        if fcst_kst.strftime("%Y-%m-%d %H:%M") not in existing:
            hf_to_fetch.append(hf)

    skipped_hfs = len(hf_full) - len(hf_to_fetch)
    failed_hfs = 0
    inserted = 0

    if not hf_to_fetch:
        return {
            "expected_hfs": len(hf_full),
            "fetched_hfs":  0,
            "skipped_hfs":  skipped_hfs,
            "failed_hfs":   0,
            "inserted":     0,
        }

    def _process_result(hf: int, body: str | None) -> int:
        """워커 결과 -> DB 적재.  메인 스레드에서만 호출.  inserted row 수 반환."""
        nonlocal failed_hfs
        if body is None:
            print(f"  [WARN] {point['name']} hf={hf}: fetch failed after {RETRY_MAX} retries")
            failed_hfs += 1
            return 0
        raw = parse_response(body)
        if not raw:
            # 빈 응답: retention 밖이거나 발표 미가용.  parser 실패와 구분되게 명시.
            print(f"  [WARN] {point['name']} hf={hf}: empty response")
            failed_hfs += 1
            return 0
        cats = derive_categories(raw)
        fcst_kst_local = base_kst + timedelta(hours=hf)
        fcst_dt_str = fcst_kst_local.strftime("%Y-%m-%d %H:%M")
        rows = [
            (
                base_dt_str,
                fcst_dt_str,
                point["name"],
                point["lat"],
                point["lon"],
                cat,
                str(val),
                collected_at,
            )
            for cat, val in cats.items()
        ]
        return insert_rows(conn, rows)

    # 워커=6 으로 hf 들을 fanout.  결과는 완료 순으로 메인 스레드에 도착.
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        future_to_hf = {
            ex.submit(fetch_one_hf, base_utc, point, hf): hf
            for hf in hf_to_fetch
        }
        for fut in as_completed(future_to_hf):
            hf = future_to_hf[fut]
            try:
                body = fut.result()
            except Exception as e:
                # fetch_one_hf 가 내부 retry 후 None 을 반환하도록 설계됐으므로
                # 여기 도달은 드물지만 안전망.
                print(f"  [WARN] {point['name']} hf={hf}: unexpected error: {e}")
                failed_hfs += 1
                continue
            inserted += _process_result(hf, body)

    return {
        "expected_hfs": len(hf_full),
        "fetched_hfs":  len(hf_to_fetch),
        "skipped_hfs":  skipped_hfs,
        "failed_hfs":   failed_hfs,
        "inserted":     inserted,
    }


# ════════════════════════════════════════════════════════════════════════
# 공유 인프라 (KIMG core 외) -- 구 collect_input / collect_kpx_asos_data /
# collect_data_jeju 에서 옮겨온 함수들.
# ════════════════════════════════════════════════════════════════════════

# ── freshest-per-hour (구 collect_input.freshest) ───────────────────────
def freshest(df: pd.DataFrame, key_cols: list[str]) -> pd.DataFrame:
    """key_cols 별로 base_datetime 이 가장 큰 행만 남김."""
    if df.empty:
        return df
    return (
        df.sort_values("base_datetime", ascending=False)
          .drop_duplicates(key_cols, keep="first")
    )


# ── KPX / ASOS 공통 helpers (구 collect_kpx_asos_data) ───────────────────
KPX_BASE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
}
ASOS_URL = "https://apihub.kma.go.kr/api/typ01/url/kma_sfctm3.php"

# KPX/ASOS API 모두 1회 호출 최대 1 개월 -- 그 이상은 chunk 분할.
MAX_CHUNK_DAYS = 30
DEFAULT_SLEEP_SEC = 2


def _chunk_date_range(
    start_date: str, end_date: str, chunk_days: int = MAX_CHUNK_DAYS,
) -> Iterator[tuple[str, str]]:
    """yield (s, e) inclusive 'YYYY-MM-DD' 문자열, 한 청크 <= chunk_days 일."""
    if not 1 <= chunk_days <= MAX_CHUNK_DAYS:
        raise ValueError(
            f"chunk_days must be in 1..{MAX_CHUNK_DAYS} (API 1-month cap)"
        )
    s = datetime.strptime(start_date, "%Y-%m-%d")
    e = datetime.strptime(end_date, "%Y-%m-%d")
    if s > e:
        raise ValueError(f"start_date ({start_date}) > end_date ({end_date})")
    cur = s
    while cur <= e:
        ce = min(cur + timedelta(days=chunk_days - 1), e)
        yield cur.strftime("%Y-%m-%d"), ce.strftime("%Y-%m-%d")
        cur = ce + timedelta(days=1)


def _decode_kpx(raw: bytes) -> str:
    """KPX CSV 응답 자동 디코딩 (UTF-8 / CP949 / EUC-KR 순)."""
    for enc in ("utf-8-sig", "utf-8", "cp949", "euc-kr"):
        try:
            text = raw.decode(enc)
            if "기준일시" in text:
                return text
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


# ── KMA ASOS primitive (구 collect_kpx_asos_data) ───────────────────────
# 제주 fetch_asos (kma_fetcher_jeju) 와 육지 ASOS 수집기 (kma_fetcher_land) 가 공유.
def _clean_asos_value(val: str) -> float:
    try:
        v = float(val)
        return np.nan if v <= -9 else v
    except Exception:
        return np.nan


def _fetch_asos_one_station_chunk(
    start_date: str, end_date: str, stn_id: int, auth_key: str,
) -> pd.DataFrame:
    """단일 station × 단일 chunk 응답 파싱 -> 무접미사 DataFrame (timestamp index).

    suffix(_west 등) 부착은 호출자가 처리.
    """
    s_compact = start_date.replace("-", "")
    e_compact = end_date.replace("-", "")
    params = {
        "tm1": f"{s_compact}0000",
        "tm2": f"{e_compact}2300",
        "stn": str(stn_id),
        "help": "0",
        "authKey": auth_key,
    }
    resp = requests.get(ASOS_URL, params=params, timeout=60)
    resp.raise_for_status()
    lines = [l for l in resp.text.split("\n") if l.strip() and not l.startswith("#")]
    if not lines:
        return pd.DataFrame()
    raw = pd.DataFrame([l.split() for l in lines])

    out = pd.DataFrame()
    out["timestamp"] = pd.to_datetime(raw[0], format="%Y%m%d%H%M").dt.strftime(
        "%Y-%m-%d %H:%M:%S"
    )
    out["temp_c"] = raw[11].apply(_clean_asos_value)
    out["humidity"] = raw[13].apply(_clean_asos_value)
    # 운량 0~10 -> 0~1.
    out["total_cloud"] = raw[25].apply(_clean_asos_value) / 10
    out["midlow_cloud"] = raw[26].apply(_clean_asos_value) / 10
    # 풍속/풍향 (36방위 -> 360도).  결측(-9)은 NaN 그대로 둔다 -- 바람은 0 으로
    # 채우면 '무풍'과 '결측'이 구분되지 않으므로(0 으로 못 채움), NaN 을 유지하고
    # 보간은 downstream(asos_refine) 에서 처리.  NaN 은 sin/cos 로 그대로 전파.
    wind_spd = raw[3].apply(_clean_asos_value)
    wind_dir_deg = raw[2].apply(_clean_asos_value) * 10
    out["wind_spd"] = wind_spd.round(2)
    out["wd_sin"] = np.sin(np.radians(wind_dir_deg)).round(4)
    out["wd_cos"] = np.cos(np.radians(wind_dir_deg)).round(4)
    # 일사량 SI(MJ/m^2/h).  음수만 0 clip.  결측(-9)은 NaN 유지 -- 야간(센서 O)인지
    # 무센서(성산/남쪽 2024 이전)인지 값만으론 구분 불가하므로 여기선 채우지 않고,
    # 호출자가 '그 날 일사를 한 번이라도 보고했는가(=센서 가동일)'로 야간 0 채움.
    out["solar_rad"] = raw[34].apply(_clean_asos_value).clip(lower=0)
    # 강수 mm.  관측 결측(-9) = 사실상 무강수로 간주해 0 으로 채운다 (rain 은 0 채움 대상).
    # 적설(snow)은 모델 미사용 + 강수로 대표 가능 -> 아예 수집하지 않음.
    out["rainfall"] = raw[15].apply(_clean_asos_value).fillna(0)
    return out.set_index("timestamp")


# ── 부분 컬럼 UPSERT (구 collect_data_jeju.partial_upsert) ───────────────
def partial_upsert(table: str, wide: pd.DataFrame, db_path: Path) -> int:
    """wide DataFrame 을 `table` 에 *부분 컬럼* UPSERT (timestamp 키).

    배치에 없는 컬럼은 *건드리지 않는다* (기존 값 보존).  배치 안의 컬럼도 값이
    NaN(→NULL) 이면 기존 값을 유지한다 -- COALESCE(excluded.c, c) 사용.  즉 한 배치는
    자기가 실제 값을 가진 셀만 덮어쓴다 ("이번 배치엔 데이터 없음"인 NaN 이 기존 좋은
    값을 NULL 로 지우지 못한다 -- KPX *_da 가 429/미발행으로 NaN 일 때의 clobber 방지).
    한 번에 테이블 컬럼의 일부만 채우는 경로(다른 fill 경로가 채운 컬럼)를 보호하는
    안전 장치 -- 제주/육지 파이프라인 공통 write helper.
    (의도적으로 값을 NULL 로 되돌리는 건 이 경로로 불가 -- 필요하면 별도 처리.)

    스키마 관리: 테이블 없으면 timestamp PRIMARY KEY + 배치 컬럼들로 만든다.
    있으면 배치의 새 컬럼만 ALTER TABLE ADD COLUMN.  UNIQUE INDEX(timestamp) 가
    없으면 만든다 (ON CONFLICT 동작에 필수).
    """
    if wide.empty:
        return 0
    cols = list(wide.columns)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as c:
        existing = {r[1] for r in c.execute(f"PRAGMA table_info({table})").fetchall()}
        if not existing:
            col_defs = ['"timestamp" TEXT PRIMARY KEY'] + [f'"{col}"' for col in cols]
            c.execute(f"CREATE TABLE {table} ({', '.join(col_defs)})")
        else:
            for col in cols:
                if col not in existing and col != "timestamp":
                    c.execute(f'ALTER TABLE {table} ADD COLUMN "{col}"')
            c.execute(
                f"CREATE UNIQUE INDEX IF NOT EXISTS idx_{table}_ts "
                f"ON {table}(timestamp)"
            )

        all_cols = ["timestamp"] + cols
        col_list = ", ".join(f'"{col}"' for col in all_cols)
        placeholders = ", ".join("?" * len(all_cols))
        updates = ", ".join(
            f'"{col}" = COALESCE(excluded."{col}", "{table}"."{col}")' for col in cols
        )
        sql = (
            f"INSERT INTO {table} ({col_list}) VALUES ({placeholders}) "
            f"ON CONFLICT(timestamp) DO UPDATE SET {updates}"
        )
        records = [
            (idx, *(None if pd.isna(v) else v for v in row))
            for idx, row in zip(wide.index, wide.values)
        ]
        cur = c.executemany(sql, records)
        return cur.rowcount

"""
api_fetchers_jeju.py -- 제주 API fetcher 통합 (KMA + KPX, 2026-06-01 compaction).
구 kma_fetcher_jeju + kpx_fetcher_jeju 를 한 파일로 합쳤다.

담는 것:
  [KMA]
  * KIMR 지역모델 fetcher (아래 원본 설명) -- fetch_one / fetch_and_prepare 등.
    standalone DB 적재(collect/run_backfill/CLI)는 없다 -- 제주 forecast 는
    collect_data_jeju 가 fetch_and_prepare 를 직접 호출해 메모리에서
    input_data_jeju.db 로 간다 (kimr.db 는 더 이상 쓰지 않음).
  * 제주 long->wide 파생 (구 collect_input): POINT_SUFFIX / kimr_one_point /
    kimg_solar / restrict_to_day_ahead_issue.
  * 제주 ASOS 3지점 관측 fetch_asos (_common 의 station primitive 사용).
  [KPX]
  * fetch_kpx_jeju (chejusukub 수급, *_jeju) / fetch_kpx_est (DA SMP+예상수요, *_da).
KIMG http/parse/derive core 는 _common 에 있고 collect_data_jeju 가 직접 쓴다.
KPX/ASOS 공통 helper(_chunk_date_range/_decode_kpx/키)도 _common 에서 import.

원본(구 KIMR 수집기) 설명:
KMA KIM 지역 모델 단일면 data=U 예보 수집.

KMA API Hub 의 KIM(Korea Integrated Model) 지역 모델 단일면 격자점 자료를
받아 세 제주 지점(West(Gosan) / East(Seongsan) / solar_farm(south)) 의 행을
SQLite 에 적재한다. (West/East 는 풍력, solar_farm 은 태양광.)

핵심 규칙
- 발표 시각(UTC): 00, 06, 12, 18  → 1일 4회 (KST 로는 09, 15, 21, 03)
- 발표 직후 데이터 가용까지 지연 ~10분 -- 안전마진 3시간
- 수집 윈도우 (day-aligned, KST 기준): [D+1 00 KST, D+3 00 KST), 2일치 hourly
- 응답에서 (varn, level) -> human label 로 매핑해 저장 (CATEGORY_MAP)
- 80m wind: t=0 에서 KIM 의 spin-up artifact 로 0.0 이 나오나, day-aligned
  윈도우가 항상 base+3h 이후부터 시작하므로 t=0 row 는 자연히 제외된다 (안심)
- INSERT OR IGNORE -- 동일 발표 재실행은 no-op (cron 재시도 안전)
- 발표가 다르면 같은 fcst_datetime 도 모두 별도 행으로 보관 (lead-time EDA)
- Store-raw 정책: TEMP/TEMP_SKIN 은 K 그대로, REH/RAIN 도 원단위 그대로 저장.
  (KIMG 는 write-time 변환을 하지만, KIMR 은 원시값 유지가 일관성 있음.)

수집 카테고리 (15 개):
- 바람:   WIND_U_10M / WIND_V_10M / WIND_U_80M / WIND_V_80M / GUST
- 안정도: CAPE / CINN / HPBL
- 응결:   TCOG (graupel) / TCOH (hail)
- 표면 met: TEMP (2m, K) / TEMP_SKIN (surface, K) / REH (2m, %)
- 강수:   RAIN_CONV (kg/m^2) / RAIN_STRAT (kg/m^2)
바람은 풍력 발전 입력, 표면 met/강수는 태양광 발전 입력 및 Village 와의
정합 비교(둘이 충분히 비슷하면 collect_input.py 에서 Village 를 드롭) 용도.

KIM API 의 특별한 점:
- 응답이 JSON 이 아니라 plaintext (EUC-KR header + ASCII data lines).
  데이터 라인은 '# ' 로 시작하지 않으므로 그 필터만 거치면 됨.
- 멀티 varn 은 콤마(',')로만 동작. '+' / 공백은 빈 응답.
  -> 13 변수를 단일 호출에 묶어 가져옴 (호출 비용 최소화)
- varn=2002/2003 은 LEVEL=10(10m) / LEVEL=80(80m) 두 행이 함께 와서 4개
  카테고리(WIND_U_10M / WIND_U_80M / WIND_V_10M / WIND_V_80M) 가 됨.
- varn=0(tmpr), 1001(rhwt) 은 LEVEL=2 (2m). 그 외 단일면은 LEVEL=0.
- Retention 이 매우 길다 -- 최소 180 일 전 발표도 응답함 (Village 의 ~1일 대비).
  -> 초기 backfill 로 수개월치 한 번에 적재 가능 (--backfill N).

사용 예
    python collect_kimr.py                         # 가장 최근 2 발표 (safety 재수집)
    python collect_kimr.py --base 20260523 12      # 특정 UTC 발표
    python collect_kimr.py --backfill 150          # 최근 150 일치 일괄 backfill (>3d -> 병렬)
    python collect_kimr.py --db ./data/kimr.db

병렬 정책 (probe_kim_parallel.py 로 검증, 2026-05-26):
- 기본 동작 / --base / --backfill <= 3 일: 순차 (workers=1)
- --backfill > 3 일: workers=6 + shared Session + warmup + retry-on-5xx-backoff
- 2026-05-24 의 504 사례는 위 스택 없이 단순 ThreadPoolExecutor 만 사용한 결과.
  실측 13% 호출에서 backoff 재시도가 발생하므로 이 보호장치 없이는 큰 backfill
  이 다시 깨진다.
"""
from __future__ import annotations

import argparse
import io
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from dotenv import load_dotenv

# 공통 인프라 (같은 core/ 라 스크립트 실행 시 import 가능).
from _common import (
    freshest,
    _fetch_asos_one_station_chunk,
    _chunk_date_range,
    _decode_kpx,
    KMA_API_KEY,
    KPX_API_KEY,
    KPX_BASE_HEADERS,
    MAX_CHUNK_DAYS,
    DEFAULT_SLEEP_SEC,
)

load_dotenv()

# ── 설정 ────────────────────────────────────────────────────────────────
KST = ZoneInfo("Asia/Seoul")
UTC = timezone.utc

AUTH_KEY = os.getenv("KMA_API_KEY")

BASE_URL = "https://apihub.kma.go.kr/api/typ06/url/kim_grib_pt_tmfc.php"

# KIM 지역 모델 격자 X/Y (사용자 제공). 이전 좌표(West=529,253 / East=548,259)는
# 바다 셀이었음 -- 2026-05-25 에 한경면(고산)·성산 육지 셀로 교체.
# - 33.3474N  / 126.18602E  (한경면, 고산 풍력)        -> X=530, Y=251
# - 33.43875N / 126.91294E  (성산 풍력)                -> X=553, Y=254
# - 33.3284N  / 126.8366E   (남쪽 태양광 단지)          -> X=550, Y=250
POINTS = [
    {"name": "West(Gosan)",      "x": 530, "y": 251},  # 서쪽(한경면, 고산) -- 풍력
    {"name": "East(Seongsan)",   "x": 553, "y": 254},  # 동쪽(성산) -- 풍력
    {"name": "solar_farm(south)", "x": 550, "y": 250},  # 남쪽 태양광 단지
]

# 발표 시각 (UTC). KST 로는 09 / 15 / 21 / 03(다음날).
ISSUE_HOURS_UTC = (0, 6, 12, 18)

# 발표 후 데이터 가용까지의 안전 마진. 관찰상 ~10분이면 충분하나 여유롭게 3h.
PUBLISH_DELAY_HOURS = 3

# day-aligned 수집 윈도우 길이 (D+1 00 KST 부터 N 일).
FORECAST_DAYS = 2

# 멀티 varn (콤마만 동작) -- 한 번의 HTTP 호출에 13개 변수를 모두 받음.
# (15 카테고리: 13 + WIND_U/V 의 LEVEL=10/80 분기 2개)
# 추가 변수 (Village 와 비교를 위한 정합용 + 태양광 단지 표면 met):
#   0     tmpr  Temperature K        -> LEVEL=2 (2m)  -> TEMP (Village TMP 와 비교)
#   17    tmps  Skin Temperature K   -> LEVEL=0       -> TEMP_SKIN (지표온 -- 태양광)
#   1001  rhwt  Relative Humidity %  -> LEVEL=2 (2m)  -> REH  (Village REH 와 비교)
#   1010  acpc  Convective Precip    -> LEVEL=0       -> RAIN_CONV
#   1009  ncpc  Non-conv Precip      -> LEVEL=0       -> RAIN_STRAT
VARNS_PARAM = "2002,2003,2022,7006,7007,3018,1074,1072,0,17,1001,1010,1009"

# (varn, level) -> human label.
# 80m wind 의 LEVEL=80 은 t=0 에서 spin-up 으로 0.0 이지만 day-aligned 윈도우가
# 항상 base+3h 이후부터 시작하므로 저장 단계에서 자연히 제외된다.
# 매핑되지 않은 (varn, level) 조합은 무시(다중 level 응답 변경 대비 안전망).
# 값 단위는 원본 그대로 저장 (TEMP/TEMP_SKIN 은 K, REH 는 %, RAIN_* 는 kg/m^2).
# 다운스트림에서 K -> degC 변환 수행. KIMG 와 달리 KIMR 는 store-raw 정책 유지.
CATEGORY_MAP: dict[tuple[int, int], str] = {
    (2002, 10): "WIND_U_10M",
    (2002, 80): "WIND_U_80M",
    (2003, 10): "WIND_V_10M",
    (2003, 80): "WIND_V_80M",
    (2022, 0):  "GUST",
    (7006, 0):  "CAPE",
    (7007, 0):  "CINN",
    (3018, 0):  "HPBL",
    (1074, 0):  "TCOG",
    (1072, 0):  "TCOH",
    (0,    2):  "TEMP",        # 2m air temperature, K
    (17,   0):  "TEMP_SKIN",   # surface/skin temperature, K
    (1001, 2):  "REH",         # 2m relative humidity, %
    (1010, 0):  "RAIN_CONV",   # convective precip, kg/m^2
    (1009, 0):  "RAIN_STRAT",  # non-convective precip, kg/m^2
}

# ef=시작,종료,간격 (h) 는 발표 시각마다 다르다 -> ef_param_for() 가 수집 윈도우에서
# 직접 계산한다. (이전: 고정 "0,87,1" 로 88스텝을 받아 ~48스텝만 남기고 버렸음.
#  -> 서버 GRIB 추출/응답크기 절반 낭비 + 과부하시 504 유발. KIMG 의 hf 산정과 동일하게
#  필요한 48스텝만 요청하도록 2026-05-30 변경.)

# 병렬 호출 설정 (probe_kim_parallel.py 로 2026-05-26 검증).
# - probe 결과: 360 pairs at workers=6 -> 100% 성공, ~3x 속도향상, 13% 호출이 retry 경유.
# - 동시성을 더 올려도 서버측 큐잉으로 이득 미미 + 5xx 위험 증가.
MAX_WORKERS = 6
RETRY_MAX = 3

# --backfill N_DAYS 가 이 값보다 클 때만 병렬 사용.  작은 작업은 순차로 충분.
PARALLEL_BACKFILL_THRESHOLD_DAYS = 3


# ── HTTP session (TCP/TLS 재사용) ───────────────────────────────────────
# 모듈 레벨 Session 으로 connection-pool 유지.  KIMR 은 (base, point) 1 회 호출이라
# 호출 빈도가 낮지만, backfill 에서 sustained 6-way 병렬이 돌 때 cold reconnect 가
# 504 의 주요 원인이었다 (2026-05-24 사례).
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


def workers_for_backfill(n_days: int) -> int:
    """N 일 backfill 에 사용할 worker 수.  > 3일이면 병렬, 아니면 순차.
    collect_data.py 가 동일 정책을 따라가도록 노출."""
    return MAX_WORKERS if n_days > PARALLEL_BACKFILL_THRESHOLD_DAYS else 1


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


def backfill_bases(days: int, now_kst: datetime) -> list[datetime]:
    """가장 최근 가용 발표부터 N 일치 거꾸로. 가장 오래된 것부터 적재하도록 reverse."""
    latest = latest_published_base(now_kst)
    cutoff = latest - timedelta(days=days)
    out: list[datetime] = []
    cur = latest
    while cur >= cutoff:
        out.append(cur)
        cur -= timedelta(hours=6)
    out.reverse()  # 오래된 것부터 최신 순 -> 진행상황 직관적
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


def ef_param_for(base_utc: datetime) -> str:
    """이 발표의 day-aligned 수집 윈도우에 맞춘 ef=시작,종료,간격(h).

    윈도우 밖 시각을 서버에서 받지 않도록 ef 범위를 잘라 호출당 GRIB 추출량과
    응답 크기를 줄인다 (서버 504 완화). 종료는 inclusive 이므로 window_end
    (=exclusive) 의 직전 시각(-1h)까지. 발표별 결과 (KIMG hf 와 동일):
        UTC 00 -> 15,62,1   UTC 06 -> 9,56,1
        UTC 12 -> 3,50,1    UTC 18 -> 21,68,1   (항상 48 스텝)
    시작이 항상 +3h 이상이라 t=0 의 80m spin-up row 는 여전히 제외된다.
    """
    window_start, window_end = collection_window(base_utc)
    start_h = int((window_start - base_utc).total_seconds() // 3600)
    end_h = int((window_end - base_utc).total_seconds() // 3600) - 1
    return f"{start_h},{end_h},1"


# ── KMA API ────────────────────────────────────────────────────────────
def parse_response(body: str) -> list[tuple[str, int, int, str]]:
    """plaintext body -> [(TMEF, VARN, LEVEL, VALUE_STR)] 데이터 라인만 추출.
    헤더는 '#' 로 시작하는 행. VALUE 는 원문 그대로 (TEXT 저장).
    """
    out: list[tuple[str, int, int, str]] = []
    for ln in body.splitlines():
        s = ln.strip()
        if not s or s.startswith("#"):
            continue
        parts = s.split()
        if len(parts) < 5:
            continue
        try:
            varn = int(parts[2])
            level = int(parts[3])
        except ValueError:
            continue
        out.append((parts[1], varn, level, parts[4]))
    return out


def fetch_one(base_utc: datetime, x: int, y: int) -> list[tuple[str, int, int, str]]:
    """단일 (publish, point) 호출.  멀티 varn 으로 13 변수 한 번에 가져옴.

    내부에서 5xx + timeout/connection error 에 대해 exponential backoff (2s, 4s)
    로 최대 RETRY_MAX 회 재시도.  4xx 는 즉시 raise.  최종 실패 시 raise -- 호출자
    (run_backfill / collect) 의 except 가 failed pair 로 카운트.
    """
    params = {
        "group": "KIMR",
        "nwp":   "r030",
        "data":  "U",
        "varn":  VARNS_PARAM,
        "tmfc":  base_utc.strftime("%Y%m%d%H"),
        "ef":    ef_param_for(base_utc),
        "X":     x,
        "Y":     y,
        "authKey": AUTH_KEY,
    }
    for attempt in range(RETRY_MAX):
        try:
            r = _kma_session.get(BASE_URL, params=params, timeout=60)
            if r.status_code == 200:
                return parse_response(r.text)
            # 5xx -> backoff & retry.  4xx -> 즉시 raise.
            if 500 <= r.status_code < 600 and attempt < RETRY_MAX - 1:
                time.sleep(2 ** (attempt + 1))
                continue
            r.raise_for_status()
            return []  # 실제 도달 불가
        except (requests.Timeout, requests.ConnectionError):
            if attempt < RETRY_MAX - 1:
                time.sleep(2 ** (attempt + 1))
                continue
            raise
    return []


# ── 수집 본체 ─────────────────────────────────────────────────────────
def fetch_and_prepare(
    base_utc: datetime, point: dict, collected_at: str,
) -> tuple[list[tuple], int, int, int]:
    """단일 (publish, point) 호출 + 윈도우 필터 + insert-ready 행 생성.
    리턴: (rows, fetched_count, dropped_unknown, dropped_window).
    네트워크 I/O 만 하므로 워커 스레드에서 호출해도 안전 (DB 접근 없음).
    """
    items = fetch_one(base_utc, point["x"], point["y"])
    base_dt_str = base_utc.astimezone(KST).strftime("%Y-%m-%d %H:%M")
    window_start, window_end = collection_window(base_utc)

    rows: list[tuple] = []
    dropped_unknown = 0
    dropped_window = 0
    for tmef, varn, level, value in items:
        cat = CATEGORY_MAP.get((varn, level))
        if cat is None:
            dropped_unknown += 1
            continue
        fcst_kst = datetime.strptime(tmef, "%Y%m%d%H").replace(tzinfo=UTC).astimezone(KST)
        if not (window_start <= fcst_kst < window_end):
            dropped_window += 1
            continue
        rows.append((
            base_dt_str,
            fcst_kst.strftime("%Y-%m-%d %H:%M"),
            point["name"],
            point["x"],
            point["y"],
            cat,
            value,
            collected_at,
        ))
    return rows, len(items), dropped_unknown, dropped_window


# ════════════════════════════════════════════════════════════════════════
# 제주 long->wide 파생 (구 collect_input).  collect_data_jeju 가 이 함수들로
# KIMR long DF 와 KIMG SOLAR_RAD 를 지점별 wide 컬럼으로 후처리한다.
# ════════════════════════════════════════════════════════════════════════

# DB 의 point_name → wide 컬럼 suffix.
POINT_SUFFIX: dict[str, str] = {
    "West(Gosan)":       "west",
    "East(Seongsan)":    "east",
    "solar_farm(south)": "south",
}

# day-ahead 발표 선택 base 시각 (KST): KIMR 00 UTC(09 KST) / KIMG 18 UTC(03 KST).
DAY_AHEAD_BASE_HOUR_KST: dict[str, int] = {
    "kimr": 9,
    "kimg": 3,
}


def restrict_to_day_ahead_issue(df: pd.DataFrame, base_hour_kst: int) -> pd.DataFrame:
    """base_datetime 의 KST 시(hour)가 base_hour_kst 인 발표만 남긴다 (day-ahead 선택)."""
    if df.empty:
        return df
    base_hours = pd.to_datetime(
        df["base_datetime"], format="%Y-%m-%d %H:%M"
    ).dt.hour
    return df[base_hours == base_hour_kst]


def kimr_one_point(
    df_long: pd.DataFrame, point: str, suffix: str,
    window_start: datetime, window_end: datetime,
    day_ahead: bool = False,
) -> pd.DataFrame:
    """단일 point 의 KIMR long → 후처리된 wide (index=fcst_datetime 문자열).

    day_ahead=True 면 00 UTC(09 KST) 발표만 사용.  False(기본) 면 globally-freshest.
    """
    sub = df_long[df_long["point_name"] == point]
    if sub.empty:
        return pd.DataFrame()
    if day_ahead:
        sub = restrict_to_day_ahead_issue(sub, DAY_AHEAD_BASE_HOUR_KST["kimr"])
        if sub.empty:
            return pd.DataFrame()

    # 1) Non-rain: freshest per (fcst_datetime, category), then pivot.
    non_rain = sub[~sub["category"].isin(["RAIN_CONV", "RAIN_STRAT"])]
    non_rain = freshest(non_rain, ["fcst_datetime", "category"])
    wide = non_rain.pivot(index="fcst_datetime", columns="category", values="fcst_value")

    # 2) Rain: per-base 누적→시간차 diff → freshest of the diff.
    rain = sub[sub["category"].isin(["RAIN_CONV", "RAIN_STRAT"])]
    if not rain.empty:
        acc = (
            rain.groupby(["base_datetime", "fcst_datetime"], as_index=False)["fcst_value"]
                .sum()
                .rename(columns={"fcst_value": "acc"})
                .sort_values(["base_datetime", "fcst_datetime"])
        )
        # base 단위로 diff (첫 행은 NaN → drop → freshest 가 직전 base 값 선택).
        acc["hourly"] = (
            acc.groupby("base_datetime")["acc"].diff().clip(lower=0).round(2)
        )
        acc = acc.dropna(subset=["hourly"])
        acc = freshest(acc, ["fcst_datetime"])
        rain_s = acc.set_index("fcst_datetime")["hourly"].rename("RAIN_HOURLY")
        wide = wide.join(rain_s, how="outer")

    # 3) 윈도우 트림 (cumulative-diff 용 추가 lookback 분 제거).
    start_s = window_start.strftime("%Y-%m-%d %H:%M")
    end_s = window_end.strftime("%Y-%m-%d %H:%M")
    wide = wide.loc[(wide.index >= start_s) & (wide.index < end_s)]
    if wide.empty:
        return wide

    # 4) 후처리 (column rename + 단위 변환 + wind 분해).
    out = pd.DataFrame(index=wide.index)
    if "TEMP" in wide:
        out[f"temp_{suffix}"] = (wide["TEMP"] - 273.15).round(2)
    if "TEMP_SKIN" in wide:
        out[f"temp_skin_{suffix}"] = (wide["TEMP_SKIN"] - 273.15).round(2)

    for height in ("10m", "80m"):
        u_col = f"WIND_U_{height.upper()}"
        v_col = f"WIND_V_{height.upper()}"
        if u_col in wide and v_col in wide:
            u, v = wide[u_col], wide[v_col]
            spd = np.sqrt(u**2 + v**2)
            wdir = (270 - np.degrees(np.arctan2(v, u))) % 360
            out[f"wind_spd_{height}_{suffix}"] = spd.round(2)
            out[f"wd_sin_{height}_{suffix}"]   = np.sin(np.radians(wdir)).round(4)
            out[f"wd_cos_{height}_{suffix}"]   = np.cos(np.radians(wdir)).round(4)

    for raw, name in [
        ("GUST",      f"gust_{suffix}"),
        ("CAPE",      f"cape_{suffix}"),
        ("CINN",      f"cinn_{suffix}"),
        ("HPBL",      f"hpbl_{suffix}"),
        ("TCOG",      f"tcog_{suffix}"),
        ("TCOH",      f"tcoh_{suffix}"),
        ("REH",       f"reh_{suffix}"),
    ]:
        if raw in wide:
            out[name] = wide[raw].round(4)

    if "RAIN_HOURLY" in wide:
        out[f"rainfall_{suffix}"] = wide["RAIN_HOURLY"]

    return out


def kimg_one_point(
    df_long: pd.DataFrame, point: str, suffix: str,
    window_start: datetime, window_end: datetime,
) -> pd.DataFrame:
    """단일 point 의 KIMG long → kimr_one_point 와 동일한 컬럼 스키마의 wide.

    KIMR lead 한계(120h=D+5) 이후 장지평 구간(D+6~)을 KIMG 로 잇기 위한 함수
    (2026-06-13).  KIMG 가 제공하는 변수(TEMP_C(이미 °C)·WIND_U/V_10M/80M·GUST·
    REH·RAIN_*(누적))를 KIMR 와 같은 변환식으로 같은 컬럼명으로 만든다.
    KIMR 전용 변수(temp_skin/cape/cinn/hpbl/tcog/tcoh)는 생략 -- 해당 컬럼은
    KIMG-only 구간에서 NaN 으로 남는다.  구름(total_cloud/midlow_cloud)은 KIMR 에
    없어 legacy 적재가 끊긴 2026-06-01 이후 죽어 있던 컬럼인데, 여기서 되살린다
    (serve_jeju_demand_lh 의 구름 4 feature 가 이 컬럼을 읽는다).
    호출자(collect_data_jeju.build_wide)가 KIMR 우선 combine_first 로 합친다
    (KIMR part 에 없는 컬럼은 전 구간 KIMG 값이 그대로 쓰임).

    주의: hf>135(_common.KIMG_HOURLY_MAX_HF) 구간은 3h 간격만 존재하므로
    rainfall diff 는 그 구간에서 시간당이 아니라 3시간 누적값이 된다 (사용 시
    보간/배분 필요 -- 저장은 원본 그대로 정책).
    """
    sub = df_long[df_long["point_name"] == point]
    if sub.empty:
        return pd.DataFrame()

    # 1) 비강수: freshest per (fcst_datetime, category), then pivot.
    non_rain = sub[~sub["category"].isin(["RAIN_CONV", "RAIN_STRAT"])]
    non_rain = freshest(non_rain, ["fcst_datetime", "category"])
    wide = non_rain.pivot(index="fcst_datetime", columns="category", values="fcst_value")

    # 2) 강수: per-base 누적→시간차 diff → freshest (kimr_one_point 와 동일 패턴).
    rain = sub[sub["category"].isin(["RAIN_CONV", "RAIN_STRAT"])]
    if not rain.empty:
        acc = (
            rain.groupby(["base_datetime", "fcst_datetime"], as_index=False)["fcst_value"]
                .sum()
                .rename(columns={"fcst_value": "acc"})
                .sort_values(["base_datetime", "fcst_datetime"])
        )
        acc["hourly"] = (
            acc.groupby("base_datetime")["acc"].diff().clip(lower=0).round(2)
        )
        acc = acc.dropna(subset=["hourly"])
        acc = freshest(acc, ["fcst_datetime"])
        rain_s = acc.set_index("fcst_datetime")["hourly"].rename("RAIN_HOURLY")
        wide = wide.join(rain_s, how="outer")

    # 3) 윈도우 트림.
    start_s = window_start.strftime("%Y-%m-%d %H:%M")
    end_s = window_end.strftime("%Y-%m-%d %H:%M")
    wide = wide.loc[(wide.index >= start_s) & (wide.index < end_s)]
    if wide.empty:
        return wide

    # 4) 후처리 -- kimr_one_point 와 동일 컬럼명/변환식.  TEMP_C 는 KIMG 가
    #    저장 시점에 이미 °C 변환을 마쳤으므로 K→°C 변환 없음.
    out = pd.DataFrame(index=wide.index)
    if "TEMP_C" in wide:
        out[f"temp_{suffix}"] = wide["TEMP_C"].round(2)

    for height in ("10m", "80m"):
        u_col = f"WIND_U_{height.upper()}"
        v_col = f"WIND_V_{height.upper()}"
        if u_col in wide and v_col in wide:
            u, v = wide[u_col], wide[v_col]
            spd = np.sqrt(u**2 + v**2)
            wdir = (270 - np.degrees(np.arctan2(v, u))) % 360
            out[f"wind_spd_{height}_{suffix}"] = spd.round(2)
            out[f"wd_sin_{height}_{suffix}"]   = np.sin(np.radians(wdir)).round(4)
            out[f"wd_cos_{height}_{suffix}"]   = np.cos(np.radians(wdir)).round(4)

    if "GUST" in wide:
        out[f"gust_{suffix}"] = wide["GUST"].round(4)
    if "REH" in wide:
        out[f"reh_{suffix}"] = wide["REH"].round(2)
    if "TCLD" in wide:
        out[f"total_cloud_{suffix}"] = wide["TCLD"].round(4)
    if "MIDLOW_CLOUD" in wide:
        out[f"midlow_cloud_{suffix}"] = wide["MIDLOW_CLOUD"].round(4)
    if "RAIN_HOURLY" in wide:
        out[f"rainfall_{suffix}"] = wide["RAIN_HOURLY"]

    return out


def kimg_solar(df_long: pd.DataFrame, day_ahead: bool = False) -> pd.Series:
    """KIMG SOLAR_RAD freshest → radiation_south (저장 단위 그대로, MJ/m^2/h)."""
    name = "radiation_south"
    if df_long.empty:
        return pd.Series(dtype="float64", name=name)
    if day_ahead:
        df_long = restrict_to_day_ahead_issue(df_long, DAY_AHEAD_BASE_HOUR_KST["kimg"])
        if df_long.empty:
            return pd.Series(dtype="float64", name=name)
    fresh = freshest(df_long, ["fcst_datetime"])
    s = fresh.set_index("fcst_datetime")["fcst_value"]
    return s.round(2).rename(name)


# ════════════════════════════════════════════════════════════════════════
# 제주 ASOS 3지점 관측 (구 collect_kpx_asos_data.fetch_asos).  _common 의
# station primitive 를 3 지점에 적용해 wide 관측 DataFrame 으로 반환.
# ════════════════════════════════════════════════════════════════════════
# solar: 일사(SI) 센서 유무.  고산(185)/남쪽(189) O, 성산(188) 없음.
ASOS_STATIONS = [
    {"stn_id": 185, "suffix": "west",  "solar": True},   # 고산
    {"stn_id": 188, "suffix": "east",  "solar": False},  # 성산 (일사 센서 없음)
    {"stn_id": 189, "suffix": "south", "solar": True},   # 남쪽 태양광 단지 인근 ASOS
]


def fetch_asos(
    start_date: str,
    end_date: str,
    auth_key: str | None = None,
    chunk_days: int = MAX_CHUNK_DAYS,
    sleep_sec: float = DEFAULT_SLEEP_SEC,
    progress: bool = True,
) -> pd.DataFrame:
    """3 ASOS 지점 관측 -> wide DataFrame.  컬럼명: <var>_<west|east|south>.

    수집 변수 (지점별 9개; 적설 제외): temp_c / humidity / total_cloud /
    midlow_cloud / wind_spd / wd_sin / wd_cos / solar_rad / rainfall.
    solar_rad 는 센서가 있는 지점만 (west/south).  성산(east)은 컬럼 자체가 없다.
    결측 정책: rainfall->0, solar_rad 는 센서 가동일의 야간 결측만 0, 그 외 NaN 유지.
    """
    key = auth_key or KMA_API_KEY
    if not key:
        sys.exit("KMA_API_KEY is not set (check .env)")

    per_station: dict[str, list[pd.DataFrame]] = {
        st["suffix"]: [] for st in ASOS_STATIONS
    }
    for s, e in _chunk_date_range(start_date, end_date, chunk_days):
        for st in ASOS_STATIONS:
            try:
                df = _fetch_asos_one_station_chunk(s, e, st["stn_id"], key)
                if progress:
                    print(
                        f"  [asos] {s} ~ {e}  stn={st['stn_id']} "
                        f"({st['suffix']:<5})  rows={len(df)}"
                    )
                if not df.empty:
                    per_station[st["suffix"]].append(df)
            except Exception as ex:
                print(
                    f"  [asos] {s} ~ {e}  stn={st['stn_id']} "
                    f"({st['suffix']})  FAIL: {ex}"
                )
            time.sleep(sleep_sec)

    parts: list[pd.DataFrame] = []
    for st in ASOS_STATIONS:
        chunks = per_station[st["suffix"]]
        if not chunks:
            continue
        df_st = (
            pd.concat(chunks)
              .reset_index()
              .drop_duplicates(subset="timestamp")
              .set_index("timestamp")
              .sort_index()
        )
        # 일사(SI) 처리: 센서 없는 지점(성산)은 컬럼을 버린다.  센서 있는 지점은
        # '그 날 일사를 한 번이라도 보고했는가'로 가동일을 판정해 가동일의 NaN(=야간)
        # 만 0 으로 채우고, 비가동일(무센서 기간)의 NaN 은 그대로 둔다.
        if not st["solar"]:
            df_st = df_st.drop(columns="solar_rad", errors="ignore")
        else:
            sr = df_st["solar_rad"]
            day_key = pd.to_datetime(df_st.index).normalize()
            sensor_day = sr.notna().groupby(day_key).transform("any")
            df_st["solar_rad"] = sr.mask(sr.isna() & sensor_day, 0.0)
        df_st.columns = [f"{c}_{st['suffix']}" for c in df_st.columns]
        parts.append(df_st)

    if not parts:
        return pd.DataFrame()
    wide = pd.concat(parts, axis=1).sort_index()
    wide.index.name = "timestamp"
    return wide


# ========================================================================
# KPX 제주 fetcher (구 kpx_fetcher_jeju 통합).  수급(*_jeju) + DA SMP/est(*_da).
# ========================================================================
KPX_JEJU_URL = "https://openapi.kpx.or.kr/downloadChejuSukubCSV.do"
KPX_EST_URL = (
    "https://apis.data.go.kr/B552115/SmpWithForecastDemand/getSmpWithForecastDemand"
)
# 제주 실시간시장 SMP/수요 (data.go.kr B552115).  date 별 96행(24h x 4구간) 반환.
# jsmpRt = 구간별 실시간 SMP -> 시간평균이 모델 타깃(smp_jeju_rt).
KPX_JEJU_RT_URL = (
    "https://apis.data.go.kr/B552115/JejuSmpLfd2/getJejuSmpLfd2"
)


# ── 1. KPX 제주 (chejusukub 수급 + 신재생, historical) ─────────────────
# 컬럼명은 모두 *_jeju suffix -- 'sukub' 의 *_land 와 짝을 이뤄 동일 변수가 두 계통에
# 충돌 없이 같은 wide DF / DB 에 공존 (supply_cap_land vs supply_cap_jeju).
_KPX_JEJU_RENAME = {
    "공급능력(MW)":     "supply_cap_jeju",
    "현재수요(MW)":     "real_demand_jeju",
    "신재생총합(MW)":   "real_renew_gen_jeju",
    "신재생태양광(MW)": "real_solar_gen_jeju",
    "신재생풍력(MW)":   "real_wind_gen_jeju",
}
_KPX_JEJU_POWER_COLS = list(_KPX_JEJU_RENAME.values())


def _fetch_kpx_jeju_chunk(start_date: str, end_date: str) -> pd.DataFrame:
    headers = {**KPX_BASE_HEADERS, "Referer": "https://openapi.kpx.or.kr/chejusukub.do"}
    resp = requests.post(
        KPX_JEJU_URL,
        data={"startDate": start_date, "endDate": end_date},
        headers=headers,
        timeout=60,
    )
    resp.raise_for_status()
    df = pd.read_csv(io.StringIO(_decode_kpx(resp.content)))
    df.columns = df.columns.str.strip()
    if df.empty or "기준일시" not in df.columns:
        return pd.DataFrame()
    df = df[df["기준일시"].astype(str).str.endswith("0000")].copy()
    df["timestamp"] = pd.to_datetime(
        df["기준일시"].astype(str), format="%Y%m%d%H%M%S"
    ).dt.strftime("%Y-%m-%d %H:%M:%S")
    df = df.rename(columns=_KPX_JEJU_RENAME)
    cols = ["timestamp"] + [c for c in _KPX_JEJU_POWER_COLS if c in df.columns]
    df = df[cols].copy()
    for c in cols[1:]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df


def fetch_kpx_jeju(
    start_date: str,
    end_date: str,
    chunk_days: int = MAX_CHUNK_DAYS,
    sleep_sec: float = DEFAULT_SLEEP_SEC,
    progress: bool = True,
) -> pd.DataFrame:
    """KPX 제주(chejusukub) 1h 수급 + 신재생을 wide DataFrame 으로 반환.

    Returns 컬럼 (5 cols, 모두 *_jeju suffix):
        supply_cap_jeju / real_demand_jeju / real_renew_gen_jeju /
        real_solar_gen_jeju / real_wind_gen_jeju.

    real_demand_jeju == 0 은 계측 오류 (제주 수요가 0 이 될 수 없음) -> 해당 행
    전체를 NaN 처리 후 양방향 시간보간 (최대 3 연속).
    """
    chunks: list[pd.DataFrame] = []
    for s, e in _chunk_date_range(start_date, end_date, chunk_days):
        try:
            df = _fetch_kpx_jeju_chunk(s, e)
            if progress:
                print(f"  [*_jeju] {s} ~ {e}  rows={len(df)}")
            if not df.empty:
                chunks.append(df)
        except Exception as ex:
            print(f"  [*_jeju] {s} ~ {e}  FAIL: {ex}")
        time.sleep(sleep_sec)
    if not chunks:
        return pd.DataFrame()
    df = (
        pd.concat(chunks, ignore_index=True)
          .drop_duplicates(subset="timestamp")
          .sort_values("timestamp")
          .set_index("timestamp")
    )

    # demand=0 보정 (전체 컬럼 NaN -> 시간 보간).
    zero_mask = df["real_demand_jeju"] == 0
    if zero_mask.any():
        print(
            f"  [*_jeju] demand=0 sensor errors: {zero_mask.sum()} rows "
            f"-> NaN + time interpolate (limit=3)"
        )
        df.loc[zero_mask, _KPX_JEJU_POWER_COLS] = np.nan
        df.index = pd.to_datetime(df.index)
        df = df.interpolate(method="time", limit=3, limit_direction="both")
        df.index = df.index.strftime("%Y-%m-%d %H:%M:%S")
    df.index.name = "timestamp"
    return df


# ── 2. KPX est (일전 SMP + 예상수요 제주/육지, FORECAST 테이블) ─────────
# 이 fetcher 의 출력은 collect_data_new 의 forecast 테이블로 들어간다.
# 컬럼은 모두 _da 접미사 (day-ahead 의미) -- smp_jeju_da / smp_land_da /
# jeju_est_demand_da / land_est_demand_da.  jeju_/land_ 접두사를 붙여 두 권역의
# 예상수요를 같은 wide DF / DB 에 충돌 없이 공존시킨다.  historical 테이블의
# 실현치(별도 컬럼)와도 이름이 안 겹치고, legacy DB 의 SMP/예상수요 컬럼을 같은
# 이름으로 양 테이블에 매핑할 수 있다.
def _fetch_kpx_est_one_day(target_date: str, service_key: str) -> pd.DataFrame:
    """하루치 (24h × 제주+육지) 호출 -> wide DF (timestamp index).

    target_date : 'YYYY-MM-DD'.  API 는 'YYYYMMDD' 로 받으므로 내부에서 변환.
    API 발행 시점: 전날 23:00 KST 이후 다음날치가 올라온다 (예: 05-27 23:00 ->
    05-28 데이터).  미래 날짜는 빈 응답.
    """
    params = {
        "serviceKey": service_key,
        "dataType": "json",
        "date": target_date.replace("-", ""),
        "numOfRows": "100",  # 24h x 2 areas = 48 rows, 100 이면 충분.
    }
    resp = requests.get(KPX_EST_URL, params=params, timeout=30)
    resp.raise_for_status()
    body = resp.json().get("response", {}).get("body", {}) or {}
    items = (body.get("items") or {}).get("item")
    if not items:
        return pd.DataFrame()
    df = pd.DataFrame(items)
    if df.empty or "areaName" not in df.columns:
        return pd.DataFrame()
    # 값 컬럼(smp/jlfd/mlfd) 중 일부가 응답에서 빠져도 KeyError 로 그 날짜 전체를
    # 잃지 않도록 방어적으로 채운다 (없으면 NaN -> 해당 _da 만 결측).
    for _col in ("smp", "jlfd", "mlfd"):
        if _col not in df.columns:
            df[_col] = pd.NA

    # 제주 행: smp_jeju_da + jeju_est_demand_da(jlfd) 만 사용.
    # 육지 행: smp_land_da + land_est_demand_da(mlfd) 만 사용.
    # slfd = jlfd + mlfd 라 별도 저장 안 함.
    df_jeju = df[df["areaName"] == "제주"][["date", "hour", "smp", "jlfd"]].rename(
        columns={"smp": "smp_jeju_da", "jlfd": "jeju_est_demand_da"}
    )
    df_land = df[df["areaName"] == "육지"][["date", "hour", "smp", "mlfd"]].rename(
        columns={"smp": "smp_land_da", "mlfd": "land_est_demand_da"}
    )
    merged = pd.merge(df_jeju, df_land, on=["date", "hour"], how="outer")
    # KPX 의 hour 는 1..24 -> 00:00 ~ 23:00 으로 매핑 (hour-1).
    merged["timestamp"] = (
        pd.to_datetime(merged["date"], format="%Y%m%d")
        + pd.to_timedelta(merged["hour"].astype(int) - 1, unit="h")
    ).dt.strftime("%Y-%m-%d %H:%M:%S")
    out_cols = [
        "smp_jeju_da", "smp_land_da",
        "jeju_est_demand_da", "land_est_demand_da",
    ]
    out = merged[["timestamp", *out_cols]].copy()
    for c in out_cols:
        out[c] = pd.to_numeric(out[c], errors="coerce")
    return out.set_index("timestamp").sort_index()


def fetch_kpx_est(
    start_date: str,
    end_date: str,
    service_key: str | None = None,
    sleep_sec: float = DEFAULT_SLEEP_SEC,
    progress: bool = True,
) -> pd.DataFrame:
    """일전(DA) SMP(제주/육지) + 제주/육지 예상수요를 wide DataFrame 으로 반환.

    API 는 일 단위 호출(target_date 1개) 이라 [start..end] 의 각 날짜에 1회씩
    호출한다.  발행되지 않은 미래 일자는 빈 응답 -> 해당 날짜는 결과에서 누락.

    Returns 컬럼 (4 cols, 모두 *_da suffix):
        smp_jeju_da / smp_land_da / jeju_est_demand_da / land_est_demand_da
    -> forecast 테이블 행.  build_historical 도 같은 컬럼을 historical 에 누적.
    """
    key = service_key or KPX_API_KEY
    if not key:
        sys.exit("KPX_API_KEY is not set (check .env)")
    s = datetime.strptime(start_date, "%Y-%m-%d")
    e = datetime.strptime(end_date, "%Y-%m-%d")
    if s > e:
        raise ValueError(f"start_date ({start_date}) > end_date ({end_date})")

    days: list[pd.DataFrame] = []
    cur = s
    while cur <= e:
        d_str = cur.strftime("%Y-%m-%d")
        try:
            df = _fetch_kpx_est_one_day(d_str, key)
            if progress:
                print(f"  [*_da] {d_str}  rows={len(df)}")
            if not df.empty:
                days.append(df)
        except Exception as ex:
            print(f"  [*_da] {d_str}  FAIL: {ex}")
        cur += timedelta(days=1)
        if cur <= e:
            time.sleep(sleep_sec)
    if not days:
        return pd.DataFrame()
    out = pd.concat(days).sort_index()
    out.index.name = "timestamp"
    return out


# ── 3. KPX 제주 실시간시장 SMP (RT SMP, HISTORICAL 타깃) ─────────────────
# 제주 실시간시장(시범사업)의 구간별(15분=4구간/h) 실시간 SMP/수요.  getJejuSmpLfd2.
# 저장 정책 (2026-06-03 변경): 구간별 원시값(smp_rt_g1..g4)을 그대로 저장하고,
# 파생은 *필요할 때* 계산해 쓴다.  저장 단계에서 함께 넣는 파생 2종:
#   smp_jeju_rt    = mean(g1..g4)                 (시간평균 RT SMP, 4단계 모델 타깃)
#   smp_rt_neg_num = count(g1..g4 < NEG_THRESHOLD) (음수권 구간 개수 0..4)
# (구 smp_rt_neg_flag = any(g<0) boolean 은 폐기.  음수 기준도 0 -> 5 로 변경:
#  실시간시장 SMP 가 5 미만이면 사실상 바닥/음수권으로 보고 구간 개수를 센다.)
# 출력은 historical 테이블 전용 (RT 는 실현치라 forecast 엔 불필요).
#
# 구간 식별: 응답 gugan 라벨은 EUC-KR 깨짐이나 선두 숫자(1..4)가 구간 인덱스라
# 그 숫자만 뽑아 g1..g4 로 피벗한다 (라벨 본문은 무시).
#
# 제약(사용자 메모, 2026-06-02):
#   - 매일 23:00 KST 발행, 단 KPX API 불안정으로 지연 가변(최대 익일 18:00 관측).
#     -> 미발행/지연 날짜는 빈 응답.  partial_upsert 의 COALESCE 가 기존값 보존하므로
#        빈 날짜를 매 실행 재시도해도 안전 (clobber 없음).
#   - smp_jeju_rt 가 없을 때의 da 대체(smp_jeju_da)는 *서빙/학습 레이어*의 제한적
#     사용이며, 저장 단계에선 RT 를 순수 유지(없으면 컬럼 NULL).  여기선 대체 안 함.
_JEJU_RT_GUGAN = ["smp_rt_g1", "smp_rt_g2", "smp_rt_g3", "smp_rt_g4"]
_JEJU_RT_MEAN = "smp_jeju_rt"
_JEJU_RT_NEG_NUM = "smp_rt_neg_num"
# 한 구간이 이 값 미만이면 '음수권'으로 카운트 (smp_rt_neg_num).  과거 boolean
# flag 는 <0 기준이었으나, 바닥권(0~5) 도 음수 위험 신호라 임계를 5 로 올렸다.
_JEJU_RT_NEG_THRESHOLD = 5.0


def _fetch_jeju_rt_smp_one_day(
    target_date: str, service_key: str, retry: int = 3,
) -> pd.DataFrame:
    """하루치(24h x 4구간) 호출 -> 구간별 + 파생 wide DF (timestamp index).

    target_date : 'YYYY-MM-DD'.  API 는 'YYYYMMDD'.
    반환 컬럼: smp_rt_g1..g4(구간 원시 RT SMP), smp_jeju_rt(시간평균),
              smp_rt_neg_num(구간 중 <NEG_THRESHOLD 개수 0..4).
    미발행/빈 응답이면 빈 DF.  5xx/네트워크 오류는 backoff 재시도(KPX 불안정 대응).
    """
    params = {
        "serviceKey": service_key,
        "dataType": "json",
        "date": target_date.replace("-", ""),
        "pageNo": "1",
        "numOfRows": "200",   # 24h x 4구간 = 96 < 200, 한 번에 전량.
    }
    body = None
    for attempt in range(retry):
        try:
            resp = requests.get(KPX_JEJU_RT_URL, params=params, timeout=30)
            if resp.status_code == 200:
                # data.go.kr 은 오류 시 XML 을 주기도 함 -> JSON 파싱 실패는 빈 응답 취급.
                try:
                    body = resp.json().get("response", {}).get("body", {}) or {}
                except ValueError:
                    return pd.DataFrame()
                break
            if 500 <= resp.status_code < 600 and attempt < retry - 1:
                time.sleep(2 ** (attempt + 1))
                continue
            resp.raise_for_status()
            return pd.DataFrame()
        except (requests.Timeout, requests.ConnectionError):
            if attempt < retry - 1:
                time.sleep(2 ** (attempt + 1))
                continue
            raise
    if not body:
        return pd.DataFrame()

    items = (body.get("items") or {}).get("item")
    if not items:
        return pd.DataFrame()
    df = pd.DataFrame(items)
    needed = {"hour", "jsmpRt", "gugan"}
    if df.empty or not needed.issubset(df.columns):
        return pd.DataFrame()

    df["hour"] = pd.to_numeric(df["hour"], errors="coerce")
    df["jsmpRt"] = pd.to_numeric(df["jsmpRt"], errors="coerce")
    # gugan 라벨은 EUC-KR 깨짐('1����' 등)이나 선두 숫자가 구간 인덱스(1..4).
    df["gnum"] = pd.to_numeric(
        df["gugan"].astype(str).str.extract(r"^\s*(\d)")[0], errors="coerce"
    )
    df = df.dropna(subset=["hour", "jsmpRt", "gnum"])
    df = df[df["gnum"].between(1, 4)]
    if df.empty:
        return pd.DataFrame()
    df["gnum"] = df["gnum"].astype(int)

    # hour x 구간 피벗 -> g1..g4 (한 시간에 4구간).  중복 구간이 와도 평균으로 합침.
    pivot = df.pivot_table(
        index="hour", columns="gnum", values="jsmpRt", aggfunc="mean",
    ).reindex(columns=[1, 2, 3, 4])
    pivot.columns = _JEJU_RT_GUGAN

    out = pivot.round(4)
    # 파생: 시간평균(타깃) + 음수권 구간 개수.  g 가 일부 NaN 이어도 안전하게 집계.
    out[_JEJU_RT_MEAN] = pivot.mean(axis=1).round(4)
    out[_JEJU_RT_NEG_NUM] = (
        (pivot < _JEJU_RT_NEG_THRESHOLD).sum(axis=1).astype(int)
    )

    # KPX hour 1..24 -> 00:00 ~ 23:00 (hour-1).
    out.index = (
        pd.to_datetime(target_date)
        + pd.to_timedelta(out.index.astype(int) - 1, unit="h")
    ).strftime("%Y-%m-%d %H:%M:%S")
    out.index.name = "timestamp"
    return out.sort_index()


def fetch_kpx_jeju_rt_smp(
    start_date: str,
    end_date: str,
    service_key: str | None = None,
    sleep_sec: float = DEFAULT_SLEEP_SEC,
    progress: bool = True,
) -> pd.DataFrame:
    """제주 실시간시장 RT SMP 를 [start..end] 일별 호출 -> wide DataFrame.

    Returns 컬럼 (6 cols, historical 전용):
        smp_rt_g1..g4    : 구간별 원시 실시간 SMP
        smp_jeju_rt      : 구간 평균 실시간 SMP (모델 타깃)
        smp_rt_neg_num   : 그 시간 4구간 중 <NEG_THRESHOLD 인 구간 개수 (0..4)

    미발행 미래/지연 일자는 빈 응답 -> 결과에서 누락(해당 시간 컬럼 NULL 유지).
    """
    key = service_key or KPX_API_KEY
    if not key:
        sys.exit("KPX_API_KEY is not set (check .env)")
    s = datetime.strptime(start_date, "%Y-%m-%d")
    e = datetime.strptime(end_date, "%Y-%m-%d")
    if s > e:
        raise ValueError(f"start_date ({start_date}) > end_date ({end_date})")

    days: list[pd.DataFrame] = []
    cur = s
    while cur <= e:
        d_str = cur.strftime("%Y-%m-%d")
        try:
            df = _fetch_jeju_rt_smp_one_day(d_str, key)
            if progress:
                # 음수권(neg_num>0) 시간 수 -- 발행 품질 한눈 확인용.
                n_neg = int((df[_JEJU_RT_NEG_NUM] > 0).sum()) if not df.empty else 0
                print(f"  [rt_smp] {d_str}  rows={len(df)}  neg_hours={n_neg}")
            if not df.empty:
                days.append(df)
        except Exception as ex:
            print(f"  [rt_smp] {d_str}  FAIL: {ex}")
        cur += timedelta(days=1)
        if cur <= e:
            time.sleep(sleep_sec)
    if not days:
        return pd.DataFrame()
    out = pd.concat(days).sort_index()
    out.index.name = "timestamp"
    return out


# NOTE: KMA ASOS fetcher 는 _common (_fetch_asos_one_station_chunk) + kma_fetcher_jeju
# (fetch_asos, 3지점) 로 이동했다 (ASOS 는 KMA 관측이라 KPX 모듈에서 분리).


# ── 테스트 CLI ─────────────────────────────────────────────────────────
# 각 fetcher 의 결과를 단독 CSV 로 저장.
def _save_csv(df: pd.DataFrame, label: str, out_path: Path) -> None:
    if df.empty:
        print(f"  [{label}] empty - no CSV written")
        return
    out_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out_path, encoding="utf-8-sig")
    print(f"  [{label}] saved {len(df)} rows -> {out_path}")


def main() -> None:
    today = datetime.now().date()
    p = argparse.ArgumentParser(
        description=(
            "KPX jeju (chejusukub) / est (DA SMP) fetcher test CLI (제주 전용).  "
            "Each source writes a CSV under data/.  (ASOS -> kma_fetcher_jeju)"
        ),
    )
    p.add_argument(
        "--start", default=None,
        help="YYYY-MM-DD (default: yesterday)",
    )
    p.add_argument(
        "--end", default=None,
        help="YYYY-MM-DD (default: today)",
    )
    p.add_argument(
        "--source", choices=["jeju", "est", "all"],
        default="all",
        help="which fetcher(s) to run (default: both)",
    )
    p.add_argument(
        "--out-dir", type=Path, default=None,
        help="output dir (default: <repo>/data)",
    )
    p.add_argument(
        "--chunk-days", type=int, default=MAX_CHUNK_DAYS,
        help=f"chunk size (1..{MAX_CHUNK_DAYS}, default {MAX_CHUNK_DAYS})",
    )
    args = p.parse_args()

    s = args.start or (today - timedelta(days=1)).strftime("%Y-%m-%d")
    e = args.end or today.strftime("%Y-%m-%d")

    out_dir = args.out_dir or (
        Path(__file__).resolve().parent.parent / "data"
    )
    print(f"[api_fetchers_jeju] range={s} ~ {e}  source={args.source}  out={out_dir}")

    if args.source in ("jeju", "all"):
        df = fetch_kpx_jeju(s, e, chunk_days=args.chunk_days)
        _save_csv(df, "*_jeju", out_dir / f"kpx_jeju_{s}_{e}.csv")
    if args.source in ("est", "all"):
        df = fetch_kpx_est(s, e)
        _save_csv(df, "*_da",   out_dir / f"kpx_est_{s}_{e}.csv")


if __name__ == "__main__":
    main()

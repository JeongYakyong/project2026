"""
api_fetchers_land.py -- 육지(본토) API fetcher 허브 (KMA + KPX).

순수 fetcher 모듈: 모든 함수가 timestamp-indexed wide DataFrame 을 반환하고
**자체 DB 는 만들지 않는다** (2026-06-01 in-memory 리팩터 -- KIMG-land / ASOS-land
중간 DB 제거).  collect_data_land 가 이 fetcher 들을 import 해 input_data_land.db 에
바로 UPSERT 한다.

담는 것:
  [KMA]
  - fetch_asos_land(start,end) -> ASOS-land 5 지점 관측 wide (메모리; asos_land.db 없음).
  - POINTS (KIMG-land 5 지점) + forecast_days_override : collect_data_land 의
    in-memory KIMG fetch(fetch_kimg_land_long)가 _common KIMG core 와 함께 사용.
  [KPX]
  - fetch_kpx_land(start,end)  -> sukub *_land 수급 7 cols.
  - fetch_land_est(start,end)  -> smp_land_da / land_est_demand_da (*_da) 2 cols.
  - fetch_land_power(start,end)-> 발전원별 실적 gen_*_kr 15 cols (powerSource.es, 전국).

CLI (테스트 CSV 만; 운영 적재는 collect_data_land.py):
    python api_fetchers_land.py --source asos  --start 2026-05-01 --end 2026-05-26
    python api_fetchers_land.py --source sukub --start 2026-05-01 --end 2026-05-26
    python api_fetchers_land.py --source est   --start 2026-05-01 --end 2026-05-26
    python api_fetchers_land.py --source power --start 2026-05-01 --end 2026-05-26

대상 지점 (KMA ASOS 지점번호 / 지역 대표성)
    100 대관령  강원 고지대 산악 풍력 독점 지표 (강릉 중복 제거)
    114 원주    강원 영서 남부 내륙 및 충북 완충 구역
    129 서산    충남 서해안 대규모 솔라 벨트 대변 (홍성 중복 제거)
    138 포항    경북 동해안 해안 기후 및 풍력 단지 지표
    252 영광군  전남 북서부 서해안 해상풍력 밸트 조준 (고창 중복 제거)
  point_name 은 ASCII (`Daegwallyeong(100)` 식) -- 한글은 Windows DB 브라우저에서
  CP949 깨짐.  지점번호를 괄호로 붙여 KIMG/ASOS 가 같은 문자열을 join 키로 쓴다.
"""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import random
import re
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd
import requests

# _common 의 공유 primitive 재사용 (같은 core/ 디렉터리).  이 모듈은 순수 fetcher 허브
# -- DataFrame 만 반환하고 자체 DB 는 만들지 않는다.  KIMG 예보는 collect_data_land 가
# _common KIMG core 로 메모리에서 직접 받으므로 여기서 KIMG/ASOS 수집기를 두지 않는다.
import _common as ckg  # FORECAST_DAYS 글로벌을 임시 오버라이드하기 위한 모듈 핸들
from _common import (
    KMA_API_KEY,
    current_kma_key,
    KPX_API_KEY,
    KPX_BASE_HEADERS,
    MAX_CHUNK_DAYS,
    DEFAULT_SLEEP_SEC,
    _chunk_date_range,
    _decode_kpx,
    _fetch_asos_one_station_chunk,
)


@contextlib.contextmanager
def forecast_days_override(days: int | None):
    """수집 윈도우 길이(_common.FORECAST_DAYS)를 임시로 바꾼다.

    days=None 이면 기본값(2일=48h) 그대로.  collection_window / collection_hf_range
    가 호출시점에 모듈 글로벌 FORECAST_DAYS 를 읽으므로, 이 값을 바꾸면 윈도우·hf range·
    로그가 일관되게 함께 줄어든다.  issue=18 고정 day-ahead 백필에서 days=1 로 두면
    한 (발표,지점)당 hf 호출이 48->24 로 절반이 돼 quota 안에 들어온다 (D+1 만 수집).
    제주 파이프라인도 같은 _common 글로벌을 읽으므로 컨텍스트 밖에서는 영향 없음.
    """
    if days is None:
        yield
        return
    old = ckg.FORECAST_DAYS
    ckg.FORECAST_DAYS = days
    try:
        yield
    finally:
        ckg.FORECAST_DAYS = old


# ── KIMG-land 수집 지점 (lat, lon).  _common 의 POINTS 만 본 5 지점으로 교체. ──────
# collect_data_land.fetch_kimg_land_long 이 이 POINTS 로 _common KIMG core 를 호출한다.
POINTS = [
    {"name": "Daegwallyeong(100)", "lat": 37.6772, "lon": 128.7185},  # 대관령 -- 강원 고지대 산악 풍력
    {"name": "Wonju(114)",         "lat": 37.3376, "lon": 127.9466},  # 원주   -- 강원 영서 남부 / 충북 완충
    {"name": "Seosan(129)",        "lat": 36.7766, "lon": 126.4939},  # 서산   -- 충남 서해안 솔라 벨트
    {"name": "Pohang(138)",        "lat": 36.0327, "lon": 129.3799},  # 포항   -- 경북 동해안 풍력
    {"name": "Yeonggwang(252)",    "lat": 35.2807, "lon": 126.4750},  # 영광군 -- 전남 북서부 해상풍력
]


# ════════════════════════════════════════════════════════════════════════
# ASOS-land 관측 fetcher (메모리; asos_land.db 없음).
# _common 의 station primitive 를 5 지점에 적용해 wide 관측 DF 를 반환한다.
# stn_id 는 KMA ASOS 표준 지점번호 (= 위 KIMG POINTS 의 name 괄호 안 숫자와 동일).
# suffix 는 제주의 west/east/south 와 같은 역할의 지점 join 키 (romanized 소문자).
# ════════════════════════════════════════════════════════════════════════
LAND_ASOS_STATIONS = [
    {"stn_id": 100, "name": "Daegwallyeong(100)", "suffix": "daegwallyeong"},  # 대관령
    {"stn_id": 114, "name": "Wonju(114)",         "suffix": "wonju"},          # 원주
    {"stn_id": 129, "name": "Seosan(129)",        "suffix": "seosan"},         # 서산
    {"stn_id": 138, "name": "Pohang(138)",        "suffix": "pohang"},         # 포항
    {"stn_id": 252, "name": "Yeonggwang(252)",    "suffix": "yeonggwang"},     # 영광군
]


def fetch_asos_land(
    start_date: str,
    end_date: str,
    chunk_days: int = MAX_CHUNK_DAYS,
    sleep_sec: float = DEFAULT_SLEEP_SEC,
    progress: bool = True,
) -> pd.DataFrame:
    """육지 5 지점 ASOS 관측 -> wide DataFrame (메모리; asos_land.db 없이).

    제주 api_fetchers_jeju.fetch_asos 의 육지판.  지점별로 chunk fetch -> 일사 야간
    결측 채움 -> 컬럼에 <var>_<suffix> 접미사 -> axis=1 concat.  결측(NaN)은 그대로
    두고(보간은 downstream), 일사 센서 없는 지점은 solar_rad 컬럼이 전부 NaN.

    컬럼명: <var>_<suffix>  (예: temp_c_seosan, wind_spd_pohang, solar_rad_daegwallyeong).
    제주 historical 의 base 변수명(temp_c/humidity/total_cloud/midlow_cloud/wind_spd/
    wd_sin/wd_cos/solar_rad/rainfall/snow_depth)과 1:1 동일, 지점 suffix 만 다르다.

    결측(null) 정책 (제주 fetch_asos 와 동일):
        rainfall  : 관측 결측(-9) -> 0 (무강수)
        solar_rad : 센서 가동일의 야간 결측만 -> 0, 무센서/비가동 구간은 NaN
        그 외      : NaN 유지 (보간은 downstream)
    """
    key = current_kma_key()
    if not key:
        sys.exit("KMA_API_KEY is not set (check .env)")

    parts: list[pd.DataFrame] = []
    for st in LAND_ASOS_STATIONS:
        chunks: list[pd.DataFrame] = []
        for s, e in _chunk_date_range(start_date, end_date, chunk_days):
            try:
                df = _fetch_asos_one_station_chunk(s, e, st["stn_id"], key)
                if progress:
                    print(
                        f"  [asos] {s} ~ {e}  stn={st['stn_id']} "
                        f"({st['suffix']:<14})  rows={len(df)}"
                    )
                if not df.empty:
                    chunks.append(df)
            except Exception as ex:
                print(
                    f"  [asos] {s} ~ {e}  stn={st['stn_id']} "
                    f"({st['suffix']})  FAIL: {ex}"
                )
            time.sleep(sleep_sec)

        if not chunks:
            continue
        df_st = (
            pd.concat(chunks)
              .reset_index()
              .drop_duplicates(subset="timestamp")
              .set_index("timestamp")
              .sort_index()
        )
        # 일사(SI) 야간 결측 채움: '그 날 한 번이라도 보고했는가'로 센서 가동일을 판정해
        # 가동일의 NaN(=야간)만 0 으로.  센서 없는 지점은 전부 NaN 으로 남는다.
        if "solar_rad" in df_st.columns:
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
# KPX 육지 fetcher (구 kpx_fetcher_land 통합) + powerSource.es 인라인.
# ========================================================================
KPX_LAND_URL = "https://openapi.kpx.or.kr/downloadSukubCSV.do"
KPX_EST_URL = (
    "https://apis.data.go.kr/B552115/SmpWithForecastDemand/getSmpWithForecastDemand"
)


# ── DA SMP/est fetcher (제주 kpx_fetcher_jeju 와 중복 보유) ────────────────
# 제주는 4컬럼 전부, 육지는 fetch_land_est 가 _land 2컬럼만 추려 쓴다.
def _fetch_kpx_est_one_day(target_date: str, service_key: str) -> pd.DataFrame:
    """하루치 (24h × 제주+육지) 호출 -> wide DF (timestamp index)."""
    params = {
        "serviceKey": service_key,
        "dataType": "json",
        "date": target_date.replace("-", ""),
        "numOfRows": "100",
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
    df_jeju = df[df["areaName"] == "제주"][["date", "hour", "smp", "jlfd"]].rename(
        columns={"smp": "smp_jeju_da", "jlfd": "jeju_est_demand_da"}
    )
    df_land = df[df["areaName"] == "육지"][["date", "hour", "smp", "mlfd"]].rename(
        columns={"smp": "smp_land_da", "mlfd": "land_est_demand_da"}
    )
    merged = pd.merge(df_jeju, df_land, on=["date", "hour"], how="outer")
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
    """일전(DA) SMP(제주/육지) + 예상수요 wide DataFrame (4 cols, *_da).  일 단위 호출."""
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


# ── 1. 육지 sukub 계통 수급 (*_land) ──────────────────────────────────────
_KPX_LAND_RENAME = {
    "공급능력(MW)":      "supply_cap_land",
    "현재수요(MW)":      "real_demand_land",
    "최대예측수요(MW)":  "max_pred_demand_land",
    "공급예비력(MW)":    "supply_reserve_land",
    "공급예비율(%)":     "supply_reserve_pct_land",
    "운영예비력(MW)":    "oper_reserve_land",
    "운영예비율(%)":     "oper_reserve_pct_land",
}


def _fetch_kpx_land_chunk(start_date: str, end_date: str) -> pd.DataFrame:
    headers = {**KPX_BASE_HEADERS, "Referer": "https://openapi.kpx.or.kr/sukub.do"}
    resp = requests.post(
        KPX_LAND_URL,
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
    df = df.rename(columns=_KPX_LAND_RENAME)
    cols = ["timestamp"] + [v for v in _KPX_LAND_RENAME.values() if v in df.columns]
    df = df[cols].copy()
    for c in cols[1:]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df


def fetch_kpx_land(
    start_date: str,
    end_date: str,
    chunk_days: int = MAX_CHUNK_DAYS,
    sleep_sec: float = DEFAULT_SLEEP_SEC,
    progress: bool = True,
) -> pd.DataFrame:
    """육지 sukub 계통 수급 1h wide DataFrame (7 cols, *_land suffix).  실패 시 빈 DF."""
    chunks: list[pd.DataFrame] = []
    for s, e in _chunk_date_range(start_date, end_date, chunk_days):
        try:
            df = _fetch_kpx_land_chunk(s, e)
            if progress:
                print(f"  [*_land] {s} ~ {e}  rows={len(df)}")
            if not df.empty:
                chunks.append(df)
        except Exception as ex:
            print(f"  [*_land] {s} ~ {e}  FAIL: {ex}")
        time.sleep(sleep_sec)
    if not chunks:
        return pd.DataFrame()
    out = (
        pd.concat(chunks, ignore_index=True)
          .drop_duplicates(subset="timestamp")
          .sort_values("timestamp")
          .set_index("timestamp")
    )
    out.index.name = "timestamp"
    return out


# ── 2. 육지 일전(DA) SMP + 예상수요 (smp_land_da / land_est_demand_da) ─────
def fetch_land_est(
    start_date: str,
    end_date: str,
    service_key: str | None = None,
    sleep_sec: float = DEFAULT_SLEEP_SEC,
    progress: bool = True,
) -> pd.DataFrame:
    """육지 일전 SMP + 예상수요만 추린 wide DataFrame (2 cols, *_da).

    제주 모듈의 fetch_kpx_est(제주/육지 DA 를 한 호출로 받음)를 그대로 호출하고,
    육지 컬럼 smp_land_da / land_est_demand_da 만 남긴다 (제주 컬럼은 제주 DB 담당).
    """
    df = fetch_kpx_est(
        start_date, end_date, service_key=service_key,
        sleep_sec=sleep_sec, progress=progress,
    )
    if df.empty:
        return df
    cols = [c for c in ("smp_land_da", "land_est_demand_da") if c in df.columns]
    out = df[cols].copy()
    out.index.name = "timestamp"
    return out


# ── powerSource.es 저수준 fetcher (구 kpx_power.py, 인라인 통합) ──────────
# KPX 발전원별 전력수급현황 (powerSource.es) 5분 원본 -> interval 다운샘플.
_POWER_URL = "https://www.kpx.or.kr/powerSource.es"
_POWER_PARAMS_BASE = {"mid": "a10404030000", "device": "chart"}
_POWER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Referer": "https://www.kpx.or.kr/powerSource.es?mid=a10404030000&device=chart",
    "Accept-Language": "ko-KR,ko;q=0.9",
}
_POWER_COL_MAP = {
    "regDate":      "timestamp",
    "btm":          "태양광(BTM,추정)",
    "ppa":          "태양광(PPA,추정)",
    "sunlight":     "태양광(전력시장)",
    "raisingWater": "양수",
    "waterPower":   "수력",
    "gas":          "가스",
    "windPower":    "풍력",
    "newRenewable": "신재생",
    "oil":          "유류",
    "localCoal":    "국내탄",
    "coal":         "유연탄",
    "nuclearPower": "원자력",
}
_VALID_INTERVALS = (10, 30, 60)


def _parse_ict_arr(html: str) -> list[dict]:
    m = re.search(r'var\s+ictArr\s*=\s*(\[.*?\]);', html, re.DOTALL)
    if not m:
        return []
    return json.loads(m.group(1))


def _power_to_df(records: list[dict], interval: int = 60) -> pd.DataFrame:
    if not records:
        return pd.DataFrame()
    if interval not in _VALID_INTERVALS:
        raise ValueError(f"interval은 {_VALID_INTERVALS} 중 하나여야 합니다.")
    df = pd.DataFrame(records)
    cols = [c for c in _POWER_COL_MAP if c in df.columns]
    df = df[cols].rename(columns=_POWER_COL_MAP)
    for col in df.columns:
        if col != "timestamp":
            df[col] = pd.to_numeric(df[col], errors="coerce")
    # 당일(미실현 시간대)의 regDate placeholder 는 NaT -> 제거.
    df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
    df = df.dropna(subset=["timestamp"]).reset_index(drop=True)
    if df.empty:
        return df
    # interval(분)에 정렬된 시각(60->:00)의 *순시값(스냅샷)* 행만 남긴다 (시간평균 아님).
    # 위치(iloc[::step]) 기반 다운샘플은 하루 첫 레코드가 정시가 아니거나 raw 간격이
    # 5분이 아니면 어긋나(이후 분=0 필터에서 전부 탈락 -> 하루 통째 손실) 시각(분) 기준
    # 선택이 안전하다.  timestamp 는 위에서 datetime 으로 변환됨.
    df = df[df["timestamp"].dt.minute % interval == 0].reset_index(drop=True)
    return df


def _power_fetch_day(
    target_date: str, interval: int = 60, session: requests.Session | None = None,
) -> pd.DataFrame:
    s = session or requests.Session()
    params = {**_POWER_PARAMS_BASE, "view_sdate": target_date, "view_edate": target_date}
    resp = s.get(_POWER_URL, params=params, headers=_POWER_HEADERS, timeout=15)
    resp.raise_for_status()
    return _power_to_df(_parse_ict_arr(resp.text), interval=interval)


def fetch_range(
    start: str, end: str, interval: int = 60, delay: float = 0.5, verbose: bool = True,
) -> pd.DataFrame:
    """powerSource.es 를 [start..end] 일 단위로 받아 합친 DataFrame (한글 컬럼)."""
    s = requests.Session()
    cur = date.fromisoformat(start)
    end_d = date.fromisoformat(end)
    all_dfs = []
    while cur <= end_d:
        ds = cur.isoformat()
        try:
            df = _power_fetch_day(ds, interval=interval, session=s)
            if df.empty:
                if verbose:
                    print(f"  {ds} -> 데이터 없음")
            else:
                all_dfs.append(df)
                if verbose:
                    print(f"  {ds} -> {len(df)}건")
        except Exception as e:
            if verbose:
                print(f"  {ds} -> 오류: {e}")
        cur += timedelta(days=1)
        if cur <= end_d:
            time.sleep(delay + random.uniform(0, 0.3))
    if not all_dfs:
        return pd.DataFrame()
    return pd.concat(all_dfs, ignore_index=True)


# ── 3. 발전원별 발전실적 (상세, gen_*_kr) -- 위 powerSource fetch_range 사용 ──
# powerSource.es 는 *전국(제주+육지 합산)* 발전 데이터다 -- 풍력/태양광 등은 제주분이
# 포함된 전국 값.  그래서 육지 전용인 sukub(*_land)/est(*_da)와 달리 **_kr 접미사**를
# 쓴다 (제주분만 따로 있는 real_solar_gen_jeju / real_wind_gen_jeju 와도 구분).  한글
# 컬럼을 ASCII gen_*_kr 로 매핑 (DB 값/컬럼은 ASCII 규칙).  태양광은 BTM/PPA/전력시장
# 3종으로 분리돼 기존 PwrAmountByGen(합산)보다 상세하다.
_POWER_RENAME = {
    "태양광(BTM,추정)":  "gen_solar_btm_kr",
    "태양광(PPA,추정)":  "gen_solar_ppa_kr",
    "태양광(전력시장)":  "gen_solar_market_kr",
    "양수":              "gen_pumped_kr",
    "수력":              "gen_hydro_kr",
    "가스":              "gen_gas_kr",
    "풍력":              "gen_wind_kr",
    "신재생":            "gen_nre_kr",   # 신재생에너지(NRE) -- renew_gen_total_kr 와 구분.
    "유류":              "gen_oil_kr",
    "국내탄":            "gen_localcoal_kr",
    "유연탄":            "gen_coal_kr",
    "원자력":            "gen_nuclear_kr",
}


def fetch_land_power(
    start_date: str,
    end_date: str,
    interval: int = 60,
    progress: bool = True,
) -> pd.DataFrame:
    """발전원별 발전실적(상세) wide DataFrame (15 cols, *전국* -> _kr 접미사).

    fetch_range(위 인라인 powerSource fetcher)로 받아 매시 정각(분=0) 행만 남기고
    한글 컬럼을 ASCII gen_*_kr 로 매핑 (12 발전원) + 파생 집계 3종
    (gen_total_kr / renew_gen_total_kr / net_load_kr).  interval=60 -> 1h 순시값.
    """
    raw = fetch_range(
        start_date, end_date, interval=interval, verbose=progress,
    )
    if raw.empty:
        return pd.DataFrame()

    df = raw.rename(columns=_POWER_RENAME)
    # 매시 정각만 (kpx_power 가 interval=60 이면 이미 시각 정렬돼 있으나 방어적으로 필터).
    ts = pd.to_datetime(df["timestamp"])
    df = df[(ts.dt.minute == 0) & (ts.dt.second == 0)].copy()
    df["timestamp"] = pd.to_datetime(df["timestamp"]).dt.strftime("%Y-%m-%d %H:%M:%S")

    gen_cols = [c for c in _POWER_RENAME.values() if c in df.columns]
    out = df[["timestamp"] + gen_cols].copy()
    for c in gen_cols:
        out[c] = pd.to_numeric(out[c], errors="coerce")
    out = (
        out.drop_duplicates(subset="timestamp")
           .sort_values("timestamp")
           .set_index("timestamp")
    )
    out.index.name = "timestamp"

    # 파생 집계 (kpx_gen_historical.csv 의 total / solar_wind_total / net_load 정의와 동일).
    #   gen_total_kr       = 12개 발전원 합계 (전국).
    #   renew_gen_total_kr = 태양광(전력시장) + 풍력  (BTM/PPA 추정 태양광 제외 -- 사용자 정의).
    #   net_load_kr        = gen_total_kr - renew_gen_total_kr.
    # 한 발전원이라도 NaN(미수집)이면 집계도 NaN 으로 둔다 (skipna=False).  0 으로
    # 채우면 결측 구간을 나중에 보간(interpolate)할 수 없으므로, 누락은 NaN 으로 보존해
    # 보간 가능하게 한다.  세 집계 모두 동일 정책 (net_load 는 차라 NaN 이 자연 전파).
    # (성분 컬럼이 아예 부재면 KeyError 방지로 필터; 둘 다 없으면 renew=NaN.)
    out["gen_total_kr"] = out[gen_cols].sum(axis=1, skipna=False)
    _renew_cols = [c for c in ("gen_solar_market_kr", "gen_wind_kr") if c in out.columns]
    out["renew_gen_total_kr"] = (
        out[_renew_cols].sum(axis=1, skipna=False) if _renew_cols else float("nan")
    )
    out["net_load_kr"] = out["gen_total_kr"] - out["renew_gen_total_kr"]
    return out


# ── 테스트 CLI (fetcher 결과를 data/ 에 CSV 로 저장; 운영 적재는 collect_data_land) ──
def _save_csv(df: pd.DataFrame, label: str, out_path: Path) -> None:
    if df.empty:
        print(f"  [{label}] empty - no CSV written")
        return
    out_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out_path, encoding="utf-8-sig")
    print(f"  [{label}] saved {len(df)} rows x {len(df.columns)} cols -> {out_path}")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=(
            "Land (mainland) API fetchers -- pure fetcher hub (returns DataFrames; "
            "no intermediate DB).  --source asos (ASOS-land obs) / sukub (*_land 수급) / "
            "est (*_da SMP/예상수요) / power (gen_*_kr 발전, powerSource.es).  "
            "Writes a test CSV to data/ (production ingest is collect_data_land.py)."
        )
    )
    p.add_argument(
        "--source", choices=["asos", "sukub", "est", "power"], default="power",
        help="which fetcher to test -> CSV (default power)",
    )
    p.add_argument("--start", default=None, help="YYYY-MM-DD (default: yesterday)")
    p.add_argument("--end", default=None, help="YYYY-MM-DD (default: today)")
    p.add_argument(
        "--chunk-days", type=int, default=MAX_CHUNK_DAYS,
        help=f"[asos] chunk size (1..{MAX_CHUNK_DAYS}, default {MAX_CHUNK_DAYS})",
    )
    p.add_argument(
        "--interval", type=int, default=60, choices=[10, 30, 60],
        help="[power] powerSource interval minutes (default 60)",
    )
    p.add_argument(
        "--out-dir", type=Path, default=None,
        help="test-CSV output dir (default <repo>/data)",
    )
    return p.parse_args()


def main() -> None:
    args = parse_args()
    today = datetime.now().date()
    s = args.start or (today - timedelta(days=1)).strftime("%Y-%m-%d")
    e = args.end or today.strftime("%Y-%m-%d")
    out_dir = args.out_dir or (Path(__file__).resolve().parent.parent / "data")
    print(f"[api_fetchers_land] range={s} ~ {e}  source={args.source}  out={out_dir}")
    if args.source == "asos":
        _save_csv(
            fetch_asos_land(s, e, chunk_days=args.chunk_days),
            "asos-land", out_dir / f"land_asos_{s}_{e}.csv",
        )
    elif args.source == "sukub":
        _save_csv(fetch_kpx_land(s, e), "*_land", out_dir / f"land_sukub_{s}_{e}.csv")
    elif args.source == "est":
        _save_csv(fetch_land_est(s, e), "*_da", out_dir / f"land_est_{s}_{e}.csv")
    elif args.source == "power":
        _save_csv(
            fetch_land_power(s, e, interval=args.interval),
            "gen_*_kr", out_dir / f"land_power_{s}_{e}.csv",
        )


if __name__ == "__main__":
    main()

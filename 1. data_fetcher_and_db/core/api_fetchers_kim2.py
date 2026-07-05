"""api_fetchers_kim2.py -- 신 KIM 표준 API(nph-kim_nc_pt_txt2_std) fetcher 허브.

2026-07-01 KMA 개편 대응 v2 수집기의 fetch 계층 (new_kma 연구로 검증, REPORT_01~03).
기존 core/ 파일은 수정하지 않는다 -- _common 의 검증된 HTTP/키풀 스택을 import 재사용.

핵심 사실 (실측 검증 2026-07-04)
- 엔드포인트: typ06/cgi-bin/url/nph-kim_nc_pt_txt2_std -- 위경도 직접 입력,
  콤마 멀티변수 1콜, 3모델(KIMG/NE57·KIMR/R030·KIML/L010) 지원, 디코더 정상
  (격자 방식 xy_txt2_std 의 전구 화면고도 버그 없음).
- R030(지역 3km): 00/12z 최대 120h·06/18z 72h, 전 구간 1h.  운량 없음.
- L010(국지 1.3km): 4주기 48h, 전 구간 1h.
- GHI(전천일사) = SWDDIR2(수평면 직달) + SWDDIF2(산란) -- 물리 검증 완료.

지점 확장 규약 (사용자 요구: 5->17지점 같은 확장 + 그 지점만 백필)
- POINTS_*_V2 리스트가 SSOT: [{"name","sfx","lat","lon"}].  지점 추가 = 1줄.
- 컬럼 접미사(sfx)는 명시 필드 -- 이름 파싱 없음.
- 지점 단위 부분 수집은 collect_forecast_v2 의 --points 와 컬럼 보존 upsert 가 담당.
"""
from __future__ import annotations

import os
import threading
import time
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import requests

import _common as ckg
from _common import (
    KST,
    UTC,
    MAX_WORKERS,
    RETRY_MAX,
    _kma_session,
    kma_quota_exceeded,
    freshest,
)
import api_fetchers_land as ckl

URL_PT_STD = "https://apihub.kma.go.kr/api/typ06/cgi-bin/url/nph-kim_nc_pt_txt2_std"

# 발표시각(UTC)별 최대 리드(h) -- 2026-07-04 전수 스캔 실측 (new_kma REPORT_02 §3).
R030_MAX_HF = {0: 120, 6: 72, 12: 120, 18: 72}
L010_MAX_HF = {0: 48, 6: 48, 12: 48, 18: 48}

# ── 지점 SSOT (sfx 명시 -- 지점 확장 시 여기에 1줄 추가) ────────────────────
# 좌표는 운영(api_fetchers_land.POINTS / api_fetchers_jeju)과 동일.
# grib 시계열 경로도 위경도 직접 입력을 지원함을 실측 확인(2026-07-04) -- 위경도로
# 주면 std(pt_txt2_std)와 같은 셀로 해석돼 소스 간 셀 일관성이 보장된다.
# (자체 X/Y 를 주면 최근접 산정 차이로 한 셀 어긋날 수 있음.)  지점 추가 = 이 리스트에
# 위경도 1줄이면 끝, 격자 변환 불필요.
POINTS_LAND_V2 = [
    {"name": "Daegwallyeong(100)", "sfx": "daegwallyeong", "lat": 37.6772, "lon": 128.7185},
    {"name": "Wonju(114)",         "sfx": "wonju",         "lat": 37.3376, "lon": 127.9466},
    {"name": "Seosan(129)",        "sfx": "seosan",        "lat": 36.7766, "lon": 126.4939},
    {"name": "Pohang(138)",        "sfx": "pohang",        "lat": 36.0327, "lon": 129.3799},
    {"name": "Yeonggwang(252)",    "sfx": "yeonggwang",    "lat": 35.2807, "lon": 126.4750},
]
# ★제주는 x/y 고정 필수: 운영 grib 좌표(2026-05-25 "바다 셀 회피" 수동 보정 계승).
#   위경도 최근접은 서/동쪽이 바다 셀로 떨어져 met 값이 크게 어긋난다
#   (temp_skin 최대 9.5°C 차 실측 -- 해수면/지표 차이).  x/y 가 있으면 fetch 가
#   X/Y 인자로 셀을 고정한다(pt_txt2_std·grib 둘 다 지원 확인).
POINTS_JEJU_V2 = [
    {"name": "West(Gosan)",        "sfx": "west",  "lat": 33.4427, "lon": 126.1713, "x": 530, "y": 251},
    {"name": "East(Seongsan)",     "sfx": "east",  "lat": 33.3868, "lon": 126.8802, "x": 553, "y": 254},
    {"name": "solar_farm(south)",  "sfx": "south", "lat": 33.3284, "lon": 126.8366, "x": 550, "y": 250},
]

# 요청 변수 묶음 (콤마 멀티변수 1콜).  대소문자 엄격 -- KIM 변수정보 PDF 기준.
# MSLP = 해면기압(급변동 감지: 기압 경향 = 전선·기압골 접근, 2026-07-05 사용자 승인)
R030_NAME_LAND = ("T2,RH2,U10,V10,U80,V80,GUST,SWDDIR2,SWDDIF2,"
                  "RAINC,RAINNC,MCAPE,MCIN,PBLH,MSLP,ACSWDNB")
# 누적 변수 diff 기준점(hf=start-1) 전용.  강수(RAINC/RAINNC)와 ACSWDNB(누적 총일사)는
# 모두 base 부터 누적이라 시작 직전값이 있어야 첫 시각 diff 가 옳다.
R030_NAME_DIFF_ANCHOR = "RAINC,RAINNC,ACSWDNB"
R030_NAME_RAIN_ANCHOR = R030_NAME_DIFF_ANCHOR   # (구명 호환)
L010_NAME = R030_NAME_LAND                  # L010 도 동일 세트 (가용성 스윕 확인)
# ※ 제주 met 는 NC 가 아니라 KIMR GRIB 시계열(fetch_kimr_grib_long)이 최종이다
#   (2026-07-05: NC per-hf 는 혼잡 밤 마비 실측으로 기각).  제주 NC 는 일사 2변수만.


# ── kim2 전용 키 풀 ─────────────────────────────────────────────────────────
# ★신규 std API 는 키(계정)별 "활용신청"이 필요하다 (2026-07-04 실측: 미신청 키는
# 403 {"message": "활용신청이 필요한 API 입니다..."}).  _common 의 프로세스 공용
# 키 회전(rotate_kma_key)을 여기서 돌리면 구 엔드포인트(NE57 part)까지 예비 키로
# 끌려가므로, kim2 는 자기만의 키 인덱스를 쓴다 -- 등록 안 된 키는 건너뛰고
# 처음 성공한 키에 고정(pin), 한도 초과 시 다음 키로.
_K2_KEYS: list[str] = []
for _k in (os.getenv("KMA_API_KEY"), os.getenv("KMA_API_KEY_SUB"),
           os.getenv("KMA_API_KEY_SUB2"), os.getenv("KMA_API_KEY_SUB3")):
    if _k and _k not in _K2_KEYS:
        _K2_KEYS.append(_k)
_k2_idx = 0
_k2_lock = threading.Lock()
_NOT_REGISTERED_MARKER = "활용신청"   # "활용신청" (u-escape: 소스 인코딩 무관)


def _k2_current() -> str | None:
    return _K2_KEYS[_k2_idx] if _K2_KEYS else None


def _k2_rotate(bad_key: str | None, why: str) -> bool:
    """bad_key 가 여전히 현재 키일 때만 다음 키로.  남은 키 없으면 False."""
    global _k2_idx
    with _k2_lock:
        if _k2_current() != bad_key:
            return True
        if _k2_idx + 1 >= len(_K2_KEYS):
            return False
        _k2_idx += 1
        print(f"  [kim2-key] {why} -> 다음 키로 전환 ({_k2_idx + 1}/{len(_K2_KEYS)})")
        return True


# ── HTTP fetch (구 _common.fetch_one_hf 미러 -- 세션·백오프 동일) ────────────
def fetch_pt_std(
    group: str, nwp: str, name: str, base_utc: datetime, hf: int,
    lat: float, lon: float, x: int | None = None, y: int | None = None,
) -> str | None:
    """단일 (모델, 발표, 지점, hf) 호출.  plaintext body 반환 (실패 시 None).

    x/y 가 주어지면 격자 셀 고정(X/Y 인자 -- 제주 바다 셀 회피), 아니면 위경도
    최근접.  5xx/timeout 은 exponential backoff(2s,4s) 재시도.  '활용신청 필요'
    403 과 한도 초과는 kim2 전용 키 풀에서 다음 키로 전환 후 즉시 재시도.
    """
    params = {
        "group": group, "nwp": nwp, "data": "U", "name": name,
        "tmfc": base_utc.strftime("%Y%m%d%H"), "hf": str(hf),
        "disp": "A", "help": "0",
    }
    if x is not None and y is not None:
        params["X"], params["Y"] = str(x), str(y)
    else:
        params["lat"], params["lon"] = f"{lat:.4f}", f"{lon:.4f}"
    attempt = 0
    while attempt < RETRY_MAX:
        key = _k2_current()
        if key is None:
            return None
        params["authKey"] = key
        try:
            r = _kma_session.get(URL_PT_STD, params=params, timeout=30)
            if r.status_code == 403 and _NOT_REGISTERED_MARKER in r.text:
                # 이 키(계정)는 신규 API 미신청 -- 재시도 카운트 소모 없이 키만 전환.
                if _k2_rotate(key, "활용신청 안 된 키"):
                    continue
                return None
            if kma_quota_exceeded(r.status_code, r.text):
                if _k2_rotate(key, "한도 초과"):
                    continue
                return None
            if r.status_code == 200:
                return r.text
            if 500 <= r.status_code < 600 and attempt < RETRY_MAX - 1:
                attempt += 1
                time.sleep(2 ** attempt)
                continue
            return None
        except requests.RequestException:
            if attempt < RETRY_MAX - 1:
                attempt += 1
                time.sleep(2 ** attempt)
                continue
            return None
    return None


def parse_pt_std(body: str) -> dict[str, float]:
    """응답 -> {변수명: 값}.  행 = 'TMFC TMEF VARN LEVEL VALUS NAME(단위)'.

    변수명은 NAME 토큰에서 '(' 앞부분 -- VARN 숫자코드에 의존하지 않는다
    (모델·파일 개편 때 코드가 바뀌어도 이름은 유지되는 것을 신뢰).
    """
    out: dict[str, float] = {}
    for ln in body.splitlines():
        s = ln.strip()
        if not s or s.startswith("#"):
            continue
        parts = s.split()
        if len(parts) < 6:
            continue
        try:
            val = float(parts[4])
        except ValueError:
            continue
        out[parts[5].split("(")[0]] = val
    return out


# ── 카테고리 파생 (_common.derive_categories 의 R030/L010 판) ────────────────
# 라벨·반올림을 KIMG long 관례에 정확히 맞춰 기존 피벗 수식이 그대로 성립하게 한다.
def derive_r030_categories(raw: dict[str, float]) -> dict[str, float]:
    out: dict[str, float] = {}
    if "T2" in raw:
        out["TEMP_C"] = round(raw["T2"] - 273.15, 2)
    if "TSKIN" in raw:
        out["TEMP_SKIN"] = round(raw["TSKIN"] - 273.15, 2)
    if "RH2" in raw:
        out["REH"] = round(raw["RH2"], 2)
    for src, cat in (("U10", "WIND_U_10M"), ("V10", "WIND_V_10M"),
                     ("U80", "WIND_U_80M"), ("V80", "WIND_V_80M")):
        if src in raw:
            out[cat] = round(raw[src], 3)
    if "GUST" in raw:
        out["GUST"] = round(raw["GUST"], 3)
    if "SWDDIR2" in raw and "SWDDIF2" in raw:
        ghi = raw["SWDDIR2"] + raw["SWDDIF2"]          # GHI = 직달수평 + 산란
        out["SOLAR_RAD"] = round(ghi * 0.0036, 4)       # W/m^2 -> MJ/m^2/h (현행식)
        out["RAD_DIRECT"] = round(raw["SWDDIR2"] * 0.0036, 4)
        out["RAD_DIFFUSE"] = round(raw["SWDDIF2"] * 0.0036, 4)
    if "RAINC" in raw:
        out["RAIN_CONV"] = round(raw["RAINC"], 4)       # mm 누적 (kg/m^2 동치)
    if "RAINNC" in raw:
        out["RAIN_STRAT"] = round(raw["RAINNC"], 4)
    if "ACSWDNB" in raw:
        out["SOLAR_ACC"] = round(raw["ACSWDNB"], 4)     # 누적 총일사 MJ/m^2 (실측=시간누적과 동일 성질)
    if "MCAPE" in raw:
        out["CAPE"] = raw["MCAPE"]                      # 피벗에서 r4 (제주 KIMR 관례)
    if "MCIN" in raw:
        out["CINN"] = raw["MCIN"]
    if "PBLH" in raw:
        out["HPBL"] = raw["PBLH"]
    if "MSLP" in raw:
        out["PRESS_MSL"] = round(raw["MSLP"] / 100.0, 2)   # Pa -> hPa
    return out


# ── hf 그리드 ────────────────────────────────────────────────────────────────
def hf_range_1h(base_utc: datetime, days: int, max_hf_map: dict[int, int]) -> list[int]:
    """day-aligned KST 윈도우 [D+1 00시, D+days 24시) 를 1h hf 리스트로.

    발표시각별 모델 리드 상한(max_hf_map)으로 절단 -- --utc 6/18 이면 자동 축소.
    (_common.collection_window 와 동일한 day-aligned 산식을 자체 보유:
     FORECAST_DAYS 글로벌에 의존하지 않기 위함.)
    """
    base_kst = base_utc.astimezone(KST)
    start_kst = (base_kst + timedelta(days=1)).replace(
        hour=0, minute=0, second=0, microsecond=0)
    end_kst = start_kst + timedelta(days=days)
    start_hf = int((start_kst - base_kst).total_seconds() // 3600)
    end_hf = int((end_kst - base_kst).total_seconds() // 3600)   # exclusive
    cap = max_hf_map[base_utc.hour]
    return [hf for hf in range(max(start_hf, 1), end_hf) if hf <= cap]


# ── long 수집 (지점 순차 x hf 병렬 -- 현행 fetch_kimg_land_long 패턴) ────────
def fetch_model_long(
    points: list[dict], group: str, nwp: str, name_param: str,
    base_utc: datetime, days: int, max_hf_map: dict[int, int],
    rain_anchor: bool = False, workers: int = MAX_WORKERS,
    anchor_name: str = R030_NAME_DIFF_ANCHOR,
) -> pd.DataFrame:
    """(base x 지점 x hf) -> long DF [base_datetime, point_name, fcst_datetime,
    category, fcst_value] -- cl.kimg_land_long_to_wide 가 요구하는 스키마 그대로.

    rain_anchor=True 면 윈도우 시작 직전 hf 를 누적변수(anchor_name)만으로 1콜 추가 --
    누적->diff 변환의 기준점 (diff 후 첫 행 NaN 으로 자연 소거).  anchor_name 으로
    앵커 변수 집합을 지정(육지=강수+ACSWDNB, 제주 일사=ACSWDNB 만).
    """
    ckg.warmup()
    hf_list = hf_range_1h(base_utc, days, max_hf_map)
    if not hf_list:
        return pd.DataFrame(columns=[
            "base_datetime", "point_name", "fcst_datetime", "category", "fcst_value"])
    base_kst = base_utc.astimezone(KST)
    base_dt_str = base_kst.strftime("%Y-%m-%d %H:%M")
    base_label = base_utc.strftime("%Y%m%d%H") + " UTC"

    tasks: list[tuple[int, str]] = [(hf, name_param) for hf in hf_list]
    if rain_anchor:
        tasks.insert(0, (hf_list[0] - 1, anchor_name))

    rows: list[tuple] = []
    for pt in points:
        t0 = time.time()
        failed = empty = n_kept = 0
        with ThreadPoolExecutor(max_workers=workers) as ex:
            fut_to_hf = {
                ex.submit(fetch_pt_std, group, nwp, name, base_utc, hf,
                          pt["lat"], pt["lon"], pt.get("x"), pt.get("y")): hf
                for hf, name in tasks
            }
            for fut in as_completed(fut_to_hf):
                hf = fut_to_hf[fut]
                body = fut.result()
                if body is None:
                    failed += 1
                    continue
                raw = parse_pt_std(body)
                if not raw:
                    empty += 1
                    continue
                cats = derive_r030_categories(raw)
                fcst_dt_str = (base_kst + timedelta(hours=hf)).strftime("%Y-%m-%d %H:%M")
                for cat, val in cats.items():
                    rows.append((base_dt_str, pt["name"], fcst_dt_str, cat, float(val)))
                    n_kept += 1
        print(f"  {nwp} {base_label} {pt['name']:<22} hfs={len(tasks):3d} "
              f"kept_rows={n_kept:5d} failed={failed:3d} empty={empty:3d} "
              f"({time.time() - t0:.1f}s)")
    if not rows:
        return pd.DataFrame(columns=[
            "base_datetime", "point_name", "fcst_datetime", "category", "fcst_value"])
    df = pd.DataFrame(rows, columns=[
        "base_datetime", "point_name", "fcst_datetime", "category", "fcst_value"])
    df["fcst_value"] = pd.to_numeric(df["fcst_value"], errors="coerce")
    return df


# ── long -> wide 피벗 (cl.kimg_land_long_to_wide 의 파라미터화 사본) ─────────
# 원본(collect_data_land.py:191-273)은 POINT_SUFFIX 5지점 dict 가 하드코딩이라
# 지점 확장이 안 된다.  수식·반올림을 자구 그대로 옮기고 suffix 맵만 주입 --
# 동일성은 스모크 테스트(아래 __main__)가 원본과 출력 비교로 기계 검증한다.
_SCALAR_CATS = {
    "SOLAR_RAD":    "radiation",
    "TCLD":         "total_cloud",
    "MIDLOW_CLOUD": "midlow_cloud",
    "TEMP_C":       "temp",
    "TEMP_SKIN":    "temp_skin",
}
_RAIN_CATS = ("RAIN_CONV", "RAIN_STRAT")
# v2 확장 카테고리 -> 컬럼 prefix (제주 KIMR 관례 r4).
_EXT_R4_CATS = {"CAPE": "cape", "CINN": "cinn", "HPBL": "hpbl",
                "TCOG": "tcog", "TCOH": "tcoh",
                "CLOUD_TOTAL_R030": "total_cloud_r030",
                "CLOUD_MIDLOW_R030": "midlow_cloud_r030"}
_EXT_RAD_CATS = {"RAD_DIRECT": "radiation_direct", "RAD_DIFFUSE": "radiation_diffuse",
                 "RAD_TOA": "radiation_toa"}
# 파생 시 이미 반올림 완료 -- 피벗은 그대로 통과 (mslp: hPa r2)
_EXT_PASS_CATS = {"PRESS_MSL": "mslp"}


def long_to_wide_v2(df: pd.DataFrame, suffix_map: dict[str, str],
                    radiation_round: int | None = None) -> pd.DataFrame:
    """long -> wide.  기존 컬럼 수식은 cl.kimg_land_long_to_wide 와 동일,
    + 확장 카테고리(cape/cinn/hpbl r4, radiation_direct/diffuse).

    suffix_map       : {point_name: 컬럼 접미사} -- 지점 확장 SSOT 주입.
    radiation_round  : 제주 관례(r2) 적용 시 2.  None 이면 육지 관례(r4 유지).
    """
    if df.empty:
        return pd.DataFrame()
    df = df.copy()
    df["fcst_value"] = pd.to_numeric(df["fcst_value"], errors="coerce")

    parts: list[pd.DataFrame] = []
    for point, suffix in suffix_map.items():
        sub = df[df["point_name"] == point]
        if sub.empty:
            print(f"  [WARN] no rows for {point} -- skipped")
            continue

        # 1) 비누적: (fcst_datetime, category) 별 freshest -> pivot.
        non_rain = sub[~sub["category"].isin(_RAIN_CATS + ("SOLAR_ACC",))]
        non_rain = freshest(non_rain, ["fcst_datetime", "category"])
        piv = non_rain.pivot(index="fcst_datetime", columns="category",
                             values="fcst_value")
        out = pd.DataFrame(index=piv.index)
        for cat, prefix in _SCALAR_CATS.items():
            if cat in piv:
                col = piv[cat]
                out[f"{prefix}_{suffix}"] = (
                    col.round(2) if cat in ("TEMP_C", "TEMP_SKIN") else col)
        if "REH" in piv:
            out[f"reh_{suffix}"] = piv["REH"].round(2)
        for height in ("10m", "80m"):
            u_col = f"WIND_U_{height.upper()}"
            v_col = f"WIND_V_{height.upper()}"
            if u_col in piv and v_col in piv:
                u, v = piv[u_col], piv[v_col]
                spd = np.sqrt(u**2 + v**2)
                wdir = (270 - np.degrees(np.arctan2(v, u))) % 360
                out[f"wind_spd_{height}_{suffix}"] = spd.round(2)
                out[f"wd_sin_{height}_{suffix}"]   = np.sin(np.radians(wdir)).round(4)
                out[f"wd_cos_{height}_{suffix}"]   = np.cos(np.radians(wdir)).round(4)
        if "GUST" in piv:
            out[f"gust_{suffix}"] = piv["GUST"].round(4)
        # 확장: cape/cinn/hpbl (제주 KIMR 관례 = raw round 4)
        for cat, prefix in _EXT_R4_CATS.items():
            if cat in piv:
                out[f"{prefix}_{suffix}"] = piv[cat].round(4)
        # 확장: 파생 단계에서 반올림 끝난 카테고리 (mslp hPa r2 등)
        for cat, prefix in _EXT_PASS_CATS.items():
            if cat in piv:
                out[f"{prefix}_{suffix}"] = piv[cat]
        # 확장: 일사 직달/산란 (derive 에서 r4 완료; 제주 관례면 r2 재적용)
        for cat, prefix in _EXT_RAD_CATS.items():
            if cat in piv:
                col = piv[cat]
                out[f"{prefix}_{suffix}"] = (
                    col.round(radiation_round) if radiation_round else col)
        if radiation_round and f"radiation_{suffix}" in out:
            out[f"radiation_{suffix}"] = out[f"radiation_{suffix}"].round(radiation_round)

        # 2) 강수: per-base 누적(conv+strat) -> diff -> clip(0) -> freshest.
        rain = sub[sub["category"].isin(_RAIN_CATS)]
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
            rain_s = acc.set_index("fcst_datetime")["hourly"].rename(f"rainfall_{suffix}")
            out = out.join(rain_s, how="outer")

        # 2b) ACSWDNB(누적 총일사) -> per-base diff -> clip(0) -> radiation_acswdnb.
        #     실측(기상청 시간누적 일사)과 단위·정의가 동일 -- 순시 SWDDIR2+SWDDIF2 대비
        #     한낮 과대편향이 작다(EDA new_kma/REPORT_05 §5-보강).  사용은 +보정 예정.
        sw = sub[sub["category"] == "SOLAR_ACC"]
        if not sw.empty:
            swacc = (
                sw.groupby(["base_datetime", "fcst_datetime"], as_index=False)["fcst_value"]
                  .sum()
                  .rename(columns={"fcst_value": "acc"})
                  .sort_values(["base_datetime", "fcst_datetime"])
            )
            swacc["hourly"] = (
                swacc.groupby("base_datetime")["acc"].diff().clip(lower=0)
                     .round(radiation_round if radiation_round else 4)
            )
            swacc = swacc.dropna(subset=["hourly"])
            swacc = freshest(swacc, ["fcst_datetime"])
            sw_s = swacc.set_index("fcst_datetime")["hourly"].rename(f"radiation_acswdnb_{suffix}")
            out = out.join(sw_s, how="outer")

        if out.empty:
            print(f"  [WARN] {point} produced no rows -- skipped")
            continue
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


# ── 제주 met: GRIB 시계열 1콜/지점 (2026-07-05 최종 -- NC per-hf 는 서버 혼잡 시
# 취약함이 실측됨: 혼잡 밤 시간대 base 1개에 40분+.  GRIB 은 지점당 1콜이라 면역).
# 운영 X/Y 고정(바다 셀 회피)·cape/cinn/tcog/tcoh 연속성 복원(grib varn 그대로).
# 일사(SWDDIR2류)는 GRIB 파일에 없어 NC per-hf(2변수, 경량)를 유지한다.
KIMR_GRIB_VARN = "0,17,1001,2002,2003,2022,7006,7007,3018,1074,1072,1010,1009,3000"
_KIMR_GRIB_CAT = {
    (0, 2):     ("TEMP_C",      lambda v: round(v - 273.15, 2)),
    (17, 0):    ("TEMP_SKIN",   lambda v: round(v - 273.15, 2)),
    (1001, 2):  ("REH",         lambda v: round(v, 2)),
    (2002, 10): ("WIND_U_10M",  lambda v: round(v, 3)),
    (2003, 10): ("WIND_V_10M",  lambda v: round(v, 3)),
    (2002, 80): ("WIND_U_80M",  lambda v: round(v, 3)),
    (2003, 80): ("WIND_V_80M",  lambda v: round(v, 3)),
    (2022, 0):  ("GUST",        lambda v: round(v, 3)),
    (7006, 0):  ("CAPE",        lambda v: v),
    (7007, 0):  ("CINN",        lambda v: v),
    (3018, 0):  ("HPBL",        lambda v: v),
    (1074, 0):  ("TCOG",        lambda v: v),
    (1072, 0):  ("TCOH",        lambda v: v),
    (1010, 0):  ("RAIN_CONV",   lambda v: round(v, 4)),
    (1009, 0):  ("RAIN_STRAT",  lambda v: round(v, 4)),
    (3000, 0):  ("PRESS_MSL",   lambda v: round(v / 100.0, 2)),   # pslp Pa -> hPa
}


def fetch_kimr_grib_long(points: list[dict], base_utc: datetime, days: int,
                         max_hf_map: dict[int, int]) -> pd.DataFrame:
    """제주 met 를 GRIB 시계열(ef 범위) 1콜/지점으로 -> long DF.

    운영 X/Y(바다 셀 회피) 고정.  행 'TMFC TMEF VARN LEVEL VALUS'(TMEF=UTC).
    강수 diff 기준점을 위해 ef start-1 부터.  실패/빈 지점은 호출자가 판단
    (빈 long 이면 cdjn 폴백)."""
    hf_list = hf_range_1h(base_utc, days, max_hf_map)
    if not hf_list:
        return pd.DataFrame(columns=[
            "base_datetime", "point_name", "fcst_datetime", "category", "fcst_value"])
    ef = f"{hf_list[0] - 1},{hf_list[-1]},1"
    base_kst = base_utc.astimezone(KST)
    base_dt_str = base_kst.strftime("%Y-%m-%d %H:%M")
    base_label = base_utc.strftime("%Y%m%d%H") + " UTC"

    rows: list[tuple] = []
    for pt in points:
        t0 = time.time()
        p = {"group": "KIMR", "nwp": "r030", "data": "U", "varn": KIMR_GRIB_VARN,
             "tmfc": base_utc.strftime("%Y%m%d%H"), "ef": ef}
        if pt.get("x") is not None:
            p["X"], p["Y"] = str(pt["x"]), str(pt["y"])
        else:
            p["lat"], p["lon"] = f"{pt['lat']:.4f}", f"{pt['lon']:.4f}"
        body = _fetch_grib(p)
        n_kept = 0
        for ln in (body or "").splitlines():
            s = ln.strip()
            if not s or s.startswith("#") or s.startswith("{"):
                continue
            q = s.split()
            if len(q) < 5:
                continue
            try:
                varn, level, val = int(q[2]), int(q[3]), float(q[4])
                tmef = datetime.strptime(q[1], "%Y%m%d%H").replace(tzinfo=UTC)
            except ValueError:
                continue
            hit = _KIMR_GRIB_CAT.get((varn, level))
            if hit is None:
                continue
            cat, fn = hit
            fcst_dt_str = tmef.astimezone(KST).strftime("%Y-%m-%d %H:%M")
            rows.append((base_dt_str, pt["name"], fcst_dt_str, cat, float(fn(val))))
            n_kept += 1
        print(f"  KIMR-grib {base_label} {pt['name']:<22} 1콜 "
              f"kept_rows={n_kept:5d} ({time.time() - t0:.1f}s)")
    df = pd.DataFrame(rows, columns=[
        "base_datetime", "point_name", "fcst_datetime", "category", "fcst_value"])
    if not df.empty:
        df["fcst_value"] = pd.to_numeric(df["fcst_value"], errors="coerce")
    return df


# ── R030 등압면 frcc -> 1h 운량 (신규 컬럼 전용 -- 기존 total/midlow_cloud 불변) ──
# 지역·국지 단일면엔 운량이 없지만 등압면 frcc(Fraction of Cloud Cover, varn 6032,
# 24레벨)로 결합 운량을 만들 수 있다 (new_kma nb05 검증: max-random 오버랩이 자체
# 일사 투과율과 정합).  GRIB 시계열이라 지점당 2콜(96시각/콜 한계)로 D+1~5 전체 커버.
# 서빙은 기존 NE57 운량을 계속 쓰고, 이 컬럼들은 EDA(G-9)·재훈련 대비 아카이브다.
URL_GRIB = "https://apihub.kma.go.kr/api/typ06/url/kim_grib_pt_tmfc.php"
# 등압면 운량의 이름은 경로마다 다르다: GRIB=varn 6032(공식명 frcc) / NC(std)=CLDFRA.
# 같은 필드임은 값 대조로 검증(nb05: NC 결합 0.978 == GRIB 결합 0.978).
# 이 모듈은 GRIB 경로라 숫자 코드로 요청한다 -- "frcc" 문자열을 API 에 보내지 않는다.
FRCC_VARN = "6032"
_GRIB_EF_CHUNK = 96          # data=P ef 범위 1콜 상한 (실측 2026-07-04)


def _fetch_grib(params: dict, timeout: int = 180) -> str | None:
    """구 grib 엔드포인트 GET (kim2 키 풀·백오프)."""
    attempt = 0
    while attempt < RETRY_MAX:
        key = _k2_current()
        if key is None:
            return None
        params["authKey"] = key
        try:
            r = _kma_session.get(URL_GRIB, params=params, timeout=timeout)
            if r.status_code == 403 or kma_quota_exceeded(r.status_code, r.text):
                if _k2_rotate(key, "grib 한도/권한"):
                    continue
                return None
            if r.status_code == 200:
                return r.text
            if 500 <= r.status_code < 600 and attempt < RETRY_MAX - 1:
                attempt += 1
                time.sleep(2 ** attempt)
                continue
            return None
        except requests.RequestException:
            if attempt < RETRY_MAX - 1:
                attempt += 1
                time.sleep(2 ** attempt)
                continue
            return None
    return None


def _frcc_combine(levels: dict[int, float]) -> tuple[float, float]:
    """{hPa: cloud fraction} -> (total, midlow).

    total  = max-random 오버랩: 붙어 있는 구름층(연속 레벨)은 한 덩어리(최대값),
             떨어진 덩어리끼리 랜덤 결합 -- nb05 채택식.
    midlow = low + mid(1-low), low=max(>=800hPa)/mid=max(450~799hPa)
             -- 기존 midlow_cloud(lcld+mcld(1-lcld)) 결합식과 동일 철학.
    """
    cs = [levels[p] for p in sorted(levels, reverse=True)]   # 지면(1000)→상공(50)
    blocks: list[float] = []
    cur = 0.0
    for c in cs:
        if c > 0.01:
            cur = max(cur, c)
        elif cur > 0:
            blocks.append(cur)
            cur = 0.0
    if cur > 0:
        blocks.append(cur)
    total = 1.0
    for bk in blocks:
        total *= (1 - bk)
    total = 1 - total
    low = max((v for p, v in levels.items() if p >= 800), default=0.0)
    mid = max((v for p, v in levels.items() if 450 <= p < 800), default=0.0)
    return round(total, 4), round(low + mid * (1 - low), 4)


def fetch_r030_frcc_long(points: list[dict], base_utc: datetime, days: int,
                         max_hf_map: dict[int, int]) -> pd.DataFrame:
    """R030 등압면 frcc(24레벨) -> 결합 운량 long (지점당 2콜, GRIB 시계열).

    카테고리: CLOUD_TOTAL_R030 / CLOUD_MIDLOW_R030 -> 신규 컬럼
    total_cloud_r030_<sfx> / midlow_cloud_r030_<sfx>.  실패 지점은 조용히
    건너뜀 (아카이브 컬럼 -- 완결성 sentinel 에 넣지 않는다).
    """
    hf_list = hf_range_1h(base_utc, days, max_hf_map)
    if not hf_list:
        return pd.DataFrame(columns=[
            "base_datetime", "point_name", "fcst_datetime", "category", "fcst_value"])
    chunks: list[tuple[int, int]] = []
    lo = hf_list[0]
    while lo <= hf_list[-1]:
        hi = min(lo + _GRIB_EF_CHUNK - 1, hf_list[-1])
        chunks.append((lo, hi))
        lo = hi + 1
    base_kst = base_utc.astimezone(KST)
    base_dt_str = base_kst.strftime("%Y-%m-%d %H:%M")
    base_label = base_utc.strftime("%Y%m%d%H") + " UTC"

    rows: list[tuple] = []
    for pt in points:
        t0 = time.time()
        prof: dict[str, dict[int, float]] = {}   # tmef -> {hPa: frcc}
        n_call = 0
        for lo, hi in chunks:
            p = {"group": "KIMR", "nwp": "r030", "data": "P", "varn": FRCC_VARN,
                 "tmfc": base_utc.strftime("%Y%m%d%H"), "ef": f"{lo},{hi},1"}
            if pt.get("x") is not None:      # 제주: 운영 셀 고정 (R030 격자 x/y)
                p["X"], p["Y"] = str(pt["x"]), str(pt["y"])
            else:
                p["lat"], p["lon"] = f"{pt['lat']:.4f}", f"{pt['lon']:.4f}"
            body = _fetch_grib(p)
            n_call += 1
            for ln in (body or "").splitlines():
                s = ln.strip()
                if not s or s.startswith("#") or s.startswith("{"):
                    continue
                p = s.split()
                if len(p) < 5:
                    continue
                try:
                    prof.setdefault(p[1], {})[int(p[3])] = float(p[4])
                except ValueError:
                    continue
        n_kept = 0
        for tmef, levels in prof.items():
            if len(levels) < 12:      # 반쪽 프로파일은 결합하지 않음
                continue
            try:
                tmef_utc = datetime.strptime(tmef, "%Y%m%d%H").replace(tzinfo=UTC)
            except ValueError:
                continue
            total, midlow = _frcc_combine(levels)
            fcst_dt_str = tmef_utc.astimezone(KST).strftime("%Y-%m-%d %H:%M")
            rows.append((base_dt_str, pt["name"], fcst_dt_str,
                         "CLOUD_TOTAL_R030", total))
            rows.append((base_dt_str, pt["name"], fcst_dt_str,
                         "CLOUD_MIDLOW_R030", midlow))
            n_kept += 1
        print(f"  R030-frcc {base_label} {pt['name']:<22} {n_call}콜 "
              f"시각 {n_kept}/{len(hf_list)} ({time.time() - t0:.1f}s)")
    df = pd.DataFrame(rows, columns=[
        "base_datetime", "point_name", "fcst_datetime", "category", "fcst_value"])
    if not df.empty:
        df["fcst_value"] = pd.to_numeric(df["fcst_value"], errors="coerce")
    return df


# ── NE57: pt_txt2_std per-hf ─────────────────────────────────────────────────
# 실측(2026-07-04): NE57 콜은 어느 엔드포인트든 벽시계 ~2.7s/콜(서버가 339MB 전구
# 파일을 여는 비용이 지배) -- 속도는 동시성으로만 개선된다.  workers=12 실측
# 2배(41.6->21.1s/지점), 실패 0.  (KIMR 시계열 grib 는 KIMG 미지원 -- 사용자 확인.)
# psl=해면기압(기압 경향), dswrtoa=대기상단 일사(청명도 Kt=dswrsfc/dswrtoa 파생용)
# -- 2026-07-05 사용자 승인 신규 아카이브 변수
NE57_NAME = ("dswrsfc,t2m,tcld,mcld,lcld,u10m,v10m,rh2m,"
             "rainc_acc,rainl_acc,u80m,v80m,gust,psl,dswrtoa")
NE57_WORKERS = 12
# 요청 상한 vs 가용 상한 분리 (2026-07-05 사용자 지시: "가능한 날까지 전부 받는다")
# - FETCH: 372h(D+15.5, 구모델 상한)까지 매번 요청 -- KMA 가 지평을 되살리면 그날부터
#   자동으로 D+13~15 데이터가 흘러들어온다 (현재는 288h 초과 = 빈 응답 ~28콜/지점/신규 base).
# - AVAIL: 완결성 판정 기준 = 실측 상한 288h -- 기대치를 여기 두어야 "영원히 불완전 ->
#   매 cron 재수집" churn 이 없다.  지평 확장이 감지되면(D+13+ 행 등장) 이 값을 올린다.
NE57_FETCH_HF = 372
NE57_AVAIL_HF = 288


def derive_ne57_categories(raw: dict[str, float]) -> dict[str, float]:
    """_common.derive_categories 의 이름 기반 미러 (varn 코드 대신 NAME 파싱).
    수식·반올림 완전 동일 -- 저장 규약 보존."""
    out: dict[str, float] = {}
    if "dswrsfc" in raw:
        out["SOLAR_RAD"] = round(raw["dswrsfc"] * 0.0036, 4)
    if "t2m" in raw:
        out["TEMP_C"] = round(raw["t2m"] - 273.15, 2)
    if "tcld" in raw:
        out["TCLD"] = round(raw["tcld"], 4)
    if "lcld" in raw and "mcld" in raw:
        out["MIDLOW_CLOUD"] = round(raw["lcld"] + raw["mcld"] * (1 - raw["lcld"]), 4)
    for src, cat in (("u10m", "WIND_U_10M"), ("v10m", "WIND_V_10M"),
                     ("u80m", "WIND_U_80M"), ("v80m", "WIND_V_80M")):
        if src in raw:
            out[cat] = round(raw[src], 3)
    if "gust" in raw:
        out["GUST"] = round(raw["gust"], 3)
    if "rh2m" in raw:
        out["REH"] = round(raw["rh2m"], 2)
    if "rainc_acc" in raw:
        out["RAIN_CONV"] = round(raw["rainc_acc"], 4)
    if "rainl_acc" in raw:
        out["RAIN_STRAT"] = round(raw["rainl_acc"], 4)
    if "psl" in raw:
        out["PRESS_MSL"] = round(raw["psl"] / 100.0, 2)     # Pa -> hPa
    if "dswrtoa" in raw:
        out["RAD_TOA"] = round(raw["dswrtoa"] * 0.0036, 4)  # 청명도 Kt 분모
    return out


def hf_range_3h(base_utc: datetime, days: int, max_hf: int = 288) -> list[int]:
    """NE57 3h 그리드: day-aligned 윈도우 안의 3의 배수 hf (상한 max_hf)."""
    base_kst = base_utc.astimezone(KST)
    start_kst = (base_kst + timedelta(days=1)).replace(
        hour=0, minute=0, second=0, microsecond=0)
    end_kst = start_kst + timedelta(days=days)
    start_hf = int((start_kst - base_kst).total_seconds() // 3600)
    end_hf = int((end_kst - base_kst).total_seconds() // 3600)
    return [hf for hf in range(max(start_hf, 1), end_hf)
            if hf % 3 == 0 and hf <= max_hf]


def fetch_ne57_std_long(points: list[dict], base_utc: datetime, days: int,
                        workers: int = NE57_WORKERS,
                        max_hf: int = NE57_FETCH_HF) -> pd.DataFrame:
    """NE57(전구 3h)을 pt_txt2_std 멀티변수 per-hf 로 -> long DF.

    같은 파일(g576 etc)을 구 typ01 pt 와 동일 값으로 읽음(교차검증 완료) +
    콜당 응답이 훨씬 빨라 백필 병목(구 pt ~2.7s/콜)을 푼다.
    강수 anchor = 윈도우 시작 직전 3h 스텝 1콜.
    """
    ckg.warmup()
    hf_list = hf_range_3h(base_utc, days, max_hf)
    if not hf_list:
        return pd.DataFrame(columns=[
            "base_datetime", "point_name", "fcst_datetime", "category", "fcst_value"])
    base_kst = base_utc.astimezone(KST)
    base_dt_str = base_kst.strftime("%Y-%m-%d %H:%M")
    base_label = base_utc.strftime("%Y%m%d%H") + " UTC"

    tasks: list[tuple[int, str]] = [(hf, NE57_NAME) for hf in hf_list]
    anchor = hf_list[0] - 3
    if anchor >= 1:
        tasks.insert(0, (anchor, "rainc_acc,rainl_acc"))

    rows: list[tuple] = []
    for pt in points:
        t0 = time.time()
        failed = empty = n_kept = 0
        with ThreadPoolExecutor(max_workers=workers) as ex:
            fut_to_hf = {
                ex.submit(fetch_pt_std, "KIMG", "NE57", name, base_utc, hf,
                          pt["lat"], pt["lon"]): hf
                for hf, name in tasks
            }
            for fut in as_completed(fut_to_hf):
                hf = fut_to_hf[fut]
                body = fut.result()
                if body is None:
                    failed += 1
                    continue
                raw = parse_pt_std(body)
                if not raw:
                    empty += 1
                    continue
                cats = derive_ne57_categories(raw)
                fcst_dt_str = (base_kst + timedelta(hours=hf)).strftime("%Y-%m-%d %H:%M")
                for cat, val in cats.items():
                    rows.append((base_dt_str, pt["name"], fcst_dt_str, cat, float(val)))
                    n_kept += 1
        print(f"  NE57-std {base_label} {pt['name']:<22} hfs={len(tasks):3d} "
              f"kept_rows={n_kept:5d} failed={failed:3d} empty={empty:3d} "
              f"({time.time() - t0:.1f}s)")
    df = pd.DataFrame(rows, columns=[
        "base_datetime", "point_name", "fcst_datetime", "category", "fcst_value"])
    if not df.empty:
        df["fcst_value"] = pd.to_numeric(df["fcst_value"], errors="coerce")
    return df


# ── 전역 knob contextmanager (확립된 패턴: forecast_days_override 와 동류) ────
@contextmanager
def ne57_3h_only():
    """NE57(전구)이 07-01부터 3h 파일만 생산하므로, 현행 빌더의 1h 구간 호출
    (hf<=135 매시간 -- 지금은 전부 빈 응답)을 제거한다.
    _common.KIMG_HOURLY_MAX_HF 를 0 으로 내리면 collection_hf_range 가 3의 배수만
    산출한다 (base당 빈 호출 ~450개 절약)."""
    old = ckg.KIMG_HOURLY_MAX_HF
    ckg.KIMG_HOURLY_MAX_HF = 0
    try:
        yield
    finally:
        ckg.KIMG_HOURLY_MAX_HF = old


@contextmanager
def land_points_override(points: list[dict] | None):
    """NE57 part(cdln.build_forecast_wide)의 대상 지점을 임시로 좁힌다 --
    지점 단위 부분 백필(--points)용.  None 이면 no-op."""
    if points is None:
        yield
        return
    old = ckl.POINTS
    ckl.POINTS = [{"name": p["name"], "lat": p["lat"], "lon": p["lon"]} for p in points]
    try:
        yield
    finally:
        ckl.POINTS = old


# ── 스모크 테스트 ────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    import collect_data_land as cl

    # 1) 실호출 스모크: R030/L010 각 1지점 1hf -- 파싱·GHI 검산
    base = ckg.latest_published_base(datetime.now(KST)).replace(hour=12)
    if base > datetime.now(UTC) - timedelta(hours=3):
        base -= timedelta(days=1)
    print(f"[smoke] base = {base}")
    for grp, nwp, nm in (("KIMR", "R030", R030_NAME_LAND), ("KIML", "L010", L010_NAME)):
        body = fetch_pt_std(grp, nwp, nm, base, 18,
                            POINTS_JEJU_V2[2]["lat"], POINTS_JEJU_V2[2]["lon"])
        raw = parse_pt_std(body or "")
        cats = derive_r030_categories(raw)
        missing = [v for v in nm.split(",") if v not in raw]
        print(f"[smoke] {nwp}: raw {len(raw)}/{len(nm.split(','))} vars"
              f"{' (누락: ' + ','.join(missing) + ')' if missing else ''}, "
              f"cats={sorted(cats)}")
        assert not missing, f"{nwp} 변수 누락: {missing}"
        assert abs(cats["SOLAR_RAD"] - (cats["RAD_DIRECT"] + cats["RAD_DIFFUSE"])) < 2e-4, \
            "GHI != DIR + DIF"
    print("[smoke] 실호출 파싱·GHI 검산 OK")

    # 2) 피벗 동일성: 합성 long 을 원본(cl.kimg_land_long_to_wide)과 v2 피벗에
    #    통과시켜 공유 컬럼 완전 일치 확인 (2 base x 3 hf x 5지점, 강수 diff 포함)
    rng = np.random.default_rng(42)
    cats_shared = ["SOLAR_RAD", "TCLD", "MIDLOW_CLOUD", "TEMP_C", "REH",
                   "WIND_U_10M", "WIND_V_10M", "WIND_U_80M", "WIND_V_80M",
                   "GUST", "RAIN_CONV", "RAIN_STRAT"]
    rows = []
    for b in ("2026-07-01 21:00", "2026-07-02 21:00"):
        for pt in cl.POINT_SUFFIX:
            for k in range(4):
                fcst = (pd.Timestamp("2026-07-03 00:00")
                        + pd.Timedelta(hours=k)).strftime("%Y-%m-%d %H:%M")
                for cat in cats_shared:
                    rows.append((b, pt, fcst, cat, float(rng.uniform(0, 10))))
    syn = pd.DataFrame(rows, columns=["base_datetime", "point_name",
                                      "fcst_datetime", "category", "fcst_value"])
    w_orig = cl.kimg_land_long_to_wide(syn)
    w_v2 = long_to_wide_v2(syn, cl.POINT_SUFFIX)
    pd.testing.assert_frame_equal(
        w_orig.sort_index(axis=1), w_v2[w_orig.columns].sort_index(axis=1))
    print(f"[smoke] 피벗 동일성 OK ({w_orig.shape[0]}행 x {w_orig.shape[1]}컬럼 완전 일치)")

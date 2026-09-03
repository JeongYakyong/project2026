# -*- coding: utf-8 -*-
"""기상개황 — 8권역 단색(초록) 지도, Leaflet HTML 임베드.

- 표시 모드(신재생 강도/일사/풍속)와 발전원 토글은 HTML 내부 JS — 실데이터는 렌더 시 주입.
- 기준 시간 = 09–15시 평균(일사·기온·풍속·강수·운량). 별도 시각 선택 없음.
- 면 색(초록 진하기): 신재생 강도(설비용량×활성도) / 일사 비율 / 풍속.
- 제주 = jeju DB 실데이터(고산 west) — 육지 보간으로 대체하지 않는다(확정 규칙).
"""
from pathlib import Path
import json

import pandas as pd
import streamlit as st

import common as C

ROOT = Path(__file__).resolve().parent.parent
_GEO_CANDIDATES = [ROOT / "9. design" / "skorea_provinces_simplified.json",
                   ROOT / "9. design" / "old design" / "skorea_provinces_simplified.json"]
GEOJSON = next((p for p in _GEO_CANDIDATES if p.exists()), _GEO_CANDIDATES[0])

# 17 시도 → 8 권역
SIDO2ZONE = {
    "서울특별시": "수도권", "경기도": "수도권", "인천광역시": "수도권",
    "대전광역시": "충청권", "세종특별자치시": "충청권", "충청남도": "충청권", "충청북도": "충청권",
    "광주광역시": "광주·전남", "전라남도": "광주·전남",
    "전라북도": "전북",
    "부산광역시": "경남권", "울산광역시": "경남권", "경상남도": "경남권",
    "대구광역시": "경북권", "경상북도": "경북권",
    "강원도": "강원", "제주특별자치도": "제주",
}

# 8 권역 — 구성·기상 지점·설비용량(MW, 2026.04 전국총량 × 2024 지역비율)·라벨 좌표
ZONES = {
    "광주·전남": dict(mem="광주·전남", db="land", stn="yeonggwang", stname="영광",
                   solar=7160, wind=616, lat=34.95, lon=126.85),
    "충청권":   dict(mem="대전·세종·충남·충북", db="land", stn="seosan", stname="서산",
                   solar=6425, wind=3, lat=36.55, lon=127.05),
    "전북":     dict(mem="전북", db="land", stn="yeonggwang", stname="영광",
                   solar=5037, wind=111, lat=35.72, lon=127.10),
    "경북권":   dict(mem="대구·경북", db="land", stn="pohang", stname="포항",
                   solar=4828, wind=782, lat=36.20, lon=128.70),
    "수도권":   dict(mem="서울·경기·인천", db="land", stn="wonju", stname="원주",
                   solar=3315, wind=73, lat=37.40, lon=126.95),
    "경남권":   dict(mem="부산·울산·경남", db="land", stn="pohang", stname="포항",
                   solar=3058, wind=139, lat=35.30, lon=128.30),
    "강원":     dict(mem="강원", db="land", stn="daegwallyeong", stname="대관령",
                   solar=2228, wind=771, lat=37.70, lon=128.30),
    "제주":     dict(mem="제주", db="jeju", stn="west", stname="고산",
                   solar=735, wind=571, lat=33.40, lon=126.53),
}

HOURS = ("09:00:00", "15:00:00")   # 기준 시간대 — 09–15시 평균(별도 시각 선택 없음)

# ---- 활성도 BIN — 실측 역산으로 교정된 확정값(수치 변경 금지) ----------------
# 활성도 % = 기대 전국 이용률(과거 실측 기상↔이용률 관계로 교정) — 이용률 예측과 같은 단위.
# 전국 기준 교정을 권역 단일 지점에 적용 → 권역 간 상대 신호로만 쓴다.
SOLAR_BINS = [(0.80, 61, "매우 좋음"), (0.60, 49, "좋음"), (0.40, 36, "보통"),
              (0.20, 23, "낮음"), (0.00, 12, "매우 낮음")]
# 풍속 경계 = ASOS 10m 지점 스케일(허브높이 파워커브 경계 아님 — 지점 평균으로는 도달 불가).
WIND_BINS = [(0, 2, 11, "미풍"), (2, 3, 21, "약함"), (3, 4.5, 44, "양호"),
             (4.5, 6, 72, "좋음"), (6, 25, 77, "최적"), (25, 999, 0, "차단")]
SA_MAX = max(p for _, p, _ in SOLAR_BINS)     # 강도맵 기준 — 최상 bin 기대 이용률
WA_MAX = max(p for _, _, p, _ in WIND_BINS)

# 청천 일사(09–15시 평균, MJ/m²·h) — 월별 관측 P97 실측값(2022~2026 historical)
CLEARSKY_0915 = {1: 1.64, 2: 2.09, 3: 2.50, 4: 2.93, 5: 3.10, 6: 3.06,
                 7: 2.79, 8: 2.69, 9: 2.59, 10: 2.20, 11: 1.83, 12: 1.47}

# 하늘상태 4분류(맑음/약간흐림/흐림/비·눈) — 관측 분포로 경계 확정.
# DB total_cloud_*는 0~1 비율(기상청 0~10 아님), rainfall_*은 mm/h.
RAIN_MMH = 0.3            # 09–15 평균 강수 ≥ 이 값이면 강수로 판정
CLOUD_OVC, CLOUD_BKN = 0.85, 0.50   # 흐림 / 약간흐림 경계
SNOW_TEMP = 1.0           # 강수 시 기온 < 이 값이면 눈

WIND_FULL = 6.0           # 풍속 모드 정규화 상한 — 최적 bin 시작(ASOS 스케일, m/s)


def solar_act(ratio: float | None, rainy: bool) -> dict | None:
    if ratio is None or pd.isna(ratio):
        return None
    if rainy:
        return {"pct": 12, "lab": "강수"}
    for mn, pct, lab in SOLAR_BINS:
        if ratio >= mn:
            return {"pct": pct, "lab": lab}
    return {"pct": 12, "lab": "매우 낮음"}


def wind_act(ws: float | None) -> dict | None:
    if ws is None or pd.isna(ws):
        return None
    for lo, hi, pct, lab in WIND_BINS:
        if lo <= ws < hi:
            return {"pct": pct, "lab": lab}
    return {"pct": 0, "lab": "차단"}


def sky_of(cloud: float | None, rain: float | None, temp: float | None,
           ratio: float | None) -> dict:
    """하늘상태 4분류 — 강수 우선, 운량 기준. 운량 결측 시 일사 비율로 근사(폴백)."""
    rain = 0.0 if rain is None or pd.isna(rain) else rain
    if rain >= RAIN_MMH:
        if temp is not None and not pd.isna(temp) and temp < SNOW_TEMP:
            return {"emo": "🌨️", "t": "눈"}
        return {"emo": "🌧️", "t": "비"}
    if cloud is not None and not pd.isna(cloud):
        if cloud >= CLOUD_OVC:
            return {"emo": "☁️", "t": "흐림"}
        if cloud >= CLOUD_BKN:
            return {"emo": "⛅", "t": "약간흐림"}
        return {"emo": "☀️", "t": "맑음"}
    if ratio is not None and not pd.isna(ratio):    # 운량 결측(제주 일부 기간) — 일사로 근사
        if ratio >= 0.65:       # 운량<0.5 구간의 관측 일사비율(~0.7)에 맞춤
            return {"emo": "☀️", "t": "맑음"}
        if ratio >= 0.40:
            return {"emo": "⛅", "t": "약간흐림"}
        return {"emo": "☁️", "t": "흐림"}
    return {"emo": "", "t": "—"}


# ---------------------------------------------------------------- 데이터 레이어
# 테이블별 컬럼 접두사 — forecast(KIMG 예보)와 historical(ASOS·제주 관측)은 이름만 다름.
# 일사는 둘 다 MJ/m²h 스케일(청천 P97도 historical 산출) — 같은 활성도 bin 적용 가능.
_PREFIX = {
    "forecast":   {"temp": "temp_", "rad": "radiation_", "wind": "wind_spd_10m_",
                   "rain": "rainfall_", "cloud": "total_cloud_"},
    "historical": {"temp": "temp_c_", "rad": "solar_rad_", "wind": "wind_spd_",
                   "rain": "rainfall_", "cloud": "total_cloud_"},
}


def _station_means(region: str, suffixes: list[str], date: str,
                   table: str = "forecast") -> dict[str, dict]:
    """지점별 09–15시 평균 {suffix: {temp, rad, wind, rain, cloud}} — 결측 컬럼은 NaN."""
    px = _PREFIX[table]
    s, e = f"{date} {HOURS[0]}", f"{date} {HOURS[1]}"
    cols = [f"{p}{sx}" for sx in suffixes for p in px.values()]
    df = C.query(region, f"SELECT {', '.join(cols)} FROM {table} "
                         "WHERE timestamp BETWEEN ? AND ?", (s, e))
    out = {}
    for sx in suffixes:
        if df.empty:
            out[sx] = {k: float("nan") for k in px}
            continue
        m = df.mean(numeric_only=True)
        out[sx] = {k: m.get(f"{p}{sx}") for k, p in px.items()}
    return out


def _station_means_fh(region: str, suffixes: list[str], date: str) -> dict[str, dict]:
    """forecast_horizon(지평 아카이브) 09–15시 평균 — 예보 전용(전국·제주 공용).

    timestamp 당 여러 base 가 있으므로 최신 base 행만 골라 가장 새 예보를 쓴다.
    컬럼명은 forecast 와 동일(KMA 기상)이라 _PREFIX 재사용.
    """
    px = _PREFIX["forecast"]
    s, e = f"{date} {HOURS[0]}", f"{date} {HOURS[1]}"
    cols = [f"{p}{sx}" for sx in suffixes for p in px.values()]
    sel = ", ".join(f'"{c}"' for c in cols)
    df = C.query(region,
                 f"SELECT {sel} FROM forecast_horizon fh WHERE timestamp BETWEEN ? AND ? "
                 f"AND base=(SELECT MAX(base) FROM forecast_horizon WHERE timestamp=fh.timestamp)",
                 (s, e))
    out = {}
    for sx in suffixes:
        if df.empty:
            out[sx] = {k: float("nan") for k in px}
            continue
        m = df.mean(numeric_only=True)
        out[sx] = {k: m.get(f"{p}{sx}") for k, p in px.items()}
    return out


def _util_label(pct: float) -> str:
    """이용률 %를 정성 라벨로 — 제주 풍력 활성도용(고산 풍속 칸 대신, 제주 분포 기준)."""
    if pct >= 45:
        return "매우 강함"
    if pct >= 28:
        return "강함"
    if pct >= 15:
        return "보통"
    if pct >= 7:
        return "약함"
    return "미약"


@st.cache_data(ttl=C.CACHE_TTL)
def jeju_wind_util(date: str, forecast: bool) -> float | None:
    """제주 그날 풍력 이용률(%) — 고산 풍속을 육지 풍속 칸에 넣으면 과대표시(≥6m/s 49%→'최적' 77%)되어,
    제주 자체 값을 쓴다. forecast=True면 제주 예측(est_wind_util_jeju, 최신 base),
    False면 실측 CF(real_wind_gen ÷ capacity). 둘 다 그날 평균(%). 데이터 없으면 None.
    """
    s, e = f"{date} 00:00:00", f"{date} 23:00:00"
    if forecast:
        df = C.query("jeju",
                     "SELECT est_wind_util_jeju u FROM est_horizon_jeju eh "
                     "WHERE timestamp BETWEEN ? AND ? AND est_wind_util_jeju IS NOT NULL "
                     "AND base=(SELECT MAX(base) FROM est_horizon_jeju "
                     "WHERE timestamp=eh.timestamp AND est_wind_util_jeju IS NOT NULL)", (s, e))
        return None if df.empty or df["u"].isna().all() else float(df["u"].mean()) * 100
    df = C.query("jeju", "SELECT real_wind_gen_jeju g, real_wind_capacity_jeju c FROM historical "
                 "WHERE timestamp BETWEEN ? AND ? AND real_wind_gen_jeju IS NOT NULL "
                 "AND real_wind_capacity_jeju > 0", (s, e))
    return None if df.empty else float((df["g"] / df["c"]).mean()) * 100


def _build_zones(date: str, table: str) -> dict[str, dict]:
    """8권역 기상(09–15시 평균)·하늘상태·활성도 — 예보/실측 공용 계산.

    예보는 양 권역 모두 forecast_horizon(최신 base), 실측은 양 권역 historical.
    """
    if table == "forecast":
        land = _station_means_fh("land", C.STATIONS_LAND, date)
        jeju = _station_means_fh("jeju", ["west"], date)
    else:
        land = _station_means("land", C.STATIONS_LAND, date, table)
        jeju = _station_means("jeju", ["west"], date, table)
    clear = CLEARSKY_0915[int(date[5:7])]

    zones = {}
    for name, z in ZONES.items():
        w = (jeju if z["db"] == "jeju" else land)[z["stn"]]
        ok = w["temp"] is not None and not pd.isna(w["temp"])
        ratio = None
        if w["rad"] is not None and not pd.isna(w["rad"]):
            ratio = float(min(1.0, max(0.0, w["rad"] / clear)))
        rain = w["rain"] if w["rain"] is not None and not pd.isna(w["rain"]) else 0.0
        rainy = ok and rain >= RAIN_MMH
        # 제주 풍력 활성도 = 고산 풍속을 육지 칸에 넣으면 과대표시 → 제주 자체 이용률을 직접 사용.
        if name == "제주":
            wu = jeju_wind_util(date, table == "forecast")
            wa = None if wu is None else {"pct": int(round(wu)), "lab": _util_label(wu)}
        else:
            wa = wind_act(w["wind"])
        zones[name] = {
            "mem": z["mem"], "stname": z["stname"], "solar": z["solar"], "wind": z["wind"],
            "lat": z["lat"], "lon": z["lon"], "ok": bool(ok),
            "temp": None if not ok else round(float(w["temp"]), 1),
            "wind_ms": None if pd.isna(w["wind"]) else round(float(w["wind"]), 1),
            "rain": None if not ok else round(float(rain), 1),
            "ratio": None if ratio is None else round(ratio, 2),
            "sky": sky_of(w["cloud"], w["rain"], w["temp"], ratio) if ok
                   else {"emo": "", "t": "—"},
            "sa": solar_act(ratio, rainy),
            "wa": wa,
        }
    return zones


@st.cache_data(ttl=C.CACHE_TTL)
def zone_day(date: str) -> dict[str, dict]:
    """선택일 8권역 — KIMG 예보 기준. 제주는 jeju DB 실데이터."""
    return _build_zones(date, "forecast")


@st.cache_data(ttl=C.CACHE_TTL)
def zone_actual(date: str) -> dict[str, dict]:
    """과거 날짜 8권역 실측(ASOS·제주 관측) — 예보와 같은 계산·같은 bin."""
    return _build_zones(date, "historical")


@st.cache_data(ttl=C.CACHE_TTL)
def national_util_actual(date: str) -> dict:
    """전국 이용률 실측(KPX 역산 gen_*_utilization_kr) — 예측과 같은 집계 기준."""
    day = C.query("land", "SELECT timestamp, gen_solar_utilization_kr AS s, "
                          "gen_wind_utilization_kr AS w FROM historical "
                          "WHERE timestamp BETWEEN ? AND ?",
                  (f"{date} 00:00:00", f"{date} 23:00:00"))
    if day.empty:
        return {"solar": None, "wind": None}
    h = day["timestamp"].dt.hour

    def pct(v):
        return None if pd.isna(v) else round(float(v) * 100, 1)

    return {"solar": pct(day.loc[h.between(9, 15), "s"].mean()),
            "wind": pct(day["w"].mean())}


@st.cache_data(ttl=C.CACHE_TTL)
def national_util(date: str) -> dict:
    """전국 이용률 예측(서빙 체인값) — est_horizon_land 최신 base.

    평균(태양광 09–15시·풍력 24시간) + 그날 시간별 최대.  est_*_util_land 컬럼이 아직 적재 안 됐으면
    (서빙 체인 미실행) graceful 하게 None — 기상개황 choropleth(forecast_horizon)는 영향 없음.
    """
    none = {"solar": None, "solar_max": None, "wind": None, "wind_max": None}
    try:
        day = C.query("land",
                      "SELECT timestamp, est_solar_util_land, est_wind_util_land "
                      "FROM est_horizon_land eh WHERE timestamp BETWEEN ? AND ? "
                      "AND base=(SELECT MAX(base) FROM est_horizon_land "
                      "WHERE timestamp=eh.timestamp AND est_solar_util_land IS NOT NULL)",
                      (f"{date} 00:00:00", f"{date} 23:00:00"))
    except Exception:  # noqa: BLE001 — 컬럼 미존재(미적재) 등은 None 으로 강등
        return none
    if day.empty or day["est_solar_util_land"].isna().all():
        return none
    h = day["timestamp"].dt.hour

    def pct(v):
        return None if pd.isna(v) else round(float(v) * 100, 1)

    return {"solar": pct(day.loc[h.between(9, 15), "est_solar_util_land"].mean()),
            "solar_max": pct(day["est_solar_util_land"].max()),
            "wind": pct(day["est_wind_util_land"].mean()),
            "wind_max": pct(day["est_wind_util_land"].max())}


# ---------------------------------------------------------------- HTML 임베드
@st.cache_resource
def _geo_text() -> str:
    return GEOJSON.read_text(encoding="utf-8")


_CONF = {"past": ("당일·과거 예보", "#16a34a"), "high": ("신뢰도 높음", "#16a34a"),
         "med": ("신뢰도 보통", "#d97706"), "low": ("신뢰도 낮음 · 참고용", "#dc2626")}


def conf_of(dplus: int) -> tuple[str, str]:
    key = "past" if dplus <= 0 else "high" if dplus <= 3 else "med" if dplus <= 7 else "low"
    return _CONF[key]


# 단색 강도맵 상수 — 투명도 상한 40% → opacity ≤ 0.60
GREEN = "#059669"
OP_MIN, OP_MAX = 0.06, 0.60

_TEMPLATE = """<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8" />
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/leaflet@1.9.3/dist/leaflet.css" />
<link rel="stylesheet" href="https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/static/pretendard.css" />
<script src="https://cdn.jsdelivr.net/npm/leaflet@1.9.3/dist/leaflet.js"></script>
<style>
  :root{ --ink:#0f172a; --sub:#475569; --line:#e2e8f0; --panel:#ffffff;
    --solar:#e11d48; --solar-soft:#fb7185; --wind:#1d4ed8; --wind-soft:#60a5fa; --green:#059669; }
  *{box-sizing:border-box}
  html,body{margin:0;padding:0;height:100%;width:100%;
    font-family:'Pretendard',-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;color:var(--ink);}
  #map{position:absolute;inset:0;}
  .leaflet-container{font-family:inherit;background:#e8edf2;}

  /* 좌우(A·C) 흰 그라데이션 — 중국·일본을 덮어 한국(B)만 남기고 정보영역을 비운다.
     z=450: 타일·면(200·400) 위, 권역 라벨·툴팁(600·650) 아래라 라벨은 그대로 보인다. */
  .fade{position:fixed;top:0;bottom:0;z-index:450;pointer-events:none;}
  .fade--l{left:0;width:34%;background:linear-gradient(to right,#fff 0%,#fff 42%,rgba(255,255,255,0) 100%);}
  .fade--r{right:0;width:34%;background:linear-gradient(to left,#fff 0%,#fff 42%,rgba(255,255,255,0) 100%);}

  .panel{position:fixed;top:12px;left:12px;z-index:1000;width:min(31%,410px);background:var(--panel);
    border:1px solid var(--line);border-radius:16px;box-shadow:0 8px 28px rgba(15,23,42,.10);overflow:hidden;}
  .panel__head{padding:14px 18px 12px;border-bottom:1px solid var(--line);}
  .panel__eyebrow{font-size:12px;font-weight:700;letter-spacing:.14em;text-transform:uppercase;color:var(--sub);}
  .panel__title{font-size:20px;font-weight:800;margin:0;line-height:1.25;}
  .panel__title .unit{font-size:13px;font-weight:600;color:var(--sub);margin-left:2px;}
  .panel__sub{font-size:13px;font-weight:600;color:var(--sub);margin-top:4px;line-height:1.35;}
  .conf{font-size:12px;font-weight:600;}
  .panel__body{padding:13px 18px 15px;}

  .wxstats{display:flex;gap:9px;margin-top:11px;}
  .wxstat{flex:1;text-align:center;background:#f8fafc;border:1px solid var(--line);border-radius:11px;padding:8px 6px;}
  .wxstat__k{font-size:11px;font-weight:700;color:var(--sub);white-space:nowrap;}
  .wxstat__v{font-size:18px;font-weight:800;color:var(--ink);margin-top:2px;font-variant-numeric:tabular-nums;}

  .modes{display:flex;gap:5px;margin-bottom:4px;}
  .mchip{flex:1;text-align:center;padding:7px 4px;border-radius:9px;border:1px solid var(--line);
    background:#fff;cursor:pointer;font-size:12px;font-weight:700;transition:.12s;line-height:1.1;}
  .mchip:hover{border-color:#cbd5e1;}
  .mchip.active{background:var(--ink);border-color:var(--ink);color:#fff;}

  .toggle{display:flex;align-items:center;gap:9px;padding:7px 10px;border-radius:9px;cursor:pointer;user-select:none;transition:background .12s;}
  .toggle:hover{background:#f8fafc;}
  .toggle input{position:absolute;opacity:0;width:0;height:0;}
  .swatch{width:15px;height:15px;border-radius:5px;flex:none;border:2px solid #cbd5e1;background:#fff;display:grid;place-items:center;transition:.12s;}
  .toggle[data-k="solar"] input:checked + .swatch{background:var(--solar);border-color:var(--solar);}
  .toggle[data-k="wind"]  input:checked + .swatch{background:var(--wind); border-color:var(--wind);}
  .swatch svg{opacity:0;width:9px;height:9px;}
  .toggle input:checked + .swatch svg{opacity:1;}
  .toggle .lab{font-size:13px;font-weight:600;flex:1;}
  .toggle .dot{width:10px;height:10px;border-radius:50%;}
  .toggle[data-k="solar"] .dot{background:var(--solar);}
  .toggle[data-k="wind"]  .dot{background:var(--wind);}

  .divider{height:1px;background:var(--line);margin:10px 0 10px;}

  .verdict{padding:14px 16px;border-radius:12px;background:#f8fafc;border:1px solid var(--line);}
  .verdict__top{display:flex;align-items:center;gap:8px;font-size:15px;font-weight:800;color:var(--ink);}
  .verdict__bar{display:flex;height:10px;border-radius:5px;overflow:hidden;margin:11px 0 12px;background:#e2e8f0;}
  .verdict__bar > span{display:block;height:100%;transition:width .3s;background:var(--green);}
  .verdict__msg{font-size:15px;line-height:1.75;color:var(--sub);}
  .verdict__msg b{font-weight:800;color:var(--ink);}

  /* 이용률 카드 2개(태양광·풍력) — 왼쪽 패널, verdict 아래 */
  .ucards{display:flex;gap:9px;margin-top:11px;}
  .ucard{flex:1;background:#f8fafc;border:1px solid var(--line);border-radius:12px;padding:10px 12px;}
  .ucard__k{font-size:12px;font-weight:700;color:var(--sub);white-space:nowrap;}
  .ucard__v{font-size:23px;font-weight:800;color:var(--ink);margin-top:3px;font-variant-numeric:tabular-nums;}
  .ucard__v small{font-size:13px;font-weight:600;color:var(--sub);margin-left:1px;}
  .ucard__s{font-size:11.5px;color:#94a3b8;font-weight:600;margin-top:2px;}

  .legend{margin-top:10px;font-size:11px;color:var(--sub);line-height:1.55;}
  .legend b{color:var(--ink);}

  /* ── 메인 hero: 표시 설정 접기(details) + 오른쪽 가스 송출량 패널 ── */
  .more{margin-top:11px;}
  .more > summary{cursor:pointer;list-style:none;font-size:12.5px;font-weight:700;color:var(--sub);
    padding:8px 11px;border:1px solid var(--line);border-radius:10px;background:#f8fafc;user-select:none;}
  .more > summary::-webkit-details-marker{display:none;}
  .more > summary:before{content:"⚙ ";opacity:.7;}
  .more > summary:hover{border-color:#cbd5e1;color:var(--ink);}
  .more[open] > summary{margin-bottom:9px;}
  .more .modes{margin-bottom:4px;}

  .panel--gas{left:auto;right:12px;width:min(27%,330px);}
  .panel--gas .panel__title{font-size:27px;}
  .panel--gas .divider{margin:11px 0;}
  .gasrow{display:flex;align-items:center;justify-content:space-between;gap:12px;font-size:14px;margin:9px 0;}
  .gasrow .gk{display:flex;align-items:center;gap:8px;color:var(--sub);font-weight:600;}
  .gasrow .gk i{width:10px;height:10px;border-radius:50%;display:inline-block;}
  .gasrow .gv{font-weight:800;font-variant-numeric:tabular-nums;color:var(--ink);}
  .gasrow .gv small{font-weight:600;color:#94a3b8;margin-left:3px;font-size:11.5px;}

  /* 전력수요 미니 시계열(스파크라인) — 오른쪽 패널 하단 */
  .dem__top{display:flex;align-items:center;justify-content:space-between;gap:12px;font-size:14px;}
  .dem__top .gk{color:var(--sub);font-weight:700;}
  .dem__top .gv{font-weight:800;color:var(--ink);font-variant-numeric:tabular-nums;}
  .dem__top .gv small{font-weight:600;color:#94a3b8;margin-left:3px;font-size:11.5px;}
  .sparklab{font-size:11.5px;font-weight:700;color:var(--sub);margin-top:9px;}
  .spark{display:block;width:100%;height:44px;margin-top:7px;}

  .wxwrap{background:none!important;border:none!important;}
  .wx{transform:translate(-50%,-50%);display:flex;flex-direction:column;align-items:center;gap:1px;pointer-events:none;}
  .wx .emo{font-size:22px;line-height:1;filter:drop-shadow(0 1px 3px rgba(0,0,0,.3));}
  .wx .nm{font-size:11px;font-weight:800;color:#0f172a;background:rgba(255,255,255,.85);
    padding:1px 6px;border-radius:7px;white-space:nowrap;box-shadow:0 1px 3px rgba(0,0,0,.14);}
  .wx .nm small{font-weight:600;color:#475569;}

  .leaflet-tooltip.rt{background:#0f172a;border:none;border-radius:10px;box-shadow:0 6px 20px rgba(0,0,0,.25);padding:0;color:#fff;font-family:inherit;}
  .leaflet-tooltip.rt:before{display:none;}
  .tip{padding:11px 13px;min-width:200px;}
  .tip__name{font-size:14px;font-weight:800;}
  .tip__mem{font-size:10.5px;color:#94a3b8;margin:1px 0 7px;}
  .tip__wx{display:flex;align-items:center;gap:6px;font-size:12px;font-weight:700;margin-bottom:7px;
    padding-bottom:7px;border-bottom:1px solid rgba(255,255,255,.14);}
  .tip__wx .ws{margin-left:auto;color:#94a3b8;font-weight:500;font-size:11px;}
  .tip__row{display:flex;align-items:center;justify-content:space-between;gap:14px;font-size:12px;margin:4px 0;}
  .tip__row .k{display:flex;align-items:center;gap:6px;color:#cbd5e1;}
  .tip__row .k i{width:8px;height:8px;border-radius:50%;display:inline-block;}
  .tip__row .v{font-weight:700;font-variant-numeric:tabular-nums;}
  .tip__row .v small{font-weight:500;color:#94a3b8;margin-left:3px;}
  .tip__act{margin-top:7px;padding-top:7px;border-top:1px solid rgba(255,255,255,.14);}
  .tip__act .lvl{font-size:11px;color:#94a3b8;}
  .mini{height:5px;border-radius:3px;background:rgba(255,255,255,.16);margin-top:3px;overflow:hidden;}
  .mini > span{display:block;height:100%;}
</style>
</head>
<body>
<div id="map"></div>
<div class="fade fade--l"></div>
<div class="fade fade--r"></div>

<div class="panel">
  <div class="panel__head">
    <h1 class="panel__title">__DATE_LABEL__ 종합 브리핑</h1>
    <div class="panel__sub">기상개황 및 가스 송출량 · D__DPLUS__<span class="conf" style="color:__CONF_C__"> · __CONF_T__</span></div>
  </div>
  <div class="panel__body">
    <div class="verdict">
      <div class="verdict__top"><span id="v-ico">☀️</span><span id="v-name">—</span></div>
      <div class="verdict__bar"><span id="v-strength"></span></div>
      <div class="verdict__msg" id="v-msg">—</div>
    </div>
    __WX_STATS__
    __UTIL_CARDS__
    <details class="more">
      <summary>표시 설정 · 일사 / 풍속 보기</summary>
      <div class="modes">
        <div class="mchip active" data-m="gen">신재생 강도</div>
        <div class="mchip" data-m="rad">일사</div>
        <div class="mchip" data-m="wind">풍속</div>
      </div>
      <div id="toggles">
        <label class="toggle" data-k="solar">
          <input type="checkbox" id="ck-solar" checked />
          <span class="swatch"><svg viewBox="0 0 10 10"><path d="M1 5l2.5 2.5L9 2" stroke="#fff" stroke-width="2" fill="none" stroke-linecap="round" stroke-linejoin="round"/></svg></span>
          <span class="lab">태양광 발전</span><span class="dot"></span>
        </label>
        <label class="toggle" data-k="wind">
          <input type="checkbox" id="ck-wind" checked />
          <span class="swatch"><svg viewBox="0 0 10 10"><path d="M1 5l2.5 2.5L9 2" stroke="#fff" stroke-width="2" fill="none" stroke-linecap="round" stroke-linejoin="round"/></svg></span>
          <span class="lab">풍력 발전</span><span class="dot"></span>
        </label>
      </div>
      <div class="legend" id="legend"></div>
    </details>
  </div>
</div>

__GAS_PANEL__

<script>
const GEO = __GEO__;
const SIDO2ZONE = __SIDO2ZONE__;
const Z = __ZONES__;            /* 권역별 기상(09–15 평균)·활성도 — Python 주입 */
const META = __META__;          /* dplus·하늘상태 대표·전국 이용률 예측 */
const GREEN = "__GREEN__", OP_MIN = __OP_MIN__, OP_MAX = __OP_MAX__, WIND_FULL = __WIND_FULL__;
const SA_MAX = __SA_MAX__, WA_MAX = __WA_MAX__;   /* 교정 활성도 상한(최상 bin) */

const LEGEND = {
  gen: "<b>면 색</b> = 신재생 발전 강도 — 진할수록 강함 · 체크된 발전원만 반영",
  rad: "<b>면 색</b> = 일사 비율 — 진할수록 강함",
  wind:"<b>면 색</b> = 풍속 — 진할수록 강함",
};

const map = L.map("map", {zoomControl:false, scrollWheelZoom:false, zoomSnap:0.25, zoomDelta:0.5});
L.control.zoom({position:'bottomright'}).addTo(map);
L.tileLayer("https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png?key=__CARTO_KEY__",{
  subdomains:"abcd", maxZoom:18, attribution:"&copy; OpenStreetMap &copy; CARTO"}).addTo(map);

/* hover 카드가 지도 가장자리에서 잘리지 않게 — 권역별로 '여는 방향'을 지정.
   제주(맨 아래)=위로, 강원·수도권(위)=아래로, 좌우 끝 권역=안쪽으로 펼친다. */
const TIP_DIR = {"제주":"top", "강원":"bottom", "수도권":"bottom", "충청권":"bottom",
                 "경북권":"left", "경남권":"left", "광주·전남":"right", "전북":"right"};

const gj = L.geoJSON(GEO, {
  style: ()=>({color:"#cbd5e1", weight:0.7, fillColor:"#94a3b8", fillOpacity:0.08}),
  onEachFeature: (f, lyr)=>{
    lyr._zone = SIDO2ZONE[f.properties.name];
    lyr.bindTooltip("", {className:"rt", sticky:true, opacity:1,
                         direction:(TIP_DIR[lyr._zone] || "top")});
    lyr.on('mouseover', ()=> lyr.setStyle({weight:2.4, color:"#0f172a"}));
    lyr.on('mouseout',  ()=> lyr.setStyle({weight:0.7, color:"#cbd5e1"}));
  }
}).addTo(map);

/* 대한민국 전체(제주 포함)에 화면 맞춤 — 좌측 패널만큼 패딩, 한국 밖 이동·축소 잠금.
   숨은 탭에서 크기 0으로 초기화되면 지도가 비어 보이므로, 컨테이너가 실제 크기를
   가질 때까지 맞춤을 미루고(ResizeObserver) 보이는 순간 invalidateSize 후 fit한다. */
const fullB = gj.getBounds();
/* 기본 배율 — 위쪽(고성·북부)을 NORTH_TRIM 만큼 잘라 한국을 더 크게(제주는 아래 여백으로 유지).
   0 = 전체(고성~마라도)  ·  값↑ = 더 확대(위가 더 잘림).  ← 기본 배율은 이 한 값으로 조절. */
const NORTH_TRIM = 0.05;
const fitNorth = fullB.getNorth() - (fullB.getNorth() - fullB.getSouth()) * NORTH_TRIM;
const FIT = L.latLngBounds(fullB.getSouthWest(), L.latLng(fitNorth, fullB.getEast()));
const KOREA = fullB.pad(0.02);
map.setMaxBounds(fullB.pad(0.6));
const mapEl = document.getElementById("map");
let needFit = true;
function fitKorea(){
  if (!needFit || !mapEl.clientWidth || !mapEl.clientHeight) return;
  map.invalidateSize();
  /* 한국을 가로 가운데(좌우 흰 마스크 사이)에 맞춤 — 위는 잘리고 아래(제주)는 여백 확보.
     컨테이너 폭 비례(sidePad)라 화면 크기에 강건. */
  const sidePad = Math.round(mapEl.clientWidth * 0.24);
  map.fitBounds(FIT, {paddingTopLeft:[sidePad,6], paddingBottomRight:[sidePad,22]});
  map.setMinZoom(map.getZoom());
  needFit = false;
}
fitKorea();
new ResizeObserver(()=>{ map.invalidateSize(); fitKorea(); }).observe(mapEl);

/* 권역 라벨 — 하늘상태 이모지 + 권역명·기온 */
const labelLayer = L.layerGroup().addTo(map);
Object.keys(Z).forEach(name=>{
  const d = Z[name];
  const t = d.ok ? Math.round(d.temp) + "°" : "—";
  L.marker([d.lat, d.lon], {interactive:false, icon: L.divIcon({
    className:"wxwrap", iconSize:[0,0], iconAnchor:[0,0],
    html:`<div class="wx"><span class="emo">${d.sky.emo}</span>`+
         `<span class="nm">${name} <small>${t}</small></span></div>`})}).addTo(labelLayer);
});

function fmt(v, suf){ return (v===null||v===undefined) ? "—" : v.toLocaleString() + (suf||""); }
function tipHTML(name, d){
  if (!d.ok){
    return `<div class="tip"><div class="tip__name">${name}</div>`+
      `<div class="tip__mem">${d.mem}</div>`+
      `<div class="tip__wx">기상 데이터 없음 <span class="ws">수집 범위 밖</span></div></div>`;
  }
  const sa = d.sa ? d.sa : {pct:0, lab:"—"}, wa = d.wa ? d.wa : {pct:0, lab:"—"};
  const rad = d.ratio===null ? "—" : Math.round(d.ratio*100)+"%";
  const rain = d.rain>0 ? ` · 강수 ${d.rain} mm/h` : "";
  return `<div class="tip"><div class="tip__name">${name} <span style="font-size:10px;color:#64748b">D${META.dplus>=0?"+":""}${META.dplus}</span></div>`+
    `<div class="tip__mem">${d.mem}</div>`+
    `<div class="tip__wx">${d.sky.emo} ${d.sky.t} · ${d.temp}° · 풍속 ${fmt(d.wind_ms," m/s")}<span class="ws">기상: ${d.stname}</span></div>`+
    `<div class="tip__row"><span class="k">일사 비율 (09–15)</span><span class="v">${rad}<small>${rain}</small></span></div>`+
    `<div class="tip__row"><span class="k"><i style="background:var(--solar)"></i>태양광 용량</span><span class="v">${d.solar.toLocaleString()} MW</span></div>`+
    `<div class="tip__row"><span class="k"><i style="background:var(--wind)"></i>풍력 용량</span><span class="v">${d.wind.toLocaleString()} MW</span></div>`+
    `<div class="tip__act">`+
      `<div class="tip__row"><span class="lvl">☀️ 태양광 활성도</span><span class="v">${sa.pct}%<small>${sa.lab}</small></span></div>`+
      `<div class="mini"><span style="width:${sa.pct}%;background:var(--solar-soft)"></span></div>`+
      `<div class="tip__row" style="margin-top:6px"><span class="lvl">🌀 풍력 활성도</span><span class="v">${wa.pct}%<small>${wa.lab}</small></span></div>`+
      `<div class="mini"><span style="width:${wa.pct}%;background:var(--wind-soft)"></span></div>`+
    `</div></div>`;
}

let mode = "gen";
function render(){
  const ckS=document.getElementById("ck-solar").checked, ckW=document.getElementById("ck-wind").checked;
  document.getElementById("toggles").style.display = (mode==="gen") ? "" : "none";
  document.getElementById("legend").innerHTML = LEGEND[mode];

  /* 신재생 강도: gen = Σ(용량×기대이용률). 기준 = 최대 권역이 최상 bin일 때 */
  let refGen = 0;
  Object.keys(Z).forEach(name=>{
    const d=Z[name];
    refGen = Math.max(refGen, (ckS?d.solar:0)*SA_MAX/100 + (ckW?d.wind:0)*WA_MAX/100);
    d._gen = (ckS? d.solar*(d.sa?d.sa.pct:0)/100 : 0) + (ckW? d.wind*(d.wa?d.wa.pct:0)/100 : 0);
  });
  const maxGen = refGen || 1;
  let sumScore=0, nOk=0, top=[];
  Object.keys(Z).forEach(name=>{
    const d=Z[name];
    if (!d.ok){ d._score=null; return; }
    const genScore = Math.min(1, d._gen/maxGen);
    d._score = (mode==="gen") ? genScore
             : (mode==="rad") ? (d.ratio===null ? null : d.ratio)
             : (d.wind_ms===null ? null : Math.min(1, d.wind_ms/WIND_FULL));
    sumScore += genScore; nOk += 1; top.push([name, d._gen]);
  });
  top.sort((a,b)=>b[1]-a[1]);

  gj.getLayers().forEach(lyr=>{
    const d=Z[lyr._zone]; if(!d) return;
    if (d._score===null || d._score===undefined){
      lyr.setStyle({fillColor:"#94a3b8", fillOpacity:0.08, color:"#cbd5e1", weight:0.7});
    } else {
      lyr.setStyle({fillColor:GREEN, fillOpacity:OP_MIN+(OP_MAX-OP_MIN)*d._score,
                    color:"#cbd5e1", weight:0.7});
    }
    lyr.setTooltipContent(tipHTML(lyr._zone, d));
  });

  document.getElementById("v-ico").textContent = META.rep.emo || "·";
  document.getElementById("v-name").textContent = `전국 대체로 ${META.rep.t}`;
  /* 이용률 수치(☀️/🌀)는 아래 카드가 보여주므로 verdict 에선 중복 표기하지 않는다. */
  if (nOk){
    const avg = Math.round(sumScore/nOk*100);
    document.getElementById("v-strength").style.width = Math.min(100, avg*1.4)+"%";
    const lead = top.length>=2
      ? `<br>가장 활발한 권역 — <b>${top[0][0]}</b> · <b>${top[1][0]}</b>` : "";
    document.getElementById("v-msg").innerHTML =
      `전국 신재생 가동 강도 <b>${avg}%</b>${lead}`;
  } else {
    document.getElementById("v-strength").style.width = "0%";
    document.getElementById("v-msg").innerHTML = "이 날짜의 기상·이용률 데이터가 없습니다.";
  }
}

document.querySelectorAll(".mchip").forEach(b=>{
  b.onclick = ()=>{ mode=b.dataset.m;
    document.querySelectorAll(".mchip").forEach(x=>x.classList.remove("active"));
    b.classList.add("active"); render(); };
});
document.getElementById("ck-solar").onchange=render;
document.getElementById("ck-wind").onchange=render;
render();
</script>
</body>
</html>"""


def _sparkline_svg(vals: list, color: str = "#1f77b4", w: int = 264, h: int = 44,
                   fill: bool = True, overlay: list | None = None,
                   overlay_color: str = "#c283b9") -> str:
    """미니 시계열 스파크라인 SVG. vals=주선(+옅은 채움), overlay=보조선(실측 등, 같은 y범위로 겹침).

    x축은 인덱스(0..n-1) 고정이라 주선·보조선이 같은 시간축에 정렬된다. None은 건너뛴다.
    """
    n = len(vals)
    allv = [v for s in (vals, overlay or []) for v in s if v is not None]
    main_pts = [(i, v) for i, v in enumerate(vals) if v is not None]
    if n < 2 or len(main_pts) < 2 or not allv:
        return ""
    ymin, ymax = min(allv), max(allv)
    rx = (n - 1) or 1
    ry = (ymax - ymin) or 1
    pad = 4

    def X(x):
        return pad + x / rx * (w - 2 * pad)

    def Y(y):
        return h - pad - (y - ymin) / ry * (h - 2 * pad)

    def poly(s):
        return " ".join(f"{X(i):.1f},{Y(v):.1f}" for i, v in enumerate(s) if v is not None)

    main = poly(vals)
    xs = [i for i, v in enumerate(vals) if v is not None]
    parts = [f'<svg class="spark" viewBox="0 0 {w} {h}" preserveAspectRatio="none">']
    if fill:
        parts.append(f'<polygon points="{X(xs[0]):.1f},{h - pad} {main} '
                     f'{X(xs[-1]):.1f},{h - pad}" fill="{color}" fill-opacity="0.10"/>')
    if overlay and poly(overlay):
        parts.append(f'<polyline points="{poly(overlay)}" fill="none" stroke="{overlay_color}" '
                     'stroke-width="1.8" stroke-opacity="0.9" ' #stroke-dasharray="3 2"
                     'stroke-linejoin="round" stroke-linecap="round"/>')
    parts.append(f'<polyline points="{main}" fill="none" stroke="{color}" stroke-width="1.4" '
                 'stroke-dasharray="3 2" stroke-linejoin="round" stroke-linecap="round"/>')
    parts.append('</svg>')
    return "".join(parts)


@st.cache_data(ttl=C.CACHE_TTL)
def national_humidity(date: str) -> float | None:
    """전국 평균 습도(%) — forecast_horizon 09–15시 5지점 평균(최신 base). 없으면 None."""
    cols = ", ".join(f"reh_{s}" for s in C.STATIONS_LAND)
    s, e = f"{date} 09:00:00", f"{date} 15:00:00"
    df = C.query("land", f"SELECT {cols} FROM forecast_horizon fh WHERE timestamp BETWEEN ? AND ? "
                 "AND base=(SELECT MAX(base) FROM forecast_horizon WHERE timestamp=fh.timestamp)",
                 (s, e))
    if df.empty:
        return None
    m = df.mean(numeric_only=True).mean()
    return None if pd.isna(m) else float(m)


def _wx_stats_html(tmax: float | None, tmin: float | None, humidity: float | None) -> str:
    """왼쪽 패널 — 전국 최고/최저 기온·습도 통계 3칸."""
    def cell(k, v, suf):
        vv = "—" if v is None else f"{v:.0f}{suf}"
        return f'<div class="wxstat"><div class="wxstat__k">{k}</div><div class="wxstat__v">{vv}</div></div>'

    return ('<div class="wxstats">'
            + cell("🌡 최고기온", tmax, "°")
            + cell("최저기온", tmin, "°")
            + cell("💧 습도", humidity, "%")
            + '</div>')


def _util_cards_html(util: dict, util_act: dict | None = None) -> str:
    """왼쪽 패널 — 전국 태양광·풍력 이용률 카드 2개(예측값 + 최대/실측 보조)."""
    util_act = util_act or {}

    def card(emoji, label, avg, mx, act):
        if avg is None:
            v, sub = "—", ""
        else:
            v = f"{avg:.1f}"
            sub = (f"실측 {act:.1f}%" if act is not None
                   else f"최대 {mx:.1f}%" if mx is not None else "")
        return (f'<div class="ucard"><div class="ucard__k">{emoji} {label}</div>'
                f'<div class="ucard__v">{v}<small>%</small></div>'
                f'<div class="ucard__s">{sub}</div></div>')

    return ('<div class="ucards">'
            + card("☀️", "태양광 이용률", util.get("solar"), util.get("solar_max"),
                   util_act.get("solar"))
            + card("🌀", "풍력 이용률", util.get("wind"), util.get("wind_max"),
                   util_act.get("wind"))
            + '</div>')


def _gas_panel_html(gas: dict | None) -> str:
    """오른쪽 패널 — 예상 가스 송출량(+발전용 시계열) · 전력수요 시계열(실측 겹침) · 순 부하 범위.

    날짜는 왼쪽 패널에만 두어 중복 표기하지 않는다. gas 없으면 빈 문자열.
    """
    if not gas:
        return ""

    def f(v):
        return "—" if v is None else f"{v:,.0f}"

    cg_row = ""
    if gas.get("citygas_ton") is not None:
        cg_row = ('<div class="gasrow"><span class="gk"><i style="background:#f2a93b"></i>'
                  f'도시가스(참고)</span><span class="gv">{f(gas["citygas_ton"])}'
                  '<small>TON</small></span></div>')
    # 4. 발전용 가스(예상) 시계열 — 발전량 MW 예측(녹색 점선) + 실측 MW 겹침(회색), 전력수요와 동일 방식
    gas_chart = ""
    if gas.get("gas_spark"):
        gas_chart = ('<div class="sparklab">발전용 가스(예상)</div>'
                     + _sparkline_svg(gas["gas_spark"], color="#059669",
                                      overlay=gas.get("gas_real_spark"), overlay_color="#94a3b8"))
    # 7. 전력수요(예상) 시계열 + 실측 겹침(수치 없이 선만)
    dem = ""
    if gas.get("demand_spark") and gas.get("demand_peak") is not None:
        dem = ('<div class="divider"></div>'
               '<div class="dem__top"><span class="gk">전력수요(예상)</span>'
               f'<span class="gv">{f(gas["demand_peak"])}<small>MW 최대</small></span></div>'
               + _sparkline_svg(gas["demand_spark"], color="#1f77b4",
                                overlay=gas.get("demand_real_spark")))
    # 8. 순 부하(Net Load) 최대·최소
    nl = ""
    if gas.get("nl_max") is not None:
        nl = ('<div class="divider"></div>'
              '<div class="gasrow"><span class="gk">순 부하 최대</span>'
              f'<span class="gv">{f(gas["nl_max"])}<small>MW</small></span></div>'
              '<div class="gasrow"><span class="gk">순 부하 최소</span>'
              f'<span class="gv">{f(gas.get("nl_min"))}<small>MW</small></span></div>')
    return (
        '<div class="panel panel--gas">'
        '<div class="panel__head">'
        '<div class="panel__eyebrow">오늘의 예상 가스 송출량</div>'
        f'<h1 class="panel__title">{f(gas["total_ton"])} <span class="unit">TON</span></h1>'
        '</div><div class="panel__body">'
        '<div class="gasrow"><span class="gk"><i style="background:var(--green)"></i>'
        f'발전용 가스</span><span class="gv">{f(gas["gen_ton"])}<small>TON</small></span></div>'
        f'{cg_row}'
        f'{gas_chart}'
        '<div class="divider"></div>'
        '<div class="gasrow"><span class="gk">시간당 최대</span>'
        f'<span class="gv">{f(gas["max_ton"])}<small>TON/h</small></span></div>'
        '<div class="gasrow"><span class="gk">시간당 최소</span>'
        f'<span class="gv">{f(gas.get("min_ton"))}<small>TON/h</small></span></div>'
        f'{dem}'
        f'{nl}'
        '</div></div>')


def build_html(day: pd.Timestamp, dplus: int, zones: dict, util: dict,
               gas: dict | None = None, util_act: dict | None = None,
               humidity: float | None = None) -> str:
    """임베드 HTML — 선택일 데이터 주입.

    gas(예상 가스 송출량+전력수요)·util_act(이용률 실측)·humidity(전국 습도)를 주면
    좌우 패널을 채운다(종합브리핑 탭의 메인 화면).
    """
    conf_t, conf_c = conf_of(dplus)
    skies = [z["sky"]["t"] for z in zones.values() if z["ok"]]
    rep = ({"emo": "", "t": "—"} if not skies else
           next(z["sky"] for z in zones.values()
                if z["ok"] and z["sky"]["t"] == max(set(skies), key=skies.count)))
    weekday = "월화수목금토일"[day.weekday()]
    temps = [z["temp"] for z in zones.values() if z["ok"] and z["temp"] is not None]
    tmax = max(temps) if temps else None
    tmin = min(temps) if temps else None
    meta = {"dplus": dplus, "rep": rep,
            "util": {"solar": util["solar"], "wind": util["wind"],
                     "solar_max": util.get("solar_max"), "wind_max": util.get("wind_max")}}
    html = _TEMPLATE
    for k, v in [("__GEO__", _geo_text()),
                 ("__SIDO2ZONE__", json.dumps(SIDO2ZONE, ensure_ascii=False)),
                 ("__ZONES__", json.dumps(zones, ensure_ascii=False)),
                 ("__META__", json.dumps(meta, ensure_ascii=False)),
                 ("__DATE_LABEL__", f"{day:%m-%d} ({weekday})"),
                 ("__DPLUS__", f"{dplus:+d}"),
                 ("__CONF_T__", conf_t), ("__CONF_C__", conf_c),
                 ("__GREEN__", GREEN), ("__OP_MIN__", str(OP_MIN)),
                 ("__OP_MAX__", str(OP_MAX)), ("__WIND_FULL__", str(WIND_FULL)),
                 ("__SA_MAX__", str(SA_MAX)), ("__WA_MAX__", str(WA_MAX)),
                 ("__CARTO_KEY__", C.CARTO_API_KEY),
                 ("__GAS_PANEL__", _gas_panel_html(gas)),
                 ("__UTIL_CARDS__", _util_cards_html(util, util_act)),
                 ("__WX_STATS__", _wx_stats_html(tmax, tmin, humidity))]:
        html = html.replace(k, v)
    return html

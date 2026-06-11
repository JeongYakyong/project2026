# -*- coding: utf-8 -*-
"""기상개황 — 8권역 단색(초록) choropleth, Leaflet HTML 임베드 (9. design/visual.md A안).

- 디자인 = 9. design/renewable_capacity_map.html 프로토타입 재현(§7 임의 변경 금지).
  날짜 선택만 Streamlit(◀/▶ 네비게이터) 쪽으로 빼고, 표시 모드(신재생 강도/일사/풍속)와
  발전원 토글은 HTML 내부 JS — 실데이터는 렌더 시 주입(A안).
- 기준 시간 = 09–15시 평균(일사·기온·풍속·강수·운량). 별도 시각 선택 없음.
- 면 색(초록 진하기): 신재생 강도(설비용량×활성도, §3.4) / 일사 비율 / 풍속.
- 권역 라벨 = 하늘상태 이모지 + 권역명·기온.
- 제주 = jeju DB 실데이터(고산 west) — 육지 보간 대체 금지(§7).
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

# 17 시도 → 8 권역 (visual.md §4)
SIDO2ZONE = {
    "서울특별시": "수도권", "경기도": "수도권", "인천광역시": "수도권",
    "대전광역시": "충청권", "세종특별자치시": "충청권", "충청남도": "충청권", "충청북도": "충청권",
    "광주광역시": "광주·전남", "전라남도": "광주·전남",
    "전라북도": "전북",
    "부산광역시": "경남권", "울산광역시": "경남권", "경상남도": "경남권",
    "대구광역시": "경북권", "경상북도": "경북권",
    "강원도": "강원", "제주특별자치도": "제주",
}

# 8 권역 — 구성·기상 지점·설비용량(MW, 2026.04 전국총량 × 2024 지역비율)·라벨 좌표 (visual.md §3.1)
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

# ---- 활성도 BIN — 실측 교정 완료(2026-06-11 사용자 확정) -------------------
# historical 2022-01~2026-06(1,620일)의 5지점 평균 기상 ↔ 실제 전국 이용률
# (gen_solar/wind_utilization_kr, 09–15시 평균)을 역산, bin별 실측 평균으로 교정.
# 활성도 % = 기대 전국 이용률 — 하단 테이블의 이용률 예측과 같은 단위.
# 전국 기준 교정을 권역 단일 지점에 적용 → 권역 간 상대 신호(바람 많은 권역이 진함).
SOLAR_BINS = [(0.80, 61, "매우 좋음"), (0.60, 49, "좋음"), (0.40, 36, "보통"),
              (0.20, 23, "낮음"), (0.00, 12, "매우 낮음")]
# 풍속 경계 = ASOS 10m 지점 스케일. 허브높이 파워커브 경계(3/6/9/13)는
# 지점 평균이 사실상 도달 불가(6년간 ≥9m/s 0일)라 폐기.
WIND_BINS = [(0, 2, 11, "미풍"), (2, 3, 21, "약함"), (3, 4.5, 44, "양호"),
             (4.5, 6, 72, "좋음"), (6, 25, 77, "최적"), (25, 999, 0, "차단")]
SA_MAX = max(p for _, p, _ in SOLAR_BINS)     # 강도맵 기준 — 최상 bin 기대 이용률
WA_MAX = max(p for _, _, p, _ in WIND_BINS)

# 청천 일사(09–15시 평균, MJ/m²·h) — 월별 관측 P97 실측값(2022~2026 historical)
CLEARSKY_0915 = {1: 1.64, 2: 2.09, 3: 2.50, 4: 2.93, 5: 3.10, 6: 3.06,
                 7: 2.79, 8: 2.69, 9: 2.59, 10: 2.20, 11: 1.83, 12: 1.47}

# 하늘상태 4분류(맑음/약간흐림/흐림/비·눈) — 2026-06-11 관측 분포로 경계 확정:
# 운량<0.5는 일사비율 ~0.7(감쇄 미미), ≥0.85에서 0.26으로 급락. 빈도 45/30/25% 균형.
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
    """하늘상태 4분류 — 강수 우선, 운량 기준. 운량 결측 시 일사 비율로 근사(§3.3 fallback)."""
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
_VARS = ("temp_", "radiation_", "wind_spd_10m_", "rainfall_", "total_cloud_")


def _station_means(region: str, suffixes: list[str], date: str) -> dict[str, dict]:
    """지점별 09–15시 평균 {suffix: {temp, rad, wind, rain, cloud}} — 결측 컬럼은 NaN."""
    s, e = f"{date} {HOURS[0]}", f"{date} {HOURS[1]}"
    cols = [f"{v}{sx}" for sx in suffixes for v in _VARS]
    df = C.query(region, f"SELECT {', '.join(cols)} FROM forecast "
                         "WHERE timestamp BETWEEN ? AND ?", (s, e))
    out = {}
    for sx in suffixes:
        if df.empty:
            out[sx] = {v: float("nan") for v in ("temp", "rad", "wind", "rain", "cloud")}
            continue
        m = df.mean(numeric_only=True)
        out[sx] = {"temp": m.get(f"temp_{sx}"), "rad": m.get(f"radiation_{sx}"),
                   "wind": m.get(f"wind_spd_10m_{sx}"), "rain": m.get(f"rainfall_{sx}"),
                   "cloud": m.get(f"total_cloud_{sx}")}
    return out


@st.cache_data(ttl=C.CACHE_TTL)
def zone_day(date: str) -> dict[str, dict]:
    """선택일 8권역 기상(09–15시 평균)·하늘상태·활성도. 제주는 jeju DB 실데이터."""
    land = _station_means("land", C.STATIONS_LAND, date)
    jeju = _station_means("jeju", ["west"], date)
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
            "wa": wind_act(w["wind"]),
        }
    return zones


@st.cache_data(ttl=C.CACHE_TTL)
def national_util(date: str) -> dict:
    """전국 이용률 예측(6단계 서빙값) — 평균(태양광 09–15시·풍력 24시간) + 그날 시간별 최대."""
    day = C.query("land", "SELECT timestamp, est_solar_util_land, est_wind_util_land "
                          "FROM forecast WHERE timestamp BETWEEN ? AND ?",
                  (f"{date} 00:00:00", f"{date} 23:00:00"))
    if day.empty:
        return {"solar": None, "solar_max": None, "wind": None, "wind_max": None}
    h = day["timestamp"].dt.hour

    def pct(v):
        return None if pd.isna(v) else round(float(v) * 100, 1)

    return {"solar": pct(day.loc[h.between(9, 15), "est_solar_util_land"].mean()),
            "solar_max": pct(day["est_solar_util_land"].max()),
            "wind": pct(day["est_wind_util_land"].mean()),
            "wind_max": pct(day["est_wind_util_land"].max())}


# ---------------------------------------------------------------- HTML (A안 임베드)
@st.cache_resource
def _geo_text() -> str:
    return GEOJSON.read_text(encoding="utf-8")


_CONF = {"past": ("당일·과거 예보", "#16a34a"), "high": ("신뢰도 높음", "#16a34a"),
         "med": ("신뢰도 보통", "#d97706"), "low": ("신뢰도 낮음 · 참고용", "#dc2626")}


def conf_of(dplus: int) -> tuple[str, str]:
    key = "past" if dplus <= 0 else "high" if dplus <= 3 else "med" if dplus <= 7 else "low"
    return _CONF[key]


# 잠정 상수(visual.md §3.4) — 단색 강도맵. 투명도 상한 40% → opacity ≤ 0.60
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

  .panel{position:fixed;top:12px;left:12px;z-index:1000;width:280px;background:var(--panel);
    border:1px solid var(--line);border-radius:14px;box-shadow:0 8px 28px rgba(15,23,42,.10);overflow:hidden;}
  .panel__head{padding:12px 16px 10px;border-bottom:1px solid var(--line);}
  .panel__eyebrow{font-size:11px;font-weight:700;letter-spacing:.14em;text-transform:uppercase;color:var(--sub);}
  .panel__title{font-size:16px;font-weight:800;margin:3px 0 0;line-height:1.25;}
  .panel__title .conf{font-size:11px;font-weight:600;margin-left:6px;}
  .panel__body{padding:11px 16px 13px;}

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

  .verdict{padding:10px 12px;border-radius:10px;background:#f8fafc;border:1px solid var(--line);}
  .verdict__top{display:flex;align-items:center;gap:7px;font-size:12px;font-weight:700;color:var(--sub);}
  .verdict__bar{display:flex;height:8px;border-radius:5px;overflow:hidden;margin:8px 0 9px;background:#e2e8f0;}
  .verdict__bar > span{display:block;height:100%;transition:width .3s;background:var(--green);}
  .verdict__msg{font-size:12.5px;line-height:1.5;color:var(--ink);}
  .verdict__msg b{font-weight:800;}

  .legend{margin-top:10px;font-size:11px;color:var(--sub);line-height:1.55;}
  .legend b{color:var(--ink);}

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

<div class="panel">
  <div class="panel__head">
    <div class="panel__eyebrow">기상개황 · 8권역</div>
    <h1 class="panel__title">__DATE_LABEL__<span class="conf" style="color:__CONF_C__">__CONF_T__</span></h1>
  </div>
  <div class="panel__body">
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
    <div class="divider"></div>
    <div class="verdict">
      <div class="verdict__top"><span id="v-ico">☀️</span><span id="v-name">—</span></div>
      <div class="verdict__bar"><span id="v-strength"></span></div>
      <div class="verdict__msg" id="v-msg">—</div>
    </div>
    <div class="legend" id="legend"></div>
  </div>
</div>

<script>
const GEO = __GEO__;
const SIDO2ZONE = __SIDO2ZONE__;
const Z = __ZONES__;            /* 권역별 기상(09–15 평균)·활성도 — Python 주입 */
const META = __META__;          /* dplus·하늘상태 대표·전국 이용률 예측 */
const GREEN = "__GREEN__", OP_MIN = __OP_MIN__, OP_MAX = __OP_MAX__, WIND_FULL = __WIND_FULL__;
const SA_MAX = __SA_MAX__, WA_MAX = __WA_MAX__;   /* 교정 활성도 상한(최상 bin) */

const LEGEND = {
  gen: "<b>면 색(초록)</b> = 신재생 발전 강도(설비용량 × 활성도, 진할수록 강함)<br>체크된 발전원만 반영 · 커서를 올리면 권역 카드",
  rad: "<b>면 색(초록)</b> = 일사 비율(09–15시 평균 ÷ 청천 일사, 진할수록 강함)<br>커서를 올리면 권역 카드",
  wind:"<b>면 색(초록)</b> = 풍속(09–15시 평균, " + WIND_FULL + " m/s에서 최대)<br>커서를 올리면 권역 카드",
};

const map = L.map("map", {zoomControl:false, scrollWheelZoom:false, zoomSnap:0.25, zoomDelta:0.5});
L.control.zoom({position:'bottomright'}).addTo(map);
L.tileLayer("https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png",{
  subdomains:"abcd", maxZoom:18, attribution:"&copy; OpenStreetMap &copy; CARTO"}).addTo(map);

const gj = L.geoJSON(GEO, {
  style: ()=>({color:"#cbd5e1", weight:0.7, fillColor:"#94a3b8", fillOpacity:0.08}),
  onEachFeature: (f, lyr)=>{
    lyr._zone = SIDO2ZONE[f.properties.name];
    lyr.bindTooltip("", {className:"rt", sticky:true});
    lyr.on('mouseover', ()=> lyr.setStyle({weight:2.4, color:"#0f172a"}));
    lyr.on('mouseout',  ()=> lyr.setStyle({weight:0.7, color:"#cbd5e1"}));
  }
}).addTo(map);

/* 대한민국 전체(제주 포함)에 화면 맞춤 — 좌측 패널만큼 패딩, 한국 밖 이동·축소 잠금 */
const KOREA = gj.getBounds().pad(0.02);
map.fitBounds(KOREA, {paddingTopLeft:[300,8], paddingBottomRight:[8,8]});
map.setMaxBounds(KOREA.pad(0.35));
map.setMinZoom(map.getZoom());

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

  /* 신재생 강도(§3.4): gen = Σ(용량×기대이용률). 기준 = 최대 권역이 최상 bin일 때 */
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
  document.getElementById("v-name").textContent =
    `D${META.dplus>=0?"+":""}${META.dplus} · 전국 대체로 ${META.rep.t}`;
  const u = META.util;
  const utilLine = (u.solar===null) ? "" :
    `전국 이용률(예측) ☀️ <b>${u.solar}%</b>·최대 ${u.solar_max}% · 🌀 <b>${u.wind}%</b>·최대 ${u.wind_max}%`;
  if (nOk){
    const avg = Math.round(sumScore/nOk*100);
    document.getElementById("v-strength").style.width = Math.min(100, avg*1.4)+"%";
    const lead = top.length>=2 ? `가장 활발: <b>${top[0][0]}</b> · <b>${top[1][0]}</b>` : "";
    document.getElementById("v-msg").innerHTML =
      `전국 신재생 가동 강도 <b>${avg}%</b>. ${lead}.` + (utilLine ? `<br>${utilLine}` : "");
  } else {
    document.getElementById("v-strength").style.width = "0%";
    document.getElementById("v-msg").innerHTML =
      utilLine ? `기상 데이터 없음 — ${utilLine}` : "이 날짜의 기상·이용률 데이터가 없습니다.";
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


def build_html(day: pd.Timestamp, dplus: int, zones: dict, util: dict) -> str:
    """A안 임베드 HTML — 선택일 데이터 주입(프로토타입 디자인 그대로)."""
    conf_t, conf_c = conf_of(dplus)
    skies = [z["sky"]["t"] for z in zones.values() if z["ok"]]
    rep = ({"emo": "", "t": "—"} if not skies else
           next(z["sky"] for z in zones.values()
                if z["ok"] and z["sky"]["t"] == max(set(skies), key=skies.count)))
    weekday = "월화수목금토일"[day.weekday()]
    meta = {"dplus": dplus, "rep": rep,
            "util": {"solar": util["solar"], "wind": util["wind"]}}
    html = _TEMPLATE
    for k, v in [("__GEO__", _geo_text()),
                 ("__SIDO2ZONE__", json.dumps(SIDO2ZONE, ensure_ascii=False)),
                 ("__ZONES__", json.dumps(zones, ensure_ascii=False)),
                 ("__META__", json.dumps(meta, ensure_ascii=False)),
                 ("__DATE_LABEL__", f"{day:%m-%d} ({weekday}) · D{dplus:+d}"),
                 ("__CONF_T__", conf_t), ("__CONF_C__", conf_c),
                 ("__GREEN__", GREEN), ("__OP_MIN__", str(OP_MIN)),
                 ("__OP_MAX__", str(OP_MAX)), ("__WIND_FULL__", str(WIND_FULL)),
                 ("__SA_MAX__", str(SA_MAX)), ("__WA_MAX__", str(WA_MAX))]:
        html = html.replace(k, v)
    return html

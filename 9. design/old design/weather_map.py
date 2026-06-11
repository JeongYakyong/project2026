# -*- coding: utf-8 -*-
"""기상개황 인포그래픽 — 시도 choropleth(5지점 IDW 보간) + 신재생 중요지역 원 + ASOS 지점.

- 바탕색 = 선택 기상변수(기온/일사/풍속)를 5개 관측지점에서 IDW(1/d²)로 시도 중심점에 보간
  → 관측이 없는 시도(서울 등)까지 전 국토 커버.
- 원 = 신재생 발전량 비중(9. design/태양광_풍력_지역별_TOP5.txt): 태양광=주황(2025),
  풍력=청록(2023). 비중이 클수록 크고 진함. 같은 시도는 좌(태양광)/우(풍력)로 살짝 어긋남.
- 지점 = 수집 5지점(파랑, hover에 실측 예보값) + 참고 13지점(회색, 9. design 18지점 셋).
"""
from pathlib import Path
import json

import numpy as np
import pandas as pd
import streamlit as st
import plotly.graph_objects as go

ROOT = Path(__file__).resolve().parent.parent
GEOJSON = ROOT / "9. design" / "skorea_provinces_simplified.json"

# 수집 5지점 (DB 컬럼 suffix ↔ 좌표, 9. design/reselected_asos_map.html)
STATIONS = {
    "daegwallyeong": ("대관령", 37.6772, 128.7185),
    "wonju": ("원주", 37.3376, 127.9466),
    "seosan": ("서산", 36.7766, 126.4939),
    "pohang": ("포항", 36.0327, 129.3799),
    "yeonggwang": ("영광군", 35.2807, 126.4750),
}
# 참고 지점(미수집 13개) — 커버리지 시각 안내용
ASOS_REF = [("춘천", 37.9026, 127.7357), ("인천", 37.4777, 126.6249), ("수원", 37.2723, 126.9851),
            ("청주", 36.6392, 127.4407), ("안동", 36.5728, 128.7071), ("상주", 36.4108, 128.1572),
            ("대구", 35.8783, 128.6526), ("전주", 35.8408, 127.1191), ("부산", 35.1047, 129.0319),
            ("목포", 34.8169, 126.3815), ("고산", 33.2938, 126.1626), ("진주", 35.1639, 128.0399),
            ("순창군", 35.3744, 127.1377)]

# 지역별 발전량 비중(%) — 태양광 2025 / 풍력 2023 (TOP5 txt 최신 연도)
SOLAR_SHARE = {"전라남도": 35.0, "충청남도": 16.4, "전라북도": 9.8, "경상북도": 9.8, "강원도": 7.6}
WIND_SHARE = {"강원도": 34.0, "경상북도": 32.5, "전라남도": 22.4, "전라북도": 5.1, "경상남도": 5.0}

VAR_DEF = {  # 라벨: (forecast 컬럼 prefix, 단위, colorscale)
    "기온": ("temp_", "℃", "RdYlBu_r"),
    "일사": ("radiation_", "W/m²", "YlOrRd"),
    "풍속": ("wind_spd_10m_", "m/s", "GnBu"),
}


@st.cache_resource
def _geo():
    gj = json.loads(GEOJSON.read_text(encoding="utf-8"))
    cents = {}
    for f in gj["features"]:
        g = f["geometry"]
        if g["type"] == "Polygon":
            ring = max(g["coordinates"], key=len)          # 가장 큰 외곽 링
        else:                                              # MultiPolygon — 본토(최대) 폴리곤
            ring = max((poly[0] for poly in g["coordinates"]), key=len)
        arr = np.asarray(ring, dtype=float)
        cents[f["properties"]["name"]] = (float(arr[:, 1].mean()), float(arr[:, 0].mean()))
    return gj, cents


def _idw(lat: float, lon: float, station_vals: dict[str, float]) -> float:
    num = den = 0.0
    for stn, v in station_vals.items():
        if pd.isna(v):
            continue
        _, slat, slon = STATIONS[stn][0], STATIONS[stn][1], STATIONS[stn][2]
        d2 = (lat - slat) ** 2 + (lon - slon) ** 2
        if d2 < 1e-6:
            return float(v)
        num += v / d2
        den += 1.0 / d2
    return num / den if den else float("nan")


def build_weather_fig(var_label: str, station_vals: dict[str, float],
                      station_hover: dict[str, str]) -> go.Figure:
    """station_vals: {suffix: 변수값}. station_hover: {suffix: hover 텍스트(3변수 요약)}."""
    _, unit, colorscale = VAR_DEF[var_label]
    gj, cents = _geo()
    names = list(cents.keys())
    z = [_idw(*cents[n], station_vals) for n in names]

    fig = go.Figure()
    fig.add_trace(go.Choroplethmapbox(
        geojson=gj, featureidkey="properties.name", locations=names, z=z,
        colorscale=colorscale, marker_opacity=0.72, marker_line_width=0.6,
        marker_line_color="#888",
        colorbar=dict(title=f"{var_label}({unit})", thickness=12, x=1.0),
        hovertemplate="%{location}<br>" + var_label + " %{z:.1f}" + unit
                      + " (보간)<extra></extra>"))

    # 신재생 중요지역 원 — 태양광(주황, 좌측 오프셋) / 풍력(청록, 우측 오프셋)
    for share, color, name, dx in [(SOLAR_SHARE, "255,143,0", "태양광 비중(%)", -0.22),
                                   (WIND_SHARE, "0,137,123", "풍력 비중(%)", 0.22)]:
        mx = max(share.values())
        lats = [cents[p][0] for p in share]
        lons = [cents[p][1] + dx for p in share]
        fig.add_trace(go.Scattermapbox(
            lat=lats, lon=lons, mode="markers", name=name,
            marker=dict(size=[14 + 36 * v / mx for v in share.values()],
                        color=[f"rgba({color},{0.30 + 0.50 * v / mx:.2f})" for v in share.values()]),
            text=[f"{p} {name[:3]} {v:.1f}%" for p, v in share.items()],
            hoverinfo="text"))

    # 관측 지점 — 수집 5지점(파랑) + 참고 13지점(회색)
    fig.add_trace(go.Scattermapbox(
        lat=[STATIONS[s][1] for s in STATIONS], lon=[STATIONS[s][2] for s in STATIONS],
        mode="markers+text", name="수집 지점(5)",
        marker=dict(size=11, color="#0d47a1"),
        text=[STATIONS[s][0] for s in STATIONS], textposition="top right",
        textfont=dict(size=11, color="#0d47a1"),
        hovertext=[station_hover.get(s, "") for s in STATIONS], hoverinfo="text"))
    fig.add_trace(go.Scattermapbox(
        lat=[a[1] for a in ASOS_REF], lon=[a[2] for a in ASOS_REF],
        mode="markers", name="참고 지점(미수집)",
        marker=dict(size=6, color="#9e9e9e"),
        text=[a[0] for a in ASOS_REF], hoverinfo="text"))

    fig.update_layout(
        mapbox=dict(style="carto-positron", center=dict(lat=36.2, lon=127.8), zoom=5.7),
        height=640, margin=dict(t=10, b=10, l=10, r=10),
        legend=dict(orientation="h", y=0.01, x=0.01, bgcolor="rgba(255,255,255,0.7)"))
    return fig

# -*- coding: utf-8 -*-
"""8단계 공용 레이어 — DB 조회(읽기 전용)·KPX 실시간 수급·단가 환산·적재 현황."""
from pathlib import Path
import sys
import sqlite3

import pandas as pd
import streamlit as st
import plotly.graph_objects as go

ROOT = Path(__file__).resolve().parent.parent
CORE = ROOT / "1. data_fetcher_and_db" / "core"
DB = {
    "land": ROOT / "1. data_fetcher_and_db" / "data" / "input_data_land.db",
    "jeju": ROOT / "1. data_fetcher_and_db" / "data" / "input_data_jeju.db",
}
PRICE_CSV = ROOT / "7. land_gas_forecaster" / "model" / "tab" / "7c_monthly_price_cost.csv"

GJ_PER_TON = 55.0      # LNG 열량(GJ/ton), 7-C
TON_PER_MWH = 0.1521   # 발전량→송출량 변환계수, 7-C
CACHE_TTL = 600
STATIONS_LAND = ["daegwallyeong", "wonju", "seosan", "pohang", "yeonggwang"]

# 색·선 규약: 실측 = solid, 예측 = dot
COLOR = {"demand": "#1f77b4", "renew": "#2ca02c", "net_load": "#9467bd",
         "gas": "#e377c2", "ton": "#8c564b", "temp": "#d62728",
         "rad": "#ff7f0e", "wind": "#7f7f7f"}


# ---------------------------------------------------------------- 조회 레이어
@st.cache_data(ttl=CACHE_TTL)
def query(region: str, sql: str, params: tuple = ()) -> pd.DataFrame:
    con = sqlite3.connect(str(DB[region]))
    try:
        df = pd.read_sql_query(sql, con, params=params, parse_dates=["timestamp"])
    finally:
        con.close()
    return df


@st.cache_data(ttl=CACHE_TTL)
def land_forecast(start: str, end: str) -> pd.DataFrame:
    """전국 forecast — 체인 예측 + 기상(5지점 평균)."""
    weather = []
    for prefix, name in [("temp_", "temp"), ("radiation_", "rad"), ("wind_spd_10m_", "wind")]:
        cols = "+".join(f"{prefix}{s}" for s in STATIONS_LAND)
        weather.append(f"({cols})/5.0 AS {name}")
    sql = f"""
        SELECT timestamp,
               est_demand_land, est_market_renew_land, est_net_load_land,
               est_gas_gen_land, est_gas_sendout_ton_land,
               {', '.join(weather)}
        FROM forecast WHERE timestamp BETWEEN ? AND ? ORDER BY timestamp
    """
    return query("land", sql, (start, end))


@st.cache_data(ttl=CACHE_TTL)
def land_actual(start: str, end: str) -> pd.DataFrame:
    """전국 historical 실측. net_load 실측은 예측과 같은 기준(수요−시장신재생)으로 재구성."""
    sql = """
        SELECT timestamp, real_demand_land, renew_gen_total_kr, gen_gas_kr
        FROM historical WHERE timestamp BETWEEN ? AND ? ORDER BY timestamp
    """
    df = query("land", sql, (start, end))
    df["net_load_actual"] = df["real_demand_land"] - df["renew_gen_total_kr"]
    return df


# ---------------------------------------------------------------- KPX 실시간 수급
@st.cache_data(ttl=300, show_spinner="KPX 실시간 수급을 불러오는 중...")
def live_sukub_land(day: str) -> pd.DataFrame:
    """KPX sukub 당일 실시간 수급(표시 전용, DB에 쓰지 않음). 실패 시 빈 DF."""
    if str(CORE) not in sys.path:
        sys.path.insert(0, str(CORE))
    try:
        from api_fetchers_land import fetch_kpx_land
        df = fetch_kpx_land(day, day, progress=False)
        return df.reset_index() if not df.empty else pd.DataFrame()
    except Exception:
        return pd.DataFrame()


# ---------------------------------------------------------------- 단가 환산
@st.cache_data(ttl=CACHE_TTL)
def gas_tariff_by_month() -> pd.Series:
    """발전용 가스 단가(원/GJ), 월별(7-C 산출물). 범위 밖 월은 마지막 값."""
    px = pd.read_csv(PRICE_CSV)
    return px.set_index("ym")["tariff_gen_won_per_GJ"].dropna()


def gas_cost_won(ts: pd.Series, ton: pd.Series) -> pd.Series:
    tariff = gas_tariff_by_month()
    t = ts.dt.strftime("%Y-%m").map(tariff).fillna(tariff.iloc[-1])
    return ton * GJ_PER_TON * t


# ---------------------------------------------------------------- 적재 현황
COVERAGE = {
    "land": [
        ("forecast", "기상 예보(서산 기온)", "temp_seosan"),
        ("forecast", "수요 예측 — 5단계", "est_demand_land"),
        ("forecast", "신재생 예측 — 6단계", "est_market_renew_land"),
        ("forecast", "net_load 예측 — 6단계", "est_net_load_land"),
        ("forecast", "가스 발전 예측 — 7단계", "est_gas_gen_land"),
        ("forecast", "가스 송출량 예측 — 7단계", "est_gas_sendout_ton_land"),
        ("historical", "수요 실측(KPX)", "real_demand_land"),
        ("historical", "신재생 실측(KPX)", "renew_gen_total_kr"),
        ("historical", "가스 발전 실측(KPX)", "gen_gas_kr"),
        ("historical", "기상 관측(서산 일사)", "solar_rad_seosan"),
    ],
    "jeju": [
        ("forecast", "기상 예보(서부 기온)", "temp_west"),
        ("forecast", "수요 예측 D+1 — 2단계", "jeju_est_demand_new"),
        ("forecast", "net_load 예측 D+1 — 3단계", "est_net_load_jeju"),
        ("forecast", "net_load 예측 하이브리드 — 3단계", "est_net_load_jeju_lh"),
        ("forecast", "SMP D+1 — 4단계", "est_smp_jeju"),
        ("forecast", "SMP D+2 — 4단계", "est_smp_jeju_d2"),
        ("historical", "수요 실측(KPX)", "real_demand_jeju"),
        ("historical", "신재생 실측(KPX)", "real_renew_gen_jeju"),
        ("historical", "net_load 실측", "real_net_load_jeju"),
        ("historical", "실시간 SMP", "smp_jeju_rt"),
    ],
}


@st.cache_data(ttl=CACHE_TTL)
def coverage_table(region: str) -> pd.DataFrame:
    rows, now = [], pd.Timestamp.now()
    con = sqlite3.connect(str(DB[region]))
    try:
        have = {t: {r[1] for r in con.execute(f"PRAGMA table_info({t})")}
                for t in ("forecast", "historical")}
        for table, label, col in COVERAGE[region]:
            if col not in have[table]:
                rows.append([table, label, "—", "—", 0, None]); continue
            lo, hi, n = con.execute(
                f"SELECT MIN(timestamp), MAX(timestamp), COUNT({col}) "
                f"FROM {table} WHERE {col} IS NOT NULL").fetchone()
            lag = round((now - pd.Timestamp(hi)).total_seconds() / 3600, 1) if hi else None
            rows.append([table, label, (lo or "—")[:16], (hi or "—")[:16], n, lag])
    finally:
        con.close()
    return pd.DataFrame(rows, columns=["테이블", "항목", "시작", "마지막 적재", "행수", "경과(시간)"])


# ---------------------------------------------------------------- 차트 헬퍼
def make_fig(height: int = 420, ytitle: str = "MW") -> go.Figure:
    fig = go.Figure()
    fig.update_layout(height=height, margin=dict(t=30, b=10, l=10, r=10),
                      legend=dict(orientation="h", y=-0.15), yaxis_title=ytitle)
    return fig


def add_actual(fig: go.Figure, ts, y, name: str, color: str, **kw):
    fig.add_trace(go.Scatter(x=ts, y=y, name=name, line=dict(color=color, width=2), **kw))


def add_forecast(fig: go.Figure, ts, y, name: str, color: str, **kw):
    fig.add_trace(go.Scatter(x=ts, y=y, name=name, line=dict(color=color, dash="dot", width=2), **kw))

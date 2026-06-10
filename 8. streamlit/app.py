# -*- coding: utf-8 -*-
"""
8단계 — Streamlit 데모 (8-A: DB 조회 레이어 + Tab 2 전국 체인 대시보드)

명제: 신재생이 만든 잔여부하(net_load)를 가스 발전이 메운다.
체인: 5(수요) → 6(신재생) → 7(가스)의 사전 적재된 예측을 읽기 전용으로 표시한다.

실행:  streamlit run "8. streamlit/app.py"
G-15(PROJECT.md §7): 자체 서버 호스팅 / DB 직접 읽기 / 사전 적재 기본 / SMP 제외.
"""
from pathlib import Path
import sqlite3

import pandas as pd
import streamlit as st
import plotly.graph_objects as go
from plotly.subplots import make_subplots

ROOT = Path(__file__).resolve().parent.parent
DB_LAND = ROOT / "1. data_fetcher_and_db" / "data" / "input_data_land.db"
DB_JEJU = ROOT / "1. data_fetcher_and_db" / "data" / "input_data_jeju.db"
PRICE_CSV = ROOT / "7. land_gas_forecaster" / "model" / "tab" / "7c_monthly_price_cost.csv"

GJ_PER_TON = 55.0          # LNG 열량(GJ/ton), 7-C
TON_PER_MWH = 0.1521       # 발전량→송출량 변환계수, 7-C
STATIONS = ["daegwallyeong", "wonju", "seosan", "pohang", "yeonggwang"]

CACHE_TTL = 600  # DB 쿼리 캐시(초)

st.set_page_config(page_title="신재생→잔여부하→가스 브리핑", layout="wide")


# ---------------------------------------------------------------- DB 조회 레이어
@st.cache_data(ttl=CACHE_TTL)
def _query(db_path: str, sql: str, params: tuple = ()) -> pd.DataFrame:
    con = sqlite3.connect(db_path)
    try:
        df = pd.read_sql_query(sql, con, params=params, parse_dates=["timestamp"])
    finally:
        con.close()
    return df


@st.cache_data(ttl=CACHE_TTL)
def land_date_range() -> tuple[str, str]:
    """표시 가능 날짜 = est_demand_land 보유 범위(G-15 ④)."""
    df = _query(str(DB_LAND),
                "SELECT MIN(timestamp) AS lo, MAX(timestamp) AS hi "
                "FROM forecast WHERE est_demand_land IS NOT NULL")
    return str(df.loc[0, "lo"])[:10], str(df.loc[0, "hi"])[:10]


@st.cache_data(ttl=CACHE_TTL)
def load_land_forecast(start: str, end: str) -> pd.DataFrame:
    """forecast 테이블의 체인 예측 + 기상(5지점 평균)."""
    weather = []
    for prefix, name in [("temp_", "temp"), ("radiation_", "rad"), ("wind_spd_10m_", "wind")]:
        cols = "+".join(f"{prefix}{s}" for s in STATIONS)
        weather.append(f"({cols})/5.0 AS {name}")
    sql = f"""
        SELECT timestamp,
               est_demand_land, est_market_renew_land, est_net_load_land,
               est_solar_gen_land, est_wind_gen_land,
               est_gas_gen_land, est_gas_sendout_ton_land,
               {', '.join(weather)}
        FROM forecast
        WHERE timestamp BETWEEN ? AND ?
        ORDER BY timestamp
    """
    return _query(str(DB_LAND), sql, (start, end))


@st.cache_data(ttl=CACHE_TTL)
def load_land_actual(start: str, end: str) -> pd.DataFrame:
    """historical 실측. net_load 실측은 예측과 같은 기준(수요−시장신재생)으로 재구성."""
    sql = """
        SELECT timestamp, real_demand_land, renew_gen_total_kr, gen_gas_kr
        FROM historical
        WHERE timestamp BETWEEN ? AND ?
        ORDER BY timestamp
    """
    df = _query(str(DB_LAND), sql, (start, end))
    df["net_load_actual"] = df["real_demand_land"] - df["renew_gen_total_kr"]
    return df


@st.cache_data(ttl=CACHE_TTL)
def gas_tariff_by_month() -> pd.Series:
    """발전용 가스 단가(원/GJ), 월별. 범위 밖 월은 마지막 값 사용(7-C 산출물)."""
    px = pd.read_csv(PRICE_CSV)
    s = px.set_index("ym")["tariff_gen_won_per_GJ"].dropna()
    return s


def tariff_for(ts: pd.Series, tariff: pd.Series) -> pd.Series:
    ym = ts.dt.strftime("%Y-%m")
    return ym.map(tariff).fillna(tariff.iloc[-1])


# ---------------------------------------------------------------- 사이드바
st.sidebar.title("발전사업자 브리핑")
region = st.sidebar.radio("지역", ["전국", "제주"], horizontal=True)

lo, hi = land_date_range()
lo_d, hi_d = pd.Timestamp(lo), pd.Timestamp(hi)
origin = st.sidebar.date_input(
    "기준일 (origin)",
    value=(hi_d - pd.Timedelta(days=1)).date(),
    min_value=(lo_d - pd.Timedelta(days=1)).date(),
    max_value=(hi_d - pd.Timedelta(days=1)).date(),
    help="이 날 23:00에 예측을 발행했다고 보고, 다음 날(D+1)부터 보여줍니다.",
)
horizon = st.sidebar.slider("표시 지평 (D+1 ~ D+N)", 1, 7, 1)
st.sidebar.caption(
    "과거 구간은 매일 갱신된 D+1 예측(사전 적재 백필)입니다. "
    "기준일 고정 다지평 시연(실행 버튼)은 8-D에서 연결 예정."
)

win_start = (pd.Timestamp(origin) + pd.Timedelta(days=1)).strftime("%Y-%m-%d 00:00:00")
win_end = (pd.Timestamp(origin) + pd.Timedelta(days=horizon)).strftime("%Y-%m-%d 23:00:00")

# ---------------------------------------------------------------- 탭
tab1, tab2, tab3, tab4 = st.tabs(
    ["개요", "예측 대시보드", "모델 검증·정직성", "전국 확장·KOGAS"]
)

with tab1:
    st.subheader("명제: 신재생이 만든 잔여부하를 가스 발전이 메운다")
    st.markdown(
        "- **체인**: 수요 예측(5단계) − 신재생 예측(6단계) = **잔여부하(net_load)** → 가스 발전(7단계) → KOGAS 송출량(TON)·가스비 환산\n"
        "- 자세한 구조 다이어그램·데이터 귀속은 **8-B에서 채워질 예정**입니다."
    )

with tab3:
    st.info("모델 검증·정직성 탭은 8-C에서 구현 예정 (단계별 MAPE·대체효과 대비표).")

with tab4:
    st.info("전국 확장·KOGAS 탭은 8-C에서 구현 예정 (변환계수 0.1521 ton/MWh, 월 가스비 규모).")

# ---------------------------------------------------------------- Tab 2 핵심
with tab2:
    if region == "제주":
        st.info("제주 대시보드(수요·신재생·net_load)는 8-B에서 구현 예정입니다. "
                "지금은 전국을 선택해 주세요.")
        st.stop()

    fc = load_land_forecast(win_start, win_end)
    ac = load_land_actual(win_start, win_end)

    if fc.empty or fc["est_demand_land"].isna().all():
        st.warning("선택한 기간에 적재된 예측이 없습니다. 기준일을 데이터 보유 범위 안에서 골라 주세요.")
        st.stop()

    df = fc.merge(ac, on="timestamp", how="left")
    tariff = gas_tariff_by_month()
    df["gas_cost_won"] = df["est_gas_sendout_ton_land"] * GJ_PER_TON * tariff_for(df["timestamp"], tariff)

    # ---- brief_ai 카드 (8-D에서 Gemini 연결)
    st.markdown("#### AI 브리핑")
    st.info("brief_ai는 8-D에서 연결됩니다 (Gemini API, 같은 날짜·지역 24시간 캐시).")

    # ---- 핵심 지표
    has_actual = df["gen_gas_kr"].notna().any()
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("평균 수요(예측)", f"{df['est_demand_land'].mean():,.0f} MW")
    renew_share = df["est_market_renew_land"].sum() / df["est_demand_land"].sum() * 100
    c2.metric("신재생 비중(예측)", f"{renew_share:.1f} %")
    c3.metric("가스 발전(예측 합)", f"{df['est_gas_gen_land'].sum() / 1000:,.1f} GWh")
    c4.metric("가스 송출량(예측 합)", f"{df['est_gas_sendout_ton_land'].sum():,.0f} TON")
    c5.metric("가스비(환산)", f"{df['gas_cost_won'].sum() / 1e8:,.0f} 억원")

    # ---- 체인 차트 스택 (x축 공유)
    fig = make_subplots(
        rows=4, cols=1, shared_xaxes=True, vertical_spacing=0.04,
        specs=[[{"secondary_y": True}], [{}], [{}], [{"secondary_y": True}]],
        subplot_titles=(
            "기상 개황 (5지점 평균)",
            "수요 vs 신재생 (MW)",
            "잔여부하 net_load = 수요 − 신재생 (MW)",
            "가스 발전 (MW) · 송출량 (TON/h)",
        ),
    )
    ts = df["timestamp"]

    # (1) 기상
    fig.add_trace(go.Scatter(x=ts, y=df["temp"], name="기온(℃)", line=dict(color="#d62728")), row=1, col=1)
    fig.add_trace(go.Scatter(x=ts, y=df["rad"], name="일사", line=dict(color="#ff7f0e", dash="dot")),
                  row=1, col=1, secondary_y=True)
    fig.add_trace(go.Scatter(x=ts, y=df["wind"], name="풍속(m/s)", line=dict(color="#7f7f7f", dash="dash")), row=1, col=1)

    # (2) 수요 vs 신재생
    fig.add_trace(go.Scatter(x=ts, y=df["est_demand_land"], name="수요 예측", line=dict(color="#1f77b4", width=2)), row=2, col=1)
    fig.add_trace(go.Scatter(x=ts, y=df["real_demand_land"], name="수요 실측", line=dict(color="#1f77b4", dash="dot")), row=2, col=1)
    fig.add_trace(go.Scatter(x=ts, y=df["est_market_renew_land"], name="신재생 예측", line=dict(color="#2ca02c", width=2)), row=2, col=1)
    fig.add_trace(go.Scatter(x=ts, y=df["renew_gen_total_kr"], name="신재생 실측", line=dict(color="#2ca02c", dash="dot")), row=2, col=1)

    # (3) net_load
    fig.add_trace(go.Scatter(x=ts, y=df["est_net_load_land"], name="net_load 예측", line=dict(color="#9467bd", width=2)), row=3, col=1)
    fig.add_trace(go.Scatter(x=ts, y=df["net_load_actual"], name="net_load 실측", line=dict(color="#9467bd", dash="dot")), row=3, col=1)

    # (4) 가스
    fig.add_trace(go.Scatter(x=ts, y=df["est_gas_gen_land"], name="가스 발전 예측", line=dict(color="#e377c2", width=2)), row=4, col=1)
    fig.add_trace(go.Scatter(x=ts, y=df["gen_gas_kr"], name="가스 발전 실측", line=dict(color="#e377c2", dash="dot")), row=4, col=1)
    fig.add_trace(go.Scatter(x=ts, y=df["est_gas_sendout_ton_land"], name="송출량(TON/h)",
                             line=dict(color="#8c564b", dash="dash")), row=4, col=1, secondary_y=True)

    fig.update_layout(height=950, legend=dict(orientation="h", y=-0.05), margin=dict(t=40, b=10))
    st.plotly_chart(fig, width="stretch")

    if has_actual:
        mape = ((df["est_gas_gen_land"] - df["gen_gas_kr"]).abs() / df["gen_gas_kr"]).mean() * 100
        st.caption(f"표시 구간 가스 발전 MAPE {mape:.1f}% — 체인 전체(예보 입력) 검증치는 ~13% (7-A2-A). "
                   "실측 대비 오차를 숨기지 않습니다(§5.4).")
    else:
        st.caption("선택 구간에 아직 실측이 없어 예측만 표시합니다.")

    # ---- 시간대별 테이블
    st.markdown("#### 시간대별 수치")
    table = df[["timestamp", "est_demand_land", "est_market_renew_land", "est_net_load_land",
                "est_gas_gen_land", "est_gas_sendout_ton_land", "gas_cost_won",
                "real_demand_land", "gen_gas_kr"]].rename(columns={
        "est_demand_land": "수요 예측(MW)", "est_market_renew_land": "신재생 예측(MW)",
        "est_net_load_land": "net_load 예측(MW)", "est_gas_gen_land": "가스 예측(MW)",
        "est_gas_sendout_ton_land": "송출량(TON)", "gas_cost_won": "가스비(원)",
        "real_demand_land": "수요 실측(MW)", "gen_gas_kr": "가스 실측(MW)",
    })
    st.dataframe(table, width="stretch", hide_index=True,
                 column_config={"timestamp": st.column_config.DatetimeColumn("시각", format="MM-DD HH:mm")})

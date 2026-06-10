# -*- coding: utf-8 -*-
"""전국 페이지 — 종합(현황/기상개황/장지평 예측) · 수요 예측 · 데이터 현황."""
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as C

st.title("전국 — 신재생 → 잔여부하 → 가스 브리핑")
menu = st.sidebar.radio("메뉴", ["종합", "수요 예측", "데이터 현황"])

TODAY = pd.Timestamp.now().normalize()
ORIGIN = TODAY - pd.Timedelta(days=1)  # 어제 23:00 발행 가정(사전 적재)


def _day_bounds(d0: pd.Timestamp, d1: pd.Timestamp) -> tuple[str, str]:
    return d0.strftime("%Y-%m-%d 00:00:00"), d1.strftime("%Y-%m-%d 23:00:00")


# ================================================================ 종합
def render_status():
    s, e = _day_bounds(TODAY, TODAY)
    fc = C.land_forecast(s, e)
    if fc.empty or fc["est_gas_gen_land"].isna().all():
        st.warning("오늘 예측이 아직 적재되지 않았습니다. 사전 적재(서빙 5→6→7)를 먼저 실행해 주세요.")
        return

    # 상단 — 예상 일일 가스 송출량
    ton_day = fc["est_gas_sendout_ton_land"].sum()
    cost_day = C.gas_cost_won(fc["timestamp"], fc["est_gas_sendout_ton_land"]).sum()
    c1, c2, c3 = st.columns(3)
    c1.metric("오늘 예상 가스 송출량", f"{ton_day:,.0f} TON")
    c2.metric("가스 발전(예측 합)", f"{fc['est_gas_gen_land'].sum() / 1000:,.1f} GWh")
    c3.metric("가스비(환산)", f"{cost_day / 1e8:,.0f} 억원")

    # 수요 실측 — KPX sukub 실시간 우선, 없으면 historical
    btn_col, info_col = st.columns([1, 4])
    if btn_col.button("실시간 새로고침", help="KPX 수급(sukub) 당일 데이터를 다시 불러옵니다 (표시 전용)"):
        C.live_sukub_land.clear()
    live = C.live_sukub_land(TODAY.strftime("%Y-%m-%d"))
    if not live.empty and "real_demand_land" in live.columns:
        actual = live[["timestamp", "real_demand_land"]].dropna()
        src = "KPX sukub 실시간"
    else:
        actual = C.land_actual(s, e)[["timestamp", "real_demand_land"]].dropna()
        src = "DB historical (실시간 불러오기 실패 또는 데이터 없음)"
    actual = actual.assign(timestamp=pd.to_datetime(actual["timestamp"]))
    actual = actual[actual["timestamp"] >= TODAY]
    last = actual["timestamp"].max() if not actual.empty else None
    info_col.caption(f"수요 실측 출처: {src} · 마지막 실측 {last:%H:%M}" if last is not None
                     else f"수요 실측 출처: {src}")

    fig = C.make_fig(height=430)
    C.add_actual(fig, actual["timestamp"], actual["real_demand_land"],
                 "전력수요 실측 (MW)", C.COLOR["demand"])
    C.add_forecast(fig, fc["timestamp"], fc["est_gas_gen_land"],
                   "가스 발전 예측 (MW)", C.COLOR["gas"])
    fig.update_xaxes(range=[TODAY, TODAY + pd.Timedelta(hours=24)])
    st.plotly_chart(fig, width="stretch")

    st.markdown("##### AI 브리핑")
    st.info("brief_ai는 8-D에서 연결됩니다 (Gemini API, 같은 날짜·지역 24시간 캐시).")


def render_weather():
    s, e = _day_bounds(TODAY, TODAY + pd.Timedelta(days=1))
    fc = C.land_forecast(s, e)
    if fc.empty:
        st.warning("기상 예보가 없습니다.")
        return
    from plotly.subplots import make_subplots
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    fig.add_scatter(x=fc["timestamp"], y=fc["temp"], name="기온(℃)",
                    line=dict(color=C.COLOR["temp"]))
    fig.add_scatter(x=fc["timestamp"], y=fc["wind"], name="풍속(m/s)",
                    line=dict(color=C.COLOR["wind"], dash="dash"))
    fig.add_scatter(x=fc["timestamp"], y=fc["rad"], name="일사",
                    line=dict(color=C.COLOR["rad"], dash="dot"), secondary_y=True)
    fig.update_layout(height=400, margin=dict(t=30, b=10),
                      legend=dict(orientation="h", y=-0.15),
                      title="오늘~내일 · 5지점 평균 (대관령·원주·서산·포항·영광)")
    st.plotly_chart(fig, width="stretch")
    st.caption("간략 표기입니다 — 상세 디자인은 추후 확정 예정.")


def render_longhorizon():
    n = st.slider("표시 지평 (D+1 ~ D+N)", 1, 7, 7, key="lh_slider")
    s, e = _day_bounds(TODAY, ORIGIN + pd.Timedelta(days=n))
    fc = C.land_forecast(s, e)
    if fc.empty or fc["est_demand_land"].isna().all():
        st.warning("장지평 예측이 적재되지 않았습니다.")
        return
    ton = fc["est_gas_sendout_ton_land"].sum()
    cost = C.gas_cost_won(fc["timestamp"], fc["est_gas_sendout_ton_land"]).sum()
    c1, c2 = st.columns(2)
    c1.metric(f"D+1~D+{n} 가스 송출량(예측 합)", f"{ton:,.0f} TON")
    c2.metric("가스비(환산)", f"{cost / 1e8:,.0f} 억원")

    fig = C.make_fig(height=450)
    C.add_forecast(fig, fc["timestamp"], fc["est_demand_land"],
                   "전력수요 예측 (MW)", C.COLOR["demand"])
    C.add_forecast(fig, fc["timestamp"], fc["est_gas_gen_land"],
                   "가스 발전 예측 (MW)", C.COLOR["gas"])
    st.plotly_chart(fig, width="stretch")
    st.caption(f"발행 기준: {ORIGIN:%Y-%m-%d} 23:00 (사전 적재). "
               "D+3 이후 기상은 (월,시) 기후값 폴백이 섞일 수 있습니다.")


# ================================================================ 수요 예측
def render_forecast_menu():
    n = st.slider("지평 (D+1 ~ D+N)", 1, 7, 3, key="fc_slider",
                  help="사전 적재된 예측을 읽기만 하므로 지연 없이 전환됩니다.")
    s, e = _day_bounds(TODAY - pd.Timedelta(days=2), ORIGIN + pd.Timedelta(days=n))
    fc = C.land_forecast(s, e)
    ac = C.land_actual(s, e)
    df = fc.merge(ac, on="timestamp", how="left")
    if df.empty:
        st.warning("표시할 데이터가 없습니다.")
        return

    t1, t2, t3 = st.tabs(["전력수요 예측", "순 수요(net_load) 예측", "천연가스 수요 예측"])
    ts = df["timestamp"]

    with t1:
        fig = C.make_fig()
        C.add_actual(fig, ts, df["real_demand_land"], "수요 실측", C.COLOR["demand"])
        C.add_forecast(fig, ts, df["est_demand_land"], "수요 예측", C.COLOR["demand"])
        st.plotly_chart(fig, width="stretch")

    with t2:
        fig = C.make_fig()
        C.add_actual(fig, ts, df["net_load_actual"], "net_load 실측", C.COLOR["net_load"])
        C.add_forecast(fig, ts, df["est_net_load_land"], "net_load 예측", C.COLOR["net_load"])
        C.add_forecast(fig, ts, df["est_market_renew_land"], "신재생 예측(참고)", C.COLOR["renew"])
        st.plotly_chart(fig, width="stretch")
        st.caption("net_load = 수요 − 시장 신재생. 실측도 같은 기준으로 재구성해 비교합니다.")

    with t3:
        fut = df[df["gen_gas_kr"].isna()]  # 실측이 아직 없는 미래 구간
        ton = fut["est_gas_sendout_ton_land"].sum()
        cost = C.gas_cost_won(fut["timestamp"], fut["est_gas_sendout_ton_land"]).sum()
        c1, c2 = st.columns(2)
        c1.metric("미래 구간 송출량(예측 합)", f"{ton:,.0f} TON")
        c2.metric("가스비(환산)", f"{cost / 1e8:,.0f} 억원")
        fig = C.make_fig()
        C.add_actual(fig, ts, df["gen_gas_kr"], "가스 발전 실측 (MW)", C.COLOR["gas"])
        C.add_forecast(fig, ts, df["est_gas_gen_land"], "가스 발전 예측 (MW)", C.COLOR["gas"])
        C.add_forecast(fig, ts, df["est_gas_sendout_ton_land"], "송출량 예측 (TON/h)", C.COLOR["ton"])
        st.plotly_chart(fig, width="stretch")
        st.caption("송출량(TON) = 발전량(MWh) × 0.1521 (7-C 변환계수, 열효율 ~43%). "
                   "체인 검증 가스 MAPE ~13% (7-A2-A, ORACLE 10.8%).")

    overlap = df.dropna(subset=["gen_gas_kr", "est_gas_gen_land"])
    if not overlap.empty:
        mape = ((overlap["est_gas_gen_land"] - overlap["gen_gas_kr"]).abs()
                / overlap["gen_gas_kr"]).mean() * 100
        st.caption(f"최근 실측 겹침 구간({len(overlap)}h) 가스 발전 MAPE {mape:.1f}% — "
                   "실측 대비 오차를 숨기지 않습니다(§5.4).")


# ================================================================ 데이터 현황
def render_data_status():
    st.subheader("데이터 적재 현황 (전국 DB)")
    st.dataframe(C.coverage_table("land"), width="stretch", hide_index=True)
    st.caption("수집은 crontab 백그라운드에서만 갱신됩니다(API 한도 보호 — 사용자 트리거 없음). "
               "예측(est_*)은 서빙 5→6→7 사전 적재분입니다.")


if menu == "종합":
    tab_now, tab_wx, tab_lh = st.tabs(["현황", "기상개황", "장지평 예측"])
    with tab_now:
        render_status()
    with tab_wx:
        render_weather()
    with tab_lh:
        render_longhorizon()
elif menu == "수요 예측":
    render_forecast_menu()
else:
    render_data_status()

# -*- coding: utf-8 -*-
"""제주 페이지 — 종합(수요·신재생·net_load·SMP 한 화면) · 데이터 현황.

명제: 신재생이 만든 잔여부하(net_load)가 SMP를 흔든다 — 2(수요)→3(신재생)→4(SMP) 서빙 체인.
예측은 사전 적재된 지평 아카이브(est_horizon_jeju·est_smp_horizon_jeju)에서 읽기만 한다.
"""
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as C

C.page_header(
    "JEJU · DAILY BRIEFING", "제주 발전 브리핑",
    "신재생이 만든 잔여부하가 SMP를 흔든다 — 2→3→4 서빙 체인의 사전 적재 예측",
    [("수요", C.COLOR["demand"]), ("신재생", C.COLOR["renew"]),
     ("net_load", C.COLOR["net_load"]), ("SMP", C.COLOR["smp"])])
menu = st.sidebar.radio("메뉴", ["종합", "데이터 현황"])


# ⚙️ 선택형 시리즈 — (라벨, 컬럼, 종류, 색, 기본 선택). 태양광·풍력은 실측·예측 둘 다 선택 가능.
JEJU_SERIES = [
    ("전력수요 실측", "real_demand_jeju", "act", C.COLOR["demand"], True),
    ("전력수요 예측", "est_demand_jeju", "est", C.COLOR["demand"], True),
    ("신재생 실측", "real_renew_gen_jeju", "act", C.COLOR["renew"], True),
    ("신재생 예측", "est_renew_gen_jeju", "est", C.COLOR["renew"], True),
    ("net_load 실측", "real_net_load_jeju", "act", C.COLOR["net_load"], True),
    ("net_load 예측", "est_net_load_jeju", "est", C.COLOR["net_load"], True),
    ("태양광 실측", "real_solar_gen_jeju", "act", C.COLOR["rad"], False),
    ("태양광 예측", "est_solar_gen_jeju", "est", C.COLOR["rad"], False),
    ("풍력 실측", "real_wind_gen_jeju", "act", C.COLOR["wind"], False),
    ("풍력 예측", "est_wind_gen_jeju", "est", C.COLOR["wind"], False),
]


def render_mw(df: pd.DataFrame, chosen: dict, show_da: bool, day: pd.Timestamp, k: int):
    """수요·신재생·net_load 비교(MW) — D+1~D+k를 한 화면. x축은 지평만큼 넓어진다(지평 D+k → k일)."""
    cd, tmpl = C.hz_hover(df)
    ts = df["timestamp"]
    fig = C.make_fig(height=440)
    for label, col, kind, color, _ in JEJU_SERIES:
        if not chosen[label]:
            continue
        if kind == "act":
            C.add_actual(fig, ts, df[col], f"{label} (MW)", color)
        else:
            C.add_forecast(fig, ts, df[col], f"{label} (MW)", color,
                           customdata=cd, hovertemplate=tmpl)
    if show_da:
        fig.add_scatter(x=ts, y=df["jeju_est_demand_da"], name="KPX 수요예측(DA) (MW)",
                        line=dict(color="#17becf", dash="dash", width=2),
                        hovertemplate="%{x|%m-%d %H시} · %{y:,.0f} MW<br>"
                        "KPX 하루전 발표<extra>%{fullData.name}</extra>")
    # x축은 지평만큼(= k일) 펼친다. 더 좁게 보려면 plotly 확대/드래그 사용.
    fig.update_xaxes(range=[day, day + pd.Timedelta(days=k)])
    st.plotly_chart(fig, width="stretch")


def render_smp(smp: pd.DataFrame, day: pd.Timestamp):
    """SMP 검증(원/kWh) — D+2 예측(이틀 전 발행) vs 하루전 SMP(KPX 발표). x축 24h 고정.

    D+1은 하루전 발표 SMP를 그대로 쓰므로(검증 의미 없음), 우리 모델의 진짜 산출인 D+2(이틀 전 예측)를
    그 날 하루 전 KPX가 발표한 SMP와 비교한다. 실시간 SMP 수집이 끊겨 발표 SMP를 기준값으로 쓴다.
    """
    ts = smp["timestamp"]
    if smp["est_smp"].isna().all() and smp["smp_jeju_da"].isna().all():
        st.caption("이 날짜의 D+2 예측·하루전 SMP가 없습니다 (이틀 전 발행본·발표 SMP 필요).")
        return
    m = C.error_metrics(smp["est_smp"], smp["smp_jeju_da"])
    if m:
        st.markdown(f"**D+2 예측 vs 하루전 SMP** — MAE **{m['mae']:,.1f}** 원/kWh · "
                    f"bias **{m['bias']:+.1f}%** · 표본 {m['n']}시간")
    else:
        st.caption("D+2 예측이 없어 비교 불가 (이틀 전 발행본 누락 — 발행본 구멍).")
    fig = C.make_fig(height=340, ytitle="SMP (원/kWh)")
    C.add_actual(fig, ts, smp["smp_jeju_da"], "하루전 SMP(KPX 발표)", "#94a3b8")
    fig.add_scatter(x=ts, y=smp["est_smp"], name="D+2 예측 (이틀 전 발행)", mode="lines",
                    line=dict(color=C.COLOR["smp"], dash="dot", width=2.5),
                    hovertemplate="%{x|%m-%d %H시} · %{y:,.1f} 원/kWh<extra>%{fullData.name}</extra>")
    dz = smp[smp["smp_danger"] == 1]
    if not dz.empty:
        fig.add_scatter(x=dz["timestamp"], y=dz["est_smp"], mode="markers", name="음수가격 경보(D+2)",
                        marker=dict(color="#dc2626", size=11, symbol="triangle-down",
                                    line=dict(width=1, color="#fff")),
                        hovertemplate="%{x|%m-%d %H시} · 음수가격 경보<extra></extra>")
    fig.update_xaxes(range=[day, day + pd.Timedelta(days=1)])   # 무조건 24시간(선택일)
    st.plotly_chart(fig, width="stretch")


def render_overview():
    """제주 종합 — 수요·신재생·net_load(D+1~D+k) + SMP 검증 24h(D+2 예측 vs 하루전 SMP, expander)."""
    day, _, cap = C.day_navigator("jeju_ov")
    h_lo, h_hi = C.jeju_horizon_range()
    # 컨트롤 묶음: …실시간 새로고침 | 설정 | 슬라이더 (네비게이터 끝 칸을 둘로 나눔)
    c_set, c_sld = cap.columns([1, 2.4], vertical_alignment="center")
    with c_set.popover("설정", help="표시 데이터 설정", width="stretch"):
        chosen = {label: st.checkbox(label, value=default, key=f"jmw_{col}")
                  for label, col, _, _, default in JEJU_SERIES}
        show_da = st.checkbox("KPX 수요예측(DA)", value=True, key="jmw_da")
    k = c_sld.slider(f"지평 D+1~D+{h_hi}", h_lo, h_hi, 1, key="jeju_hzk", width="stretch",
                     help="선택일 전날 발행한 예보로 D+1(선택일)부터 며칠 앞까지 볼지 고릅니다. "
                          "지평이 길수록 화면도 그만큼 넓어집니다. D+1은 KPX 하루전 수요예측과 비교됩니다.")

    end = day + pd.Timedelta(days=k - 1)
    df = C.jeju_range_compare(day, end, mode="latest")
    if df["est_demand_jeju"].isna().all() and df["real_demand_jeju"].isna().all():
        lo, hi = C.jeju_date_range()
        st.warning(f"선택한 날짜의 예측이 지평 아카이브(est_horizon_jeju)에 없습니다. "
                   f"적재 범위: **{lo} ~ {hi}**.")
        return
    st.caption(f"표시 기준: {day:%Y-%m-%d}부터 D+1~D+{k} · 최근 발행 예보 · "
               "실측 ━ / 예측 ··· / KPX 하루전 ╌")

    # 차트 ① — 수요·신재생·net_load (D+1~D+k, x축이 지평만큼 넓어짐)
    render_mw(df, chosen, show_da, day, k)

    # SMP 검증 프레임(선택일 24h) — D+2 예측(이틀 전 발행, horizon_d=2) + 하루전 SMP(KPX). 지표·expander 공용.
    smp = C.jeju_smp_frame(day, day, mode="fixed", value=2)

    # 지표 4개 — 차트 ① 아래. 모두 선택일 기준.
    d1 = df[df["timestamp"].dt.normalize() == day]
    smp_mean = smp["smp_jeju_da"].mean()
    n_danger = int((smp["smp_danger"] == 1).sum())
    nl_min = d1["est_net_load_jeju"].min()
    pen = d1["est_renew_gen_jeju"] / d1["est_demand_jeju"] * 100
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("SMP 일 평균(하루전 발표)", "—" if pd.isna(smp_mean) else f"{smp_mean:,.1f} 원/kWh")
    c2.metric("음수가격 경보(D+2 예측)", f"{n_danger} 시간")
    c3.metric("최저 net_load(예측)", "—" if pd.isna(nl_min) else f"{nl_min:,.0f} MW")
    c4.metric("신재생 최대 침투율(예측)", "—" if pen.isna().all() else f"{pen.max():.0f} %",
              help="신재생 발전 예측 ÷ 전력수요 예측의 선택일 최대치")

    # 차트 ② — SMP 검증(펼쳐 보기). D+1=발표값 그대로라 검증 의미 없음 → 우리 모델 산출 D+2로 검증. 선택일 24h.
    with st.expander("SMP 검증 — D+2 예측 vs 하루전 SMP(KPX) (선택일 24시간)"):
        render_smp(smp, day)
        st.caption("우리 SMP 모델의 진짜 산출은 **D+2(이틀 전 예측)** 입니다 — D+1은 하루전 발표 SMP를 그대로 쓰기 "
                   "때문입니다(회귀로 못 이김이 검증됨). 그래서 **그 날을 이틀 전에 예측한 값(빨강)** 을, **하루 전 KPX가 "
                   "발표한 SMP(회색)** 와 비교합니다 — 예: 오늘이 22일이면 20일에 예측한 D+2 vs 21일 발표 SMP. "
                   "실시간 SMP 수집이 끊겨 발표 SMP를 기준값으로 씁니다. ▽ = D+2 음수가격 경보.")


if menu == "종합":
    render_overview()
else:
    st.subheader("데이터 적재 현황 (제주 DB)")
    st.dataframe(C.coverage_table("jeju"), width="stretch", hide_index=True)
    st.caption("수집은 crontab 백그라운드에서만 갱신됩니다(API 한도 보호 — 사용자 트리거 없음). "
               "예측 정본 = est_horizon_jeju(2·3)·est_smp_horizon_jeju(4) · 기상 정본 = forecast_horizon.")

# -*- coding: utf-8 -*-
"""제주 페이지 — 종합(수요·신재생·순 부하·SMP) · 검증(모델별 지평 정확도) · 데이터 현황."""
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as C

C.page_header(
    "GASCAST · 제주", "국가 가스수급 예측 플랫폼", "",
    [("수요", C.COLOR["demand"]), ("신재생", C.COLOR["renew"]),
     ("순 부하", C.COLOR["net_load"]), ("SMP", C.COLOR["smp"])])
menu = st.sidebar.radio("메뉴", ["종합", "검증", "데이터 현황"])
TODAY = pd.Timestamp.now().normalize()


# 지표 카드 공용 스타일 — 라벨·값·보조줄 전부 가운데 정렬 + delta 화살표·배경 제거(담백하게).
# emotion 기본 스타일을 !important로 덮음. 종합·검증 카드에서 공용 주입.
_METRIC_CSS = """<style>
[data-testid="stMetric"]{ text-align:center !important; }
[data-testid="stMetric"] [data-testid="stMarkdownContainer"],
[data-testid="stMetric"] [data-testid="stMarkdownContainer"] p{
    text-align:center !important; width:100% !important; }
/* 라벨은 기본 display:grid라 justify-content가 안 먹음 → flex로 바꿔 가운데 정렬 */
[data-testid="stMetricLabel"]{ display:flex !important; justify-content:center !important; width:100% !important; }
[data-testid="stMetricValue"]{ justify-content:center !important; }
/* delta(보조줄)도 라벨처럼 flex+width 100% 줘야 가운데로 옴 */
[data-testid="stMetricDelta"]{ display:flex !important; justify-content:center !important;
    width:100% !important; background:none !important; padding:0 !important; }
[data-testid="stMetricDelta"] svg{ display:none !important; }
</style>"""


def inject_metric_style():
    st.markdown(_METRIC_CSS, unsafe_allow_html=True)


# ⚙️ 선택형 시리즈 — (라벨, 컬럼, 종류, 색, 기본 선택). 태양광·풍력은 실측·예측 둘 다 선택 가능.
JEJU_SERIES = [
    ("전력수요 실측", "real_demand_jeju", "act", C.COLOR["demand"], True),
    ("전력수요 예측", "est_demand_jeju", "est", C.COLOR["demand"], True),
    ("신재생 실측", "real_renew_gen_jeju", "act", C.COLOR["renew"], True),
    ("신재생 예측", "est_renew_gen_jeju", "est", C.COLOR["renew"], True),
    ("순 부하 실측", "real_net_load_jeju", "act", C.COLOR["net_load"], True),
    ("순 부하 예측", "est_net_load_jeju", "est", C.COLOR["net_load"], True),
    ("태양광 실측", "real_solar_gen_jeju", "act", C.COLOR["rad"], False),
    ("태양광 예측", "est_solar_gen_jeju", "est", C.COLOR["rad"], False),
    ("풍력 실측", "real_wind_gen_jeju", "act", C.COLOR["wind"], False),
    ("풍력 예측", "est_wind_gen_jeju", "est", C.COLOR["wind"], False),
]


def render_mw(df: pd.DataFrame, chosen: dict, show_da: bool, day: pd.Timestamp, k: int):
    """수요·신재생·순 부하 비교(MW) — D+1~D+k를 한 화면. x축은 지평만큼 넓어진다(지평 D+k → k일)."""
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
                        line=dict(color="#17becf", dash="dash", width=2,
                                  shape="spline", smoothing=C.LINE_SMOOTHING),
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
                    line=dict(color=C.COLOR["smp"], dash="dot", width=2.5,
                              shape="spline", smoothing=C.LINE_SMOOTHING),
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
    """제주 종합 — 수요·신재생·순 부하(D+1~D+k) + SMP 검증 24h(D+2 예측 vs 하루전 SMP, expander)."""
    day, _, cap = C.day_navigator("jeju_ov")
    h_lo, h_hi = C.jeju_horizon_range()
    # 컨트롤 묶음: …실시간 새로고침 | 설정 | 슬라이더 (네비게이터 끝 칸을 둘로 나눔)
    c_set, c_sld = cap.columns([0.6, 2.4], vertical_alignment="center")
    with c_set.popover("설정", help="표시 데이터 설정", width="stretch"):
        chosen = {label: st.checkbox(label, value=default, key=f"jmw_{col}")
                  for label, col, _, _, default in JEJU_SERIES}
        show_da = st.checkbox("KPX 수요예측(DA)", value=True, key="jmw_da")
    k = c_sld.slider(f"지평 D+1~D+{h_hi}", h_lo, h_hi, 1, key="jeju_hzk", width="stretch",
                     help="선택일 기준 예측 길이(지평)를 선택합니다.")
    end = day + pd.Timedelta(days=k - 1)
    df = C.jeju_range_compare(day, end, mode="latest")
    if df["est_demand_jeju"].isna().all() and df["real_demand_jeju"].isna().all():
        lo, hi = C.jeju_date_range()
        st.warning(f"선택한 날짜의 예측이 아직 없습니다. 예측 보유 범위: **{lo} ~ {hi}**.")
        return
    # 차트 ① — 수요·신재생·순 부하 (D+1~D+k, x축이 지평만큼 넓어짐)
    render_mw(df, chosen, show_da, day, k)

    # 지표 5개 — 차트 ①과 같은 표시 구간(D+1~D+k) 전체 기준. 보조줄 = 최대/최소가 '발생한 시점'.
    sc, wc = C.jeju_renew_capacity()
    nl = df["est_net_load_jeju"]
    su, wu = df["est_solar_util_jeju"], df["est_wind_util_jeju"]
    comb = (df["est_solar_gen_jeju"] + df["est_wind_gen_jeju"]) / (sc + wc) * 100
    ts_col = df["timestamp"]

    def _when(series: pd.Series, how: str):
        """series 최대/최소가 발생한 시점 'MM-DD HH시' (없으면 None)."""
        s = series.dropna()
        if s.empty:
            return None
        i = s.idxmax() if how == "max" else s.idxmin()
        return f"{ts_col.loc[i]:%m-%d %H시}"

    # 지표 카드: 라벨·값·보조줄 전부 가운데 정렬(공용 스타일).
    inject_metric_style()
    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("최대 순 부하(예측)", "—" if nl.isna().all() else f"{nl.max():,.0f} MW",
              _when(nl, "max"), delta_color="off")
    m2.metric("최저 순 부하(예측)", "—" if nl.isna().all() else f"{nl.min():,.0f} MW",
              _when(nl, "min"), delta_color="off")
    m3.metric("신재생 최대 이용률", "—" if comb.isna().all() else f"{comb.max():.0f} %",
              _when(comb, "max"), delta_color="off",
              help="태양광+풍력 합산 이용률(발전 예측 ÷ 설비용량)의 표시 구간 최대치")
    m4.metric("태양광 최대 이용률", "—" if su.isna().all() else f"{su.max() * 100:.0f} %",
              _when(su, "max"), delta_color="off")
    m5.metric("풍력 최대 이용률", "—" if wu.isna().all() else f"{wu.max() * 100:.0f} %",
              _when(wu, "max"), delta_color="off")

    # 차트 ② — SMP 검증(펼쳐 보기). D+1=발표값 그대로라 검증 의미 없음 → 모델 산출 D+2로 검증. 선택일 24h.
    smp = C.jeju_smp_frame(day, day, mode="fixed", value=2)
    with st.expander("SMP 검증 — D+2 예측 vs 하루전 SMP(KPX) (선택일 24시간)"):
        render_smp(smp, day)
        st.caption("SMP 모델의 실제 산출은 **D+2(이틀 전 예측, 빨강)** 이며, "
                   "**하루 전 KPX가 발표한 SMP(회색)** 와 비교합니다. ▽ = 음수가격 경보.")


# 검증 차트 — 모델별 색(실측·예측 공용). 수요=파랑·순 부하=보라·태양광=주황·풍력=회색.
ACC_COLORS = {"수요": C.COLOR["demand"], "순 부하": C.COLOR["net_load"],
              "태양광": C.COLOR["rad"], "풍력": C.COLOR["wind"]}
VAL_PERIODS = {"7일": 7, "14일": 14, "한달": 30, "3개월": 92, "전체": None, "직접 설정": "custom"}


def _period_control(prefix: str):
    """검증기간 컨트롤(프리셋+직접설정) → (start, end) 날짜 문자열. '직접 설정' 미완료면 None."""
    psel = st.segmented_control("검증기간 (실측 대상일)", list(VAL_PERIODS),
                                default="한달", key=f"{prefix}_p") or "한달"
    mode = VAL_PERIODS[psel]
    if mode == "custom":
        lo, hi = C.jeju_date_range()
        lo_d, hi_d = pd.Timestamp(lo).date(), pd.Timestamp(hi).date()
        rng = st.date_input("대상일 범위", value=(lo_d, hi_d),
                            min_value=lo_d, max_value=hi_d, key=f"{prefix}_c")
        if isinstance(rng, (tuple, list)) and len(rng) == 2:
            return rng[0].strftime("%Y-%m-%d"), rng[1].strftime("%Y-%m-%d")
        st.caption("시작·종료일을 모두 선택하세요.")
        return None
    if mode is None:                         # '전체' = 적재 시작일부터
        return C.jeju_date_range()[0], None
    return (TODAY - pd.Timedelta(days=mode)).strftime("%Y-%m-%d"), None


def render_daily_trend():
    """① 일별 정확도 추이 — 검증기간 + 지평. x=날짜, y=오차율(%). 특정일 급등=그 날 기상 급변 신호."""
    h_lo, h_hi = C.jeju_horizon_range()
    c1, c2 = st.columns([3, 1], vertical_alignment="bottom")
    with c1:
        pr = _period_control("jtrend")
    k = c2.selectbox("지평", list(range(h_lo, h_hi + 1)),
                     format_func=lambda d: f"D+{d}", key="jtrend_hz")
    if pr is None:
        return
    start, end = pr

    # 선택 지평 카드 — 검증기간 전체에서 D+k 정확도(4개 모델 한눈).
    acc_h = C.jeju_horizon_accuracy(start, end)
    hz_lbl = f"D+{k}"
    if not acc_h.empty and hz_lbl in acc_h.index:
        inject_metric_style()
        row = acc_h.loc[hz_lbl]
        st.markdown(f"**{hz_lbl} 정확도** — 검증기간 전체 기준")
        cards = st.columns(4)
        CARD = [("수요", "수요", "MAPE"), ("순 부하", "순 부하", "nMAE"),
                ("태양광", "태양광", "설비용량 nMAE"), ("풍력", "풍력", "설비용량 nMAE")]
        for col, (title, key, kind) in zip(cards, CARD):
            v = row[key] if pd.notna(row[key]) else None
            col.metric(title, "—" if v is None else f"{v:.1f} %", kind, delta_color="off")

    acc = C.jeju_daily_accuracy(start, end, k)
    if acc.empty:
        st.caption("이 기간·지평에 집계할 데이터가 없습니다.")
        return
    st.markdown(f"**일별 추이** — D+{k}")
    fig = C.make_fig(height=400, ytitle="오차율 (%)")
    for name in C.JEJU_ACC_MODELS:
        fig.add_scatter(x=acc.index, y=acc[name], name=name, mode="lines+markers",
                        line=dict(color=ACC_COLORS[name], width=2.2), marker=dict(size=5),
                        connectgaps=False,
                        hovertemplate="%{x|%m-%d} · %{y:.1f}%<extra>" + name + "</extra>")
    st.plotly_chart(fig, width="stretch")
    st.caption(f"D+{k}(각 날짜를 {k}일 전에 예측) 기준 일별 오차율 · 수요=MAPE, 순 부하=평균 대비 nMAE, "
               "태양광·풍력=설비용량 기준 nMAE · 값이 갑자기 솟은 날 = 그 날 기상이 급변(비·구름 등)해 "
               "예측이 빗나간 날로 읽습니다.")


def render_horizon_curve():
    """② 지평별 성능 — 검증기간만 선택. x=지평(며칠 전 예측), y=오차율(%). 표는 expander."""
    pr = _period_control("jhz")
    if pr is None:
        return
    start, end = pr
    acc = C.jeju_horizon_accuracy(start, end)
    if acc.empty:
        st.caption("이 기간에 집계할 데이터가 없습니다.")
        return
    hz_num = [int(s[2:]) for s in acc.index]          # "D+3" → 3
    fig = C.make_fig(height=400, ytitle="오차율 (%)")
    for name in C.JEJU_ACC_MODELS:
        fig.add_scatter(x=hz_num, y=acc[name], name=name, mode="lines+markers",
                        line=dict(color=ACC_COLORS[name], width=2.2), marker=dict(size=6),
                        hovertemplate="D+%{x} · %{y:.1f}%<extra>" + name + "</extra>")
    fig.update_xaxes(title="지평 (며칠 전에 예측했는지)", tickmode="array",
                     tickvals=hz_num, ticktext=list(acc.index))
    st.plotly_chart(fig, width="stretch")
    st.caption("왼→오로 갈수록(지평이 길수록) 오차가 커지는 추세 = 멀리서 예측할수록 어렵다는 뜻 · "
               "수요=MAPE, 순 부하=평균 대비 nMAE, 태양광·풍력=설비용량 기준 nMAE.")
    with st.expander("정확한 수치 표로 보기"):
        st.dataframe(acc, width="stretch")


def render_date_series():
    """③ 지정일 예측 시계열 — 지정일 + 지평 n. n일 전 예측(점선) vs 실측(실선), 4계열 동시."""
    h_lo, h_hi = C.jeju_horizon_range()
    lo, hi = C.jeju_date_range()
    lo_d, hi_d = pd.Timestamp(lo).date(), pd.Timestamp(hi).date()
    default_day = min(hi_d, (TODAY - pd.Timedelta(days=1)).date())
    c1, c2 = st.columns([3, 1], vertical_alignment="bottom")
    day = c1.date_input("지정일", value=default_day, min_value=lo_d, max_value=hi_d, key="jds_day")
    n = c2.selectbox("지평", list(range(h_lo, h_hi + 1)),
                     format_func=lambda d: f"D+{d} ({d}일 전 예측)", key="jds_hz")
    day = pd.Timestamp(day)
    df = C.jeju_range_compare(day, day, use_live=False, mode="fixed", value=n)
    if df["real_demand_jeju"].isna().all() and df["est_demand_jeju"].isna().all():
        st.caption("이 날짜의 예측·실측이 모두 없습니다.")
        return
    no_fc = df["est_demand_jeju"].isna().all()
    ts = df["timestamp"]
    cd, tmpl = C.hz_hover(df)
    fig = C.make_fig(height=440)
    SER = [("수요", "real_demand_jeju", "est_demand_jeju", C.COLOR["demand"]),
           ("신재생", "real_renew_gen_jeju", "est_renew_gen_jeju", C.COLOR["renew"]),
           ("태양광", "real_solar_gen_jeju", "est_solar_gen_jeju", C.COLOR["rad"]),
           ("풍력", "real_wind_gen_jeju", "est_wind_gen_jeju", C.COLOR["wind"])]
    for name, ac, ec, color in SER:
        C.add_actual(fig, ts, df[ac], f"{name} 실측", color)
        C.add_forecast(fig, ts, df[ec], f"{name} 예측", color, customdata=cd, hovertemplate=tmpl)
    fig.update_xaxes(range=[day, day + pd.Timedelta(days=1)])    # 선택일 24시간
    st.plotly_chart(fig, width="stretch")
    if no_fc:
        st.caption(f"⚠ {day:%Y-%m-%d}을 {n}일 전(D+{n})에 예측한 발행본이 없어 실측만 표시됩니다(발행본 구멍).")
    st.caption(f"{day:%Y-%m-%d}을 **{n}일 전(D+{n})에 예측**한 값(점선) vs 실측(실선) · "
               "수요·신재생·태양광·풍력 동시 표시 · 실측이 아직 없는 미래일이면 점선만 보입니다.")


def render_validation():
    """제주 검증 — 모델 정확도 시각화 3종(일별 추이·지평별 성능·지정일 시계열). SMP는 제외(종합에서 따로)."""
    st.subheader("모델 정확도 검증 (제주)")
    st.caption("수요=MAPE · 순 부하=평균 대비 nMAE · 태양광·풍력=설비용량 기준 nMAE(MAE÷설비용량) · "
               "값이 낮을수록 정확 · 검증기간 = 실측이 있는 대상일 기준.")
    t1, t2, t3 = st.tabs(["① 일별 정확도 추이", "② 지평별 성능", "③ 지정일 예측 시계열"])
    with t1:
        render_daily_trend()
    with t2:
        render_horizon_curve()
    with t3:
        render_date_series()


def render_data_status():
    """데이터 현황 — 주요 항목 × 날짜 일별 수집률 히트맵(흰 0% → 초록 100%)."""
    import plotly.graph_objects as go

    st.subheader("데이터 현황 (제주)")
    heat = C.jeju_coverage_daily()
    cols, labels = list(heat.columns), list(heat.index)
    is_lh = {lab: lh for lab, _, _, lh in C.JEJU_COVERAGE_ITEMS}   # 장지평(예보)=초록 / 그 외=파랑
    cov = heat.values                                              # 실제 수집률(0~1)
    # 부호로 색 구분: 장지평(예보)=+수집률(초록), 그 외=−수집률(파랑). 0=빈칸(연회색).
    signed = cov.copy()
    for i, lab in enumerate(labels):
        if not is_lh.get(lab, False):
            signed[i] = -cov[i]
    fig = go.Figure(go.Heatmap(
        z=signed, x=cols, y=labels, customdata=cov, xgap=1, ygap=2,
        colorscale=[[0.0, "#1d6fb8"], [0.5, "#f1f5f9"], [1.0, "#059669"]], zmin=-1, zmax=1,
        hovertemplate="%{y}<br>%{x} · 수집률 %{customdata:.0%}<extra></extra>", showscale=False))
    fig.update_layout(height=max(360, 34 * len(labels) + 90),
                      margin=dict(t=10, b=10, l=10, r=10),
                      yaxis=dict(autorange="reversed", tickfont=dict(size=12)),
                      # type='category' 필수 — 안 하면 'MM-DD'를 날짜로 오인해 월 단위로 뭉갬
                      xaxis=dict(type="category", tickfont=dict(size=10), tickangle=-90))
    today_lbl = pd.Timestamp.now().strftime("%m-%d")
    if today_lbl in cols:
        fig.add_vline(x=today_lbl, line_dash="dot", line_color="#dc2626")
    st.plotly_chart(fig, width="stretch")
    st.caption("🟩 초록 = 예보(미래까지 채워짐) · 🟦 파랑 = 실측(오늘까지 채워짐) · "
               "진할수록 그날 수집률이 높음 · 빨간 점선 = 오늘.")
    C.help_expander(
        "**초록(예보 계열)** — 수요·순 부하·태양광·풍력 예측과 기상 예보는 D+3 이후 미래까지 "
        "미리 채워집니다.\n\n"
        "**파랑(실측 계열)** — 실측값과 하루전 SMP는 오늘까지만 채워집니다. "
        "SMP 예측은 D+1·D+2까지만 발행됩니다.\n\n"
        "데이터는 서버가 매일 정해진 시각에 자동 수집합니다.")
    with st.expander("항목별 최신 현황 요약"):
        st.dataframe(C.coverage_table("jeju"), width="stretch", hide_index=True)


if menu == "종합":
    render_overview()
elif menu == "검증":
    render_validation()
else:
    render_data_status()

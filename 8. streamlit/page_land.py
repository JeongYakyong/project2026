# -*- coding: utf-8 -*-
"""전국 페이지 — 종합(현황/기상개황/장지평 예측) · 수요 예측 · 데이터 현황."""
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as C
import brief_ai as B

C.page_header(
    "NATIONAL · DAILY BRIEFING", "가스 송출량 예측 브리핑",
    "신재생이 만든 잔여부하를 가스 발전이 메운다 — 5→6→7 서빙 체인의 사전 적재 예측",
    [("수요", C.COLOR["demand"]), ("신재생", C.COLOR["renew"]),
     ("net_load", C.COLOR["net_load"]), ("가스", C.COLOR["gas"])])
menu = st.sidebar.radio("메뉴", ["종합", "검증", "데이터 현황", "운영 실행"])

TODAY = pd.Timestamp.now().normalize()
ORIGIN = TODAY - pd.Timedelta(days=1)  # 어제 23:00 발행 가정(사전 적재)


def _day_bounds(d0: pd.Timestamp, d1: pd.Timestamp) -> tuple[str, str]:
    return d0.strftime("%Y-%m-%d 00:00:00"), d1.strftime("%Y-%m-%d 23:00:00")


def missing_forecast_block(day: pd.Timestamp, key: str):
    """선택 구간 예측이 지평 아카이브에 없을 때 안내 (적재 범위 표시)."""
    lo, hi = C.land_date_range()
    st.warning(f"선택한 구간의 예측이 지평 아카이브(est_horizon_land)에 없습니다. "
               f"적재 범위: **{lo} ~ {hi}**.")


# ================================================================ 종합
def render_forecast_check():
    """예측 확인 — 선택일 24시간 예측(가스 중심) + 수요 실측. 기본 = 오늘.

    배치: 네비게이터(+⚙️ 표시 데이터) → 비교 plot → 송출량 지표 → AI 브리핑.
    """
    day, _, cap = C.day_navigator("fchk")
    mode, value, label = "latest", None, "가장 최근 예측 (날짜별 최신 발행본)"

    df = C.land_day_compare(day, mode=mode, value=value)
    if df["est_gas_gen_land"].isna().all():
        missing_forecast_block(day, key="fchk_gen")
        return

    render_series_compare(df, prefix="fchk", gear_col=cap)
    st.caption(f"표시 기준: {day:%Y-%m-%d} · {label}")

    # 하단 — 선택일 가스 송출량 지표 4개
    ton = df["est_gas_sendout_ton_land"]
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("발전용 가스 하루 예상 송출량", f"{ton.sum():,.0f} TON")
    c2.metric("시간당 가스 최대 예상 송출량", f"{ton.max():,.0f} TON/h")
    c3.metric("시간당 가스 최소 예상 송출량", f"{ton.min():,.0f} TON/h")
    c4.metric("가스발전 합", f"{df['est_gas_gen_land'].sum() / 1000:,.1f} GWh")

    st.markdown("##### AI 브리핑")
    B.render_brief_panel("fchk", day)


def render_daily_sendout():
    """일일 송출량(일단위, TON/day) — 발전용 막대 + 도시가스 on/off 누적(총 송출량).

    발전용은 시간당 예측(5→6→7 체인)의 하루 합, 도시가스는 일단위 보조모델(10단계).
    둘 다 단위 TON이라 그대로 더한다. 도시가스는 일단위라 일단위 화면에서만 합산 가능.
    """
    start, _, c_slider = C.day_navigator("ds")
    lo, hi = C.land_date_range()
    avail_end = pd.Timestamp(hi)

    # 끝 날짜 슬라이더 (15일 창, 미래엔 D+표기) — 장지평과 같은 방식
    win_end = max(start, min(avail_end, start + pd.Timedelta(days=14)))
    options = list(pd.date_range(start, win_end, freq="D"))
    end = c_slider.select_slider(
        "예측 구간 끝 날짜", options=options, value=options[-1], key="ds_end",
        format_func=lambda d: f"{d:%m-%d}" + (f" (D+{(d - ORIGIN).days})" if d >= TODAY else ""))

    show_cg = st.toggle(
        "도시가스 합산", value=True, key="ds_citygas",
        help="켜면 발전용 위에 도시가스(난방 중심·일단위 보조모델, 10단계)를 쌓아 "
             "'총 송출량'으로 봅니다. 발전용·도시가스 모두 단위는 TON입니다.")

    daily = C.land_daily_sendout(start, end)
    if daily.empty or daily["gen_ton"].dropna().empty:
        st.warning(f"선택 구간의 일일 송출량 예측이 없습니다. (적재 범위: {lo} ~ {hi})")
        return

    fig = C.make_fig(height=460, ytitle="일 송출량 (TON/day)")
    fig.add_bar(x=daily["date"], y=daily["gen_ton"], name="발전용 가스",
                marker_color=C.COLOR["ton"],
                hovertemplate="%{x|%m-%d}<br>발전용 %{y:,.0f} TON<extra></extra>")
    if show_cg:
        fig.add_bar(x=daily["date"], y=daily["citygas_ton"].fillna(0), name="도시가스(참고)",
                    marker_color=C.COLOR["citygas"],
                    hovertemplate="%{x|%m-%d}<br>도시가스 %{y:,.0f} TON<extra></extra>")
        fig.update_layout(barmode="stack")
    fig.update_xaxes(tickformat="%m-%d")
    st.plotly_chart(fig, width="stretch")

    gen_sum = daily["gen_ton"].sum()
    cg_sum = daily["citygas_ton"].sum()
    cols = st.columns(3)
    cols[0].metric("발전용 송출량 (기간 합)", f"{gen_sum:,.0f} TON")
    if show_cg:
        cols[1].metric("도시가스 송출량 (기간 합)", f"{cg_sum:,.0f} TON")
        cols[2].metric("총 송출량 (기간 합)", f"{gen_sum + cg_sum:,.0f} TON")

    st.caption(
        "발전용 = 시간당 예측(5→6→7 체인)의 하루 합계 · 도시가스 = 일단위 보조모델(10단계). "
        "둘 다 단위가 TON이라 그대로 더합니다(막대 높이 = 그날 총 송출량). 도시가스는 "
        "net_load·신재생과 무관한 기온 기반 **보조·참고**값으로, 일 실측이 없어 간접검증입니다.")


# 누적 그룹 색 — 전력거래소 차트와 비슷한 톤 (원전 주황·가스 노랑·BTM/PPA 연분홍)
MIX_COLORS = {"원전": "#f28e2b", "기타발전": "#9c755f", "가스": "#edc948",
              "태양광+풍력": "#59a14f", "BTM+PPA": "#f1a7c1"}


def _rgba(hex_color: str, alpha: float) -> str:
    h = hex_color.lstrip("#")
    return f"rgba({int(h[0:2], 16)},{int(h[2:4], 16)},{int(h[4:6], 16)},{alpha})"


def render_gen_mix():
    """발전데이터 탭 — 전력거래소식 누적 발전 믹스(실측) + 예측 dot(누적기준 정렬)."""
    day, _, cap = C.day_navigator("mix")
    mode, value, label = "latest", None, "가장 최근 예측 (날짜별 최신 발행본)"
    cap.caption(f"{day:%Y-%m-%d} 00~23시 · 실측 누적 + 예측 dot · {label}")

    mix = C.land_day_mix(day)
    # 미수집 시간 절단: 가스 발전 0은 물리적으로 불가(항상 켜짐) → 0/결측 시간은 그래프에서 제외
    valid = mix["가스"].notna() & (mix["가스"] > 0) & mix["원전"].notna()
    if not valid.any():
        st.warning("이 날짜의 발전실적이 아직 수집되지 않았습니다. "
                   "예측은 '예측 확인' 탭에서 보세요.")
        return
    m = mix[valid].copy()
    for c in ["원전", "기타발전", "가스", "태양광+풍력", "BTM+PPA", "계량수요", "총수요"]:
        m[c] = pd.to_numeric(m[c], errors="coerce")

    fig = C.make_fig(height=480)
    for name in ["원전", "기타발전", "가스", "태양광+풍력", "BTM+PPA"]:
        fig.add_scatter(x=m["timestamp"], y=m[name], name=name, mode="lines",
                        stackgroup="mix",
                        line=dict(width=0.5, color=_rgba(MIX_COLORS[name], 0.9)),
                        fillcolor=_rgba(MIX_COLORS[name], 0.45))
    fig.add_scatter(x=m["timestamp"], y=m["총수요"], name="전체 전력수요(총수요)",
                    line=dict(color="#455a64", width=2))

    # 예측 dot — 실측 띠의 윗변과 겹치도록 아래 누적(베이스)을 더해 같은 기준으로 정렬
    est = C.land_day_compare(day, mode=mode, value=value)[
        ["timestamp", "est_demand_land", "est_gas_gen_land", "est_market_renew_land"]]
    m = m.merge(est, on="timestamp", how="left")
    # 총수요 기준 예측 = 계량수요 예측 + BTM/PPA(실측). 지평 아카이브는 시장뷰(계량수요)만 보관.
    m["est_true_demand_land"] = m["est_demand_land"] + m["BTM+PPA"]
    fig.add_scatter(x=m["timestamp"], y=m["est_true_demand_land"],
                    name="전력수요 예측(총수요 기준)",
                    line=dict(color="#78909c", width=2, dash="dot"))
    base_gas = m["원전"] + m["기타발전"]
    fig.add_scatter(x=m["timestamp"], y=base_gas + m["est_gas_gen_land"],
                    name="가스발전 예측(누적기준)",
                    line=dict(color="#8a6d00", width=2, dash="dot"))
    base_renew = base_gas + m["가스"]
    fig.add_scatter(x=m["timestamp"], y=base_renew + m["est_market_renew_land"],
                    name="태양광+풍력 예측(누적기준)",
                    line=dict(color="#1b5e20", width=2, dash="dot"))

    fig.update_xaxes(range=[day, day + pd.Timedelta(hours=24)])
    st.plotly_chart(fig, width="stretch")
    st.caption("실측 누적: 원전(기저) → 기타발전(석탄·수력·양수·유류 등) → 가스 → 태양광+풍력(시장) "
               "→ BTM+PPA(추정). 총수요 선 = 계량수요 + BTM/PPA, "
               "수요 예측 점선 = 같은 기준(계량수요 예측 + BTM/PPA 추정, 6단계 est_true_demand). "
               "가스·태양광+풍력 예측 dot은 아래 누적을 더해 실측 띠의 윗변과 같은 기준 — "
               "점선과 띠 경계의 간격이 곧 예측 오차입니다. 미수집 시간(오늘 잔여·미래)은 면적을 그리지 않습니다.")


# 공통 비교 plot 시리즈 — (라벨, 컬럼, 종류, 색, 기본 선택). 예측 확인·장지평 공용.
COMPARE_SERIES = [
    ("전력수요 실측", "real_demand_land", "act", C.COLOR["demand"], True),
    ("전력수요 예측", "est_demand_land", "est", C.COLOR["demand"], True),
    ("가스발전 실측", "gen_gas_kr", "act", C.COLOR["gas"], True),
    ("가스발전 예측", "est_gas_gen_land", "est", C.COLOR["gas"], True),
    ("신재생 실측", "renew_gen_total_kr", "act", C.COLOR["renew"], True),
    ("신재생 예측", "est_market_renew_land", "est", C.COLOR["renew"], True),
    ("net_load 실측", "real_net_load", "act", C.COLOR["net_load"], False),
    ("net_load 예측", "est_net_load_land", "est", C.COLOR["net_load"], False),
    ("KPX 수요예측(DA)", "land_est_demand_da", "kpx", "#17becf", False),
]


def render_series_compare(df: pd.DataFrame, prefix: str, height: int = 460,
                          gear_col=None):
    """⚙️ 선택형 예측 vs 실측 비교 plot — 예측 확인·장지평 탭 공용 컴포넌트.

    gear_col을 주면 ⚙️ popover를 그 자리(예: 네비게이터 행)에 렌더.
    """
    if gear_col is None:
        gear_col, _ = st.columns([1, 5])
    with gear_col.popover("⚙️ 표시 데이터"):
        chosen = {label: st.checkbox(label, value=default, key=f"{prefix}_s_{col}")
                  for label, col, _, _, default in COMPARE_SERIES}

    cd, tmpl = C.hz_hover(df)
    fig = C.make_fig(height=height)
    for label, col, kind, color, _ in COMPARE_SERIES:
        if not chosen[label]:
            continue
        if kind == "act":
            C.add_actual(fig, df["timestamp"], df[col], f"{label} (MW)", color)
        elif kind == "kpx":
            fig.add_scatter(x=df["timestamp"], y=df[col], name=f"{label} (MW)",
                            line=dict(color=color, dash="dash", width=2),
                            hovertemplate="%{x|%m-%d %H시} · %{y:,.0f} MW<br>"
                            "KPX 하루전 발표(D+1)<extra>%{fullData.name}</extra>")
        else:
            C.add_forecast(fig, df["timestamp"], df[col], f"{label} (MW)", color,
                           customdata=cd, hovertemplate=tmpl)
    fig.update_xaxes(range=[df["timestamp"].min(), df["timestamp"].max()])
    st.plotly_chart(fig, width="stretch")


def render_weather():
    """기상개황 — 8권역 초록 choropleth(Leaflet 임베드, visual.md A안) + 간략 권역 테이블."""
    import streamlit.components.v1 as components
    import weather_map as W

    if not W.GEOJSON.exists():
        st.warning("기상개황 지도 자산(시도 geojson)을 찾을 수 없습니다 — 9. design 재구성 중. "
                   "다음 세션 디자인 개편에서 정리 예정입니다.")
        return

    day, _, cap = C.day_navigator("wx", refresh=False)
    dplus = (day - TODAY).days
    cap.caption(f"{day:%Y-%m-%d} · 09–15시 평균(일사·기온·풍속·강수) 기준 — 별도 시각 선택 없음")

    date = day.strftime("%Y-%m-%d")
    zones = W.zone_day(date)
    util = W.national_util(date)
    if all(not z["ok"] for z in zones.values()) and util["solar"] is None:
        st.warning(f"{date} 예보가 없습니다 (KIMG 예보 보유 범위 밖).")
        return

    components.html(W.build_html(day, dplus, zones, util), height=620)

    # 간략 테이블 — 8권역 기상상태 + 전국 이용률 예측(6단계 서빙값).
    # 과거·당일은 실측 병기: 셀 = 예보 → 실측 (기상 ASOS · 이용률 KPX 역산).
    past = dplus <= 0
    act_zones = W.zone_actual(date) if past else {}
    act_util = W.national_util_actual(date) if past else {"solar": None, "wind": None}

    def cell(est, act):
        return est if act is None else f"{est} → {act}"

    m1, m2, m3 = st.columns([1, 1, 3])
    m1.metric("전국 태양광 이용률(예측)",
              "—" if util["solar"] is None else f"{util['solar']:.1f}%",
              f"실측 {act_util['solar']:.1f}%" if act_util["solar"] is not None
              else "—" if util["solar_max"] is None else f"최대 {util['solar_max']:.1f}%",
              delta_color="off",
              help="평균 = 09–15시 · 최대 = 그날 시간별 최대 · 과거 날짜는 KPX 실측 병기")
    m2.metric("전국 풍력 이용률(예측)",
              "—" if util["wind"] is None else f"{util['wind']:.1f}%",
              f"실측 {act_util['wind']:.1f}%" if act_util["wind"] is not None
              else "—" if util["wind_max"] is None else f"최대 {util['wind_max']:.1f}%",
              delta_color="off",
              help="평균 = 24시간 · 최대 = 그날 시간별 최대 · 과거 날짜는 KPX 실측 병기")

    rows = []
    for name, z in zones.items():
        a = act_zones.get(name)
        a_ok = a is not None and a["ok"]
        rows.append({
            "권역": name,
            "날씨": cell(f"{z['sky']['emo']} {z['sky']['t']}" if z["ok"] else "—",
                       f"{a['sky']['emo']} {a['sky']['t']}" if a_ok else None),
            "기온(℃)": cell("—" if z["temp"] is None else f"{z['temp']:.1f}",
                          f"{a['temp']:.1f}" if a_ok and a["temp"] is not None else None),
            "일사 비율": cell("—" if z["ratio"] is None else f"{z['ratio'] * 100:.0f}%",
                          f"{a['ratio'] * 100:.0f}%" if a_ok and a["ratio"] is not None else None),
            "풍속(m/s)": cell("—" if z["wind_ms"] is None else f"{z['wind_ms']:.1f}",
                           f"{a['wind_ms']:.1f}" if a_ok and a["wind_ms"] is not None else None),
            # 과거 모드는 라벨 생략(셀 폭) — % 끼리 비교
            "태양광 활성도": cell("—" if z["sa"] is None
                            else f"{z['sa']['pct']}%" if past else f"{z['sa']['pct']}% {z['sa']['lab']}",
                            f"{a['sa']['pct']}%" if a_ok and a["sa"] is not None else None),
            "풍력 활성도": cell("—" if z["wa"] is None
                           else f"{z['wa']['pct']}%" if past else f"{z['wa']['pct']}% {z['wa']['lab']}",
                           f"{a['wa']['pct']}%" if a_ok and a["wa"] is not None else None),
        })
    m3.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True, height=320)
    if past:
        st.caption("과거·당일 — 셀 표기 = **예보 → 실측** (예보 = rolling D+1 발행분, "
                   "기상 실측 = ASOS 관측, 이용률 실측 = KPX 발전실적 역산). "
                   "실측 미적재 구간은 예보만 표시됩니다.")

    st.caption("면 색(초록) = 모드별 신재생 강도(설비용량×활성도)·일사 비율·풍속 — 진할수록 강함. "
               "용량 = 2026.04 전국총량 × 2024 지역비율(추정), 권역 기상 = 대표 관측소 예보"
               "(영광→광주·전남/전북, 포항→경남/경북 공유 — 의도된 매핑), 제주 = 제주 DB 실데이터(고산). "
               "활성도 = 기대 전국 이용률(2022~26 historical 실측 역산 교정) — 권역엔 상대 신호로 적용. "
               "출처: 기상청 KIMG 예보 · 6단계 이용률 예측.")


def render_longhorizon():
    """장지평 — 표준 네비(시작일) + 끝 날짜 슬라이더 + 예측 기준(basetime×horizon) 선택."""
    start, _, c_slider = C.day_navigator("lh")

    # 지평 아카이브의 실제 목표시각 범위 — 거짓 범위를 안 보여줌
    lo, hi = C.land_date_range()
    avail_end = pd.Timestamp(hi)

    # 예측 길이 — 네비 행 오른쪽 슬라이더 (14일 창, 미래엔 D+표기 보조)
    win_end = max(start, min(avail_end, start + pd.Timedelta(days=13)))
    options = list(pd.date_range(start, win_end, freq="D"))
    end = c_slider.select_slider(
        "예측 구간 끝 날짜", options=options, value=options[-1],
        format_func=lambda d: f"{d:%m-%d}" + (f" (D+{(d - ORIGIN).days})" if d >= TODAY else ""))
    n_days = (end - start).days + 1

    mode, value, label = "latest", None, "가장 최근 예측 (날짜별 최신 발행본)"
    df = C.land_range_compare(start, end, mode=mode, value=value)
    if df.empty or df["est_demand_land"].isna().all():
        st.warning(f"선택 구간/기준의 예측이 없습니다. (지평 아카이브: {lo} ~ {hi})")
        return

    ton = df["est_gas_sendout_ton_land"].sum()
    cost = C.gas_cost_won(df["timestamp"], df["est_gas_sendout_ton_land"]).sum()
    gm = C.error_metrics(df["est_gas_gen_land"], df["gen_gas_kr"])
    c1, c2, c3 = st.columns(3)
    c1.metric(f"{start:%m-%d}~{end:%m-%d} ({n_days}일) 가스 송출량(예측 합)", f"{ton:,.0f} TON")
    c2.metric("가스비(환산)", f"{cost / 1e8:,.0f} 억원")
    if gm:
        c3.metric("가스 MAPE", f"{gm['mape']:.1f} %", f"bias {gm['bias']:+.1f}%", delta_color="off")

    render_series_compare(df, prefix="lh", height=480)
    st.caption(f"예측 기준: **{label}**. 발행일·지평을 바꿔가며 같은 구간을 볼 수 있습니다 — "
               "'지평 고정'으로 D+1과 D+12를 비교하면 멀리서 본 예측도 정확도가 비슷한 것"
               "(지평 평평, 체인 검증 D+1≈D+12)을 확인할 수 있습니다. "
               "미래 구간은 실측이 없어 예측만 표시되고, KPX 수요예측(DA)은 D+1 발행분만 비교에 포함됩니다.")


# ================================================================ 수요 예측
def render_forecast_menu():
    # 상단 컨트롤 — 날짜 내비(7일 고정) + '지평 D+k' 하나로 정리(예측기준 3모드·표시기간 슬라이더 제거).
    # 검증 시계열은 "어느 지평(D+k)을 볼지"가 핵심 — 정밀 비교는 아래 '정확도 평가' 탭이 담당.
    start, _, cap = C.day_navigator("fm")
    end = start + pd.Timedelta(days=6)
    meta = C.land_horizon_meta()
    k = st.slider("지평 D+k (각 날짜를 정확히 k일 전에 예측한 값)", meta["h_lo"], meta["h_hi"], 1,
                  key="fm_hzk", help="그 지평의 시계열을 봅니다. D+1은 KPX 하루전 예측과도 비교됩니다.")
    mode, value, label = "fixed", k, f"D+{k} (각 날짜를 {k}일 전에 예측)"
    cap.caption(f"{start:%Y-%m-%d} ~ {end:%Y-%m-%d} (7일) · {label} · "
                "실측 ━ / 예측 ··· / KPX DA ╌")

    df = C.land_range_compare(start, end, mode=mode, value=value)
    if df.empty or (df["est_demand_land"].isna().all() and df["real_demand_land"].isna().all()):
        missing_forecast_block(start, key="fm_gen")
        return

    t1, t2, t3, t4, t5 = st.tabs(
        ["전력수요", "순수요(net_load)", "천연가스", "정확도 평가", "지평별 정확도"])
    ts = df["timestamp"]
    cd, tmpl = C.hz_hover(df)
    da_hover = ("%{x|%m-%d %H시} · %{y:,.0f} MW<br>KPX 하루전 발표(D+1)"
                "<extra>%{fullData.name}</extra>")

    with t1:
        fig = C.make_fig()
        C.add_actual(fig, ts, df["real_demand_land"], "수요 실측", C.COLOR["demand"])
        C.add_forecast(fig, ts, df["est_demand_land"], "수요 예측", C.COLOR["demand"],
                       customdata=cd, hovertemplate=tmpl)
        fig.add_scatter(x=ts, y=df["land_est_demand_da"], name="KPX 수요예측(DA)",
                        line=dict(color="#17becf", dash="dash", width=2), hovertemplate=da_hover)
        st.plotly_chart(fig, width="stretch")
        st.caption("KPX 수요예측(DA)은 전력거래소 하루 전 발표 — **표시 지평이 D+1일 때만** 비교에 나옵니다.")

    with t2:
        fig = C.make_fig()
        C.add_actual(fig, ts, df["real_net_load"], "net_load 실측", C.COLOR["net_load"])
        C.add_forecast(fig, ts, df["est_net_load_land"], "net_load 예측", C.COLOR["net_load"],
                       customdata=cd, hovertemplate=tmpl)
        C.add_forecast(fig, ts, df["est_market_renew_land"], "신재생 예측(참고)", C.COLOR["renew"],
                       customdata=cd, hovertemplate=tmpl)
        st.plotly_chart(fig, width="stretch")
        st.caption("net_load = 수요 − 시장 신재생. 실측도 같은 기준으로 재구성해 비교합니다.")

    with t3:
        ton = df["est_gas_sendout_ton_land"].sum()
        cost = C.gas_cost_won(df["timestamp"], df["est_gas_sendout_ton_land"]).sum()
        c1, c2 = st.columns(2)
        c1.metric(f"{start:%m-%d}~{end:%m-%d} 송출량(예측 합)", f"{ton:,.0f} TON")
        c2.metric("가스비(환산)", f"{cost / 1e8:,.0f} 억원")
        fig = C.make_fig()
        C.add_actual(fig, ts, df["gen_gas_kr"], "가스 발전 실측 (MW)", C.COLOR["gas"])
        C.add_forecast(fig, ts, df["est_gas_gen_land"], "가스 발전 예측 (MW)", C.COLOR["gas"],
                       customdata=cd, hovertemplate=tmpl)
        C.add_forecast(fig, ts, df["est_gas_sendout_ton_land"], "송출량 예측 (TON/h)", C.COLOR["ton"],
                       customdata=cd, hovertemplate=tmpl)
        st.plotly_chart(fig, width="stretch")
        st.caption("송출량(TON) = 발전량(MWh) × 0.1521 (7-C 변환계수, 열효율 ~43%). "
                   "체인 검증 가스 MAPE ~13% (7-A2-A, ORACLE 10.8%).")

    with t4:
        render_validation(df)

    with t5:
        st.caption("발행본을 모아 본 D+1~D+15 지평별 정확도 — 수요·net_load·가스 = MAPE, 신재생 = nMAE, "
                   "단위 %. 긴 지평은 실측이 있는(더 오래된) 발행본에서 채워집니다.")
        render_horizon_accuracy()


# ================================================================ 검증 (예측 vs 실측, 하루 단위)
CHAIN_PANELS = [  # (제목, est 컬럼, 실측 컬럼, 색, 지표종류 — 신재생은 심야 분모 문제로 nMAE)
    ("수요", "est_demand_land", "real_demand_land", C.COLOR["demand"], "mape"),
    ("신재생", "est_market_renew_land", "renew_gen_total_kr", C.COLOR["renew"], "nmae"),
    ("net_load", "est_net_load_land", "real_net_load", C.COLOR["net_load"], "mape"),
    ("가스", "est_gas_gen_land", "gen_gas_kr", C.COLOR["gas"], "mape"),
]


def render_validation(df: pd.DataFrame):
    """체인 스택 4행 검증 — 구간은 수요 예측 메뉴의 공통 시간 선택을 따른다."""
    # ---- 체인 스택 4행 (x축 공유) — 패널 제목에 평가지표 배지(구간 전체 기준)
    from plotly.subplots import make_subplots
    titles = []
    for name, ec, ac, _, kind in CHAIN_PANELS:
        m = C.error_metrics(df[ec], df[ac])
        if m:
            lbl = "nMAE" if kind == "nmae" else "MAPE"
            titles.append(f"{name} — {lbl} {m[kind]:.1f}% · MAE {m['mae']:,.0f} MW · bias {m['bias']:+.1f}%")
        else:
            titles.append(f"{name} — 실측 없음(예측만)")
    fig = make_subplots(rows=4, cols=1, shared_xaxes=True,
                        vertical_spacing=0.05, subplot_titles=titles)
    cd, tmpl = C.hz_hover(df)
    for i, (name, ec, ac, color, _kind) in enumerate(CHAIN_PANELS, start=1):
        fig.add_scatter(x=df["timestamp"], y=df[ac], name=f"{name} 실측",
                        line=dict(color=color, width=2.5), row=i, col=1)
        if ec == "est_gas_gen_land":
            cdg = [[c[0], f"{t:,.0f} TON" if pd.notna(t) else "—"]
                   for c, t in zip(cd, df["est_gas_sendout_ton_land"])]
            htmpl = ("%{x|%m-%d %H시} · %{y:,.0f} MW · %{customdata[1]}<br>"
                     "%{customdata[0]}<extra>%{fullData.name}</extra>")
            fig.add_scatter(x=df["timestamp"], y=df[ec], name=f"{name} 예측",
                            line=dict(color=color, dash="dot", width=2),
                            customdata=cdg, hovertemplate=htmpl, row=i, col=1)
        else:
            fig.add_scatter(x=df["timestamp"], y=df[ec], name=f"{name} 예측",
                            line=dict(color=color, dash="dot", width=2),
                            customdata=cd, hovertemplate=tmpl, row=i, col=1)
    fig.update_layout(height=900, margin=dict(t=40, b=10),
                      legend=dict(orientation="h", y=-0.04), showlegend=False)
    fig.update_annotations(font_size=13, x=0.0, xanchor="left")
    st.plotly_chart(fig, width="stretch")
    st.caption("신재생↑ → net_load↓ → 가스↓ — 같은 시각을 수직으로 비교하세요. "
               "실측은 KPX 실시간(sukub·발전실적)으로 보강되며, 오차를 숨기지 않습니다(§5.4).")


def _show_acc_table(acc: pd.DataFrame):
    if acc.empty:
        st.caption("집계할 적재분이 없습니다.")
    else:
        st.dataframe(acc, width="stretch", height=560)


def render_horizon_accuracy():
    """지평별 정확도 — 기간별(프리셋+직접설정) / 계절별(봄·여름·가을·겨울) 탭."""
    tabs = st.tabs(["기간별", "봄", "여름", "가을", "겨울"])
    with tabs[0]:
        PERIODS = {"7일": 7, "14일": 14, "한달": 30, "3개월": 92, "직접 설정": None}
        psel = st.segmented_control("기간", list(PERIODS), default="한달",
                                    key="hzacc_period") or "한달"
        if psel == "직접 설정":
            meta = C.land_horizon_meta()
            lo, hi = meta["bases"][0].date(), meta["bases"][-1].date()
            rng = st.date_input("발행일(base) 범위", value=(lo, hi),
                                min_value=lo, max_value=hi, key="hzacc_custom")
            if isinstance(rng, (tuple, list)) and len(rng) == 2:
                acc = C.land_horizon_accuracy(start=rng[0].strftime("%Y-%m-%d"),
                                              end=rng[1].strftime("%Y-%m-%d"))
            else:
                st.caption("시작·종료 발행일을 모두 선택하세요.")
                acc = pd.DataFrame()
        else:
            cutoff = (TODAY - pd.Timedelta(days=PERIODS[psel])).strftime("%Y-%m-%d")
            acc = C.land_horizon_accuracy(start=cutoff)
        _show_acc_table(acc)
    for i, seas in enumerate(["봄", "여름", "가을", "겨울"], start=1):
        with tabs[i]:
            st.caption(f"{seas}({'·'.join(f'{m}월' for m in C.SEASON_MONTHS[seas])}) — 전 기간 발행본 대상")
            _show_acc_table(C.land_horizon_accuracy(season=seas))


# ================================================================ 데이터 현황
# 정본 = est_horizon_land(예측, tall)·forecast_horizon(기상, tall)·historical(실측·KPX DA).
# 레거시 forecast 는 ⚠ 단기캐시로 별도 영역.
TALL_TABLES = {"est_horizon_land", "forecast_horizon"}
HZ_FULL = {"est_horizon_land": 15, "forecast_horizon": 16}   # 완전 발행본의 지평(KIMG≈15.5일)
PAST_PRESET = {"1주": 7, "1개월": 30, "2개월": 61, "3개월": 92}

# fetcher/단계별 대표 컬럼 — 히트맵 요약·DB 조회 기본 선택.
DS_GROUPS = {
    "historical": [
        ("ASOS 관측", ["solar_rad_seosan", "temp_c_seosan", "wind_spd_daegwallyeong"]),
        ("KPX 수급 sukub", ["real_demand_land", "supply_cap_land"]),
        ("KPX 발전실적", ["renew_gen_total_kr", "gen_gas_kr", "gen_solar_market_kr"]),
        ("KPX DA·SMP", ["land_est_demand_da", "smp_land_da"]),
        ("파생 용량·이용률", ["gen_solar_utilization_kr", "gen_wind_utilization_kr"]),
    ],
    "est_horizon_land": [
        ("수요 — 5단계", ["est_demand_land"]),
        ("신재생·net_load — 6단계", ["est_market_renew_land", "est_net_load_land"]),
        ("가스 — 7단계", ["est_gas_gen_land", "est_gas_sendout_ton_land"]),
    ],
    "forecast_horizon": [
        ("KIMG 기상예보", ["radiation_seosan", "temp_seosan",
                        "wind_spd_10m_daegwallyeong", "rainfall_seosan"]),
    ],
}


def _coverage_heatmap(heat: pd.DataFrame, end: pd.Timestamp):
    import plotly.graph_objects as go

    fig = go.Figure(go.Heatmap(
        z=heat.values, x=heat.columns, y=heat.index,
        colorscale=[[0, "#f1f5f9"], [1, "#059669"]], zmin=0, zmax=1,
        hovertemplate="%{y}<br>%{x} ~ +6h · 적재율 %{z:.0%}<extra></extra>",
        showscale=False))
    fig.update_layout(height=max(360, 16 * len(heat.index) + 80),
                      margin=dict(t=10, b=10, l=10, r=10),
                      yaxis=dict(autorange="reversed", tickfont=dict(size=11)))
    if end >= TODAY:
        fig.add_vline(x=pd.Timestamp.now(), line_dash="dot", line_color="#dc2626")
    st.plotly_chart(fig, width="stretch")
    st.caption("셀 = 6시간 블록의 적재율(흰색 0% → 초록 100%). "
               "빨간 점선 = 현재 시각. 행 자체가 없는 구간도 0%로 표시됩니다.")


def _ds_db_browser(table: str, s: str, e: str, default_cols: list[str], extra=None):
    """공용 DB 직접 조회 — 컬럼 선택 + timestamp 구간 필터."""
    extra = extra or []
    cols = [c for c in C.table_columns("land", table) if c != "timestamp"]
    default = [c for c in default_cols if c in cols]
    sel = st.multiselect("컬럼 선택", cols, default=default, key=f"ds_cols_{table}")
    chosen = [c for c in (sel if sel else cols) if c not in extra]
    use = ["timestamp"] + extra + chosen
    df = C.query("land", f"SELECT {', '.join(use)} FROM {table} "
                         "WHERE timestamp BETWEEN ? AND ? ORDER BY timestamp", (s, e))
    st.dataframe(df, width="stretch", height=520)
    st.caption(f"{len(df):,}행 × {len(use)}컬럼 — 읽기 전용.")


def _ds_timestamp(table: str):
    """timestamp 단일키 테이블(historical) — 6시간 적재율 히트맵 + DB 직접 조회."""
    groups = DS_GROUPS[table]
    c1, c2 = st.columns([2.4, 3], vertical_alignment="bottom")
    psel = c1.segmented_control("조회 기간(과거)", list(PAST_PRESET) + ["직접 선택"],
                                default="1개월", key=f"ds_past_{table}") or "1개월"
    if psel == "직접 선택":
        lo, hi = C.table_range("land", table)
        rng = c2.date_input("기간", value=(max(pd.Timestamp(lo), TODAY - pd.Timedelta(days=30)).date(),
                            min(pd.Timestamp(hi), TODAY).date()),
                            min_value=pd.Timestamp(lo).date(), max_value=pd.Timestamp(hi).date(),
                            key=f"ds_range_{table}")
        if len(rng) != 2:
            st.info("기간(시작·끝)을 모두 선택하세요."); return
        start, end = pd.Timestamp(rng[0]), pd.Timestamp(rng[1])
    else:
        start, end = TODAY - pd.Timedelta(days=PAST_PRESET[psel]), TODAY
    s, e = _day_bounds(start, end)
    st.caption(f"`{table}` · {start:%Y-%m-%d} ~ {end:%Y-%m-%d}")

    tab_sum, tab_full, tab_db = st.tabs(
        ["적재 히트맵 — fetcher 요약", "적재 히트맵 — 전체 피처", "DB 직접 조회"])
    with tab_sum:
        heat = C.coverage_heat("land", table, s, e)
        reps, labels = [], []
        for gname, cols in groups:
            for col in cols:
                if col in heat.index:
                    reps.append(col); labels.append(f"[{gname}]  {col}")
        sub = heat.loc[reps]; sub.index = labels
        _coverage_heatmap(sub, end)
        with st.expander("항목별 신선도 요약 (정본 테이블)"):
            st.dataframe(C.coverage_table("land"), width="stretch", hide_index=True)
            st.caption("수집은 crontab 백그라운드에서만 갱신됩니다(API 한도 보호). "
                       "예측 정본 = est_horizon_land · 기상 정본 = forecast_horizon.")
    with tab_full:
        _coverage_heatmap(C.coverage_heat("land", table, s, e), end)
    with tab_db:
        _ds_db_browser(table, s, e, [g[1][0] for g in groups])


def _ds_tall(table: str):
    """tall 아카이브(base×지평) — 발행본별 적재 완성도 표 + DB 직접 조회.

    발행본×지평 적재 히트맵(적재율 100% 색칠·KIMG 15.5일 규칙)은 설계 확정 후 추가 예정.
    """
    full = HZ_FULL[table]
    cov = C.query("land", f"SELECT base, COUNT(DISTINCT horizon_d) 지평수, COUNT(*) 행수, "
                          f"MIN(timestamp) 목표시작, MAX(timestamp) 목표끝 "
                          f"FROM {table} GROUP BY base ORDER BY base DESC")
    cov["완성도%"] = (cov["행수"] / (full * 24) * 100).round(0).clip(upper=100)
    n_full = int((cov["완성도%"] >= 100).sum())
    m1, m2, m3 = st.columns(3)
    m1.metric("발행본(base) 수", f"{len(cov):,}")
    m2.metric(f"완전 적재(D+1~{full})", f"{n_full:,}")
    m3.metric("최신 발행본 완성도", f"{cov['완성도%'].iloc[0]:.0f}%" if len(cov) else "—")
    st.caption(f"`{table}` — 발행본별 완성도. 완전 발행본 = D+1~{full} ({full * 24}행/base). "
               "최신 발행본이 부분이면 야간 아카이브 작업 전입니다. "
               "발행본×지평 적재 히트맵(100% 색칠·KIMG 15.5일 규칙)은 다음 라운드에 추가합니다.")
    st.dataframe(cov.head(45), width="stretch", hide_index=True, height=420)

    with st.expander("항목별 신선도 요약 (정본 테이블)"):
        st.dataframe(C.coverage_table("land"), width="stretch", hide_index=True)
    with st.expander("DB 직접 조회 (base·horizon_d·timestamp)"):
        lo, hi = C.table_range("land", table)
        rng = st.date_input("목표시각 기간",
                            value=(max(pd.Timestamp(lo), TODAY - pd.Timedelta(days=3)).date(),
                                   min(pd.Timestamp(hi), TODAY + pd.Timedelta(days=15)).date()),
                            min_value=pd.Timestamp(lo).date(), max_value=pd.Timestamp(hi).date(),
                            key=f"ds_range_{table}")
        if len(rng) == 2:
            s, e = _day_bounds(pd.Timestamp(rng[0]), pd.Timestamp(rng[1]))
            _ds_db_browser(table, s, e, [g[1][0] for g in DS_GROUPS[table]],
                           extra=["base", "horizon_d"])


def render_data_status():
    st.subheader("데이터 적재 현황 (전국 DB)")
    st.caption("정본 — **est_horizon_land**(예측 아카이브)·**forecast_horizon**(기상 아카이브)·"
               "**historical**(실측·KPX DA).")
    table = st.segmented_control("테이블", ["historical", "est_horizon_land", "forecast_horizon"],
                                 default="historical", key="ds_table") or "historical"
    if table in TALL_TABLES:
        _ds_tall(table)
    else:
        _ds_timestamp(table)


def render_run_ops():
    """운영 실행 — 서빙 체인 러너(serve_chain_land_new.py)를 수동 트리거.

    서버 cron(매일 06:00)과 동일 작업.  서빙은 로컬 추론(API 무관)이라 대시보드에서 직접 실행 안전.
    """
    st.subheader("서빙 체인 실행 — 5→6→7 → est_horizon_land")
    st.caption("forecast_horizon(기상 예보) → 수요·신재생·가스(보정·블렌딩) 예측을 est_horizon_land 에 "
               "적재. 로컬 추론(API 무관). 서버 cron(매일 06:00)과 같은 작업을 수동으로 돌린다.")

    mode = st.radio("대상 발행본(base)", ["최신", "특정 발행일", "최근 N개"],
                    horizontal=True, key="ops_mode")
    args: list[str] = []
    if mode == "특정 발행일":
        d = st.date_input("발행일 (12 UTC base 날짜)",
                          value=(TODAY - pd.Timedelta(days=1)).date(), key="ops_base")
        args += ["--base", d.strftime("%Y-%m-%d")]
    elif mode == "최근 N개":
        n = st.number_input("N (최근 base 개수, backfill)", min_value=1, max_value=15,
                            value=3, key="ops_n")
        args += ["--backfill", str(int(n))]

    dry = st.toggle("dry-run (산출만, 적재 안 함)", value=False, key="ops_dry")
    if dry:
        args += ["--no-write"]

    st.code('python "7. land_gas_forecaster/serve_chain_land_new.py" '
            + (" ".join(args) if args else "  # 최신 base"), language="bash")

    if st.button("▶ 서빙 체인 실행", type="primary", key="ops_run"):
        with st.spinner("서빙 체인 실행 중… (base 당 수 초)"):
            rc, out = C.run_script(C.SERVE_CHAIN_LAND, args)
        if rc == 0:
            st.success("완료 (종료코드 0)")
            if not dry:
                st.cache_data.clear()   # 새 적재가 다른 메뉴 조회에 반영되도록 캐시 무효화
                st.caption("est_horizon_land 갱신 → 조회 캐시 초기화. 다른 메뉴에서 최신 예측 확인 가능.")
        else:
            st.error(f"실패 (종료코드 {rc})")
        st.code(out or "(출력 없음)")

    st.divider()
    st.subheader("데이터 수집 (KMA/KPX API)")
    st.caption("⚠ API 한도 보호 — 평소엔 서버 cron 전용. **개발단계 임시 수동 버튼**(비밀번호 게이트). "
               "기상은 완결성 auto-resume 라 재실행해도 완전한 base 는 콜 없이 skip.")
    pw = st.text_input("실행 비밀번호", type="password", key="ops_pw",
                       help="개발단계 임시 가드 — 운영 공개 전 제거/교체")
    unlocked = pw == C.OPS_PASSWORD
    if pw and not unlocked:
        st.error("비밀번호가 틀립니다.")
    elif not pw:
        st.info("수집 버튼은 비밀번호 입력 후 활성화됩니다.")

    col_f, col_h = st.columns(2)
    with col_f:
        st.markdown("**① 기상예보 → forecast_horizon**")
        fmode = st.radio("대상", ["최신 12z", "최근 N개(backfill)"], key="cf_mode")
        fargs = ["--region", "land"]
        if fmode == "최근 N개(backfill)":
            fn = st.number_input("N (최근 base)", 1, 7, 3, key="cf_n")
            fargs += ["--backfill", str(int(fn))]
        if st.button("▶ 기상 수집 실행", disabled=not unlocked, key="cf_run"):
            with st.spinner("기상 수집 중… (KMA API, base 당 수 분)"):
                rc, out = C.run_script(C.COLLECT_FORECAST, fargs, cwd=C.DATA_DIR)
            if rc == 0:
                st.success("완료 (종료코드 0)")
                st.cache_data.clear()
            else:
                st.error(f"실패 (종료코드 {rc})")
            st.code(out or "(출력 없음)")
    with col_h:
        st.markdown("**② 실측 → historical**")
        hd = st.number_input("최근 일수 (--historical-days)", 1, 30, 2, key="ch_days")
        if st.button("▶ 실측 수집 실행", disabled=not unlocked, key="ch_run"):
            with st.spinner("실측 수집 중… (KPX/ASOS API)"):
                rc, out = C.run_script(C.COLLECT_LAND_HIST,
                                       ["--historical-days", str(int(hd))], cwd=C.DATA_DIR)
            if rc == 0:
                st.success("완료 (종료코드 0)")
                st.cache_data.clear()
            else:
                st.error(f"실패 (종료코드 {rc})")
            st.code(out or "(출력 없음)")


if menu == "종합":
    # 탭별 독립 네비게이터(표준 구조) — 기상개황은 새로고침 없는 슬림 버전
    tab_now, tab_daily, tab_mix, tab_wx, tab_lh = st.tabs(
        ["예측 확인", "일일 송출량", "발전데이터", "기상개황", "장지평 예측"])
    with tab_now:
        render_forecast_check()
    with tab_daily:
        render_daily_sendout()
    with tab_mix:
        render_gen_mix()
    with tab_wx:
        render_weather()
    with tab_lh:
        render_longhorizon()
elif menu == "검증":
    render_forecast_menu()
elif menu == "데이터 현황":
    render_data_status()
else:
    render_run_ops()

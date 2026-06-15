# -*- coding: utf-8 -*-
"""전국 페이지 — 종합(현황/기상개황/장지평 예측) · 수요 예측 · 데이터 현황."""
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as C

C.page_header(
    "NATIONAL · DAILY BRIEFING", "가스 송출량 예측 브리핑",
    "신재생이 만든 잔여부하를 가스 발전이 메운다 — 5→6→7 서빙 체인의 사전 적재 예측",
    [("수요", C.COLOR["demand"]), ("신재생", C.COLOR["renew"]),
     ("net_load", C.COLOR["net_load"]), ("가스", C.COLOR["gas"])])
menu = st.sidebar.radio("메뉴", ["종합", "수요 예측", "데이터 현황"])

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
    mode, value, label = C.horizon_picker("fchk")

    df = C.land_day_compare(day, mode=mode, value=value)
    if df["est_gas_gen_land"].isna().all():
        missing_forecast_block(day, key="fchk_gen")
        return

    render_series_compare(df, prefix="fchk", gear_col=cap)
    st.caption(f"표시 기준: {day:%Y-%m-%d} · {label}")

    # 하단 — 선택일 가스 송출량 지표 4개
    ton = df["est_gas_sendout_ton_land"]
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("일별 예상 가스 송출량", f"{ton.sum():,.0f} TON")
    c2.metric("최대 예상 시간당 가스 송출량", f"{ton.max():,.0f} TON/h")
    c3.metric("최소 예상 시간당 가스 송출량", f"{ton.min():,.0f} TON/h")
    c4.metric("가스발전 합", f"{df['est_gas_gen_land'].sum() / 1000:,.1f} GWh")

    st.markdown("##### AI 브리핑")
    st.info("brief_ai는 8-D에서 연결됩니다 (Gemini API, 같은 날짜·지역 24시간 캐시).")


# 누적 그룹 색 — 전력거래소 차트와 비슷한 톤 (원전 주황·가스 노랑·BTM/PPA 연분홍)
MIX_COLORS = {"원전": "#f28e2b", "기타발전": "#9c755f", "가스": "#edc948",
              "태양광+풍력": "#59a14f", "BTM+PPA": "#f1a7c1"}


def _rgba(hex_color: str, alpha: float) -> str:
    h = hex_color.lstrip("#")
    return f"rgba({int(h[0:2], 16)},{int(h[2:4], 16)},{int(h[4:6], 16)},{alpha})"


def render_gen_mix():
    """발전데이터 탭 — 전력거래소식 누적 발전 믹스(실측) + 예측 dot(누적기준 정렬)."""
    day, _, cap = C.day_navigator("mix")
    mode, value, label = C.horizon_picker("mix")
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

    mode, value, label = C.horizon_picker("lh")
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
    # 메뉴 상단 공통 컨트롤(표준 구조 + 기간 슬라이더) — 4개 탭이 같은 구간을 본다
    start, n, cap = C.day_navigator("fm", ndays=(1, 7, 3))
    end = start + pd.Timedelta(days=n - 1)
    mode, value, label = C.horizon_picker("fm")
    cap.caption(f"{start:%Y-%m-%d} ~ {end:%Y-%m-%d} ({n}일) · {label} · "
                "실측 ━ / 예측 ··· / KPX DA ╌")

    df = C.land_range_compare(start, end, mode=mode, value=value)
    if df.empty or (df["est_demand_land"].isna().all() and df["real_demand_land"].isna().all()):
        missing_forecast_block(start, key="fm_gen")
        return

    t1, t2, t3, t4 = st.tabs(["전력수요 예측", "순 수요(net_load) 예측", "천연가스 수요 예측", "검증"])
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

    with st.expander("최근 30일 일별 MAPE 추이"):
        hist = C.land_daily_error_history((TODAY - pd.Timedelta(days=1)).strftime("%Y-%m-%d"))
        if hist.dropna(how="all").empty:
            st.caption("아직 집계할 적재분이 없습니다.")
        else:
            fig2 = C.make_fig(height=300, ytitle="MAPE (%)")
            colors = {"수요": C.COLOR["demand"], "신재생": C.COLOR["renew"],
                      "net_load": C.COLOR["net_load"], "가스": C.COLOR["gas"]}
            for col in hist.columns:
                fig2.add_scatter(x=hist.index, y=hist[col], name=col,
                                 line=dict(color=colors[col]))
            st.plotly_chart(fig2, width="stretch")
            st.caption("수요·net_load·가스 = 일별 MAPE, 신재생 = nMAE(심야 분모 문제 회피). "
                       "가스 일평균이 체인 검증치(~13%, 7-A2-A)와 비슷하면 정상입니다.")


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


def _ds_legacy_forecast():
    st.warning("이 `forecast` 테이블은 timestamp 단일키 **롤링 스냅샷(과거=사실상 D+1)**입니다. "
               "예측 정본이 아니며(→ est_horizon_land), 최신 서빙의 D+1~3 단기캐시로만 의미가 있습니다. "
               "여기 `est_*` 컬럼은 폐기 대상입니다.")
    lo, hi = C.table_range("land", "forecast")
    rng = st.date_input("기간", value=(max(pd.Timestamp(lo), TODAY - pd.Timedelta(days=7)).date(),
                        min(pd.Timestamp(hi), TODAY + pd.Timedelta(days=3)).date()),
                        min_value=pd.Timestamp(lo).date(), max_value=pd.Timestamp(hi).date(),
                        key="ds_range_forecast")
    if len(rng) == 2:
        s, e = _day_bounds(pd.Timestamp(rng[0]), pd.Timestamp(rng[1]))
        _ds_db_browser("forecast", s, e, ["land_est_demand_da", "est_demand_land"])


def render_data_status():
    st.subheader("데이터 적재 현황 (전국 DB)")
    st.caption("정본 — **est_horizon_land**(예측 아카이브)·**forecast_horizon**(기상 아카이브)·"
               "**historical**(실측·KPX DA). `forecast`는 ⚠ 레거시 단기캐시(맨 아래).")
    table = st.segmented_control("테이블", ["historical", "est_horizon_land", "forecast_horizon"],
                                 default="historical", key="ds_table") or "historical"
    if table in TALL_TABLES:
        _ds_tall(table)
    else:
        _ds_timestamp(table)
    with st.expander("⚠ 레거시 단기캐시 — forecast 테이블 (예측 소스 아님)"):
        _ds_legacy_forecast()


if menu == "종합":
    # 탭별 독립 네비게이터(표준 구조) — 기상개황은 새로고침 없는 슬림 버전
    tab_now, tab_mix, tab_wx, tab_lh = st.tabs(["예측 확인", "발전데이터", "기상개황", "장지평 예측"])
    with tab_now:
        render_forecast_check()
    with tab_mix:
        render_gen_mix()
    with tab_wx:
        render_weather()
    with tab_lh:
        render_longhorizon()
elif menu == "수요 예측":
    render_forecast_menu()
else:
    render_data_status()

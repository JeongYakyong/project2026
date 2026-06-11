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


def day_navigator(prefix: str):
    """하루 단위 날짜 네비게이터 (◀ 전일 / 날짜 / 익일 ▶ / 오늘 / 실시간 새로고침).

    반환: (선택일 Timestamp, 캡션용 column). 기본 = 오늘.
    """
    key = f"{prefix}_day"
    if key not in st.session_state:
        st.session_state[key] = TODAY.date()

    def _shift(delta: int):
        st.session_state[key] = (TODAY.date() if delta == 0
                                 else st.session_state[key] + pd.Timedelta(days=delta))

    nav = st.columns([1, 1, 2, 1, 1.6, 3])
    nav[0].button("◀ 전일", key=f"{prefix}_prev", on_click=_shift, args=(-1,))
    nav[1].button("익일 ▶", key=f"{prefix}_next", on_click=_shift, args=(1,))
    nav[2].date_input("날짜", key=key, label_visibility="collapsed")
    nav[3].button("오늘", key=f"{prefix}_today", on_click=_shift, args=(0,))
    if nav[4].button("실시간 새로고침", key=f"{prefix}_refresh",
                     help="실측(KPX sukub·발전실적)을 다시 불러옵니다 (표시 전용)"):
        C.clear_live_caches()
    return pd.Timestamp(st.session_state[key]), nav[5]


def missing_forecast_block(day: pd.Timestamp, key: str):
    """예측이 없는 날짜 안내 + 제한 실행 버튼 (원칙: 예측은 DB 우선, 없을 때만 실행)."""
    st.info("이 날짜의 예측이 DB에 없습니다. 아래 버튼으로 이 날짜만 생성할 수 있습니다 "
            "(서빙 5→6→7, 로컬 모델 추론 — 수집 API와 무관).")
    if st.button(f"{day:%Y-%m-%d} 예측 생성", key=key):
        with st.spinner("체인 서빙 실행 중 (5→6→7)..."):
            err = _run_chain_for_day(day)
        if err:
            st.error(err)
        else:
            C.query.clear()
            C.land_forecast.clear()
            st.rerun()


# ================================================================ 종합
def render_forecast_check():
    """예측 확인 — 선택일 24시간 예측(가스 중심) + 수요 실측. 기본 = 오늘."""
    day, cap = day_navigator("fchk")
    cap.caption(f"{day:%Y-%m-%d} 00~23시 · 24시간 예측 기본")

    df = C.land_day_compare(day)
    if df["est_gas_gen_land"].isna().all():
        missing_forecast_block(day, key="fchk_gen")
        return

    # 상단 — 선택일 예상 가스 송출량
    ton_day = df["est_gas_sendout_ton_land"].sum()
    cost_day = C.gas_cost_won(df["timestamp"], df["est_gas_sendout_ton_land"]).sum()
    c1, c2, c3 = st.columns(3)
    c1.metric(f"{day:%m-%d} 예상 가스 송출량", f"{ton_day:,.0f} TON")
    c2.metric("가스 발전(예측 합)", f"{df['est_gas_gen_land'].sum() / 1000:,.1f} GWh")
    c3.metric("가스비(환산)", f"{cost_day / 1e8:,.0f} 억원")

    render_series_compare(df, prefix="fchk")

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
    day, cap = day_navigator("mix")
    cap.caption(f"{day:%Y-%m-%d} 00~23시 · 실측 누적 + 예측 dot")

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
    est = C.land_day_compare(day)[["timestamp", "est_gas_gen_land",
                                   "est_market_renew_land", "est_true_demand_land"]]
    m = m.merge(est, on="timestamp", how="left")
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


def render_series_compare(df: pd.DataFrame, prefix: str, height: int = 460):
    """⚙️ 선택형 예측 vs 실측 비교 plot — 예측 확인·장지평 탭 공용 컴포넌트."""
    gear, cap = st.columns([1, 5])
    with gear.popover("⚙️ 표시 데이터"):
        chosen = {label: st.checkbox(label, value=default, key=f"{prefix}_s_{col}")
                  for label, col, _, _, default in COMPARE_SERIES}

    fig = C.make_fig(height=height)
    for label, col, kind, color, _ in COMPARE_SERIES:
        if not chosen[label]:
            continue
        if kind == "act":
            C.add_actual(fig, df["timestamp"], df[col], f"{label} (MW)", color)
        elif kind == "kpx":
            fig.add_scatter(x=df["timestamp"], y=df[col], name=f"{label} (MW)",
                            line=dict(color=color, dash="dash", width=2))
        else:
            C.add_forecast(fig, df["timestamp"], df[col], f"{label} (MW)", color)
    fig.update_xaxes(range=[df["timestamp"].min(), df["timestamp"].max()])
    st.plotly_chart(fig, width="stretch")

    actual = df.dropna(subset=["real_demand_land"])
    last = actual["timestamp"].max() if not actual.empty else None
    cap.caption("실측 ━ solid / 예측 ··· dot / KPX DA ╌ dash · 실측은 KPX 실시간(sukub·발전실적)으로 보강"
                + (f" · 마지막 실측 {last:%m-%d %H:%M}" if last is not None else " · 실측 없음"))


def render_weather():
    """기상개황 — 8권역 초록 choropleth(Leaflet 임베드, visual.md A안) + 간략 권역 테이블."""
    import streamlit.components.v1 as components
    import weather_map as W

    if not W.GEOJSON.exists():
        st.warning("기상개황 지도 자산(시도 geojson)을 찾을 수 없습니다 — 9. design 재구성 중. "
                   "다음 세션 디자인 개편에서 정리 예정입니다.")
        return

    day, cap = day_navigator("wx")
    dplus = (day - TODAY).days
    cap.caption(f"{day:%Y-%m-%d} · 09–15시 평균(일사·기온·풍속·강수) 기준 — 별도 시각 선택 없음")

    date = day.strftime("%Y-%m-%d")
    zones = W.zone_day(date)
    util = W.national_util(date)
    if all(not z["ok"] for z in zones.values()) and util["solar"] is None:
        st.warning(f"{date} 예보가 없습니다 (KIMG 예보 보유 범위 밖).")
        return

    components.html(W.build_html(day, dplus, zones, util), height=620)

    # 간략 테이블 — 8권역 기상상태 + 전국 이용률 예측(6단계 서빙값)
    m1, m2, m3 = st.columns([1, 1, 3])
    m1.metric("전국 태양광 이용률(예측)",
              "—" if util["solar"] is None else f"{util['solar']:.1f}%",
              "—" if util["solar_max"] is None else f"최대 {util['solar_max']:.1f}%",
              delta_color="off", help="평균 = 09–15시 · 최대 = 그날 시간별 최대")
    m2.metric("전국 풍력 이용률(예측)",
              "—" if util["wind"] is None else f"{util['wind']:.1f}%",
              "—" if util["wind_max"] is None else f"최대 {util['wind_max']:.1f}%",
              delta_color="off", help="평균 = 24시간 · 최대 = 그날 시간별 최대")
    rows = [{"권역": name,
             "날씨": f"{z['sky']['emo']} {z['sky']['t']}" if z["ok"] else "—",
             "기온(℃)": z["temp"] if z["ok"] else None,
             "일사 비율": "—" if z["ratio"] is None else f"{z['ratio'] * 100:.0f}%",
             "풍속(m/s)": z["wind_ms"],
             "태양광 활성도": "—" if z["sa"] is None else f"{z['sa']['pct']}% {z['sa']['lab']}",
             "풍력 활성도": "—" if z["wa"] is None else f"{z['wa']['pct']}% {z['wa']['lab']}"}
            for name, z in zones.items()]
    m3.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True, height=320)

    st.caption("면 색(초록) = 모드별 신재생 강도(설비용량×활성도)·일사 비율·풍속 — 진할수록 강함. "
               "용량 = 2026.04 전국총량 × 2024 지역비율(추정), 권역 기상 = 대표 관측소 예보"
               "(영광→광주·전남/전북, 포항→경남/경북 공유 — 의도된 매핑), 제주 = 제주 DB 실데이터(고산). "
               "활성도 = 기대 전국 이용률(2022~26 historical 실측 역산 교정) — 권역엔 상대 신호로 적용. "
               "출처: 기상청 KIMG 예보 · 6단계 이용률 예측.")


def render_longhorizon():
    # 적재된 예측의 실제 범위(사전 적재) — cron이 밀려도 거짓 범위를 안 보여줌
    lo, hi = C.land_date_range()
    avail_start, avail_end = pd.Timestamp(lo), pd.Timestamp(hi)

    c1, c2 = st.columns([1.5, 3.5])
    start = pd.Timestamp(c1.date_input(
        "시작일 (과거 가능)", value=min(TODAY, avail_end - pd.Timedelta(days=1)).date(),
        min_value=avail_start.date(),
        max_value=(avail_end - pd.Timedelta(days=1)).date(), key="lh_start"))
    # 예측 길이 — 끝 날짜를 그대로 보여주는 슬라이더 (최대 14일 창, 미래엔 D+표기 보조)
    win_end = min(avail_end, start + pd.Timedelta(days=13))
    options = list(pd.date_range(start, win_end, freq="D"))
    end = c2.select_slider(
        "예측 구간 끝 날짜", options=options, value=options[-1],
        format_func=lambda d: f"{d:%m-%d}" + (f" (D+{(d - ORIGIN).days})" if d >= TODAY else ""))
    n_days = (end - start).days + 1

    past_mode = start < TODAY
    if past_mode:
        # 과거 = 지평 모드: "k일 전 발행" 예측(7-A2-A 체인 산출)과 실측 비교 — rolling D+1이 아님
        k = st.radio("발행 시점(며칠 전에 예측했는가)", C.CHAIN_HORIZONS, index=3, horizontal=True,
                     key="lh_horizon", format_func=lambda k: f"D+{k} ({k}일 전 발행)")
        df = C.land_horizon_compare(start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"), k)
    else:
        df = C.land_range_compare(start, end)

    if df.empty or df["est_demand_land"].isna().all():
        st.warning("선택 구간의 예측이 없습니다."
                   + (" (지평 모드 보유 범위: 2022-01-02 ~ 체인 데이터셋 끝)" if past_mode else ""))
        return

    ton = df["est_gas_sendout_ton_land"].sum()
    cost = C.gas_cost_won(df["timestamp"], df["est_gas_sendout_ton_land"]).sum()
    gm = C.error_metrics(df["est_gas_gen_land"], df["gen_gas_kr"])
    c1, c2, c3 = st.columns(3)
    c1.metric(f"{start:%m-%d}~{end:%m-%d} ({n_days}일) 가스 송출량(예측 합)", f"{ton:,.0f} TON")
    c2.metric("가스비(환산)", f"{cost / 1e8:,.0f} 억원")
    if gm:
        c3.metric(f"가스 MAPE ({'D+%d 발행' % k if past_mode else '최신 발행'})", f"{gm['mape']:.1f} %",
                  f"bias {gm['bias']:+.1f}%", delta_color="off")

    render_series_compare(df, prefix="lh", height=480)
    if past_mode:
        st.caption(f"과거 구간 = **{k}일 전 발행 예측**(7-A2-A 체인 산출: 수요 5-A2·신재생 6단계 지평별 + "
                   "가스 7-A2 즉석 계산) vs 실측. 지평을 바꿔도 가스 정확도가 비슷한 것(지평 평평, "
                   "체인 검증 D+1 13.08%≈D+12 13.16%)이 이 데모의 핵심 발견입니다.")
    else:
        st.caption(f"발행 기준: {ORIGIN:%Y-%m-%d} 23:00 (사전 적재). 미래 구간은 실측이 없어 예측만 표시됩니다. "
                   "D+3 이후 기상은 (월,시) 기후값 폴백이 섞일 수 있습니다. "
                   "KPX 수요예측(DA)은 하루 전 발표라 내일까지만 존재합니다. "
                   "D+12 확장은 수요 장지평 서빙(5-A2 D+12 모델) 연결 후 제공 예정입니다.")


# ================================================================ 수요 예측
def render_forecast_menu():
    # 공통 시간 선택 — 4개 탭이 같은 구간을 본다 (과거 가능 + 기간 슬라이더 + ◀ ▶)
    start, cap = day_navigator("fm")
    n = cap.slider("표시 기간(일)", 1, 7, 3, key="fm_ndays",
                   help="시작일부터 N일. 사전 적재된 예측을 읽기만 하므로 지연 없이 전환됩니다.")
    end = start + pd.Timedelta(days=n - 1)
    st.caption(f"{start:%Y-%m-%d} ~ {end:%Y-%m-%d} ({n}일) · "
               "실측 ━ solid / 예측 ··· dot / KPX DA ╌ dash")

    df = C.land_range_compare(start, end)
    if df.empty or (df["est_demand_land"].isna().all() and df["real_demand_land"].isna().all()):
        missing_forecast_block(start, key="fm_gen")
        return

    t1, t2, t3, t4 = st.tabs(["전력수요 예측", "순 수요(net_load) 예측", "천연가스 수요 예측", "검증"])
    ts = df["timestamp"]

    with t1:
        fig = C.make_fig()
        C.add_actual(fig, ts, df["real_demand_land"], "수요 실측", C.COLOR["demand"])
        C.add_forecast(fig, ts, df["est_demand_land"], "수요 예측", C.COLOR["demand"])
        fig.add_scatter(x=ts, y=df["land_est_demand_da"], name="KPX 수요예측(DA)",
                        line=dict(color="#17becf", dash="dash", width=2))
        st.plotly_chart(fig, width="stretch")
        st.caption("KPX 수요예측(DA)은 전력거래소 하루 전 발표 — 우리 예측과의 직접 비교 기준입니다.")

    with t2:
        fig = C.make_fig()
        C.add_actual(fig, ts, df["real_net_load"], "net_load 실측", C.COLOR["net_load"])
        C.add_forecast(fig, ts, df["est_net_load_land"], "net_load 예측", C.COLOR["net_load"])
        C.add_forecast(fig, ts, df["est_market_renew_land"], "신재생 예측(참고)", C.COLOR["renew"])
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
        C.add_forecast(fig, ts, df["est_gas_gen_land"], "가스 발전 예측 (MW)", C.COLOR["gas"])
        C.add_forecast(fig, ts, df["est_gas_sendout_ton_land"], "송출량 예측 (TON/h)", C.COLOR["ton"])
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


def _run_chain_for_day(day: pd.Timestamp) -> str:
    """선택일 D 하루를 채우는 제한 실행: origin=D-1로 서빙 5→6→7 (각 D+1만)."""
    import subprocess, sys as _sys
    origin = (day - pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    cmds = [
        [_sys.executable, str(C.ROOT / "5. land_demand_forecaster" / "serve_land_demand.py"),
         "predict", origin, "--days", "1"],
        [_sys.executable, str(C.ROOT / "6. land_solarwind_forecaster" / "serve_solarwind_land.py"),
         "predict", origin, "--days", "1"],
        [_sys.executable, str(C.ROOT / "7. land_gas_forecaster" / "serve_land_gas.py"),
         "predict", origin, "--days", "1"],
    ]
    for cmd in cmds:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        if r.returncode != 0:
            return f"실패: {Path(cmd[1]).name}\n{r.stderr[-500:]}"
    return ""


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
    for i, (name, ec, ac, color, _kind) in enumerate(CHAIN_PANELS, start=1):
        fig.add_scatter(x=df["timestamp"], y=df[ac], name=f"{name} 실측",
                        line=dict(color=color, width=2.5), row=i, col=1)
        hover = None
        if ec == "est_gas_gen_land":
            hover = [f"{v:,.0f} MW · {t:,.0f} TON" if pd.notna(v) else ""
                     for v, t in zip(df[ec], df["est_gas_sendout_ton_land"])]
        fig.add_scatter(x=df["timestamp"], y=df[ec], name=f"{name} 예측",
                        line=dict(color=color, dash="dot", width=2),
                        text=hover, hoverinfo="text+x" if hover else None, row=i, col=1)
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
PAST_PRESET = {"1주": 7, "1개월": 30, "2개월": 61, "3개월": 92}
FUT_PRESET = {"적재 끝까지": None, "1주": 7, "2주": 14, "1개월": 30, "2개월": 61}

# API fetcher 계열별 대표 컬럼 — 탭1 요약 히트맵(2~3개씩)·탭3 기본 선택(각 첫 컬럼).
# 출처: 1. data_fetcher_and_db/core (api_fetchers_land.py·collect_data_land.py).
DS_GROUPS = {
    "historical": [
        ("ASOS 관측", ["solar_rad_seosan", "temp_c_seosan", "wind_spd_daegwallyeong"]),
        ("KPX 수급 sukub", ["real_demand_land", "supply_cap_land"]),
        ("KPX 발전실적", ["renew_gen_total_kr", "gen_gas_kr", "gen_solar_market_kr"]),
        ("KPX DA·SMP", ["land_est_demand_da", "smp_land_da"]),
        ("파생 용량·이용률", ["gen_solar_utilization_kr", "gen_wind_utilization_kr"]),
    ],
    "forecast": [
        ("KIMG 기상예보", ["radiation_seosan", "temp_seosan", "wind_spd_10m_daegwallyeong",
                        "rainfall_seosan"]),
        ("KPX DA·SMP", ["land_est_demand_da", "smp_land_da"]),
        ("서빙 5단계 수요", ["est_demand_land", "est_true_demand_land"]),
        ("서빙 6단계 신재생", ["est_market_renew_land", "est_net_load_land", "est_solar_util_land"]),
        ("서빙 7단계 가스", ["est_gas_gen_land", "est_gas_sendout_ton_land"]),
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


def render_data_status():
    st.subheader("데이터 적재 현황 (전국 DB)")

    # 컨트롤 — 테이블·기간(프리셋/직접)·미래 지평(forecast). 탭 위 본문 배치.
    c1, c2, c3 = st.columns([1.1, 2.2, 2.7])
    table = c1.radio("테이블", ["historical", "forecast"], key="ds_table", horizontal=True)
    psel = c2.radio("조회 기간(과거)", list(PAST_PRESET) + ["직접 선택"], index=1,
                    key="ds_past", horizontal=True)
    if psel == "직접 선택":
        lo, hi = C.table_range("land", table)
        rng = c3.date_input(
            "기간 (forecast는 미래 날짜도 선택 가능)",
            value=(max(pd.Timestamp(lo), TODAY - pd.Timedelta(days=30)).date(),
                   min(pd.Timestamp(hi), TODAY).date()),
            min_value=pd.Timestamp(lo).date(), max_value=pd.Timestamp(hi).date(),
            key=f"ds_range_{table}")
        if len(rng) != 2:
            st.info("기간(시작·끝)을 모두 선택하세요.")
            return
        start, end = pd.Timestamp(rng[0]), pd.Timestamp(rng[1])
    else:
        start, end = TODAY - pd.Timedelta(days=PAST_PRESET[psel]), TODAY
        if table == "forecast":
            fsel = c3.radio("미래 지평", list(FUT_PRESET), index=0, key="ds_fut",
                            horizontal=True)
            end = (pd.Timestamp(C.table_range("land", "forecast")[1]).normalize()
                   if FUT_PRESET[fsel] is None else TODAY + pd.Timedelta(days=FUT_PRESET[fsel]))
    s, e = _day_bounds(start, end)
    st.caption(f"`{table}` · {start:%Y-%m-%d} ~ {end:%Y-%m-%d}"
               + (f" (오늘+{(end - TODAY).days}일)" if end > TODAY else ""))

    groups = DS_GROUPS[table]
    tab_sum, tab_full, tab_db = st.tabs(
        ["적재 히트맵 — fetcher 요약", "적재 히트맵 — 전체 피처", "DB 직접 조회"])

    with tab_sum:
        heat = C.coverage_heat("land", table, s, e)
        reps, labels = [], []
        for gname, cols in groups:
            for col in cols:
                if col in heat.index:
                    reps.append(col)
                    labels.append(f"[{gname}]  {col}")
        sub = heat.loc[reps]
        sub.index = labels
        _coverage_heatmap(sub, end)
        with st.expander("항목별 신선도 요약"):
            st.dataframe(C.coverage_table("land"), width="stretch", hide_index=True)
            st.caption("수집은 crontab 백그라운드에서만 갱신됩니다(API 한도 보호 — 사용자 트리거 없음). "
                       "예측(est_*)은 서빙 5→6→7 사전 적재분입니다.")

    with tab_full:
        heat = C.coverage_heat("land", table, s, e)
        _coverage_heatmap(heat, end)

    with tab_db:
        cols = [c for c in C.table_columns("land", table) if c != "timestamp"]
        default = [g[1][0] for g in groups if g[1][0] in cols]   # fetcher별 대표 1개씩
        sel = st.multiselect("컬럼 선택", cols, default=default, key=f"ds_cols_{table}")
        use = ["timestamp"] + (sel if sel else cols)
        df = C.query("land", f"SELECT {', '.join(use)} FROM {table} "
                             "WHERE timestamp BETWEEN ? AND ? ORDER BY timestamp", (s, e))
        st.dataframe(df, width="stretch", height=560)
        st.caption(f"{len(df):,}행 × {len(use)}컬럼 — 헤더 클릭으로 정렬, 읽기 전용. "
                   "기본 선택 = API fetcher별 대표 컬럼 1개씩.")


if menu == "종합":
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

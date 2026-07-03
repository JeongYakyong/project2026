# -*- coding: utf-8 -*-
"""전국 페이지 — 수급 예측(종합브리핑/예측 확인/에너지 믹스/장지평 예측) · 예측 검증 · 데이터 현황 · 외부 연동 · 관리자메뉴."""
import os
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as C
import brief_ai as B
import brief_store as BS
import gas_price_store as GP

# API 공개 주소 — 도메인이 바뀌면 여기 또는 환경변수(SERVE_API_PUBLIC_URL)만 고친다.
API_PUBLIC_DEFAULT = os.environ.get("SERVE_API_PUBLIC_URL", "https://gascast.gonetis.com/api")
# 서버 자체 점검·미리보기용 내부 주소 — 공개 주소는 공유기 특성상 서버 자신이 못 불러 '꺼짐'으로 오인될 수 있다.
API_LOCAL_URL = os.environ.get("SERVE_API_LOCAL_URL", "http://127.0.0.1:8800")

C.page_header(
    "GASCAST · 전국", "국가 가스수급 예측 플랫폼", "",
    [("수요", C.COLOR["demand"]), ("신재생", C.COLOR["renew"]),
     ("순 부하", C.COLOR["net_load"]), ("가스", C.COLOR["gas"])])
menu = st.sidebar.radio("메뉴", ["수급 예측", "예측 검증", "데이터 현황", "외부 연동", "관리자메뉴"])


# 예측 제공 범위 일시 축소 안내 — 세션당 1회 팝업
@st.dialog("예측 제공 범위 안내")
def _horizon_notice():
    st.markdown(
        "기상청 수치예보 생산부서 정책으로 **2026-06-14부터** 예측 제공 범위가 "
        "**D+15 → D+12**로 일시 축소되었습니다.\n\n"
        "기상청 제공정책 변경 시 D+15까지 자동으로 다시 확대됩니다.")
    if st.button("확인", type="primary", width="stretch"):
        st.rerun()


if not st.session_state.get("hz_notice_seen"):
    st.session_state["hz_notice_seen"] = True
    _horizon_notice()

TODAY = pd.Timestamp.now().normalize()
ORIGIN = TODAY - pd.Timedelta(days=1)  # 어제 23:00 발행 가정(사전 적재)


def _day_bounds(d0: pd.Timestamp, d1: pd.Timestamp) -> tuple[str, str]:
    return d0.strftime("%Y-%m-%d 00:00:00"), d1.strftime("%Y-%m-%d 23:00:00")


def missing_forecast_block(day: pd.Timestamp, key: str):
    """선택 구간 예측이 없을 때 안내 (보유 범위 표시)."""
    lo, hi = C.land_date_range()
    st.warning(f"선택한 구간의 예측이 아직 없습니다. 예측 보유 범위: **{lo} ~ {hi}**.")


# ================================================================ 수급 예측
def render_forecast_check():
    """예측 확인 탭 — 선택일 24시간 예측(가스 중심) + 수요 실측. 기본 = 오늘."""
    day, _, cap = C.day_navigator("fchk")
    mode, value = "latest", None

    df = C.land_day_compare(day, mode=mode, value=value)
    if df["est_gas_gen_land"].isna().all():
        missing_forecast_block(day, key="fchk_gen")
        return

    render_series_compare(df, prefix="fchk", gear_col=cap)
    origin = C.land_forecast_origin(day)
    st.caption(f"{day:%Y-%m-%d} 예측 데이터 발행 시간 - {origin} 예측" if origin
               else f"{day:%Y-%m-%d}")

    # 하단 — 선택일 송출량 지표 5개 (전국 천연가스 = 발전용 + 도시가스 보조)
    ton = df["est_gas_sendout_ton_land"]
    gen_ton = float(ton.sum())
    daily = C.land_daily_sendout(day, day)
    cg_vals = daily["citygas_ton"].dropna() if "citygas_ton" in daily.columns else pd.Series(dtype=float)
    has_cg = not cg_vals.empty
    cg_ton = float(cg_vals.sum()) if has_cg else 0.0
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("전국 천연가스 예상 송출량", f"{gen_ton + cg_ton:,.0f} TON",
              help="발전용 가스 + 도시가스(참고)의 하루 합. 둘 다 단위는 TON입니다.")
    c2.metric("발전용 가스 예상 송출량", f"{gen_ton:,.0f} TON",
              help="시간당 송출량 예측의 하루 합")
    c3.metric("도시가스 예상 송출량", f"{cg_ton:,.0f} TON" if has_cg else "—",
              help="난방 중심·기온 기반의 하루 단위 보조 예측. 일 실측이 없어 참고값입니다.")
    c4.metric("시간당 최대 예상 송출량", f"{ton.max():,.0f} TON/h")
    c5.metric("시간당 최소 예상 송출량", f"{ton.min():,.0f} TON/h")

    st.markdown("##### AI 브리핑")
    B.render_brief_display("fchk", day)  # 선택일이 속한 지평 밴드 종합을 자동 표시(생성은 관리자메뉴)


def render_daily_sendout():
    """일일 송출량(TON/day) — 발전용 막대 + 도시가스 on/off 누적(총 송출량).

    발전용 = 시간당 예측의 하루 합, 도시가스 = 하루 단위 보조 예측. 둘 다 단위 TON이라 그대로 더한다.
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
        help="켜면 발전용 위에 도시가스(난방 중심·참고값)를 쌓아 '총 송출량'으로 봅니다. "
             "발전용·도시가스 모두 단위는 TON입니다.")

    daily = C.land_daily_sendout(start, end)
    if daily.empty or daily["gen_ton"].dropna().empty:
        st.warning(f"선택 구간의 일일 송출량 예측이 없습니다. (예측 보유 범위: {lo} ~ {hi})")
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

    st.caption("막대 높이 = 그날 총 송출량(발전용 + 도시가스), 단위 TON. "
               "도시가스는 기온 기반의 **참고값**으로, 일 단위 실측이 없어 정확도 확인에 제한이 있습니다.")


# 누적 그룹 색 — 전력거래소 차트와 비슷한 톤 (원전 주황·가스 노랑·BTM/PPA 연분홍)
MIX_COLORS = {"원전": "#f28e2b", "기타발전": "#9c755f", "가스": "#edc948",
              "태양광+풍력": "#59a14f", "BTM+PPA": "#f1a7c1"}


def _rgba(hex_color: str, alpha: float) -> str:
    h = hex_color.lstrip("#")
    return f"rgba({int(h[0:2], 16)},{int(h[2:4], 16)},{int(h[4:6], 16)},{alpha})"


def render_gen_mix():
    """에너지 믹스 탭 — 발전원별 누적 발전 믹스(실측) + 예측 dot(누적기준 정렬)."""
    day, _, cap = C.day_navigator("mix")
    mode, value = "latest", None

    mix = C.land_day_mix(day)
    # 미수집 시간 절단: 가스 발전 0은 물리적으로 불가(항상 켜짐) → 0/결측 시간은 그래프에서 제외
    valid = mix["가스"].notna() & (mix["가스"] > 0) & mix["원전"].notna()
    if not valid.any():
        st.warning("이 날짜의 발전실적이 아직 수집되지 않았습니다. "
                   "예측은 '예측 확인' 탭에서 볼 수 있습니다.")
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
    # 총수요 기준 예측 = 계량수요 예측 + BTM/PPA(실측). 예측 아카이브는 계량수요만 보관.
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
    C.help_expander(
        "**색 띠(실측 누적)**: 원전(기저) → 기타발전(석탄·수력·양수·유류 등) → 가스 → "
        "태양광+풍력(시장) → BTM+PPA(추정) 순서로 쌓입니다.\n\n"
        "**선**: 총수요 실선 = 계량수요 + BTM/PPA. 수요 예측 점선도 같은 기준으로 맞춰 비교합니다.\n\n"
        "**예측 점선의 위치**: 가스·태양광+풍력 예측은 아래 누적을 더해 실측 띠의 윗변과 같은 기준에 "
        "그립니다 — 점선이 띠 경계에서 벌어진 만큼이 예측 오차입니다.\n\n"
        "아직 수집되지 않은 시간(오늘 잔여·미래)은 면적을 그리지 않습니다.")


# 공통 비교 plot 시리즈 — (라벨, 컬럼, 종류, 색, 기본 선택). 예측 확인·장지평 공용.
COMPARE_SERIES = [
    ("전력수요 실측", "real_demand_land", "act", C.COLOR["demand"], True),
    ("전력수요 예측", "est_demand_land", "est", C.COLOR["demand"], True),
    ("가스발전 실측", "gen_gas_kr", "act", C.COLOR["gas"], True),
    ("가스발전 예측", "est_gas_gen_land", "est", C.COLOR["gas"], True),
    ("천연가스 송출량(TON/h)", "est_gas_sendout_ton_land", "ton", C.COLOR["ton"], True),
    ("신재생 실측", "renew_gen_total_kr", "act", C.COLOR["renew"], True),
    ("신재생 예측", "est_market_renew_land", "est", C.COLOR["renew"], True),
    ("순 부하 실측", "real_net_load", "act", C.COLOR["net_load"], False),
    ("순 부하 예측", "est_net_load_land", "est", C.COLOR["net_load"], False),
    ("KPX 수요예측(DA)", "land_est_demand_da", "kpx", "#17becf", False),
]


def render_series_compare(df: pd.DataFrame, prefix: str, height: int = 460,
                          gear_col=None, show_ton: bool = True):
    """⚙️ 선택형 예측 vs 실측 비교 plot — 예측 확인·장지평 탭 공용 컴포넌트.

    gear_col을 주면 ⚙️ popover를 그 자리(예: 네비게이터 행)에 렌더.
    show_ton=False면 천연가스 송출량(TON/h) 보조축 계열을 빼고 MW 계열만 본다(장지평=일별 집중).
    """
    series = [s for s in COMPARE_SERIES if show_ton or s[2] != "ton"]
    if gear_col is None:
        gear_col, _ = st.columns([1, 5])
    with gear_col.popover("⚙️ 표시 데이터"):
        chosen = {label: st.checkbox(label, value=default, key=f"{prefix}_s_{col}")
                  for label, col, _, _, default in series}

    cd, tmpl = C.hz_hover(df)
    fig = C.make_fig(height=height)
    use_y2 = False
    for label, col, kind, color, _ in series:
        if not chosen[label]:
            continue
        if kind == "act":
            C.add_actual(fig, df["timestamp"], df[col], f"{label} (MW)", color)
        elif kind == "kpx":
            fig.add_scatter(x=df["timestamp"], y=df[col], name=f"{label} (MW)",
                            line=dict(color=color, dash="dash", width=2),
                            hovertemplate="%{x|%m-%d %H시} · %{y:,.0f} MW<br>"
                            "KPX 하루전 발표(D+1)<extra>%{fullData.name}</extra>")
        elif kind == "ton":
            # 송출량(TON/h)은 가스 발전 MW의 약 0.15배라 같은 축에선 바닥에 깔린다
            # → 오른쪽 보조축(y2)으로 올려 같은 plot 안에서 읽기 쉽게 한다.
            fig.add_scatter(x=df["timestamp"], y=df[col], name=label, yaxis="y2",
                            mode="lines", line=dict(color=color, dash="dot", width=2.5),
                            customdata=cd,
                            hovertemplate="%{x|%m-%d %H시} · %{y:,.0f} TON/h<br>"
                            "%{customdata[0]}<extra>%{fullData.name}</extra>")
            use_y2 = True
        else:
            C.add_forecast(fig, df["timestamp"], df[col], f"{label} (MW)", color,
                           customdata=cd, hovertemplate=tmpl)
    if use_y2:
        fig.update_layout(
            margin=dict(t=30, b=10, l=10, r=80),
            yaxis2=dict(title=dict(text="송출량 (TON/h)", standoff=8,
                                   font=dict(size=12, color=C.COLOR["ton"])),
                        overlaying="y", side="right", showgrid=False, rangemode="tozero",
                        tickfont=dict(size=11.5, color=C.COLOR["ton"])))
    fig.update_xaxes(range=[df["timestamp"].min(), df["timestamp"].max()])
    st.plotly_chart(fig, width="stretch", key=f"{prefix}_series")


def _hero_gas(day, dplus):
    """선택일 예상 가스 송출량(+시계열)·전력수요(예측·실측)·순 부하 dict — hero 오른쪽 패널용.

    예측 없으면 None. 시계열은 24시간 값 리스트(None=결측)로 넘겨 패널에서 스파크라인으로 그린다.
    """
    gdf = C.land_day_compare(day)
    gton = gdf["est_gas_sendout_ton_land"]
    if gton.dropna().empty:
        return None
    daily = C.land_daily_sendout(day, day)
    cg = daily["citygas_ton"].dropna() if "citygas_ton" in daily.columns else pd.Series(dtype=float)
    cg_ton = float(cg.sum()) if not cg.empty else None
    gen = float(gton.sum())

    def spark(s):
        return [None if pd.isna(v) else round(float(v)) for v in s]

    # 발전용 가스 스파크라인 = 발전량(MW) 예측 + 실측(gen_gas_kr) 오버레이 — 전력수요와 동일 방식
    ggen = gdf["est_gas_gen_land"]
    ggen_real = gdf["gen_gas_kr"] if "gen_gas_kr" in gdf.columns else pd.Series(dtype=float)
    dem, dem_real = gdf["est_demand_land"], gdf["real_demand_land"]
    nl = gdf["est_net_load_land"]
    return {"dplus": int(dplus), "gen_ton": gen,
            "max_ton": float(gton.max()), "min_ton": float(gton.min()),
            "citygas_ton": cg_ton, "total_ton": gen + (cg_ton or 0.0),
            "gas_spark": spark(ggen),
            "gas_real_spark": spark(ggen_real) if ggen_real.notna().any() else None,
            "demand_peak": float(dem.max()) if dem.notna().any() else None,
            "demand_spark": spark(dem),
            "demand_real_spark": spark(dem_real) if dem_real.notna().any() else None,
            "nl_min": float(nl.min()) if nl.notna().any() else None,
            "nl_max": float(nl.max()) if nl.notna().any() else None}

def render_hero():
    """종합 메인 hero — 전국 기상 지도 + 간결 날씨 패널 + 예상 가스 송출량 패널.

    날씨(지도) → 신재생 강도(왼쪽 패널) → 가스 송출(오른쪽 패널)을 한 화면으로 잇는다.
    권역별 상세(예보 대 실측)는 아래 expander 로 접어 둔다.
    """
    import streamlit.components.v1 as components
    import weather_map as W

    if not W.GEOJSON.exists():
        st.warning("지도 데이터 파일을 찾을 수 없어 기상 지도를 표시할 수 없습니다.")
        return

    day, _, cap = C.day_navigator("hero", refresh=False)
    dplus = (day - TODAY).days
    origin = C.land_forecast_origin(day)
    cap.caption(f"{day:%Y-%m-%d} 예측 데이터 발행 시간 - {origin} 예측" if origin
                else f"{day:%Y-%m-%d}")

    date = day.strftime("%Y-%m-%d")
    zones = W.zone_day(date)
    util = W.national_util(date)
    if all(not z["ok"] for z in zones.values()) and util["solar"] is None:
        st.warning(f"{date} 예보가 없습니다 (KIMG 예보 보유 범위 밖).")
        return
    util_act = W.national_util_actual(date) if dplus <= 0 else None
    st.iframe(
        W.build_html(day, dplus, zones, util, gas=_hero_gas(day, dplus),
                    util_act=util_act, humidity=W.national_humidity(date)),
        height=620)

    # 지도 아래 — AI 종합 브리핑(관리자메뉴/서버가 생성한 것을 가져와 표시만) → 권역별 상세
    st.markdown("##### AI 종합 브리핑")
    B.render_brief_display("hero", day)  # 선택일이 속한 지평 밴드 종합을 자동 표시

    with st.expander("권역별 상세 · 예보 대 실측 (8권역 표)"):
        _hero_weather_table(date, dplus, zones)
    C.help_expander(
        "**지도 면 색(초록)** = 신재생 발전 강도(설비용량 × 활성도) — 진할수록 강합니다. "
        "표시 설정에서 일사·풍속 모드로 바꿀 수 있습니다.\n\n"
        "**권역별 표 읽는 법** — 과거·당일은 셀에 `예보 → 실측`을 나란히 표기합니다. "
        "실측이 아직 수집되지 않은 구간은 예보만 표시됩니다.\n"
        "- 기상 실측 = 기상청 지상 관측, 이용률 실측 = 전력거래소 발전실적으로 계산\n\n"
        "**활성도** = 그 날씨에서 기대되는 전국 이용률(과거 실측으로 교정) — 권역에는 상대 신호로 적용합니다.\n\n"
        "**권역 기상** = 대표 관측소 예보를 사용합니다(영광 → 광주·전남/전북, 포항 → 경남/경북 공유). "
        "제주는 제주 관측 데이터(고산)를 씁니다. 설비용량은 전국 총량에 지역 비율을 적용한 추정값입니다.\n\n"
        "출처: 기상청 수치예보 · 자체 이용률 예측 모델.")

def _hero_weather_table(date, dplus, zones):
    """hero 아래 expander — 8권역 기상상태 표(예보 → 실측 병기). 이용률 카드는 왼쪽 패널로 이동."""
    import weather_map as W

    # 8권역 표 — 과거·당일은 실측 병기: 셀 = 예보 → 실측 (기상 ASOS).
    past = dplus <= 0
    act_zones = W.zone_actual(date) if past else {}

    def cell(est, act):
        return est if act is None else f"{est} → {act}"

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
    st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True, height=320)
    if past:
        st.caption("셀 표기 = **예보 → 실측** · 실측이 아직 없는 구간은 예보만 표시됩니다.")


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

    mode, value = "latest", None
    df = C.land_range_compare(start, end, mode=mode, value=value)
    if df.empty or df["est_demand_land"].isna().all():
        st.warning(f"선택 구간의 예측이 없습니다. (예측 보유 범위: {lo} ~ {hi})")
        return

    ton = df["est_gas_sendout_ton_land"].sum()
    cost = C.gas_cost_won(df["timestamp"], df["est_gas_sendout_ton_land"]).sum()
    gm = C.error_metrics(df["est_gas_gen_land"], df["gen_gas_kr"])
    c1, c2, c3 = st.columns(3)
    c1.metric(f"{start:%m-%d}~{end:%m-%d} ({n_days}일) 가스 송출량(예측 합)", f"{ton:,.0f} TON")
    c2.metric("가스비(환산)", f"{cost / 1e8:,.0f} 억원")
    if gm:
        # bias는 delta(아랫줄) 대신 라벨 옆에 — 카드 3개 높이를 똑같이 유지
        c3.metric(f"가스 MAPE · bias {gm['bias']:+.1f}%", f"{gm['mape']:.1f} %")

    render_series_compare(df, prefix="lh", height=480, show_ton=False)
    st.caption("각 날짜의 **가장 최근 발행 예측**을 이어 붙인 미래 전망입니다 · "
               "미래 구간은 실측이 없어 예측만 표시됩니다.")

    with st.expander("일일 송출량 — 발전용 + 도시가스 합산 (일단위 TON/day)", expanded=True):
        render_daily_sendout()


# ================================================================ 예측 검증
def _mark_selected_day(fig, day: pd.Timestamp, label: bool = True, **kw):
    """선택일(구간 끝) 시작 위치에 세로 점선 표시 — 검증 차트 공용.

    plotly add_vline은 날짜 축에 Timestamp를 주면 주석 위치 계산에서 깨진다 → epoch(ms)로 우회.
    """
    x = day.timestamp() * 1000
    opts = dict(line_dash="dot", line_color="#dc2626", opacity=0.55)
    if label:
        opts.update(annotation_text="선택일", annotation_position="top left",
                    annotation_font=dict(size=11, color="#dc2626"))
    fig.add_vline(x=x, **opts, **kw)


def render_forecast_menu():
    # 검증 시계열은 "어느 지평(D+k)을 볼지"가 핵심 — 정밀 비교는 '정확도 평가' 탭이 담당.
    day, _, cap = C.day_navigator("fm")
    meta = C.land_horizon_meta()
    c_hz, c_win = cap.columns([2.1, 1.6], vertical_alignment="bottom")
    k = c_hz.slider("지평 D+k (며칠 전 예측인지)", meta["h_lo"], meta["h_hi"], 1,
                    key="fm_hzk",
                    help="k를 올릴수록 더 먼 미래를 내다본 예측으로 바뀝니다 —\n\n "
                         "지평이 길어질수록 오차가 커지는 '오차 증폭'을 확인할 수 있습니다.")
    WIN_OPTS = {"3일": 3, "7일": 7, "12일": 12, "15일": 15}
    with c_win, st.container(key="fm_win_box"):     # 2×2 pill — 전용 CSS는 common._CSS
        wsel = st.segmented_control("표시 구간", list(WIN_OPTS), default="7일", key="fm_win",
                                    help="선택일까지 지난 N일을 표시합니다. 15일은 기상청 예보 "
                                         "축소(D+13~15)로 일부 구간이 빌 수 있습니다.") or "7일"
    # 선택일 = 구간의 끝 — 기본(오늘)이면 지난 N일이 꽉 찬 화면. 지평(D+k)만 바꿔 오차 증폭을 비교.
    win = WIN_OPTS[wsel]
    end = day
    start = end - pd.Timedelta(days=win - 1)
    mode, value = "fixed", k

    df = C.land_range_compare(start, end, mode=mode, value=value)
    if df.empty or (df["est_demand_land"].isna().all() and df["real_demand_land"].isna().all()):
        missing_forecast_block(start, key="fm_gen")
        return

    t1, t2, t3, t4, t5 = st.tabs(
        ["전력수요", "순 부하(Net Load)", "천연가스", "정확도 평가", "지평별 정확도"])
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
        _mark_selected_day(fig, day)
        st.plotly_chart(fig, width="stretch")
        st.caption("KPX 수요예측(DA)은 전력거래소 하루 전 발표값으로, 표시 지평이 D+1일 때만 비교가 가능합니다.")

    with t2:
        fig = C.make_fig()
        C.add_actual(fig, ts, df["real_net_load"], "순 부하 실측", C.COLOR["net_load"])
        C.add_forecast(fig, ts, df["est_net_load_land"], "순 부하 예측", C.COLOR["net_load"],
                       customdata=cd, hovertemplate=tmpl)
        C.add_forecast(fig, ts, df["est_market_renew_land"], "신재생 예측(참고)", C.COLOR["renew"],
                       customdata=cd, hovertemplate=tmpl)
        _mark_selected_day(fig, day)
        st.plotly_chart(fig, width="stretch")
        st.caption("순 부하(Net Load) = 전력수요 − 신재생 발전. 실측도 같은 기준으로 재구성해 비교합니다.")

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
        _mark_selected_day(fig, day)
        st.plotly_chart(fig, width="stretch")
        st.caption("송출량(TON) = 발전량(MWh) × 0.1521 — 발전 효율 기준 환산계수입니다.")

    with t4:
        render_validation(df, day)

    with t5:
        st.caption("D+1 ~ D+15 지평별 정확도를 비교합니다. 각 지평별 오차의 증폭을 확인할 수 있습니다.")
        render_horizon_accuracy()


# ================================================================ 검증 (예측 vs 실측, 하루 단위)
CHAIN_PANELS = [  # (제목, est 컬럼, 실측 컬럼, 색, 지표종류 — 신재생은 심야 분모 문제로 nMAE)
    ("수요", "est_demand_land", "real_demand_land", C.COLOR["demand"], "mape"),
    ("신재생", "est_market_renew_land", "renew_gen_total_kr", C.COLOR["renew"], "nmae"),
    ("순 부하", "est_net_load_land", "real_net_load", C.COLOR["net_load"], "mape"),
    ("가스", "est_gas_gen_land", "gen_gas_kr", C.COLOR["gas"], "mape"),
]


def render_validation(df: pd.DataFrame, day: pd.Timestamp | None = None):
    """체인 스택 4행 검증 — 구간은 예측 검증 메뉴의 공통 시간 선택을 따른다."""
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
    if day is not None:
        _mark_selected_day(fig, day, label=False, row="all", col=1)
    st.plotly_chart(fig, width="stretch")
    st.caption("신재생 발전이 늘면 순 부하가 줄고 가스 발전도 줄어듭니다 — 같은 시각을 위아래로 비교해 보세요. "
               "실측은 전력거래소 실시간 자료로 채워지며, 오차를 숨기지 않고 그대로 보여줍니다.")


# 지평별 곡선·일별 추이·카드 공용 — (라벨, land_horizon_accuracy 컬럼, COLOR 키, 지표).
HZ_ACC_SPECS = [("수요", "수요 MAPE", "demand", "MAPE"),
                ("신재생", "신재생 nMAE", "renew", "nMAE"),
                ("순 부하", "순 부하 MAPE", "net_load", "MAPE"),
                ("가스", "가스 MAPE", "gas", "MAPE")]


def _show_horizon_curve(acc: pd.DataFrame):
    """지평별 정확도 곡선(x=지평·y=오차율) + 정확한 수치 표는 expander. 제주 '② 지평별 성능'과 같은 양식."""
    if acc.empty:
        st.caption("집계할 데이터가 없습니다.")
        return
    hz_num = [int(s[2:]) for s in acc.index]          # "D+3" → 3
    fig = C.make_fig(height=400, ytitle="오차율 (%)")
    for label, col, ckey, _kind in HZ_ACC_SPECS:
        if col in acc.columns:
            fig.add_scatter(x=hz_num, y=acc[col], name=label, mode="lines+markers",
                            line=dict(color=C.COLOR[ckey], width=2.2), marker=dict(size=6),
                            connectgaps=False,
                            hovertemplate="D+%{x} · %{y:.1f}%<extra>" + label + "</extra>")
    fig.update_xaxes(title="지평 (며칠 전에 예측했는지)", tickmode="array",
                     tickvals=hz_num, ticktext=list(acc.index))
    st.plotly_chart(fig, width="stretch")
    st.caption("지평이 길수록(오른쪽) 오차가 커지는 추세 · 수요·순 부하·가스=MAPE, 신재생=nMAE.")
    with st.expander("정확한 수치 표로 보기"):
        st.dataframe(acc, width="stretch", height=560)


def render_daily_trend_land():
    """일별 정확도 추이 — 기간 + 지평 D+k. x=날짜·y=오차율(%). 제주 '① 일별 정확도 추이'를 전국에 이식.

    특정일 급등 = 그 날 기상 급변(비·구름) 신호. 데이터 = land_daily_error_history(fixed D+k).
    """
    meta = C.land_horizon_meta()
    PERIODS = {"1주": 7, "2주": 14, "한달": 30, "3개월": 92, "6개월": 183}
    # 라벨 글자를 좁은 컬럼에 따로 넣어 컨트롤 왼쪽에 가로로 붙임(세로 라벨 대신 한 줄).
    lp, cp, lh, ch, _ = st.columns([0.4, 3.4, 0.4, 1.1, 1.3], vertical_alignment="center")
    lp.markdown("**기간**")
    psel = cp.segmented_control("기간", list(PERIODS), default="한달", key="ldt_period",
                                label_visibility="collapsed") or "한달"
    lh.markdown("**지평**")
    k = ch.selectbox("지평", list(range(meta["h_lo"], meta["h_hi"] + 1)),
                     format_func=lambda d: f"D+{d}", key="ldt_hz",
                     label_visibility="collapsed", help="각 날짜를 k일 전에 예측한 값")
    days = PERIODS[psel]

    # 선택 지평 카드 — 최근 기간 전체에서 D+k 정확도(4개 모델 한눈). 지표종류는 아래 캡션에서 안내.
    cutoff = (TODAY - pd.Timedelta(days=days)).strftime("%Y-%m-%d")
    acc_h = C.land_horizon_accuracy(start=cutoff)
    hz_lbl = f"D+{k}"
    if not acc_h.empty and hz_lbl in acc_h.index:
        row = acc_h.loc[hz_lbl]
        cards = st.columns(4)
        for col, (title, ac_col, _ckey, _kind) in zip(cards, HZ_ACC_SPECS):
            v = row[ac_col] if ac_col in row and pd.notna(row[ac_col]) else None
            col.metric(title, "—" if v is None else f"{v:.1f} %")

    daily = C.land_daily_error_history(TODAY.strftime("%Y-%m-%d"), days=days, mode="fixed", value=k)
    if daily.empty or daily.dropna(how="all").empty:
        st.caption("이 기간·지평에 집계할 데이터가 없습니다.")
        return
    fig = C.make_fig(height=400, ytitle="오차율 (%)")
    for label, _col, ckey, _kind in HZ_ACC_SPECS:
        if label in daily.columns:
            fig.add_scatter(x=daily.index, y=daily[label], name=label, mode="lines+markers",
                            line=dict(color=C.COLOR[ckey], width=2.2), marker=dict(size=5),
                            connectgaps=False,
                            hovertemplate="%{x|%m-%d} · %{y:.1f}%<extra>" + label + "</extra>")
    st.plotly_chart(fig, width="stretch")


def render_horizon_accuracy():
    """지평별 정확도 — 일별 추이(꺾은선·카드) + 기간별/계절별 지평 곡선(꺾은선 + 표 expander)."""
    tabs = st.tabs(["일별 추이", "기간별", "봄", "여름", "가을", "겨울"])
    with tabs[0]:
        render_daily_trend_land()
    with tabs[1]:
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
        _show_horizon_curve(acc)
    for i, seas in enumerate(["봄", "여름", "가을", "겨울"], start=2):
        with tabs[i]:
            st.caption(f"{seas}({'·'.join(f'{m}월' for m in C.SEASON_MONTHS[seas])}) — 전 기간 발행본 대상")
            _show_horizon_curve(C.land_horizon_accuracy(season=seas))


# ================================================================ 데이터 현황
TALL_TABLES = {"est_horizon_land", "forecast_horizon"}
HZ_FULL = {"est_horizon_land": 15, "forecast_horizon": 16}   # 완전 발행본의 지평(KIMG≈15.5일)
PAST_PRESET = {"1주": 7, "1개월": 30, "2개월": 61, "3개월": 92}

# 항목 그룹별 대표 컬럼 — 히트맵 요약·DB 조회 기본 선택.
DS_GROUPS = {
    "historical": [
        ("기상 관측", ["solar_rad_seosan", "temp_c_seosan", "wind_spd_daegwallyeong"]),
        ("전력 수급", ["real_demand_land", "supply_cap_land"]),
        ("발전 실적", ["renew_gen_total_kr", "gen_gas_kr", "gen_solar_market_kr"]),
        ("하루전 예측·가격", ["land_est_demand_da", "smp_land_da"]),
        ("파생 용량·이용률", ["gen_solar_utilization_kr", "gen_wind_utilization_kr"]),
    ],
    "est_horizon_land": [
        ("전력수요 예측", ["est_demand_land"]),
        ("신재생·순 부하 예측", ["est_market_renew_land", "est_net_load_land"]),
        ("가스 발전·송출량 예측", ["est_gas_gen_land", "est_gas_sendout_ton_land"]),
    ],
    "forecast_horizon": [
        ("기상 예보", ["radiation_seosan", "temp_seosan",
                    "wind_spd_10m_daegwallyeong", "rainfall_seosan"]),
    ],
}


# 데이터 성격별 색 — 수집 현황 히트맵을 출처/성격으로 구분(셀 진하기 = 수집률).
DS_GROUP_COLORS = {
    "기상 관측": "#0891b2",
    "전력 수급": "#2563eb",
    "발전 실적": "#059669",
    "하루전 예측·가격": "#d97706",
    "파생 용량·이용률": "#7c3aed",
    "기타": "#94a3b8",
}


def _hist_group(col: str) -> str:
    """historical 컬럼 → 데이터 성격 그룹(전체 항목 히트맵 색 구분용). DS_GROUPS 대표 컬럼과 같은 분류."""
    c = col.lower()
    if col.endswith("_da") or c.startswith("smp_"):
        return "하루전 예측·가격"
    if "utilization" in c or "capacity" in c:
        return "파생 용량·이용률"
    if any(k in c for k in ("temp_c", "solar_rad", "wind_spd", "humid", "rainfall",
                            "cloud", "snow", "wd_cos", "wd_sin")):
        return "기상 관측"
    if "demand" in c or "supply" in c or "reserve" in c:
        return "전력 수급"
    if c.startswith("gen_") or "renew" in c or "net_load" in c:
        return "발전 실적"
    return "기타"


def _coverage_heatmap(heat: pd.DataFrame, end: pd.Timestamp, row_groups=None):
    """6시간 블록 수집률 히트맵. row_groups(행별 성격 그룹) 주면 그룹마다 다른 색(셀 진하기=수집률)."""
    import numpy as np
    import plotly.graph_objects as go

    cov = heat.values.astype(float)              # 실제 수집률 0~1
    fig = go.Figure()
    if row_groups is None:
        fig.add_trace(go.Heatmap(
            z=cov, x=heat.columns, y=heat.index,
            colorscale=[[0, "#f1f5f9"], [1, "#059669"]], zmin=0, zmax=1,
            hovertemplate="%{y}<br>%{x} ~ +6h · 수집률 %{z:.0%}<extra></extra>", showscale=False))
    else:
        # 그룹마다 색띠 1개씩 — z를 그룹 띠 [i/N,(i+1)/N] 안에서 수집률로 채운다(단일 트레이스라 hover 정확).
        order = list(dict.fromkeys(row_groups))
        n = len(order)
        gi = np.array([order.index(g) for g in row_groups])[:, None]   # (행,1)
        # 수집률에 0.999를 곱해 띠 경계에 정확히 안 닿게(경계값이 다음 띠 연한색으로 튀는 것 방지).
        z = np.where(np.isnan(cov), np.nan, (gi + np.clip(cov, 0, 1) * 0.999) / n)
        light = "#f1f5f9"
        cs = []
        for i, g in enumerate(order):                                   # 띠마다 연한색→그룹색, 경계는 급단차
            cs += [[i / n, light], [(i + 1) / n, DS_GROUP_COLORS.get(g, "#94a3b8")]]
        fig.add_trace(go.Heatmap(
            z=z, x=heat.columns, y=heat.index, customdata=cov, hoverongaps=False,
            colorscale=cs, zmin=0, zmax=1, showscale=False,
            hovertemplate="%{y}<br>%{x} ~ +6h · 수집률 %{customdata:.0%}<extra></extra>"))
    fig.update_layout(height=max(360, 16 * len(heat.index) + 80),
                      margin=dict(t=10, b=10, l=10, r=10),
                      yaxis=dict(autorange="reversed", tickfont=dict(size=11)))
    if end >= TODAY:
        fig.add_vline(x=pd.Timestamp.now(), line_dash="dot", line_color="#dc2626")
    st.plotly_chart(fig, width="stretch")
    if row_groups is not None:
        used = list(dict.fromkeys(row_groups))
        legend = " &nbsp; ".join(
            f"<span style='color:{DS_GROUP_COLORS.get(g, '#94a3b8')};font-size:1.1em'>■</span> {g}"
            for g in used)
        st.markdown(f"<div style='font-size:.85rem;color:#64748b'>{legend}</div>",
                    unsafe_allow_html=True)


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
    st.caption(f"{len(df):,}행 × {len(use)}컬럼")


def _ds_timestamp(table: str):
    """timestamp 단일키 테이블(historical) — 6시간 수집률 히트맵 + DB 직접 조회."""
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
    st.caption(f"{C.TABLE_LABEL.get(table, table)} · {start:%Y-%m-%d} ~ {end:%Y-%m-%d}")

    tab_sum, tab_full, tab_db = st.tabs(
        ["수집 현황 — 주요 항목", "수집 현황 — 전체 항목", "DB 직접 조회"])
    with tab_sum:
        heat = C.coverage_heat("land", table, s, e)
        reps, labels, rgroups = [], [], []
        for gname, cols in groups:
            for col in cols:
                if col in heat.index:
                    reps.append(col); labels.append(f"[{gname}]  {col}"); rgroups.append(gname)
        sub = heat.loc[reps]; sub.index = labels
        _coverage_heatmap(sub, end, row_groups=rgroups)
        with st.expander("항목별 최신 현황 요약"):
            st.dataframe(C.coverage_table("land"), width="stretch", hide_index=True)
    with tab_full:
        heat_full = C.coverage_heat("land", table, s, e)
        _coverage_heatmap(heat_full, end, row_groups=[_hist_group(c) for c in heat_full.index])
    with tab_db:
        _ds_db_browser(table, s, e, [g[1][0] for g in groups])


def _ds_tall(table: str):
    """tall 아카이브(base×지평) — 발행본별 저장 완성도 표 + DB 직접 조회."""
    full = HZ_FULL[table]
    cov = C.query("land", f"SELECT base, COUNT(DISTINCT horizon_d) 지평수, COUNT(*) 행수, "
                          f"MIN(timestamp) 목표시작, MAX(timestamp) 목표끝 "
                          f"FROM {table} GROUP BY base ORDER BY base DESC")
    cov["완성도%"] = (cov["행수"] / (full * 24) * 100).round(0).clip(upper=100)
    n_full = int((cov["완성도%"] >= 100).sum())
    m1, m2, m3 = st.columns(3)
    m1.metric("발행본(base) 수", f"{len(cov):,}")
    m2.metric(f"완전 발행본(D+1~{full})", f"{n_full:,}")
    m3.metric("최신 발행본 완성도", f"{cov['완성도%'].iloc[0]:.0f}%" if len(cov) else "—")
    st.caption(f"{C.TABLE_LABEL.get(table, table)} - 발행본별 완성도")
    st.dataframe(cov.head(45), width="stretch", hide_index=True, height=420)

    with st.expander("항목별 최신 현황 요약"):
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
    st.subheader("데이터 현황 (전국)")
    table = st.segmented_control("저장소", ["historical", "est_horizon_land", "forecast_horizon"],
                                 default="historical", key="ds_table",
                                 format_func=lambda t: C.TABLE_LABEL.get(t, t)) or "historical"
    if table in TALL_TABLES:
        _ds_tall(table)
    else:
        _ds_timestamp(table)


def render_run_ops():
    """관리자메뉴 — 예측 체인·수집·브리핑 생성 수동 실행. 메뉴 전체가 비밀번호 잠금(C.ops_gate)."""
    if not C.ops_gate():
        return
    st.subheader("예측 실행 — 수요 → 신재생 → 가스")
    st.caption("기상 예보(forecast_horizon)를 입력으로 수요·신재생·가스 예측을 만들어 "
               "est_horizon_land 에 저장합니다. 서버가 매일 06:00에 자동 실행하는 것과 같은 작업입니다.")

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

    dry = st.toggle("dry-run (산출만, 저장 안 함)", value=False, key="ops_dry")
    if dry:
        args += ["--no-write"]

    st.code('python "7. land_gas_forecaster/serve_chain_land_new.py" '
            + (" ".join(args) if args else "  # 최신 base"), language="bash")

    if st.button("▶ 예측 실행", type="primary", key="ops_run"):
        with st.spinner("예측 실행 중… (base 당 수 초)"):
            rc, out = C.run_script(C.SERVE_CHAIN_LAND, args)
        if rc == 0:
            st.success("완료 (종료코드 0)")
            if not dry:
                st.cache_data.clear()   # 새 저장분이 다른 메뉴 조회에 반영되도록 캐시 무효화
                st.caption("est_horizon_land 갱신 → 조회 캐시 초기화. 다른 메뉴에서 최신 예측 확인 가능.")
        else:
            st.error(f"실패 (종료코드 {rc})")
        st.code(out or "(출력 없음)")

    st.divider()
    st.subheader("데이터 수집 (KMA/KPX API)")
    st.caption("⚠ API 한도 보호 — 평소엔 서버 cron 전용. 수동 실행은 한도에 주의하세요. "
               "기상은 완결성 auto-resume 라 재실행해도 완전한 base 는 콜 없이 skip.")

    col_f, col_h = st.columns(2)
    with col_f:
        st.markdown("**① 기상예보 → forecast_horizon**")
        fmode = st.radio("대상", ["최신", "최근 N개(backfill)"], key="cf_mode")
        futc = st.selectbox("발표 시각 (UTC)",
                            ["12Z (기본·cron 동일)", "18Z", "06Z", "00Z"], key="cf_utc")
        futc_h = int(futc[:2])
        st.caption("12z 발표에 문제가 있을 때(예: 장지평 빈 응답) 다른 발표 시각으로 "
                   "수동 수집합니다. 지평(D+n)은 발표 시각의 KST 날짜 기준이라 "
                   "18z는 KST 다음날 새벽 3시 발표 → 같은 날 12z보다 D+1 시작일이 하루 늦습니다.")
        fargs = ["--region", "land"]
        if futc_h != 12:
            fargs += ["--utc", str(futc_h)]
        if fmode == "최근 N개(backfill)":
            fn = st.number_input("N (최근 base)", 1, 7, 3, key="cf_n")
            fargs += ["--backfill", str(int(fn))]
        if st.button("▶ 기상 수집 실행", key="cf_run"):
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
        if st.button("▶ 실측 수집 실행", key="ch_run"):
            with st.spinner("실측 수집 중… (KPX/ASOS API)"):
                rc, out = C.run_script(C.COLLECT_LAND_HIST,
                                       ["--historical-days", str(int(hd))], cwd=C.DATA_DIR)
            if rc == 0:
                st.success("완료 (종료코드 0)")
                st.cache_data.clear()
            else:
                st.error(f"실패 (종료코드 {rc})")
            st.code(out or "(출력 없음)")

    st.divider()
    st.subheader("AI 브리핑 생성")
    st.caption("종합브리핑·예측 확인 탭은 여기서 생성된 브리핑을 **가져와 표시만** 합니다. "
               "매일 새벽 서버가 D+1~D+15 날짜별 종합을 자동 생성하며, 아래 버튼으로 지금 즉시 생성할 수도 있습니다.")
    bday = st.date_input("생성 기준일(오늘)", value=TODAY.date(), key="ops_brief_day")

    st.markdown("**날짜별 종합 — D+1~D+15 한 번에 생성 (3콜)** "
                "(단기 D+1~3 · 중기 D+4~10 · 장기 D+11~15)")
    st.caption("매일 새벽 서버 cron(`gen_briefs_land.py`)이 자동 생성하는 것과 같습니다. "
               "구간별 1콜로 날짜별 브리핑을 받아 저장하며, DB만 읽고 수집 API는 호출하지 않습니다(AI 호출만).")
    if st.button("▶ 15일 종합 생성 (3콜)", type="primary", key="ops_band_gen"):
        with st.spinner("AI 브리핑 작성 중… (3회 호출)"):
            res = B.generate_all_days("land", pd.Timestamp(bday), use_live=False)
        nok = sum(1 for r in res if r["ok"])
        (st.success if nok == len(res) else st.warning)(f"{nok}/{len(res)}일 생성·저장")
        for r in res:
            mark = "✅" if r["ok"] else "⚠"
            st.caption(f"{mark} **D+{r['horizon']}** ({r['start']})"
                       + (f" — {r['msg']}" if r.get("msg") else ""))
        st.cache_data.clear()

    with st.expander("자유 형식 브리핑 — 임의 구간·종류(송출량·기상 등)"):
        B.render_brief_panel("ops", pd.Timestamp(bday), default_n=1)

    with st.expander("저장된 AI 브리핑 기록 (시작일·지평·종류)"):
        B.render_saved_briefs("land")

    render_gas_price()


def render_gas_price():
    """발전용 가스 단가(원/GJ) 월별 수동 입력 — 가스비 환산에 쓰인다.

    기본값 = 실적 CSV. 여기서 입력한 월 단가가 그 위를 덮어쓰고(gas_price_store, 전용 DB),
    CSV 에 없는 최근·앞으로의 월도 추가할 수 있다. 저장 시 조회 캐시를 비워 즉시 반영한다.
    """
    st.divider()
    st.subheader("발전용 가스 단가 (원/GJ)")
    st.caption("가스비 = 송출량(TON) × 55 GJ/ton × **월 단가**. 기본값은 과거 실적 단가이며, "
               "여기서 입력한 단가가 우선합니다(없는 월도 추가 가능). "
               "JKM($/MMBtu)이 아니라 발전용 정산 단가(원/GJ)를 직접 넣습니다.")

    tariff = C.gas_tariff_by_month()          # CSV + 입력값 병합
    ov = GP.load_overrides()

    # 입력 줄 — 월 선택(최근 실적 다음 달 근처) + 단가 + 저장
    cur = pd.Timestamp.now().to_period("M")
    months = pd.period_range(cur - 2, periods=9, freq="M").astype(str).tolist()
    c_m, c_v, c_b = st.columns([1.4, 1.4, 1], vertical_alignment="bottom")
    ym_sel = c_m.selectbox("월 (YYYY-MM)", months, index=2, key="gp_ym")
    default_val = float(tariff.get(ym_sel, tariff.iloc[-1]))
    val = c_v.number_input("단가 (원/GJ)", min_value=0.0, value=default_val,
                           step=100.0, format="%.1f", key="gp_val",
                           help="비우거나 0이면 저장되지 않습니다")
    if c_b.button("저장", type="primary", width="stretch", key="gp_save"):
        if val > 0:
            GP.save(ym_sel, val)
            st.cache_data.clear()             # 환산 캐시(gas_tariff_by_month) 무효화
            st.success(f"{ym_sel} 단가 {val:,.0f} 원/GJ 저장 — 다른 메뉴 가스비에 반영됩니다.")
            st.rerun()
        else:
            st.warning("0보다 큰 단가를 입력하세요.")

    # 현재 적용 단가(최근 10개월) + 출처 표
    with st.expander("현재 적용 단가 · 저장된 입력값", expanded=bool(ov)):
        show = tariff.tail(10).rename("원/GJ").to_frame()
        show.insert(0, "월", show.index)
        show["출처"] = ["입력값" if m in ov else "CSV(실적)" for m in show.index]
        st.dataframe(show, width="stretch", hide_index=True)
        if ov:
            st.caption("저장된 입력값 — 삭제하면 해당 월은 CSV 기본값으로 되돌아갑니다.")
            for m in sorted(ov):
                d1, d2 = st.columns([3, 1], vertical_alignment="center")
                d1.write(f"**{m}** · {ov[m]:,.0f} 원/GJ")
                if d2.button("삭제", key=f"gp_del_{m}", width="stretch"):
                    GP.delete(m)
                    st.cache_data.clear()
                    st.rerun()


# ================================================================ 외부 연동 (API)
_API_ENDPOINTS = [
    ("GET /forecast", "예측 시계열", "전력수요·신재생·가스 발전(MW)·송출량(TON)의 시간별 예측값"),
    ("GET /chart", "예측 차트", "접속 시 대화형 예측 그래프를 제공"),
    ("GET /brief", "AI 브리핑", "해당 일자의 AI 브리핑 본문(저장본)"),
    ("GET /bundle", "예측 + 브리핑 묶음", "예측 시계열과 AI 브리핑을 한 번에 제공하는 통합 조회"),
    ("GET /briefings", "브리핑 목록", "저장된 AI 브리핑의 목록과 기본 정보"),
    ("GET /docs", "API 문서(Swagger)", "브라우저에서 확인하는 대화형 API 문서"),
]


@st.cache_data(ttl=10, show_spinner=False)
def _api_health(base: str) -> tuple[bool, str]:
    """API 서버 헬스 핑 — (응답여부, 메모). 짧은 캐시로 매 rerun 호출을 막는다."""
    try:
        import requests
        r = requests.get(base.rstrip("/") + "/", timeout=1.5)
        return (r.status_code == 200), (r.json().get("service", "") if r.ok else f"HTTP {r.status_code}")
    except Exception as e:                      # 미기동·주소오류 등 — 폴백으로 처리
        return False, type(e).__name__


def _local_bundle(sd: pd.Timestamp, days: int, kind: str) -> dict:
    """API 미응답 시 폴백 — serve_api 와 같은 함수로 동일 형식의 /bundle 응답을 직접 만든다."""
    ser = B.forecast_series(sd, days, use_live=False)
    ser = ser.assign(timestamp=ser["timestamp"].astype(str))
    ser = ser.where(pd.notna(ser), None)
    recs = ser.to_dict("records")
    rec = BS.load(sd.strftime("%Y-%m-%d"), days, kind)
    return {"region": "land", "start": sd.strftime("%Y-%m-%d"), "days": days, "kind": kind,
            "forecast": {"fields": ["timestamp", "horizon_d", "demand_mw", "renew_mw",
                                    "gas_gen_mw", "sendout_ton"],
                         "n_rows": len(recs), "series": recs},
            "brief": rec}


def render_api_use():
    """외부 연동 · 'API 활용' 탭 — 상태·공개 주소·문서/차트 버튼·엔드포인트 표."""
    head, badge = st.columns([8, 2], vertical_alignment="center")
    head.subheader("API 활용 — 예측과 AI 브리핑을 외부 시스템에 제공")
    # 점검은 서버 내부 주소(127.0.0.1)로 — 공개 주소는 공유기 특성상 서버 자신이 못 불러 '꺼짐'으로 오인될 수 있다.
    ok, _detail = _api_health(API_LOCAL_URL)
    if ok:
        badge.success("🟢 API 서버 정상")
    else:
        badge.error("🔴 API 서버 비정상")

    pub = st.text_input("API 공개 주소", value=API_PUBLIC_DEFAULT, key="api_base",
                        help="외부에서 호출하는 주소입니다.").rstrip("/")

    cs = pd.Timestamp(st.session_state.get("api_day", TODAY.date())).strftime("%Y-%m-%d")
    cd = int(st.session_state.get("api_days", 1))
    b1, b2, _sp = st.columns([1.2, 1.2, 2.6])
    b1.link_button("API 문서 열기  ↗  /docs", f"{pub}/docs", type="primary", width="stretch",
                   help="대화형 문서(Swagger) — 모든 주소를 화면에서 직접 호출해 볼 수 있습니다.")
    b2.link_button("예측 차트 열기  ↗  /chart", f"{pub}/chart?start={cs}&days={cd}", width="stretch",
                   help="링크 접속만으로 대화형 예측 그래프를 확인할 수 있습니다.")

    st.markdown("**제공하는 주소(엔드포인트)**")
    st.dataframe(pd.DataFrame(_API_ENDPOINTS, columns=["주소", "무엇을", "내용"]),
                 width="stretch", hide_index=True)


def render_api_help():
    """외부 연동 · '도움말' 탭 — 호출 예시 + 간단한 응답 미리보기(꼭 필요한 것만)."""
    st.subheader("도움말 — 호출 예시 · 응답 미리보기")
    pub = st.session_state.get("api_base", API_PUBLIC_DEFAULT).rstrip("/")
    lo, hi = C.land_date_range()

    c1, c2, c3 = st.columns([1.4, 1, 1.2], vertical_alignment="bottom")
    sday = c1.date_input("시작일", value=min(TODAY.date(), pd.Timestamp(hi).date()), key="api_day",
                         help=f"예측 보유 범위: {lo} ~ {hi}")
    ndays = c2.slider("일수", 1, 7, 1, key="api_days")
    kind = c3.selectbox("브리핑 종류", ["overview", "sendout", "weather"], key="api_kind")
    sd = pd.Timestamp(sday)
    qurl = f"{pub}/bundle?start={sd:%Y-%m-%d}&days={ndays}&kind={kind}"

    st.markdown("**호출 예시** — 위에서 고른 조건을 그대로 사용한 예시입니다.")
    st.code(qurl, language="text")                                   # 브라우저 주소창
    st.code(f"curl '{qurl}'", language="bash")                       # 명령줄
    st.code("import requests\n"                                      # 파이썬
            f"r = requests.get('{pub}/bundle', params={{\n"
            f"    'start': '{sd:%Y-%m-%d}', 'days': {ndays}, 'kind': '{kind}'}})\n"
            "print(r.json())", language="python")

    st.markdown("**응답 미리보기**")
    if st.button("▶ 실제 API 호출해 보기", type="primary", key="api_call"):
        try:
            import requests
            prev = requests.get(f"{API_LOCAL_URL}/bundle",
                                params={"start": sd.strftime("%Y-%m-%d"),
                                        "days": int(ndays), "kind": kind}, timeout=8).json()
        except Exception:
            try:
                prev = _local_bundle(sd, int(ndays), kind)   # API 미응답 시 같은 형식으로 폴백
            except Exception:
                prev = None
        st.session_state["_api_preview"] = prev
    prev = st.session_state.get("_api_preview")
    if isinstance(prev, dict):
        fc = prev.get("forecast", {})
        st.caption(f"예측 {fc.get('n_rows', 0)}행" + ("  ·  AI 브리핑 포함" if prev.get("brief") else ""))
        with st.expander("전체 JSON 응답", expanded=True):
            st.json(prev)
    else:
        st.caption("버튼을 누르면 실제 응답(JSON)을 확인할 수 있습니다.")


# ---------------------------------------------------------------- 이용 조건·면책 고지
def render_disclaimer():
    """외부 연동 첫 탭 — 서비스의 한계와 이용 조건을 분명히 밝힌다."""
    st.subheader("⚠️ 이용 조건 및 면책 고지")
    st.error(
        "**본 서비스는 참고용 예측 보조 도구입니다. "
        "실제 전력 계통 운영이나 가스 수급 의사결정의 유일한 근거로 사용할 수 없습니다.**")

    st.markdown("---")

    st.markdown("#### 1. 서비스의 목적과 한계")
    st.write(
        "본 서비스는 전국 단위의 전력수요·신재생 발전·천연가스 발전 및 송출량을 "
        "**예측·분석하기 위한 참고용 도구**입니다.\n\n"
        "제공되는 모든 예측값·그래프·수치·AI 브리핑은 실제 계통 운영, 급전 판단, "
        "가스 수급 계획, 전력·가스 거래 등 **실무 의사결정을 대체하지 않습니다.** \n\n"
        "예측은 참고 자료이며, 실시간 계통 상황을 그대로 반영하지 않습니다.")

    st.markdown("#### 2. 예측 정확도의 한계")
    st.write(
        "예측은 과거 데이터를 학습한 인공지능 모델이 만든 통계적 추정값입니다. "
        "특히 다음과 같은 상황에서 오차가 크게 커질 수 있습니다.")
    st.write(
        "- 전력거래소의 출력제어·발전 유지 등 운영상 결정\n"
        "- 발전소 정기점검, 송전 제약 등 전력 계통의 구조적 변화\n"
        "- 태풍·집중호우·폭설 등 급격한 기상 변화\n"
        "- 미래로 갈수록 커지는 기상 예보 자체의 오차의 증폭\n"
        "- 학습 데이터에 없던 새로운 계절 패턴이나 설비 증설\n"
        "- 입력 데이터(실측·예보)의 결측·지연·오류")
    st.caption("※ 도시가스 송출량은 일 단위 실측이 없어 기온을 바탕으로 간접 추정한 참고값입니다.")

    st.markdown("#### 3. 데이터 출처와 신뢰성")
    st.write(
        "본 서비스는 전력거래소(KPX)와 기상청(KMA)의 공개 데이터를 바탕으로 합니다.\n\n"
        "해당 기관의 시스템 장애, 데이터 지연·정정, 형식 변경 등으로 수집 데이터가 불완전하거나 부정확할 수 있으며, \n\n "
        "본 서비스는 **외부 데이터의 정확성을 보증하지 않습니다.**")

    st.markdown("#### 4. 외부 연동(API) 이용 조건")
    st.warning(
        "외부 시스템이 API로 가져가는 데이터는 조회만 가능한 **참고 자료**입니다.")
    st.write(
        "- 실시간 계통 운영, 자동 급전, 자동 거래 등 즉각적인 판단이 필요한 곳에 "
        "**직접 연결하지 마십시오.**\n"
        "- 본 서비스는 무중단 운영을 보장하지 않으며, **예고 없이 중단·변경될 수 있습니다.**\n"
        "- 시연·연구 목적으로 제공되며, 다른 용도로 활용할 경우 반드시 자체 검증 절차를 거쳐야 합니다.")

    st.markdown("#### 5. 책임의 한계")
    st.write("본 서비스는 다음에 대하여 어떠한 법적 책임도 지지 않습니다.")
    st.write(
        "- 예측이 실제와 달라 발생한 직접·간접 손실\n"
        "- 시스템 장애, 데이터 유실, API 중단 등으로 인한 서비스 이용 불가\n"
        "- 본 서비스의 결과를 근거로 내린 판단에 따른 재정적·운영적 손해\n"
        "- 전력거래소·기상청 등 외부 서비스의 변경·중단으로 인한 영향")

    st.markdown("#### 6. 이용자의 책임")
    st.write(
        "본 서비스를 이용하는 것은 위 내용을 충분히 이해하고 동의한 것으로 봅니다.\n\n"
        "예측 결과를 실무에 참고할 경우 반드시 **자체 검증 절차와 담당자의 판단을 함께 거쳐야 하며,** "
        "이용에 따른 모든 결과의 책임은 이용자 본인에게 있습니다.")

    st.markdown("---")
    st.caption("본 고지는 서비스 배포 시점을 기준으로 작성되었으며, 사전 통보 없이 변경될 수 있습니다.")


if menu == "수급 예측":
    tab_hero, tab_now, tab_mix, tab_lh = st.tabs(
        ["종합브리핑", "예측 확인", "에너지 믹스", "장지평 예측"])
    with tab_hero:
        render_hero()
    with tab_now:
        render_forecast_check()
    with tab_mix:
        render_gen_mix()
    with tab_lh:
        render_longhorizon()
elif menu == "예측 검증":
    render_forecast_menu()
elif menu == "데이터 현황":
    render_data_status()
elif menu == "관리자메뉴":
    render_run_ops()
else:
    # 외부 연동 — 3탭: 이용 조건(면책) · API 활용(문서·차트) · 도움말(예시·미리보기).
    tab_terms, tab_use, tab_help = st.tabs(["⚠️ 이용 조건", "API 활용", "도움말"])
    with tab_terms:
        render_disclaimer()
    with tab_use:
        render_api_use()
    with tab_help:
        render_api_help()

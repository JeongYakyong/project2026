# -*- coding: utf-8 -*-
"""8단계 공용 레이어 — DB 조회(읽기 전용)·KPX 실시간 수급·단가 환산·적재 현황."""
from pathlib import Path
import sys
import sqlite3

import pandas as pd
import streamlit as st
import plotly.graph_objects as go
import plotly.io as pio

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
def land_date_range() -> tuple[str, str]:
    """예측 적재 범위(est_demand_land 기준) — 표시 가능 날짜 한계(G-15 ④)."""
    df = query("land", "SELECT MIN(timestamp) AS lo, MAX(timestamp) AS hi "
                       "FROM forecast WHERE est_demand_land IS NOT NULL")
    return str(df.loc[0, "lo"])[:10], str(df.loc[0, "hi"])[:10]


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
               est_gas_gen_land, est_gas_sendout_ton_land, est_true_demand_land,
               land_est_demand_da,
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


# ---------------------------------------------------------------- KPX 실시간 (표시 전용, DB에 쓰지 않음)
@st.cache_data(ttl=300, show_spinner="KPX 실시간 수급을 불러오는 중...")
def live_sukub_land(day: str) -> pd.DataFrame:
    """KPX sukub 수급(real_demand_land 등 7컬럼). 실패 시 빈 DF."""
    if str(CORE) not in sys.path:
        sys.path.insert(0, str(CORE))
    try:
        from api_fetchers_land import fetch_kpx_land
        df = fetch_kpx_land(day, day, progress=False)
        return df.reset_index() if not df.empty else pd.DataFrame()
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=300, show_spinner="KPX 발전실적을 불러오는 중...")
def live_power_land(day: str) -> pd.DataFrame:
    """KPX 발전원별 실적(gen_gas_kr·gen_solar_market_kr·gen_wind_kr 등). 실패 시 빈 DF."""
    if str(CORE) not in sys.path:
        sys.path.insert(0, str(CORE))
    try:
        from api_fetchers_land import fetch_land_power
        df = fetch_land_power(day, day, progress=False)
        return df.reset_index() if not df.empty else pd.DataFrame()
    except Exception:
        return pd.DataFrame()


def clear_live_caches():
    live_sukub_land.clear()
    live_power_land.clear()


# ---------------------------------------------------------------- 비교 프레임 (예측 vs 실측, 하루/구간)
def land_range_compare(start_day: pd.Timestamp, end_day: pd.Timestamp,
                       use_live: bool = True) -> pd.DataFrame:
    """[start_day 00시, end_day 23시] 예측(DB) + 실측(DB historical, 최근 날짜는 live 보강).

    실측 net_load는 예측과 같은 기준(수요 − 시장신재생)으로 재구성한다.
    KPX 수요예측(land_est_demand_da)도 포함(전력거래소 비교용 — D+1까지만 발표됨).
    """
    s = start_day.strftime("%Y-%m-%d 00:00:00")
    e = end_day.strftime("%Y-%m-%d 23:00:00")
    base = pd.DataFrame({"timestamp": pd.date_range(s, e, freq="h")})

    est = land_forecast(s, e)[["timestamp", "est_demand_land", "est_market_renew_land",
                               "est_net_load_land", "est_gas_gen_land",
                               "est_gas_sendout_ton_land", "est_true_demand_land",
                               "land_est_demand_da"]]
    act = query("land", """
        SELECT timestamp, real_demand_land, renew_gen_total_kr, gen_gas_kr
        FROM historical WHERE timestamp BETWEEN ? AND ? ORDER BY timestamp
    """, (s, e))
    df = base.merge(est, on="timestamp", how="left").merge(act, on="timestamp", how="left")

    # DB가 못 따라온 최근 구간(오늘 포함 3일 이내, 미래 제외)은 live fetch로 보강 (live 값 우선)
    if use_live:
        today = pd.Timestamp.now().normalize()
        for day in pd.date_range(start_day.normalize(), end_day.normalize(), freq="D"):
            if not (0 <= (today - day).days <= 3):
                continue
            d = day.strftime("%Y-%m-%d")
            sk = live_sukub_land(d)
            if not sk.empty and "real_demand_land" in sk.columns:
                sk = sk.assign(timestamp=pd.to_datetime(sk["timestamp"]))
                df = df.merge(sk[["timestamp", "real_demand_land"]], on="timestamp",
                              how="left", suffixes=("", "_live"))
                df["real_demand_land"] = df["real_demand_land_live"].combine_first(df["real_demand_land"])
                df = df.drop(columns=["real_demand_land_live"])
            pw = live_power_land(d)
            if not pw.empty and "gen_gas_kr" in pw.columns:
                pw = pw.assign(timestamp=pd.to_datetime(pw["timestamp"]))
                pw["renew_live"] = pw.get("gen_solar_market_kr", 0) + pw.get("gen_wind_kr", 0)
                df = df.merge(pw[["timestamp", "gen_gas_kr", "renew_live"]], on="timestamp",
                              how="left", suffixes=("", "_live"))
                df["gen_gas_kr"] = df["gen_gas_kr_live"].combine_first(df["gen_gas_kr"])
                df["renew_gen_total_kr"] = df["renew_live"].combine_first(df["renew_gen_total_kr"])
                df = df.drop(columns=["gen_gas_kr_live", "renew_live"])

    df["real_net_load"] = df["real_demand_land"] - df["renew_gen_total_kr"]
    return df


def land_day_compare(day: pd.Timestamp, use_live: bool = True) -> pd.DataFrame:
    """선택일 00~23시 비교 프레임 (land_range_compare의 하루 버전)."""
    return land_range_compare(day, day, use_live=use_live)


# ---------------------------------------------------------------- 지평 모드 (과거를 "k일 전 발행 예측"으로)
CHAINED_PARQUET = ROOT / "7. land_gas_forecaster" / "training" / "chained_gas_dataset.parquet"
GAS_SERVE_PY = ROOT / "7. land_gas_forecaster" / "serve_land_gas.py"
CHAIN_HORIZONS = (1, 2, 3, 7, 12)


@st.cache_resource
def _gas_assets():
    """7단계 서빙 자산 재사용 — serve_land_gas 모듈(모델·LNG 용량·bias 보정·변환계수)."""
    import importlib.util
    import lightgbm as lgb
    spec = importlib.util.spec_from_file_location("serve_land_gas", str(GAS_SERVE_PY))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    booster = lgb.Booster(model_file=m.MODEL)
    calib, conv = m._load_calib()
    lng = m._lng_cap_series()
    return m, booster, calib, conv, lng


@st.cache_resource
def _chained() -> pd.DataFrame:
    """7-A2-A 체인 데이터셋 — 지평별(D+1/2/3/7/12) 수요·신재생 예측, 2022-01~적재말."""
    return pd.read_parquet(CHAINED_PARQUET)


@st.cache_data(ttl=CACHE_TTL)
def land_horizon_compare(start: str, end: str, horizon: int) -> pd.DataFrame:
    """[start, end] 구간을 "horizon일 전 발행" 예측으로 구성 + 실측 — 지평 평평(7-A2-A) 입증용.

    수요·신재생 = chained parquet(5-A2·6단계 지평별 산출), 가스 = 7-A2 모델 즉석 계산.
    """
    s_day, e_day = pd.Timestamp(start), pd.Timestamp(end)
    df = land_range_compare(s_day, e_day)
    df = df.drop(columns=["est_demand_land", "est_market_renew_land", "est_net_load_land",
                          "est_gas_gen_land", "est_gas_sendout_ton_land", "est_true_demand_land"])

    ch = _chained()
    sub = ch[(ch["horizon"] == horizon)
             & (ch["timestamp"] >= s_day)
             & (ch["timestamp"] <= e_day + pd.Timedelta(hours=23))].copy()
    if sub.empty:
        for c in ["est_demand_land", "est_market_renew_land", "est_net_load_land",
                  "est_gas_gen_land", "est_gas_sendout_ton_land"]:
            df[c] = float("nan")
        return df

    m, booster, calib, conv, lng = _gas_assets()
    idx = pd.DatetimeIndex(sub["timestamp"])
    feats = pd.DataFrame({
        "real_demand_land": sub["est_demand"].astype(float).values,
        "renew_gen_total_kr": sub["est_renew"].astype(float).values,
        "hour": idx.hour, "dow": idx.dayofweek, "month": idx.month, "doy": idx.dayofyear,
        "day_type": pd.Categorical(sub["day_type"].astype(str).values, categories=m.DTCATS),
    })
    cap = m._lng_cap_for(idx, lng)
    gen = booster.predict(feats[m.FEATS]) * cap * calib

    est = pd.DataFrame({
        "timestamp": sub["timestamp"].values,
        "est_demand_land": feats["real_demand_land"].values,
        "est_market_renew_land": feats["renew_gen_total_kr"].values,
        "est_gas_gen_land": gen,
        "est_gas_sendout_ton_land": gen * conv,
    })
    est["est_net_load_land"] = est["est_demand_land"] - est["est_market_renew_land"]
    return df.merge(est, on="timestamp", how="left")


MIX_GEN_COLS = ["gen_nuclear_kr", "gen_coal_kr", "gen_localcoal_kr", "gen_oil_kr",
                "gen_hydro_kr", "gen_pumped_kr", "gen_nre_kr", "gen_gas_kr",
                "gen_solar_market_kr", "gen_wind_kr", "gen_solar_btm_kr", "gen_solar_ppa_kr"]


def land_day_mix(day: pd.Timestamp, use_live: bool = True) -> pd.DataFrame:
    """선택일 발전 믹스 6그룹(누적용 실측) + 수요선. DB historical, 최근 날짜는 live 보강.

    그룹: 원전 / 기타발전(석탄·국내탄·유류·수력·양수·기타신재생, 양수 펌핑은 음수 그대로 합산) /
          가스 / 태양광+풍력(시장) / BTM+PPA(추정). 수요선 = 계량수요·총수요(+BTM/PPA).
    """
    s = day.strftime("%Y-%m-%d 00:00:00")
    e = day.strftime("%Y-%m-%d 23:00:00")
    base = pd.DataFrame({"timestamp": pd.date_range(s, e, freq="h")})
    cols = ", ".join(MIX_GEN_COLS)
    df = base.merge(query("land", f"""
        SELECT timestamp, real_demand_land, {cols}
        FROM historical WHERE timestamp BETWEEN ? AND ? ORDER BY timestamp
    """, (s, e)), on="timestamp", how="left")

    if use_live and (pd.Timestamp.now().normalize() - day).days <= 3:
        pw = live_power_land(day.strftime("%Y-%m-%d"))
        if not pw.empty:
            pw = pw.assign(timestamp=pd.to_datetime(pw["timestamp"]))
            keep = [c for c in MIX_GEN_COLS if c in pw.columns]
            df = df.merge(pw[["timestamp"] + keep], on="timestamp", how="left", suffixes=("", "_lv"))
            for c in keep:
                df[c] = df[f"{c}_lv"].combine_first(df[c])
            df = df.drop(columns=[f"{c}_lv" for c in keep])
        sk = live_sukub_land(day.strftime("%Y-%m-%d"))
        if not sk.empty and "real_demand_land" in sk.columns:
            sk = sk.assign(timestamp=pd.to_datetime(sk["timestamp"]))
            df = df.merge(sk[["timestamp", "real_demand_land"]], on="timestamp",
                          how="left", suffixes=("", "_lv"))
            df["real_demand_land"] = df["real_demand_land_lv"].combine_first(df["real_demand_land"])
            df = df.drop(columns=["real_demand_land_lv"])

    out = pd.DataFrame({"timestamp": df["timestamp"]})
    out["원전"] = df["gen_nuclear_kr"]
    out["기타발전"] = df[["gen_coal_kr", "gen_localcoal_kr", "gen_oil_kr",
                       "gen_hydro_kr", "gen_pumped_kr", "gen_nre_kr"]].sum(axis=1, min_count=1)
    out["가스"] = df["gen_gas_kr"]
    out["태양광+풍력"] = df[["gen_solar_market_kr", "gen_wind_kr"]].sum(axis=1, min_count=2)
    out["BTM+PPA"] = df[["gen_solar_btm_kr", "gen_solar_ppa_kr"]].sum(axis=1, min_count=2)
    out["계량수요"] = df["real_demand_land"]
    out["총수요"] = df["real_demand_land"] + out["BTM+PPA"]
    return out


def error_metrics(est: pd.Series, act: pd.Series) -> dict | None:
    """겹치는 시간만으로 MAPE(%)·MAE·bias(%). 겹침 없으면 None."""
    m = pd.concat([est, act], axis=1, keys=["e", "a"]).dropna()
    m = m[m["a"].abs() > 1e-6]
    if m.empty:
        return None
    err = m["e"] - m["a"]
    return {"mape": float((err.abs() / m["a"].abs()).mean() * 100),
            "nmae": float(err.abs().mean() / m["a"].abs().mean() * 100),  # 분모 작은 시간대에 강건
            "mae": float(err.abs().mean()),
            "bias": float(err.sum() / m["a"].sum() * 100),
            "n": len(m)}


@st.cache_data(ttl=CACHE_TTL)
def land_daily_error_history(end_day: str, days: int = 30) -> pd.DataFrame:
    """최근 N일 일별 MAPE 추이 (수요/신재생/net_load/가스). DB 적재분만 사용."""
    end = pd.Timestamp(end_day)
    s = (end - pd.Timedelta(days=days - 1)).strftime("%Y-%m-%d 00:00:00")
    e = end.strftime("%Y-%m-%d 23:00:00")
    est = land_forecast(s, e)
    act = land_actual(s, e)
    df = est.merge(act, on="timestamp", how="inner")
    pairs = {"수요": ("est_demand_land", "real_demand_land", "mape"),
             "신재생": ("est_market_renew_land", "renew_gen_total_kr", "nmae"),
             "net_load": ("est_net_load_land", "net_load_actual", "mape"),
             "가스": ("est_gas_gen_land", "gen_gas_kr", "mape")}
    out = {}
    grp = df.groupby(df["timestamp"].dt.date)
    for name, (ec, ac, kind) in pairs.items():
        def _daily(g, ec=ec, ac=ac, kind=kind):
            v = g[[ec, ac]].dropna()
            if len(v) < 12:
                return float("nan")
            err = (v[ec] - v[ac]).abs()
            return float(err.mean() / v[ac].abs().mean() * 100) if kind == "nmae" \
                else float((err / v[ac].abs()).mean() * 100)
        out[name] = grp.apply(_daily, include_groups=False)
    return pd.DataFrame(out)


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
def table_columns(region: str, table: str) -> list[str]:
    con = sqlite3.connect(str(DB[region]))
    try:
        return [r[1] for r in con.execute(f"PRAGMA table_info({table})")]
    finally:
        con.close()


@st.cache_data(ttl=CACHE_TTL)
def table_range(region: str, table: str) -> tuple[str, str]:
    df = query(region, f"SELECT MIN(timestamp) AS lo, MAX(timestamp) AS hi FROM {table}")
    return str(df.loc[0, "lo"]), str(df.loc[0, "hi"])


@st.cache_data(ttl=CACHE_TTL)
def coverage_heat(region: str, table: str, start: str, end: str) -> pd.DataFrame:
    """6시간 블록별 컬럼 적재율(0~1) — index=컬럼(DB 순서), columns=블록 시작 시각.

    기간 전체를 시간 격자로 reindex — 행 자체가 없는 구간도 0%로 드러난다.
    """
    df = query(region, f"SELECT * FROM {table} WHERE timestamp BETWEEN ? AND ? "
                       "ORDER BY timestamp", (start, end))
    grid = pd.date_range(start, end, freq="h")
    if df.empty:
        return pd.DataFrame(0.0, index=[c for c in table_columns(region, table)
                                        if c != "timestamp"],
                            columns=pd.date_range(start, end, freq="6h"))
    df = df.set_index("timestamp").reindex(grid)
    return df.notna().resample("6h").mean().T


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
# 전 차트 공용 템플릿 — 기상개황 지도와 같은 토큰(Pretendard·ink/slate·line #e2e8f0).
# pio 기본값으로 등록해 make_fig 외(make_subplots·go.Figure 직접 생성)에도 일괄 적용.
pio.templates["briefing"] = go.layout.Template(layout=go.Layout(
    font=dict(family="Pretendard, 'Segoe UI', sans-serif", size=13, color="#334155"),
    paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
    xaxis=dict(gridcolor="#eef2f7", linecolor="#e2e8f0", zerolinecolor="#e2e8f0",
               tickfont=dict(size=11.5, color="#64748b")),
    yaxis=dict(gridcolor="#eef2f7", linecolor="#e2e8f0", zerolinecolor="#e2e8f0",
               tickfont=dict(size=11.5, color="#64748b"),
               title=dict(font=dict(size=12, color="#64748b"))),
    legend=dict(font=dict(size=12, color="#475569")),
    hoverlabel=dict(bgcolor="#0f172a", bordercolor="rgba(15,23,42,0)",
                    font=dict(family="Pretendard, 'Segoe UI', sans-serif",
                              size=12.5, color="#f1f5f9")),
))
pio.templates.default = "briefing"


def make_fig(height: int = 420, ytitle: str = "MW") -> go.Figure:
    fig = go.Figure()
    fig.update_layout(height=height, margin=dict(t=30, b=10, l=10, r=10),
                      legend=dict(orientation="h", y=-0.15), yaxis_title=ytitle)
    return fig


def add_actual(fig: go.Figure, ts, y, name: str, color: str, **kw):
    fig.add_trace(go.Scatter(x=ts, y=y, name=name, line=dict(color=color, width=2), **kw))


def add_forecast(fig: go.Figure, ts, y, name: str, color: str, **kw):
    fig.add_trace(go.Scatter(x=ts, y=y, name=name, line=dict(color=color, dash="dot", width=2), **kw))


# ---------------------------------------------------------------- UI 레이어 (8-A 디자인)
# 디자인 토큰 = 기상개황 지도(weather_map.py)와 동일: ink #0f172a / sub #64748b /
# line #e2e8f0 / green #059669. 캔버스·사이드바 색은 .streamlit/config.toml 테마가 담당.
_CSS = """
<style>
/* ---- 지표 카드 ---- */
[data-testid="stMetric"]{
  background:#fff; border:1px solid #cbd5e1; border-radius:14px;
  padding:.85rem 1.05rem .8rem; box-shadow:0 1px 2px rgba(15,23,42,.05); }
[data-testid="stMetricLabel"] p{
  font-size:.78rem; font-weight:700; color:#64748b; letter-spacing:.01em; }
[data-testid="stMetricValue"]{
  font-family:'IBM Plex Mono','Pretendard',monospace; font-size:1.5rem;
  font-weight:600; color:#0f172a; letter-spacing:-.03em; }
[data-testid="stMetricDelta"]{ font-size:.78rem; }

/* ---- 차트·지도 임베드를 흰 카드로 ---- */
[data-testid="stPlotlyChart"]{
  background:#fff; border:1px solid #cbd5e1; border-radius:14px;
  padding:.6rem .7rem .3rem; box-shadow:0 1px 2px rgba(15,23,42,.05); }
[data-testid="stIFrame"], iframe[title="st.iframe"]{
  border:1px solid #cbd5e1; border-radius:14px;
  box-shadow:0 1px 2px rgba(15,23,42,.05); }

/* ---- 탭 — 알약 버튼(선택 가능해 보이게, 지도 패널 mchip 과 동일 문법) ---- */
[data-testid="stTabs"] [role="tablist"]{ gap:6px; border-bottom:none; }
[data-testid="stTabs"] [role="tab"]{
  background:#fff; border:1px solid #94a3b8; border-radius:999px;
  padding:.15rem 1.05rem; margin-bottom:6px; transition:border-color .12s; }
[data-testid="stTabs"] [role="tab"]:hover{ border-color:#475569; }
[data-testid="stTabs"] [role="tab"] p{ font-size:.9rem; font-weight:700; color:#64748b; }
[data-testid="stTabs"] [role="tab"][aria-selected="true"]{
  background:#0f172a; border-color:#0f172a; }
[data-testid="stTabs"] [role="tab"][aria-selected="true"] p{ color:#fff; }
[data-testid="stTabs"] [data-baseweb="tab-highlight"]{ display:none; }
[data-testid="stTabs"] [data-baseweb="tab-border"]{ display:none; }

/* ---- 작은 지표(보조 수치 — 가스비 등): container(key=*_metric_sm) 로 감싸 적용 ---- */
[class*="metric_sm"] [data-testid="stMetricValue"]{ font-size:1.05rem; }
[class*="metric_sm"] [data-testid="stMetric"]{ padding:.7rem .9rem; }

/* ---- 버튼·캡션 ---- */
.stButton button p{ font-weight:700; font-size:.88rem; }
[data-testid="stCaptionContainer"]{ color:#64748b; }

/* ---- 사이드바: 페이지 링크(전국/제주) — 더 크게 ---- */
[data-testid="stSidebarNav"] a{ padding:.45rem .75rem; border-radius:10px; }
[data-testid="stSidebarNav"] a span{ font-size:1.05rem; font-weight:700; }
[data-testid="stSidebarNav"] a span[data-testid="stIconMaterial"]{ font-size:1.35rem; }

/* ---- date_input: 박스 안 날짜 중앙 정렬 (전 페이지 공통) ---- */
.stDateInput input{ text-align:center; }

/* ---- 사이드바: radio 를 내비게이션 메뉴처럼 ---- */
section[data-testid="stSidebar"] [data-testid="stWidgetLabel"] p{
  font-size:.7rem; font-weight:800; letter-spacing:.16em; color:#94a3b8;
  text-transform:uppercase; }
section[data-testid="stSidebar"] [role="radiogroup"]{ gap:3px; }
section[data-testid="stSidebar"] [role="radiogroup"] label{
  width:100%; margin:0; padding:.5rem .8rem; border-radius:10px;
  transition:background .12s; }
section[data-testid="stSidebar"] [role="radiogroup"] label:hover{
  background:rgba(148,163,184,.14); }
section[data-testid="stSidebar"] [role="radiogroup"] label:has(input:checked){
  background:rgba(52,211,153,.16); }
section[data-testid="stSidebar"] [role="radiogroup"] label:has(input:checked) p{
  color:#6ee7b7; font-weight:800; }
section[data-testid="stSidebar"] [role="radiogroup"] label > div:first-child{
  display:none; }   /* 라디오 동그라미 숨김 — 메뉴처럼 보이게 */

/* ---- 페이지 헤더 ---- */
.bf-head{ margin:0 0 .9rem; }
.bf-eyebrow{ font-size:.7rem; font-weight:800; letter-spacing:.2em; color:#059669; }
.bf-titlerow{ display:flex; align-items:center; gap:1rem; flex-wrap:wrap; margin:.15rem 0 .3rem; }
.bf-title{ font-size:1.85rem; font-weight:800; letter-spacing:-.02em;
  color:#0f172a; line-height:1.15; }
.bf-chain{ display:inline-flex; align-items:center; gap:.45rem; background:#fff;
  border:1px solid #cbd5e1; border-radius:999px; padding:.38rem .9rem;
  box-shadow:0 1px 2px rgba(15,23,42,.05); }
.bf-step{ display:inline-flex; align-items:center; gap:.34rem; font-size:.8rem;
  font-weight:700; color:#334155; white-space:nowrap; }
.bf-step i{ width:.55rem; height:.55rem; border-radius:50%; display:inline-block; }
.bf-arrow{ color:#94a3b8; font-size:.78rem; }
.bf-sub{ font-size:.88rem; color:#64748b; }
</style>"""


def inject_style():
    """전역 CSS — app.py(엔트리)에서 매 rerun마다 호출(전 페이지 공통)."""
    st.markdown(_CSS, unsafe_allow_html=True)


def day_navigator(prefix: str, ndays: tuple[int, int, int] | None = None,
                  refresh: bool = True):
    """8단계 표준 날짜 컨트롤 — ◀ 어제 | 날짜 | 내일 ▶ | (새로고침) | (표시 기간) | 캡션.

    탭/메뉴마다 독립 배치(prefix 별 session 키). ndays=(최소, 최대, 기본)이면
    표시 기간(일) 슬라이더 포함, refresh=False면 새로고침 버튼 없는 슬림 버전.
    반환: (선택일 Timestamp, 표시일수 n | None, 캡션용 column). 기본 = 오늘.
    """
    key = f"{prefix}_day"
    if key not in st.session_state:
        st.session_state[key] = pd.Timestamp.now().normalize().date()

    def _shift(delta: int):
        st.session_state[key] = st.session_state[key] + pd.Timedelta(days=delta)

    ratios = [0.8, 1.6, 0.8]
    if refresh:
        ratios.append(1.5)
    if ndays:
        ratios.append(2.1)
    ratios.append(2.5 if ndays else 4.6)
    cols = st.columns(ratios, vertical_alignment="center")
    cols[0].button("◀ 어제", key=f"{prefix}_prev", on_click=_shift, args=(-1,), width="stretch")
    cols[1].date_input("날짜", key=key, label_visibility="collapsed")
    cols[2].button("내일 ▶", key=f"{prefix}_next", on_click=_shift, args=(1,), width="stretch")
    i = 3
    if refresh:
        if cols[i].button("실시간 새로고침", key=f"{prefix}_refresh", width="stretch",
                          help="실측(KPX sukub·발전실적)을 다시 불러옵니다 (표시 전용)"):
            clear_live_caches()
        i += 1
    n = None
    if ndays:
        n = cols[i].slider("표시 기간(일)", ndays[0], ndays[1], ndays[2],
                           key=f"{prefix}_ndays",
                           help="시작일부터 N일 — 사전 적재된 예측을 읽기만 하므로 지연 없음")
    return pd.Timestamp(st.session_state[key]), n, cols[-1]


def page_header(eyebrow: str, title: str, sub: str, chain: list[tuple[str, str]]):
    """페이지 헤더 — eyebrow + 제목 + 체인 pill(단계 점 색 = 차트 COLOR 규약과 동일)."""
    steps = '<span class="bf-arrow">→</span>'.join(
        f'<span class="bf-step"><i style="background:{c}"></i>{label}</span>'
        for label, c in chain)
    st.markdown(
        f'<div class="bf-head"><div class="bf-eyebrow">{eyebrow}</div>'
        f'<div class="bf-titlerow"><div class="bf-title">{title}</div>'
        f'<div class="bf-chain">{steps}</div></div>'
        f'<div class="bf-sub">{sub}</div></div>', unsafe_allow_html=True)

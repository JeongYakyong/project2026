# -*- coding: utf-8 -*-
"""8단계 공용 레이어 — DB 조회(읽기 전용)·KPX 실시간 수급·단가 환산·적재 현황·운영 실행."""
from pathlib import Path
import importlib
import subprocess
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
         "gas": "#e377c2", "ton": "#8c564b", "citygas": "#f2a93b",
         "smp": "#d62728", "temp": "#d62728", "rad": "#ff7f0e", "wind": "#7f7f7f"}


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
def has_table(region: str, table: str) -> bool:
    """테이블 존재 여부 — 보조 테이블(est_horizon_citygas 등)이 없는 DB도 안전하게 처리."""
    con = sqlite3.connect(str(DB[region]))
    try:
        r = con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                        (table,)).fetchone()
        return r is not None
    finally:
        con.close()


# ---------------------------------------------------------------- 운영 실행 (서빙 체인·수집)
# 대시보드에서 러너/수집기를 직접 트리거.
#   - 서빙 체인: 로컬 추론(API 무관) → 무가드.  cwd=ROOT.
#   - 수집(기상/실측): KMA/KPX API 호출 → ★개발단계 임시 비밀번호(OPS_PASSWORD) 게이트.
#     수집기는 .env(API 키)를 load_dotenv()(cwd 기준)로 읽으므로 cwd 를 데이터 폴더로 둔다(cron 과 동일).
# 같은 인터프리터(sys.executable = 이 streamlit 의 venv)로 실행해 로컬·서버 동일 동작.
DATA_DIR = ROOT / "1. data_fetcher_and_db"
SERVE_CHAIN_LAND = ROOT / "7. land_gas_forecaster" / "serve_chain_land_new.py"
COLLECT_FORECAST = DATA_DIR / "core" / "collect_forecast_new.py"   # ① 기상 → forecast_horizon
COLLECT_LAND_HIST = DATA_DIR / "core" / "collect_data_land_new.py"  # ② 실측 → historical
OPS_PASSWORD = "8888"   # ★임시(개발단계). 운영 공개 전 제거/교체할 것.


def run_script(script: Path, args: list[str], timeout: int = 3600,
               cwd: Path | None = None) -> tuple[int, str]:
    """script 를 현재 인터프리터로 실행 → (returncode, stdout+stderr 합본).

    blocking — 호출부에서 st.spinner 로 감싼다.  서빙 체인은 base 당 수 초, 기상 수집은 수 분.
    cwd 미지정이면 ROOT(서빙).  수집기는 cwd=DATA_DIR 로 넘겨 .env 를 찾게 한다.
    """
    try:
        proc = subprocess.run(
            [sys.executable, str(script), *args],
            cwd=str(cwd or ROOT), capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=timeout,
        )
        return proc.returncode, (proc.stdout or "") + (proc.stderr or "")
    except subprocess.TimeoutExpired as e:
        return 124, f"[timeout {timeout}s] {e}"
    except Exception as e:  # noqa: BLE001
        return 1, f"[실행 실패] {e}"


# ---------------------------------------------------------------- 지평 아카이브 (basetime × horizon)
# 예측은 모두 est_horizon_land(tall: base 발행시각 × horizon_d 지평 × timestamp 목표시각)에서
# 읽는다. 구 forecast 테이블(timestamp 단일키 "최신 스냅샷")은 지평이 뭉개져 예측 소스로 안 쓴다.
HZ_TABLE = "est_horizon_land"
HZ_EST_COLS = ["est_demand_land", "est_market_renew_land", "est_net_load_land",
               "est_gas_gen_land", "est_gas_sendout_ton_land", "est_solar_util_land"]


@st.cache_data(ttl=CACHE_TTL)
def land_horizon_meta() -> dict:
    """지평 아카이브 메타 — 발행시각(base) 목록·지평(D+) 범위·목표시각 범위."""
    rng = query("land", f"SELECT MIN(horizon_d) lo_h, MAX(horizon_d) hi_h, "
                        f"MIN(timestamp) lo_t, MAX(timestamp) hi_t FROM {HZ_TABLE}")
    # 발행일(asof) 선택지는 D+1부터 온전히 적재된 base만 — 아카이브 끝의 부분 적재본 제외
    bases = query("land", f"SELECT DISTINCT base FROM {HZ_TABLE} WHERE horizon_d=1 "
                         "ORDER BY base")["base"]
    return {"bases": [pd.Timestamp(b) for b in bases],
            "h_lo": int(rng.loc[0, "lo_h"]), "h_hi": int(rng.loc[0, "hi_h"]),
            "t_lo": str(rng.loc[0, "lo_t"]), "t_hi": str(rng.loc[0, "hi_t"])}


@st.cache_data(ttl=CACHE_TTL)
def land_date_range() -> tuple[str, str]:
    """예측 표시 가능 목표시각 범위 — 지평 아카이브 기준(G-15 ④)."""
    df = query("land", f"SELECT MIN(timestamp) lo, MAX(timestamp) hi FROM {HZ_TABLE} "
                       "WHERE est_demand_land IS NOT NULL")
    return str(df.loc[0, "lo"])[:10], str(df.loc[0, "hi"])[:10]


def _hz_select(region: str, table: str, cols: list[str],
               mode: str, value, start: str, end: str) -> pd.DataFrame:
    """지평 아카이브(base × horizon_d × timestamp)에서 예측 시계열을 뽑는 공용 SQL — 세 정리축.

    mode='latest' : 목표시각마다 '가장 최근 발행본'(가장 짧은 지평) — 운영 best(과거=사실상 D+1).
    mode='asof'   : value=발행시각(base) 고정 → 그 발행본이 내다본 전 구간.
    mode='fixed'  : value=지평(정수 k) 고정 → 모든 목표를 '정확히 k일 전 발행'으로.
    반환: timestamp + base + horizon_d + cols.  land·jeju 공통(테이블/컬럼만 다름).
    """
    collist = ", ".join(cols)
    if mode == "asof":
        base = pd.Timestamp(value).strftime("%Y-%m-%d %H:%M:%S")
        return query(region, f"SELECT timestamp, base, horizon_d, {collist} FROM {table} "
                             "WHERE base=? AND timestamp BETWEEN ? AND ? ORDER BY timestamp",
                     (base, start, end))
    if mode == "fixed":
        return query(region, f"SELECT timestamp, base, horizon_d, {collist} FROM {table} "
                             "WHERE horizon_d=? AND timestamp BETWEEN ? AND ? ORDER BY timestamp",
                     (int(value), start, end))
    ecols = ", ".join(f"e.{c}" for c in cols)
    return query(region, f"SELECT e.timestamp, e.base, e.horizon_d, {ecols} FROM {table} e "
                         f"JOIN (SELECT timestamp, MIN(horizon_d) h FROM {table} "
                         "WHERE timestamp BETWEEN ? AND ? GROUP BY timestamp) m "
                         "ON e.timestamp=m.timestamp AND e.horizon_d=m.h ORDER BY e.timestamp",
                 (start, end))


@st.cache_data(ttl=CACHE_TTL)
def land_est_horizon(mode: str, value, start: str, end: str) -> pd.DataFrame:
    """전국 예측 지평 아카이브(est_horizon_land) — _hz_select 의 land 래퍼.

    반환: timestamp + base + horizon_d + HZ_EST_COLS. 정리축 의미는 _hz_select 참고.
    """
    return _hz_select("land", HZ_TABLE, HZ_EST_COLS, mode, value, start, end)


# ---------------------------------------------------------------- 도시가스 지평 아카이브 (10단계, 보조·일단위)
# 도시가스(난방 중심·기온 기반)는 발전용과 별개인 보조·참고 산출물. 일단위 모델이라
# timestamp = 목표일 00:00. 발전용(ton/h)·도시가스(ton/day) 모두 단위 TON → 일단위에서 합산.
CITYGAS_TABLE = "est_horizon_citygas"


@st.cache_data(ttl=CACHE_TTL)
def land_citygas_horizon(mode: str, value, start: str, end: str) -> pd.DataFrame:
    """도시가스 일단위 송출 예측 — est_horizon_citygas(base × horizon_d × 목표일).

    land_est_horizon 과 같은 정리축(latest/asof/fixed). 테이블 없으면 빈 프레임.
    반환: timestamp(목표일 00:00) + base + horizon_d + est_citygas_sendout.
    """
    empty = pd.DataFrame(columns=["timestamp", "base", "horizon_d", "est_citygas_sendout"])
    if not has_table("land", CITYGAS_TABLE):
        return empty
    cols = "timestamp, base, horizon_d, est_citygas_sendout"
    if mode == "asof":
        base = pd.Timestamp(value).strftime("%Y-%m-%d %H:%M:%S")
        return query("land", f"SELECT {cols} FROM {CITYGAS_TABLE} "
                             "WHERE base=? AND timestamp BETWEEN ? AND ? ORDER BY timestamp",
                     (base, start, end))
    if mode == "fixed":
        return query("land", f"SELECT {cols} FROM {CITYGAS_TABLE} "
                             "WHERE horizon_d=? AND timestamp BETWEEN ? AND ? ORDER BY timestamp",
                     (int(value), start, end))
    return query("land", f"SELECT e.timestamp, e.base, e.horizon_d, e.est_citygas_sendout "
                         f"FROM {CITYGAS_TABLE} e JOIN (SELECT timestamp, MIN(horizon_d) h "
                         f"FROM {CITYGAS_TABLE} WHERE timestamp BETWEEN ? AND ? GROUP BY timestamp) m "
                         "ON e.timestamp=m.timestamp AND e.horizon_d=m.h ORDER BY e.timestamp",
                 (start, end))


@st.cache_data(ttl=CACHE_TTL)
def land_daily_sendout(start_day: pd.Timestamp, end_day: pd.Timestamp,
                       mode: str = "latest", value=None) -> pd.DataFrame:
    """일단위(TON/day) 송출량 — 발전용(시간당 합) + 도시가스(일단위 보조).

    발전용 = est_horizon_land.est_gas_sendout_ton_land 를 날짜별 합(ton/h → ton/day).
    도시가스 = est_horizon_citygas.est_citygas_sendout (이미 일단위). 둘 다 단위 TON.
    반환: date · gen_ton · n_hours · citygas_ton · total_ton (날짜순).
    """
    s = start_day.strftime("%Y-%m-%d 00:00:00")
    e = end_day.strftime("%Y-%m-%d 23:59:59")
    g = land_est_horizon(mode, value, s, e)[["timestamp", "est_gas_sendout_ton_land"]].copy()
    if g.empty:
        gen = pd.DataFrame(columns=["date", "gen_ton", "n_hours"])
    else:
        g["date"] = g["timestamp"].dt.normalize()
        gen = (g.groupby("date")
                 .agg(gen_ton=("est_gas_sendout_ton_land", "sum"),
                      n_hours=("est_gas_sendout_ton_land", "count")).reset_index())
    c = land_citygas_horizon(mode, value, s, e)
    if c.empty:
        cg = pd.DataFrame(columns=["date", "citygas_ton"])
    else:
        c["date"] = c["timestamp"].dt.normalize()
        cg = c[["date", "est_citygas_sendout"]].rename(columns={"est_citygas_sendout": "citygas_ton"})
    out = pd.merge(gen, cg, on="date", how="outer").sort_values("date").reset_index(drop=True)
    out["total_ton"] = out["gen_ton"].fillna(0) + out["citygas_ton"].fillna(0)
    return out


# ---------------------------------------------------------------- 최근 실측 DB 채움 (갭필 후 저장)
# 원칙(사용자 2026-06-15): DB에 현재 시각까지 데이터가 있으면 DB에서 읽고, 없으면(뒤처졌으면)
# 그 부족분만 KPX 라이브 수집 → historical 에 저장.  매번 전체를 다시 긁지 않는다.
# region별 실시간 보강 설정 — (실측 판정 컬럼, fetcher 모듈, fetcher 함수명).
# 수집·저장 로직은 똑같고 호출하는 KPX 창구만 다르다:
#   land = sukub(수급) + 발전실적 두 창구  /  jeju = chejusukub 한 창구(수급+신재생 한 번에).
_LIVE_FETCH = {
    "land": ("real_demand_land", "api_fetchers_land", ("fetch_kpx_land", "fetch_land_power")),
    "jeju": ("real_demand_jeju", "api_fetchers_jeju", ("fetch_kpx_jeju",)),
}


@st.cache_data(ttl=300, show_spinner="최신 실측을 받아 DB에 채우는 중...")
def ensure_recent(region: str, day_str: str) -> int:
    """그 날 historical 이 '현재 가용 시각'까지 비었으면 KPX 부족분만 수집→DB 저장.

    DB가 이미 충분하면 수집하지 않고 0 반환(= DB에서 읽으면 됨).  5분 캐시로 호출 빈도 제한.
    미래일은 즉시 0.  표시 전용 라이브가 아니라 historical 에 partial_upsert 로 영속 저장한다.
    region 으로 호출 창구만 갈린다(land=sukub / jeju=chejusukub) — 로직은 동일.
    """
    demand_col, module, fn_names = _LIVE_FETCH[region]
    now = pd.Timestamp.now()
    day = pd.Timestamp(day_str).normalize()
    if day > now.normalize():
        return 0  # 미래 — 실측 없음
    # 그 날 채워져야 할 마지막 시각(오늘이면 직전 정시, 과거일이면 23시)
    last_needed = (now.floor("h") - pd.Timedelta(hours=1)) if day == now.normalize() \
        else day + pd.Timedelta(hours=23)
    with sqlite3.connect(str(DB[region])) as con:
        row = con.execute(
            f"SELECT MAX(timestamp) FROM historical WHERE timestamp BETWEEN ? AND ? "
            f"AND {demand_col} IS NOT NULL",
            (f"{day_str} 00:00:00", f"{day_str} 23:00:00")).fetchone()
    have = pd.Timestamp(row[0]) if row and row[0] else None
    if have is not None and have >= last_needed:
        return 0  # DB 충분 — 라이브 수집 안 함 (DB에서 읽는다)

    # 부족 → KPX 그 날치만 수집해 historical 에 partial upsert (영속)
    if str(CORE) not in sys.path:
        sys.path.insert(0, str(CORE))
    try:
        mod = importlib.import_module(module)
        from _common import partial_upsert
    except Exception:
        return 0
    parts = []
    for name in fn_names:
        try:
            d = getattr(mod, name)(day_str, day_str, progress=False)
            if d is not None and not d.empty:
                if "timestamp" in d.columns:
                    d = d.set_index("timestamp")
                d.index = pd.to_datetime(d.index)
                parts.append(d)
        except Exception:
            pass
    if not parts:
        return 0
    wide = pd.concat(parts, axis=1)
    wide.index = wide.index.strftime("%Y-%m-%d %H:%M:%S")
    wide.index.name = "timestamp"
    n = partial_upsert("historical", wide, DB[region])
    query.clear()   # DB 갱신 → 조회 캐시 무효화
    return n


def clear_live_caches():
    ensure_recent.clear()
    query.clear()


# ---------------------------------------------------------------- 비교 프레임 (예측 vs 실측, 하루/구간)
def land_range_compare(start_day: pd.Timestamp, end_day: pd.Timestamp,
                       use_live: bool = True, mode: str = "latest",
                       value=None) -> pd.DataFrame:
    """[start_day 00시, end_day 23시] 예측(지평 아카이브) + 실측(historical, 최근 live 보강).

    mode/value = land_est_horizon의 정리축(최신 / 발행일 고정 / 지평 고정).
    실측 net_load는 예측과 같은 기준(수요 − 시장신재생)으로 재구성한다.
    KPX 수요예측(land_est_demand_da)은 day-ahead라 **표시 지평이 D+1인 행에서만** 유효 —
    다른 지평(D+2~15)과는 비교가 성립하지 않으므로 그 행은 비운다.
    """
    s = start_day.strftime("%Y-%m-%d 00:00:00")
    e = end_day.strftime("%Y-%m-%d 23:00:00")
    base = pd.DataFrame({"timestamp": pd.date_range(s, e, freq="h")})

    # DB가 최근 구간(오늘 포함 3일 이내)을 못 따라왔으면 그 부족분만 채워 DB를 최신화한 뒤,
    # 아래는 전부 DB에서 읽는다 (DB에 있으면 수집 안 함 — ensure_recent 가 판정).
    if use_live:
        today = pd.Timestamp.now().normalize()
        for day in pd.date_range(start_day.normalize(), end_day.normalize(), freq="D"):
            if 0 <= (today - day).days <= 3:
                ensure_recent("land", day.strftime("%Y-%m-%d"))

    est = land_est_horizon(mode, value, s, e)
    # KPX DA는 historical에 완전 적재(forecast 스냅샷판은 결측 많음 → 폐기). 동일 값.
    da = query("land", "SELECT timestamp, land_est_demand_da FROM historical "
                       "WHERE timestamp BETWEEN ? AND ? ORDER BY timestamp", (s, e))
    act = query("land", """
        SELECT timestamp, real_demand_land, renew_gen_total_kr, gen_gas_kr
        FROM historical WHERE timestamp BETWEEN ? AND ? ORDER BY timestamp
    """, (s, e))
    df = (base.merge(est, on="timestamp", how="left")
              .merge(da, on="timestamp", how="left")
              .merge(act, on="timestamp", how="left"))
    # KPX DA는 D+1 발표분만 비교 의미가 있음 → 표시 지평이 D+1이 아닌 행은 비운다
    if "horizon_d" in df.columns:
        df.loc[df["horizon_d"] != 1, "land_est_demand_da"] = float("nan")

    df["real_net_load"] = df["real_demand_land"] - df["renew_gen_total_kr"]
    return df


def land_day_compare(day: pd.Timestamp, use_live: bool = True,
                     mode: str = "latest", value=None) -> pd.DataFrame:
    """선택일 00~23시 비교 프레임 (land_range_compare의 하루 버전)."""
    return land_range_compare(day, day, use_live=use_live, mode=mode, value=value)


# ---------------------------------------------------------------- 제주 지평 아카이브·비교 (2→3→4)
# 제주는 수요(2)·신재생/net_load(3) 예측을 est_horizon_jeju, SMP(4)를 est_smp_horizon_jeju 에 적재.
# 발행본(base)=전날 21:00(육지 23:00과 다름)·지평 D+1~7(SMP는 D+1~2). 실측 live 보강은 없음(서버 cron).
JEJU_HZ_TABLE = "est_horizon_jeju"
JEJU_SMP_TABLE = "est_smp_horizon_jeju"
JEJU_EST_COLS = ["est_demand_jeju", "est_solar_gen_jeju", "est_wind_gen_jeju", "est_net_load_jeju",
                 "est_solar_util_jeju", "est_wind_util_jeju"]
JEJU_SMP_COLS = ["est_smp", "smp_neg_proba", "smp_danger"]


@st.cache_data(ttl=CACHE_TTL)
def jeju_date_range() -> tuple[str, str]:
    """제주 예측 표시 가능 목표시각 범위 — est_horizon_jeju 기준."""
    df = query("jeju", f"SELECT MIN(timestamp) lo, MAX(timestamp) hi FROM {JEJU_HZ_TABLE} "
                       "WHERE est_demand_jeju IS NOT NULL")
    return str(df.loc[0, "lo"])[:10], str(df.loc[0, "hi"])[:10]


@st.cache_data(ttl=CACHE_TTL)
def jeju_horizon_range() -> tuple[int, int]:
    """제주 예측 지평(D+) 범위 — est_horizon_jeju 기준(현재 D+1~7)."""
    df = query("jeju", f"SELECT MIN(horizon_d) lo, MAX(horizon_d) hi FROM {JEJU_HZ_TABLE}")
    return int(df.loc[0, "lo"]), int(df.loc[0, "hi"])


def jeju_range_compare(start_day: pd.Timestamp, end_day: pd.Timestamp,
                       use_live: bool = True, mode: str = "latest", value=None) -> pd.DataFrame:
    """[start_day 00시, end_day 23시] 제주 MW 비교(수요·신재생·net_load) + 실측.

    mode/value = 예측 정리축(latest/asof/fixed). 종합 화면은 latest 로 선택일부터 D+1~D+k 창을 본다
    (목표시각마다 가장 최근 발행본 — 발행본 구멍에 강건, 미래 구간은 자연히 긴 지평으로 채워짐).
    신재생 예측 = 태양광+풍력 발전 예측 합. net_load 실측 = 수요−신재생(예측과 같은 기준 재구성).
    KPX 제주 하루전 수요예측(jeju_est_demand_da)은 비교용 참조로 그대로 싣는다(각 날짜의 하루 전 발표분).
    실측 보강은 육지와 동일 — 최근 구간이 DB에 비면 chejusukub 에서 부족분만 채운다(ensure_recent).
    SMP(4)는 별도 jeju_smp_frame 으로 다룬다.
    """
    s = start_day.strftime("%Y-%m-%d 00:00:00")
    e = end_day.strftime("%Y-%m-%d 23:00:00")
    # DB가 최근 구간(오늘 포함 3일 이내)을 못 따라왔으면 그 부족분만 채워 최신화한 뒤 DB에서 읽는다.
    if use_live:
        today = pd.Timestamp.now().normalize()
        for day in pd.date_range(start_day.normalize(), end_day.normalize(), freq="D"):
            if 0 <= (today - day).days <= 3:
                ensure_recent("jeju", day.strftime("%Y-%m-%d"))
    base = pd.DataFrame({"timestamp": pd.date_range(s, e, freq="h")})
    est = _hz_select("jeju", JEJU_HZ_TABLE, JEJU_EST_COLS, mode, value, s, e)
    act = query("jeju", "SELECT timestamp, real_demand_jeju, real_renew_gen_jeju, "
                        "real_solar_gen_jeju, real_wind_gen_jeju, jeju_est_demand_da "
                        "FROM historical WHERE timestamp BETWEEN ? AND ? ORDER BY timestamp", (s, e))
    df = (base.merge(est, on="timestamp", how="left")
              .merge(act, on="timestamp", how="left"))
    df["est_renew_gen_jeju"] = df[["est_solar_gen_jeju", "est_wind_gen_jeju"]].sum(axis=1, min_count=1)
    df["real_net_load_jeju"] = df["real_demand_jeju"] - df["real_renew_gen_jeju"]
    return df


@st.cache_data(ttl=CACHE_TTL)
def jeju_smp_frame(start_day: pd.Timestamp, end_day: pd.Timestamp,
                   mode: str = "asof", value=None) -> pd.DataFrame:
    """[start_day 00시, end_day 23시] 제주 SMP 비교 — 예측(est_smp_horizon_jeju) + 하루전 SMP.

    참조선 = 하루전 SMP(smp_jeju_da). 실시간 SMP(smp_jeju_rt) 수집이 끊겨 이를 대체로 쓴다.
    smp_danger = 음수가격 위험(0/1). 종합 화면은 latest 로 선택일부터 48시간 창을 본다(SMP는 D+1·D+2만 발행).
    """
    s = start_day.strftime("%Y-%m-%d 00:00:00")
    e = end_day.strftime("%Y-%m-%d 23:00:00")
    base = pd.DataFrame({"timestamp": pd.date_range(s, e, freq="h")})
    est = _hz_select("jeju", JEJU_SMP_TABLE, JEJU_SMP_COLS, mode, value, s, e)[
        ["timestamp"] + JEJU_SMP_COLS]
    act = query("jeju", "SELECT timestamp, smp_jeju_da FROM historical "
                        "WHERE timestamp BETWEEN ? AND ? ORDER BY timestamp", (s, e))
    return (base.merge(est, on="timestamp", how="left")
                .merge(act, on="timestamp", how="left"))


# 검증탭 4개 모델 — (표시 라벨, est 컬럼, 실측 컬럼, 지표종류, 설비용량 컬럼).  SMP는 검증탭에서 제외.
#   수요   = MAPE          (분모=실측수요, 크고 안정).
#   순수요 = nMAE          (분모=평균 |net_load| — net_load는 설비용량이 없고 한낮 0 근처라 MAPE는 튐).
#   태양광·풍력 = capmae   (MAE ÷ 설비용량 — 신재생 예측의 표준 nMAE. 저발전 시간 분모 0 문제 회피).
JEJU_ACC_SPECS = [
    ("수요", "est_demand_jeju", "real_demand_jeju", "mape", None),
    ("순수요", "est_net_load_jeju", "real_net_load_jeju", "nmae", None),
    ("태양광", "est_solar_gen_jeju", "real_solar_gen_jeju", "capmae", "real_solar_capacity_jeju"),
    ("풍력", "est_wind_gen_jeju", "real_wind_gen_jeju", "capmae", "real_wind_capacity_jeju"),
]
JEJU_ACC_MODELS = [s[0] for s in JEJU_ACC_SPECS]   # ["수요","순수요","태양광","풍력"]


def _jeju_acc_join(start: str | None, end: str | None) -> pd.DataFrame:
    """검증용 est_horizon_jeju × historical 조인 (검증기간=실측 대상 timestamp). 파생 net_load·설비용량 포함."""
    where, params = [], []
    if start:
        where.append("e.timestamp >= ?"); params.append(f"{start} 00:00:00")
    if end:
        where.append("e.timestamp <= ?"); params.append(f"{end} 23:59:59")
    wsql = ("WHERE " + " AND ".join(where)) if where else ""
    df = query("jeju", f"""
        SELECT e.timestamp, e.horizon_d AS hz,
               e.est_demand_jeju, e.est_net_load_jeju, e.est_solar_gen_jeju, e.est_wind_gen_jeju,
               h.real_demand_jeju, h.real_renew_gen_jeju, h.real_solar_gen_jeju, h.real_wind_gen_jeju,
               h.real_solar_capacity_jeju, h.real_wind_capacity_jeju
        FROM {JEJU_HZ_TABLE} e JOIN historical h ON e.timestamp = h.timestamp {wsql}
        ORDER BY e.timestamp
    """, tuple(params))
    if not df.empty:
        df["real_net_load_jeju"] = df["real_demand_jeju"] - df["real_renew_gen_jeju"]
    return df


def _acc_metric(g: pd.DataFrame, ec: str, ac: str, kind: str, cap_col):
    """(값%, 표본). capmae = MAE ÷ 설비용량(설비용량 기준 nMAE), 그 외 = error_metrics 의 mape/nmae.

    error_metrics 가 |실측|>1e-6 인 시간만 쓰므로 태양광 MAE 는 사실상 낮만 — 그 낮 MAE 를 설비용량으로 나눈다.
    """
    m = error_metrics(g[ec], g[ac])
    if not m:
        return None, 0
    if kind == "capmae":
        cap = g[cap_col].dropna().mean()
        if not cap or cap <= 0:
            return None, m["n"]
        return m["mae"] / cap * 100, m["n"]
    return m[kind], m["n"]


@st.cache_data(ttl=CACHE_TTL)
def jeju_horizon_accuracy(start: str | None = None, end: str | None = None) -> pd.DataFrame:
    """제주 4개 모델의 지평별 정확도 — 검증기간(실측 대상일 = 타깃 timestamp) 안에서 D+1~7 집계.

    수요 = MAPE, 순수요 = nMAE, 태양광·풍력 = 설비용량 기준 nMAE(MAE÷설비용량), 단위 %.
    est_horizon_jeju(D+1~7) × historical 실측. 미래 대상일·실측 없는 칸은 자동 제외.
    반환: index=지평(D+1..), 컬럼=모델별 지표(%, 없으면 None) + 표본(시간).
    """
    mw = _jeju_acc_join(start, end)
    if mw.empty:
        return pd.DataFrame()
    rows = []
    for hz in range(1, int(mw["hz"].max()) + 1):
        g = mw[mw["hz"] == hz]
        rec, n = {"지평": f"D+{hz}"}, 0
        for label, ec, ac, kind, cap_col in JEJU_ACC_SPECS:
            v, nn = _acc_metric(g, ec, ac, kind, cap_col)
            rec[label] = round(v, 1) if v is not None else None
            n = max(n, nn)
        rec["표본"] = n
        rows.append(rec)
    return pd.DataFrame(rows).set_index("지평")


@st.cache_data(ttl=CACHE_TTL)
def jeju_daily_accuracy(start: str, end: str | None, k: int) -> pd.DataFrame:
    """선택 지평 D+k에서 검증기간의 '일별' 정확도 추이 — index=날짜, 컬럼=모델별 지표(%).

    수요 = MAPE, 순수요 = nMAE, 태양광·풍력 = 설비용량 기준 nMAE. 하루 표본 < 8이면 그 날 그 모델은 NaN(낮만인 태양광 보호).
    맑은 날 정확하다가 특정일 급등 = 그 날 기상 급변(비·구름) 신호로 읽는다.
    """
    mw = _jeju_acc_join(start, end)
    if mw.empty:
        return pd.DataFrame()
    mw = mw[mw["hz"] == k]
    if mw.empty:
        return pd.DataFrame()
    grp = mw.groupby(mw["timestamp"].dt.date)
    out = {}
    for label, ec, ac, kind, cap_col in JEJU_ACC_SPECS:
        def _daily(g, ec=ec, ac=ac, kind=kind, cap_col=cap_col):
            v, nn = _acc_metric(g, ec, ac, kind, cap_col)
            return v if (v is not None and nn >= 8) else float("nan")
        out[label] = grp.apply(_daily, include_groups=False)
    res = pd.DataFrame(out)
    res.index = pd.to_datetime(res.index)
    return res


@st.cache_data(ttl=CACHE_TTL)
def jeju_renew_capacity() -> tuple[float, float]:
    """제주 태양광·풍력 설비용량(MW) — historical 최신값. 합산 신재생 이용률 계산용."""
    df = query("jeju", "SELECT real_solar_capacity_jeju s, real_wind_capacity_jeju w FROM historical "
                       "WHERE real_solar_capacity_jeju IS NOT NULL ORDER BY timestamp DESC LIMIT 1")
    if df.empty:
        return float("nan"), float("nan")
    return float(df.loc[0, "s"]), float(df.loc[0, "w"])


# 데이터 현황 히트맵 항목 — (라벨, 테이블, 컬럼, 장지평여부).
# 장지평(D+3 이상) 수집 가능=예보(green) / 불가=실측·근일(blue). SMP는 D+1·D+2뿐이라 장지평 불가(blue).
JEJU_COVERAGE_ITEMS = [
    ("수요 예측", "est_horizon_jeju", "est_demand_jeju", True),
    ("net_load 예측", "est_horizon_jeju", "est_net_load_jeju", True),
    ("태양광 예측", "est_horizon_jeju", "est_solar_gen_jeju", True),
    ("풍력 예측", "est_horizon_jeju", "est_wind_gen_jeju", True),
    ("기상 예보", "forecast_horizon", "temp_west", True),
    ("SMP 예측", "est_smp_horizon_jeju", "est_smp", False),
    ("하루전 SMP", "historical", "smp_jeju_da", False),
    ("수요 실측", "historical", "real_demand_jeju", False),
    ("신재생 실측", "historical", "real_renew_gen_jeju", False),
]


@st.cache_data(ttl=CACHE_TTL)
def jeju_coverage_daily(days_back: int = 30, days_fwd: int = 7) -> pd.DataFrame:
    """제주 주요 항목의 일별 적재율(0~1) — index=항목, columns=날짜(MM-DD). 데이터 현황 히트맵용.

    하루 = 24시간 기준 채워진 비율. 예측 tall 테이블(est_horizon_*)은 목표시각 distinct 기준
    (어느 발행본이든 그 시각을 덮으면 셈) — 발행본별이 아니라 '그 시각 예측이 있나'를 본다.
    """
    today = pd.Timestamp.now().normalize()
    lo, hi = today - pd.Timedelta(days=days_back), today + pd.Timedelta(days=days_fwd)
    s, e = lo.strftime("%Y-%m-%d 00:00:00"), hi.strftime("%Y-%m-%d 23:00:00")
    dates = pd.date_range(lo, hi, freq="D")
    out = {}
    for label, table, col, _lh in JEJU_COVERAGE_ITEMS:
        if not has_table("jeju", table) or col not in table_columns("jeju", table):
            out[label] = [0.0] * len(dates)
            continue
        df = query("jeju", f"SELECT substr(timestamp, 1, 10) d, COUNT(DISTINCT timestamp) n "
                           f"FROM {table} WHERE {col} IS NOT NULL AND timestamp BETWEEN ? AND ? "
                           "GROUP BY d", (s, e))
        m = dict(zip(df["d"], df["n"]))
        out[label] = [min(1.0, m.get(d.strftime("%Y-%m-%d"), 0) / 24) for d in dates]
    return pd.DataFrame(out, index=[d.strftime("%m-%d") for d in dates]).T


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
    # 최근 구간(오늘 포함 3일 이내)이 DB에 비었으면 부족분만 채워 최신화 — 그 외엔 DB만 읽음
    if use_live and 0 <= (pd.Timestamp.now().normalize() - day.normalize()).days <= 3:
        ensure_recent("land", day.strftime("%Y-%m-%d"))
    base = pd.DataFrame({"timestamp": pd.date_range(s, e, freq="h")})
    cols = ", ".join(MIX_GEN_COLS)
    df = base.merge(query("land", f"""
        SELECT timestamp, real_demand_land, {cols}
        FROM historical WHERE timestamp BETWEEN ? AND ? ORDER BY timestamp
    """, (s, e)), on="timestamp", how="left")

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
def land_daily_error_history(end_day: str, days: int = 30,
                             mode: str = "latest", value=None) -> pd.DataFrame:
    """최근 N일 일별 MAPE 추이 (수요/신재생/net_load/가스). 지평 아카이브 적재분만 사용.

    mode/value = 평가 지평(기본 'latest' = 과거 구간이라 사실상 D+1).
    """
    end = pd.Timestamp(end_day)
    s = (end - pd.Timedelta(days=days - 1)).strftime("%Y-%m-%d 00:00:00")
    e = end.strftime("%Y-%m-%d 23:00:00")
    est = land_est_horizon(mode, value, s, e)
    act = query("land", """
        SELECT timestamp, real_demand_land, renew_gen_total_kr, gen_gas_kr
        FROM historical WHERE timestamp BETWEEN ? AND ? ORDER BY timestamp
    """, (s, e))
    act["net_load_actual"] = act["real_demand_land"] - act["renew_gen_total_kr"]
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
            if len(v) < 12:              # 하루 절반 이상 쌓인 날만(진행 중 오늘은 오후 늦게부터 표시)
                return float("nan")
            err = (v[ec] - v[ac]).abs()
            return float(err.mean() / v[ac].abs().mean() * 100) if kind == "nmae" \
                else float((err / v[ac].abs()).mean() * 100)
        out[name] = grp.apply(_daily, include_groups=False)
    return pd.DataFrame(out)


SEASON_MONTHS = {"봄": (3, 4, 5), "여름": (6, 7, 8), "가을": (9, 10, 11), "겨울": (12, 1, 2)}


@st.cache_data(ttl=CACHE_TTL)
def land_horizon_accuracy(start: str | None = None, end: str | None = None,
                          season: str | None = None) -> pd.DataFrame:
    """발행본을 모아 D+1~D+15 지평별 정확도 (est_horizon_land 예측 × historical 실측).

    필터(택일/병용):
      - 기간별: start(발행일 base 하한)·end(상한). 둘 다 None 이면 전 기간.
      - 계절별: season ∈ {봄,여름,가을,겨울} → 타깃 시각의 월로 필터(전 기간 대상).
    수요·net_load·가스 = MAPE, 신재생 = nMAE(심야 분모 문제 회피), 단위 %.  가스 bias·표본 동반.
    최근 발행본의 먼 지평은 실측이 아직 없어 자동 제외 — 긴 지평은 더 오래된 발행본에서 채워진다.
    """
    where, params = [], []
    if start:
        where.append("e.base >= ?"); params.append(f"{start} 00:00:00")
    if end:
        where.append("e.base <= ?"); params.append(f"{end} 23:59:59")
    wsql = ("WHERE " + " AND ".join(where)) if where else ""
    df = query("land", f"""
        SELECT e.timestamp, e.horizon_d AS hz,
               e.est_demand_land, e.est_market_renew_land, e.est_net_load_land, e.est_gas_gen_land,
               h.real_demand_land, h.renew_gen_total_kr, h.gen_gas_kr
        FROM est_horizon_land e JOIN historical h ON e.timestamp = h.timestamp {wsql}
    """, tuple(params))
    if df.empty:
        return pd.DataFrame()
    if season:
        df = df[df["timestamp"].dt.month.isin(SEASON_MONTHS[season])]
        if df.empty:
            return pd.DataFrame()
    df["real_net_load"] = df["real_demand_land"] - df["renew_gen_total_kr"]
    specs = [("수요 MAPE", "est_demand_land", "real_demand_land", "mape"),
             ("신재생 nMAE", "est_market_renew_land", "renew_gen_total_kr", "nmae"),
             ("net_load MAPE", "est_net_load_land", "real_net_load", "mape"),
             ("가스 MAPE", "est_gas_gen_land", "gen_gas_kr", "mape")]
    rows = []
    for hz in range(1, 16):
        g = df[df["hz"] == hz]
        rec = {"지평": f"D+{hz}"}
        n = 0
        for name, ec, ac, kind in specs:
            m = error_metrics(g[ec], g[ac])
            rec[name] = round(m[kind], 1) if m else None
            if m:
                n = max(n, m["n"])
        mg = error_metrics(g["est_gas_gen_land"], g["gen_gas_kr"])
        rec["가스 bias"] = round(mg["bias"], 1) if mg else None
        rec["표본"] = n
        rows.append(rec)
    return pd.DataFrame(rows).set_index("지평")


# ---------------------------------------------------------------- 단가 환산
@st.cache_data(ttl=CACHE_TTL)
def gas_tariff_by_month() -> pd.Series:
    """발전용 가스 단가(원/GJ), 월별. 기본값 = 7-C CSV, 운영 입력값이 그 위를 덮어쓴다.

    CSV(`7c_monthly_price_cost.csv`)는 과거 실적 단가의 폴백이고, 운영 실행 화면에서 입력한
    월 단가(gas_price_store)가 override 로 우선한다. CSV 에 없는 최근·앞으로의 월도 입력해 추가할 수
    있다(끝내 없는 월은 gas_cost_won 이 마지막 값으로 폴백). 저장 후 st.cache_data.clear() 로 반영.
    """
    import gas_price_store as gps
    s = pd.read_csv(PRICE_CSV).set_index("ym")["tariff_gen_won_per_GJ"].dropna()
    ov = gps.load_overrides()                      # 운영 입력값 = override(DB 우선)
    if ov:
        s = s.copy()
        for ym, v in ov.items():
            s.loc[ym] = float(v)
    return s.sort_index()


def gas_cost_won(ts: pd.Series, ton: pd.Series) -> pd.Series:
    tariff = gas_tariff_by_month()
    t = ts.dt.strftime("%Y-%m").map(tariff).fillna(tariff.iloc[-1])
    return ton * GJ_PER_TON * t


# ---------------------------------------------------------------- 적재 현황
COVERAGE = {
    "land": [
        # 예측 정본 = est_horizon_land(지평 아카이브). 기상 정본 = forecast_horizon.
        ("est_horizon_land", "수요 예측 — 5단계", "est_demand_land"),
        ("est_horizon_land", "신재생 예측 — 6단계", "est_market_renew_land"),
        ("est_horizon_land", "net_load 예측 — 6단계", "est_net_load_land"),
        ("est_horizon_land", "가스 발전 예측 — 7단계", "est_gas_gen_land"),
        ("est_horizon_land", "가스 송출량 예측 — 7단계", "est_gas_sendout_ton_land"),
        ("est_horizon_citygas", "도시가스 송출량 예측 — 10단계(보조)", "est_citygas_sendout"),
        ("forecast_horizon", "기상 예보 아카이브(서산 기온)", "temp_seosan"),
        ("historical", "수요 실측(KPX)", "real_demand_land"),
        ("historical", "신재생 실측(KPX)", "renew_gen_total_kr"),
        ("historical", "가스 발전 실측(KPX)", "gen_gas_kr"),
        ("historical", "KPX 수요예측 DA", "land_est_demand_da"),
        ("historical", "기상 관측(서산 일사)", "solar_rad_seosan"),
    ],
    "jeju": [
        # 예측 정본 = est_horizon_jeju·est_smp_horizon_jeju(지평 아카이브). 기상 정본 = forecast_horizon.
        ("est_horizon_jeju", "수요 예측 — 2단계", "est_demand_jeju"),
        ("est_horizon_jeju", "net_load 예측 — 3단계", "est_net_load_jeju"),
        ("est_horizon_jeju", "태양광 이용률 예측 — 3단계", "est_solar_util_jeju"),
        ("est_horizon_jeju", "풍력 이용률 예측 — 3단계", "est_wind_util_jeju"),
        ("est_smp_horizon_jeju", "SMP 예측 — 4단계", "est_smp"),
        ("est_smp_horizon_jeju", "SMP 음수경보 — 4단계", "smp_danger"),
        ("forecast_horizon", "기상 예보 아카이브(서부 기온)", "temp_west"),
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
        tables = {t for t, _, _ in COVERAGE[region]}
        have = {t: {r[1] for r in con.execute(f"PRAGMA table_info({t})")} for t in tables}
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


# 시간당 점을 둥근 곡선으로 잇는 정도(0~1.3). 시각화 전용 — 직선 이음의 각진 느낌을 부드럽게.
# 클수록 더 둥글지만 급변 구간(태양광 일출 등)에서 곡선이 0 아래로 살짝 휠 수 있어 보수적으로 0.6.
LINE_SMOOTHING = 0.6


def add_actual(fig: go.Figure, ts, y, name: str, color: str, **kw):
    fig.add_trace(go.Scatter(x=ts, y=y, name=name,
                             line=dict(color=color, width=2, shape="spline",
                                       smoothing=LINE_SMOOTHING), **kw))


def add_forecast(fig: go.Figure, ts, y, name: str, color: str, **kw):
    fig.add_trace(go.Scatter(x=ts, y=y, name=name,
                             line=dict(color=color, dash="dot", width=2, shape="spline",
                                       smoothing=LINE_SMOOTHING), **kw))


def land_forecast_origin(day: pd.Timestamp) -> str | None:
    """선택일 24h 예측의 발행 시각(base)·지평 라벨 — mode='latest'. '발행 MM-DD HH시 (D+k)' 또는 None.

    하루는 보통 한 발행본이라 대표(최빈) base 를 쓴다. est_horizon_land 직접 조회(KPX live 무관).
    """
    start = day.strftime("%Y-%m-%d 00:00:00")
    end = day.strftime("%Y-%m-%d 23:00:00")
    df = land_est_horizon("latest", None, start, end)
    base_s = df["base"].dropna() if "base" in df.columns else pd.Series(dtype=object)
    if base_s.empty:
        return None
    top = base_s.mode().iloc[0]
    hzs = df.loc[df["base"] == top, "horizon_d"].dropna()
    htxt = f" (D+{int(hzs.iloc[0])})" if not hzs.empty else ""
    return f"발행 {pd.Timestamp(top):%m-%d %H시}{htxt}"


def hz_hover(df: pd.DataFrame):
    """예측 트레이스용 (customdata, hovertemplate) — 커서에 발행일(base)·지평(D+) 표시.

    df는 land_est_horizon/land_range_compare 산출(컬럼 base·horizon_d 포함)을 가정.
    """
    b = df["base"] if "base" in df.columns else [None] * len(df)
    h = df["horizon_d"] if "horizon_d" in df.columns else [None] * len(df)
    cd = []
    for bb, hh in zip(b, h):
        if pd.isna(bb) or pd.isna(hh):
            cd.append(["—"])
        else:
            cd.append([f"발행 {pd.Timestamp(bb):%Y-%m-%d %H시} · D+{int(hh)}"])
    tmpl = ("%{x|%m-%d %H시} · %{y:,.0f} MW<br>%{customdata[0]}"
            "<extra>%{fullData.name}</extra>")
    return cd, tmpl


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

/* ---- AI 브리핑 카드 — 연한 톤 + 좌측 강조선, 글머리별 줄바꿈 ---- */
.brief-card{
  background:#f4faf7; border:1px solid #d7e6dd; border-left:3px solid #059669;
  border-radius:12px; padding:.75rem .95rem; margin:.15rem 0 .5rem;
  box-shadow:0 1px 2px rgba(15,23,42,.04); }
.brief-card .bi{
  position:relative; padding-left:1.05rem; margin:.34rem 0; line-height:1.62;
  color:#1f2937; font-size:.93rem; }
.brief-card .bi:before{
  content:"•"; position:absolute; left:.1rem; top:-.02rem;
  color:#059669; font-weight:700; }
.brief-card .bi:first-child{ margin-top:.05rem; }
.brief-card .bi:last-child{ margin-bottom:.05rem; }

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
                          help="최근 구간 실측(KPX 수급·발전실적)을 다시 불러옵니다"):
            clear_live_caches()
        i += 1
    n = None
    if ndays:
        n = cols[i].slider("표시 기간(일)", ndays[0], ndays[1], ndays[2],
                           key=f"{prefix}_ndays",
                           help="시작일부터 N일 — 사전 적재된 예측을 읽기만 하므로 지연 없음")
    return pd.Timestamp(st.session_state[key]), n, cols[-1]


# 예측 기준(basetime × horizon) 선택 — est_horizon_land의 세 정리축을 UI로 노출.
HZ_MODES = {"최신 발행": "latest", "발행일 고정": "asof", "지평 고정 (D+k)": "fixed"}


def horizon_picker(prefix: str) -> tuple[str, object, str]:
    """예측 기준 컨트롤 — (mode, value, label) 반환.  해석을 쉬운 말로 안내.

    최신 발행  = 각 날짜를 '가장 최근에 예측한' 값(과거 구간은 사실상 하루 전 예측).
    발행일 고정 = '특정 날짜에 예측한' 결과 — 그 날 기준 앞으로 며칠치(D+1~D+15)를 그대로.
    지평 고정  = '며칠 전에 예측했는지(k일 전)'를 고정 — 모든 날짜를 k일 전 예측으로 통일.
    """
    meta = land_horizon_meta()
    c0, c1 = st.columns([1.3, 3], vertical_alignment="bottom")
    pick = c0.segmented_control("예측 기준", list(HZ_MODES), default="최신 발행",
                                key=f"{prefix}_hzmode") or "최신 발행"
    mode = HZ_MODES[pick]
    if mode == "asof":
        bases = meta["bases"]
        b = c1.select_slider("예측을 돌린 날짜", options=bases, value=bases[-1],
                             key=f"{prefix}_hzbase",
                             format_func=lambda t: f"{t:%Y-%m-%d}에 예측",
                             help="그 날짜에 예측한 예보가 내다본 앞으로 며칠치"
                                  "(D+1~D+15, 최대 15일 뒤)를 그대로 보여줍니다.")
        return mode, b, f"{b:%Y-%m-%d}에 예측한 예보 (앞으로 D+1~D+{meta['h_hi']})"
    if mode == "fixed":
        k = c1.slider("며칠 전에 예측한 값인지 (D+k)", meta["h_lo"], meta["h_hi"], 1,
                      key=f"{prefix}_hzk",
                      help="모든 날짜를 '정확히 k일 전에 예측한' 값으로 통일합니다. "
                           "예: D+3 이면 각 날짜를 3일 전에 미리 예측한 값.")
        return mode, k, f"D+{k} — 각 날짜를 {k}일 전에 예측한 값"
    c1.caption("각 날짜를 '가장 최근에 예측한' 값으로 보여줍니다 — 과거 구간은 사실상 하루 전(D+1) 예측입니다.")
    return "latest", None, "가장 최근 예측 (날짜별 최신 발행본)"


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

"""kma_new 예비 EDA 공용 라이브러리 (2026-07-05)

표본: v2 격리 DB 의 장마철 9~10 발행일(06-25~07-04), D+1~12.
목적: 신규 변수(직달/산란 일사·1h 운량·cape/cinn/hpbl·해면기압·대기상단일사)의
      특성·물리 정합·예보 정확도를 신재생/급변동 관점에서 정직하게 본다.

★규약: radiation 단위 = MJ/m^2/h, total_cloud = 0~1 비율. 인코딩 utf-8.
"""
from __future__ import annotations
import sqlite3
from pathlib import Path
import numpy as np
import pandas as pd

BASE = Path(__file__).resolve().parents[2]      # 1. data_fetcher_and_db
DB_V2_LAND = BASE / "data" / "v2_land.db"
DB_V2_JEJU = BASE / "data" / "v2_jeju.db"
DB_LAND    = BASE / "data" / "input_data_land.db"
DB_JEJU    = BASE / "data" / "input_data_jeju.db"
FIGS = Path(__file__).resolve().parent / "figs"
FIGS.mkdir(exist_ok=True)

POINTS = {
    "land": [
        {"sfx": "daegwallyeong", "ko": "대관령", "lat": 37.6772, "lon": 128.7185},
        {"sfx": "wonju",         "ko": "원주",   "lat": 37.3376, "lon": 127.9466},
        {"sfx": "seosan",        "ko": "서산",   "lat": 36.7766, "lon": 126.4939},
        {"sfx": "pohang",        "ko": "포항",   "lat": 36.0327, "lon": 129.3799},
        {"sfx": "yeonggwang",    "ko": "영광",   "lat": 35.2807, "lon": 126.4750},
    ],
    "jeju": [
        {"sfx": "west",  "ko": "제주서(고산)",   "lat": 33.4427, "lon": 126.1713},
        {"sfx": "east",  "ko": "제주동(성산)",   "lat": 33.3868, "lon": 126.8802},
        {"sfx": "south", "ko": "제주남(태양광)", "lat": 33.3284, "lon": 126.8366},
    ],
}
MJ = 0.0036   # W/m^2 -> MJ/m^2/h (현행 규약)


# ── 폰트(맑은 고딕, 흰 배경) ─────────────────────────────────────────────
def setup_mpl():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams.update({
        "font.family": "Malgun Gothic",
        "axes.unicode_minus": False,
        "figure.facecolor": "white",
        "axes.facecolor": "white",
        "savefig.facecolor": "white",
        "figure.dpi": 110,
        "axes.grid": True,
        "grid.alpha": 0.25,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "font.size": 10,
    })
    return plt


# ── 예보(v2 격리 DB) 로더 ────────────────────────────────────────────────
def load_forecast(region: str, table: str = "forecast_horizon") -> pd.DataFrame:
    db = DB_V2_LAND if region == "land" else DB_V2_JEJU
    con = sqlite3.connect(db)
    df = pd.read_sql(f"SELECT * FROM {table}", con,
                     parse_dates=["timestamp", "base"])
    con.close()
    df = df.rename(columns={"timestamp": "ts"})
    return df


# ── 실측(historical) 로더 ────────────────────────────────────────────────
WX_ACT = {  # 실측 컬럼 접두(지점별 접미 붙음)
    "land": ["solar_rad", "temp_c", "total_cloud", "midlow_cloud", "wind_spd", "rainfall"],
    "jeju": ["solar_rad", "temp_c", "total_cloud", "midlow_cloud", "wind_spd", "rainfall"],
}
TARGETS = {
    "land": ["gen_solar_market_kr", "gen_solar_btm_kr", "gen_solar_ppa_kr",
             "gen_wind_kr", "gen_wind_capacity_kr", "gen_gas_kr",
             "net_load_kr", "real_demand_land"],
    "jeju": ["real_solar_gen_jeju", "real_wind_gen_jeju",
             "real_solar_utilization_jeju", "real_wind_utilization_jeju",
             "real_demand_jeju", "real_solar_capacity_jeju", "real_wind_capacity_jeju"],
}


def load_actuals(region: str, t0="2026-06-20", t1="2026-07-05") -> pd.DataFrame:
    db = DB_LAND if region == "land" else DB_JEJU
    con = sqlite3.connect(db)
    allc = [r[1] for r in con.execute("PRAGMA table_info(historical)")]
    con.close()
    want = ["timestamp"]
    for pre in WX_ACT[region]:
        want += [c for c in allc if c.startswith(pre + "_")]
    want += [c for c in TARGETS[region] if c in allc]
    con = sqlite3.connect(db)
    df = pd.read_sql(f"SELECT {','.join(dict.fromkeys(want))} FROM historical "
                     f"WHERE timestamp>='{t0}' AND timestamp<'{t1}'", con,
                     parse_dates=["timestamp"])
    con.close()
    return df.rename(columns={"timestamp": "ts"})


# ── pvlib 청천일사·태양고도 (야간 마스크·청명도 Kt 분모) ──────────────────
def solar_geometry(region: str) -> pd.DataFrame:
    """지점×시각별 태양고도(elevation)·청천 GHI(MJ) — 06-20~07-05 1h."""
    import pvlib
    idx = pd.date_range("2026-06-20", "2026-07-05", freq="1h", tz="Asia/Seoul")
    rows = []
    for p in POINTS[region]:
        loc = pvlib.location.Location(p["lat"], p["lon"], tz="Asia/Seoul")
        sp = loc.get_solarposition(idx)
        cs = loc.get_clearsky(idx, model="ineichen")   # GHI W/m^2
        rows.append(pd.DataFrame({
            "ts": idx.tz_localize(None),
            "sfx": p["sfx"],
            "elev": sp["apparent_elevation"].values,
            "cs_ghi_mj": cs["ghi"].values * MJ,
        }))
    return pd.concat(rows, ignore_index=True)


# ── 예보(wide) → 지점 long 변환 도우미 ───────────────────────────────────
def melt_points(df: pd.DataFrame, region: str, cols_base: list[str]) -> pd.DataFrame:
    """cols_base=['radiation','radiation_direct',...] 를 지점 long 으로.
    반환: [base, ts, horizon_d, sfx, <cols_base...>]"""
    keep = ["base", "ts", "horizon_d"]
    out = []
    for p in POINTS[region]:
        sfx = p["sfx"]
        ren = {f"{c}_{sfx}": c for c in cols_base if f"{c}_{sfx}" in df.columns}
        if not ren:
            continue
        sub = df[keep + list(ren)].rename(columns=ren).copy()
        sub["sfx"] = sfx
        out.append(sub)
    return pd.concat(out, ignore_index=True)


def mae(a, b):
    d = (np.asarray(a, float) - np.asarray(b, float))
    d = d[~np.isnan(d)]
    return float(np.abs(d).mean()) if len(d) else np.nan


def bias(a, b):
    d = (np.asarray(a, float) - np.asarray(b, float))
    d = d[~np.isnan(d)]
    return float(d.mean()) if len(d) else np.nan


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    for reg in ("land", "jeju"):
        fc = load_forecast(reg)
        ac = load_actuals(reg)
        print(f"[{reg}] forecast {fc.shape}  bases={fc.base.dt.date.nunique()}  "
              f"actuals {ac.shape}")
    g = solar_geometry("land")
    print("solar_geometry 예:", g.head(2).to_dict("records"))

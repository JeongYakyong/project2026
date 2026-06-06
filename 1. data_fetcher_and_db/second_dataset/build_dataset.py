# -*- coding: utf-8 -*-
"""
A0/A1 데이터 확보·분리 빌더 (PRD §5.0, §5.1)
- 마스터셋 결합(제주/전국) → 결측·중복·시간구멍 감사(채우기 전) → LNG 타깃 도출+backfill
  → 정답/피처/금지 라벨링 → 시간순 split → parquet/딕셔너리/감사보고서 출력.
모든 경로는 repo 루트(이 파일의 상위) 기준. DB는 읽기 전용으로만 연다.
"""
import os, sqlite3, json
import pandas as pd, numpy as np

# 이 파일은 "1. data_fetcher_and_db/second_dataset/" 안에 위치한다.
HERE = os.path.dirname(os.path.abspath(__file__))     # .../second_dataset
FETCHER_DIR = os.path.dirname(HERE)                    # .../1. data_fetcher_and_db
ROOT = os.path.dirname(FETCHER_DIR)                    # repo 루트
JEJU_DB = os.path.join(FETCHER_DIR, "data", "input_data_jeju.db")
LAND_DB = os.path.join(FETCHER_DIR, "data", "input_data_land.db")
CSV = os.path.join(ROOT, "7. data from csv")  # TODO: 실제 원천 CSV 위치로 지정 필요(현재 해당 폴더 없음)
OUT = os.path.join(HERE, "data")              # second_dataset/data (기존 stale "8. lng_dataset/data" 대체)
os.makedirs(OUT, exist_ok=True)

# 게이트 G-4(충실본): merit-order 부하수준별 분해. fit_merit_split.py 산출물 사용.
MERIT_PATH = os.path.join(OUT, "merit_split_2024.json")
HVDC_LAST = "2025-04-01 00:00:00"   # G-3: 마스터 HVDC 가용 끝(이후 결손)


def load_merit_split():
    """fuel_gen → (oil_hat, lng_hat) merit-order 분해함수 로드."""
    if not os.path.exists(MERIT_PATH):
        raise FileNotFoundError("먼저 fit_merit_split.py 를 실행해 merit_split_2024.json 생성")
    m = json.load(open(MERIT_PATH))
    fg, og_ = np.array(m["fuel_grid"]), np.array(m["oil_grid"])

    def split_lng(fuel):
        fuel = np.asarray(fuel, float)
        oil = np.interp(fuel, fg, og_)
        return np.clip(fuel - oil, 0, fuel)
    return split_lng, m

audit = {"gates": {}, "missing": {}, "duplicates": {}, "gaps": {}, "target": {}, "splits": {}}


def read_sql(db, q, **kw):
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        return pd.read_sql(q, con, **kw)
    finally:
        con.close()


# ---------------------------------------------------------------- 달력 피처
def add_calendar(df):
    ts = df["timestamp"]
    df["hour"] = ts.dt.hour
    df["dow"] = ts.dt.dayofweek
    df["month"] = ts.dt.month
    df["doy"] = ts.dt.dayofyear
    df["year"] = ts.dt.year
    df["hour_sin"] = np.sin(2 * np.pi * df.hour / 24)
    df["hour_cos"] = np.cos(2 * np.pi * df.hour / 24)
    df["month_sin"] = np.sin(2 * np.pi * df.month / 12)
    df["month_cos"] = np.cos(2 * np.pi * df.month / 12)
    df["doy_sin"] = np.sin(2 * np.pi * df.doy / 365.25)
    df["doy_cos"] = np.cos(2 * np.pi * df.doy / 365.25)
    return df


def audit_frame(name, df, key="timestamp", freq="h"):
    """채우기 전 결측·중복·시간구멍 집계 (PRD §5.0-1)."""
    dup = int(df[key].duplicated().sum())
    full = pd.date_range(df[key].min(), df[key].max(), freq=freq)
    gaps = full.difference(df[key])
    miss = df.isna().sum()
    miss = miss[miss > 0].sort_values(ascending=False)
    audit["duplicates"][name] = dup
    audit["gaps"][name] = {"count": int(len(gaps)),
                           "first": str(gaps.min()) if len(gaps) else None,
                           "last": str(gaps.max()) if len(gaps) else None}
    audit["missing"][name] = {k: int(v) for k, v in miss.items()}
    print(f"[audit:{name}] rows={len(df)} dup={dup} time_gaps={len(gaps)} "
          f"cols_with_na={len(miss)}")


# ================================================================ 제주
def build_jeju():
    print("\n=== 제주 마스터셋 ===")
    h = read_sql(JEJU_DB,
        "select timestamp, day_type, real_demand_jeju, real_renew_gen_jeju, "
        "real_solar_gen_jeju, real_wind_gen_jeju, real_net_load_jeju, "
        "temp_c_west, temp_c_east, temp_c_south, "
        "smp_jeju_rt, smp_rt_neg_num from historical",
        parse_dates=["timestamp"])

    # G-1: net_load = demand - renew_total (DB 컬럼은 2025-12-13~ 만 채워짐 → 전구간 도출)
    h["net_load"] = h["real_demand_jeju"] - h["real_renew_gen_jeju"]

    # 외생: HVDC(실측, ~2025-04) / only_gen 실측 LNG·유류(2020~2024) / 유가(일)
    hv = pd.read_csv(os.path.join(CSV, "jeju_hvdc_hourly.csv"), parse_dates=["timestamp"])
    hv = hv[["timestamp", "HVDC_Total"]]
    og = pd.read_csv(os.path.join(CSV, "only_gen.csv"), parse_dates=["timestamp"])
    og = og.rename(columns={"LNG_Gen": "lng_meas", "Oil_Gen": "oil_meas",
                            "HVDC_Total": "hvdc_og"})
    oil = pd.read_csv(os.path.join(CSV, "oil_price_daily.csv"), parse_dates=["date"])
    oil["date"] = oil["date"].dt.normalize()

    m = h.merge(hv, on="timestamp", how="left").merge(
        og[["timestamp", "lng_meas", "oil_meas"]], on="timestamp", how="left")
    m["date"] = m["timestamp"].dt.normalize()
    m = m.merge(oil[["date", "Dubai", "Brent", "WTI"]], on="date", how="left")
    m = add_calendar(m)

    audit_frame("jeju", m)

    # ---- A1: LNG 타깃 도출 + backfill (PRD §5.1, merit-order 분해) ----
    # 2020~2024: only_gen 실측 그대로 정답(target_source=measured)
    # 2025-01~2025-04(HVDC 가용): fuel_gen=net_load-HVDC, lng=merit_split(fuel_gen) (derived)
    # 그 이후: HVDC 없음 → 타깃 없음(none, 예측경로 5.2에서 처리)
    split_lng, merit = load_merit_split()
    m["fuel_gen"] = m["net_load"] - m["HVDC_Total"]
    lng = m["lng_meas"].copy()
    src = pd.Series(np.where(m["lng_meas"].notna(), "measured", "none"), index=m.index)

    der_mask = (m["lng_meas"].isna() & m["fuel_gen"].notna() &
                (m["timestamp"] <= pd.Timestamp(HVDC_LAST)))
    lng_der = pd.Series(split_lng(m["fuel_gen"].fillna(0).values), index=m.index)
    lng = lng.where(~der_mask, lng_der)
    src = src.where(~der_mask, "derived")
    m["lng_gen"] = lng
    m["target_source"] = src.values
    # 모델 사용 가능 플래그: 실측 타깃만 True. derived(추정)/none은 False
    # (제주 타깃 불완전성 명시 — 전국과의 비대칭을 행 단위로 표기)
    m["model_usable"] = (m["target_source"] == "measured")

    # 정합 검증(G-2/G-4): 2024(=도출 대상 2025와 동일 레짐)에서 merit 도출식 vs 실측.
    # 2020~2023은 LNG 점유율이 낮은 별도 레짐이라 2024 곡선 적용은 부적절 → 검증 제외.
    val = m[(m.year == 2024) & m.lng_meas.notna() & m.fuel_gen.notna()].copy()
    val["lng_from_fuel"] = split_lng(val.fuel_gen.values)
    err = (val.lng_from_fuel - val.lng_meas)
    mae = err.abs().mean()
    mape = (err.abs() / val.lng_meas.replace(0, np.nan)).mean() * 100
    audit["target"]["jeju"] = {
        "measured_rows": int((src == "measured").sum()),
        "derived_rows": int((src == "derived").sum()),
        "none_rows": int((src == "none").sum()),
        "split_method": "merit_order_isotonic_2024",
        "derive_check_2024_MAE": round(float(mae), 3),
        "derive_check_2024_MAPE_pct": round(float(mape), 3),
        "merit_backtest_random_5050x5": merit["backtest_random_5050x5"],
        "scalar_baseline_2024": merit["insample_2024"],
    }
    print(f"[jeju target] measured={int((src=='measured').sum())} "
          f"derived={int((src=='derived').sum())} none={int((src=='none').sum())} "
          f"| 도출식 검증 MAE={mae:.2f} MAPE={mape:.2f}%")

    # ---- 시간순 split (PRD §5.0-3) : 학습/검증은 실측 정답 구간만 ----
    m["split"] = "unused"
    m.loc[(m.year <= 2023) & (m.target_source == "measured"), "split"] = "train"
    m.loc[(m.year == 2024) & (m.target_source == "measured"), "split"] = "val"
    m.loc[m.target_source == "derived", "split"] = "demo"   # 자기참조 → 정확도 제외
    audit["splits"]["jeju"] = m["split"].value_counts().to_dict()

    return m


# ---- 제주 서빙(예측경로 5.2): forecast의 est_net_load → 동일 피처 ----
def build_jeju_serving():
    f = read_sql(JEJU_DB,
        "select timestamp, day_type, est_net_load_jeju, "
        "temp_west, temp_east, temp_south from forecast",
        parse_dates=["timestamp"])
    f = f.rename(columns={"est_net_load_jeju": "net_load",
                          "temp_west": "temp_c_west", "temp_east": "temp_c_east",
                          "temp_south": "temp_c_south"})
    f = f.dropna(subset=["net_load"]).reset_index(drop=True)
    f = add_calendar(f)
    print(f"[jeju serving] rows={len(f)} range={f.timestamp.min()}~{f.timestamp.max()}")
    return f


# ================================================================ 전국
def build_land():
    print("\n=== 전국 마스터셋 ===")
    cols = ("timestamp, day_type, real_demand_land, net_load_kr, renew_gen_total_kr, "
            "gen_gas_kr, gen_oil_kr, gen_coal_kr, gen_nuclear_kr, gen_wind_kr, "
            "temp_c_daegwallyeong, temp_c_wonju, temp_c_seosan, temp_c_pohang, "
            "temp_c_yeonggwang, smp_land_da")
    h = read_sql(LAND_DB, f"select {cols} from historical", parse_dates=["timestamp"])
    h = add_calendar(h)
    audit_frame("land", h)

    # 타깃 = gen_gas_kr 실측(자기참조 없음, 검증목표2 최강 증거)
    h["target_source"] = np.where(h["gen_gas_kr"].notna(), "measured", "none")
    # 전국은 전 구간 실측 → 사실상 전부 True (제주와 대비되는 완전 타깃)
    h["model_usable"] = (h["target_source"] == "measured")
    audit["target"]["land"] = {
        "measured_rows": int((h.target_source == "measured").sum()),
        "none_rows": int((h.target_source == "none").sum()),
    }

    # 시간순 split: train 2020-2023 / val 2024 / test 2025~ (전부 실측 정답 존재)
    h["split"] = "unused"
    ok = h["target_source"] == "measured"
    h.loc[ok & (h.year <= 2023), "split"] = "train"
    h.loc[ok & (h.year == 2024), "split"] = "val"
    h.loc[ok & (h.year >= 2025), "split"] = "test"
    audit["splits"]["land"] = h["split"].value_counts().to_dict()
    print(f"[land] split={h['split'].value_counts().to_dict()}")
    return h


# ================================================================ KOGAS 월별(A3 환산용)
def build_kogas_monthly():
    print("\n=== KOGAS 월별 (A3 환산 참조) ===")
    t = pd.read_csv(os.path.join(CSV, "gas_tariff_2020_2026.csv"), encoding="utf-8-sig")
    t = t.rename(columns={"연월": "ym", "단위": "unit", "구분": "cat",
                          "항목": "item", "값": "value"})
    # 일반발전 합계만 추출(원/GJ, 원/Nm3)
    gj = t[(t.cat == "일반발전") & (t.item == "합계") & (t.unit == "원/GJ")][["ym", "value"]]
    gj = gj.rename(columns={"value": "tariff_gen_won_per_GJ"})
    nm = t[(t.cat == "일반발전") & (t.item == "합계") & (t.unit == "원/Nm3")][["ym", "value"]]
    nm = nm.rename(columns={"value": "tariff_gen_won_per_Nm3"})
    ip = pd.read_csv(os.path.join(CSV, "gas_import_price_monthly.csv"), encoding="utf-8-sig")
    ip = ip.rename(columns={"연월": "ym", "평균(MMBTU당달러)": "import_usd_per_MMBTU_avg"})
    ip = ip[["ym", "import_usd_per_MMBTU_avg"]]
    te = pd.read_csv(os.path.join(CSV, "gas_temp_effect_monthly.csv"), encoding="utf-8-sig")
    te = te.rename(columns={"연월": "ym", "기온효과": "temp_effect"})

    k = gj.merge(nm, on="ym", how="outer").merge(ip, on="ym", how="outer").merge(
        te, on="ym", how="outer")
    k["ym"] = pd.to_datetime(k["ym"]).dt.to_period("M").astype(str)
    k = k.sort_values("ym").reset_index(drop=True)
    print(f"[kogas] rows={len(k)} cols={list(k.columns)}")
    return k


# 누수원(타깃 도출식 입력·동시결정 발전·발행지연 SMP) — full 데이터셋에서 제외
FORBIDDEN = {
    "jeju": ["HVDC_Total", "fuel_gen", "lng_meas", "oil_meas",
             "smp_jeju_rt", "smp_rt_neg_num"],
    "land": ["gen_oil_kr", "gen_coal_kr", "gen_nuclear_kr", "gen_wind_kr"],
}


def make_full(df, region):
    """전 구간(2020~2026) 모델링용 단일 데이터셋: 누수컬럼만 제외, 전 행 유지.
    target/target_source/model_usable/split 라벨 포함 → 제주 타깃 불완전성이 행 단위로 드러남."""
    full = df.drop(columns=FORBIDDEN[region], errors="ignore").reset_index(drop=True)
    n_usable = int(full["model_usable"].sum())
    audit["full"] = audit.get("full", {})
    audit["full"][region] = {"rows": len(full), "cols": len(full.columns),
                             "model_usable_rows": n_usable,
                             "not_usable_rows": int(len(full) - n_usable)}
    print(f"[full:{region}] rows={len(full)} cols={len(full.columns)} "
          f"model_usable={n_usable} not_usable={len(full) - n_usable}")
    return full


def write_outputs(jeju, jeju_srv, land, kogas):
    jeju = jeju.drop(columns=["date"], errors="ignore")
    jeju.to_parquet(os.path.join(OUT, "jeju_master.parquet"), index=False)
    jeju_srv.to_parquet(os.path.join(OUT, "jeju_serving.parquet"), index=False)
    land.to_parquet(os.path.join(OUT, "land_master.parquet"), index=False)
    kogas.to_parquet(os.path.join(OUT, "kogas_monthly.parquet"), index=False)
    # 전 구간 모델링용 단일 데이터셋(누수컬럼 제외, 제주 불완전 타깃 플래그 포함)
    make_full(jeju, "jeju").to_parquet(os.path.join(OUT, "jeju_full.parquet"), index=False)
    make_full(land, "land").to_parquet(os.path.join(OUT, "land_full.parquet"), index=False)
    # split별 분리 파일(제주 train/val, 전국 train/val/test)
    for s in ["train", "val"]:
        jeju[jeju.split == s].to_parquet(os.path.join(OUT, f"jeju_{s}.parquet"), index=False)
    for s in ["train", "val", "test"]:
        land[land.split == s].to_parquet(os.path.join(OUT, f"land_{s}.parquet"), index=False)
    with open(os.path.join(OUT, "audit.json"), "w", encoding="utf-8") as f:
        json.dump(audit, f, ensure_ascii=False, indent=2)
    print("\n[written] parquet + audit.json ->", OUT)


if __name__ == "__main__":
    jeju = build_jeju()
    jeju_srv = build_jeju_serving()
    land = build_land()
    kogas = build_kogas_monthly()
    write_outputs(jeju, jeju_srv, land, kogas)
    print("\nDONE")

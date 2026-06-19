# -*- coding: utf-8 -*-
"""DB -> Colab 학습용 CSV 추출 (전국 수요 Cross-Attention PatchTST + RevIN, 5-B).

`1. data_fetcher_and_db/data/input_data_land.db` 의 `historical` 에서 v2 지점선택 기상
원천 + real_demand_land + day_type 을 추출하고, 외부 `kr_elec_capa.csv`(월별 PPA 용량)을
조인해 cap_btmppa 를 붙인다. 파생(공간평균·달력·RevIN)은 Colab 노트북에서 생성 — 여기선 추출만.

v2 지점선택(exp_features 정본):
  기온=5지점 / 일사·구름=서산·영광 / 풍속=대관령·포항.
타깃 = real_demand_land(MW). day_type ∈ {holiday, weekday, weekend} → 노트북서 is_weekend/is_holiday.

사용법:
    python "5. land_demand_forecaster/training/export_landdemand_csv.py"
    # -> training/demand_raw_land.csv 생성
"""
from __future__ import annotations
import argparse, sqlite3, sys
from pathlib import Path
import numpy as np, pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB = REPO_ROOT / "1. data_fetcher_and_db" / "data" / "input_data_land.db"
DEFAULT_CAPA = REPO_ROOT / "1. data_fetcher_and_db" / "second_dataset" / "kr_elec_capa.csv"
DEFAULT_OUT = Path(__file__).resolve().parent / "demand_raw_land.csv"

STATIONS = ["daegwallyeong", "wonju", "seosan", "pohang", "yeonggwang"]
SOLAR_SEL = ["seosan", "yeonggwang"]
WIND_SEL = ["daegwallyeong", "pohang"]
TARGET = "real_demand_land"


def load_capa(capa_path: Path) -> pd.Series:
    """월별 PPA 용량(합계) → Period(M) Series (exp_features.load_capa 동일)."""
    df = pd.read_csv(capa_path, encoding="euc-kr", header=None, skiprows=2)
    df.columns = ["period", "region", "LNG", "solar", "wind", "PPA"]
    df = df[df.region.astype(str).str.strip() == "합계"].copy()
    df["ym"] = pd.to_datetime(df.period, format="%b-%y").dt.to_period("M")
    df["PPA"] = pd.to_numeric(df.PPA, errors="coerce")
    return df.dropna(subset=["PPA"]).set_index("ym")["PPA"].sort_index()


def export(db_path: Path, capa_path: Path, out_path: Path, start, end):
    if not db_path.exists():
        sys.exit(f"[ERR] DB not found: {db_path}")
    cols = ["timestamp", TARGET, "day_type"]
    cols += [f"temp_c_{s}" for s in STATIONS]
    cols += [f"humidity_{s}" for s in STATIONS]      # 불쾌지수용(상대습도) — 전 5지점
    cols += [f"wind_spd_{s}" for s in STATIONS]       # 체감기온용 — 전 5지점(구 WIND_SEL→전체)
    cols += [f"solar_rad_{s}" for s in SOLAR_SEL]
    cols += [f"total_cloud_{s}" for s in SOLAR_SEL]
    cols += [f"midlow_cloud_{s}" for s in SOLAR_SEL]
    con = sqlite3.connect(str(db_path))
    try:
        avail = pd.read_sql("PRAGMA table_info(historical)", con)["name"].tolist()
        missing = [c for c in cols if c not in avail]
        if missing:
            sys.exit(f"[ERR] historical 에 없는 컬럼: {missing}")
        where = []
        if start: where.append(f"timestamp >= '{start} 00:00:00'")
        if end:   where.append(f"timestamp <= '{end} 23:00:00'")
        where_sql = (" WHERE " + " AND ".join(where)) if where else ""
        q = f"SELECT {', '.join(chr(34)+c+chr(34) for c in cols)} FROM historical{where_sql} ORDER BY timestamp"
        df = pd.read_sql(q, con, parse_dates=["timestamp"])
    finally:
        con.close()
    df = df.sort_values("timestamp").reset_index(drop=True)

    # cap_btmppa 조인 (월별 PPA, 끝 이후 ffill/bfill — exp_features.cap_for 동일)
    ppa = load_capa(capa_path)
    ym = df["timestamp"].dt.to_period("M")
    full = pd.period_range(min(ym.min(), ppa.index.min()), max(ym.max(), ppa.index.max()), freq="M")
    df["cap_btmppa"] = ym.map(ppa.reindex(full).ffill().bfill()).astype(float).values

    print(f"[OK] rows={len(df)}  range {df['timestamp'].min()} -> {df['timestamp'].max()}")
    print(f"     {TARGET} nonnull={df[TARGET].notna().mean()*100:.1f}%  range {df[TARGET].min():.0f}~{df[TARGET].max():.0f}")
    print(f"     cap_btmppa {df['cap_btmppa'].min():.0f}~{df['cap_btmppa'].max():.0f} MW")
    print(f"     day_type: {df['day_type'].value_counts().to_dict()}")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out_path, index=False, encoding="utf-8-sig")
    print(f"[OK] wrote {out_path}  ({out_path.stat().st_size/1e6:.2f} MB)")


def main():
    ap = argparse.ArgumentParser(description="전국 수요 PatchTST 학습용 CSV 추출(5-B)")
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--capa", type=Path, default=DEFAULT_CAPA)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--start", type=str, default=None)
    ap.add_argument("--end", type=str, default=None)
    args = ap.parse_args()
    export(args.db, args.capa, args.out, args.start, args.end)


if __name__ == "__main__":
    main()

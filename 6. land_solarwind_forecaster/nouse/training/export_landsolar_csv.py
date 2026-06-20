# -*- coding: utf-8 -*-
"""DB -> Colab 학습용 CSV 추출 (전국 태양광 3지점 PatchTST 학습용, 6-B).

`1. data_fetcher_and_db/data/input_data_land.db` 의 `historical` 에서 태양광 3지점
(영광·서산·포항, G-13 확정)의 "원천(raw)" 컬럼만 wide CSV 로 추출한다. 파생 피처
(Hour_sin, solar_damping 등)는 Colab 노트북에서 생성 — 이 스크립트는 순수 추출만.

설계(6-B): 풍력은 LGBM 확정(비교 안 함) → 태양광만 export. PatchTST 피처는 LGBM과
다르게(지점별 raw 시퀀스). target = gen_solar_utilization_kr(시장 태양광 이용률, 0~1).
BTM/PPA 도 같은 이용률 공유(6-A2 검증) → 이 이용률 하나가 true_renew까지 구동.

사용법:
    python "6. land_solarwind_forecaster/training/export_landsolar_csv.py"
    # -> training/solarsolar_raw_land.csv 생성
"""
from __future__ import annotations
import argparse, sqlite3, sys
from pathlib import Path
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB = REPO_ROOT / "1. data_fetcher_and_db" / "data" / "input_data_land.db"
DEFAULT_OUT = Path(__file__).resolve().parent / "solar_raw_land.csv"

SOLAR_ST = ["yeonggwang", "seosan", "pohang"]   # 전남·충남·경북 (G-13)
# 지점별 원천 (PatchTST 입력 후보 — rainfall→solar_damping, humidity는 노트북서 선택)
PER_ST = ["solar_rad", "total_cloud", "midlow_cloud", "rainfall", "humidity"]
TARGET = "gen_solar_utilization_kr"
REF = ["gen_solar_capacity_kr", "gen_solar_market_kr", "day_type"]


def export(db_path: Path, out_path: Path, start, end):
    if not db_path.exists():
        sys.exit(f"[ERR] DB not found: {db_path}")
    cols = ["timestamp"]
    for st in SOLAR_ST:
        cols += [f"{v}_{st}" for v in PER_ST]
    cols += [TARGET] + REF
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
    print(f"[OK] rows={len(df)}  range {df['timestamp'].min()} -> {df['timestamp'].max()}")
    print(f"     {TARGET} nonnull={df[TARGET].notna().mean()*100:.1f}%")
    for st in SOLAR_ST:
        print(f"     solar_rad_{st:12s} nonnull={df[f'solar_rad_{st}'].notna().mean()*100:5.1f}%  "
              f"rainfall nonnull={df[f'rainfall_{st}'].notna().mean()*100:5.1f}%")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out_path, index=False, encoding="utf-8-sig")
    print(f"[OK] wrote {out_path}  ({out_path.stat().st_size/1e6:.2f} MB)")


def main():
    ap = argparse.ArgumentParser(description="전국 태양광 3지점 학습용 CSV 추출(6-B)")
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--start", type=str, default=None)
    ap.add_argument("--end", type=str, default=None)
    args = ap.parse_args()
    export(args.db, args.out, args.start, args.end)


if __name__ == "__main__":
    main()

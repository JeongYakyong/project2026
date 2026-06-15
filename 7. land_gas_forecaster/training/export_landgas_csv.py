# -*- coding: utf-8 -*-
"""DB -> Colab 학습용 CSV 추출 (전국 가스 직접예측 PatchTST 학습용, 7-D 실험).

실험(7-D): 체인(수요→신재생→가스)을 건너뛰고 **수요 → 가스 직접** PatchTST.
신재생을 명시적으로 계산하지 않고, 원시 태양광 기상 + 포항 풍속을 주어 모델이
"수요 − f(기상) → 가스(순부하 급전)"을 끝단에서 학습하게 한다(덕커브 내재화).

`1. data_fetcher_and_db/data/input_data_land.db` 의 `historical` 에서 원천 컬럼만
wide CSV 로 추출(파생 피처 Hour_sin·solar_damping 등은 Colab 노트북에서 생성).

피처 확정(2026-06-15, 사용자):
  타깃   = gen_gas_kr (MW, 노트북서 train MinMax 고정 스케일러로 정규화)
  드라이버= real_demand_land (학습=실측 / 서빙=est_demand_land)
  태양광 = solar_rad·total_cloud·midlow_cloud·solar_damping(rainfall 파생) @ 영광·서산·포항
  풍속   = wind_spd_pohang (historical 단일 채널 = 서빙 forecast_horizon wind_spd_10m_pohang)
  달력   = Hour_sin/cos, Year_sin/cos / 자기회귀 = 가스 MW(past_y)

주의: gen_gas_kr 은 2022~ 유효(이전 NULL). 노트북에서 가스 결측 구간은 학습창 밖.

사용법:
    python "7. land_gas_forecaster/training/export_landgas_csv.py"
    # -> training/gas_raw_land.csv 생성
"""
from __future__ import annotations
import argparse, sqlite3, sys
from pathlib import Path
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB = REPO_ROOT / "1. data_fetcher_and_db" / "data" / "input_data_land.db"
DEFAULT_OUT = Path(__file__).resolve().parent / "gas_raw_land.csv"

SOLAR_ST = ["yeonggwang", "seosan", "pohang"]      # 전남·충남·경북 (G-13, 6단계와 동일)
PER_ST = ["solar_rad", "total_cloud", "midlow_cloud", "rainfall"]   # rainfall→solar_damping
WIND_COL = "wind_spd_pohang"                        # 단일 풍속(=서빙 wind_spd_10m_pohang)
DRIVER = "real_demand_land"
TARGET = "gen_gas_kr"


def export(db_path: Path, out_path: Path, start, end):
    if not db_path.exists():
        sys.exit(f"[ERR] DB not found: {db_path}")
    cols = ["timestamp"]
    for st in SOLAR_ST:
        cols += [f"{v}_{st}" for v in PER_ST]
    cols += [WIND_COL, DRIVER, TARGET]
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
    print(f"     {TARGET} nonnull={df[TARGET].notna().mean()*100:.1f}%  (>0: {(df[TARGET]>0).mean()*100:.1f}%)")
    print(f"     {DRIVER} nonnull={df[DRIVER].notna().mean()*100:.1f}%   {WIND_COL} nonnull={df[WIND_COL].notna().mean()*100:.1f}%")
    for st in SOLAR_ST:
        print(f"     solar_rad_{st:12s} nonnull={df[f'solar_rad_{st}'].notna().mean()*100:5.1f}%  "
              f"rainfall nonnull={df[f'rainfall_{st}'].notna().mean()*100:5.1f}%")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out_path, index=False, encoding="utf-8-sig")
    print(f"[OK] wrote {out_path}  ({out_path.stat().st_size/1e6:.2f} MB)")


def main():
    ap = argparse.ArgumentParser(description="전국 가스 직접예측 학습용 CSV 추출(7-D)")
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--start", type=str, default="2022-01-01", help="기본 2022(가스 유효 시작)")
    ap.add_argument("--end", type=str, default=None)
    args = ap.parse_args()
    export(args.db, args.out, args.start, args.end)


if __name__ == "__main__":
    main()

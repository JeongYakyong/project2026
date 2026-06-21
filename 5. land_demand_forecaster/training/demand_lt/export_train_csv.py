# -*- coding: utf-8 -*-
"""historical → land_demand_train.csv (Colab 업로드용 학습 입력).

model_lt.build_features 가 필요로 하는 원본 컬럼만 추출(self-contained CSV 하나로 Colab 학습).
"""
import os, sqlite3
import pandas as pd
import model_lt as M

HERE = os.path.dirname(os.path.abspath(__file__))
# 정본 DB = 1. data_fetcher_and_db/data (평면 넘버링, 단일 출처)
DB = os.path.normpath(os.path.join(HERE, '..', '..', '..', '1. data_fetcher_and_db', 'data', 'input_data_land.db'))
OUT = os.path.join(HERE, 'land_demand_train.csv')

cols = (['timestamp', 'real_demand_land']
        + [f'temp_c_{s}' for s in M.TEMP_SEL] + [f'humidity_{s}' for s in M.TEMP_SEL]
        + [f'solar_rad_{s}' for s in M.SOLAR_SEL])

with sqlite3.connect(DB) as con:
    df = pd.read_sql(f"SELECT {', '.join(cols)} FROM historical ORDER BY timestamp", con)
df.to_csv(OUT, index=False)
print(f'wrote {OUT}  rows={len(df)} cols={len(df.columns)}  {df.timestamp.min()} .. {df.timestamp.max()}')

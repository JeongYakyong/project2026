# -*- coding: utf-8 -*-
"""v4 낮 과대예측 구조 분석 — post-hoc 보정 설계용.
시각×계절×지평별 bias 를 보고, 보정을 어느 granularity 로 걸지 판단한다.
"""
import os, sqlite3
import numpy as np, pandas as pd

DB = os.path.normpath(os.path.join(os.getcwd(), '..', '..', '..', '1. data_fetcher_and_db', 'data', 'input_data_land.db'))
con = sqlite3.connect(DB)
p = pd.read_sql("SELECT base,timestamp,horizon_d,est_demand_land AS pred FROM est_horizon_land_new WHERE model='patchtst_lt'",
                con, parse_dates=['timestamp', 'base'])
act = pd.read_sql("SELECT timestamp, real_demand_land AS act FROM historical", con, parse_dates=['timestamp'])
d = p.merge(act, on='timestamp', how='inner')
d = d[(d.act > 0) & d.pred.notna()].copy()
d['hour'] = d.timestamp.dt.hour
SEASON = {12: '겨울', 1: '겨울', 2: '겨울', 3: '봄', 4: '봄', 5: '봄', 6: '여름', 7: '여름', 8: '여름'}
d['season'] = d.timestamp.dt.month.map(SEASON)
d['e'] = (d.pred - d.act) / d.act * 100      # bias%

print("=== 시각별 bias% (전 지평 평균) ===")
print("시각:", ' '.join(f'{h:>5}' for h in range(6, 21)))
print("bias:", ' '.join(f'{d[d.hour==h].e.mean():>5.1f}' for h in range(6, 21)))

print("\n=== 시각×계절 bias% ===")
for s in ['겨울', '봄', '여름']:
    sub = d[d.season == s]
    print(f"{s}:", ' '.join(f'{sub[sub.hour==h].e.mean():>5.1f}' for h in range(6, 21)))

print("\n=== 낮(9~15시) bias%: 지평×계절 ===")
print("지평 |  겨울  |  봄   | 여름")
for n in range(1, 16):
    row = d[(d.horizon_d == n) & (d.hour >= 9) & (d.hour <= 15)]
    cells = [f'{row[row.season==s].e.mean():>+5.1f}' if len(row[row.season==s]) else '  -  ' for s in ['겨울', '봄', '여름']]
    print(f"D{n:<2}  | " + ' | '.join(cells))

print("\n낮 전체 bias%:", f'{d[(d.hour>=9)&(d.hour<=15)].e.mean():+.2f}', '| 밤:', f'{d[(d.hour<9)|(d.hour>15)].e.mean():+.2f}')

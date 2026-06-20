# -*- coding: utf-8 -*-
"""train/serve 공변량 이동 측정: forecast_horizon 예보기상 vs historical 관측기상, 지평별 오차.
모델은 관측으로 학습 → 서빙은 예보. 지평이 길수록 오차가 커지는지(=장지평 처방 필요) 확인.
"""
import os, sqlite3
import numpy as np, pandas as pd
import model_lt as M

DB = os.path.normpath(os.path.join(os.getcwd(), '..', '..', '..', '1. data_fetcher_and_db', 'data', 'input_data_land.db'))
con = sqlite3.connect(DB)

# 관측(historical) 피처
obs = M.build_features(M._load_raw(DB))[['temp_c', 'humidity', 'solar_rad']]
obs.columns = ['o_temp', 'o_hum', 'o_sol']

# 예보(forecast_horizon) → 같은 집계
cols = ([f'temp_{s}' for s in M.TEMP_SEL] + [f'reh_{s}' for s in M.TEMP_SEL] + [f'radiation_{s}' for s in M.SOLAR_SEL])
sel = ', '.join(f'"{c}"' for c in ['base', 'timestamp'] + cols)
fc = pd.read_sql(f'SELECT {sel} FROM forecast_horizon', con, parse_dates=['base', 'timestamp'])
fc['f_temp'] = fc[[f'temp_{s}' for s in M.TEMP_SEL]].mean(1)
fc['f_hum'] = fc[[f'reh_{s}' for s in M.TEMP_SEL]].mean(1)
fc['f_sol'] = fc[[f'radiation_{s}' for s in M.SOLAR_SEL]].mean(1)
fc = fc[['base', 'timestamp', 'f_temp', 'f_hum', 'f_sol']].dropna(subset=['f_temp'])

# 지평 = (타깃일 - base일) 일수
fc['horizon_d'] = (fc['timestamp'].dt.normalize() - fc['base'].dt.normalize()).dt.days
fc = fc[(fc.horizon_d >= 1) & (fc.horizon_d <= 15)]

m = fc.merge(obs, left_on='timestamp', right_index=True, how='inner')
hour = m['timestamp'].dt.hour
isday = (hour >= 9) & (hour <= 20)

print(f"매칭 {len(m)}행  base {m.base.nunique()}개")
print("\n지평 | temp bias/MAE(℃) | 습도 bias/MAE(%) | 일사 bias/MAE(MJ) | 낮일사 MAE")
print("-" * 78)
for n in [1, 2, 3, 5, 8, 11, 15]:
    s = m[m.horizon_d == n]
    if len(s) == 0:
        continue
    tb, tm = (s.f_temp - s.o_temp).mean(), (s.f_temp - s.o_temp).abs().mean()
    hb, hm = (s.f_hum - s.o_hum).mean(), (s.f_hum - s.o_hum).abs().mean()
    sb, sm = (s.f_sol - s.o_sol).mean(), (s.f_sol - s.o_sol).abs().mean()
    sd = m[(m.horizon_d == n) & isday]
    sdm = (sd.f_sol - sd.o_sol).abs().mean()
    print(f"D+{n:<2} | {tb:+5.2f} / {tm:4.2f}    | {hb:+5.1f} / {hm:4.1f}    | {sb:+5.2f} / {sm:4.2f}    | {sdm:4.2f}")

# 관측 자체의 변동폭(오차를 맥락화)
print(f"\n참고: 관측 temp σ={obs.o_temp.std():.1f}℃  습도 σ={obs.o_hum.std():.1f}%  "
      f"일사 σ={obs.o_sol.std():.2f}MJ (낮 평균 {obs.o_sol[ (obs.index.hour>=9)&(obs.index.hour<=20) ].mean():.2f})")

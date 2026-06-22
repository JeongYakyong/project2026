# -*- coding: utf-8 -*-
"""6단계 장지평 LGBM 최종 가중치 생성기(_final).  2026-06-22.

정직한 예보 아카이브(forecast_horizon, base×지평×시각)를 학습 데이터로 삼아, 멀어질수록
예보가 틀리는 감쇠를 horizon_d 로 직접 학습 + 평년(기후값) 앵커로 장지평 수축.  태양광은
낮(평년 일사>1%)만 학습, 풍력은 전 시간.  ★서빙 serve_solarwind_land._build_lh_feats 를
그대로 import 해 피처를 만들어 train-serve 완전 일치.

산출(6. land_solarwind_forecaster/model/models/):
  - lgbm_land_solar_final.txt / lgbm_land_wind_final.txt
  - lh_final_meta.json (피처순서·평년앵커(월×시각)·낮판정·블렌딩 메모)

검증(성능 비교·전진분할)은 _train_lgbm_lh.py.  이 파일은 '전체 데이터로 최종 학습 후 저장'만.
"""
import os, sys, json, sqlite3, importlib.util
import numpy as np, pandas as pd, lightgbm as lgb

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, '..', '..'))
DB = os.path.join(ROOT, '1. data_fetcher_and_db', 'data', 'input_data_land.db')
MOD = os.path.normpath(os.path.join(HERE, '..', 'model', 'models'))


def _imp(name, path):
    s = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(s); sys.modules[name] = m; s.loader.exec_module(m)
    return m

serve6 = _imp('serve_solarwind_land', os.path.join(ROOT, '6. land_solarwind_forecaster', 'serve_solarwind_land.py'))
SOLAR_ST, WIND_ST = serve6.LH_SOLAR_ST, serve6.LH_WIND_ST
FS, FW = serve6.LH_SOLAR_FEATS, serve6.LH_WIND_FEATS

PARAMS = dict(objective='regression_l1', num_leaves=31, learning_rate=0.04,
              feature_fraction=0.8, bagging_fraction=0.8, bagging_freq=1,
              min_child_samples=100, max_depth=-1, verbose=-1)
NROUND = 500

# ── 데이터 로드 ──────────────────────────────────────────────────────
con = sqlite3.connect(DB)
wcols = []
for st in SOLAR_ST: wcols += [f'radiation_{st}', f'total_cloud_{st}', f'midlow_cloud_{st}', f'rainfall_{st}']
for st in WIND_ST:  wcols += [f'wind_spd_10m_{st}', f'wd_sin_10m_{st}', f'wd_cos_10m_{st}']
wcols = list(dict.fromkeys(wcols))
fh = pd.read_sql(f'SELECT timestamp, base, horizon_d, {", ".join(wcols)} FROM forecast_horizon '
                 'WHERE horizon_d BETWEEN 1 AND 15', con, parse_dates=['timestamp'])
h = pd.read_sql('SELECT timestamp, gen_solar_utilization_kr, gen_wind_utilization_kr FROM historical',
                con, parse_dates=['timestamp'])
con.close()
for c in wcols: fh[c] = pd.to_numeric(fh[c], errors='coerce')
for c in ('gen_solar_utilization_kr', 'gen_wind_utilization_kr'): h[c] = pd.to_numeric(h[c], errors='coerce')
H = h.set_index('timestamp')

# ── 평년 앵커(월×시각) — 생산용은 전체 다년 실측 ──
h['m'] = h.timestamp.dt.month; h['hr'] = h.timestamp.dt.hour
clim_s = h.groupby(['m', 'hr']).gen_solar_utilization_kr.mean()
clim_w = h.groupby(['m', 'hr']).gen_wind_utilization_kr.mean()
clim_solar = {(int(m), int(hr)): float(v) for (m, hr), v in clim_s.items() if np.isfinite(v)}
clim_wind  = {(int(m), int(hr)): float(v) for (m, hr), v in clim_w.items() if np.isfinite(v)}
ctx = {'clim_solar': clim_solar, 'clim_wind': clim_wind}

# forecast_horizon 컬럼 → 서빙 _day_weather 명칭으로 rename(공용 빌더 입력 규격)
rename = {}
for st in SOLAR_ST: rename[f'radiation_{st}'] = f'solar_rad_{st}'
for st in WIND_ST:
    rename[f'wind_spd_10m_{st}'] = f'wind_spd_{st}'
    rename[f'wd_sin_10m_{st}'] = f'wd_sin_{st}'; rename[f'wd_cos_10m_{st}'] = f'wd_cos_{st}'

ysol = H['gen_solar_utilization_kr'].to_dict(); ywin = H['gen_wind_utilization_kr'].to_dict()
parts = []
for (base, n), g in fh.groupby(['base', 'horizon_d'], sort=False):
    gw = g.set_index('timestamp').sort_index().rename(columns=rename)
    M = serve6._build_lh_feats(gw, int(n), ctx)        # ★서빙과 동일 함수
    M['y_solar'] = [ysol.get(t, np.nan) for t in M.index]
    M['y_wind']  = [ywin.get(t, np.nan) for t in M.index]
    parts.append(M)
big = pd.concat(parts)
big['is_day'] = big['clim_solar'] > serve6.LH_DAY_THR

# ── 학습(전체 데이터, 보류 없음) ──
solar_df = big[big.is_day & big.y_solar.notna()]
wind_df  = big[big.y_wind.notna()]
print(f'학습 표본  태양광(낮)={len(solar_df):,}행  풍력={len(wind_df):,}행')
ms = lgb.train(PARAMS, lgb.Dataset(solar_df[FS], solar_df['y_solar'], categorical_feature=['season_grp']),
               num_boost_round=NROUND)
mw = lgb.train(PARAMS, lgb.Dataset(wind_df[FW], wind_df['y_wind'], categorical_feature=['season_grp']),
               num_boost_round=NROUND)
ms.save_model(os.path.join(MOD, 'lgbm_land_solar_final.txt'))
mw.save_model(os.path.join(MOD, 'lgbm_land_wind_final.txt'))

meta = {
    'created': '2026-06-22', 'note': '장지평 재훈련 — 지평인지+평년앵커 LGBM. 태양광=PatchTST(D1-6)와 블렌딩, 풍력=전지평.',
    'solar_feats': FS, 'wind_feats': FW,
    'solar_st': SOLAR_ST, 'wind_st': WIND_ST,
    'k_damp': serve6.LH_KDAMP, 'day_thr': serve6.LH_DAY_THR,
    'blend': 'su = (1-w)*PatchTST + w*LGBM, w=clip((n-5)/4,0,1) → D5=0·D7=0.5(교차)·D9=1',
    'clim_source': 'historical 전체(월×시각 평균 이용률)',
    'clim_solar': {f'{m}-{hr}': v for (m, hr), v in clim_solar.items()},
    'clim_wind':  {f'{m}-{hr}': v for (m, hr), v in clim_wind.items()},
    'params': PARAMS, 'nround': NROUND,
    'n_solar_rows': int(len(solar_df)), 'n_wind_rows': int(len(wind_df)),
}
with open(os.path.join(MOD, 'lh_final_meta.json'), 'w', encoding='utf-8') as f:
    json.dump(meta, f, ensure_ascii=False, indent=1)
print('저장 완료:', os.path.join(MOD, 'lgbm_land_solar_final.txt'))
print('         ', os.path.join(MOD, 'lgbm_land_wind_final.txt'))
print('         ', os.path.join(MOD, 'lh_final_meta.json'))
print('태양광 피처:', FS)
print('풍력 피처:', FW)

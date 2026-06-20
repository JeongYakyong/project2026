# -*- coding: utf-8 -*-
"""수요 v2(D+15) 지평별 정직 예측을 DB `est_horizon_land` 에 적재 (forecast_horizon 양식).

forecast_horizon(실예보) 전 base × 지평 d=1..15 에 대해 수요를 예측(lag168/336/504 정직가드,
기후값 폴백 없음)하고, base·horizon_d·timestamp 키로 `est_horizon_land` 에 UPSERT.
미래 타깃(실측 아직 없음)도 보존 — 운영 아카이브 겸용.  실측 있는 구간으로 지평별 MAPE 요약 출력.

표(forecast_horizon 정렬): timestamp TEXT, base TEXT, horizon_d INT, est_demand_land REAL,
  PRIMARY KEY(base, timestamp).  이후 신재생·가스 컬럼을 같은 표에 ALTER 로 추가(Phase 3).
"""
from __future__ import annotations
import os, sys, json, sqlite3, importlib.util, warnings
import numpy as np, pandas as pd, lightgbm as lgb
warnings.filterwarnings('ignore')

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, '..', '..'))
DB = os.path.join(ROOT, '1. data_fetcher_and_db', 'data', 'input_data_land.db')


def _imp(name, path):
    s = importlib.util.spec_from_file_location(name, path); m = importlib.util.module_from_spec(s)
    s.loader.exec_module(m); return m


expf = _imp('expf', os.path.join(HERE, 'exp_features.py'))
bht = _imp('bht', os.path.join(ROOT, '7. land_gas_forecaster', 'training', 'build_horizon_backtest.py'))
MODEL = os.path.join(HERE, 'models', 'lgbm_land_demand_v2.txt')
META = os.path.join(HERE, 'models', 'model_meta_v2.json')
FEAT = expf.BASEFEAT + ['total_cloud', 'midlow_cloud', 'cap_btmppa']
HZ = tuple(range(1, 16))   # D+1..D+15 (연속)


def mape(a, p):
    a, p = np.asarray(a, float), np.asarray(p, float); m = (a > 0) & np.isfinite(a) & np.isfinite(p)
    return float(np.mean(np.abs(a[m]-p[m])/a[m])*100) if m.any() else np.nan


def nbias(a, p):
    a, p = np.asarray(a, float), np.asarray(p, float); m = (a > 0) & np.isfinite(a) & np.isfinite(p)
    return float(np.mean((p[m]-a[m])/a[m])*100) if m.any() else np.nan


def main(write=True):
    m = lgb.Booster(model_file=MODEL); best = m.num_trees()
    offset = float(json.load(open(META, encoding='utf-8'))['init_score'])
    d_act = bht.load_actuals(); ppa = expf.load_capa()
    r = expf.eval_forecast(m, best, FEAT, d_act, ppa, horizons=HZ, offset=offset, require_actual=False)

    print('=' * 62)
    print('수요 v2(D+15) 지평별 — est_horizon_land 적재 (정직, 미래 보존)')
    print('=' * 62)
    print(f'{"지평":>5} | {"예측행":>7} | {"실측대조":>8} | {"MAPE":>7} | {"bias":>7}')
    for n in HZ:
        g = r[r.horizon == n]; ev = g.dropna(subset=['actual']); ev = ev[ev.actual > 0]
        print(f'  D+{n:>2} | {len(g):7} | {len(ev):8} | {mape(ev.actual, ev.pred):6.2f}% | {nbias(ev.actual, ev.pred):+6.2f}%')

    if not write:
        print('\n(--no-write: 적재 생략)'); return
    data = [(pd.Timestamp(t).strftime('%Y-%m-%d %H:%M:%S'), str(b), int(h), float(p))
            for b, t, h, p in zip(r.base, r.timestamp, r.horizon, r.pred) if np.isfinite(p)]
    with sqlite3.connect(DB) as con:
        con.execute('CREATE TABLE IF NOT EXISTS est_horizon_land ('
                    'timestamp TEXT, base TEXT, horizon_d INT, est_demand_land REAL, '
                    'PRIMARY KEY(base, timestamp))')
        cols = [c[1] for c in con.execute('PRAGMA table_info(est_horizon_land)')]
        if 'est_demand_land' not in cols:
            con.execute('ALTER TABLE est_horizon_land ADD COLUMN est_demand_land REAL')
        con.executemany(
            'INSERT INTO est_horizon_land (timestamp, base, horizon_d, est_demand_land) VALUES (?,?,?,?) '
            'ON CONFLICT(base, timestamp) DO UPDATE SET horizon_d=excluded.horizon_d, '
            'est_demand_land=excluded.est_demand_land', data)
        con.commit()
        n_rows = con.execute('SELECT COUNT(*) FROM est_horizon_land').fetchone()[0]
        rng = con.execute('SELECT MIN(timestamp), MAX(timestamp), COUNT(DISTINCT base) FROM est_horizon_land').fetchone()
    print(f'\n적재 완료: est_horizon_land  {n_rows}행  (UPSERT {len(data)})')
    print(f'  범위 {rng[0]} .. {rng[1]}  base수 {rng[2]}')


if __name__ == '__main__':
    try: sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception: pass
    main(write='--no-write' not in sys.argv)

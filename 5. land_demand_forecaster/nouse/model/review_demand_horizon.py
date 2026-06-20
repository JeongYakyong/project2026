# -*- coding: utf-8 -*-
"""Stage 1 체크포인트 — 수요 v2(D+15 확장, lag168/336/504 정직가드) 지평별 정직 백테스트.

forecast_horizon(실예보) 전 base에 대해 지평 {1-7,12,14,15} 수요 MAPE/bias 산출.
기후값 폴백 없음(예보 없는 시각 드롭), lag는 h<=k 가용성 가드(누설 차단).
산출: 콘솔 표 + models/fig/review_demand_horizon.png
"""
from __future__ import annotations
import os, sys, json, importlib.util
import numpy as np, pandas as pd, lightgbm as lgb

HERE = os.path.dirname(os.path.abspath(__file__))
FIG = os.path.join(HERE, 'fig'); os.makedirs(FIG, exist_ok=True)


def _imp(name, path):
    s = importlib.util.spec_from_file_location(name, path); m = importlib.util.module_from_spec(s)
    s.loader.exec_module(m); return m


expf = _imp('expf', os.path.join(HERE, 'exp_features.py'))
ROOT = os.path.normpath(os.path.join(HERE, '..', '..'))
bht = _imp('bht', os.path.join(ROOT, '7. land_gas_forecaster', 'training', 'build_horizon_backtest.py'))

import warnings; warnings.filterwarnings('ignore')
MODEL = os.path.join(HERE, 'models', 'lgbm_land_demand_v2.txt')
META = os.path.join(HERE, 'models', 'model_meta_v2.json')
FEAT = expf.BASEFEAT + ['total_cloud', 'midlow_cloud', 'cap_btmppa']
HZ = (1, 2, 3, 4, 5, 6, 7, 12, 14, 15)


def mape(a, p):
    a, p = np.asarray(a, float), np.asarray(p, float); m = (a > 0) & np.isfinite(a) & np.isfinite(p)
    return float(np.mean(np.abs(a[m]-p[m])/a[m])*100) if m.any() else np.nan


def nbias(a, p):
    a, p = np.asarray(a, float), np.asarray(p, float); m = (a > 0) & np.isfinite(a) & np.isfinite(p)
    return float(np.mean((p[m]-a[m])/a[m])*100) if m.any() else np.nan


def main():
    m = lgb.Booster(model_file=MODEL); best = m.num_trees()
    offset = float(json.load(open(META, encoding='utf-8'))['init_score'])
    d_act = bht.load_actuals(); ppa = expf.load_capa()
    r = expf.eval_forecast(m, best, FEAT, d_act, ppa, horizons=HZ, offset=offset)
    print('=' * 60)
    print('수요 v2(D+15) 정직 지평별 — forecast_horizon 백테스트')
    print('=' * 60)
    print(f'{"지평":>5} | {"MAPE":>7} | {"bias":>7} | {"n":>6}')
    rows = []
    for n in HZ:
        g = r[r.horizon == n]
        mp, bi = mape(g.actual, g.pred), nbias(g.actual, g.pred)
        rows.append((n, mp, bi, len(g)))
        print(f'  D+{n:>2} | {mp:6.2f}% | {bi:+6.2f}% | {len(g):6}')

    import matplotlib
    matplotlib.use('Agg'); import matplotlib.pyplot as plt
    try: plt.rcParams['font.family'] = 'Malgun Gothic'
    except Exception: pass
    plt.rcParams['axes.unicode_minus'] = False
    fig, ax = plt.subplots(figsize=(6.4, 3.6))
    xs = [x[0] for x in rows]; ys = [x[1] for x in rows]
    ax.plot(xs, ys, 'o-', color='#2563eb')
    for x, y in zip(xs, ys):
        ax.text(x, y + 0.1, f'{y:.1f}', ha='center', fontsize=8)
    ax.set_xlabel('horizon (D+n)'); ax.set_ylabel('수요 MAPE (%)')
    ax.set_title('수요 v2 정직 지평곡선 (lag168/336/504 가드, 기후값 폴백 없음)')
    ax.grid(alpha=0.3); fig.tight_layout()
    p = os.path.join(FIG, 'review_demand_horizon.png'); fig.savefig(p, dpi=130)
    print('\nsaved', p)


if __name__ == '__main__':
    try: sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception: pass
    main()

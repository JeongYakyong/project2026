# -*- coding: utf-8 -*-
"""가스 비대칭 손실 스윕 — 낮(09-15h) 과대 페널티 (MIXED 피처 위).

확정 피처(2026-06-14): real_demand_land(MW), renew_util, gas_lag168/lag24/rec24/rec168,
h, hour, dow, doy. 타깃=가스 MW.  여기에 커스텀 L2 비대칭(낮&과대 grad/hess ×alpha) 추가.
수요 v2 와 동일 부호(land=낮 과대를 아래로).  init_score=평균, predict 시 가산.
"""
from __future__ import annotations
import os, sys, importlib.util
import numpy as np, pandas as pd, lightgbm as lgb

HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location('egr', os.path.join(HERE, 'exp_gas_ratio.py'))
egr = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(egr)

MIXED_FEAT = ['real_demand_land', 'renew_util', 'gas_lag168', 'gas_lag24', 'gas_rec24', 'gas_rec168',
              'h', 'hour', 'dow', 'doy']
ALPHAS = [1.0, 2.0, 4.0, 8.0]
PARAMS = dict(metric='l1', learning_rate=0.03, num_leaves=127, min_data_in_leaf=100,
              feature_fraction=0.85, bagging_fraction=0.8, bagging_freq=5, lambda_l2=0.2,
              verbosity=-1, random_state=42)


class Shifted:
    def __init__(s, m, off): s.m = m; s.off = off
    def predict(s, X, num_iteration=None): return s.m.predict(X, num_iteration=num_iteration) + s.off
    def feature_name(s): return s.m.feature_name()


def make_obj(is_day, alpha):
    def obj(y_pred, dset):
        resid = y_pred - dset.get_label()
        grad = resid.astype(np.float64); hess = np.ones_like(resid)
        od = is_day & (resid > 0); grad[od] *= alpha; hess[od] *= alpha
        return grad, hess
    return obj


def train_asym(samp, alpha):
    tr = samp[(samp.tyear >= 2022) & (samp.tyear <= 2024)]; va = samp[samp.tyear == 2025]
    is_day = ((tr.hour.values >= 9) & (tr.hour.values <= 15))
    init = float(tr.y.mean())
    dtr = lgb.Dataset(tr[MIXED_FEAT], tr.y, init_score=np.full(len(tr), init))
    dva = lgb.Dataset(va[MIXED_FEAT], va.y, reference=dtr, init_score=np.full(len(va), init))
    p = dict(PARAMS); p['objective'] = make_obj(is_day, alpha)
    m = lgb.train(p, dtr, num_boost_round=3000, valid_sets=[dva], valid_names=['val'],
                  callbacks=[lgb.early_stopping(120, verbose=False)])
    return Shifted(m, init), int(m.best_iteration)


def main():
    d = egr.load_cont(); samp = egr.build_samples(d)
    res = {}
    for a in ALPHAS:
        m, best = train_asym(samp, a)
        res[a] = egr.eval_chain(m, best, MIXED_FEAT, d, ratio=False)
        print(f'  alpha={a}: best_iter {best}')
    print('\n지평 | ' + ' | '.join(f'a={a:>4}' for a in ALPHAS))
    for n in egr.BLOCKS:
        lo, hi = egr.BLOCKS[n]
        cells = [f'{egr.mape(g.gen_gas_kr,g.pred):5.2f}/{egr.nbias(g.gen_gas_kr,g.pred):+4.1f}'
                 for g in (res[a][(res[a].h >= lo) & (res[a].h <= hi)] for a in ALPHAS)]
        print(f' D+{n:>2} | ' + ' | '.join(f'{c:>11}' for c in cells))
    print('\n낮(09-15) | ' + ' | '.join(f'a={a:>4}' for a in ALPHAS))
    for s in ['겨울', '봄', '여름']:
        cells = []
        for a in ALPHAS:
            g = res[a]; g = g[(g.season == s) & (pd.DatetimeIndex(g.timestamp).hour.isin(range(9, 16)))]
            cells.append(f'{egr.mape(g.gen_gas_kr,g.pred):5.2f}/{egr.nbias(g.gen_gas_kr,g.pred):+4.1f}')
        print(f'  {s}낮 | ' + ' | '.join(f'{c:>11}' for c in cells))


if __name__ == '__main__':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass
    main()

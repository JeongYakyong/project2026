# -*- coding: utf-8 -*-
"""v2 vs 실험모델 honest 비교 + feature importance + VIF.
동일 exp_features·동일 forecast_horizon 으로 같은 표본에서 평가(공정 비교).
실행: python _ab_comfort_eval.py [tag]   (tag 기본=v2hum; v2comfort 도 가능)
v2 honest 는 _ab_cache/v2_honest.parquet 캐시(피처추가는 v2 예측 불변).
"""
from __future__ import annotations
import os, sys, json, importlib.util
import numpy as np, pandas as pd, lightgbm as lgb
try: sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception: pass
HERE = os.path.dirname(os.path.abspath(__file__))
MODELDIR = os.path.join(HERE, '..', 'model'); MODELS = os.path.join(MODELDIR, 'models')
CACHE = os.path.join(HERE, '_ab_cache'); os.makedirs(CACHE, exist_ok=True)
TAG = sys.argv[1] if len(sys.argv) > 1 else 'v2hum'


def _imp(n, p):
    s = importlib.util.spec_from_file_location(n, p); m = importlib.util.module_from_spec(s); s.loader.exec_module(m); return m
expf = _imp('expf', os.path.join(MODELDIR, 'exp_features.py')); bht = expf.bht
mape, nbias = expf.mape, expf.nbias


def honest(tag):
    meta = json.load(open(os.path.join(MODELS, f'model_meta_{tag}.json'), encoding='utf-8'))
    m = lgb.Booster(model_file=os.path.join(MODELS, f'lgbm_land_demand_{tag}.txt'))
    ppa = expf.load_capa(); d_act = bht.load_actuals()
    r = expf.eval_forecast(m, int(meta['best_iteration']), meta['features'], d_act, ppa,
                           horizons=range(1, 16), offset=float(meta['init_score']))
    return r, m


def honest_v2_cached():
    cp = os.path.join(CACHE, 'v2_honest.parquet')
    mp = os.path.getmtime(os.path.join(MODELS, 'lgbm_land_demand_v2.txt'))
    if os.path.exists(cp) and os.path.getmtime(cp) >= mp:
        return pd.read_parquet(cp)
    r, _ = honest('v2'); r.to_parquet(cp, index=False); return r


def vif_table(feats, X):
    A = X[feats].dropna().values.astype(float); A = (A - A.mean(0)) / (A.std(0) + 1e-12)
    out = []
    for j, f in enumerate(feats):
        y = A[:, j]; Xo = np.column_stack([np.ones(len(A)), np.delete(A, j, axis=1)])
        beta, *_ = np.linalg.lstsq(Xo, y, rcond=None)
        r2 = 1 - ((y - Xo @ beta) ** 2).sum() / ((y - y.mean()) ** 2).sum()
        out.append((f, 1.0 / max(1e-9, 1 - r2)))
    return sorted(out, key=lambda x: -x[1])


def main():
    print(f'honest 평가: v2(캐시) vs {TAG} ...')
    rv = honest_v2_cached().rename(columns={'pred': 'pred_v2'})
    re, me = honest(TAG); re = re.rename(columns={'pred': 'pred_exp'})
    g = rv[['base', 'timestamp', 'horizon', 'actual', 'pred_v2', 'daypart', 'season']].merge(
        re[['base', 'timestamp', 'horizon', 'pred_exp']], on=['base', 'timestamp', 'horizon'], how='inner')
    g = g[g.actual > 0]
    print(f'동일표본 n={len(g)}\n')

    for part in ['낮', '밤']:
        d = g[g.daypart == part]
        print(f'======== {part} MAPE : v2 → {TAG} (Δ) ========')
        print('  지평     v2     exp      Δ')
        for n in range(1, 16):
            dn = d[d.horizon == n]; a, b = mape(dn.actual, dn.pred_v2), mape(dn.actual, dn.pred_exp)
            print(f'  D+{n:<3}{a:8.2f}{b:8.2f}  {b-a:+6.2f}')
        for lab, sub in [('D+1-15', d), ('D+3-15(서빙)', d[d.horizon >= 3])]:
            a, b = mape(sub.actual, sub.pred_v2), mape(sub.actual, sub.pred_exp)
            print(f'  {lab:<12}{a:7.2f}{b:8.2f}  {b-a:+6.2f}')
        print()

    print(f'======== 계절 낮 (D+3-15) v2 → {TAG} ========')
    d = g[(g.daypart == '낮') & (g.horizon >= 3)]
    for s in ['겨울', '봄', '여름', '가을']:
        ds = d[d.season == s]
        if len(ds) == 0: continue
        a, b = mape(ds.actual, ds.pred_v2), mape(ds.actual, ds.pred_exp)
        print(f'  {s}: {a:.2f} → {b:.2f} ({b-a:+.2f}) n={len(ds)}')

    imp = pd.DataFrame({'f': me.feature_name(), 'g': me.feature_importance('gain')})
    imp['pct'] = imp.g / imp.g.sum() * 100; imp = imp.sort_values('pct', ascending=False)
    print(f'\n======== {TAG} feature importance (gain%) ========')
    for _, r in imp.iterrows(): print(f'  {r.f:<14}{r.pct:6.2f}%')

    d = expf.load_hist(); ppa = expf.load_capa(); tr = expf.build_samples(d, ppa)
    tr = tr[tr.tyear <= 2024]
    num = [f for f in ['temp_c4', 'humidity', 'di', 'wct', 'solar_rad', 'total_cloud', 'midlow_cloud',
                       'cap_btmppa', 'rec24', 'rec168', 'h', 'hour_sin', 'hour_cos', 'month_sin', 'month_cos'] if f in tr.columns]
    print(f'\n======== VIF (학습표본, 10+ = 강한 다중공선성) ========')
    for f, v in vif_table(num, tr): print(f'  {f:<14}{v:8.2f}')

    g.to_parquet(os.path.join(HERE, f'_ab_{TAG}_merged.parquet'), index=False)
    print(f'\n저장: _ab_{TAG}_merged.parquet')


if __name__ == '__main__':
    main()

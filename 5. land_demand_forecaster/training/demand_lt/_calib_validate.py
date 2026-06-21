# -*- coding: utf-8 -*-
"""post-hoc bias 보정의 일반화 검증 — base 홀짝 교차검증.
보정 = 곱셈계수 c[key] = median(act/pred) (fit half). 다른 half 에 적용해 개선이 유지되는지.
key granularity 후보를 비교: hour / (season,hour) / (season,hour,horizon그룹).
과적합이면 fit 에서만 좋고 held-out 에선 안 좋음.
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
d['hgrp'] = np.where(d.horizon_d <= 5, 'A', np.where(d.horizon_d <= 10, 'B', 'C'))   # 3구간
# 5구간: 초단기 D1-3 / 단기 D4-6 / 중기 D7-9 / 중장기 D10-12 / 장기 D13-15
d['hgrp5'] = pd.cut(d.horizon_d, [0, 3, 6, 9, 12, 15], labels=['초단', '단', '중', '중장', '장'])
d['day'] = (d.hour >= 9) & (d.hour <= 15)
# base 홀짝 분할
ubase = sorted(d.base.unique())
half0 = set(ubase[0::2]); half1 = set(ubase[1::2])
d['fold'] = np.where(d.base.isin(half0), 0, 1)

KEYS = {'(계절,시각)': ['season', 'hour'],
        '(계절,시각,3구간)': ['season', 'hour', 'hgrp'],
        '(계절,시각,5구간)': ['season', 'hour', 'hgrp5'],
        '(계절,시각,지평15)': ['season', 'hour', 'horizon_d']}


def mape(g): return float(np.mean(np.abs(g.pred_c - g.act) / g.act) * 100) if len(g) else np.nan
def bias(g): return float(np.mean((g.pred_c - g.act) / g.act) * 100) if len(g) else np.nan


def run(keys, mode):
    """mode='heldout' = 다른 fold로 적합 후 적용 / 'insample' = 전체로 적합·적용(과적합 상한)."""
    out = d.copy(); out['pred_c'] = out.pred
    if mode == 'insample':
        c = out.assign(r=out.act / out.pred).groupby(keys)['r'].median()
        cf = pd.Index(list(zip(*[out[k] for k in keys]))).map(c).to_numpy(dtype=float)
        out['pred_c'] = out.pred * np.where(np.isfinite(cf), cf, 1.0)
        return out
    for test in (0, 1):
        fit = out[out.fold != test]; tst = out.fold == test
        c = fit.assign(r=fit.act / fit.pred).groupby(keys)['r'].median()
        cf = pd.Index(list(zip(*[out.loc[tst, k] for k in keys]))).map(c).to_numpy(dtype=float)
        out.loc[tst, 'pred_c'] = out.loc[tst, 'pred'] * np.where(np.isfinite(cf), cf, 1.0)
    return out


d['pred_c'] = d.pred
print(f"[보정 전]  낮 {mape(d[d.day]):.2f}(bias{bias(d[d.day]):+.2f}) | 밤 {mape(d[~d.day]):.2f} | 여름낮 {mape(d[d.day&(d.season=='여름')]):.2f} | 전체 {mape(d):.2f}")
print(f"\n{'granularity':<20} | 낮(held-out) | 낮(in-sample) | 밤 | 여름낮 | 전체(held) | 셀수")
for name, keys in KEYS.items():
    ho = run(keys, 'heldout'); ins = run(keys, 'insample')
    dho = ho[ho.day]; gap = mape(ins[ins.day]) - mape(dho)   # 과적합 신호(클수록 위험)
    ncell = d.groupby(keys, observed=True).ngroups
    print(f"{name:<20} | {mape(dho):.2f}({bias(dho):+.2f}) | {mape(ins[ins.day]):.2f} (gap{gap:+.2f}) | {mape(ho[~ho.day]):.2f} | {mape(dho[dho.season=='여름']):.2f} | {mape(ho):.2f} | {ncell}")

# -*- coding: utf-8 -*-
"""수요 5-A(pooled, Global+Horizon-Feature) vs 5-A2(direct per-horizon) 정량 비교.

사용자 직감(2026-06-14): 지평 데이터가 생긴 지금 5-A2(direct)가 압도적일 것.  운영은 현재 5-A.
실예보(forecast_horizon)로 같은 (base, 지평) 에서 두 모델을 돌려 계절×낮(09-15h) 축으로 비교한다.
7단계 빌더(build_horizon_backtest)의 기상/스크래치 기계를 재사용한다.
"""
from __future__ import annotations
import os, sys, importlib.util
import numpy as np, pandas as pd, lightgbm as lgb

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, '..', '..'))
BT = os.path.join(ROOT, '7. land_gas_forecaster', 'training', 'build_horizon_backtest.py')
POOLED = os.path.join(HERE, 'models', 'lgbm_land_demand_direct.txt')   # 5-A
TAB = os.path.join(HERE, 'tab'); os.makedirs(TAB, exist_ok=True)

# build_horizon_backtest 동적 임포트(헬퍼 재사용)
spec = importlib.util.spec_from_file_location('bht', BT)
bht = importlib.util.module_from_spec(spec); spec.loader.exec_module(bht)

ST, WX, FORE_PREFIX, DTCATS = bht.ST, bht.WX, bht.FORE_PREFIX, bht.DTCATS
BLOCKS, LAGW = bht.BLOCKS, bht.LAGW
FEAT_POOLED = ['h', 'lag168', 'lag24', 'rec24', 'rec168', 'temp_c', 'solar_rad', 'wind_spd',
               'hour_sin', 'hour_cos', 'dow_sin', 'dow_cos', 'month_sin', 'month_cos', 'day_type']
SEASON = {12: '겨울', 1: '겨울', 2: '겨울', 3: '봄', 4: '봄', 5: '봄',
          6: '여름', 7: '여름', 8: '여름', 9: '가을', 10: '가을', 11: '가을'}


def predict_pooled(con, d_act, model, O, n):
    """5-A pooled: h 피처 포함 단일 모델로 블록 n 예측."""
    h0, h1 = BLOCKS[n]; H = np.arange(h0, h1 + 1)
    targets = pd.DatetimeIndex([O + pd.Timedelta(hours=int(h)) for h in H])
    dem = d_act['real_demand_land']
    wx, valid = bht.fh_demand_weather(con, targets)
    df = pd.DataFrame(index=targets)
    df['h'] = H
    df['lag168'] = dem.reindex(targets - pd.Timedelta(hours=168)).values
    lag24 = dem.reindex(targets - pd.Timedelta(hours=24)).values
    df['lag24'] = np.where(H <= 24, lag24, np.nan)
    df['rec24'] = float(dem.loc[O - pd.Timedelta(hours=23):O].mean())
    df['rec168'] = float(dem.loc[O - pd.Timedelta(hours=167):O].mean())
    for w in WX:
        df[w] = wx[w].values
    hr = targets.hour; dw = targets.dayofweek; mo = targets.month
    df['hour_sin'] = np.sin(2*np.pi*hr/24); df['hour_cos'] = np.cos(2*np.pi*hr/24)
    df['dow_sin'] = np.sin(2*np.pi*dw/7); df['dow_cos'] = np.cos(2*np.pi*dw/7)
    df['month_sin'] = np.sin(2*np.pi*mo/12); df['month_cos'] = np.cos(2*np.pi*mo/12)
    dt = d_act['day_type'].reindex(targets).values
    df['day_type'] = pd.Categorical(dt, categories=DTCATS)
    ok = valid.values & ~np.isnan(df['lag168'].values)
    pred = np.full(len(targets), np.nan)
    if ok.any():
        pred[ok] = model.predict(df.loc[ok, FEAT_POOLED])
    return targets, pred, ok


def mape(a, p):
    a, p = np.asarray(a, float), np.asarray(p, float)
    m = (a > 0) & np.isfinite(a) & np.isfinite(p)
    return float(np.mean(np.abs(a[m]-p[m])/a[m])*100) if m.any() else np.nan


def nbias(a, p):
    a, p = np.asarray(a, float), np.asarray(p, float)
    m = (a > 0) & np.isfinite(a) & np.isfinite(p)
    return float(np.mean((p[m]-a[m])/a[m])*100) if m.any() else np.nan


def main(limit=None):
    d_act = bht.load_actuals()
    pooled = lgb.Booster(model_file=POOLED)
    direct = {n: lgb.Booster(model_file=os.path.join(bht.DEM_MODELS, f'lgbm_land_demand_D{n}.txt'))
              for n in [1, 2, 3, 7, 12]}
    import sqlite3
    with sqlite3.connect(bht.DB) as con:
        bases = [r[0] for r in con.execute('SELECT DISTINCT base FROM forecast_horizon ORDER BY base').fetchall()]
    if limit:
        bases = bases[::max(1, len(bases)//limit)][:limit]
    sc = bht.build_scratch(os.path.join(__import__('tempfile').gettempdir(), 'cmp_demand.db'))
    rows = []
    for base in bases:
        O = pd.Timestamp(base).normalize() + pd.Timedelta(hours=23)
        bht.set_scratch_forecast(sc, base)
        for n in [1, 2, 3, 7, 12]:
            tgp, pp, okp = predict_pooled(sc, d_act, pooled, O, n)
            tgd, pd_, dt_, okd = bht.predict_demand(sc, d_act, direct[n], O, n)
            act = d_act['real_demand_land'].reindex(tgp).values
            rows.append(pd.DataFrame({'timestamp': tgp, 'horizon': n, 'actual': act,
                                      'pooled': pp, 'direct': pd_}))
    sc.close()
    r = pd.concat(rows, ignore_index=True).dropna(subset=['actual'])
    r = r[r.actual > 0]
    r['season'] = pd.DatetimeIndex(r.timestamp).month.map(SEASON)
    r['daypart'] = np.where((pd.DatetimeIndex(r.timestamp).hour >= 9) &
                            (pd.DatetimeIndex(r.timestamp).hour <= 15), '낮(09-15)', '밤/주변')

    print('=== 지평별 (전체) ===')
    for n in [1, 2, 3, 7, 12]:
        g = r[r.horizon == n]
        print(f'  D+{n:>2}: pooled MAPE {mape(g.actual,g.pooled):.2f}% bias {nbias(g.actual,g.pooled):+.2f}% | '
              f'direct MAPE {mape(g.actual,g.direct):.2f}% bias {nbias(g.actual,g.direct):+.2f}% | '
              f'n={len(g)}')
    print('\n=== 계절×낮 (전 지평 합산) ===')
    out = []
    for (s, dp), g in r.groupby(['season', 'daypart']):
        out.append(dict(season=s, daypart=dp, n=len(g),
                        pooled_MAPE=round(mape(g.actual, g.pooled), 2),
                        direct_MAPE=round(mape(g.actual, g.direct), 2),
                        pooled_bias=round(nbias(g.actual, g.pooled), 2),
                        direct_bias=round(nbias(g.actual, g.direct), 2)))
    t = pd.DataFrame(out)
    print(t.to_string(index=False))
    t.to_csv(os.path.join(TAB, 'cmp_pooled_vs_direct.csv'), index=False, encoding='utf-8-sig')


if __name__ == '__main__':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass
    main(limit=int(sys.argv[sys.argv.index('--limit')+1]) if '--limit' in sys.argv else None)

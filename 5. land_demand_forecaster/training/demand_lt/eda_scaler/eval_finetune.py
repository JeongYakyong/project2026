# -*- coding: utf-8 -*-
"""파인튜닝 결과 채점 — 봉인 test = forecast_horizon(예보 기상, 2025-12-15~2026-06-18).

비교 3종(모두 같은 base×timestamp×지평):
  orig_raw   : 기존 weights, 보정 없음
  orig_calib : 기존 weights × calib_lt.json (현 production)
  ft_raw     : weights_ft(파인튜닝), ★보정 없음   ← 사용자 관심: 보정없이 bias 잡히나?
지표: MAPE, bias(%) = mean((p-a)/a). 핵심 = 낮 solar_rad 사분위별 bias(맑음 과대/흐림 과소가 평평해졌나).
서빙과 동일 경로(model_lt.predict_horizon, 예보 기상). train(≤2025-11-30)과 무겹침이라 과적합도 같이 드러남.
"""
from __future__ import annotations
import os, sys, json, sqlite3
try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass
import numpy as np, pandas as pd
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import model_lt as M  # noqa

HERE = os.path.dirname(os.path.abspath(__file__))
DEMAND = os.path.dirname(HERE)
DB = r'C:\Users\bjkim\Desktop\project2026\1. data_fetcher_and_db\data\input_data_land.db'
W_ORIG = os.path.join(DEMAND, 'weights')
W_FT = os.path.join(DEMAND, 'weights_ft')


def mape(a, p):
    a, p = np.asarray(a, float), np.asarray(p, float); k = (a > 0) & np.isfinite(a) & np.isfinite(p)
    return float(np.mean(np.abs(a[k] - p[k]) / a[k]) * 100) if k.any() else np.nan


def bias(a, p):
    a, p = np.asarray(a, float), np.asarray(p, float); k = (a > 0) & np.isfinite(a) & np.isfinite(p)
    return float(np.mean((p[k] - a[k]) / a[k]) * 100) if k.any() else np.nan


def serve_all(lt_dir, tag):
    A = M.load_serve(DB, lt_dir)
    with sqlite3.connect(DB) as con:
        bases = [b for (b,) in con.execute('SELECT DISTINCT base FROM forecast_horizon ORDER BY base')]
        rows = []
        for i, base in enumerate(bases):
            for n in sorted(A['models']):
                res = M.predict_horizon(A, con, base, n, calibrated=False)   # ★raw
                if res is None:
                    continue
                tg, pred = res
                for ts, v in zip(tg, pred):
                    if np.isfinite(v):
                        rows.append((ts, base, n, float(v)))
            if (i + 1) % 40 == 0:
                print(f'   [{tag}] {i+1}/{len(bases)} base')
    return pd.DataFrame(rows, columns=['timestamp', 'base', 'horizon_d', f'pred_{tag}'])


def main():
    print('서빙(예보 기상) 2패스 — 시간 좀 걸림')
    ft = serve_all(W_FT, 'ft')
    orig = serve_all(W_ORIG, 'orig')
    calib = json.load(open(os.path.join(W_ORIG, 'calib_lt.json'), encoding='utf-8'))

    with sqlite3.connect(DB) as con:
        hist = pd.read_sql('SELECT timestamp, real_demand_land AS actual, solar_rad_seosan, solar_rad_yeonggwang '
                           'FROM historical', con, parse_dates=['timestamp'])
    hist['solar_rad'] = hist[['solar_rad_seosan', 'solar_rad_yeonggwang']].mean(1)

    df = ft.merge(orig, on=['timestamp', 'base', 'horizon_d'], how='inner')
    df = df.merge(hist[['timestamp', 'actual', 'solar_rad']], on='timestamp', how='inner')
    df = df[(df.actual > 0)].copy()
    df['hour'] = df.timestamp.dt.hour; df['month'] = df.timestamp.dt.month
    df['season'] = df.month.map(M.SEASON)
    df['pred_orig_calib'] = df['pred_orig'] * [calib.get(M.calib_key(m, h, n), 1.0)
                                               for m, h, n in zip(df.month, df.hour, df.horizon_d)]
    print(f'\n채점 rows: {len(df)} (base {df.base.nunique()} × 지평 {sorted(df.horizon_d.unique())})')

    MODELS = [('orig_raw', 'pred_orig'), ('orig_calib', 'pred_orig_calib'), ('ft_raw', 'pred_ft')]
    print('\n=== 전체 ===')
    for name, col in MODELS:
        print(f'  {name:11s} MAPE {mape(df.actual, df[col]):5.2f}  bias {bias(df.actual, df[col]):+5.2f}')

    print('\n=== 낮(09~15시) solar_rad 사분위별 bias(%)  [핵심: 평평해졌나] ===')
    day = df[(df.hour >= 9) & (df.hour <= 15)].copy()
    day['sq'] = pd.qcut(day.solar_rad, 4, labels=['Q1흐림', 'Q2', 'Q3', 'Q4맑음'])
    tab = {}
    for name, col in MODELS:
        tab[name] = day.groupby('sq', observed=True).apply(lambda g: bias(g.actual, g[col]))
    print(pd.DataFrame(tab).round(2).to_string())
    print('  (range = Q4-Q1, 0에 가까울수록 solar 조건부 bias 제거)')
    for name, _ in MODELS:
        s = tab[name]; print(f'    {name:11s} range {s["Q4맑음"]-s["Q1흐림"]:+.2f}')

    print('\n=== 낮 계절별 bias(%) ===')
    for name, col in MODELS:
        pv = day.groupby('season').apply(lambda g: bias(g.actual, g[col]))
        print(f'  {name:11s}', {k: round(pv[k], 1) for k in pv.index})

    print('\n=== 지평별 MAPE (과적합/열화 점검) ===')
    print('지평 | orig_raw orig_calib  ft_raw')
    for n in sorted(df.horizon_d.unique()):
        g = df[df.horizon_d == n]
        print(f'  D{n:<3d}| {mape(g.actual,g.pred_orig):7.2f} {mape(g.actual,g.pred_orig_calib):9.2f} {mape(g.actual,g.pred_ft):7.2f}')

    df.to_csv(os.path.join(HERE, 'eval_finetune_rows.csv'), index=False, encoding='utf-8-sig')
    print('\n저장: eval_finetune_rows.csv')


if __name__ == '__main__':
    main()

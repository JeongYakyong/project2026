# -*- coding: utf-8 -*-
"""est_horizon_land_new 실예보 백테스트 정확도 비교 — 지평별 × (전체/낮/밤/계절).

대상 모델:
  patchtst_lt        : 신규 anchor-residual (est_horizon_land_new)
  patchtst_final336  : pure-PatchTST 기준선 (est_horizon_land_new)
  hybrid_old         : 기존 production 하이브리드 (est_horizon_land.est_demand_land)

지표: MAPE = mean(|a-p|/a)*100, bias = mean((p-a)/a)*100  (a=real_demand_land>0).
낮=09~15시, 밤=그 외. 계절: 12·1·2 겨울 / 3·4·5 봄 / 6·7·8 여름 / 9·10·11 가을.
실행: python eval_land_new.py   (또는 --metric bias)
"""
from __future__ import annotations
import os, argparse, sqlite3
import numpy as np, pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.normpath(os.path.join(HERE, '..', '..', '..', '1. data_fetcher_and_db', 'data', 'input_data_land.db'))
SEASON = {12: '겨울', 1: '겨울', 2: '겨울', 3: '봄', 4: '봄', 5: '봄',
          6: '여름', 7: '여름', 8: '여름', 9: '가을', 10: '가을', 11: '가을'}
MODELS = ['hybrid_old', 'patchtst_final336', 'patchtst_lt']


def mape(a, p):
    a, p = np.asarray(a, float), np.asarray(p, float); k = (a > 0) & np.isfinite(a) & np.isfinite(p)
    return float(np.mean(np.abs(a[k] - p[k]) / a[k]) * 100) if k.any() else np.nan


def bias(a, p):
    a, p = np.asarray(a, float), np.asarray(p, float); k = (a > 0) & np.isfinite(a) & np.isfinite(p)
    return float(np.mean((p[k] - a[k]) / a[k]) * 100) if k.any() else np.nan


def load():
    with sqlite3.connect(DB) as con:
        new = pd.read_sql("SELECT model, base, timestamp, horizon_d, est_demand_land AS pred "
                          "FROM est_horizon_land_new", con, parse_dates=['timestamp'])
        bases = tuple(new.base.unique())
        q = ("SELECT 'hybrid_old' AS model, base, timestamp, horizon_d, est_demand_land AS pred "
             "FROM est_horizon_land WHERE base IN (%s)" % ','.join('?' * len(bases)))
        old = pd.read_sql(q, con, params=bases, parse_dates=['timestamp'])
        act = pd.read_sql("SELECT timestamp, real_demand_land AS actual FROM historical", con, parse_dates=['timestamp'])
    df = pd.concat([new, old], ignore_index=True)
    df = df.merge(act, on='timestamp', how='inner')
    df = df[(df.actual > 0) & df.pred.notna() & df.actual.notna()].copy()
    df['daypart'] = np.where((df.timestamp.dt.hour >= 9) & (df.timestamp.dt.hour <= 15), '낮', '밤')
    df['season'] = df.timestamp.dt.month.map(SEASON)
    return df


def matrix(df, fn, title):
    """지평(행) × 모델(열) 표 출력."""
    models = [m for m in MODELS if m in df.model.unique()]
    print(f'\n■ {title}  [{fn.__name__}]  (행=지평 D, 열=모델)')
    head = '지평 | ' + ' | '.join(f'{m:>17}' for m in models)
    print(head); print('-' * len(head))
    for n in range(1, 16):
        cells = []
        for m in models:
            g = df[(df.model == m) & (df.horizon_d == n)]
            v = fn(g.actual, g.pred) if len(g) else np.nan
            cells.append(f'{v:>17.2f}' if np.isfinite(v) else f'{"-":>17}')
        print(f' D{n:<2} | ' + ' | '.join(cells))
    # 전체 지평 평균(샘플 가중 아님, 지평 단순평균)
    cells = []
    for m in models:
        vs = [fn(df[(df.model == m) & (df.horizon_d == n)].actual, df[(df.model == m) & (df.horizon_d == n)].pred)
              for n in range(1, 16)]
        cells.append(f'{np.nanmean(vs):>17.2f}')
    print(' avg | ' + ' | '.join(cells))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--metric', choices=['mape', 'bias', 'both'], default='both')
    ap.add_argument('--csv', default=os.path.join(HERE, 'eval_land_new.csv'))
    args = ap.parse_args()
    df = load()
    n_act = df.timestamp.max()
    print(f'평가표본: {len(df):,}행 | base {df.base.nunique()}개 | 실측 timestamp ~ {n_act}')
    print(f'계절 분포: ' + ', '.join(f'{s} {len(g):,}' for s, g in df.groupby("season")))

    fns = {'mape': [mape], 'bias': [bias], 'both': [mape, bias]}[args.metric]
    for fn in fns:
        matrix(df, fn, '전체')
        matrix(df[df.daypart == '낮'], fn, '낮(09~15시)')
        matrix(df[df.daypart == '밤'], fn, '밤')
        for s in ['겨울', '봄', '여름', '가을']:
            sub = df[df.season == s]
            if len(sub):
                matrix(sub, fn, f'계절={s}')

    # CSV: 모델×지평×slice 요약
    rows = []
    for slname, sub in [('전체', df), ('낮', df[df.daypart == '낮']), ('밤', df[df.daypart == '밤'])] + \
            [(f'계절_{s}', df[df.season == s]) for s in ['겨울', '봄', '여름', '가을']]:
        for m in MODELS:
            for n in range(1, 16):
                g = sub[(sub.model == m) & (sub.horizon_d == n)]
                if len(g):
                    rows.append(dict(slice=slname, model=m, horizon_d=n, n=len(g),
                                     mape=round(mape(g.actual, g.pred), 3), bias=round(bias(g.actual, g.pred), 3)))
    pd.DataFrame(rows).to_csv(args.csv, index=False, encoding='utf-8-sig')
    print(f'\n상세 요약 CSV -> {args.csv}')


if __name__ == '__main__':
    import sys
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass
    main()

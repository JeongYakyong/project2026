# -*- coding: utf-8 -*-
"""Phase 1b — 계절 × 낮시간 분해 진단 (비대칭 학습 설계의 근거).

사용자 우선순위(2026-06-14): ① 계절성(특히 봄·가을 전이철) ② 태양광 낮 시간(09~15h)을
반드시 캐치(비대칭 학습 허용).  단 land 는 제주식 비대칭이 역효과(낮 맑은날 과대) — 그래서
**오차의 방향(부호)** 을 낮/밤·계절별로 먼저 잰다.

두 축에서 본다:
  A. 실예보 백테스트(horizon_backtest.parquet, 2025-12~2026-06) — 지평 전파 포함, 단 가을 없음.
  B. ORACLE 전기간(historical, 전 계절) — 가스 모델 자체의 계절×낮시간 한계(예보 무관 바닥).

산출: tab/seg_*.csv 콘솔 표.  계절 = 겨울(12,1,2)/봄(3,4,5)/여름(6,7,8)/가을(9,10,11).
낮시간 = 09~15h(태양광 피크), 그 외=밤.
"""
from __future__ import annotations
import os, sys, json
import numpy as np, pandas as pd, lightgbm as lgb

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, '..', '..'))
DB = os.path.join(ROOT, '1. data_fetcher_and_db', 'data', 'input_data_land.db')
GAS_MODEL = os.path.join(HERE, '..', 'model', 'lgbm_land_gas_util.txt')
CALIB_JSON = os.path.join(HERE, '..', 'model', 'gas_serving_calib.json')
CAP_CSV = os.path.join(ROOT, '1. data_fetcher_and_db', 'second_dataset', 'kr_elec_capa.csv')
RT = os.path.join(HERE, 'horizon_backtest.parquet')
TAB = os.path.join(HERE, 'tab'); os.makedirs(TAB, exist_ok=True)
GAS_FEATS = ['real_demand_land', 'renew_gen_total_kr', 'hour', 'dow', 'month', 'doy', 'day_type']
DTCATS = ['holiday', 'weekday', 'weekend']
SEASON = {12: '겨울', 1: '겨울', 2: '겨울', 3: '봄', 4: '봄', 5: '봄',
          6: '여름', 7: '여름', 8: '여름', 9: '가을', 10: '가을', 11: '가을'}


def season(m): return m.map(SEASON)
def daypart(h): return np.where((h >= 9) & (h <= 15), '낮(09-15)', '밤/주변')


def mape(a, p):
    a, p = np.asarray(a, float), np.asarray(p, float)
    m = (a > 0) & np.isfinite(a) & np.isfinite(p)
    return float(np.mean(np.abs(a[m]-p[m])/a[m])*100) if m.any() else np.nan


def nbias(a, p):
    a, p = np.asarray(a, float), np.asarray(p, float)
    m = np.isfinite(a) & np.isfinite(p)
    return float((np.mean(p[m])-np.mean(a[m]))/np.mean(np.abs(a[m]))*100) if m.any() else np.nan


def _lng():
    cap = pd.read_csv(CAP_CSV, encoding='euc-kr').rename(columns={'기간': 'period', '지역': 'region', 'LNG': 'LNG_cap'})
    cap = cap[cap['region'] == '합계'].copy()
    cap['ym'] = pd.to_datetime(cap['period'], format='%b-%y').dt.to_period('M')
    cap['LNG_cap'] = pd.to_numeric(cap['LNG_cap'], errors='coerce')
    return cap[['ym', 'LNG_cap']].dropna().sort_values('ym').set_index('ym')['LNG_cap']


def _cap_for(idx, lng):
    ym = idx.to_period('M')
    full = pd.period_range(min(ym.min(), lng.index.min()), max(ym.max(), lng.index.max()), freq='M')
    return ym.map(lng.reindex(full).ffill().bfill()).astype(float).values


def gas_pred(df, dcol, rcol, booster, lng, calib=1.0):
    idx = pd.DatetimeIndex(df['timestamp'] if 'timestamp' in df else df.index)
    g = pd.DataFrame(index=idx)
    g['real_demand_land'] = df[dcol].values; g['renew_gen_total_kr'] = df[rcol].values
    g['hour'] = idx.hour; g['dow'] = idx.dayofweek; g['month'] = idx.month; g['doy'] = idx.dayofyear
    g['day_type'] = pd.Categorical(
        df['day_type'].values if 'day_type' in df else np.where(idx.dayofweek >= 5, 'weekend', 'weekday'),
        categories=DTCATS)
    return booster.predict(g[GAS_FEATS]) * _cap_for(idx, lng) * calib


def seg_table(df, a, p, label):
    df = df.copy(); df['_a'] = np.asarray(a, float); df['_p'] = np.asarray(p, float)
    df['season'] = season(pd.DatetimeIndex(df.timestamp).month if 'timestamp' in df else df.index.month)
    df['daypart'] = daypart(pd.DatetimeIndex(df.timestamp).hour if 'timestamp' in df else df.index.hour)
    rows = []
    for (s, dp), g in df.groupby(['season', 'daypart']):
        rows.append(dict(season=s, daypart=dp, n=len(g),
                         MAPE=round(mape(g._a, g._p), 2), nbias=round(nbias(g._a, g._p), 2)))
    t = pd.DataFrame(rows)
    print(f'\n### {label}')
    print(t.to_string(index=False))
    t.to_csv(os.path.join(TAB, f'seg_{label}.csv'), index=False, encoding='utf-8-sig')
    return t


def main():
    booster = lgb.Booster(model_file=GAS_MODEL)
    lng = _lng()
    cj = json.load(open(CALIB_JSON, encoding='utf-8'))
    by_h = {int(k): float(v) for k, v in cj.get('bias_calib_by_horizon', {}).items()}

    # ── A. 실예보 백테스트: 가스(보정 후) 계절×낮 ──
    rt = pd.read_parquet(RT)
    rt = rt.dropna(subset=['gen_gas_kr']); rt = rt[rt.gen_gas_kr > 0]
    seg_table(rt, rt.gen_gas_kr, rt.est_gas_gen, 'A_가스_실예보_전지평')
    # 낮시간만 지평별
    print('\n### A2_가스_실예보_낮(09-15)_지평별')
    dd = rt[(pd.DatetimeIndex(rt.timestamp).hour >= 9) & (pd.DatetimeIndex(rt.timestamp).hour <= 15)]
    for n in [1, 3, 7, 12]:
        g = dd[dd.horizon == n]
        print(f'  D+{n:>2} 낮: 가스 MAPE {mape(g.gen_gas_kr, g.est_gas_gen):.2f}%  '
              f'nbias {nbias(g.gen_gas_kr, g.est_gas_gen):+.2f}%  '
              f'net_load nbias {nbias(g.net_load_kr, g.est_net_load):+.2f}%  '
              f'신재생 nbias {nbias(g.renew_gen_total_kr, g.est_renew):+.2f}%')

    # ── B. ORACLE 전기간(전 계절): 가스 모델 자체 한계 ──
    with __import__('sqlite3').connect(DB) as con:
        h = pd.read_sql('SELECT timestamp, real_demand_land, renew_gen_total_kr, gen_gas_kr, day_type '
                        'FROM historical', con, parse_dates=['timestamp'])
    h = h[(h.timestamp.dt.year >= 2022)].dropna(subset=['gen_gas_kr', 'real_demand_land', 'renew_gen_total_kr'])
    h = h[h.gen_gas_kr > 0].set_index('timestamp')
    gp = gas_pred(h, 'real_demand_land', 'renew_gen_total_kr', booster, lng, calib=by_h.get(1, 1.0))
    # test(2026)와 train포함 전체 분리해서
    for yrlab, sub, pr in [('2022-25(학습포함)', h[h.index.year <= 2025], gp[h.index.year <= 2025]),
                           ('2026(test)', h[h.index.year == 2026], gp[h.index.year == 2026])]:
        seg_table(sub.reset_index(), sub.gen_gas_kr.values, pr, f'B_가스_ORACLE_{yrlab}')


if __name__ == '__main__':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass
    main()

# -*- coding: utf-8 -*-
"""Phase 1 — 정직한 지평별 진단: 실예보 백테스트 vs 기후값 프록시 vs ORACLE.

horizon_backtest.parquet(실예보, Phase 0) 와 chained_gas_dataset.parquet(기후값 프록시, 7-A2-A)
를 같은 가스 파이프라인(7-A2 + 현행 보정)으로 평가해, 단계별·지평별 정확도를 나란히 비교한다.
ORACLE = 실측 입력(real_demand_land·renew_gen_total_kr)을 같은 가스모델에 넣은 상한.

산출: tab/diag_*.csv, fig/diag_gas_by_horizon.png, REPORT_horizon_diagnosis.md (수치 자동 삽입은 안 함,
      표 CSV 와 그림만 생성하고 리포트는 사람이 작성/갱신).
"""
from __future__ import annotations
import os, sys, json
import numpy as np, pandas as pd, lightgbm as lgb
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, '..', '..'))
GAS_MODEL = os.path.join(HERE, '..', 'model', 'lgbm_land_gas_util.txt')
CALIB_JSON = os.path.join(HERE, '..', 'model', 'gas_serving_calib.json')
CAP_CSV = os.path.join(ROOT, '1. data_fetcher_and_db', 'second_dataset', 'kr_elec_capa.csv')
RT = os.path.join(HERE, 'horizon_backtest.parquet')
PROXY = os.path.join(HERE, 'chained_gas_dataset.parquet')
TAB = os.path.join(HERE, 'tab'); FIG = os.path.join(HERE, 'fig')
os.makedirs(TAB, exist_ok=True); os.makedirs(FIG, exist_ok=True)
GAS_FEATS = ['real_demand_land', 'renew_gen_total_kr', 'hour', 'dow', 'month', 'doy', 'day_type']
DTCATS = ['holiday', 'weekday', 'weekend']
HZ = [1, 2, 3, 7, 12]


def _lng_cap_series():
    cap = pd.read_csv(CAP_CSV, encoding='euc-kr').rename(
        columns={'기간': 'period', '지역': 'region', 'LNG': 'LNG_cap'})
    cap = cap[cap['region'] == '합계'].copy()
    cap['ym'] = pd.to_datetime(cap['period'], format='%b-%y').dt.to_period('M')
    cap['LNG_cap'] = pd.to_numeric(cap['LNG_cap'], errors='coerce')
    return cap[['ym', 'LNG_cap']].dropna().sort_values('ym').set_index('ym')['LNG_cap']


def _cap_for(idx, lng):
    ym = idx.to_period('M')
    full = pd.period_range(min(ym.min(), lng.index.min()), max(ym.max(), lng.index.max()), freq='M')
    s = lng.reindex(full).ffill().bfill()
    return ym.map(s).astype(float).values


def gas_pred(df, demand_col, renew_col, booster, calib, lng):
    """df 의 (demand_col, renew_col, 달력, day_type) → 가스 발전량(보정 포함)."""
    idx = pd.DatetimeIndex(df['timestamp'])
    g = pd.DataFrame(index=idx)
    g['real_demand_land'] = df[demand_col].values
    g['renew_gen_total_kr'] = df[renew_col].values
    g['hour'] = df['hour'].values; g['dow'] = df['dow'].values
    g['month'] = df['month'].values; g['doy'] = df['doy'].values
    g['day_type'] = pd.Categorical(df['day_type'].values, categories=DTCATS)
    util = booster.predict(g[GAS_FEATS])
    return util * _cap_for(idx, lng) * calib


def mape(a, p):
    a = np.asarray(a, float); p = np.asarray(p, float)
    m = (a > 0) & np.isfinite(a) & np.isfinite(p)
    return float(np.mean(np.abs(a[m] - p[m]) / a[m]) * 100) if m.any() else float('nan')


def bias(a, p):
    a = np.asarray(a, float); p = np.asarray(p, float)
    m = (a > 0) & np.isfinite(a) & np.isfinite(p)
    return float(np.mean((p[m] - a[m]) / a[m]) * 100) if m.any() else float('nan')


def nmae(a, p):
    a = np.asarray(a, float); p = np.asarray(p, float)
    m = np.isfinite(a) & np.isfinite(p)
    return float(np.mean(np.abs(a[m] - p[m])) / np.mean(np.abs(a[m])) * 100) if m.any() else float('nan')


def nbias(a, p):
    """정규화 편향 = (mean(pred)-mean(actual))/mean(actual)×100.  심야 분모≈0(신재생)에서
    비율 편향이 폭발하는 걸 피하려고 평균 기반으로 잰다."""
    a = np.asarray(a, float); p = np.asarray(p, float)
    m = np.isfinite(a) & np.isfinite(p)
    return float((np.mean(p[m]) - np.mean(a[m])) / np.mean(a[m]) * 100) if m.any() else float('nan')


def main():
    booster = lgb.Booster(model_file=GAS_MODEL)
    cj = json.load(open(CALIB_JSON, encoding='utf-8'))
    calib = float(cj['bias_calib'])
    lng = _lng_cap_series()

    rt = pd.read_parquet(RT)
    px = pd.read_parquet(PROXY)
    px = px[px['split'] == 'test'].copy()           # 프록시는 test=2026 만 비교(실예보 구간과 정합)
    # 프록시·ORACLE 가스 예측(같은 모델·보정)
    px['gas_proxy'] = gas_pred(px, 'est_demand', 'est_renew', booster, calib, lng)
    rt['gas_oracle'] = gas_pred(rt, 'real_demand_land', 'renew_gen_total_kr', booster, calib, lng)

    recs = []
    for n in HZ:
        r = rt[rt.horizon == n]; p = px[px.horizon == n]
        rd = r.dropna(subset=['real_demand_land'])
        rec = dict(
            horizon=n,
            # 수요(5)
            demand_mape_real=mape(rd.real_demand_land, rd.est_demand),
            demand_bias_real=bias(rd.real_demand_land, rd.est_demand),
            # 신재생(6) nMAE + 정규화편향(심야 분모≈0이라 비율편향 대신 평균기반)
            renew_nmae_real=nmae(rd.renew_gen_total_kr, rd.est_renew),
            renew_nbias_real=nbias(rd.renew_gen_total_kr, rd.est_renew),
            # net_load nMAE
            netload_nmae_real=nmae(r.dropna(subset=['net_load_kr']).net_load_kr,
                                   r.dropna(subset=['net_load_kr']).est_net_load),
            # 가스(7)
            gas_mape_real=mape(r.gen_gas_kr, r.est_gas_gen),
            gas_bias_real=bias(r.gen_gas_kr, r.est_gas_gen),
            gas_mape_proxy=mape(p.gen_gas_kr, p.gas_proxy),
            gas_bias_proxy=bias(p.gen_gas_kr, p.gas_proxy),
            gas_mape_oracle=mape(r.gen_gas_kr, r.gas_oracle),
            n_real=int(r.gen_gas_kr.notna().sum()),
        )
        recs.append(rec)
    tab = pd.DataFrame(recs)
    tab.to_csv(os.path.join(TAB, 'diag_by_horizon.csv'), index=False, encoding='utf-8-sig')
    pd.set_option('display.width', 200, 'display.max_columns', 30)
    print(tab.round(2).to_string(index=False))

    # 그림: 가스 MAPE by horizon (proxy vs real vs oracle)
    fig, ax = plt.subplots(figsize=(6.2, 3.8))
    ax.plot(tab.horizon, tab.gas_mape_proxy, 'o--', color='#94a3b8', label='proxy (climatology)')
    ax.plot(tab.horizon, tab.gas_mape_real, 'o-', color='#059669', label='real forecast (honest)')
    ax.plot(tab.horizon, tab.gas_mape_oracle, 'o:', color='#0f172a', label='ORACLE (actual inputs)')
    ax.set_xlabel('horizon (D+n)'); ax.set_ylabel('gas gen MAPE (%)')
    ax.set_xticks(HZ); ax.set_title('Land gas MAPE by horizon')
    ax.grid(alpha=0.3); ax.legend(fontsize=8)
    fig.tight_layout(); fig.savefig(os.path.join(FIG, 'diag_gas_by_horizon.png'), dpi=130)
    print('saved fig/diag_gas_by_horizon.png  tab/diag_by_horizon.csv')


if __name__ == '__main__':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass
    main()

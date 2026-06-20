# -*- coding: utf-8 -*-
"""가스 모델 재정교화 실험 — 5-A식 Global+Horizon 자기회귀 다지평.

사용자 통찰(2026-06-14): 가스도 자기 과거(lag·최근레벨)가 있고 수요(5-A)처럼 그걸 참고해
타깃을 직접 다지평 예측해야 한다.  현재 7-A2 는 동시점 회귀라 가스 자기상관(lag24=0.73·
lag168=0.78, 수요급)을 통째로 버리고 있었다.  가스 가용성=수요와 동일(같은 KPX 피드, 같은
마지막 실측 시각) → 가스 lag 은 origin 시점에 알려진 값이라 누수 아님(§5 '타깃 lag 금지'의
보수적 기본을 override; 명제 순수성은 드라이버-only 7-A 로 보존).

구조 = Global Model with Horizon Feature (h=1..288 direct, D+1~D+12).  5-A 와 동일 템플릿.
누적 변형:
  G0 drivers   : 현행 7-A2 (demand, renew, 달력, day_type)  -- 기준선
  G1 +auto     : + h, gas_lag168(h>168=NaN), gas_lag24(h<=24), gas_rec24, gas_rec168
  G2 +netload  : G1 + net_load (historical 실측, 사용자 지시)
  G3 +btmppa   : G2 + cap_btmppa (넣은것/뺀것 비교)
학습 historical 실측(가스≥2022, train 타깃<=2024 / val 2025).  평가 = v2 체인 백테스트
(horizon_backtest_v2.parquet, 드라이버=v2 체인예측 / 가스lag=historical 실측 / 실측 gas 대조).
비대칭 손실은 이후 단계(사용자: 맨 마지막).
"""
from __future__ import annotations
import os, sys, sqlite3, importlib.util
import numpy as np, pandas as pd, lightgbm as lgb

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, '..', '..'))
DB = os.path.join(ROOT, '1. data_fetcher_and_db', 'data', 'input_data_land.db')
PARQUET = os.path.join(HERE, '..', 'training', 'horizon_backtest_v2.parquet')


def _imp(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m


expf = _imp('expf', os.path.join(ROOT, '5. land_demand_forecaster', 'model', 'exp_features.py'))

CAL = ['hour', 'dow', 'month', 'doy']
DTCATS = ['holiday', 'weekday', 'weekend']
G0 = ['real_demand_land', 'renew_gen_total_kr'] + CAL + ['day_type']
AUTO = ['h', 'gas_lag168', 'gas_lag24', 'gas_rec24', 'gas_rec168']
VARIANTS = {
    'G0 drivers(7A2)': G0,
    'G1 +auto/h': G0 + AUTO,
    'G2 +net_load': G0 + AUTO + ['net_load'],
    'G3 +cap_btmppa': G0 + AUTO + ['net_load', 'cap_btmppa'],
}
HMAX = 288
PARAMS = dict(objective='regression_l1', metric='l1', learning_rate=0.03, num_leaves=127,
              min_data_in_leaf=100, feature_fraction=0.85, bagging_fraction=0.8, bagging_freq=5,
              lambda_l2=0.2, verbosity=-1, random_state=42)
SEASON = {12: '겨울', 1: '겨울', 2: '겨울', 3: '봄', 4: '봄', 5: '봄', 6: '여름', 7: '여름', 8: '여름', 9: '가을', 10: '가을', 11: '가을'}
BLOCKS = {1: (1, 24), 2: (25, 48), 3: (49, 72), 7: (145, 168), 12: (265, 288)}


def mape(a, p):
    a, p = np.asarray(a, float), np.asarray(p, float); m = (a > 0) & np.isfinite(a) & np.isfinite(p)
    return float(np.mean(np.abs(a[m]-p[m])/a[m])*100) if m.any() else np.nan


def nbias(a, p):
    a, p = np.asarray(a, float), np.asarray(p, float); m = (a > 0) & np.isfinite(a) & np.isfinite(p)
    return float(np.mean((p[m]-a[m])/a[m])*100) if m.any() else np.nan


def load_cont():
    cols = ['timestamp', 'gen_gas_kr', 'real_demand_land', 'renew_gen_total_kr', 'net_load_kr', 'day_type']
    with sqlite3.connect(DB) as con:
        raw = pd.read_sql(f"SELECT {', '.join(cols)} FROM historical", con, parse_dates=['timestamp'])
    raw = raw.sort_values('timestamp')
    idx = pd.date_range(raw.timestamp.min(), raw.timestamp.max(), freq='h')
    d = raw.set_index('timestamp').reindex(idx); d.index.name = 'timestamp'
    for c in ['gen_gas_kr', 'real_demand_land', 'renew_gen_total_kr', 'net_load_kr']:
        d[c] = pd.to_numeric(d[c], errors='coerce').replace(0, np.nan).interpolate('time', limit=6)
    d['day_type'] = d['day_type'].ffill().bfill()
    d['cap_btmppa'] = expf.cap_for(d.index, expf.load_capa())
    return d


def build_samples(d):
    gas = d.gen_gas_kr.values; dem = d.real_demand_land.values; ren = d.renew_gen_total_kr.values
    nl = d.net_load_kr.values; cap = d.cap_btmppa.values; dt = d.day_type.values.astype(object)
    hour = d.index.hour.values; dow = d.index.dayofweek.values; month = d.index.month.values
    doy = d.index.dayofyear.values; year = d.index.year.values
    rec24 = pd.Series(gas).rolling(24, min_periods=20).mean().values
    rec168 = pd.Series(gas).rolling(168, min_periods=140).mean().values
    N = len(d); H = np.arange(1, HMAX + 1)
    origins = np.where((hour == 23) & (np.arange(N) >= 167) & (np.arange(N) <= N - 1 - HMAX))[0]
    tgt = (origins[:, None] + H[None, :]).ravel()
    hh = np.broadcast_to(H, (len(origins), HMAX)).ravel()
    lag168_idx = tgt - 168
    g = pd.DataFrame({
        'y': gas[tgt], 'h': hh.astype(np.int16),
        'gas_lag168': np.where(hh <= 168, gas[lag168_idx], np.nan),   # h>168 은 미래라 NaN(누수차단)
        'gas_lag24': np.where(hh <= 24, gas[tgt - 24], np.nan),
        'gas_rec24': np.repeat(rec24[origins], HMAX), 'gas_rec168': np.repeat(rec168[origins], HMAX),
        'real_demand_land': dem[tgt], 'renew_gen_total_kr': ren[tgt], 'net_load': nl[tgt],
        'cap_btmppa': cap[tgt], 'hour': hour[tgt], 'dow': dow[tgt], 'month': month[tgt],
        'doy': doy[tgt], 'day_type': dt[tgt], 'tyear': year[tgt]})
    g = g[(g.y.notna()) & (g.y > 0) & g.gas_rec168.notna() & g.real_demand_land.notna()].reset_index(drop=True)
    g['day_type'] = pd.Categorical(g['day_type'], categories=DTCATS)
    return g


def train(samp, feat):
    tr = samp[(samp.tyear >= 2022) & (samp.tyear <= 2024)]; va = samp[samp.tyear == 2025]
    dtr = lgb.Dataset(tr[feat], tr.y, categorical_feature=['day_type'] if 'day_type' in feat else 'auto')
    dva = lgb.Dataset(va[feat], va.y, reference=dtr,
                      categorical_feature=['day_type'] if 'day_type' in feat else 'auto')
    m = lgb.train(PARAMS, dtr, num_boost_round=3000, valid_sets=[dva], valid_names=['val'],
                  callbacks=[lgb.early_stopping(120, verbose=False)])
    return m, int(m.best_iteration)


def eval_chain(model, best, feat, d):
    """v2 체인 백테스트: 드라이버=parquet 예측, 가스lag=historical 실측, 실측 gas 대조."""
    px = pd.read_parquet(PARQUET)
    gas = d.gen_gas_kr
    rows = []
    for base, gb in px.groupby('base'):
        O = pd.Timestamp(base).normalize() + pd.Timedelta(hours=23)
        rec24 = float(gas.loc[O - pd.Timedelta(hours=23):O].mean())
        rec168 = float(gas.loc[O - pd.Timedelta(hours=167):O].mean())
        sub = gb.copy(); t = pd.DatetimeIndex(sub.timestamp)
        h = ((t - O) / pd.Timedelta(hours=1)).astype(int)
        sub['h'] = h.values
        sub['gas_lag168'] = np.where(h.values <= 168, gas.reindex(t - pd.Timedelta(hours=168)).values, np.nan)
        sub['gas_lag24'] = np.where(h.values <= 24, gas.reindex(t - pd.Timedelta(hours=24)).values, np.nan)
        sub['gas_rec24'] = rec24; sub['gas_rec168'] = rec168
        sub['real_demand_land'] = sub.est_demand; sub['renew_gen_total_kr'] = sub.est_renew
        sub['net_load'] = sub.est_net_load
        sub['hour'] = t.hour; sub['dow'] = t.dayofweek; sub['month'] = t.month; sub['doy'] = t.dayofyear
        sub['cap_btmppa'] = expf.cap_for(t, expf.load_capa())
        sub['day_type'] = pd.Categorical(sub.day_type, categories=DTCATS)
        rows.append(sub)
    r = pd.concat(rows, ignore_index=True)
    ok = r[feat].notna().all(axis=1) if False else np.ones(len(r), bool)
    r['pred'] = model.predict(r[feat], num_iteration=best)
    r = r.dropna(subset=['gen_gas_kr']); r = r[r.gen_gas_kr > 0]
    r['season'] = pd.DatetimeIndex(r.timestamp).month.map(SEASON)
    return r


def main():
    d = load_cont()
    samp = build_samples(d)
    print('학습 샘플:', len(samp), ' tyear:', dict(samp.tyear.value_counts().sort_index()))
    res = {}
    for name, feat in VARIANTS.items():
        m, best = train(samp, feat)
        r = eval_chain(m, best, feat, d)
        res[name] = r
        imp = pd.DataFrame({'f': m.feature_name(), 'g': m.feature_importance('gain')}).sort_values('g', ascending=False)
        top = ', '.join(f'{x.f}{x.g/imp.g.sum()*100:.0f}' for _, x in imp.head(4).iterrows())
        print(f'  {name}: best_iter {best}  중요도상위 {top}')

    names = list(VARIANTS)
    print('\n======== 가스 MAPE / bias — 지평별 (보정 전, raw) ========')
    for n in BLOCKS:
        lo, hi = BLOCKS[n]
        cells = []
        for k in names:
            g = res[k]; g = g[(g.h >= lo) & (g.h <= hi)]
            cells.append(f'{mape(g.gen_gas_kr,g.pred):5.2f}/{nbias(g.gen_gas_kr,g.pred):+5.1f}')
        print(f' D+{n:>2} | ' + ' | '.join(f'{c:>12}' for c in cells))
    print('\n======== 봄/여름/겨울 낮(09-15) 가스 MAPE / bias ========')
    for s in ['겨울', '봄', '여름']:
        cells = []
        for k in names:
            g = res[k]; g = g[(g.season == s) & (pd.DatetimeIndex(g.timestamp).hour >= 9) & (pd.DatetimeIndex(g.timestamp).hour <= 15)]
            cells.append(f'{mape(g.gen_gas_kr,g.pred):5.2f}/{nbias(g.gen_gas_kr,g.pred):+5.1f}')
        print(f' {s}낮 | ' + ' | '.join(f'{c:>12}' for c in cells))


if __name__ == '__main__':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass
    main()

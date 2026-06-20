# -*- coding: utf-8 -*-
"""가스 — MW 절대값 vs 비율(이용률) 종합 검토 + 공변량이동(covariate shift).

사용자 지시(2026-06-14):
  1) net_load 제외 2) cap_btmppa 제외 3) month/doy 중 doy만 4) day_type 제외
  5) real_demand·renew_gen 둘 다 성장(비정상) 6) → MW보다 비율 적용이 바람직
  7) gas·real_demand·renew_gen 전부 비율 관점 검토.

배경: 절대 MW 는 용량·수요 성장으로 연도 추세를 타 test 2026 이 train 범위 밖(외삽)→
covariate shift(=cap_btmppa 가 망한 원리).  비율(이용률=발전/용량)은 용량 성장을 제거해
정상(stationary)에 가깝다.  7-A2 가 이미 가스 타깃을 util(gen/LNG_cap)로 쓰는 것과 일관.

이 스크립트:
  (A) 비정상성 정량화: 각 MW 변수 vs 비율형의 연도상관·train(2022-24)/test(2026) 범위·외삽여부.
  (B) 가스 모델 MW set vs RATIO set 비교(체인 백테스트 정확도 + 공변량이동).
용량 = kr_elec_capa.csv (LNG·태양광·풍력, 월별).  타깃은 양쪽 다 gas_util(=gen/LNG_cap)→×LNG_cap 복원.
"""
from __future__ import annotations
import os, sys, sqlite3, importlib.util
import numpy as np, pandas as pd, lightgbm as lgb

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, '..', '..'))
DB = os.path.join(ROOT, '1. data_fetcher_and_db', 'data', 'input_data_land.db')
CAPA = os.path.join(ROOT, '1. data_fetcher_and_db', 'second_dataset', 'kr_elec_capa.csv')
PARQUET = os.path.join(HERE, '..', 'training', 'horizon_backtest_v2.parquet')

DTCATS = ['holiday', 'weekday', 'weekend']
CAL = ['h', 'hour', 'dow', 'doy']
MW_FEAT = ['real_demand_land', 'renew_gen_total_kr', 'gas_lag168', 'gas_lag24', 'gas_rec24', 'gas_rec168'] + CAL
RATIO_FEAT = ['real_demand_land', 'renew_util', 'gutil_lag168', 'gutil_lag24', 'gutil_rec24', 'gutil_rec168'] + CAL
HMAX = 360   # D+15(=360h)까지 — 수요·신재생 지평확장과 정합 (구 288=D+12)
PARAMS = dict(objective='regression_l1', metric='l1', learning_rate=0.03, num_leaves=127,
              min_data_in_leaf=100, feature_fraction=0.85, bagging_fraction=0.8, bagging_freq=5,
              lambda_l2=0.2, verbosity=-1, random_state=42)
BLOCKS = {1: (1, 24), 2: (25, 48), 3: (49, 72), 7: (145, 168), 12: (265, 288), 14: (313, 336), 15: (337, 360)}
SEASON = {12: '겨울', 1: '겨울', 2: '겨울', 3: '봄', 4: '봄', 5: '봄', 6: '여름', 7: '여름', 8: '여름', 9: '가을', 10: '가을', 11: '가을'}


def mape(a, p):
    a, p = np.asarray(a, float), np.asarray(p, float); m = (a > 0) & np.isfinite(a) & np.isfinite(p)
    return float(np.mean(np.abs(a[m]-p[m])/a[m])*100) if m.any() else np.nan


def nbias(a, p):
    a, p = np.asarray(a, float), np.asarray(p, float); m = (a > 0) & np.isfinite(a) & np.isfinite(p)
    return float(np.mean((p[m]-a[m])/a[m])*100) if m.any() else np.nan


def load_caps():
    df = pd.read_csv(CAPA, encoding='euc-kr', header=None, skiprows=2,
                     names=['period', 'region', 'LNG', 'solar', 'wind', 'PPA'])
    df = df[df.region.astype(str).str.strip() == '합계'].copy()
    df['ym'] = pd.to_datetime(df.period, format='%b-%y').dt.to_period('M')
    for c in ['LNG', 'solar', 'wind']:
        df[c] = pd.to_numeric(df[c], errors='coerce')
    return df.dropna(subset=['LNG']).set_index('ym')[['LNG', 'solar', 'wind']].sort_index()


def cap_on(idx, caps, col):
    ym = idx.to_period('M')
    full = pd.period_range(min(ym.min(), caps.index.min()), max(ym.max(), caps.index.max()), freq='M')
    return ym.map(caps[col].reindex(full).ffill().bfill()).astype(float).values


def load_cont():
    cols = ['timestamp', 'gen_gas_kr', 'real_demand_land', 'renew_gen_total_kr']
    with sqlite3.connect(DB) as con:
        raw = pd.read_sql(f"SELECT {', '.join(cols)} FROM historical", con, parse_dates=['timestamp'])
    raw = raw.sort_values('timestamp')
    idx = pd.date_range(raw.timestamp.min(), raw.timestamp.max(), freq='h')
    d = raw.set_index('timestamp').reindex(idx); d.index.name = 'timestamp'
    for c in cols[1:]:
        d[c] = pd.to_numeric(d[c], errors='coerce').replace(0, np.nan).interpolate('time', limit=6)
    caps = load_caps()
    d['LNG_cap'] = cap_on(d.index, caps, 'LNG')
    d['renew_cap'] = cap_on(d.index, caps, 'solar') + cap_on(d.index, caps, 'wind')
    d['gas_util'] = d.gen_gas_kr / d.LNG_cap
    d['renew_util'] = d.renew_gen_total_kr / d.renew_cap
    return d


def build_samples(d):
    gas = d.gen_gas_kr.values; gutil = d.gas_util.values
    dem = d.real_demand_land.values; ren = d.renew_gen_total_kr.values; renu = d.renew_util.values
    lng = d.LNG_cap.values
    hour = d.index.hour.values; dow = d.index.dayofweek.values; doy = d.index.dayofyear.values
    year = d.index.year.values
    grec24 = pd.Series(gutil).rolling(24, min_periods=20).mean().values
    grec168 = pd.Series(gutil).rolling(168, min_periods=140).mean().values
    rec24 = pd.Series(gas).rolling(24, min_periods=20).mean().values
    rec168 = pd.Series(gas).rolling(168, min_periods=140).mean().values
    N = len(d); H = np.arange(1, HMAX + 1)
    origins = np.where((hour == 23) & (np.arange(N) >= 167) & (np.arange(N) <= N - 1 - HMAX))[0]
    tgt = (origins[:, None] + H[None, :]).ravel(); hh = np.broadcast_to(H, (len(origins), HMAX)).ravel()
    li = tgt - 168
    g = pd.DataFrame({
        'y': gas[tgt], 'gas_util': gutil[tgt], 'LNG_cap': lng[tgt], 'h': hh.astype(np.int16),
        'real_demand_land': dem[tgt], 'renew_gen_total_kr': ren[tgt], 'renew_util': renu[tgt],
        'gas_lag168': np.where(hh <= 168, gas[li], np.nan), 'gas_lag24': np.where(hh <= 24, gas[tgt-24], np.nan),
        'gas_rec24': np.repeat(rec24[origins], HMAX), 'gas_rec168': np.repeat(rec168[origins], HMAX),
        'gutil_lag168': np.where(hh <= 168, gutil[li], np.nan), 'gutil_lag24': np.where(hh <= 24, gutil[tgt-24], np.nan),
        'gutil_rec24': np.repeat(grec24[origins], HMAX), 'gutil_rec168': np.repeat(grec168[origins], HMAX),
        'hour': hour[tgt], 'dow': dow[tgt], 'doy': doy[tgt], 'tyear': year[tgt]})
    g = g[(g.y > 0) & g.gas_util.notna() & g.gutil_rec168.notna() & g.real_demand_land.notna()].reset_index(drop=True)
    return g


def shift_stats(tr, te, f):
    """train/test 평균 + test 가 train [p1,p99] 밖인 비율(외삽)."""
    lo, hi = np.nanpercentile(tr[f], [1, 99])
    out = float(((te[f] < lo) | (te[f] > hi)).mean() * 100)
    return tr[f].mean(), te[f].mean(), out


def train(samp, feat, target):
    tr = samp[(samp.tyear >= 2022) & (samp.tyear <= 2024)]; va = samp[samp.tyear == 2025]
    dtr = lgb.Dataset(tr[feat], tr[target]); dva = lgb.Dataset(va[feat], va[target], reference=dtr)
    m = lgb.train(PARAMS, dtr, num_boost_round=3000, valid_sets=[dva], valid_names=['val'],
                  callbacks=[lgb.early_stopping(120, verbose=False)])
    return m, int(m.best_iteration)


def eval_chain(model, best, feat, d, ratio):
    px = pd.read_parquet(PARQUET); caps = load_caps()
    gas = d.gen_gas_kr; gutil = d.gas_util
    rows = []
    for base, gb in px.groupby('base'):
        O = pd.Timestamp(base).normalize() + pd.Timedelta(hours=23)
        sub = gb.copy(); t = pd.DatetimeIndex(sub.timestamp); h = ((t - O) / pd.Timedelta(hours=1)).astype(int).values
        sub['h'] = h
        sub['real_demand_land'] = sub.est_demand
        rcap = cap_on(t, caps, 'solar') + cap_on(t, caps, 'wind')
        sub['renew_gen_total_kr'] = sub.est_renew; sub['renew_util'] = sub.est_renew / rcap
        sub['gas_lag168'] = np.where(h <= 168, gas.reindex(t - pd.Timedelta(hours=168)).values, np.nan)
        sub['gas_lag24'] = np.where(h <= 24, gas.reindex(t - pd.Timedelta(hours=24)).values, np.nan)
        sub['gas_rec24'] = float(gas.loc[O - pd.Timedelta(hours=23):O].mean())
        sub['gas_rec168'] = float(gas.loc[O - pd.Timedelta(hours=167):O].mean())
        sub['gutil_lag168'] = np.where(h <= 168, gutil.reindex(t - pd.Timedelta(hours=168)).values, np.nan)
        sub['gutil_lag24'] = np.where(h <= 24, gutil.reindex(t - pd.Timedelta(hours=24)).values, np.nan)
        sub['gutil_rec24'] = float(gutil.loc[O - pd.Timedelta(hours=23):O].mean())
        sub['gutil_rec168'] = float(gutil.loc[O - pd.Timedelta(hours=167):O].mean())
        sub['hour'] = t.hour; sub['dow'] = t.dayofweek; sub['doy'] = t.dayofyear
        sub['LNG_cap'] = cap_on(t, caps, 'LNG')
        rows.append(sub)
    r = pd.concat(rows, ignore_index=True)
    pred = model.predict(r[feat], num_iteration=best)
    r['pred'] = pred * r['LNG_cap'] if ratio else pred       # ratio 면 util→MW 복원
    r = r.dropna(subset=['gen_gas_kr']); r = r[r.gen_gas_kr > 0]
    r['season'] = pd.DatetimeIndex(r.timestamp).month.map(SEASON)
    return r


def main():
    d = load_cont(); samp = build_samples(d)
    tr = samp[(samp.tyear >= 2022) & (samp.tyear <= 2024)]; te = samp[samp.tyear == 2026]
    print('=' * 80); print('(A) 비정상성 — 연도상관 + train(2022-24)/test(2026) 평균 + 외삽비율(test가 train p1~p99 밖)')
    print('=' * 80)
    print(f'{"변수":18} {"corr(연도)":>10} {"train평균":>10} {"test평균":>10} {"외삽%":>7}')
    yr = tr.tyear.values
    for f in ['gen_gas' if False else 'y', 'gas_util', 'real_demand_land', 'renew_gen_total_kr', 'renew_util',
              'gas_rec168', 'gutil_rec168', 'LNG_cap']:
        if f not in samp: continue
        ry = np.corrcoef(yr, tr[f])[0, 1]
        trm, tem, out = shift_stats(tr, te, f)
        print(f'{f:18} {ry:>+10.3f} {trm:>10.1f} {tem:>10.1f} {out:>6.1f}%')

    print('\n' + '=' * 80); print('(B) 가스 모델: MW vs RATIO(전부 이용률) vs MIXED(가스·수요 MW + 신재생만 util)'); print('=' * 80)
    MIXED_FEAT = ['real_demand_land', 'renew_util', 'gas_lag168', 'gas_lag24', 'gas_rec24', 'gas_rec168'] + CAL
    mM, bM = train(samp, MW_FEAT, 'y'); rM = eval_chain(mM, bM, MW_FEAT, d, ratio=False)
    mR, bR = train(samp, RATIO_FEAT, 'gas_util'); rR = eval_chain(mR, bR, RATIO_FEAT, d, ratio=True)
    mX, bX = train(samp, MIXED_FEAT, 'y'); rX = eval_chain(mX, bX, MIXED_FEAT, d, ratio=False)
    print(f'  best_iter  MW {bM} / RATIO {bR} / MIXED {bX}')
    print('\n지평 |     MW       |   RATIO(전부)  |  MIXED(신재생만)')
    for n in BLOCKS:
        lo, hi = BLOCKS[n]
        def cell(r): g = r[(r.h >= lo) & (r.h <= hi)]; return f'{mape(g.gen_gas_kr,g.pred):5.2f}/{nbias(g.gen_gas_kr,g.pred):+5.1f}'
        print(f' D+{n:>2} | {cell(rM):>11} | {cell(rR):>12} | {cell(rX):>12}')
    print('\n낮(09-15) |     MW       |   RATIO(전부)  |  MIXED(신재생만)')
    for s in ['겨울', '봄', '여름']:
        def celld(r): g = r[(r.season == s) & (pd.DatetimeIndex(r.timestamp).hour.isin(range(9, 16)))]; return f'{mape(g.gen_gas_kr,g.pred):5.2f}/{nbias(g.gen_gas_kr,g.pred):+5.1f}'
        print(f'  {s}낮 | {celld(rM):>11} | {celld(rR):>12} | {celld(rX):>12}')


if __name__ == '__main__':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass
    main()

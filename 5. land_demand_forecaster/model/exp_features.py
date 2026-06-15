# -*- coding: utf-8 -*-
"""수요 피처 엔지니어링 실험 — 지점선택 base 에 구름·BTM/PPA 용량 단계 추가.

사용자 방향(2026-06-14): ① 일사·풍속·구름은 용량집중지(태양광=서산·영광, 풍력=대관령·포항)만
② 봄·낮 과대예측의 유력 원인 = BTM/PPA 용량 피처 부재(제주 2-A엔 있고 land 5-A엔 없음).
PPA 용량(kr_elec_capa.csv, 월별)이 14.6k→21.5k MW 성장하는데 모델이 모르니 미드데이 BTM
억제 증가를 못 따라가 과대예측한다는 가설.

변형(누적):
  V0 select   : 일사/풍속 지점선택(서산영광 / 대관령포항), 기온 5평균  [직전 실험 우승안]
  V1 +cloud   : + total_cloud·midlow_cloud (서산·영광 평균)
  V2 +btmppa  : V1 + cap_btmppa (월별 PPA 용량)
구조=Global+Horizon LGBM(5-A 동일 params). 학습 train≤2024/val2025, 평가=실예보 백테스트 낮×계절.
"""
from __future__ import annotations
import os, sys, sqlite3, tempfile, importlib.util
import numpy as np, pandas as pd, lightgbm as lgb

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, '..', '..'))
DB = os.path.join(ROOT, '1. data_fetcher_and_db', 'data', 'input_data_land.db')
CAPA = os.path.join(ROOT, '1. data_fetcher_and_db', 'second_dataset', 'kr_elec_capa.csv')
BT = os.path.join(ROOT, '7. land_gas_forecaster', 'training', 'build_horizon_backtest.py')
spec = importlib.util.spec_from_file_location('bht', BT)
bht = importlib.util.module_from_spec(spec); spec.loader.exec_module(bht)

STATIONS = ['daegwallyeong', 'wonju', 'seosan', 'pohang', 'yeonggwang']
SOLAR_SEL = ['seosan', 'yeonggwang']      # 태양광·구름 집중지(충남·전남)
WIND_SEL = ['daegwallyeong', 'pohang']    # 풍력 집중지(강원·경북)
PARAMS = dict(objective='regression_l1', metric='mae', learning_rate=0.03, num_leaves=255,
              min_data_in_leaf=100, feature_fraction=0.85, bagging_fraction=0.8, bagging_freq=5,
              lambda_l2=0.2, verbosity=-1, random_state=42)
DTCATS = bht.DTCATS; BLOCKS, LAGW = bht.BLOCKS, bht.LAGW
SEASON = {12: '겨울', 1: '겨울', 2: '겨울', 3: '봄', 4: '봄', 5: '봄',
          6: '여름', 7: '여름', 8: '여름', 9: '가을', 10: '가을', 11: '가을'}
BASEFEAT = ['h', 'lag168', 'lag336', 'lag504', 'lag24', 'rec24', 'rec168', 'temp_c', 'solar_rad', 'wind_spd',
            'hour_sin', 'hour_cos', 'dow_sin', 'dow_cos', 'month_sin', 'month_cos', 'day_type']
VARIANTS = {
    'V0 select': [],
    'V1 +cloud': ['total_cloud', 'midlow_cloud'],
    'V2 +btmppa': ['total_cloud', 'midlow_cloud', 'cap_btmppa'],
}


def mape(a, p):
    a, p = np.asarray(a, float), np.asarray(p, float)
    m = (a > 0) & np.isfinite(a) & np.isfinite(p)
    return float(np.mean(np.abs(a[m]-p[m])/a[m])*100) if m.any() else np.nan


def nbias(a, p):
    a, p = np.asarray(a, float), np.asarray(p, float)
    m = (a > 0) & np.isfinite(a) & np.isfinite(p)
    return float(np.mean((p[m]-a[m])/a[m])*100) if m.any() else np.nan


def load_capa():
    """월별 PPA 용량(합계) → Period(M) 인덱스 Series."""
    df = pd.read_csv(CAPA, encoding='euc-kr', header=None, skiprows=2)
    df.columns = ['period', 'region', 'LNG', 'solar', 'wind', 'PPA']
    df = df[df.region.astype(str).str.strip() == '합계'].copy()
    df['ym'] = pd.to_datetime(df.period, format='%b-%y').dt.to_period('M')
    df['PPA'] = pd.to_numeric(df.PPA, errors='coerce')
    return df.dropna(subset=['PPA']).set_index('ym')['PPA'].sort_index()


def cap_for(idx, ppa):
    ym = idx.to_period('M')
    full = pd.period_range(min(ym.min(), ppa.index.min()), max(ym.max(), ppa.index.max()), freq='M')
    return ym.map(ppa.reindex(full).ffill().bfill()).astype(float).values


def load_hist():
    cl = [f'{c}_{s}' for s in STATIONS for c in ('total_cloud', 'midlow_cloud')]
    wxcols = [f'{w}_{s}' for s in STATIONS for w in ('temp_c', 'solar_rad', 'wind_spd')]
    pull = ['timestamp', 'real_demand_land', 'day_type'] + wxcols + cl
    with sqlite3.connect(DB) as con:
        raw = pd.read_sql(f"SELECT {', '.join(pull)} FROM historical", con, parse_dates=['timestamp'])
    raw = raw.sort_values('timestamp')
    idx = pd.date_range(raw.timestamp.min(), raw.timestamp.max(), freq='h')
    d = raw.set_index('timestamp').reindex(idx); d.index.name = 'timestamp'
    d.loc[d.real_demand_land == 0, 'real_demand_land'] = np.nan
    d['real_demand_land'] = d['real_demand_land'].interpolate('time')
    for c in wxcols + cl:
        d[c] = pd.to_numeric(d[c], errors='coerce').interpolate('time')
    d['day_type'] = d['day_type'].ffill().bfill()
    # 집계 컬럼
    d['temp_c'] = d[[f'temp_c_{s}' for s in STATIONS]].mean(1)
    d['solar_rad'] = d[[f'solar_rad_{s}' for s in SOLAR_SEL]].mean(1)
    d['wind_spd'] = d[[f'wind_spd_{s}' for s in WIND_SEL]].mean(1)
    d['total_cloud'] = d[[f'total_cloud_{s}' for s in SOLAR_SEL]].mean(1)
    d['midlow_cloud'] = d[[f'midlow_cloud_{s}' for s in SOLAR_SEL]].mean(1)
    return d


HMAX = 360   # 지평 최대(h) — D+15(=360h)까지 학습.  (구 168=D+7; lag168 의 168 과 구분)


def build_samples(d, ppa):
    dem = d.real_demand_land.values.astype(float)
    hour = d.index.hour.values; dow = d.index.dayofweek.values; month = d.index.month.values
    year = d.index.year.values; dtype_arr = d.day_type.values.astype(object)
    N = len(d)
    rec24 = pd.Series(dem).rolling(24, min_periods=24).mean().values
    rec168 = pd.Series(dem).rolling(168, min_periods=168).mean().values
    capb = cap_for(d.index, ppa)
    H = np.arange(1, HMAX + 1)
    origins = np.where((hour == 23) & (np.arange(N) >= 167) & (np.arange(N) <= N-1-HMAX))[0]
    tgt = (origins[:, None] + H[None, :]).ravel()
    hh = np.broadcast_to(H, (len(origins), HMAX)).ravel()
    def _lag(k):   # 정직 가드: h<=k(타깃-k가 원점 이전, 실서빙 가용) & 인덱스>=0 일 때만 채움
        idx = tgt - k
        val = np.where(idx >= 0, dem[np.clip(idx, 0, N-1)], np.nan)
        return np.where(hh <= k, val, np.nan)
    g = {'y': dem[tgt], 'h': hh.astype(np.int16),
         'lag168': _lag(168), 'lag336': _lag(336), 'lag504': _lag(504),
         'lag24': np.where(hh <= 24, dem[tgt-24], np.nan),
         'rec24': np.repeat(rec24[origins], HMAX), 'rec168': np.repeat(rec168[origins], HMAX),
         'temp_c': d.temp_c.values[tgt], 'solar_rad': d.solar_rad.values[tgt], 'wind_spd': d.wind_spd.values[tgt],
         'total_cloud': d.total_cloud.values[tgt], 'midlow_cloud': d.midlow_cloud.values[tgt],
         'cap_btmppa': capb[tgt], 'hour': hour[tgt], 'dow': dow[tgt], 'month': month[tgt],
         'day_type': dtype_arr[tgt], 'tyear': year[tgt]}
    s = pd.DataFrame(g)
    s['hour_sin'] = np.sin(2*np.pi*s.hour/24); s['hour_cos'] = np.cos(2*np.pi*s.hour/24)
    s['dow_sin'] = np.sin(2*np.pi*s.dow/7); s['dow_cos'] = np.cos(2*np.pi*s.dow/7)
    s['month_sin'] = np.sin(2*np.pi*s.month/12); s['month_cos'] = np.cos(2*np.pi*s.month/12)
    s = s[s.y.notna() & s.lag504.notna()].reset_index(drop=True)   # lag504=21일 이력 보장(전 지평 주간앵커)
    s['day_type'] = pd.Categorical(s['day_type'], categories=DTCATS)
    return s


def train(samp, feat):
    tr = samp[samp.tyear <= 2024]; va = samp[samp.tyear == 2025]
    dtr = lgb.Dataset(tr[feat], tr.y, categorical_feature=['day_type'])
    dva = lgb.Dataset(va[feat], va.y, categorical_feature=['day_type'], reference=dtr)
    m = lgb.train(PARAMS, dtr, num_boost_round=4000, valid_sets=[dva], valid_names=['val'],
                  callbacks=[lgb.early_stopping(150, verbose=False)])
    return m, int(m.best_iteration)


FORE_PREFIX = {'temp_c': 'temp', 'solar_rad': 'radiation', 'wind_spd': 'wind_spd_10m'}


def fh_weather(con, targets):
    cols = ([f'{FORE_PREFIX[w]}_{s}' for w in ('temp_c',) for s in STATIONS] +
            [f'radiation_{s}' for s in SOLAR_SEL] + [f'wind_spd_10m_{s}' for s in WIND_SEL] +
            [f'total_cloud_{s}' for s in SOLAR_SEL] + [f'midlow_cloud_{s}' for s in SOLAR_SEL])
    cols = sorted(set(cols))
    ext = pd.date_range(targets.min() - pd.Timedelta(hours=3), targets.max() + pd.Timedelta(hours=3), freq='h')
    sel = ', '.join(f'"{c}"' for c in ['timestamp'] + cols)
    fc = pd.read_sql(f'SELECT {sel} FROM forecast WHERE timestamp BETWEEN ? AND ? ORDER BY timestamp',
                     con, params=(bht._S(ext[0]), bht._S(ext[-1])), parse_dates=['timestamp']).set_index('timestamp')
    fc = fc.apply(pd.to_numeric, errors='coerce').reindex(ext)

    def mean_interp(cs):
        return fc[cs].mean(1).interpolate('time', limit=3, limit_area='inside').reindex(targets).values
    out = pd.DataFrame(index=targets)
    out['temp_c'] = mean_interp([f'temp_{s}' for s in STATIONS])
    out['solar_rad'] = mean_interp([f'radiation_{s}' for s in SOLAR_SEL])
    out['wind_spd'] = mean_interp([f'wind_spd_10m_{s}' for s in WIND_SEL])
    out['total_cloud'] = mean_interp([f'total_cloud_{s}' for s in SOLAR_SEL])
    out['midlow_cloud'] = mean_interp([f'midlow_cloud_{s}' for s in SOLAR_SEL])
    valid = out[['temp_c', 'solar_rad', 'wind_spd']].notna().all(axis=1)
    return out, valid


def eval_forecast(model, best, feat, d_act, ppa, horizons=(1, 2, 3, 7, 12), offset=0.0, require_actual=True):
    with sqlite3.connect(DB) as con:
        bases = [r[0] for r in con.execute('SELECT DISTINCT base FROM forecast_horizon ORDER BY base').fetchall()]
    sc = bht.build_scratch(os.path.join(tempfile.gettempdir(), 'exp_feat.db'))
    dem = d_act['real_demand_land']; rows = []
    for base in bases:
        O = pd.Timestamp(base).normalize() + pd.Timedelta(hours=23)
        bht.set_scratch_forecast(sc, base)
        for n in horizons:
            h0, h1 = (n - 1) * 24 + 1, n * 24; H = np.arange(h0, h1+1)
            tg = pd.DatetimeIndex([O + pd.Timedelta(hours=int(h)) for h in H])
            wx, valid = fh_weather(sc, tg)
            df = pd.DataFrame(index=tg)
            df['h'] = H
            for k in (168, 336, 504):   # 정직 가드: h<=k 일 때만(타깃-k가 원점 이전)
                df[f'lag{k}'] = np.where(H <= k, dem.reindex(tg - pd.Timedelta(hours=k)).values, np.nan)
            df['lag24'] = np.where(H <= 24, dem.reindex(tg - pd.Timedelta(hours=24)).values, np.nan)
            df['rec24'] = float(dem.loc[O - pd.Timedelta(hours=23):O].mean())
            df['rec168'] = float(dem.loc[O - pd.Timedelta(hours=167):O].mean())
            for c in ('temp_c', 'solar_rad', 'wind_spd', 'total_cloud', 'midlow_cloud'):
                df[c] = wx[c].values
            df['cap_btmppa'] = cap_for(tg, ppa)
            df['hour_sin'] = np.sin(2*np.pi*tg.hour/24); df['hour_cos'] = np.cos(2*np.pi*tg.hour/24)
            df['dow_sin'] = np.sin(2*np.pi*tg.dayofweek/7); df['dow_cos'] = np.cos(2*np.pi*tg.dayofweek/7)
            df['month_sin'] = np.sin(2*np.pi*tg.month/12); df['month_cos'] = np.cos(2*np.pi*tg.month/12)
            df['day_type'] = pd.Categorical(d_act['day_type'].reindex(tg).values, categories=DTCATS)
            ok = valid.values & ~np.isnan(df['lag504'].values)
            pred = np.full(len(tg), np.nan)
            if ok.any():
                pred[ok] = model.predict(df.loc[ok, feat], num_iteration=best) + offset
            rows.append(pd.DataFrame({'base': base, 'timestamp': tg, 'horizon': n,
                                      'actual': dem.reindex(tg).values, 'pred': pred}))
    sc.close()
    r = pd.concat(rows, ignore_index=True)
    if require_actual:
        r = r.dropna(subset=['actual', 'pred']); r = r[r.actual > 0]   # 평가용(실측 필요)
    else:
        r = r.dropna(subset=['pred'])                                  # 아카이브용(미래 타깃도 보존)
    r['season'] = pd.DatetimeIndex(r.timestamp).month.map(SEASON)
    r['daypart'] = np.where((pd.DatetimeIndex(r.timestamp).hour >= 9) & (pd.DatetimeIndex(r.timestamp).hour <= 15), '낮', '밤')
    return r


def main():
    d = load_hist(); ppa = load_capa(); d_act = bht.load_actuals()
    print('PPA 용량 범위:', f'{ppa.min():.0f}~{ppa.max():.0f} MW', ppa.index.min(), '~', ppa.index.max())
    samp = build_samples(d, ppa)
    res = {}
    for name, extra in VARIANTS.items():
        feat = BASEFEAT + extra
        m, best = train(samp, feat)
        res[name] = eval_forecast(m, best, feat, d_act, ppa)
        # 중요도(상위)
        imp = pd.DataFrame({'f': m.feature_name(), 'g': m.feature_importance('gain')}).sort_values('g', ascending=False)
        extra_imp = imp[imp.f.isin(extra)]
        print(f'  {name}: best_iter {best}  추가피처 중요도 ' +
              (', '.join(f'{r.f} {r.g/imp.g.sum()*100:.1f}%' for _, r in extra_imp.iterrows()) if extra else '-'))

    names = list(VARIANTS)
    print('\n======== 지평별 MAPE ========')
    print('지평  | ' + ' | '.join(f'{n:>14}' for n in names))
    for n in [1, 3, 7, 12]:
        cells = [f'{mape(g[g.horizon==n].actual,g[g.horizon==n].pred):5.2f}/{nbias(g[g.horizon==n].actual,g[g.horizon==n].pred):+5.2f}' for g in (res[k] for k in names)]
        print(f' D+{n:>2} | ' + ' | '.join(f'{c:>14}' for c in cells))
    print('\n======== 계절×낮 MAPE / bias ========')
    for s in ['겨울', '봄', '여름']:
        for dp in ['낮', '밤']:
            cells = []
            for k in names:
                g = res[k]; g = g[(g.season == s) & (g.daypart == dp)]
                cells.append(f'{mape(g.actual,g.pred):5.2f}/{nbias(g.actual,g.pred):+5.2f}')
            print(f' {s}{dp} | ' + ' | '.join(f'{c:>14}' for c in cells))


if __name__ == '__main__':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass
    main()

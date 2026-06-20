# -*- coding: utf-8 -*-
"""수요 모델 기상 공간집계 비교 실험 — 단순 5지점평균 vs 지점선택(용량집중지).

사용자 가설(2026-06-14): 태양광은 충남·전남(서산·영광), 풍력은 강원·경북(대관령·포항)에 용량이
집중돼 단순 5지점평균은 왜곡. 일사=서산+영광, 풍속=대관령+포항만 쓰는 게 나을 수 있다.

피처 정의가 바뀌므로 변형마다 수요 Global+Horizon LGBM 을 재학습(train≤2024/val2025)한 뒤
실예보 백테스트(forecast_horizon, 2025-12~2026-06)로 비교한다. 평가축 = 지평 + 계절×낮(09-15h).
구조·하이퍼파라미터·나머지 피처는 5-A 와 동일(기온은 두 변형 다 5지점평균 유지).
"""
from __future__ import annotations
import os, sys, sqlite3, tempfile, importlib.util
import numpy as np, pandas as pd, lightgbm as lgb

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, '..', '..'))
DB = os.path.join(ROOT, '1. data_fetcher_and_db', 'data', 'input_data_land.db')
BT = os.path.join(ROOT, '7. land_gas_forecaster', 'training', 'build_horizon_backtest.py')
TAB = os.path.join(HERE, 'tab'); os.makedirs(TAB, exist_ok=True)
spec = importlib.util.spec_from_file_location('bht', BT)
bht = importlib.util.module_from_spec(spec); spec.loader.exec_module(bht)

STATIONS = ['daegwallyeong', 'wonju', 'seosan', 'pohang', 'yeonggwang']
WX = ['temp_c', 'solar_rad', 'wind_spd']
FORE_PREFIX = {'temp_c': 'temp', 'solar_rad': 'radiation', 'wind_spd': 'wind_spd_10m'}
FEAT = ['h', 'lag168', 'lag24', 'rec24', 'rec168', 'temp_c', 'solar_rad', 'wind_spd',
        'hour_sin', 'hour_cos', 'dow_sin', 'dow_cos', 'month_sin', 'month_cos', 'day_type']
PARAMS = dict(objective='regression_l1', metric='mae', learning_rate=0.03, num_leaves=255,
              min_data_in_leaf=100, feature_fraction=0.85, bagging_fraction=0.8, bagging_freq=5,
              lambda_l2=0.2, verbosity=-1, random_state=42)
BLOCKS, LAGW = bht.BLOCKS, bht.LAGW
DTCATS = bht.DTCATS
SEASON = {12: '겨울', 1: '겨울', 2: '겨울', 3: '봄', 4: '봄', 5: '봄',
          6: '여름', 7: '여름', 8: '여름', 9: '가을', 10: '가을', 11: '가을'}

VARIANTS = {
    'current(5평균)':
        {'temp_c': STATIONS, 'solar_rad': STATIONS, 'wind_spd': STATIONS},
    'select(일사=서산영광,풍속=대관령포항)':
        {'temp_c': STATIONS, 'solar_rad': ['seosan', 'yeonggwang'], 'wind_spd': ['daegwallyeong', 'pohang']},
}


def mape(a, p):
    a, p = np.asarray(a, float), np.asarray(p, float)
    m = (a > 0) & np.isfinite(a) & np.isfinite(p)
    return float(np.mean(np.abs(a[m]-p[m])/a[m])*100) if m.any() else np.nan


def nbias(a, p):
    a, p = np.asarray(a, float), np.asarray(p, float)
    m = (a > 0) & np.isfinite(a) & np.isfinite(p)
    return float(np.mean((p[m]-a[m])/a[m])*100) if m.any() else np.nan


def load_hist():
    pull = ['timestamp', 'real_demand_land', 'land_est_demand_da', 'day_type'] + \
           [f'{w}_{s}' for s in STATIONS for w in WX]
    with sqlite3.connect(DB) as con:
        raw = pd.read_sql(f"SELECT {', '.join(pull)} FROM historical", con, parse_dates=['timestamp'])
    raw = raw.sort_values('timestamp')
    idx = pd.date_range(raw.timestamp.min(), raw.timestamp.max(), freq='h')
    d = raw.set_index('timestamp').reindex(idx); d.index.name = 'timestamp'
    d.loc[d.real_demand_land == 0, 'real_demand_land'] = np.nan
    d['real_demand_land'] = d['real_demand_land'].interpolate('time')
    for s in STATIONS:
        for w in WX:
            d[f'{w}_{s}'] = pd.to_numeric(d[f'{w}_{s}'], errors='coerce').interpolate('time')
    d['day_type'] = d['day_type'].ffill().bfill()
    return d


def agg_wx(frame, agg, prefix=None):
    """frame 의 지점별 컬럼을 변형 정의대로 평균해 temp_c/solar_rad/wind_spd 반환.
    prefix=None 이면 historical 컬럼명({w}_{s}), 아니면 forecast({FORE_PREFIX[w]}_{s})."""
    out = pd.DataFrame(index=frame.index)
    for w in WX:
        cols = [f'{(FORE_PREFIX[w] if prefix else w)}_{s}' for s in agg[w]]
        out[w] = frame[cols].mean(axis=1)
    return out


def build_samples(d, agg):
    wx = agg_wx(d, agg)
    dem = d.real_demand_land.values.astype(float)
    base = d.land_est_demand_da.values.astype(float)
    hour = d.index.hour.values; dow = d.index.dayofweek.values; month = d.index.month.values
    year = d.index.year.values; dtype_arr = d.day_type.values.astype(object)
    N = len(d)
    rec24 = pd.Series(dem).rolling(24, min_periods=24).mean().values
    rec168 = pd.Series(dem).rolling(168, min_periods=168).mean().values
    H = np.arange(1, 169)
    origins = np.where((hour == 23) & (np.arange(N) >= 167) & (np.arange(N) <= N-1-168))[0]
    tgt = (origins[:, None] + H[None, :]).ravel()
    hh = np.broadcast_to(H, (len(origins), 168)).ravel()
    s = pd.DataFrame({
        'y': dem[tgt], 'h': hh.astype(np.int16), 'lag168': dem[tgt-168],
        'lag24': np.where(hh <= 24, dem[tgt-24], np.nan),
        'rec24': np.repeat(rec24[origins], 168), 'rec168': np.repeat(rec168[origins], 168),
        'temp_c': wx.temp_c.values[tgt], 'solar_rad': wx.solar_rad.values[tgt], 'wind_spd': wx.wind_spd.values[tgt],
        'hour': hour[tgt], 'dow': dow[tgt], 'month': month[tgt],
        'day_type': dtype_arr[tgt], 'tyear': year[tgt]})
    s['hour_sin'] = np.sin(2*np.pi*s.hour/24); s['hour_cos'] = np.cos(2*np.pi*s.hour/24)
    s['dow_sin'] = np.sin(2*np.pi*s.dow/7); s['dow_cos'] = np.cos(2*np.pi*s.dow/7)
    s['month_sin'] = np.sin(2*np.pi*s.month/12); s['month_cos'] = np.cos(2*np.pi*s.month/12)
    s = s[s.y.notna() & s.lag168.notna()].reset_index(drop=True)
    s['day_type'] = pd.Categorical(s['day_type'], categories=DTCATS)
    return s


def train(samp):
    tr = samp[samp.tyear <= 2024]; va = samp[samp.tyear == 2025]
    dtr = lgb.Dataset(tr[FEAT], tr.y, categorical_feature=['day_type'])
    dva = lgb.Dataset(va[FEAT], va.y, categorical_feature=['day_type'], reference=dtr)
    m = lgb.train(PARAMS, dtr, num_boost_round=4000, valid_sets=[dva], valid_names=['val'],
                  callbacks=[lgb.early_stopping(150, verbose=False)])
    return m, int(m.best_iteration)


def fh_weather_variant(con, targets, agg):
    cols = sorted({f'{FORE_PREFIX[w]}_{s}' for w in WX for s in agg[w]})
    ext = pd.date_range(targets.min() - pd.Timedelta(hours=3), targets.max() + pd.Timedelta(hours=3), freq='h')
    sel = ', '.join(f'"{c}"' for c in ['timestamp'] + cols)
    fc = pd.read_sql(f'SELECT {sel} FROM forecast WHERE timestamp BETWEEN ? AND ? ORDER BY timestamp',
                     con, params=(bht._S(ext[0]), bht._S(ext[-1])), parse_dates=['timestamp']).set_index('timestamp')
    fc = fc.apply(pd.to_numeric, errors='coerce').reindex(ext)
    out = pd.DataFrame(index=targets)
    for w in WX:
        m = fc[[f'{FORE_PREFIX[w]}_{s}' for s in agg[w]]].mean(axis=1)
        out[w] = m.interpolate('time', limit=3, limit_area='inside').reindex(targets).values
    return out, out.notna().all(axis=1)


def eval_forecast(model, best, agg, d_act):
    with sqlite3.connect(DB) as con:
        bases = [r[0] for r in con.execute('SELECT DISTINCT base FROM forecast_horizon ORDER BY base').fetchall()]
    sc = bht.build_scratch(os.path.join(tempfile.gettempdir(), 'exp_wx.db'))
    dem = d_act['real_demand_land']
    rows = []
    for base in bases:
        O = pd.Timestamp(base).normalize() + pd.Timedelta(hours=23)
        bht.set_scratch_forecast(sc, base)
        for n in [1, 2, 3, 7, 12]:
            h0, h1 = BLOCKS[n]; H = np.arange(h0, h1+1); lagw = LAGW[n]
            tg = pd.DatetimeIndex([O + pd.Timedelta(hours=int(h)) for h in H])
            wx, valid = fh_weather_variant(sc, tg, agg)
            df = pd.DataFrame(index=tg)
            df['h'] = H; df['lag168'] = dem.reindex(tg - pd.Timedelta(hours=168)).values
            df['lag24'] = np.where(H <= 24, dem.reindex(tg - pd.Timedelta(hours=24)).values, np.nan)
            df['rec24'] = float(dem.loc[O - pd.Timedelta(hours=23):O].mean())
            df['rec168'] = float(dem.loc[O - pd.Timedelta(hours=167):O].mean())
            for w in WX:
                df[w] = wx[w].values
            df['hour_sin'] = np.sin(2*np.pi*tg.hour/24); df['hour_cos'] = np.cos(2*np.pi*tg.hour/24)
            df['dow_sin'] = np.sin(2*np.pi*tg.dayofweek/7); df['dow_cos'] = np.cos(2*np.pi*tg.dayofweek/7)
            df['month_sin'] = np.sin(2*np.pi*tg.month/12); df['month_cos'] = np.cos(2*np.pi*tg.month/12)
            df['day_type'] = pd.Categorical(d_act['day_type'].reindex(tg).values, categories=DTCATS)
            ok = valid.values & ~np.isnan(df['lag168'].values)
            pred = np.full(len(tg), np.nan)
            if ok.any():
                pred[ok] = model.predict(df.loc[ok, FEAT], num_iteration=best)
            rows.append(pd.DataFrame({'timestamp': tg, 'horizon': n,
                                      'actual': dem.reindex(tg).values, 'pred': pred}))
    sc.close()
    r = pd.concat(rows, ignore_index=True).dropna(subset=['actual', 'pred']); r = r[r.actual > 0]
    return r


def main():
    d = load_hist()
    d_act = bht.load_actuals()
    results = {}
    for name, agg in VARIANTS.items():
        print(f'\n### 학습: {name}')
        samp = build_samples(d, agg)
        m, best = train(samp)
        print(f'  best_iter {best}, 샘플 {len(samp)}')
        r = eval_forecast(m, best, agg, d_act)
        r['season'] = pd.DatetimeIndex(r.timestamp).month.map(SEASON)
        r['daypart'] = np.where((pd.DatetimeIndex(r.timestamp).hour >= 9) &
                                (pd.DatetimeIndex(r.timestamp).hour <= 15), '낮', '밤')
        results[name] = r

    print('\n\n======== 지평별 MAPE (실예보) ========')
    print(f'{"지평":>5} | ' + ' | '.join(f'{n:>22}' for n in VARIANTS))
    for n in [1, 2, 3, 7, 12]:
        cells = []
        for name in VARIANTS:
            g = results[name]; g = g[g.horizon == n]
            cells.append(f'{mape(g.actual,g.pred):5.2f}% b{nbias(g.actual,g.pred):+5.2f}%')
        print(f'  D+{n:>2} | ' + ' | '.join(f'{c:>22}' for c in cells))

    print('\n======== 계절×낮 MAPE (전 지평) ========')
    for s in ['겨울', '봄', '여름']:
        for dp in ['낮', '밤']:
            cells = []
            for name in VARIANTS:
                g = results[name]; g = g[(g.season == s) & (g.daypart == dp)]
                cells.append(f'{mape(g.actual,g.pred):5.2f}% b{nbias(g.actual,g.pred):+5.2f}%')
            print(f'  {s} {dp} | ' + ' | '.join(f'{c:>22}' for c in cells))


if __name__ == '__main__':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass
    main()

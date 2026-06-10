# -*- coding: utf-8 -*-
"""7-A2-A 체인 데이터셋 빌더 — 5단계(수요)·6단계(신재생) 서빙 출력을 지평별로 생성.

목적: 7단계 가스 모델을 '실측 입력'이 아니라 '서빙(예보) 입력'으로 재학습(A안)하기 위해,
      train 2022-24 / val 2025 / test 2026 전 구간에 대해 지평별 체인 입력을 만든다.

지평: D+1/D+2/D+3/D+7/D+12 (다른 모델들과 동일).
  - 수요  est_demand : 5-A2 지평별 LGBM (lgbm_land_demand_D{n}.txt) — 검증 지평과 정확히 일치.
  - 신재생 est_renew  : 6단계 serve_solarwind_land._predict_day(horizon=n) 의 est_market_renew_land.
  - 기상  : forecast 예보 우선 + (월,시) 기후값 폴백 (과거 구간은 기후값 = 서빙 하한 모드).
  - 타깃  : 실측 gen_gas_kr (historical).

출력: training/chained_gas_dataset.parquet  (timestamp, horizon, est_demand, est_renew, gen_gas_kr, 달력, day_type, split)
사용: python build_chained_dataset.py [--limit N] [--horizons 1,2,3,7,12]
"""
from __future__ import annotations
import os, sys, sqlite3, json, time, argparse, importlib.util
import numpy as np, pandas as pd, lightgbm as lgb

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, '..', '..'))
DB   = os.path.join(ROOT, '1. data_fetcher_and_db', 'data', 'input_data_land.db')
DEM_MODELS = os.path.join(ROOT, '5. land_demand_forecaster', 'model', 'models')
SERVE6 = os.path.join(ROOT, '6. land_solarwind_forecaster', 'serve_solarwind_land.py')

ST = ['daegwallyeong', 'wonju', 'seosan', 'pohang', 'yeonggwang']
WX = ['temp_c', 'solar_rad', 'wind_spd']
FORE_PREFIX = {'temp_c': 'temp', 'solar_rad': 'radiation', 'wind_spd': 'wind_spd_10m'}
DTCATS = ['holiday', 'weekday', 'weekend']
CYC = ['hour_sin', 'hour_cos', 'dow_sin', 'dow_cos', 'month_sin', 'month_cos']
FEAT_DEM = ['lag_week', 'rec24', 'rec168'] + WX + CYC + ['day_type']
BLOCKS = {1: (1, 24), 2: (25, 48), 3: (49, 72), 7: (145, 168), 12: (265, 288)}
LAGW = {1: 168, 2: 168, 3: 168, 7: 168, 12: 336}


# ── 6단계 서빙 모듈 동적 임포트 ──
def _load_serve6():
    spec = importlib.util.spec_from_file_location('serve_solarwind_land', SERVE6)
    mod = importlib.util.module_from_spec(spec)
    sys.modules['serve_solarwind_land'] = mod
    spec.loader.exec_module(mod)
    return mod


def _conn():
    return sqlite3.connect(DB)


# ── 수요 시계열·기상(5지점평균)·기후값 (5-A2 와 동일 전처리) ──
def load_demand_assets():
    pull = ['timestamp', 'real_demand_land', 'gen_gas_kr', 'day_type'] + [f'{w}_{s}' for s in ST for w in WX]
    with _conn() as con:
        raw = pd.read_sql(f"SELECT {', '.join(pull)} FROM historical", con, parse_dates=['timestamp'])
    raw = raw.sort_values('timestamp')
    for w in WX:
        raw[w] = raw[[f'{w}_{s}' for s in ST]].mean(axis=1)
    idx = pd.date_range(raw.timestamp.min(), raw.timestamp.max(), freq='h')
    d = raw.set_index('timestamp')[['real_demand_land', 'gen_gas_kr', 'day_type'] + WX].reindex(idx)
    d.loc[d.real_demand_land == 0, 'real_demand_land'] = np.nan
    d['real_demand_land'] = d['real_demand_land'].interpolate('time')
    for w in WX:
        d[w] = d[w].interpolate('time')
    d['day_type'] = d['day_type'].ffill().bfill()
    d.index.name = 'timestamp'
    # 기후값: train(<=2024) (hour,month) 평균
    tr = d[d.index.year <= 2024]
    clim = {w: tr.groupby([tr.index.hour, tr.index.month])[w].mean() for w in WX}
    return d, clim


# ── 대상일 기상(forecast 우선 + 기후값 폴백), 5지점평균 ──
def target_weather(targets: pd.DatetimeIndex, clim: dict) -> pd.DataFrame:
    fcols = [f'{FORE_PREFIX[w]}_{s}' for s in ST for w in WX]
    t0, t1 = targets.min(), targets.max()
    with _conn() as con:
        fc = pd.read_sql(
            f"SELECT timestamp, {', '.join(fcols)} FROM forecast WHERE timestamp BETWEEN ? AND ?",
            con, params=(t0.strftime('%Y-%m-%d %H:%M:%S'), t1.strftime('%Y-%m-%d %H:%M:%S')),
            parse_dates=['timestamp'])
    fc = fc.set_index('timestamp')
    out = pd.DataFrame(index=targets)
    for w in WX:
        cols = [f'{FORE_PREFIX[w]}_{s}' for s in ST]
        fmean = (fc[cols].apply(pd.to_numeric, errors='coerce').mean(axis=1).reindex(targets)
                 if len(fc) else pd.Series(np.nan, index=targets))
        cl = pd.Series([clim[w].get((t.hour, t.month), np.nan) for t in targets], index=targets)
        out[w] = fmean.where(fmean.notna(), cl)
    return out


# ── 수요 예측 (5-A2 D{n}) ──
def predict_demand(d, clim, dem_model, O, n):
    h0, h1 = BLOCKS[n]; H = np.arange(h0, h1 + 1); lagw = LAGW[n]
    targets = pd.DatetimeIndex([O + pd.Timedelta(hours=int(h)) for h in H])
    dem = d['real_demand_land']
    lag_week = dem.reindex(targets - pd.Timedelta(hours=lagw)).values
    rec24 = float(dem.loc[O - pd.Timedelta(hours=23):O].mean())
    rec168 = float(dem.loc[O - pd.Timedelta(hours=167):O].mean())
    wx = target_weather(targets, clim)
    df = pd.DataFrame(index=targets)
    df['lag_week'] = lag_week; df['rec24'] = rec24; df['rec168'] = rec168
    for w in WX:
        df[w] = wx[w].values
    hr = targets.hour; dw = targets.dayofweek; mo = targets.month
    df['hour_sin'] = np.sin(2*np.pi*hr/24); df['hour_cos'] = np.cos(2*np.pi*hr/24)
    df['dow_sin'] = np.sin(2*np.pi*dw/7); df['dow_cos'] = np.cos(2*np.pi*dw/7)
    df['month_sin'] = np.sin(2*np.pi*mo/12); df['month_cos'] = np.cos(2*np.pi*mo/12)
    dt = d['day_type'].reindex(targets).values
    df['day_type'] = pd.Categorical(dt, categories=DTCATS)
    if df[['lag_week'] + WX].isna().any().any():
        raise ValueError('demand feat NaN')
    pred = dem_model.predict(df[FEAT_DEM])
    return targets, pred, dt


def build(horizons, limit=None, start='2022-01-01', end='2026-06-09'):
    d, clim = load_demand_assets()
    serve6 = _load_serve6()
    A6 = serve6.load_assets()
    dem_models = {n: lgb.Booster(model_file=os.path.join(DEM_MODELS, f'lgbm_land_demand_D{n}.txt'))
                  for n in horizons}
    gas = d['gen_gas_kr']
    # origin 후보: 23:00, [start,end] 안에서 타깃·과거 충분
    origins_all = pd.date_range(pd.Timestamp(start).normalize() + pd.Timedelta(hours=23),
                                pd.Timestamp(end).normalize() + pd.Timedelta(hours=23), freq='D')
    rows = []
    t_start = time.time()
    for n in horizons:
        origins = origins_all
        if limit:
            origins = origins[::max(1, len(origins)//limit)][:limit]
        ok = 0
        with _conn() as con:
            for O in origins:
                try:
                    tg, dem_pred, dt = predict_demand(d, clim, dem_models[n], O, n)
                    out6, *_ = serve6._predict_day(con, O.normalize(), n, A6)
                    ren = pd.Series(out6[serve6.OUT['mr']].values,
                                    index=pd.DatetimeIndex(out6['timestamp'])).reindex(tg).values
                    gy = gas.reindex(tg).values
                    if np.isnan(ren).any() or np.isnan(gy).all():
                        continue
                    sub = pd.DataFrame({
                        'timestamp': tg, 'horizon': n,
                        'est_demand': dem_pred, 'est_renew': ren, 'gen_gas_kr': gy,
                        'hour': tg.hour, 'dow': tg.dayofweek, 'month': tg.month, 'doy': tg.dayofyear,
                        'day_type': dt})
                    rows.append(sub); ok += 1
                except Exception as e:
                    continue
        el = time.time() - t_start
        print(f'  D+{n:>2}: {ok}/{len(origins)} origins  (누적 {el:.1f}s)')
    res = pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()
    if len(res):
        yr = pd.DatetimeIndex(res.timestamp).year
        res['split'] = np.where(yr <= 2024, 'train', np.where(yr == 2025, 'val', 'test'))
    return res


if __name__ == '__main__':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument('--limit', type=int, default=None, help='지평당 origin 표본수(스모크테스트)')
    ap.add_argument('--horizons', default='1,2,3,7,12')
    ap.add_argument('--out', default=os.path.join(HERE, 'chained_gas_dataset.parquet'))
    a = ap.parse_args()
    hz = [int(x) for x in a.horizons.split(',')]
    res = build(hz, limit=a.limit)
    if len(res):
        print(f'\n총 {len(res)}행  지평별:', res.groupby("horizon").size().to_dict())
        print('split별:', res.groupby("split").size().to_dict())
        # 정합성: 체인 입력 vs 실측 (참고용)
        with _conn() as con:
            act = pd.read_sql('SELECT timestamp, real_demand_land, renew_gen_total_kr FROM historical',
                              con, parse_dates=['timestamp']).set_index('timestamp')
        m = res.join(act, on='timestamp')
        for n, g in m.groupby('horizon'):
            dd = g.dropna(subset=['real_demand_land'])
            db = (dd.est_demand - dd.real_demand_land).mean()
            rb = (g.est_renew - g.renew_gen_total_kr).mean()
            print(f'  D+{n:>2} 입력 bias: 수요 {db:+.0f}MW  신재생 {rb:+.0f}MW')
        if not a.limit:
            res.to_parquet(a.out); print('saved', a.out)
        else:
            print('(스모크테스트 — 저장 생략)')

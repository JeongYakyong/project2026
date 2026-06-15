# -*- coding: utf-8 -*-
"""실예보 지평 백테스트 빌더 — forecast_horizon(base별 실제 예보)로 5·6·7 체인을 정직하게 검증.

배경
----
기존 `build_chained_dataset.py`(→chained_gas_dataset.parquet)는 과거 구간에 forecast 가 없어
기상 입력이 사실상 전부 (월,시) 기후값 프록시였다.  "지평 평평·가스 ~13%·A안 기각"이 모두 그
프록시 위에서 나온 결론이다.  이 빌더는 사용자가 구축한 `forecast_horizon`(육지 181 base·
D+1~12, 2025-12~2026-06)의 **실제 지평별 예보**로 같은 체인을 돌려 정직하게 재측정한다.

★ 하드 규칙 (사용자 지시 2026-06-14): **기후값 폴백 절대 금지.**
   예보가 진짜 없는 시각은 기후값으로 채우지 않고 평가에서 제외한다.  허용되는 보정은
   forecast 앵커 사이의 시간 보간(≤4h, 외삽 금지)까지뿐 — 이건 실예보의 재표집이지 기후값이
   아니다.  forecast_horizon 은 D+7~12 가 3h 해상도(8행/일)지만 ≤4h 보간으로 1h 복원된다.

정렬
----
origin O = base 날짜 23:00 (base 21:00 = 12 UTC 발표와 정렬). horizon_d=n ↔ D+n 블록.
  수요 BLOCKS[n] 의 타깃 = O + h시간 (h∈블록) = D+n 의 00..23시.
  6단계 _predict_day(con, O.normalize(), n) 의 idx = (base날짜+n) 00..23시 = 동일.

방법
----
- 수요(5): 5-A2 지평별 모델(lgbm_land_demand_D{n}.txt).  기상 = forecast_horizon[base] 5지점평균
  (기후값 폴백 없음).  build_chained_dataset.predict_demand 와 동일 피처, target_weather 만 교체.
- 신재생(6): serve_solarwind_land._predict_day(con, ...) 를 **스크래치 connection**으로 호출.
  스크래치 DB 의 `forecast` 테이블에 그 base 의 forecast_horizon 행만 넣어, 서빙 코드 무수정으로
  지평 정직 기상을 먹인다(_predict_day 가 con 인자를 받음).  market_renew/true_renew/util 은
  수요와 무관(기상만) → 그대로 채택.  net_load 는 우리 수요로 재계산(스크래치엔 est_demand 없음).
- 가스(7): 7-A2(lgbm_land_gas_util.txt) 에 (수요예측, 신재생예측, 달력, day_type) → util.
  발전량 raw = util×LNG_cap(보정 전), 보정판 = ×bias_calib.  Phase 2 에서 raw 로 보정 재적합.
- 유효성: forecast_horizon 행은 원자적(temp 있으면 전 기상 있음, 수집기 sentinel 설계) →
  5지점 temp/rad/wind 가 ≤4h 보간 후에도 NaN 인 시각은 '예보 없음'으로 보고 **드롭**.

산출: training/horizon_backtest.parquet
  컬럼 = base, timestamp, horizon, est_demand, est_renew, est_net_load,
         est_gas_gen_raw(보정전), est_gas_gen(보정후), est_gas_ton,
         실측 real_demand_land/renew_gen_total_kr/net_load_kr/gen_gas_kr, 달력, day_type, weather_src
사용: python build_horizon_backtest.py [--limit N] [--horizons 1,2,3,7,12]
"""
from __future__ import annotations
import os, sys, sqlite3, json, time, argparse, importlib.util, tempfile
import numpy as np, pandas as pd, lightgbm as lgb

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, '..', '..'))
DB   = os.path.join(ROOT, '1. data_fetcher_and_db', 'data', 'input_data_land.db')
DEM_MODELS = os.path.join(ROOT, '5. land_demand_forecaster', 'model', 'models')
SERVE6 = os.path.join(ROOT, '6. land_solarwind_forecaster', 'serve_solarwind_land.py')
GAS_MODEL = os.path.join(HERE, '..', 'model', 'lgbm_land_gas_util.txt')
CALIB_JSON = os.path.join(HERE, '..', 'model', 'gas_serving_calib.json')
CAP_CSV = os.path.join(ROOT, '1. data_fetcher_and_db', 'second_dataset', 'kr_elec_capa.csv')

ST = ['daegwallyeong', 'wonju', 'seosan', 'pohang', 'yeonggwang']
WX = ['temp_c', 'solar_rad', 'wind_spd']
FORE_PREFIX = {'temp_c': 'temp', 'solar_rad': 'radiation', 'wind_spd': 'wind_spd_10m'}
DTCATS = ['holiday', 'weekday', 'weekend']
CYC = ['hour_sin', 'hour_cos', 'dow_sin', 'dow_cos', 'month_sin', 'month_cos']
FEAT_DEM = ['lag_week', 'rec24', 'rec168'] + WX + CYC + ['day_type']
BLOCKS = {1: (1, 24), 2: (25, 48), 3: (49, 72), 7: (145, 168), 12: (265, 288)}
LAGW = {1: 168, 2: 168, 3: 168, 7: 168, 12: 336}
GAS_FEATS = ['real_demand_land', 'renew_gen_total_kr', 'hour', 'dow', 'month', 'doy', 'day_type']


def _conn():
    return sqlite3.connect(DB)


def _load_serve6():
    spec = importlib.util.spec_from_file_location('serve_solarwind_land', SERVE6)
    mod = importlib.util.module_from_spec(spec)
    sys.modules['serve_solarwind_land'] = mod
    spec.loader.exec_module(mod)
    return mod


# ── 실측 수요/타깃 시계열 (기후값 산출 안 함) ──
def load_actuals():
    pull = (['timestamp', 'real_demand_land', 'gen_gas_kr', 'net_load_kr',
             'renew_gen_total_kr', 'day_type'] + [f'{w}_{s}' for s in ST for w in WX])
    with _conn() as con:
        raw = pd.read_sql(f"SELECT {', '.join(pull)} FROM historical", con, parse_dates=['timestamp'])
    raw = raw.sort_values('timestamp')
    idx = pd.date_range(raw.timestamp.min(), raw.timestamp.max(), freq='h')
    d = raw.set_index('timestamp').reindex(idx)
    d.loc[d.real_demand_land == 0, 'real_demand_land'] = np.nan
    d['real_demand_land'] = d['real_demand_land'].interpolate('time')
    d['day_type'] = d['day_type'].ffill().bfill()
    d.index.name = 'timestamp'
    return d


# ── 스크래치 forecast(=해당 base 슬라이스) 기상 → 수요용 5지점평균 (기후값 폴백 없음) ──
def fh_demand_weather(con, targets: pd.DatetimeIndex):
    """스크래치 `forecast`(그 base 의 forecast_horizon 행만 담김)에서 temp_c/solar_rad/wind_spd
    5지점평균.  ≤4h 시간보간(외삽 금지)만 허용, 기후값 폴백 없음.  반환 (df, valid_mask)."""
    fcols = [f'{FORE_PREFIX[w]}_{s}' for s in ST for w in WX]
    ext = pd.date_range(targets.min() - pd.Timedelta(hours=3),
                        targets.max() + pd.Timedelta(hours=3), freq='h')
    sel = ', '.join(f'"{c}"' for c in ['timestamp'] + fcols)
    fc = pd.read_sql(
        f'SELECT {sel} FROM forecast WHERE timestamp BETWEEN ? AND ? ORDER BY timestamp',
        con, params=(_S(ext[0]), _S(ext[-1])), parse_dates=['timestamp']).set_index('timestamp')
    fc = fc.apply(pd.to_numeric, errors='coerce').reindex(ext)
    out = pd.DataFrame(index=targets)
    for w in WX:
        cols = [f'{FORE_PREFIX[w]}_{s}' for s in ST]
        fmean = fc[cols].mean(axis=1) if len(fc.columns) else pd.Series(np.nan, index=ext)
        fmean = fmean.interpolate(method='time', limit=3, limit_area='inside').reindex(targets)
        out[w] = fmean.values
    valid = out.notna().all(axis=1)        # 기후값 금지 — 예보 없는 시각은 제외
    return out, valid


def _S(t):
    return pd.Timestamp(t).strftime('%Y-%m-%d %H:%M:%S')


# ── 수요 예측 (5-A2 D{n}) — build_chained_dataset.predict_demand 의 기상만 교체 ──
def predict_demand(con, d_act, dem_model, O, n):
    h0, h1 = BLOCKS[n]; H = np.arange(h0, h1 + 1); lagw = LAGW[n]
    targets = pd.DatetimeIndex([O + pd.Timedelta(hours=int(h)) for h in H])
    dem = d_act['real_demand_land']
    lag_week = dem.reindex(targets - pd.Timedelta(hours=lagw)).values
    rec24 = float(dem.loc[O - pd.Timedelta(hours=23):O].mean())
    rec168 = float(dem.loc[O - pd.Timedelta(hours=167):O].mean())
    wx, valid = fh_demand_weather(con, targets)
    df = pd.DataFrame(index=targets)
    df['lag_week'] = lag_week; df['rec24'] = rec24; df['rec168'] = rec168
    for w in WX:
        df[w] = wx[w].values
    hr = targets.hour; dw = targets.dayofweek; mo = targets.month
    df['hour_sin'] = np.sin(2*np.pi*hr/24); df['hour_cos'] = np.cos(2*np.pi*hr/24)
    df['dow_sin'] = np.sin(2*np.pi*dw/7); df['dow_cos'] = np.cos(2*np.pi*dw/7)
    df['month_sin'] = np.sin(2*np.pi*mo/12); df['month_cos'] = np.cos(2*np.pi*mo/12)
    dt = d_act['day_type'].reindex(targets).values
    df['day_type'] = pd.Categorical(dt, categories=DTCATS)
    # lag_week NaN(과거 부족) 또는 기상 invalid → 그 시각 드롭
    ok = valid.values & ~np.isnan(lag_week)
    pred = np.full(len(targets), np.nan)
    if ok.any():
        pred[ok] = dem_model.predict(df.loc[ok, FEAT_DEM])
    return targets, pred, dt, ok


# ── 스크래치 DB: historical 1회 복사 + base별 forecast 교체 ──
def build_scratch(scratch_path):
    with _conn() as con:
        hist = pd.read_sql('SELECT * FROM historical', con)
    sc = sqlite3.connect(scratch_path)
    hist.to_sql('historical', sc, if_exists='replace', index=False)
    sc.execute('CREATE INDEX IF NOT EXISTS ix_h ON historical(timestamp)')
    sc.commit()
    return sc


def set_scratch_forecast(sc, base):
    with _conn() as con:
        f = pd.read_sql('SELECT * FROM forecast_horizon WHERE base=? ORDER BY timestamp',
                        con, params=(base,))
    f = f.drop(columns=[c for c in ('base', 'horizon_d') if c in f.columns])
    f.to_sql('forecast', sc, if_exists='replace', index=False)
    sc.commit()


def _lng_cap_for(idx, lng):
    ym = idx.to_period('M')
    full = pd.period_range(min(ym.min(), lng.index.min()), max(ym.max(), lng.index.max()), freq='M')
    s = lng.reindex(full).ffill().bfill()
    return ym.map(s).astype(float).values


def _lng_cap_series():
    cap = pd.read_csv(CAP_CSV, encoding='euc-kr').rename(
        columns={'기간': 'period', '지역': 'region', 'LNG': 'LNG_cap'})
    cap = cap[cap['region'] == '합계'].copy()
    cap['ym'] = pd.to_datetime(cap['period'], format='%b-%y').dt.to_period('M')
    cap['LNG_cap'] = pd.to_numeric(cap['LNG_cap'], errors='coerce')
    return cap[['ym', 'LNG_cap']].dropna().sort_values('ym').set_index('ym')['LNG_cap']


def build(horizons, limit=None):
    d_act = load_actuals()
    serve6 = _load_serve6()
    A6 = serve6.load_assets()
    dem_models = {n: lgb.Booster(model_file=os.path.join(DEM_MODELS, f'lgbm_land_demand_D{n}.txt'))
                  for n in horizons}
    gas_booster = lgb.Booster(model_file=GAS_MODEL)
    calib_j = json.load(open(CALIB_JSON, encoding='utf-8'))
    bias_calib = float(calib_j['bias_calib']); conv = float(calib_j['conv_ton_per_mwh'])
    lng = _lng_cap_series()

    with _conn() as con:
        bases = [r[0] for r in con.execute(
            'SELECT DISTINCT base FROM forecast_horizon ORDER BY base').fetchall()]
    if limit:
        bases = bases[::max(1, len(bases)//limit)][:limit]

    scratch_path = os.path.join(tempfile.gettempdir(), 'horizon_bt_scratch.db')
    sc = build_scratch(scratch_path)
    gas = d_act['gen_gas_kr']; nlk = d_act['net_load_kr']; rgt = d_act['renew_gen_total_kr']
    rdl = d_act['real_demand_land']

    rows = []; t0 = time.time()
    for bi, base in enumerate(bases, 1):
        O = pd.Timestamp(base).normalize() + pd.Timedelta(hours=23)
        set_scratch_forecast(sc, base)
        for n in horizons:
            try:
                tg, dem_pred, dt, ok = predict_demand(sc, d_act, dem_models[n], O, n)
                if not ok.any():
                    continue
                out6, *_ = serve6._predict_day(sc, O.normalize(), n, A6)
                mr = pd.Series(out6[serve6.OUT['mr']].values,
                               index=pd.DatetimeIndex(out6['timestamp'])).reindex(tg).values
                # 마스크: 기상 유효(ok) & 신재생 산출 존재
                m = ok & ~pd.isna(mr) & ~np.isnan(dem_pred)
                if not m.any():
                    continue
                tg2 = tg[m]; dem2 = dem_pred[m]; mr2 = mr[m].astype(float); dt2 = np.asarray(dt)[m]
                # 가스(7-A2)
                gf = pd.DataFrame(index=tg2)
                gf['real_demand_land'] = dem2; gf['renew_gen_total_kr'] = mr2
                gf['hour'] = tg2.hour; gf['dow'] = tg2.dayofweek
                gf['month'] = tg2.month; gf['doy'] = tg2.dayofyear
                gf['day_type'] = pd.Categorical(dt2, categories=DTCATS)
                util = gas_booster.predict(gf[GAS_FEATS])
                cap = _lng_cap_for(tg2, lng)
                gen_raw = util * cap
                gen = gen_raw * bias_calib
                rows.append(pd.DataFrame({
                    'base': base, 'timestamp': tg2, 'horizon': n,
                    'est_demand': dem2, 'est_renew': mr2,
                    'est_net_load': dem2 - mr2,
                    'est_gas_gen_raw': gen_raw, 'est_gas_gen': gen, 'est_gas_ton': gen * conv,
                    'real_demand_land': rdl.reindex(tg2).values,
                    'renew_gen_total_kr': rgt.reindex(tg2).values,
                    'net_load_kr': nlk.reindex(tg2).values,
                    'gen_gas_kr': gas.reindex(tg2).values,
                    'hour': tg2.hour, 'dow': tg2.dayofweek, 'month': tg2.month, 'doy': tg2.dayofyear,
                    'day_type': dt2}))
            except Exception as e:
                if limit:
                    print(f'  [skip] base {base[:10]} D+{n}: {str(e)[:80]}')
                continue
        if bi % 20 == 0 or bi == len(bases):
            print(f'  base {bi}/{len(bases)} ({base[:10]})  누적 {len(rows)} blocks  {time.time()-t0:.0f}s')
    sc.close()
    res = pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()
    return res


if __name__ == '__main__':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument('--limit', type=int, default=None, help='base 표본수(스모크테스트)')
    ap.add_argument('--horizons', default='1,2,3,7,12')
    ap.add_argument('--out', default=os.path.join(HERE, 'horizon_backtest.parquet'))
    a = ap.parse_args()
    hz = [int(x) for x in a.horizons.split(',')]
    res = build(hz, limit=a.limit)
    if not len(res):
        print('결과 없음'); sys.exit(1)
    print(f'\n총 {len(res)}행  지평별:', res.groupby('horizon').size().to_dict())
    print('base 수:', res.base.nunique(), ' 기간:', res.timestamp.min(), '~', res.timestamp.max())
    # 입력 정직성: 체인 입력 vs 실측 bias
    for n, g in res.groupby('horizon'):
        gg = g.dropna(subset=['real_demand_land'])
        dmape = float(np.mean(np.abs(gg.real_demand_land - gg.est_demand) / gg.real_demand_land) * 100)
        db = (gg.est_demand - gg.real_demand_land).mean()
        rb = (gg.est_renew - gg.renew_gen_total_kr).mean()
        ev = g.dropna(subset=['gen_gas_kr']); ev = ev[ev.gen_gas_kr > 0]
        gmape = float(np.mean(np.abs(ev.gen_gas_kr - ev.est_gas_gen) / ev.gen_gas_kr) * 100) if len(ev) else float('nan')
        gbias = float(np.mean((ev.est_gas_gen - ev.gen_gas_kr) / ev.gen_gas_kr) * 100) if len(ev) else float('nan')
        print(f'  D+{n:>2}: 수요 MAPE {dmape:.2f}% bias {db:+.0f}MW | 신재생 bias {rb:+.0f}MW | '
              f'가스 MAPE {gmape:.2f}% bias {gbias:+.1f}% (n={len(ev)})')
    if not a.limit:
        res.to_parquet(a.out); print('saved', a.out)
    else:
        print('(스모크 — 저장 생략)')

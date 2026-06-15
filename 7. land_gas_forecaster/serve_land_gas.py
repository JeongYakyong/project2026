# -*- coding: utf-8 -*-
"""7단계 서빙 v2 — 5-A식 가스 자기회귀 다지평 forecaster (체인 5·6 입력 + 가스 자기과거).

v2(2026-06-14, G-17/G-18): 구 7-A2(동시점 util×cap)에서 전환.  가스도 자기상관(lag168 0.78)이
강하고 가용성이 수요와 동일(누수 아님) → 수요(5-A)처럼 origin 의 가스 과거(lag·최근레벨)를 참고해
T+h 를 직접 예측.

피처(MIXED, 공선성·covariate shift 검토 후 확정):
  real_demand_land(MW, 5단계 est_demand_land) · renew_util(6단계 est_market_renew_land/(태양광+풍력 용량))
  · gas_lag168(h>168 NaN)/gas_lag24(h<=24)/gas_rec24/gas_rec168(historical 실측 가스)
  · h · hour · dow · doy.   (net_load·cap_btmppa·month·day_type 제외 — 중복/covariate shift.)
타깃 = 가스 MW(÷LNG_cap 미적용: gas 는 정상, LNG_cap 은 100% 외삽이라 비율화가 역효과).
손실 = 낮(09-15h) 과대 비대칭(α4, 학습).  보정 = 낮/밤 분리 지평별(전역 보정이 낮교정 푸는 것 방지).
블렌딩(Stage5, 2026-06-15) = 장지평일수록 가스 기후값(우리 historical doy±7×시각×요일유형 평년) 쪽으로
  w(h) 가중평균: final=(1-w)·예보보정 + w·기후값.  w=0(D+1~4)→0.5(D+15).  정직 백테스트 MAPE
  최소·계절 균형 검증(Option A 단조).  기후값 절대금지 하드규칙은 해제됨(기후값=우리가 만든 평년 모델).
명제용 드라이버-only 7-A 와 구 7-A2(util) 는 보존.

출력(forecast, _land): est_gas_gen_land(MW), est_gas_sendout_ton_land(TON/h, ×0.1521).
API: predict_gas_to_db(origin, days_ahead) / backfill_gas_to_db(start, end). CLI 동일.
"""
from __future__ import annotations
import os, sys, sqlite3, json
import numpy as np, pandas as pd, lightgbm as lgb

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, '..'))
DB   = os.path.join(ROOT, '1. data_fetcher_and_db', 'data', 'input_data_land.db')
CAP_CSV = os.path.join(ROOT, '1. data_fetcher_and_db', 'second_dataset', 'kr_elec_capa.csv')
MODEL = os.path.join(HERE, 'model', 'lgbm_land_gas_v2.txt')
META  = os.path.join(HERE, 'model', 'model_meta_gas_v2.json')
CALIB_JSON = os.path.join(HERE, 'model', 'gas_serving_calib.json')

DEMAND_COL = 'est_demand_land'           # 5단계
RENEW_COL  = 'est_market_renew_land'     # 6단계 (시장 solar+wind)
OUT_GEN = 'est_gas_gen_land'
OUT_TON = 'est_gas_sendout_ton_land'
FEATS = ['real_demand_land', 'renew_util', 'gas_lag168', 'gas_lag24', 'gas_rec24', 'gas_rec168',
         'h', 'hour', 'dow', 'doy']
_OFFSET = float(json.load(open(META, encoding='utf-8'))['init_score'])
HZ_FIT = [1, 2, 3, 7, 12]


def _conn():
    return sqlite3.connect(DB)


def _load_calib():
    c = json.load(open(CALIB_JSON, encoding='utf-8'))
    dp = c['bias_calib_by_horizon_daypart']
    day = {int(k): float(v['day']) for k, v in dp.items()}
    night = {int(k): float(v['night']) for k, v in dp.items()}
    w = {int(k): float(v) for k, v in c.get('blend_weight_by_horizon', {}).items()}
    clim = c.get('climatology', {'window_days': 7, 'years': '2022-2024'})
    return day, night, float(c['conv_ton_per_mwh']), w, clim


_CLIM = {}
def load_gas_climatology(years='2022-2024', window=7):
    """가스 기후값(우리 historical 실측): doy±window 슬라이딩 × 시각 × 요일유형 평균. 폴백=시각만."""
    key = (years, window)
    if key in _CLIM:
        return _CLIM[key]
    y0, y1 = [int(x) for x in str(years).split('-')]
    with _conn() as con:
        d = pd.read_sql(f"SELECT timestamp, gen_gas_kr, day_type FROM historical "
                        f"WHERE timestamp>='{y0}-01-01' AND timestamp<'{y1+1}-01-01'", con, parse_dates=['timestamp'])
    d = d[d.gen_gas_kr > 0].copy()
    d['doy'] = d.timestamp.dt.dayofyear.clip(1, 366); d['hour'] = d.timestamp.dt.hour

    def circ(arr):
        p = np.concatenate([arr[-window:], arr, arr[:window]]); return np.convolve(p, np.ones(2*window+1), 'valid')
    lut, fb = {}, {}
    for (hr, dt), g in d.groupby(['hour', 'day_type']):
        a = g.groupby('doy').gen_gas_kr.agg(['sum', 'count']).reindex(range(1, 367), fill_value=0)
        S, C = circ(a['sum'].values), circ(a['count'].values); lut[(hr, dt)] = np.where(C > 0, S/np.maximum(C, 1), np.nan)
    for hr, g in d.groupby('hour'):
        a = g.groupby('doy').gen_gas_kr.agg(['sum', 'count']).reindex(range(1, 367), fill_value=0)
        S, C = circ(a['sum'].values), circ(a['count'].values); fb[hr] = np.where(C > 0, S/np.maximum(C, 1), np.nan)
    _CLIM[key] = (lut, fb)
    return lut, fb


def _clim_vals(idx, day_type, lut, fb):
    doy = np.clip(idx.dayofyear.values, 1, 366); hr = idx.hour.values; out = np.full(len(idx), np.nan)
    for i in range(len(idx)):
        v = lut.get((hr[i], day_type[i])); x = v[doy[i]-1] if v is not None else np.nan
        if not np.isfinite(x):
            x = fb[hr[i]][doy[i]-1]
        out[i] = x
    return out


def _blend_w(dayahead, wd):
    if not wd:
        return np.zeros(len(dayahead))
    hs = np.array(sorted(wd)); return np.interp(dayahead, hs, [wd[h] for h in hs])


def _calib_vec(dayahead, hour, day_c, night_c):
    """행별 보정 — 낮(09-15h)/밤 분리 + 적합지평 사이 선형보간."""
    hs = np.array(sorted(day_c))
    dv = np.interp(dayahead, hs, [day_c[h] for h in hs])
    nv = np.interp(dayahead, hs, [night_c[h] for h in hs])
    is_day = (hour >= 9) & (hour <= 15)
    return np.where(is_day, dv, nv)


def _renew_cap(idx: pd.DatetimeIndex) -> np.ndarray:
    """월별 태양광+풍력 용량(kr_elec_capa.csv 합계)."""
    cap = pd.read_csv(CAP_CSV, encoding='euc-kr', header=None, skiprows=2,
                      names=['period', 'region', 'LNG', 'solar', 'wind', 'PPA'])
    cap = cap[cap.region.astype(str).str.strip() == '합계'].copy()
    cap['ym'] = pd.to_datetime(cap.period, format='%b-%y').dt.to_period('M')
    for c in ('solar', 'wind'):
        cap[c] = pd.to_numeric(cap[c], errors='coerce')
    s = cap.dropna(subset=['solar', 'wind']).set_index('ym')
    rc = (s['solar'] + s['wind']).sort_index()
    ym = idx.to_period('M')
    full = pd.period_range(min(ym.min(), rc.index.min()), max(ym.max(), rc.index.max()), freq='M')
    return ym.map(rc.reindex(full).ffill().bfill()).astype(float).values


def load_gas_series() -> pd.Series:
    """historical 가스 발전 연속 시계열(0/결측 시간보간) — 자기회귀 lag·rec 용."""
    with _conn() as con:
        d = pd.read_sql('SELECT timestamp, gen_gas_kr FROM historical', con, parse_dates=['timestamp'])
    d = d.sort_values('timestamp')
    idx = pd.date_range(d.timestamp.min(), d.timestamp.max(), freq='h')
    s = d.set_index('timestamp')['gen_gas_kr'].reindex(idx).replace(0, np.nan).interpolate('time', limit=6)
    s.index.name = 'timestamp'
    return s


def _read_chain(con, t0, t1):
    cols = [c[1] for c in con.execute('PRAGMA table_info(forecast)')]
    dtsel = ', day_type' if 'day_type' in cols else ''
    df = pd.read_sql(
        f'SELECT timestamp, "{DEMAND_COL}", "{RENEW_COL}"{dtsel} FROM forecast '
        f'WHERE timestamp BETWEEN ? AND ? ORDER BY timestamp',
        con, params=(t0, t1), parse_dates=['timestamp']).set_index('timestamp')
    return df


def predict_gas_to_db(origin_date: str | None = None, days_ahead: int = 7,
                      write: bool = True, verbose: bool = True) -> pd.DataFrame:
    day_c, night_c, conv, w_dict, clim_spec = _load_calib()
    clim_lut, clim_fb = load_gas_climatology(clim_spec.get('years', '2022-2024'), clim_spec.get('window_days', 7))
    booster = lgb.Booster(model_file=MODEL)
    gas = load_gas_series()

    if origin_date is None:
        O = gas.dropna().index.max().normalize() + pd.Timedelta(hours=23)
        if O > gas.dropna().index.max():
            O -= pd.Timedelta(days=1)
    else:
        O = pd.Timestamp(origin_date).normalize() + pd.Timedelta(hours=23)
    rec24 = float(gas.loc[O - pd.Timedelta(hours=23):O].mean())
    rec168 = float(gas.loc[O - pd.Timedelta(hours=167):O].mean())
    if not np.isfinite(rec24) or not np.isfinite(rec168):
        raise ValueError(f'원점 가스 최근레벨 NaN (O={O}) — 실측 적재 확인')

    H = np.arange(1, days_ahead * 24 + 1)
    idx = pd.DatetimeIndex([O + pd.Timedelta(hours=int(h)) for h in H])
    t0, t1 = idx.min().strftime('%Y-%m-%d %H:%M:%S'), idx.max().strftime('%Y-%m-%d %H:%M:%S')
    with _conn() as con:
        ci = _read_chain(con, t0, t1)
    dem = pd.to_numeric(ci[DEMAND_COL], errors='coerce').reindex(idx)
    ren = pd.to_numeric(ci[RENEW_COL], errors='coerce').reindex(idx)
    if dem.isna().all():
        raise ValueError(f'체인 입력 없음 ({t0}~{t1}) — 5·6단계 서빙을 먼저 실행하세요.')

    df = pd.DataFrame(index=idx)
    df['real_demand_land'] = dem.values
    df['renew_util'] = ren.values / _renew_cap(idx)
    df['gas_lag168'] = np.where(H <= 168, gas.reindex(idx - pd.Timedelta(hours=168)).values, np.nan)
    df['gas_lag24'] = np.where(H <= 24, gas.reindex(idx - pd.Timedelta(hours=24)).values, np.nan)
    df['gas_rec24'] = rec24; df['gas_rec168'] = rec168
    df['h'] = H; df['hour'] = idx.hour; df['dow'] = idx.dayofweek; df['doy'] = idx.dayofyear

    ok = df['real_demand_land'].notna().values & df['renew_util'].notna().values
    pred = np.full(len(idx), np.nan)
    pred[ok] = booster.predict(df.loc[ok, FEATS]) + _OFFSET
    dayahead = ((idx.normalize() - O.normalize()).days).astype(float)
    cvec = _calib_vec(dayahead, idx.hour.values, day_c, night_c)
    gen_cal = pred * cvec
    # 블렌딩: 장지평일수록 가스 기후값(평년) 쪽으로 (w(h), 기후값 가용 시각만)
    if 'day_type' in ci.columns:
        dtv = ci['day_type'].reindex(idx).values
        dtv = np.where(pd.isna(dtv), np.where(idx.dayofweek >= 5, 'weekend', 'weekday'), dtv)
    else:
        dtv = np.where(idx.dayofweek >= 5, 'weekend', 'weekday')
    clim = _clim_vals(idx, dtv, clim_lut, clim_fb)
    wv = _blend_w(dayahead, w_dict)
    gen = gen_cal.copy()
    use = np.isfinite(clim) & np.isfinite(gen_cal)
    gen[use] = (1 - wv[use]) * gen_cal[use] + wv[use] * clim[use]
    ton = gen * conv

    out = pd.DataFrame({'timestamp': idx.strftime('%Y-%m-%d %H:%M:%S'),
                        OUT_GEN: np.round(gen, 1), OUT_TON: np.round(ton, 2)})
    out = out[np.isfinite(gen)]
    if write and len(out):
        with _conn() as con:
            cols = [c[1] for c in con.execute('PRAGMA table_info(forecast)')]
            for c in (OUT_GEN, OUT_TON):
                if c not in cols:
                    con.execute(f'ALTER TABLE forecast ADD COLUMN "{c}" REAL')
            con.executemany(
                f'INSERT INTO forecast ("timestamp","{OUT_GEN}","{OUT_TON}") VALUES (?,?,?) '
                f'ON CONFLICT("timestamp") DO UPDATE SET "{OUT_GEN}"=excluded."{OUT_GEN}", '
                f'"{OUT_TON}"=excluded."{OUT_TON}"',
                [(r.timestamp, float(r[OUT_GEN]), float(r[OUT_TON])) for _, r in out.iterrows()])
            con.commit()
    if verbose:
        gm = float(np.nanmean(gen))
        print(f'origin={O:%Y-%m-%d} → D+1..D+{days_ahead}  {len(out)}h  '
              f'gas {gm:.0f}MW(avg)  송출 {np.nansum(ton):.0f}TON(합)  calib=낮/밤 분리·지평보간')
        print(out.head(12).to_string(index=False))
    return out


def backfill_gas_to_db(start: str, end: str, days_ahead: int = 1,
                       write: bool = True, verbose: bool = True) -> pd.DataFrame:
    """과거 origin들에 대해 예측 후 실측 gen_gas_kr와 MAPE(체인 입력 존재 구간만)."""
    with _conn() as con:
        gas = pd.read_sql('SELECT timestamp, gen_gas_kr FROM historical', con,
                          parse_dates=['timestamp']).set_index('timestamp')['gen_gas_kr']
    origins = pd.date_range(pd.Timestamp(start).normalize(), pd.Timestamp(end).normalize(), freq='D')
    rows = []
    for O in origins:
        try:
            o = predict_gas_to_db(O.strftime('%Y-%m-%d'), days_ahead, write=write, verbose=False)
        except Exception:
            continue
        o = o.copy(); o['actual'] = gas.reindex(pd.DatetimeIndex(o['timestamp'])).values
        rows.append(o)
    if not rows:
        print('예측 가능한 origin 없음'); return pd.DataFrame()
    res = pd.concat(rows, ignore_index=True)
    if verbose:
        m = res.dropna(subset=['actual']); m = m[m.actual > 0]
        mape = float(np.mean(np.abs(m.actual - m[OUT_GEN]) / m.actual) * 100)
        bias = float(np.mean((m[OUT_GEN] - m.actual) / m.actual) * 100)
        hr = pd.DatetimeIndex(m.timestamp).hour
        dm = m[(hr >= 9) & (hr <= 15)]
        dmape = float(np.mean(np.abs(dm.actual - dm[OUT_GEN]) / dm.actual) * 100)
        print(f'[backfill] {start}~{end}  예측 {len(res)}h  실측대조 {len(m)}h  '
              f'발전량 MAPE {mape:.2f}%  bias {bias:+.1f}%  낮(09-15) MAPE {dmape:.2f}%')
    return res


if __name__ == '__main__':
    import argparse
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass
    p = argparse.ArgumentParser(description='7단계 v2 가스 서빙 (자기회귀 다지평 + 체인 5·6)')
    sub = p.add_subparsers(dest='cmd', required=True)
    pp = sub.add_parser('predict'); pp.add_argument('date', nargs='?', default=None)
    pp.add_argument('--days', type=int, default=7); pp.add_argument('--no-write', action='store_true')
    bf = sub.add_parser('backfill'); bf.add_argument('start'); bf.add_argument('end')
    bf.add_argument('--days', type=int, default=1); bf.add_argument('--no-write', action='store_true')
    a = p.parse_args()
    if a.cmd == 'predict':
        predict_gas_to_db(a.date, a.days, write=not a.no_write)
    else:
        backfill_gas_to_db(a.start, a.end, a.days, write=not a.no_write)

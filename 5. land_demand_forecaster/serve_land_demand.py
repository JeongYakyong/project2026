"""5-B. 전국 수요 D+1~D+15 서빙 — DB 전용 파이프라인 (직접 다지평 LGBM, lag168/336/504 정직가드).

================================================================================
무엇을 하나
================================================================================
input_data_land.db 한 곳에서 읽고 쓴다.
  - 입력 : historical (실측 real_demand_land + 5지점 기상),
           forecast   (기상예보 5지점, day_type)
  - 모델 : model/models/lgbm_land_demand_direct.txt  (5-A 직접 다지평, h=1..168)
  - 출력 : forecast.est_demand_land  ← origin 다음 D+1~D+n 수요 예측 UPSERT

설계(5-A 학습과 동일)
================================================================================
  origin O = 지정일 23:00 (마지막 완전한 하루의 끝). 타깃 = O+1h .. O+(days*24)h.
  피처 = h, lag168(전 지평 실측 가용), lag24(h<=24만), rec24/rec168(원점 최근레벨),
         기상3(기온/일사/풍속 5지점평균), 달력(hour/dow/month sin·cos), day_type.
  기상은 forecast 예보 우선, 없으면 (월,시) 기후값 폴백.
    → forecast 테이블이 보통 ~D+1 까지만 예보 보유(발행 한계). D+2~ 는 기후값.
    → 정직성: D+1 은 예보(상한쪽), 원거리는 기후값(하한쪽). REPORT_5-A 의 괄호와 동일.

  forecast 매핑:  temp_c<-temp_{st}, solar_rad<-radiation_{st}, wind_spd<-wind_spd_10m_{st}

공개 API
================================================================================
    predict_demand_to_db(origin_date, days_ahead=7, write=True)  # 핵심
    backfill_demand_to_db(start, end, days_ahead=7)              # 과거 구간 채움(평가용)
"""
from __future__ import annotations
import os, sqlite3, json
import numpy as np, pandas as pd
import lightgbm as lgb

HERE   = os.path.dirname(os.path.abspath(__file__))
DB_PATH= os.path.normpath(os.path.join(
    HERE, '..', '1. data_fetcher_and_db', 'data', 'input_data_land.db'))
# v2 (2026-06-14): 지점선택 기상 + 구름(서산영광) + cap_btmppa + 낮 비대칭 손실.
MODEL  = os.path.join(HERE, 'model', 'models', 'lgbm_land_demand_v2.txt')
META   = os.path.join(HERE, 'model', 'models', 'model_meta_v2.json')
CAP_CSV= os.path.normpath(os.path.join(
    HERE, '..', '1. data_fetcher_and_db', 'second_dataset', 'kr_elec_capa.csv'))

STATIONS = ['daegwallyeong', 'wonju', 'seosan', 'pohang', 'yeonggwang']
SOLAR_SEL = ['seosan', 'yeonggwang']        # 태양광·구름 집중지(충남·전남)
WIND_SEL  = ['daegwallyeong', 'pohang']     # 풍력 집중지(강원·경북)
OUT_COL  = 'est_demand_land'
# 기상 피처 -> 평균 대상 지점 (용량집중지 선택, v2)
AGG = {'temp_c': STATIONS, 'solar_rad': SOLAR_SEL, 'wind_spd': WIND_SEL,
       'total_cloud': SOLAR_SEL, 'midlow_cloud': SOLAR_SEL}
WEATHER_FEATS = list(AGG)                    # forecast/기후값 폴백이 필요한 기상 5종
# 기상 피처 -> forecast 테이블 컬럼 접두사 / historical 컬럼 접두사
FORE_PREFIX = {'temp_c': 'temp', 'solar_rad': 'radiation', 'wind_spd': 'wind_spd_10m',
               'total_cloud': 'total_cloud', 'midlow_cloud': 'midlow_cloud'}
HIST_PREFIX = {'temp_c': 'temp_c', 'solar_rad': 'solar_rad', 'wind_spd': 'wind_spd',
               'total_cloud': 'total_cloud', 'midlow_cloud': 'midlow_cloud'}
FEAT = ['h', 'lag168', 'lag336', 'lag504', 'lag24', 'rec24', 'rec168', 'temp_c', 'solar_rad', 'wind_spd',
        'hour_sin', 'hour_cos', 'dow_sin', 'dow_cos', 'month_sin', 'month_cos', 'day_type',
        'total_cloud', 'midlow_cloud', 'cap_btmppa']   # lag336/504=장지평 주간앵커(D+15), BASEFEAT와 동일순
DAYTYPE_CATS = ['holiday', 'weekday', 'weekend']   # 5-A astype('category') 와 동일 정렬
_OFFSET = float(json.load(open(META, encoding='utf-8'))['init_score'])  # 커스텀목적함수 init_score 가산


# ── cap_btmppa: 월별 PPA 용량(kr_elec_capa.csv 합계) — 결정값(예보 불필요) ──
def _ppa_series() -> pd.Series:
    cap = pd.read_csv(CAP_CSV, encoding='euc-kr', header=None, skiprows=2,
                      names=['period', 'region', 'LNG', 'solar', 'wind', 'PPA'])
    cap = cap[cap.region.astype(str).str.strip() == '합계'].copy()
    cap['ym'] = pd.to_datetime(cap.period, format='%b-%y').dt.to_period('M')
    cap['PPA'] = pd.to_numeric(cap.PPA, errors='coerce')
    return cap.dropna(subset=['PPA']).set_index('ym')['PPA'].sort_index()


def _cap_btmppa(idx: pd.DatetimeIndex) -> np.ndarray:
    ppa = _ppa_series(); ym = idx.to_period('M')
    full = pd.period_range(min(ym.min(), ppa.index.min()), max(ym.max(), ppa.index.max()), freq='M')
    return ym.map(ppa.reindex(full).ffill().bfill()).astype(float).values


def _conn():
    return sqlite3.connect(DB_PATH)


# =============================================================================
# 1. 실측 수요 시계열 (0/결측 시간보간) — 연속 시간축
# =============================================================================
def load_demand_series() -> pd.Series:
    with _conn() as con:
        d = pd.read_sql('SELECT timestamp, real_demand_land FROM historical',
                        con, parse_dates=['timestamp'])
    d = d.sort_values('timestamp')
    idx = pd.date_range(d['timestamp'].min(), d['timestamp'].max(), freq='h')
    s = d.set_index('timestamp')['real_demand_land'].reindex(idx)
    s = s.replace(0, np.nan).interpolate(method='time')
    s.index.name = 'timestamp'
    return s


# =============================================================================
# 2. (월,시) 기후값 — 먼 지평 기상 폴백
# =============================================================================
def build_climatology() -> dict[str, pd.Series]:
    cols = {f'{HIST_PREFIX[w]}_{st}' for w in WEATHER_FEATS for st in AGG[w]}
    sel = ['timestamp'] + sorted(cols)
    with _conn() as con:
        df = pd.read_sql(f"SELECT {', '.join(sel)} FROM historical",
                         con, parse_dates=['timestamp'])
    for w in WEATHER_FEATS:
        df[w] = df[[f'{HIST_PREFIX[w]}_{st}' for st in AGG[w]]].apply(
            pd.to_numeric, errors='coerce').mean(axis=1)
    df['month'] = df.timestamp.dt.month; df['hour'] = df.timestamp.dt.hour
    return {w: df.groupby(['month', 'hour'])[w].mean() for w in WEATHER_FEATS}


# =============================================================================
# 3. 타깃 기상 조립 (forecast 예보 우선 + 기후값 폴백) + day_type
# =============================================================================
def load_target_weather(targets: pd.DatetimeIndex, clim: dict) -> pd.DataFrame:
    tmin = targets.min().strftime('%Y-%m-%d %H:%M:%S')
    tmax = targets.max().strftime('%Y-%m-%d %H:%M:%S')
    fcols = (['timestamp', 'day_type'] +
             sorted({f'{FORE_PREFIX[w]}_{st}' for w in WEATHER_FEATS for st in AGG[w]}))
    with _conn() as con:
        fc = pd.read_sql(
            f"SELECT {', '.join(f'\"{c}\"' for c in fcols)} FROM forecast "
            f"WHERE timestamp BETWEEN ? AND ? ORDER BY timestamp",
            con, params=(tmin, tmax), parse_dates=['timestamp'])
    fc = fc.set_index('timestamp')
    out = pd.DataFrame(index=targets)
    for w in WEATHER_FEATS:
        cols = [f'{FORE_PREFIX[w]}_{st}' for st in AGG[w]]
        have = fc[cols].apply(pd.to_numeric, errors='coerce') if len(fc) else pd.DataFrame()
        fmean = have.mean(axis=1).reindex(targets) if len(have) else pd.Series(np.nan, index=targets)
        # D+5.5(135h) 이후 forecast 는 3h 행만 존재(KIMG 1h 해상도 한계) -- 그 사이
        # 구멍은 양옆 실예보의 시간 보간이 기후값보다 정확하므로 먼저 메운다.
        # 신뢰성 한계: limit=3 (연속 결측 3h = 앵커 간격 4h 까지만 보간, 그 이상
        # 벌어진 구멍은 보간하지 않음).  limit_area='inside' 로 예보 범위 밖 외삽
        # 금지 -> 진짜 예보가 없는 지평만 기후값 폴백으로 남는다.
        fmean = fmean.interpolate(method='time', limit=3, limit_area='inside')
        cl = pd.Series([clim[w].get((t.month, t.hour), np.nan) for t in targets], index=targets)
        out[w] = fmean.where(fmean.notna(), cl)
        out[w + '_src'] = np.where(fmean.notna(), 'forecast', 'climatology')
    # day_type: forecast 보유 우선, 없으면 dow 로 weekday/weekend 추정(공휴일은 예보범위 밖이면 미반영)
    dt = fc['day_type'].reindex(targets) if 'day_type' in fc else pd.Series(index=targets, dtype=object)
    dt = dt.where(dt.notna(),
                  pd.Series(np.where(targets.dayofweek >= 5, 'weekend', 'weekday'), index=targets))
    out['day_type'] = dt.values
    return out


# =============================================================================
# 4. 핵심 — origin 다음 D+1..D+n 직접 다지평 예측
# =============================================================================
def _resolve_origin(series: pd.Series, origin_date: str | None) -> pd.Timestamp:
    """origin = 지정일 23:00. 미지정시 '실측이 23:00까지 있는 마지막 하루'."""
    if origin_date is not None:
        O = pd.Timestamp(origin_date).normalize() + pd.Timedelta(hours=23)
    else:
        valid = series.dropna()
        last = valid.index.max()
        O = last.normalize() + pd.Timedelta(hours=23)
        if O > last:                      # 오늘이 아직 23:00 전 → 전날 23:00
            O = O - pd.Timedelta(days=1)
    return O


def predict_demand_to_db(origin_date: str | None = None, days_ahead: int = 7,
                         write: bool = True, verbose: bool = True) -> pd.DataFrame:
    if not (1 <= days_ahead <= 15):
        raise ValueError('days_ahead 는 1~15 (모델 학습 지평 1..360h)')
    series = load_demand_series()
    O = _resolve_origin(series, origin_date)

    # 원점 윈도우 [O-167, O] 실측 필요(lag168·rec168)
    win = series.loc[O - pd.Timedelta(hours=167): O]
    if len(win) < 168 or win.isna().any():
        raise ValueError(f'[history] 원점 윈도우({O-pd.Timedelta(hours=167)}~{O}) '
                         f'부족/NaN — 보유 {len(win)}행 (실측 적재 확인)')
    rec24  = float(series.loc[O - pd.Timedelta(hours=23): O].mean())
    rec168 = float(win.mean())

    H = np.arange(1, days_ahead * 24 + 1)
    targets = pd.DatetimeIndex([O + pd.Timedelta(hours=int(h)) for h in H])
    clim = build_climatology()
    wx = load_target_weather(targets, clim)

    df = pd.DataFrame(index=targets)
    df['h'] = H
    for k in (168, 336, 504):   # 주간앵커 — h<=k(타깃-k가 원점 이전, 실서빙 가용) 일 때만, 그 외 NaN
        df[f'lag{k}'] = np.where(H <= k, series.reindex(targets - pd.Timedelta(hours=k)).values, np.nan)
    df['lag24'] = np.where(H <= 24, series.reindex(targets - pd.Timedelta(hours=24)).values, np.nan)
    df['rec24'] = rec24; df['rec168'] = rec168
    for w in WEATHER_FEATS: df[w] = wx[w].values
    df['cap_btmppa'] = _cap_btmppa(targets)        # 월별 PPA 용량(결정값)
    hr = targets.hour.values; dw = targets.dayofweek.values; mo = targets.month.values
    df['hour_sin'] = np.sin(2*np.pi*hr/24); df['hour_cos'] = np.cos(2*np.pi*hr/24)
    df['dow_sin']  = np.sin(2*np.pi*dw/7);  df['dow_cos']  = np.cos(2*np.pi*dw/7)
    df['month_sin']= np.sin(2*np.pi*mo/12); df['month_cos']= np.cos(2*np.pi*mo/12)
    df['day_type'] = pd.Categorical(wx['day_type'].values, categories=DAYTYPE_CATS)

    booster = lgb.Booster(model_file=MODEL)
    # 커스텀 비대칭 목적함수 모델 → predict 는 init_score 를 안 더해주므로 _OFFSET 가산.
    df['est_demand_land'] = (booster.predict(df[FEAT]) + _OFFSET).round(1)
    df['dayahead'] = ((df['h'] - 1) // 24 + 1).astype(int)
    df['weather_src'] = wx['temp_c_src'].values
    out = df.reset_index().rename(columns={'index': 'timestamp'})
    out = out[['timestamp', 'h', 'dayahead', 'est_demand_land', 'weather_src', 'day_type']]

    if write:
        rows = [(t.strftime('%Y-%m-%d %H:%M:%S'), float(v))
                for t, v in zip(out['timestamp'], out['est_demand_land'])]
        with _conn() as con:
            cols = [c[1] for c in con.execute('PRAGMA table_info(forecast)')]
            if OUT_COL not in cols:
                con.execute(f'ALTER TABLE forecast ADD COLUMN "{OUT_COL}" REAL')
            con.executemany(
                f'INSERT INTO forecast ("timestamp","{OUT_COL}") VALUES (?,?) '
                f'ON CONFLICT("timestamp") DO UPDATE SET "{OUT_COL}"=excluded."{OUT_COL}"', rows)
            con.commit()
        if verbose:
            print(f'[DB] forecast.{OUT_COL} ← origin {O:%Y-%m-%d %H:%M} '
                  f'D+1..D+{days_ahead} ({len(rows)}행) UPSERT')

    if verbose:
        nfc = int((out.weather_src == 'forecast').sum())
        print(f'origin={O:%Y-%m-%d %H:%M}  기상: forecast {nfc}h / climatology {len(out)-nfc}h')
        print(out.head(24).to_string(index=False))
    return out


# =============================================================================
# 5. 백필/평가 — 과거 origin 들에 대해 예측 후 실측과 MAPE
# =============================================================================
def backfill_demand_to_db(start: str, end: str, days_ahead: int = 7,
                          write: bool = False, verbose: bool = True) -> pd.DataFrame:
    series = load_demand_series()
    origins = pd.date_range(pd.Timestamp(start).normalize() + pd.Timedelta(hours=23),
                            pd.Timestamp(end).normalize() + pd.Timedelta(hours=23), freq='D')
    allrows = []
    for O in origins:
        win = series.loc[O - pd.Timedelta(hours=167): O]
        if len(win) < 168 or win.isna().any():
            continue
        try:
            o = predict_demand_to_db(O.strftime('%Y-%m-%d'), days_ahead, write=write, verbose=False)
            o['actual'] = series.reindex(pd.DatetimeIndex(o['timestamp'])).values
            allrows.append(o)
        except Exception:
            continue
    if not allrows:
        print('예측 가능한 origin 없음'); return pd.DataFrame()
    res = pd.concat(allrows, ignore_index=True)
    if verbose:
        m = res.dropna(subset=['actual'])
        m = m[m.actual > 0]
        print(f'[backfill] origins {len(allrows)}  예측행 {len(res)}  실측대조 {len(m)}')
        for dn, g in m.groupby('dayahead'):
            mape = float(np.mean(np.abs(g.actual - g.est_demand_land) / g.actual) * 100)
            print(f'  D+{dn}: MAPE {mape:.2f}%  (n={len(g)})')
    return res


# =============================================================================
# 6. CLI
# =============================================================================
if __name__ == '__main__':
    import sys, argparse
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass
    p = argparse.ArgumentParser(description='전국 수요 D+1~D+7 서빙 (직접 다지평 LGBM)')
    sub = p.add_subparsers(dest='cmd', required=True)
    pp = sub.add_parser('predict', help='origin 다음 D+1..D+n 예측 → DB')
    pp.add_argument('date', nargs='?', default=None, help='origin 날짜 YYYY-MM-DD (생략시 최신)')
    pp.add_argument('--days', type=int, default=7, help='며칠 앞까지 (1~7, 기본 7)')
    pp.add_argument('--no-write', action='store_true')
    bf = sub.add_parser('backfill', help='과거 구간 예측·MAPE 평가')
    bf.add_argument('start'); bf.add_argument('end')
    bf.add_argument('--days', type=int, default=7)
    bf.add_argument('--write', action='store_true')
    a = p.parse_args()
    if a.cmd == 'predict':
        predict_demand_to_db(a.date, a.days, write=not a.no_write)
    elif a.cmd == 'backfill':
        backfill_demand_to_db(a.start, a.end, a.days, write=a.write)

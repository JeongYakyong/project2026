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

출력(est_horizon_land, _land): est_gas_gen_land(MW), est_gas_sendout_ton_land(TON/h, ×0.1521).
사용: 통합 체인 serve_chain_land_new.py 가 이 파일의 보정·기후값·용량 함수를 import 해 적용한다.
  (옛 단독 실행 진입점 predict_gas_to_db/backfill_gas_to_db 는 체인과 중복이라 제거됨, 2026-06-19.)
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
    if not c.get('calibration_enabled', True):
        # ★bias 보정 OFF (2026-06-15): 백테스트가 겨울 위주라 calib(>1)가 여름엔 거꾸로 과대를
        # 키운다(raw +5% → final +13%).  적합값은 JSON 에 보존하고 모든 지평 1.0(중립)으로 반환.
        # 1년치(여름·가을 포함) 데이터 확보 후 calibration_enabled=true 로 되돌려 재적용.
        # 블렌딩 가중(w)·기후값은 유지(요청은 calibration 한정).
        day = {int(k): 1.0 for k in dp}
        night = {int(k): 1.0 for k in dp}
    else:
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

# 직접 실행(standalone) 진입점은 제거됨(2026-06-19) — 통합 체인 serve_chain_land_new.py 가
# 위 라이브러리 함수(_load_calib·load_gas_climatology·_clim_vals·_blend_w·_calib_vec·
# _renew_cap·load_gas_series)를 import 해 5→6→7 을 한 번에 돌리고 보정·블렌딩까지 적용해
# est_horizon_land 에 쓴다.  옛 _read_chain·predict_gas_to_db·backfill_gas_to_db(forecast
# 테이블 읽기·쓰기)는 체인과 중복이라 삭제.  이 파일은 체인이 쓰는 라이브러리로만 남는다.

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
MODEL = os.path.join(HERE, 'model', 'lgbm_land_gas_v3.txt')   # v3(2026-06-21 G-25): 야간 레짐 대응(최근원전). v2 롤백 보존.
META  = os.path.join(HERE, 'model', 'model_meta_gas_v3.json')
CALIB_JSON = os.path.join(HERE, 'model', 'gas_serving_calib.json')

DEMAND_COL = 'est_demand_land'           # 5단계
RENEW_COL  = 'est_market_renew_land'     # 6단계 (시장 solar+wind)
OUT_GEN = 'est_gas_gen_land'
OUT_TON = 'est_gas_sendout_ton_land'
# v3 피처 = v2 MIXED + nuke_rec24/nuke_rec168(origin 이하 최근 원전 평균, 관성 대리).
FEATS = ['real_demand_land', 'renew_util', 'gas_lag168', 'gas_lag24', 'gas_rec24', 'gas_rec168',
         'h', 'hour', 'dow', 'doy', 'nuke_rec24', 'nuke_rec168']
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
    if not c.get('blend_enabled', True):
        # ★기후값 블렌딩 OFF (2026-06-22): 6단계 G-27 장지평 재훈련 후 가스 정직 재검증 결과,
        # 옛(06-15·옛 6단계) 적합 블렌딩이 새 체인에서 D+5~15 전 계절 MAPE 를 키우고(전체
        # 9.69→10.04%·D+15 +0.9%p) v3 가 고친 겨울 밤 과소를 2022–24 옛 원전레짐 기후값으로
        # 되돌린다(겨울밤 D13-15 raw −0.3% → 블렌딩 후 −4.2%).  새 6단계가 '멀수록 평년 수축'을
        # 직접 학습하면서 블렌딩의 변동축소 효과가 중복·역효과가 됨.  raw v3 가 새 체인서 이미
        # 중심화 → 블렌딩 제거.  w 적합값은 JSON 에 보존하고 모든 지평 0(블렌딩 없음)으로 반환.
        w = {int(k): 0.0 for k in c.get('blend_weight_by_horizon', {})}
    else:
        w = {int(k): float(v) for k, v in c.get('blend_weight_by_horizon', {}).items()}
    clim = c.get('climatology', {'window_days': 7, 'years': '2022-2024'})
    return day, night, float(c['conv_ton_per_mwh']), w, clim


# ── 저부하(밤·저녁) 임시 보정 (2026 여름 냉방부족 과대예측) ──────────────────
# 원인: 시원한 여름으로 전력수요 급락 → 모델 수요→가스 곡선이 저수요서 과대(학습기울기<실제).
# 편향은 '시간대 모양 × 시간에 따라 커지는 레벨' 구조. 낮(9-16h)은 무편향이라 보호(가중치0).
# corr(h)=hour_weight[h]×level, est_gas_gen_land = raw - corr.  raw 보존 → 되돌리기 쉬움.
def _load_lowload():
    """gas_serving_calib.json 의 lowload_night_correction 설정(없으면 빈 dict)."""
    c = json.load(open(CALIB_JSON, encoding='utf-8'))
    return c.get('lowload_night_correction', {})


def lowload_level(con, O, ll):
    """밤 보정 레벨(MW). manual=고정치 / adaptive=최근 lookback일 밤 nowcast 편향(인과적)."""
    if str(ll.get('level_mode', 'adaptive')) == 'manual':
        return float(ll.get('manual_level', 0.0))
    ad = ll.get('adaptive', {})
    look = int(ad.get('lookback_days', 7)); hz = int(ad.get('nowcast_horizon', 1))
    minr = int(ad.get('min_rows', 30)); day_hrs = set(int(x) for x in ll.get('day_protect_hours', []))
    lo = (O.normalize() - pd.Timedelta(days=look)).strftime('%Y-%m-%d %H:%M:%S')
    hi = O.normalize().strftime('%Y-%m-%d %H:%M:%S')
    try:
        p = pd.read_sql("SELECT timestamp, est_gas_gen_land_raw FROM est_horizon_land "
                        f"WHERE horizon_d={hz} AND timestamp>='{lo}' AND timestamp<'{hi}'",
                        con, parse_dates=['timestamp'])
        a = pd.read_sql("SELECT timestamp, gen_gas_kr FROM historical "
                        f"WHERE timestamp>='{lo}' AND timestamp<'{hi}'", con, parse_dates=['timestamp'])
    except Exception:
        return float(ll.get('manual_level', 0.0))
    d = p.merge(a, on='timestamp').dropna()
    d = d[(d.gen_gas_kr > 0) & (~d.timestamp.dt.hour.isin(day_hrs))]
    if len(d) < minr:                                   # 데이터 부족 → 수동 폴백
        return float(ll.get('manual_level', 0.0))
    return float((d.est_gas_gen_land_raw - d.gen_gas_kr).mean())


def lowload_corr(idx: pd.DatetimeIndex, level: float, ll) -> np.ndarray:
    """행별 밤 보정량 corr(h)=hour_weight[h]×level (낮=가중치0 → 0)."""
    hw = ll.get('hour_weight', {})
    w = np.array([float(hw.get(str(int(h)), 0.0)) for h in idx.hour])
    return w * float(level)


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


def load_nuke_series() -> pd.Series:
    """historical 원전 발전 연속 시계열(결측만 시간보간, 0 보존) — v3 최근원전 피처(nuke_rec24/168) 용.
    학습(exp_gas_regime.load_cont)과 동일하게 0 은 정상값으로 두고 보간 limit 6 만 적용."""
    with _conn() as con:
        d = pd.read_sql('SELECT timestamp, gen_nuclear_kr FROM historical', con, parse_dates=['timestamp'])
    d = d.sort_values('timestamp')
    idx = pd.date_range(d.timestamp.min(), d.timestamp.max(), freq='h')
    s = d.set_index('timestamp')['gen_nuclear_kr'].reindex(idx).interpolate('time', limit=6)
    s.index.name = 'timestamp'
    return s

# 직접 실행(standalone) 진입점은 제거됨(2026-06-19) — 통합 체인 serve_chain_land_new.py 가
# 위 라이브러리 함수(_load_calib·load_gas_climatology·_clim_vals·_blend_w·_calib_vec·
# _renew_cap·load_gas_series)를 import 해 5→6→7 을 한 번에 돌리고 보정·블렌딩까지 적용해
# est_horizon_land 에 쓴다.  옛 _read_chain·predict_gas_to_db·backfill_gas_to_db(forecast
# 테이블 읽기·쓰기)는 체인과 중복이라 삭제.  이 파일은 체인이 쓰는 라이브러리로만 남는다.

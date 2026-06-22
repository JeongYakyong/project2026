# -*- coding: utf-8 -*-
"""6단계 신재생 진단 — 지평 5구간 × 4계절 × 채널(태양광·풍력·합산) 정밀 비교.

목적: 현재 서빙 모델(태양광 PatchTST·풍력 LGBM, est_horizon_land)이 lag168(1주 전
같은 시각) 기준선에 '언제·어느 계절에' 지는지를 칸별로 확인한다. 재훈련 설계 근거.

정직 평가: est_horizon_land = 각 발행시각에 그때 받은 예보 기상을 그대로 넣은 D+1~15
예측 아카이브. 실측 = historical 시장 신재생. 지표 = nMAE(%) = 평균절대오차 / 평균발전량.

계절(사용자 확정, 긴 여름): 봄 3~5 · 여름 6~9 · 가을 10~11 · 겨울 12~2.
지평 5구간: D1-3 · D4-6 · D7-9 · D10-12 · D13-15.
기준선: lag168(대상시각 −168h 실측).  ※ D+8~15 의 lag168 은 발행시점엔 미래라
        서빙 불가 — 여기선 '진단용 참고 기준선'으로만 본다(낙관적일 수 있음).
"""
import os, sqlite3
import numpy as np, pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, '..', '..'))
DB = os.path.join(ROOT, '1. data_fetcher_and_db', 'data', 'input_data_land.db')

pd.set_option('display.width', 200)
pd.set_option('display.max_columns', 30)

# ── 데이터 로드 ──────────────────────────────────────────────────────
con = sqlite3.connect(DB)
e = pd.read_sql('SELECT timestamp, horizon_d, est_market_renew_land, '
                'est_solar_util_land, est_wind_util_land FROM est_horizon_land',
                con, parse_dates=['timestamp'])
h = pd.read_sql('SELECT timestamp, gen_solar_market_kr, gen_wind_kr, '
                'gen_solar_capacity_kr, gen_wind_capacity_kr FROM historical',
                con, parse_dates=['timestamp'])
con.close()
for c in h.columns:
    if c != 'timestamp':
        h[c] = pd.to_numeric(h[c], errors='coerce')
h['act_renew'] = h.gen_solar_market_kr + h.gen_wind_kr
H = h.set_index('timestamp')

# 예측 발전량 = 이용률 × 설비용량(실측), 실측·lag168 매핑
e['act_solar'] = e.timestamp.map(H['gen_solar_market_kr'].to_dict())
e['act_wind']  = e.timestamp.map(H['gen_wind_kr'].to_dict())
e['act_renew'] = e.timestamp.map(H['act_renew'].to_dict())
e['est_solar'] = e.est_solar_util_land * e.timestamp.map(H['gen_solar_capacity_kr'].to_dict())
e['est_wind']  = e.est_wind_util_land  * e.timestamp.map(H['gen_wind_capacity_kr'].to_dict())
e['lag_solar'] = e.timestamp.map(H['gen_solar_market_kr'].shift(freq='168h').to_dict())
e['lag_wind']  = e.timestamp.map(H['gen_wind_kr'].shift(freq='168h').to_dict())
e['lag_renew'] = e.timestamp.map(H['act_renew'].shift(freq='168h').to_dict())

# ── 분류: 계절·지평구간 ──────────────────────────────────────────────
def season(m):
    if m in (3, 4, 5):  return '봄(3-5)'
    if m in (6, 7, 8, 9): return '여름(6-9)'
    if m in (10, 11):   return '가을(10-11)'
    return '겨울(12-2)'

def segment(d):
    if d <= 3:  return 'D1-3'
    if d <= 6:  return 'D4-6'
    if d <= 9:  return 'D7-9'
    if d <= 12: return 'D10-12'
    return 'D13-15'

e['season'] = e.timestamp.dt.month.map(season)
e['seg'] = e.horizon_d.map(segment)
SEAS_ORD = ['봄(3-5)', '여름(6-9)', '가을(10-11)', '겨울(12-2)']
SEG_ORD  = ['D1-3', 'D4-6', 'D7-9', 'D10-12', 'D13-15']

def nmae(a, p):
    a = np.asarray(a, float); p = np.asarray(p, float)
    m = np.isfinite(a) & np.isfinite(p)
    if m.sum() == 0 or a[m].mean() == 0:
        return np.nan
    return float(np.abs(a[m] - p[m]).mean() / a[m].mean() * 100)

# ── 채널별 계절×구간 매트릭스 ────────────────────────────────────────
CH = {'태양광': ('act_solar', 'est_solar', 'lag_solar'),
      '풍력':   ('act_wind',  'est_wind',  'lag_wind'),
      '합산':   ('act_renew', 'est_market_renew_land', 'lag_renew')}

def matrix(metric_fn):
    out = {}
    for s in SEAS_ORD:
        row = {}
        for g in SEG_ORD:
            sub = e[(e.season == s) & (e.seg == g)]
            row[g] = metric_fn(sub)
        out[s] = row
    return pd.DataFrame(out).T[SEG_ORD]

for name, (ac, pc, lc) in CH.items():
    mdl = matrix(lambda sub: nmae(sub[ac], sub[pc]))
    lag = matrix(lambda sub: nmae(sub[ac], sub[lc]))
    dlt = mdl - lag  # 음수 = 모델이 lag보다 우수(이김), 양수 = 모델이 짐
    print('\n' + '=' * 78)
    print(f'[{name}]  nMAE(%)  — 모델(현행 서빙)')
    print(mdl.round(1).to_string())
    print(f'\n[{name}]  nMAE(%)  — lag168 기준선')
    print(lag.round(1).to_string())
    print(f'\n[{name}]  차이(모델 − lag168)   ★음수=모델 이김 / ★양수=모델이 짐')
    print(dlt.round(1).to_string())

# ── 표본 수(칸별 시간 수) ────────────────────────────────────────────
cnt = e.groupby(['season', 'seg']).size().unstack().reindex(SEAS_ORD)[SEG_ORD]
print('\n' + '=' * 78)
print('[표본 수] 칸별 평가 시간 개수  (가을=0·여름 얇음 확인용)')
print(cnt.fillna(0).astype(int).to_string())

# ── 전 지평 채널별 요약 ──────────────────────────────────────────────
print('\n' + '=' * 78)
print('[전체 요약] 채널별 nMAE(%)  모델 vs lag168')
for name, (ac, pc, lc) in CH.items():
    print(f'  {name:4s}  모델={nmae(e[ac], e[pc]):5.1f}   lag168={nmae(e[ac], e[lc]):5.1f}')
print('\n평가 기간:', e.timestamp.min(), '~', e.timestamp.max(),
      '· 발행시각 수:', e.timestamp.dt.normalize().nunique() if 'horizon_d' in e else 'NA')

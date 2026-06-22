# -*- coding: utf-8 -*-
"""6단계 신재생 장지평 재훈련 — 가벼운 LGBM(지평 인지·평년 앵커) 비교 실험.

핵심: 학습 데이터를 '정직한 예보 아카이브(forecast_horizon, 발행 base × 지평 × 시각)'로
삼아, 멀어질수록 예보가 틀리는 감쇠를 모델이 horizon_d 로 직접 학습하게 한다. 평년(기후값)
이용률을 입력 앵커로 줘서 지평이 멀면 평년으로 자연 수축. 손튜닝 블렌딩 가중치 없음.

정직 비교: 대상시각(ISO주) 그룹 교차검증 out-of-fold → 같은 대상시각이 학습/평가에
겹치지 않게(누수 차단). 현행 서빙(est_horizon_land: 태양광 PatchTST·풍력 LGBM)과 1:1.

★평가 규칙(사용자, 2026-06-22): 태양광은 밤=0(거저 맞힘) → '낮 시간만' 학습·평가.
  풍력·합산은 전 시간(풍력은 24시간 모두 중요).

사용자 확정:
  - 태양광 3지점(포항·영광·서산) · 풍력 2지점(대관령·영광)
  - lag168 피처 제거 · 가을=봄과 한 묶음(계절그룹) · 평년 레벨은 다년 실측에서 산출
  - 태양광은 비교만(단지평 PatchTST 유지, 장지평만 LGBM 후보)
"""
import os, sqlite3
import numpy as np, pandas as pd
import lightgbm as lgb
from sklearn.model_selection import GroupKFold

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, '..', '..'))
DB = os.path.join(ROOT, '1. data_fetcher_and_db', 'data', 'input_data_land.db')

SOLAR_ST = ['pohang', 'yeonggwang', 'seosan']
WIND_ST  = ['daegwallyeong', 'yeonggwang']
K_DAMP = 0.3
CLIM_CUTOFF = '2025-12-15'         # 평년·누수 차단: 예보 아카이브 시작 이전 실측만
DAY_THR = 0.01                     # 낮 판정: 평년 태양광 이용률 > 1%
NFOLD = 5
pd.set_option('display.width', 200); pd.set_option('display.max_columns', 30)

def season(m):
    if m in (3, 4, 5):   return '봄(3-5)'
    if m in (6, 7, 8, 9): return '여름(6-9)'
    if m in (10, 11):    return '가을(10-11)'
    return '겨울(12-2)'
def season_grp(m):                 # 가을=봄과 한 묶음
    if m in (12, 1, 2):  return 0
    if m in (6, 7, 8, 9): return 2
    return 1
def segment(d):
    if d <= 3:  return 'D1-3'
    if d <= 6:  return 'D4-6'
    if d <= 9:  return 'D7-9'
    if d <= 12: return 'D10-12'
    return 'D13-15'
SEAS_ORD = ['봄(3-5)', '여름(6-9)', '가을(10-11)', '겨울(12-2)']
SEG_ORD  = ['D1-3', 'D4-6', 'D7-9', 'D10-12', 'D13-15']

def nmae(a, p):
    a = np.asarray(a, float); p = np.asarray(p, float)
    m = np.isfinite(a) & np.isfinite(p)
    if m.sum() == 0 or a[m].mean() == 0: return np.nan
    return float(np.abs(a[m] - p[m]).mean() / a[m].mean() * 100)

# ── 데이터 로드 ──────────────────────────────────────────────────────
con = sqlite3.connect(DB)
wcols = []
for st in SOLAR_ST: wcols += [f'radiation_{st}', f'total_cloud_{st}', f'midlow_cloud_{st}', f'rainfall_{st}']
for st in WIND_ST:  wcols += [f'wind_spd_10m_{st}', f'wd_sin_10m_{st}', f'wd_cos_10m_{st}']
wcols = list(dict.fromkeys(wcols))
e = pd.read_sql(f'SELECT timestamp, base, horizon_d, {", ".join(wcols)} FROM forecast_horizon',
                con, parse_dates=['timestamp', 'base'])
h = pd.read_sql('SELECT timestamp, gen_solar_market_kr, gen_wind_kr, gen_solar_capacity_kr, '
                'gen_wind_capacity_kr, gen_solar_utilization_kr, gen_wind_utilization_kr FROM historical',
                con, parse_dates=['timestamp'])
# ★현행 기준 = 백업(옛 모델, out-of-sample)에서 읽는다. est_horizon_land 는 신규로 백필돼
#   in-sample(낙관)이라 정직 비교에 못 씀.  PatchTST 태양광(D1-6 생산 블렌딩용)도 여기서 정직 확보.
cur = pd.read_sql('SELECT base, timestamp, est_solar_util_land, est_wind_util_land '
                  'FROM est_horizon_land_bak_20260622', con, parse_dates=['timestamp', 'base'])
con.close()
for c in h.columns:
    if c != 'timestamp': h[c] = pd.to_numeric(h[c], errors='coerce')
H = h.set_index('timestamp')
for c in wcols: e[c] = pd.to_numeric(e[c], errors='coerce')
e = e[(e.horizon_d >= 1) & (e.horizon_d <= 15)].copy()

e['y_solar'] = e.timestamp.map(H['gen_solar_utilization_kr'].to_dict())
e['y_wind']  = e.timestamp.map(H['gen_wind_utilization_kr'].to_dict())
e['cap_s']   = e.timestamp.map(H['gen_solar_capacity_kr'].to_dict())
e['cap_w']   = e.timestamp.map(H['gen_wind_capacity_kr'].to_dict())
e['act_s']   = e.timestamp.map(H['gen_solar_market_kr'].to_dict())
e['act_w']   = e.timestamp.map(H['gen_wind_kr'].to_dict())
e = e.merge(cur, on=['base', 'timestamp'], how='left')

# ── 평년 앵커(월×시각, cutoff 이전 다년 실측) ──
hpast = h[h.timestamp < CLIM_CUTOFF].copy()
hpast['m'] = hpast.timestamp.dt.month; hpast['hr'] = hpast.timestamp.dt.hour
clim_s = hpast.groupby(['m', 'hr']).gen_solar_utilization_kr.mean()
clim_w = hpast.groupby(['m', 'hr']).gen_wind_utilization_kr.mean()
e['m'] = e.timestamp.dt.month; e['hr'] = e.timestamp.dt.hour
e['clim_solar'] = e.set_index(['m', 'hr']).index.map(clim_s).astype(float)
e['clim_wind']  = e.set_index(['m', 'hr']).index.map(clim_w).astype(float)
e['is_day'] = e['clim_solar'].fillna(0) > DAY_THR   # ★낮 판정

# ── damping(태양광): 대상일 주간(06~20h) 강수합, 지점별 ──
e['tdate'] = e.timestamp.dt.normalize()
daymask = e.timestamp.dt.hour.between(6, 20)
rsum = e[daymask].groupby(['base', 'tdate'])[[f'rainfall_{st}' for st in SOLAR_ST]].sum()
rsum.columns = [f'rsum_{st}' for st in SOLAR_ST]
e = e.merge(rsum, on=['base', 'tdate'], how='left')
for st in SOLAR_ST:
    e[f'solar_damping_{st}'] = np.exp(-K_DAMP * e[f'rsum_{st}'].fillna(0).clip(upper=20))

e['hour_sin'] = np.sin(2*np.pi*e.hr/24); e['hour_cos'] = np.cos(2*np.pi*e.hr/24)
e['season_grp'] = e.timestamp.dt.month.map(season_grp).astype('category')
e['season'] = e.timestamp.dt.month.map(season); e['seg'] = e.horizon_d.map(segment)
_iso = e['timestamp'].dt.isocalendar()
e['iso_week'] = (_iso.year.astype(int) * 100 + _iso.week.astype(int)).values

FS = []
for st in SOLAR_ST: FS += [f'radiation_{st}', f'total_cloud_{st}', f'midlow_cloud_{st}', f'solar_damping_{st}']
FS += ['clim_solar', 'season_grp', 'hour_sin', 'hour_cos', 'horizon_d']
FW = []
for st in WIND_ST: FW += [f'wind_spd_10m_{st}', f'wd_sin_10m_{st}', f'wd_cos_10m_{st}']
FW += ['clim_wind', 'season_grp', 'hour_sin', 'hour_cos', 'horizon_d']

PARAMS = dict(objective='regression_l1', num_leaves=31, learning_rate=0.04,
              feature_fraction=0.8, bagging_fraction=0.8, bagging_freq=1,
              min_child_samples=100, max_depth=-1, verbose=-1)
NROUND = 500

def oof_predict(feats, ycol, rowmask=None):
    """대상시각(ISO주) 그룹 교차검증 out-of-fold 이용률 예측. rowmask=학습/예측 대상 행."""
    df = e.dropna(subset=[ycol]).copy()
    if rowmask is not None: df = df[rowmask.loc[df.index]]
    grp = df['iso_week'].values
    oof = pd.Series(np.nan, index=df.index)
    for tr, te in GroupKFold(n_splits=NFOLD).split(df, groups=grp):
        Xtr, Xte = df.iloc[tr], df.iloc[te]
        dtr = lgb.Dataset(Xtr[feats], Xtr[ycol], categorical_feature=['season_grp'])
        m = lgb.train(PARAMS, dtr, num_boost_round=NROUND)
        oof.iloc[te] = np.clip(m.predict(Xte[feats]), 0, 1)
    out = pd.Series(np.nan, index=e.index); out.loc[df.index] = oof
    return out

print('낮 판정 시간대(평년>1%):', sorted(e[e.is_day].hr.unique()))
print('학습/예측: 태양광 LGBM(낮만) ...')
e['lgb_solar'] = oof_predict(FS, 'y_solar', rowmask=e['is_day']).where(e['is_day'], 0.0)
print('학습/예측: 풍력 LGBM(전 시간) ...')
e['lgb_wind'] = oof_predict(FW, 'y_wind')

# ── 발전량 환원 ──
e['new_sg'] = e.lgb_solar * e.cap_s;          e['new_wg'] = e.lgb_wind * e.cap_w
e['cur_sg'] = e.est_solar_util_land * e.cap_s; e['cur_wg'] = e.est_wind_util_land * e.cap_w
e['new_rg'] = e.new_sg + e.new_wg;            e['cur_rg'] = e.cur_sg + e.cur_wg
e['act_rg'] = e.act_s + e.act_w

# ── 생산 블렌딩(태양광 PatchTST D1-6 ↔ LGBM D7-15, 풍력 LGBM) 정직 지평별 → 보고서 CSV ──
#   현행(cur)=옛 모델 out-of-sample · LGBM oof=누수없는 교차검증 → 둘 다 정직.  서빙 _blend_w 와 동일식.
e['w_blend'] = np.clip((e.horizon_d - 5) / 4.0, 0.0, 1.0)
e['blend_su'] = (1 - e.w_blend) * e.est_solar_util_land + e.w_blend * e.lgb_solar   # 태양광 생산 블렌딩
e['prod_sg'] = e.blend_su * e.cap_s
e['prod_wg'] = e.lgb_wind * e.cap_w                                                 # 풍력 = 신규 LGBM
e['prod_rg'] = e.prod_sg + e.prod_wg
e['lag_rg'] = e.timestamp.map((H.gen_solar_market_kr + H.gen_wind_kr).shift(freq='168h').to_dict())
REPORT = os.path.join(ROOT, '9. design', 'report', 'stage6')
ph = []
for n in range(1, 16):
    g = e[e.horizon_d == n]; gd = g[g.is_day]
    ph.append(dict(horizon=n,
        renew_new=nmae(g.act_rg, g.prod_rg), renew_old=nmae(g.act_rg, g.cur_rg), renew_lag=nmae(g.act_rg, g.lag_rg),
        solar_new=nmae(gd.act_s, gd.prod_sg), solar_old=nmae(gd.act_s, gd.cur_sg),
        wind_new=nmae(g.act_w, g.prod_wg), wind_old=nmae(g.act_w, g.cur_wg)))
pd.DataFrame(ph).round(2).to_csv(os.path.join(REPORT, 'perf_by_horizon_6_new.csv'), index=False, encoding='utf-8-sig')
print('보고서 정직 지평별(발전량) 저장:', os.path.join(REPORT, 'perf_by_horizon_6_new.csv'))

# ── 이용률 기준 정직 지평별(우리 모델 vs lag168 vs 기후값 평년) → #1·#2 그림용 ──
#   이용률(%) 단위 비교. 기후값=월×시각 평년(서빙 가능·전 지평 정직) / lag168=1주 전(장지평은 미래라 참고용).
e['act_su'] = e.y_solar; e['act_wu'] = e.y_wind
e['pred_su'] = e.blend_su; e['pred_wu'] = e.lgb_wind
e['clim_su'] = e.clim_solar; e['clim_wu'] = e.clim_wind
e['lag_su'] = e.timestamp.map(H.gen_solar_utilization_kr.shift(freq='168h').to_dict())
e['lag_wu'] = e.timestamp.map(H.gen_wind_utilization_kr.shift(freq='168h').to_dict())
_ws = e.cap_s + e.cap_w                                       # 전체 신재생 = 용량가중 이용률
e['act_ru'] = (e.act_s + e.act_w) / _ws
e['pred_ru'] = (e.pred_su * e.cap_s + e.pred_wu * e.cap_w) / _ws
e['clim_ru'] = (e.clim_su * e.cap_s + e.clim_wu * e.cap_w) / _ws
e['lag_ru'] = (e.lag_su * e.cap_s + e.lag_wu * e.cap_w) / _ws
pu = []
for n in range(1, 16):
    g = e[e.horizon_d == n]; gd = g[g.is_day]
    pu.append(dict(horizon=n,
        renew_model=nmae(g.act_ru, g.pred_ru), renew_lag=nmae(g.act_ru, g.lag_ru), renew_clim=nmae(g.act_ru, g.clim_ru),
        solar_model=nmae(gd.act_su, gd.pred_su), solar_lag=nmae(gd.act_su, gd.lag_su), solar_clim=nmae(gd.act_su, gd.clim_su),
        wind_model=nmae(g.act_wu, g.pred_wu), wind_lag=nmae(g.act_wu, g.lag_wu), wind_clim=nmae(g.act_wu, g.clim_wu)))
pd.DataFrame(pu).round(2).to_csv(os.path.join(REPORT, 'perf_util_horizon_6.csv'), index=False, encoding='utf-8-sig')
print('보고서 정직 지평별(이용률) 저장:', os.path.join(REPORT, 'perf_util_horizon_6.csv'))

# ── 5구간×4계절 비교(태양광=낮만 / 풍력·합산=전 시간) ──
def matrix(fn, base):
    return pd.DataFrame({s: {g: fn(base[(base.season == s) & (base.seg == g)]) for g in SEG_ORD}
                         for s in SEAS_ORD}).T[SEG_ORD]

CH = {'태양광(낮)': ('act_s', 'cur_sg', 'new_sg', e[e.is_day]),
      '풍력':       ('act_w', 'cur_wg', 'new_wg', e),
      '합산':       ('act_rg', 'cur_rg', 'new_rg', e)}
for name, (ac, cc, nc, base) in CH.items():
    curm = matrix(lambda s: nmae(s[ac], s[cc]), base)
    newm = matrix(lambda s: nmae(s[ac], s[nc]), base)
    print('\n' + '=' * 80)
    print(f'[{name}] 현행(PatchTST/LGBM) nMAE(%)'); print(curm.round(1).to_string())
    print(f'\n[{name}] 신규 LGBM(지평인지+평년앵커) nMAE(%)'); print(newm.round(1).to_string())
    print(f'\n[{name}] 개선폭(신규 − 현행)   ★음수=신규가 더 정확'); print((newm - curm).round(1).to_string())
    pd.concat({'현행': curm, '신규LGBM': newm, '개선': newm - curm}, axis=1).round(2).to_csv(
        os.path.join(HERE, f'cv_compare_{name}.csv'), encoding='utf-8-sig')

print('\n' + '=' * 80); print('[전체 요약] 채널별 nMAE(%)  현행 vs 신규 LGBM')
for name, (ac, cc, nc, base) in CH.items():
    print(f'  {name:8s}  현행={nmae(base[ac], base[cc]):5.1f}   신규LGBM={nmae(base[ac], base[nc]):5.1f}')

print('\n[지평구간 요약] nMAE(%)  (태양광=낮 / 풍력·합산=전시간)')
for g in SEG_ORD:
    sd = e[(e.seg == g) & e.is_day]; sa = e[e.seg == g]
    print(f'  {g:7s}  태양광 현행={nmae(sd.act_s, sd.cur_sg):4.1f}/신규={nmae(sd.act_s, sd.new_sg):4.1f}   '
          f'풍력 현행={nmae(sa.act_w, sa.cur_wg):4.1f}/신규={nmae(sa.act_w, sa.new_wg):4.1f}   '
          f'합산 현행={nmae(sa.act_rg, sa.cur_rg):4.1f}/신규={nmae(sa.act_rg, sa.new_rg):4.1f}')

# ── 전진 분할 검증(앞 70% 주 학습 → 뒤 30% 주 예측, 생산환경 모사) ──
print('\n\n' + '#' * 80)
print('# 전진 분할: 앞 70% 주 학습 → 뒤 30% 주 예측 (현행 모델은 2025-01 학습본=더 옛것)')
def fwd(feats, ycol, rowmask=None):
    df = e.dropna(subset=[ycol])
    if rowmask is not None: df = df[rowmask.loc[df.index]]
    wks = np.sort(df['iso_week'].unique()); cut = wks[int(len(wks) * 0.70)]
    tr = df[df.iso_week < cut]; te = df[df.iso_week >= cut]
    dtr = lgb.Dataset(tr[feats], tr[ycol], categorical_feature=['season_grp'])
    m = lgb.train(PARAMS, dtr, num_boost_round=NROUND)
    return te.index, np.clip(m.predict(te[feats]), 0, 1), cut
si, sp, cut = fwd(FS, 'y_solar', rowmask=e['is_day']); wi, wp, _ = fwd(FW, 'y_wind')
te = e.loc[si.union(wi)].copy()
te['fwd_su'] = 0.0; te.loc[si, 'fwd_su'] = sp
te['fwd_wu'] = np.nan; te.loc[wi, 'fwd_wu'] = wp
te['fwd_sg'] = te.fwd_su * te.cap_s; te['fwd_wg'] = te.fwd_wu * te.cap_w
te['fwd_rg'] = te.fwd_sg + te.fwd_wg
print(f'  분할 경계 ISO주={cut} · 테스트 {te.timestamp.min().date()}~{te.timestamp.max().date()} '
      f'· 계절={sorted(te.season.unique())}')
for nm, ac, cc, nc, daycol in [('태양광(낮)', 'act_s', 'cur_sg', 'fwd_sg', True),
                               ('풍력', 'act_w', 'cur_wg', 'fwd_wg', False),
                               ('합산', 'act_rg', 'cur_rg', 'fwd_rg', False)]:
    tt = te[te.is_day] if daycol else te
    print(f'\n  [{nm}] 지평구간별 nMAE(%)  현행 vs 신규(전진)')
    for g in SEG_ORD:
        s = tt[tt.seg == g]
        print(f'    {g:7s}  현행={nmae(s[ac], s[cc]):5.1f}   신규={nmae(s[ac], s[nc]):5.1f}')
    print(f'    전체    현행={nmae(tt[ac], tt[cc]):5.1f}   신규={nmae(tt[ac], tt[nc]):5.1f}')
print('\n저장: cv_compare_태양광(낮)/풍력/합산.csv')

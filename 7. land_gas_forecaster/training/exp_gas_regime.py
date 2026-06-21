# -*- coding: utf-8 -*-
"""탐색 — 야간 레짐(2026 원전↓→가스↑) 대응: '최근 원전' 관성 피처 + walk-forward.

사용자 통찰(2026-06-21):
  · 원전은 관성이 매우 강한 기저전원 → 전날/최근 원전이 미래 원전의 거의 완벽한 대리값.
    서빙 때 origin 이하 실측만 쓰면 가용(미래 원전 불필요).  옛 '원전 피처 금지'는 구체적 EDA
    없이 내린 결정(covariate shift) → walk-forward 로 신레짐을 학습창에 넣으면 우려 해소.
  · 가스 자기회귀도 시각별 최근값으로 강화(rec24/168 은 스칼라라 야간 특이 상승을 못 실음).

이 스크립트(탐색 전용 — 최종 피처는 사용자 확정 후 production):
  (A) 원전 관성 정량화: nuke_t ↔ nuke_{t-24h}/{t-168h} 상관, 하루 변화 분포.
  (B) ★결정적 실험: 2026 을 학습에서 빼고(train ≤2025-12) 2026 을 oracle(실측 피처) test.
      BASE(현 MIXED) vs +최근원전 vs +시각별최근가스 야간 bias/MAPE 비교.
      → +최근원전이 2026 야간 bias 를 잡으면 "관성 피처가 신레짐을 스스로 추종" 입증.
  (C) walk-forward 참고: train ≤2026-03 / test 2026-04~06.

타깃 = 가스 MW.  손실 = l1(피처 효과 격리 위해 비대칭 미적용).  oracle 피처(실측 수요·신재생)로
모델 함수 품질만 본다(체인/예보 노이즈 분리).  origin=23:00, 다지평 1..360 자기회귀(누수가드 동일).
"""
from __future__ import annotations
import os, sys, sqlite3
import numpy as np, pandas as pd, lightgbm as lgb

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, '..', '..'))
DB = os.path.join(ROOT, '1. data_fetcher_and_db', 'data', 'input_data_land.db')
CAPA = os.path.join(ROOT, '1. data_fetcher_and_db', 'second_dataset', 'kr_elec_capa.csv')

CAL = ['h', 'hour', 'dow', 'doy']
BASE_FEAT = ['real_demand_land', 'renew_util', 'gas_lag168', 'gas_lag24', 'gas_rec24', 'gas_rec168'] + CAL
HMAX = 360
SEASON = {12: '겨울', 1: '겨울', 2: '겨울', 3: '봄', 4: '봄', 5: '봄',
          6: '여름', 7: '여름', 8: '여름', 9: '가을', 10: '가을', 11: '가을'}
PARAMS = dict(objective='regression_l1', metric='l1', learning_rate=0.03, num_leaves=127,
              min_data_in_leaf=100, feature_fraction=0.85, bagging_fraction=0.8, bagging_freq=5,
              lambda_l2=0.2, verbosity=-1, random_state=42)


def mape(a, p):
    a, p = np.asarray(a, float), np.asarray(p, float); m = (a > 0) & np.isfinite(a) & np.isfinite(p)
    return float(np.mean(np.abs(a[m]-p[m])/a[m])*100) if m.any() else np.nan


def nbias(a, p):
    a, p = np.asarray(a, float), np.asarray(p, float); m = (a > 0) & np.isfinite(a) & np.isfinite(p)
    return float(np.mean((p[m]-a[m])/a[m])*100) if m.any() else np.nan


def load_caps():
    df = pd.read_csv(CAPA, encoding='euc-kr', header=None, skiprows=2,
                     names=['period', 'region', 'LNG', 'solar', 'wind', 'PPA'])
    df = df[df.region.astype(str).str.strip() == '합계'].copy()
    df['ym'] = pd.to_datetime(df.period, format='%b-%y').dt.to_period('M')
    for c in ['LNG', 'solar', 'wind']:
        df[c] = pd.to_numeric(df[c], errors='coerce')
    return df.dropna(subset=['LNG']).set_index('ym')[['LNG', 'solar', 'wind']].sort_index()


def cap_on(idx, caps, col):
    ym = idx.to_period('M')
    full = pd.period_range(min(ym.min(), caps.index.min()), max(ym.max(), caps.index.max()), freq='M')
    return ym.map(caps[col].reindex(full).ffill().bfill()).astype(float).values


def load_cont():
    cols = ['timestamp', 'gen_gas_kr', 'real_demand_land', 'renew_gen_total_kr', 'gen_nuclear_kr', 'gen_pumped_kr']
    with sqlite3.connect(DB) as con:
        raw = pd.read_sql(f"SELECT {', '.join(cols)} FROM historical", con, parse_dates=['timestamp'])
    raw = raw.sort_values('timestamp')
    idx = pd.date_range(raw.timestamp.min(), raw.timestamp.max(), freq='h')
    d = raw.set_index('timestamp').reindex(idx); d.index.name = 'timestamp'
    for c in ['gen_gas_kr', 'real_demand_land', 'renew_gen_total_kr']:
        d[c] = pd.to_numeric(d[c], errors='coerce').replace(0, np.nan).interpolate('time', limit=6)
    for c in ['gen_nuclear_kr', 'gen_pumped_kr']:   # 원전·양수는 0 이 정상값일 수 있어 0 보존
        d[c] = pd.to_numeric(d[c], errors='coerce').interpolate('time', limit=6)
    caps = load_caps()
    d['renew_cap'] = cap_on(d.index, caps, 'solar') + cap_on(d.index, caps, 'wind')
    d['renew_util'] = d.renew_gen_total_kr / d.renew_cap
    return d


def confirm_inertia(d):
    print('=' * 74)
    print('(A) 원전 관성 — 최근 원전이 미래 원전을 얼마나 잘 대리하나')
    print('=' * 74)
    nuke = d.gen_nuclear_kr
    for lag in [24, 48, 168, 336]:
        c = nuke.corr(nuke.shift(lag))
        print(f'  corr(원전_t, 원전_t-{lag:>3}h) = {c:.4f}')
    dd = nuke.resample('D').mean()
    chg = dd.diff().abs()
    print(f'  하루 평균 원전 변화량 |Δ|: 중앙값 {chg.median():.0f}MW · 90퍼센타일 {chg.quantile(.9):.0f}MW '
          f'(평균레벨 {nuke.mean():.0f}MW 대비 {chg.median()/nuke.mean()*100:.1f}%)')
    # 7일 전 원전으로 오늘 원전 추정 시 오차(서빙 D+7 대리 상황)
    for lag in [24, 168, 336]:
        err = (nuke - nuke.shift(lag)).abs()
        print(f'  원전을 {lag}h 전 값으로 대리 시 MAE {err.mean():.0f}MW ({err.mean()/nuke.mean()*100:.1f}%)')


def build_samples(d):
    gas = d.gen_gas_kr.values; dem = d.real_demand_land.values; renu = d.renew_util.values
    nuke = d.gen_nuclear_kr.values; pump = d.gen_pumped_kr.values
    hour = d.index.hour.values; dow = d.index.dayofweek.values; doy = d.index.dayofyear.values
    year = d.index.year.values; month = d.index.month.values
    N = len(d)
    rec24 = pd.Series(gas).rolling(24, min_periods=20).mean().values
    rec168 = pd.Series(gas).rolling(168, min_periods=140).mean().values
    nrec24 = pd.Series(nuke).rolling(24, min_periods=20).mean().values
    nrec168 = pd.Series(nuke).rolling(168, min_periods=140).mean().values
    prec168 = pd.Series(pump).rolling(168, min_periods=140).mean().values
    # 시각별 최근가스 = 같은 시각 직전 7일 평균(=lag24의 7항 평균).  origin 시점 정보만 사용.
    gas_s = pd.Series(gas)
    ghour7 = (gas_s.shift(24) + gas_s.shift(48) + gas_s.shift(72) + gas_s.shift(96)
              + gas_s.shift(120) + gas_s.shift(144) + gas_s.shift(168)).values / 7.0

    H = np.arange(1, HMAX + 1)
    origins = np.where((hour == 23) & (np.arange(N) >= 167) & (np.arange(N) <= N - 1 - HMAX))[0]
    tgt = (origins[:, None] + H[None, :]).ravel(); hh = np.broadcast_to(H, (len(origins), HMAX)).ravel()
    li = tgt - 168
    # 시각별 최근가스: 타깃 시각 기준, origin 이하 같은 시각 7일 평균 → ghour7[tgt-? ]
    # origin 이하만 쓰려면 origin 직전 같은 시각 평균을 타깃 hour 로 매핑해야 하나, 근사로
    # ghour7[tgt] 는 타깃-(24..168) 평균이라 h<=168 일 때 일부가 origin 이후가 됨 → h<=24 만 채택(안전).
    g = pd.DataFrame({
        'y': gas[tgt], 'h': hh.astype(np.int16),
        'real_demand_land': dem[tgt], 'renew_util': renu[tgt],
        'gas_lag168': np.where(hh <= 168, gas[li], np.nan),
        'gas_lag24': np.where(hh <= 24, gas[tgt-24], np.nan),
        'gas_rec24': np.repeat(rec24[origins], HMAX), 'gas_rec168': np.repeat(rec168[origins], HMAX),
        # 원전 관성 피처 (origin 시점 최근값 — 미래 원전 불필요)
        'nuke_rec24': np.repeat(nrec24[origins], HMAX), 'nuke_rec168': np.repeat(nrec168[origins], HMAX),
        'nuke_lag168': np.where(hh <= 168, nuke[li], np.nan),
        'pump_rec168': np.repeat(prec168[origins], HMAX),
        # 시각별 최근가스 (h<=24 만 — origin 이하 보장)
        'gas_hour7': np.where(hh <= 24, ghour7[tgt], np.nan),
        'hour': hour[tgt], 'dow': dow[tgt], 'doy': doy[tgt],
        'tyear': year[tgt], 'tmonth': month[tgt]})
    g = g[(g.y > 0) & g.real_demand_land.notna() & g.gas_rec168.notna() & g.nuke_rec168.notna()].reset_index(drop=True)
    return g


def run_fold(samp, tr_mask, te_mask, label):
    sets = {
        'BASE(현행)': BASE_FEAT,
        '+최근원전': BASE_FEAT + ['nuke_rec24', 'nuke_rec168'],
        '+최근원전+lag168': BASE_FEAT + ['nuke_rec24', 'nuke_rec168', 'nuke_lag168'],
        '+최근원전+양수': BASE_FEAT + ['nuke_rec24', 'nuke_rec168', 'pump_rec168'],
        '+시각별최근가스': BASE_FEAT + ['gas_hour7'],
        '+원전+시각가스': BASE_FEAT + ['nuke_rec24', 'nuke_rec168', 'gas_hour7'],
    }
    tr = samp[tr_mask]; te = samp[te_mask].copy()
    te['hr'] = te.hour; te['night'] = ~((te.hr >= 9) & (te.hr <= 15))
    te['season'] = te.tmonth.map(SEASON)
    print('\n' + '=' * 90)
    print(f'{label}   (train n={len(tr)},  test n={len(te)})')
    print('=' * 90)
    hdr = f'{"피처셋":18} {"전체MAPE":>8} {"전체bias":>8} | {"밤MAPE":>7} {"밤bias":>7} | ' \
          f'{"겨울밤b":>7} {"봄밤b":>7} {"여름밤b":>7}'
    print(hdr)
    for name, feat in sets.items():
        m = lgb.train(PARAMS, lgb.Dataset(tr[feat], tr.y), num_boost_round=500, callbacks=[lgb.log_evaluation(0)])
        te['p'] = m.predict(te[feat])
        nt = te[te.night]
        def sb(seas):
            g = nt[nt.season == seas]
            return nbias(g.y, g.p) if len(g) > 30 else float('nan')
        print(f'{name:18} {mape(te.y,te.p):>7.2f}% {nbias(te.y,te.p):>+7.1f}% | '
              f'{mape(nt.y,nt.p):>6.2f}% {nbias(nt.y,nt.p):>+6.1f}% | '
              f'{sb("겨울"):>+6.1f} {sb("봄"):>+6.1f} {sb("여름"):>+6.1f}')


def main():
    d = load_cont()
    confirm_inertia(d)
    samp = build_samples(d)
    print(f'\n샘플 {len(samp)}행, 연도분포:', samp.tyear.value_counts().sort_index().to_dict())

    # (B) 결정적 실험 — 2026 을 학습에서 제외(train ≤2025) → 2026 oracle test
    run_fold(samp, samp.tyear <= 2025, samp.tyear == 2026,
             '(B) train ≤2025 (신레짐 미포함) → test 2026  ★관성피처가 레짐을 추종하나')

    # (C) walk-forward — train ≤2026-03, test 2026-04~06
    tr_c = (samp.tyear <= 2025) | ((samp.tyear == 2026) & (samp.tmonth <= 3))
    te_c = (samp.tyear == 2026) & (samp.tmonth >= 4)
    run_fold(samp, tr_c, te_c, '(C) walk-forward train ≤2026-03 → test 2026-04~06')


if __name__ == '__main__':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass
    main()

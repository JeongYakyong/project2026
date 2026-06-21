# -*- coding: utf-8 -*-
"""(A) 타깃 Demand 이상치 점검 + (B) 낮 과대예측 ↔ solar_rad 관계 진단.

질문1: 타깃(real_demand_land)에 큰 이상치가 있나? → MSTL 잔차 + min/max-IQR.
질문2: "낮 과대예측은 solar_rad 문제 아니냐?" → 보정전 v4(patchtst_lt) 시점별 bias 를
        시각·solar_rad 수준으로 쪼개, '햇빛 셀수록 더 과대'인지 직접 확인.
        + BTM 태양광 성장(연도별 한낮)을 같이 보여 근본원인(계량수요 한낮 억제) 맥락 제시.
산출: eda_scaler/ 에 그림 + 표.
"""
from __future__ import annotations
import os, sys, sqlite3
try:
    sys.stdout.reconfigure(encoding='utf-8'); sys.stderr.reconfigure(encoding='utf-8')
except Exception:
    pass
import numpy as np, pandas as pd
import matplotlib; matplotlib.use('Agg')
import matplotlib.pyplot as plt
from statsmodels.tsa.seasonal import MSTL

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import model_lt as M  # noqa

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.normpath(os.path.join(HERE, '..', '..', '..', '..', '1. data_fetcher_and_db', 'data', 'input_data_land.db'))
TRAIN_END = '2025-01-01'
SOLAR_SEL = M.SOLAR_SEL  # seosan, yeonggwang
plt.rcParams['font.family'] = 'Malgun Gothic'; plt.rcParams['axes.unicode_minus'] = False


def mad_z(x):
    x = np.asarray(x, float); med = np.median(x); mad = np.median(np.abs(x - med)) or 1e-9
    return 0.6745 * (x - med) / mad


def load_hist():
    cols = ['timestamp', 'real_demand_land', 'gen_solar_btm_kr', 'gen_solar_ppa_kr', 'gen_solar_market_kr'] \
        + [f'solar_rad_{s}' for s in SOLAR_SEL] + [f'temp_c_{s}' for s in M.TEMP_SEL]
    with sqlite3.connect(DB) as con:
        df = pd.read_sql(f"SELECT {','.join(cols)} FROM historical", con, parse_dates=['timestamp'])
    df = df.set_index('timestamp').sort_index()
    df['solar_rad'] = df[[f'solar_rad_{s}' for s in SOLAR_SEL]].mean(1)
    df['temp_c'] = df[[f'temp_c_{s}' for s in M.TEMP_SEL]].mean(1)
    df['dem'] = df['real_demand_land'].replace(0, np.nan)
    return df


# ───────────────── (A) 타깃 Demand 이상치 ─────────────────
def part_a():
    df = load_hist()
    s = df['dem'].interpolate('time').ffill().bfill()
    s = s[s.index >= '2020-01-01']
    res = MSTL(s, periods=(24, 168)).fit()
    rem = res.resid
    rem_tr = rem.loc[rem.index < TRAIN_END]
    z = mad_z(rem_tr.values)
    s_tr = s.loc[s.index < TRAIN_END]
    q1, med, q3 = np.percentile(s_tr, [25, 50, 75]); iqr = q3 - q1
    lo, hi = s_tr.min(), s_tr.max(); p01, p99 = np.percentile(s_tr, [1, 99])
    print('=== (A) 타깃 Demand 이상치 (train<2025) ===')
    print(f'  min {lo:.0f} | 1% {p01:.0f} | 중앙 {med:.0f} | 99% {p99:.0f} | max {hi:.0f} | IQR {iqr:.0f}')
    print(f'  min이 Q1 아래 {(q1-lo)/iqr:.2f} IQR | max가 Q3 위 {(hi-q3)/iqr:.2f} IQR | 본문1~99%={ (p99-p01)/(hi-lo):.3f}')
    print(f'  잔차 |z|>3.5 = {int((np.abs(z)>3.5).sum())} ({100*(np.abs(z)>3.5).mean():.3f}%) | |z|>5 = {int((np.abs(z)>5).sum())}')

    fig, ax = plt.subplots(4, 1, figsize=(11, 9), sharex=True)
    ax[0].plot(s.index, s.values, lw=0.4, color='#1f4e79'); ax[0].set_ylabel('원본'); ax[0].set_title('MSTL 분해 — 타깃 real_demand_land (일24h·주168h)')
    ax[1].plot(res.trend.index, res.trend.values, lw=0.7, color='#c00000'); ax[1].set_ylabel('추세')
    seas = res.seasonal.iloc[:, 0]; ax[2].plot(seas.index[:24*14], seas.values[:24*14], lw=0.6, color='#548235'); ax[2].set_ylabel('일주기\n(첫2주)')
    zf = mad_z(rem.values); m = np.abs(zf) > 3.5
    ax[3].plot(rem.index, rem.values, lw=0.3, color='#7f7f7f')
    ax[3].scatter(rem.index[m], rem.values[m], s=6, color='#e8000b', zorder=3, label=f'|z|>3.5 ({int(m.sum())}개)')
    ax[3].axhline(0, color='k', lw=0.4); ax[3].set_ylabel('잔차'); ax[3].legend(fontsize=8)
    for a in ax: a.axvline(pd.Timestamp(TRAIN_END), color='navy', ls='--', lw=0.8)
    fig.tight_layout(); fig.savefig(os.path.join(HERE, 'mstl_demand.png'), dpi=110); plt.close(fig)
    print('  그림: mstl_demand.png')


# ───────────────── (B) 낮 과대예측 ↔ solar_rad ─────────────────
def part_b():
    hist = load_hist()
    with sqlite3.connect(DB) as con:
        pr = pd.read_sql("SELECT timestamp, horizon_d, est_demand_land AS pred FROM est_horizon_land_raw "
                         "WHERE model='patchtst_lt'", con, parse_dates=['timestamp'])
    g = pr.merge(hist[['dem', 'solar_rad', 'temp_c']], left_on='timestamp', right_index=True, how='inner')
    g = g[(g['dem'] > 0) & g['pred'].notna()].copy()
    g['bias'] = (g['pred'] - g['dem']) / g['dem'] * 100
    g['hour'] = g['timestamp'].dt.hour
    g['month'] = g['timestamp'].dt.month
    g['season'] = g['month'].map(M.SEASON)
    print(f"\n=== (B) 보정전 v4 bias 진단 (n={len(g)}, 지평 전체) ===")

    # 1) 시각별 bias
    by_h = g.groupby('hour')['bias'].mean()
    print('  시각별 bias(%) 09~15시:', {h: round(by_h[h], 2) for h in range(9, 16)})

    # 2) 낮(09~15)에서 solar_rad 사분위별 bias — '햇빛 셀수록 더 과대?'
    day = g[(g['hour'] >= 9) & (g['hour'] <= 15)].copy()
    day['solar_q'] = pd.qcut(day['solar_rad'], 4, labels=['Q1(흐림)', 'Q2', 'Q3', 'Q4(맑음)'])
    sq = day.groupby('solar_q', observed=True)['bias'].agg(['mean', 'count'])
    print('\n  [낮 09~15시] solar_rad 사분위별 평균 bias(%):')
    print(sq.round(2).to_string())
    corr = day[['solar_rad', 'bias']].corr().iloc[0, 1]
    print(f'  낮 bias ~ solar_rad 상관계수 r = {corr:.3f}  (+면 맑을수록 과대)')

    # 3) 계절×낮 solar 사분위 (봄 덕커브 확인)
    print('\n  [낮] 계절별 × solar 사분위 bias(%):')
    pv = day.pivot_table(index='season', columns='solar_q', values='bias', aggfunc='mean', observed=True)
    print(pv.round(2).to_string())

    # 4) BTM+PPA 태양광 성장 (연도별 한낮 12~14시 평균) — 근본원인 맥락
    hist2 = hist.copy(); hist2['btm_ppa'] = hist2['gen_solar_btm_kr'].fillna(0) + hist2['gen_solar_ppa_kr'].fillna(0)
    noon = hist2[(hist2.index.hour >= 12) & (hist2.index.hour <= 14)]
    yr = noon.groupby(noon.index.year)['btm_ppa'].mean()
    print('\n  한낮(12~14시) BTM+PPA 태양광 평균(MW) 연도별:')
    print({int(y): round(v, 0) for y, v in yr.items() if pd.notna(v)})

    # 그림: (좌) 낮 solar 사분위 bias, (우) BTM 성장
    fig, ax = plt.subplots(1, 2, figsize=(13, 4.5))
    sq['mean'].plot(kind='bar', ax=ax[0], color='#c0504d')
    ax[0].axhline(0, color='k', lw=0.6); ax[0].set_title('낮(09~15시) solar_rad 사분위별 예측 bias(%)\n(+ = 과대예측)')
    ax[0].set_ylabel('bias %'); ax[0].tick_params(axis='x', rotation=0)
    yr2 = yr.dropna(); ax[1].bar([str(int(y)) for y in yr2.index], yr2.values, color='#4f81bd')
    ax[1].set_title('한낮(12~14시) BTM+PPA 태양광 평균(MW)\n— 계량수요 한낮 억제폭의 성장')
    ax[1].set_ylabel('MW')
    fig.tight_layout(); fig.savefig(os.path.join(HERE, 'daytime_solar_bias.png'), dpi=110); plt.close(fig)
    print('\n  그림: daytime_solar_bias.png')


if __name__ == '__main__':
    part_a()
    part_b()

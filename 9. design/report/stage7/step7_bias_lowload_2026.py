# -*- coding: utf-8 -*-
"""7단계 진단 · 2026 장마 저부하 구간 발전용 가스 과대예측 (집 양식).

목적: 6/20~7/5 실측 가스가 20,000MW 아래로 내려간 저부하 레짐에서 v3 모델이
      구조적으로 과대예측함을 보인다. (예보품질이 아니라 저부하 자체가 원인 → D+1~3 단지평)
데이터: input_data_land_check.db (서버 최신 스냅샷) — historical(실측) vs est_horizon_land(예측)
실행: python step7_bias_lowload_2026.py  → 같은 폴더에 PNG + CSV 생성
"""
import os, sqlite3
import numpy as np, pandas as pd
import matplotlib as mpl, matplotlib.pyplot as plt

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, '..', '..', '..'))
DB = os.path.join(ROOT, '1. data_fetcher_and_db', 'temp_DB', 'input_data_land_check.db')

# ======================================================================
#  ▼▼▼  바꿀 값(색·라벨·문구·축)은 여기 모여 있습니다  ▼▼▼
# ======================================================================
INK, MUTED, SOFT = '#2d3142', '#4f5d75', '#7a8399'
ACT_C  = '#4f5d75'      # 실측 = 짙은 회청
PRED_C = '#eb6c36'      # 예측 = 주황
FILL_C = '#f2b8a2'      # 과대예측 음영
RULE   = '#d9dce3'
BAR_HI = '#eb6c36'      # 20k 이하 = 강조
BAR_LO = '#9aa0ac'      # 20k 이상 = 회색

WIN_S, WIN_E = '2026-06-20', '2026-07-06'
SUP  = '2026 장마철 발전용 가스 예측 편향 진단  (6/20~7/5, 예측거리 D+1~3)'
# ======================================================================

mpl.rcParams.update({
    'font.family': 'Malgun Gothic', 'axes.unicode_minus': False,
    'figure.facecolor': 'white', 'axes.facecolor': 'white', 'savefig.facecolor': 'white',
    'axes.edgecolor': MUTED, 'axes.labelcolor': INK, 'text.color': INK,
    'xtick.color': MUTED, 'ytick.color': MUTED, 'figure.dpi': 150,
})

def clean(ax):
    for s in ('top', 'right'): ax.spines[s].set_visible(False)
    for s in ('left', 'bottom'): ax.spines[s].set_color(RULE)
    ax.tick_params(length=0)

def _save(fig, path):
    for ax in fig.axes:
        for lab in ax.get_xticklabels() + ax.get_yticklabels():
            lab.set_fontweight('bold')
    fig.savefig(path, bbox_inches='tight', dpi=150)
    plt.close(fig)

# ── 데이터 ────────────────────────────────────────────────────────────
con = sqlite3.connect(DB)
h = pd.read_sql("SELECT timestamp, gen_gas_kr AS act FROM historical", con, parse_dates=['timestamp'])
e = pd.read_sql(f"SELECT timestamp, horizon_d, est_gas_gen_land AS pred FROM est_horizon_land "
                f"WHERE timestamp>='{WIN_S}' AND timestamp<'{WIN_E}'", con, parse_dates=['timestamp'])
con.close()
m = e.merge(h, on='timestamp').dropna(subset=['act', 'pred'])
m['err'] = m['pred'] - m['act']
m['hour'] = m.timestamp.dt.hour
s = m[m.horizon_d <= 3].copy()          # 단지평 = 예보품질 영향 최소

# 왼쪽: 24시간 평균 실측 vs 예측
hr = s.groupby('hour').agg(act=('act', 'mean'), pred=('pred', 'mean')).reindex(range(24))

# 오른쪽: 실측 가스 구간별 평균 편향 (D+1~2 = 가장 정직)
s2 = m[m.horizon_d <= 2].copy()
edges = [0, 12000, 15000, 18000, 20000, 25000, 40000]
labs = ['~12k', '12–15k', '15–18k', '18–20k', '20–25k', '25k~']
s2['bk'] = pd.cut(s2.act, edges, labels=labs)
bar = s2.groupby('bk', observed=True).err.mean()

# ── 그림 ──────────────────────────────────────────────────────────────
fig, (axL, axR) = plt.subplots(1, 2, figsize=(11.2, 4.5), gridspec_kw={'wspace': 0.28})

# 왼쪽 패널
axL.fill_between(hr.index, hr.act, hr.pred, color=FILL_C, alpha=0.55, zorder=1, label='과대예측 폭')
axL.plot(hr.index, hr.act,  color=ACT_C,  lw=2.6, zorder=3, label='실측 가스')
axL.plot(hr.index, hr.pred, color=PRED_C, lw=2.6, zorder=3, label='모델 예측')
axL.set_title('하루 24시간 평균 — 예측이 항상 실측 위', fontsize=12.5, fontweight='bold', color=INK, pad=10)
axL.set_xlabel('시각 (시)', fontsize=10.5); axL.set_ylabel('발전용 가스 (MW)', fontsize=10.5)
axL.set_xticks([0, 4, 8, 12, 16, 20, 23]); axL.set_xlim(0, 23)
axL.set_ylim(6000, 24000)
axL.legend(loc='upper left', frameon=False, fontsize=9.8, handlelength=1.4)
clean(axL)
# 밤 구간 화살표 주석
axL.annotate('밤·새벽 과대 최악\n(+19~37%)', xy=(4, hr.loc[4, 'pred']), xytext=(6.2, 21500),
             fontsize=9.5, color=PRED_C, fontweight='bold', ha='left',
             arrowprops=dict(arrowstyle='->', color=PRED_C, lw=1.4))

# 오른쪽 패널
colors = [BAR_HI if labs.index(str(b)) <= 3 else BAR_LO for b in bar.index]
xb = np.arange(len(bar))
axR.bar(xb, bar.values, color=colors, width=0.68, zorder=3)
for x, v in zip(xb, bar.values):
    axR.text(x, v + 60, f'+{v:,.0f}', ha='center', va='bottom', fontsize=9.6, fontweight='bold',
             color=(BAR_HI if labs.index(str(bar.index[x])) <= 3 else MUTED))
axR.axhline(0, color=MUTED, lw=0.8)
axR.set_title('실측 가스 수준별 평균 편향 — 20k 아래에 집중', fontsize=12.5, fontweight='bold', color=INK, pad=10)
axR.set_xlabel('실측 발전용 가스 구간 (MW)', fontsize=10.5); axR.set_ylabel('평균 편향  (예측 빼기 실측, MW)', fontsize=10.5)
axR.set_xticks(xb); axR.set_xticklabels(bar.index, fontsize=9.8)
axR.set_ylim(0, max(bar.values) * 1.20)
clean(axR)
axR.text(4.5, max(bar.values) * 1.12, '저부하(20k↓)에 집중\n+1,400~2,400MW 과대', color=BAR_HI,
         fontsize=9.8, fontweight='bold', ha='center', va='top')

fig.suptitle(SUP, fontsize=13.5, fontweight='bold', color=INK, y=1.02, x=0.02, ha='left')
_save(fig, os.path.join(HERE, 'step7_bias_lowload_2026.png'))

# CSV 근거 저장
hr.round(0).to_csv(os.path.join(HERE, 'bias_lowload_hourly.csv'), encoding='utf-8-sig')
bar.round(0).to_csv(os.path.join(HERE, 'bias_lowload_bucket.csv'), encoding='utf-8-sig')
print('saved step7_bias_lowload_2026.png')
print('D+1~3 hourly mean bias(MW):', round((hr.pred - hr.act).mean(), 0))
print(bar.round(0).to_dict())

# -*- coding: utf-8 -*-
"""7단계 · 해마다 커지는 '숨은 태양광' (연도별 5월 첫째 주).
데이터: land_renew_reconstructed.parquet — 총수요(true_demand) - 전력시장 수요(real_demand_land)
        = 자가용(BTM)·PPA 태양광 발전(btm_recon + ppa_recon). 2024년까지 역추정, 이후 실측.
연도별(2020~2025) 5월 1~7일 평균 하루 프로파일로, 숨은 태양광이 매년 커지는 것을 보여줍니다.
실행: python step7_gap_yearly.py  → step7_gap_yearly.png 생성
"""
import os
import numpy as np, pandas as pd
import matplotlib as mpl, matplotlib.pyplot as plt

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, '..', '..', '..'))
PQ = os.path.join(ROOT, '1. data_fetcher_and_db', 'second_dataset', 'data', 'land_renew_reconstructed.parquet')

# ======================================================================
#  ▼▼▼  바꿀 값(색·라벨·문구·기간)은 여기 모여 있습니다  ▼▼▼
# ======================================================================
INK, MUTED, SOFT, ACCENT = '#2d3142', '#4f5d75', '#7a8399', '#eb6c36'
RULE = '#d9dce3'
YEARS = [2021, 2025]      # 2022는 역추정 자료 공백으로 제외
MONTH, DAY_FROM, DAY_TO = 5, 1, 32          # 5월 한 달 [from, to)

TITLE    = "해마다 커지는 ‘숨은 태양광’"
SUBTITLE = "총수요와 전력시장 수요의 한낮 차이 — 지붕 위 자가용·PPA 태양광 (해마다 5월, 하루 평균)"
YLABEL   = "숨은 태양광 = 두 수요의 차이 (MW)"
XLABEL   = "하루 24시간"
CAPTION  = ("출처: 전력거래소 계통 실측 + 자가용·PPA 역추정(2024년까지 추정, 2025년 실측). 두 수요의 차이는 "
            "계량에 안 잡히는 자가용(BTM)·PPA 태양광입니다. 2022년은 역추정 자료 공백으로 제외했습니다.")
# ======================================================================

mpl.rcParams.update({
    'font.family': 'Malgun Gothic', 'axes.unicode_minus': False,
    'figure.facecolor': 'white', 'axes.facecolor': 'white', 'savefig.facecolor': 'white',
    'axes.edgecolor': MUTED, 'axes.labelcolor': INK, 'text.color': INK,
    'xtick.color': MUTED, 'ytick.color': MUTED, 'figure.dpi': 150,
})

r = pd.read_parquet(PQ)
r['timestamp'] = pd.to_datetime(r['timestamp'])
r['gap'] = r['btm_recon'].fillna(0) + r['ppa_recon'].fillna(0)
r['year'] = r.timestamp.dt.year; r['hour'] = r.timestamp.dt.hour

# 연도별 색: 옛해=옅은 회색 → 최근=강조 주황
def lerp(c1, c2, t):
    a = np.array(mpl.colors.to_rgb(c1)); b = np.array(mpl.colors.to_rgb(c2))
    return tuple(a + (b - a) * t)
N = len(YEARS)
colors = [lerp('#c7cdd8', ACCENT, i / (N - 1)) for i in range(N)]

fig, ax = plt.subplots(figsize=(7.8, 4.7))
peaks = {}
for yr, col in zip(YEARS, colors):
    w = r[(r.year == yr) & (r.timestamp.dt.month == MONTH) &
          (r.timestamp.dt.day >= DAY_FROM) & (r.timestamp.dt.day < DAY_TO)]
    if len(w) == 0:
        continue
    prof = w.groupby('hour')['gap'].mean().reindex(range(24))
    lw = 3.0 if yr == YEARS[-1] else 2.0
    ax.plot(prof.index, prof.values, color=col, lw=lw, label=str(yr),
            marker='o', ms=3.2, markeredgecolor='white', markeredgewidth=0.5,
            zorder=3 + (yr == YEARS[-1]))
    peaks[yr] = float(np.nanmax(prof.values))
    print(f'{yr}: 한낮 최대 숨은태양광 {peaks[yr]:.0f} MW')

# 최근/최초 연도 끝 라벨
ax.annotate(f'{YEARS[-1]}년\n약 {peaks[YEARS[-1]]/1000:.0f},000 MW',
            xy=(12, peaks[YEARS[-1]]), xytext=(15.4, peaks[YEARS[-1]] + 600),
            fontsize=9.3, color=ACCENT, fontweight='bold', ha='left', va='center')
ax.annotate(f'{YEARS[0]}년\n거의 없음',
            xy=(12, peaks[YEARS[0]]), xytext=(14.5, peaks[YEARS[0]] + 2200),
            fontsize=9.0, color=SOFT, fontweight='bold', ha='left', va='center',
            arrowprops=dict(arrowstyle='->', color=SOFT, lw=1.0))

ax.set_xlim(0, 23); ax.set_ylim(0, max(peaks.values()) * 1.18)
ax.set_xticks([0, 6, 12, 18, 23]); ax.set_xticklabels(['0시', '6시', '12시', '18시', '24시'], fontsize=9.5)
ax.set_xlabel(XLABEL, fontsize=10)
ax.set_ylabel(YLABEL, fontsize=10)
ax.set_title(TITLE, fontsize=14.5, fontweight='bold', color=INK, loc='left', pad=30)
ax.text(0, 1.035, SUBTITLE, transform=ax.transAxes, fontsize=9.2, color=SOFT, ha='left')
ax.legend(loc='upper left', frameon=False, fontsize=9.0, ncol=2, title='연도',
          title_fontsize=8.5, handlelength=1.6)

for s in ('top', 'right'): ax.spines[s].set_visible(False)
for s in ('left', 'bottom'): ax.spines[s].set_color(RULE)
ax.tick_params(length=0); ax.yaxis.grid(True, alpha=0.18); ax.set_axisbelow(True)
fig.text(0.012, 0.005, CAPTION, fontsize=8.0, color=MUTED)
fig.subplots_adjust(top=0.82, bottom=0.18, left=0.10, right=0.97)
fig.savefig(os.path.join(HERE, 'step7_gap_yearly.png'), bbox_inches='tight', dpi=150)
plt.close(fig)
print('saved step7_gap_yearly.png')

# -*- coding: utf-8 -*-
"""7단계 · 총수요 vs 전력시장 수요 (차이 = 자가용·PPA 발전).
데이터: historical(gen_total_kr=총수요, real_demand_land=전력시장 수요) — 최근 7일.
두 수요의 차이가 곧 '계량에 안 잡히는' 자가용(BTM)·PPA 태양광 발전을 시사합니다.
실행: python step7_demand_gap.py  → step7_demand_gap.png 생성
"""
import os, sqlite3
import numpy as np, pandas as pd
import matplotlib as mpl, matplotlib.pyplot as plt
import matplotlib.dates as mdates

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, '..', '..', '..'))
DB = os.path.join(ROOT, '1. data_fetcher_and_db', 'data', 'input_data_land.db')

# ======================================================================
#  ▼▼▼  바꿀 값(색·라벨·문구·기간)은 여기 모여 있습니다  ▼▼▼
# ======================================================================
INK, MUTED, SOFT, ACCENT = '#2d3142', '#4f5d75', '#7a8399', '#eb6c36'
C_TOTAL  = '#3b6ea5'   # 총수요(파랑)
C_MARKET = '#d4564b'   # 전력시장 수요(빨강)
C_GAP    = ACCENT      # 차이 영역
RULE     = '#d9dce3'

START, END = '2026-06-13', '2026-06-14'   # 7일 [START, END)
TITLE    = "‘총수요’와 ‘전력시장 수요’의 차이 — 숨은 태양광"
SUBTITLE = "지붕 위 자가용·PPA 태양광은 계량에 안 잡혀, 한낮 전력시장 수요만 끌어내립니다(최근 7일)"
YLABEL   = "수요 (MW)"
LAB_TOTAL, LAB_MARKET = "총수요 (자가용·PPA 포함)", "전력시장 수요 (계량분)"
# ======================================================================

mpl.rcParams.update({
    'font.family': 'Malgun Gothic', 'axes.unicode_minus': False,
    'figure.facecolor': 'white', 'axes.facecolor': 'white', 'savefig.facecolor': 'white',
    'axes.edgecolor': MUTED, 'axes.labelcolor': INK, 'text.color': INK,
    'xtick.color': MUTED, 'ytick.color': MUTED, 'figure.dpi': 150,
})

con = sqlite3.connect(DB)
df = pd.read_sql("SELECT timestamp, gen_total_kr, real_demand_land, gen_solar_btm_kr, gen_solar_ppa_kr "
                 "FROM historical ORDER BY timestamp", con, parse_dates=['timestamp'])
con.close()
df = df[(df.timestamp >= START) & (df.timestamp < END)].copy()
df['gap'] = df.gen_total_kr - df.real_demand_land
df['btmppa'] = df.gen_solar_btm_kr.fillna(0) + df.gen_solar_ppa_kr.fillna(0)
peak_gap = df.gap.max()
print('rows', len(df), 'max gap', round(peak_gap), 'MW  gap~btm+ppa corr',
      round(df.gap.corr(df.btmppa), 4))

fig, ax = plt.subplots(figsize=(8.4, 4.5))
t = df.timestamp
ax.fill_between(t, df.real_demand_land, df.gen_total_kr, color=C_GAP, alpha=0.13, zorder=1,
                label='차이 = 자가용·PPA 태양광')
ax.plot(t, df.gen_total_kr,    color=C_TOTAL,  lw=1.8, zorder=3, label=LAB_TOTAL)
ax.plot(t, df.real_demand_land, color=C_MARKET, lw=1.8, zorder=3, label=LAB_MARKET)

# 가장 격차 큰 한낮에 화살표 주석
imax = df.gap.idxmax(); tmax = df.loc[imax, 'timestamp']
y_lo = df.loc[imax, 'real_demand_land']; y_hi = df.loc[imax, 'gen_total_kr']
ax.annotate('', xy=(tmax, y_hi), xytext=(tmax, y_lo),
            arrowprops=dict(arrowstyle='<->', color=ACCENT, lw=1.4))
ax.text(tmax, (y_lo + y_hi) / 2, f'  한낮 차이\n  약 {peak_gap/1000:.0f},000 MW', fontsize=9.2,
        color=ACCENT, fontweight='bold', ha='left', va='center')

ax.xaxis.set_major_locator(mdates.DayLocator())
ax.xaxis.set_major_formatter(mdates.DateFormatter('%m-%d'))
ax.set_xlim(df.timestamp.min(), df.timestamp.max())
ax.set_ylabel(YLABEL, fontsize=10)
ax.set_title(TITLE, fontsize=14, fontweight='bold', color=INK, loc='left', pad=30)
ax.text(0, 1.035, SUBTITLE, transform=ax.transAxes, fontsize=9.4, color=SOFT, ha='left')
ax.legend(loc='upper center', bbox_to_anchor=(0.5, -0.13), ncol=3, frameon=False, fontsize=9.0)

for s in ('top', 'right'): ax.spines[s].set_visible(False)
for s in ('left', 'bottom'): ax.spines[s].set_color(RULE)
ax.tick_params(length=0); ax.yaxis.grid(True, alpha=0.18); ax.set_axisbelow(True)
ax.tick_params(axis='x', labelsize=9.5)
fig.text(0.012, 0.005,
         "출처: 전력거래소 계통 실측 · 두 수요의 차이는 자가용(BTM)·PPA 태양광 발전과 일치합니다. "
         "이 숨은 태양광까지 반영해야 가스 예측이 정확해집니다.",
         fontsize=8.2, color=MUTED)
fig.subplots_adjust(top=0.82, bottom=0.20, left=0.08, right=0.97)
fig.savefig(os.path.join(HERE, 'step7_demand_gap.png'), bbox_inches='tight', dpi=150)
plt.close(fig)
print('saved step7_demand_gap.png')

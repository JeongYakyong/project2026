# -*- coding: utf-8 -*-
"""덕커브 역전 — 4·5월 계량수요(real_demand_land) 한낮 vs 새벽, 2022~2026.
BTM 태양광 폭증으로 한낮 계량수요가 새벽 아래로 내려가는(부호 역전) 현상 시각화.
(a) 연도별 24h 평균 형태(일평균=100% 정규화) (b) 한낮−새벽 차이 막대.
"""
from __future__ import annotations
import os, sys, sqlite3
try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass
import numpy as np, pandas as pd
import matplotlib; matplotlib.use('Agg')
import matplotlib.pyplot as plt
plt.rcParams['font.family'] = 'Malgun Gothic'; plt.rcParams['axes.unicode_minus'] = False

HERE = os.path.dirname(os.path.abspath(__file__))
DB = r'C:\Users\bjkim\Desktop\project2026\1. data_fetcher_and_db\data\input_data_land.db'
YEARS = [2022, 2023, 2024, 2025, 2026]
NOON, DAWN = (12, 13), (3, 4)        # 한낮 12~13시 / 새벽 3~4시

with sqlite3.connect(DB) as con:
    df = pd.read_sql('SELECT timestamp, real_demand_land AS dem FROM historical', con, parse_dates=['timestamp'])
df = df[df.dem > 0].copy()
df['year'] = df.timestamp.dt.year; df['month'] = df.timestamp.dt.month; df['hour'] = df.timestamp.dt.hour
df = df[df.month.isin([4, 5])]        # 4·5월

colors = ['#b0b0b0', '#7fb3d5', '#5499c7', '#e8770b', '#c0392b']   # 옛→최근(2025·26 강조색)
fig, ax = plt.subplots(1, 2, figsize=(12, 4.6))

# (a) 24h 형태 — 각 연도 일평균=100% 정규화
prof = df.groupby(['year', 'hour'])['dem'].mean().unstack(0)
norm = prof / prof.mean(axis=0) * 100
for i, y in enumerate(YEARS):
    if y in norm.columns:
        ax[0].plot(norm.index, norm[y], color=colors[i], lw=2.4 if y >= 2025 else 1.4,
                   label=f'{y}', zorder=3 if y >= 2025 else 2)
ax[0].axvspan(NOON[0] - 0.5, NOON[1] + 0.5, color='#fff2cc', zorder=0)
ax[0].axvspan(DAWN[0] - 0.5, DAWN[1] + 0.5, color='#e8f0fe', zorder=0)
ax[0].axhline(100, color='k', lw=0.5, ls=':')
ax[0].set_title('4·5월 평균 일중 수요 형태 (일평균=100%)')
ax[0].set_xlabel('시각'); ax[0].set_ylabel('일평균 대비 %'); ax[0].set_xticks(range(0, 24, 3))
ax[0].axhline(91.5, color='k', lw=1, ls=':')
ax[0].legend(title='연도', fontsize=9); ax[0].annotate('한낮', (12.5, ax[0].get_ylim()[0]), ha='center', fontsize=8, color='#b8860b')
ax[0].annotate('새벽', (3.5, ax[0].get_ylim()[0]), ha='center', fontsize=8, color='#3a6ea5')

# (b) 한낮 - 새벽 (MW) 막대 — 4월·5월 분리(역전 시점이 다름)
def nd(sub):
    return sub[sub.hour.isin(NOON)]['dem'].mean() - sub[sub.hour.isin(DAWN)]['dem'].mean()
apr = [nd(df[(df.year == y) & (df.month == 4)]) for y in YEARS]
may = [nd(df[(df.year == y) & (df.month == 5)]) for y in YEARS]
x = np.arange(len(YEARS)); w = 0.38
for off, vals, lab in [(-w / 2, apr, '4월'), (w / 2, may, '5월')]:
    bs = ax[1].bar(x + off, vals, w, label=lab,
                   color=['#5499c7' if v >= 0 else '#c0392b' for v in vals],
                   edgecolor='k', linewidth=0.4, hatch='' if lab == '4월' else '//')
    for b, v in zip(bs, vals):
        ax[1].annotate(f'{v:+,.0f}', (b.get_x() + b.get_width() / 2, v),
                       ha='center', va='bottom' if v >= 0 else 'top', fontsize=7.5)
ax[1].axhline(0, color='k', lw=0.9)
ax[1].set_xticks(x); ax[1].set_xticklabels([str(y) for y in YEARS])
ax[1].set_title('4월·5월 낮 수요 - 새벽 수요')
ax[1].set_ylabel('MW')
ax[1].legend(loc='lower left', fontsize=10)
#ax[1].annotate('4월 = 2025년부터 역전 · 5월 = 2026년 역전  (한낮 < 새벽 = 덕커브)',
#               (0.5, 0.99), xycoords='axes fraction', fontsize=8.5, color='#c0392b', ha='center', va='top')

fig.suptitle('낮의 전력수요가 새벽보다 적은 현상의 발생', fontsize=20)
fig.tight_layout(rect=[0, 0, 1, 0.96])
out = os.path.join(HERE, 'duck_curve_flip.png')
fig.savefig(out, dpi=120); plt.close(fig)
print('저장:', out)
print('4월 한낮-새벽(MW):', {y: round(v) for y, v in zip(YEARS, apr)})
print('5월 한낮-새벽(MW):', {y: round(v) for y, v in zip(YEARS, may)})

# -*- coding: utf-8 -*-
"""7단계 · 밤 시간대 발전 구성 변화(원전↓→가스↑) — 가스 모델 재학습의 근거 (집 양식).
데이터: historical(gen_gas_kr·gen_nuclear_kr·net_load_kr), 깊은 밤(0~6시)·같은 수요 구간만.
실행: python step7_night_regime.py  → 같은 폴더에 step7_night_regime.png 생성
"""
import os, sqlite3
import numpy as np, pandas as pd
import matplotlib as mpl, matplotlib.pyplot as plt

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, '..', '..', '..'))
DB = os.path.join(ROOT, '1. data_fetcher_and_db', 'data', 'input_data_land.db')

# ======================================================================
#  ▼▼▼  바꿀 값(색·라벨·문구·축)은 여기 모여 있습니다  ▼▼▼
# ======================================================================
INK, MUTED, SOFT, ACCENT = '#2d3142', '#4f5d75', '#7a8399', '#eb6c36'
RULE = '#d9dce3'
C_GAS  = ACCENT       # 가스 = 강조(주황)
C_NUKE = '#8aa0c0'    # 원전 = 차분한 청회색(보조)

TITLE    = '밤에 원전이 줄자, 그 자리를 가스가 메웠다'
SUBTITLE = '한밤중(0~6시)·전력 수요가 비슷한 날만 모아 비교 — 같은 조건인데 2026년 발전 구성이 달라짐'
YLABEL   = '평균 발전량 (GW)'
LAB_GAS  = '가스 발전'
LAB_NUKE = '원자력 발전'
NETLOAD_LO, NETLOAD_HI = 55000, 60000   # 같은 조건으로 통제할 잔여수요 구간(MW)
YEARS = [2023, 2024, 2025, 2026]
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

# ── 데이터 로드: 깊은 밤 + 같은 수요 구간 ───────────────────────────────
con = sqlite3.connect(DB)
d = pd.read_sql('SELECT timestamp, gen_gas_kr, gen_nuclear_kr, net_load_kr FROM historical',
                con, parse_dates=['timestamp'])
con.close()
d = d[(d.gen_gas_kr > 0) & (d.net_load_kr > 0)].copy()
d['year'] = d.timestamp.dt.year; d['hour'] = d.timestamp.dt.hour
night = d[(d.hour >= 0) & (d.hour <= 6) &
          (d.net_load_kr >= NETLOAD_LO) & (d.net_load_kr < NETLOAD_HI)]
g = night.groupby('year').agg(gas=('gen_gas_kr', 'mean'), nuke=('gen_nuclear_kr', 'mean'))
g = g.reindex(YEARS) / 1000.0   # MW → GW
print(g.round(2).to_string())
d_gas = (g.gas.iloc[-1] - g.gas.iloc[-2]) * 1000
d_nuke = (g.nuke.iloc[-1] - g.nuke.iloc[-2]) * 1000

# ════════════════════════════════════════════════════════════════════
fig, ax = plt.subplots(figsize=(7.8, 4.6))
x = np.arange(len(YEARS)); w = 0.38
ax.bar(x - w/2, g.gas,  w, color=C_GAS,  label=LAB_GAS,  zorder=3)
ax.bar(x + w/2, g.nuke, w, color=C_NUKE, label=LAB_NUKE, zorder=3)

# 값 라벨(막대 위)
for xi, (gv, nv) in zip(x, zip(g.gas, g.nuke)):
    ax.text(xi - w/2, gv + 0.3, f'{gv:.1f}', ha='center', va='bottom', fontsize=8.6, color=C_GAS, fontweight='bold')
    ax.text(xi + w/2, nv + 0.3, f'{nv:.1f}', ha='center', va='bottom', fontsize=8.6, color=MUTED)

# 2026 변화 강조 주석
ax.annotate(f'원전 약 {abs(d_nuke):,.0f}MW 줄고\n가스가 그만큼 메움',
            xy=(x[-1], g.gas.iloc[-1] + 0.3), xytext=(x[-1] - 1.25, max(g.gas.max(), g.nuke.max()) + 3.3),
            fontsize=9.3, color=ACCENT, fontweight='bold', ha='center', va='center',
            arrowprops=dict(arrowstyle='->', color=ACCENT, lw=1.3))

ax.set_xticks(x); ax.set_xticklabels([f'{y}년' for y in YEARS], fontsize=9.5)
ax.set_ylabel(YLABEL, fontsize=10)
ax.set_ylim(0, max(g.gas.max(), g.nuke.max()) + 6)
ax.set_title(TITLE, fontsize=14, fontweight='bold', color=INK, loc='left', pad=30)
ax.text(0, 1.03, SUBTITLE, transform=ax.transAxes, fontsize=9.5, color=SOFT, ha='left')
ax.legend(loc='upper left', frameon=False, fontsize=9.3, ncol=2, handlelength=1.4)
clean(ax)
fig.text(0.012, 0.005,
         f"한국전력거래소 실측 · 잔여수요 약 {NETLOAD_LO//1000}~{NETLOAD_HI//1000}GW 인 밤만 비교. "
         "기존 모델은 원전이 많던 과거만 배워 밤 가스를 적게 봤습니다 — 이 변화를 반영해 모델을 다시 학습했습니다.",
         fontsize=8.2, color=MUTED)
fig.subplots_adjust(top=0.82, bottom=0.16, left=0.09, right=0.97)
fig.savefig(os.path.join(HERE, 'step7_night_regime.png'), bbox_inches='tight', dpi=150)
plt.close(fig)
print('saved step7_night_regime.png')

# -*- coding: utf-8 -*-
"""7단계 · 발전용 가스의 일별 상관 — 잔여수요(net_load) vs 기온.
대상 = ★KOGAS 일별 발전 송출량(daliy_lng_gen_21-26.csv, TON). net_load·기온은 전국 일별 평균.
왼쪽: 가스 vs net_load(강한 직선상관) / 오른쪽: 가스 vs 기온(U자 — 추위·더위 모두 ↑ 라 단순상관 약함).
실행: python step7_gas_corr.py  → step7_gas_corr.png 생성
"""
import os, sqlite3
import numpy as np, pandas as pd
import matplotlib as mpl, matplotlib.pyplot as plt

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, '..', '..', '..'))
DB = os.path.join(ROOT, '1. data_fetcher_and_db', 'data', 'input_data_land.db')
SD = os.path.join(ROOT, '1. data_fetcher_and_db', 'second_dataset')

# ======================================================================
#  ▼▼▼  바꿀 값(색·라벨·문구)은 여기 모여 있습니다  ▼▼▼
# ======================================================================
INK, MUTED, SOFT, ACCENT = '#2d3142', '#4f5d75', '#7a8399', '#eb6c36'
RULE = '#d9dce3'
SEA_COL = {'겨울':'#4a78b5', '봄':'#5aa469', '여름':'#eb6c36', '가을':'#b58a3c'}
START = '2021-01-01'
TITLE    = "발전용 가스는 잔여수요와 강하게, 기온과는 약하게 상관"
SUBTITLE = "일별 상관 (KOGAS 발전 송출량 · 전국 평균, 2021~2026) — 기온은 추위·더위가 상쇄돼 약하고, net_load가 둘을 모두 담습니다"
XL_NET, XL_TMP = "잔여수요 net_load (GW)", "전국 평균기온 (°C)"
YL = "발전용 가스 송출량 (천 톤/일)"
# ======================================================================

mpl.rcParams.update({
    'font.family': 'Malgun Gothic', 'axes.unicode_minus': False,
    'figure.facecolor': 'white', 'axes.facecolor': 'white', 'savefig.facecolor': 'white',
    'axes.edgecolor': MUTED, 'axes.labelcolor': INK, 'text.color': INK,
    'xtick.color': MUTED, 'ytick.color': MUTED, 'figure.dpi': 150,
})

# ── 일별 데이터 ─────────────────────────────────────────────
con = sqlite3.connect(DB)
tc = ['temp_c_daegwallyeong','temp_c_wonju','temp_c_seosan','temp_c_pohang','temp_c_yeonggwang']
h = pd.read_sql(f"SELECT timestamp, net_load_kr, {','.join(tc)} FROM historical", con, parse_dates=['timestamp'])
con.close()
h['temp'] = h[tc].mean(axis=1); h['date'] = h.timestamp.dt.normalize()
dd = h.groupby('date').agg(netload=('net_load_kr','mean'), temp=('temp','mean'), n=('net_load_kr','size')).reset_index()
dd = dd[dd.n >= 20]
kg = pd.read_csv(os.path.join(SD,'data','daliy_lng_gen_21-26.csv'), encoding='cp949').rename(columns={'날짜':'date','공급량':'gas'})
kg['date'] = pd.to_datetime(kg['date'])
d = dd.merge(kg[['date','gas']], on='date', how='inner')
d = d[d.date >= START].copy()
sea = lambda m: {12:'겨울',1:'겨울',2:'겨울',3:'봄',4:'봄',5:'봄',6:'여름',7:'여름',8:'여름',9:'가을',10:'가을',11:'가을'}[m]
d['season'] = d.date.dt.month.map(sea)
d['gasK'] = d.gas/1000.0; d['nlG'] = d.netload/1000.0
rN = d.gas.corr(d.netload); rT = d.gas.corr(d.temp)
print('n=%d  r(net_load)=%.3f  r(temp)=%.3f' % (len(d), rN, rT))

fig, (axA, axB) = plt.subplots(1, 2, figsize=(8.8, 4.4), sharey=True)

def scatter(ax, xcol, seasons=True):
    for s, c in SEA_COL.items():
        g = d[d.season == s]
        ax.scatter(g[xcol], g.gasK, s=9, c=c, alpha=0.38, edgecolors='none', zorder=2, label=s)
    for sp in ('top','right'): ax.spines[sp].set_visible(False)
    for sp in ('left','bottom'): ax.spines[sp].set_color(RULE)
    ax.tick_params(length=0); ax.grid(True, alpha=0.16); ax.set_axisbelow(True)

# (A) net_load — 직선 적합
scatter(axA, 'nlG')
xa = np.linspace(d.nlG.min(), d.nlG.max(), 50)
ca = np.polyfit(d.nlG, d.gasK, 1)
axA.plot(xa, np.polyval(ca, xa), color=INK, lw=2.2, zorder=4)
axA.set_xlabel(XL_NET, fontsize=10.5); axA.set_ylabel(YL, fontsize=10.5)
axA.text(0.04, 0.93, f'r = {rN:.2f}', transform=axA.transAxes, fontsize=15, fontweight='bold',
         color=ACCENT, ha='left', va='top')
axA.text(0.04, 0.85, '강한 직선 상관', transform=axA.transAxes, fontsize=9.5, color=MUTED, ha='left', va='top')

# (B) 기온 — 2차(U자) 적합
scatter(axB, 'temp')
xb = np.linspace(d.temp.min(), d.temp.max(), 80)
cb = np.polyfit(d.temp, d.gasK, 2)
axB.plot(xb, np.polyval(cb, xb), color=INK, lw=2.2, zorder=4)
axB.set_xlabel(XL_TMP, fontsize=10.5)
axB.text(0.5, 0.93, f'r = {rT:.2f}', transform=axB.transAxes, fontsize=15, fontweight='bold',
         color='#7f9bb5', ha='center', va='top')
axB.text(0.5, 0.85, '추우면 난방·더우면 냉방 → 양쪽 다 ↑\n(상쇄되어 단순상관 약함)', transform=axB.transAxes,
         fontsize=9, color=MUTED, ha='center', va='top')

fig.suptitle(TITLE, fontsize=14.5, fontweight='bold', color=INK, x=0.012, ha='left', y=1.02)
fig.text(0.012, 0.945, SUBTITLE, fontsize=9.3, color=SOFT, ha='left')
handles = [plt.Line2D([0],[0], marker='o', ls='', mfc=c, mec='none', ms=7, label=s) for s,c in SEA_COL.items()]
fig.legend(handles=handles, loc='lower center', bbox_to_anchor=(0.5, -0.03), ncol=4, frameon=False, fontsize=9.5)
fig.text(0.012, -0.115,
         "출처: 전력거래소 계통 + KOGAS 일별 발전 송출량(corr 0.97·0.1526 ton/MWh로 정렬). n=%d일. "
         "기온 단순상관은 약하지만, net_load는 추위·더위로 생기는 수요를 모두 담아 발전용 가스를 강하게 설명합니다." % len(d),
         fontsize=8.0, color=MUTED, ha='left')
fig.subplots_adjust(top=0.86, bottom=0.16, left=0.085, right=0.985, wspace=0.08)
fig.savefig(os.path.join(HERE, 'step7_gas_corr.png'), bbox_inches='tight', dpi=150)
plt.close(fig)
print('saved step7_gas_corr.png')

# -*- coding: utf-8 -*-
"""7단계 · 발전용 가스의 역할 (실제 데이터 기반 덕 커브).
데이터: powerSource_20260612.xlsx (전력거래소 계통, 2026-06-12~19, 5분 단위) → 1시간 단위 변환 → 8일 평균 하루 프로파일.
발전원을 3범주(기저·신재생·가스)로 묶어, 가스가 '신재생이 비운 자리'를 메우는 모습을 보여줍니다.
실행: python step7_concept.py  → step7_concept.png + powerSource_hourly.csv 생성
"""
import os
import numpy as np, pandas as pd
import matplotlib as mpl, matplotlib.pyplot as plt

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, '..', '..', '..'))
XLSX = os.path.join(ROOT, '1. data_fetcher_and_db', 'second_dataset', 'powerSource_20260612.xlsx')

# ======================================================================
#  ▼▼▼  바꿀 값(색·라벨·문구·범주)은 여기 모여 있습니다  ▼▼▼
# ======================================================================
INK, MUTED, SOFT, ACCENT = '#2d3142', '#4f5d75', '#7a8399', '#eb6c36'
C_BASE  = '#dfe3ea'   # 기저(원자력·석탄 등)
C_RENEW = '#a9cbe8'   # 신재생(태양광·풍력)
C_GAS   = '#f4b896'   # 발전용 가스(강조 계열, 옅게)
RULE    = '#d9dce3'

TITLE    = "가스는 신재생이 비운 자리를 메웁니다"
SUBTITLE = "하루 동안의 발전 구성(실측) — 발전용 가스는 수요에서 기저·신재생을 뺀 '나머지'를 맡습니다"
XLABEL   = "하루 24시간"
YLABEL   = "발전량 (MW)"
LAB_BASE, LAB_RENEW, LAB_GAS, LAB_DEMAND = "기저(원자력·석탄 등)", "신재생(태양광·풍력)", "발전용 가스", "전체 수요"
CAPTION  = ("출처: 전력거래소 계통 실측(2026-06-12~19, 5분 → 1시간 변환, 8일 평균). "
            "기저=원자력·석탄·수력·유류, 신재생=태양광·풍력 등. 양수(저장)는 제외했습니다.")

# 범주별 묶음(엑셀 한글 열 이름)
G_BASE  = ['원자력', '유연탄', '국내탄', '수력', '유류']
G_RENEW = ['태양광(BTM,추정)', '태양광(PPA,추정)', '태양광(전력시장)', '풍력', '신재생']
G_GAS   = ['가스']
# ======================================================================

mpl.rcParams.update({
    'font.family': 'Malgun Gothic', 'axes.unicode_minus': False,
    'figure.facecolor': 'white', 'axes.facecolor': 'white', 'savefig.facecolor': 'white',
    'axes.edgecolor': MUTED, 'axes.labelcolor': INK, 'text.color': INK,
    'xtick.color': MUTED, 'ytick.color': MUTED, 'figure.dpi': 150,
})

# ── 엑셀 로드 → 1시간 단위 변환 ─────────────────────────────────
raw = pd.read_excel(XLSX)
dt = pd.to_datetime(raw['날짜'].astype(str) + ' ' + raw['시간'].astype(str))
num = raw.drop(columns=['날짜', '시간']).set_index(dt)
hourly = num.resample('1h').mean()                       # 5분 → 1시간
hourly.to_csv(os.path.join(HERE, 'powerSource_hourly.csv'), encoding='utf-8-sig')

# 8일 평균 하루 프로파일(시각별 평균)
prof = hourly.groupby(hourly.index.hour).mean()
prof = prof.reindex(range(24))
base  = prof[G_BASE].sum(axis=1).values
renew = prof[G_RENEW].sum(axis=1).values
gas   = prof[G_GAS].sum(axis=1).values
demand = base + renew + gas
h = np.arange(24)
print('가스 최소시각 %dh(%.0f MW) / 최대시각 %dh(%.0f MW)'
      % (int(np.argmin(gas)), gas.min(), int(np.argmax(gas)), gas.max()))

fig, ax = plt.subplots(figsize=(7.8, 4.7))
y1 = base; y2 = base + renew; y3 = base + renew + gas
ax.fill_between(h, 0,  y1, color=C_BASE,  zorder=1, label=LAB_BASE)
ax.fill_between(h, y1, y2, color=C_RENEW, zorder=1, label=LAB_RENEW)
ax.fill_between(h, y2, y3, color=C_GAS,   zorder=1, label=LAB_GAS)
ax.plot(h, demand, color=INK, lw=2.4, zorder=3, label=LAB_DEMAND)
ax.plot(h, y2, color='#6fa3cf', lw=1.0, alpha=0.7, zorder=2)   # 신재생 윗선

hsolar = int(np.argmax(renew)); hgas = int(np.argmax(gas))
# 한낮 — 태양광이 수요 증가를 대신 받아냄(가스 부담 완화)
ax.annotate("한낮\n태양광이 크게 늘어\n가스 부담을 덜어줍니다",
            xy=(hsolar, (y1[hsolar] + y2[hsolar]) / 2), xytext=(4.5, 70000),
            fontsize=9.2, color='#2f6aa0', fontweight='bold', ha='center', va='center',
            arrowprops=dict(arrowstyle='->', color='#2f6aa0', lw=1.3))
# 저녁 — 태양광이 지면 가스가 하루 최대로 메움
ax.annotate("저녁\n태양광이 지면\n가스가 하루 최대로 메웁니다",
            xy=(hgas, (y2[hgas] + y3[hgas]) / 2), xytext=(21, 78000),
            fontsize=9.2, color=ACCENT, fontweight='bold', ha='center', va='center',
            arrowprops=dict(arrowstyle='->', color=ACCENT, lw=1.3))

ax.set_xlim(0, 23); ax.set_ylim(0, demand.max() * 1.12)
ax.set_xticks([0, 6, 12, 18, 23]); ax.set_xticklabels(['0시', '6시', '12시', '18시', '24시'], fontsize=9.5)
ax.set_xlabel(XLABEL, fontsize=10)
ax.set_ylabel(YLABEL, fontsize=10, color=MUTED)
ax.set_title(TITLE, fontsize=14.5, fontweight='bold', color=INK, loc='left', pad=30)
ax.text(0, 1.035, SUBTITLE, transform=ax.transAxes, fontsize=9.3, color=SOFT, ha='left')

handles, labels = ax.get_legend_handles_labels()
order = [labels.index(x) for x in [LAB_DEMAND, LAB_GAS, LAB_RENEW, LAB_BASE]]
ax.legend([handles[i] for i in order], [labels[i] for i in order],
          loc='upper center', bbox_to_anchor=(0.5, -0.13), ncol=4, frameon=False, fontsize=9.0)

for s in ('top', 'right'): ax.spines[s].set_visible(False)
for s in ('left', 'bottom'): ax.spines[s].set_color(RULE)
ax.tick_params(length=0)
fig.text(0.012, 0.005, CAPTION, fontsize=8.0, color=MUTED)
fig.subplots_adjust(top=0.82, bottom=0.20, left=0.09, right=0.97)
fig.savefig(os.path.join(HERE, 'step7_concept.png'), bbox_inches='tight', dpi=150)
plt.close(fig)
print('saved step7_concept.png')

# -*- coding: utf-8 -*-
"""
천연가스 가격 변동성 — 연도별 가격 등락폭 (보고서용 2패널)

  왼쪽  ① 아시아 LNG 현물가격(JKM)   — 연도별 최저~최고 범위
  오른쪽 ② 미국 천연가스 가격(Henry Hub) — 연도별 최저~최고 범위

두 가격은 스케일이 매우 달라(JKM 최고 84 vs Henry Hub 최고 9.4) 패널을 나눈다.
막대는 그 해의 '최저가~최고가' 구간(세로 막대), 막대 위 숫자는 등락폭(최고-최저).

양식: 흰 배경 · 맑은 고딕 · 강조 주황(#eb6c36) — 9. design/drawing_rule.md 준수.

데이터 출처:
  · JKM       : S&P Global Commodity Insights(Platts) JKM(Japan Korea Marker) 현물가격
  · Henry Hub : 미국 에너지정보청(EIA) / NYMEX Henry Hub 천연가스 현물가격
  원자료: (이 폴더) gas_price_volatility.csv

실행:  python plot_gas_price_volatility.py  →  같은 폴더에 gas_price_volatility.png
"""
import os
import numpy as np
import pandas as pd
import matplotlib as mpl
from matplotlib.figure import Figure
from matplotlib.backends.backend_agg import FigureCanvasAgg

# ────────────────────────────────────────────────────────────────────────────
# ▼▼▼  보통 여기 값만 고치면 됩니다  ▼▼▼
# ────────────────────────────────────────────────────────────────────────────
# 연도 라벨 (CSV의 '2026 (YTD)' → 보기 좋게)
YEAR_LABELS = {'2026 (YTD)': '2026\n(연초~현재)'}

# 막대 색: 연도별 그라데이션 (옅은 색 → 진한 빨강, 위기 해 2022가 가장 진함은 데이터로 결정)
YEAR_GRAD = {'2022': '#8c1d1d', '2023': '#e3743a', '2024': '#f0a830',
             '2025': '#4a9d6a', '2026 (YTD)': '#eb6c36'}
C_TEXT  = '#1a1a1a'

# 글씨 크기 (문서 삽입용 — 크고 굵게)
FS_TICK    = 16   # 눈금 글씨
FS_AXLABEL = 17   # 축 제목
FS_TITLE   = 18   # 패널 제목
FS_VALUE   = 13   # 막대 위/안 숫자
FS_SUPTTL  = 23   # 전체 제목

BAR_W = 0.62
# ────────────────────────────────────────────────────────────────────────────
# ▲▲▲  여기까지  ▲▲▲
# ────────────────────────────────────────────────────────────────────────────

HERE = os.path.dirname(os.path.abspath(__file__))
CSV  = os.path.join(HERE, 'gas_price_volatility.csv')
OUT  = os.environ.get('CHART_OUTPUT', os.path.join(HERE, 'gas_price_volatility.png'))

mpl.rcParams['font.family'] = 'Malgun Gothic'
mpl.rcParams['axes.unicode_minus'] = False

# ── 데이터 ──────────────────────────────────────────────────────────────────
# 표 부분만 읽는다(7행: 헤더 + 5개 연도). 아래 출처 주석 줄은 건너뛴다.
df = pd.read_csv(CSV, nrows=5)
df = df.dropna(subset=['Year'])
years = df['Year'].astype(str).tolist()

# ── 공통: 축을 크고 굵게 ────────────────────────────────────────────────────
def style_axis(ax, title, ylabel=None):
    ax.set_title(title, fontsize=FS_TITLE, fontweight='bold', pad=12)
    if ylabel:
        ax.set_ylabel(ylabel, fontsize=FS_AXLABEL, fontweight='bold')
    ax.tick_params(axis='both', labelsize=FS_TICK, width=1.4, length=6)
    for lab in ax.get_xticklabels() + ax.get_yticklabels():
        lab.set_fontweight('bold')
    ax.grid(True, axis='y', color='#d8dbe0', lw=0.8, alpha=0.9)
    ax.set_axisbelow(True)
    for s in ax.spines.values():
        s.set_edgecolor('#b9bdc6')


def draw_panel(ax, lo_col, hi_col, rng_col, title, ylabel, ytop):
    x = np.arange(len(years))
    lo = df[lo_col].to_numpy(float)
    hi = df[hi_col].to_numpy(float)
    rng = df[rng_col].to_numpy(float)
    colors = [YEAR_GRAD.get(y, '#9aa3b2') for y in years]

    # 최저~최고 구간 막대 (floating bar)
    ax.bar(x, hi - lo, bottom=lo, width=BAR_W, color=colors,
           edgecolor='white', linewidth=1.0, zorder=3)

    for xi, l, h, r in zip(x, lo, hi, rng):
        # 막대 위: 등락폭(최고-최저) — 변동성의 핵심 숫자
        ax.text(xi, h + ytop * 0.018, f'등락폭 {r:g}', ha='center', va='bottom',
                fontsize=FS_VALUE, fontweight='bold', color=C_TEXT, zorder=5)
        # 막대 아래: 최저 ~ 최고 (한 줄로 — 짧은 막대에서도 겹치지 않음)
        ax.text(xi, l - ytop * 0.016, f'{l:g} ~ {h:g}', ha='center', va='top',
                fontsize=FS_VALUE, fontweight='bold', color=C_TEXT, zorder=5)

    ax.set_xticks(x)
    ax.set_xticklabels([YEAR_LABELS.get(y, y) for y in years])
    ax.set_ylim(0, ytop)
    style_axis(ax, title, ylabel)


# ── 그림 (1×2) ──────────────────────────────────────────────────────────────
fig = Figure(figsize=(15, 7.5))
FigureCanvasAgg(fig)
fig.patch.set_facecolor('white')
ax1 = fig.add_subplot(1, 2, 1)
ax2 = fig.add_subplot(1, 2, 2)
for ax in (ax1, ax2):
    ax.set_facecolor('white')

draw_panel(ax1, 'JKM_Min', 'JKM_Max', 'JKM_Range',
           '① 아시아 LNG 현물가격 (JKM)', '가격 ($/MMBtu)', ytop=95)
draw_panel(ax2, 'HH_Min', 'HH_Max', 'HH_Range',
           '② 미국 천연가스 가격 (Henry Hub)', '가격 ($/MMBtu)', ytop=11)

fig.suptitle('천연가스 가격 변동성 — 연도별 최저~최고 가격 범위',
             fontsize=FS_SUPTTL, fontweight='bold', y=0.985)

# 출처 (그림 하단)
src = ('자료: 아시아 LNG 현물가격(JKM) — S&P Global Commodity Insights(Platts) JKM 현물가격   |   '
       '미국 천연가스 가격(Henry Hub) — 미국 에너지정보청(EIA)·NYMEX 현물가격\n'
       '단위 $/MMBtu(백만BTU당 미국 달러).  2026년은 연초부터 현재까지 집계.')
fig.text(0.5, 0.015, src, ha='center', va='bottom', fontsize=11.5,
         color='#4f5d75', linespacing=1.5)

fig.subplots_adjust(left=0.07, right=0.97, top=0.88, bottom=0.16, wspace=0.18)
fig.savefig(OUT, dpi=150, facecolor='white')
print('saved:', OUT)

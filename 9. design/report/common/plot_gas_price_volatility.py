# -*- coding: utf-8 -*-
"""
천연가스 가격 변동성 — 연도별 가격 등락폭 (보고서용 1패널)

  한 그래프(같은 축)에 두 가격을 나란히 두어 변동성을 직접 비교한다.
   · 아시아 LNG 현물가격(JKM)   — 막대를 꽉 채움(solid)
   · 미국 천연가스 가격(Henry Hub) — 빗금(///)

같은 $/MMBtu 축에 올리면, JKM이 Henry Hub보다 훨씬 크게 출렁인다는 점이
한눈에 보인다(JKM 막대가 압도적으로 길고, Henry Hub 막대는 바닥에 깔린다).
막대 = 그 해의 '최저가~최고가' 구간, 막대 위 숫자 = 등락폭(최고-최저).

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
YEAR_LABELS = {'2026 (YTD)': '2026'}

# 제외할 연도 (2022는 JKM 84로 워낙 커서 빼면 세로축을 크게 줄일 수 있음)
EXCLUDE_YEARS = ['2022']

# 두 가격의 색 (연하게). JKM=강조 주황(채움), Henry Hub=차분한 청회색(빗금)
C_JKM   = '#f0a878'   # JKM 채움색 (연한 주황)
E_JKM   = '#d9572a'   # JKM 테두리
C_HH    = '#cfd6e0'   # Henry Hub 채움색 (연한 청회색)
E_HH    = '#5a6b86'   # Henry Hub 테두리·빗금색
C_TEXT  = '#1a1a1a'

# 글씨 크기 (문서 삽입용 — 크고 굵게)
FS_TICK    = 16   # 눈금 글씨
FS_AXLABEL = 17   # 축 제목
FS_VALUE   = 13   # 막대 숫자
FS_LEGEND  = 15   # 범례
FS_SUPTTL  = 22   # 전체 제목

BAR_W = 0.38      # 한 해에 두 막대가 나란히
YTOP  = 60        # 세로축 상한 ($/MMBtu)
# ────────────────────────────────────────────────────────────────────────────
# ▲▲▲  여기까지  ▲▲▲
# ────────────────────────────────────────────────────────────────────────────

HERE = os.path.dirname(os.path.abspath(__file__))
CSV  = os.path.join(HERE, 'gas_price_volatility.csv')
OUT  = os.environ.get('CHART_OUTPUT', os.path.join(HERE, 'gas_price_volatility.png'))

mpl.rcParams['font.family'] = 'Malgun Gothic'
mpl.rcParams['axes.unicode_minus'] = False
mpl.rcParams['hatch.linewidth'] = 1.4

# ── 데이터 ──────────────────────────────────────────────────────────────────
# 표 부분만 읽는다(헤더 + 5개 연도). 아래 출처 주석 줄은 건너뛴다.
df = pd.read_csv(CSV, nrows=5)
df = df.dropna(subset=['Year'])
df = df[~df['Year'].astype(str).isin(EXCLUDE_YEARS)].reset_index(drop=True)
years = df['Year'].astype(str).tolist()
x = np.arange(len(years))

# ── 그림 (1패널) ─────────────────────────────────────────────────────────────
fig = Figure(figsize=(11, 8))
FigureCanvasAgg(fig)
fig.patch.set_facecolor('white')
ax = fig.add_subplot(1, 1, 1)
ax.set_facecolor('white')

# JKM (왼쪽 막대, 꽉 채움) / Henry Hub (오른쪽 막대, 빗금)
ax.bar(x - BAR_W / 2, df['JKM_Max'] - df['JKM_Min'], bottom=df['JKM_Min'],
       width=BAR_W, color=C_JKM, edgecolor=E_JKM, linewidth=1.4, zorder=3,
       label='아시아 LNG 현물가격 (JKM)')
ax.bar(x + BAR_W / 2, df['HH_Max'] - df['HH_Min'], bottom=df['HH_Min'],
       width=BAR_W, facecolor=C_HH, edgecolor=E_HH, linewidth=1.4, hatch='///',
       zorder=3, label='미국 천연가스 가격 (Henry Hub)')


#def label_bar(xc, lo, hi, rng):
#    ax.text(xc, hi + YTOP * 0.012, f'{rng:g}', ha='center', va='bottom',
#            fontsize=FS_VALUE, fontweight='bold', color=C_TEXT, zorder=5)
#    ax.text(xc, lo - YTOP * 0.014, f'{lo:g}~{hi:g}', ha='center', va='top',
#            fontsize=FS_VALUE - 1.5, fontweight='bold', color=C_TEXT, zorder=5)


#for i in range(len(years)):
#    label_bar(x[i] - BAR_W / 2, df['JKM_Min'][i], df['JKM_Max'][i], df['JKM_Range'][i])
#    label_bar(x[i] + BAR_W / 2, df['HH_Min'][i], df['HH_Max'][i], df['HH_Range'][i])

# 핵심 메시지 주석 — JKM의 변동성이 압도적으로 크다
ax.annotate('JKM과 Henry Hub 연간 천연가스 가격 변동성 비교',
            xy=(x[0] - BAR_W / 4, df['JKM_Max'][0]), xytext=(0.5, 30),
            fontsize=FS_LEGEND, fontweight='bold', color='black', va='center',
            #arrowprops=dict(arrowstyle='->', color=E_JKM, lw=1.8),
            bbox=dict(boxstyle='round,pad=0.4', fc='white', ec=E_JKM, lw=1.2))

# 축·격자·테두리
ax.set_xticks(x)
ax.set_xticklabels([YEAR_LABELS.get(y, y) for y in years])
ax.set_ylim(0, YTOP)
ax.set_ylabel('가격 ($/MMBtu)', fontsize=FS_AXLABEL, fontweight='bold')
ax.tick_params(axis='both', labelsize=FS_TICK, width=1.4, length=6)
for lab in ax.get_xticklabels() + ax.get_yticklabels():
    lab.set_fontweight('bold')
ax.grid(True, axis='y', color='#d8dbe0', lw=0.8, alpha=0.9)
ax.set_axisbelow(True)
for s in ax.spines.values():
    s.set_edgecolor('#b9bdc6')
ax.legend(fontsize=FS_LEGEND, loc='upper right', framealpha=0.95,
          prop={'weight': 'bold'})

fig.suptitle('JKM과 Henry Hub 연간 천연가스 가격 변동성 비교',
             fontsize=FS_SUPTTL, fontweight='bold', y=0.97)

# 출처 (그림 하단)
src = ('출처: 아시아 LNG 현물가격(JKM) — S&P Global Commodity Insights(Platts), '
       '미국 천연가스 가격(Henry Hub) — 미국 에너지정보청(EIA)·NYMEX 현물가격\n'
       )
fig.text(0.05, 0.012, src, ha='left', va='bottom', fontsize=10.5,
         color='#4f5d75', linespacing=1.5)

fig.subplots_adjust(left=0.08, right=0.97, top=0.90, bottom=0.15)
fig.savefig(OUT, dpi=150, facecolor='white')
print('saved:', OUT)

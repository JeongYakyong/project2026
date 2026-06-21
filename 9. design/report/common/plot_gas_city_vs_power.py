# -*- coding: utf-8 -*-
"""
용도별 천연가스 공급량 비교 — 도시가스 vs 발전 (그림 복원 스크립트)

원본 그림: gas_yoy_change_city_vs_power.png (PNG만 남고 코드가 유실되어 복원).
입력: 한국가스공사_용도별 월 공급량_20260331.csv  (cp949, 컬럼=연도/월/용도/공급량[톤])
출력:
  - gas_yoy_change_city_vs_power.png  (좌: 전년대비 변화율 YoY / 우: 같은 달 연도별 변동폭)

실행: python plot_gas_city_vs_power.py
"""
import os
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import matplotlib as mpl

HERE = os.path.dirname(os.path.abspath(__file__))
CSV = os.path.join(HERE, '한국가스공사_용도별 월 공급량_20260331.csv')
OUT = os.path.join(HERE, 'gas_yoy_change_city_vs_power.png')

# 색: 도시가스=벽돌빨강, 발전=주황
C_CITY = "#2b91c0"
C_POWER = '#e8893a'

START = '2020-01'   # 그림 표시 구간 시작 (YoY는 직전연도 데이터 필요 → 내부적으로 전 구간 사용)

# ── 데이터 로드 (톤 → 천톤) ──────────────────────────────────
df = pd.read_csv(CSV, encoding='cp949')
df.columns = ['year', 'month', 'category', 'supply']
df['supply'] = df['supply'] / 1000.0  # 톤 → 천톤
df['date'] = pd.to_datetime(dict(year=df['year'], month=df['month'], day=1))

cats = {'도시가스': C_CITY, '발전': C_POWER}

# 용도별 월 시계열 (피벗)
piv = df.pivot_table(index='date', columns='category', values='supply', aggfunc='sum').sort_index()

# ── 그림 ─────────────────────────────────────────────────────
plt.style.use('seaborn-v0_8-whitegrid')
# 한글 폰트(맑은 고딕)는 style.use 뒤에 설정해야 초기화되지 않음
mpl.rcParams['font.family'] = 'Malgun Gothic'
mpl.rcParams['axes.unicode_minus'] = False

fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(20, 8))

# ① 전년대비 변화율(YoY): (당월 − 전년 같은 달) / 전년 같은 달 × 100
yoy = piv.pct_change(12) * 100.0
yoy_plot = yoy.loc[yoy.index >= START]
for cat, color in cats.items():
    # '발전'일 경우 굵기를 3.0으로, 아닐 경우 1.5로 설정
    line_width = 3.0 if cat == '발전' else 1.5
    
    ax1.plot(yoy_plot.index, yoy_plot[cat], marker='o', ms=4, lw=line_width,
             color=color, label=cat)
ax1.axhline(0, color='#333333', lw=1)
ax1.set_title('① 같은 달 전년대비 변화율 (YoY)', fontsize=15, fontweight='bold', pad=12)
plt.setp(ax1.get_xticklabels(), fontsize=13, fontweight='bold')
plt.setp(ax1.get_yticklabels(), fontsize=13, fontweight='bold')
ax1.set_ylabel('전년 같은 달 대비 변화율 (%)', fontsize=15, fontweight ='bold')
ax1.legend(fontsize=15, loc='upper right', bbox_to_anchor=(0.90, 1.0))

# ② 같은 달 연도별 변동폭: 각 캘린더월의 연도간 (최대 − 최소) / 평균 × 100
sub = df[df['date'] >= START]
months = list(range(1, 13))
bar_w = 0.4
x = np.arange(12)
for i, (cat, color) in enumerate(cats.items()):
    vals = []
    for m in months:
        s = sub[(sub['category'] == cat) & (sub['month'] == m)]['supply']
        vals.append((s.max() - s.min()) / s.mean() * 100.0 if len(s) else np.nan)
    ax2.bar(x + (i - 0.5) * bar_w, vals, width=bar_w, color=color, label=cat)
ax2.set_title('② 같은 달 연도별 변동폭', fontsize=15, fontweight='bold', pad=12)
ax2.set_ylabel('연도간 최대 최소 변동폭 (%)', fontsize=15, fontweight ='bold')
ax2.set_xticks(x)
ax2.set_xticklabels([f'{m}월' for m in months], fontsize=13, fontweight='bold')
plt.setp(ax2.get_yticklabels(), fontsize=13, fontweight='bold')
ax2.legend(fontsize=12, loc='upper right')

fig.suptitle('용도별 천연가스 공급량 변동 비교 — 도시가스 vs 발전 (2020~2026, 월별)',
             fontsize=30, fontweight='bold', y=0.98)
fig.text(0.5, 0.01,
         '자료: 한국가스공사 용도별 월 공급량(톤→천톤). ①전년 같은 달 대비 변화율. '
         '②각 캘린더월의 연도간 (최대−최소)/평균.',
         ha='center', fontsize=11, color='#888888')

fig.tight_layout(rect=[0, 0.03, 1, 0.95])
fig.savefig(OUT, dpi=130, bbox_inches='tight')
print('saved:', OUT)

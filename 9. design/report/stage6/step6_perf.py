# -*- coding: utf-8 -*-
"""6단계 · 태양광 예측 모델 성능 비교 (PatchTST vs LGBM).
출처: 6. land_solarwind_forecaster/nouse/model/tab/6-B_compare.csv
실행: python step6_perf.py   → 같은 폴더에 step6_perf.png 생성
"""
import os
import numpy as np
import matplotlib
import matplotlib.font_manager as fm
from matplotlib.figure import Figure
from matplotlib.backends.backend_agg import FigureCanvasAgg

# 맑은 고딕(시스템 폰트) 적용
for _f in ['Malgun Gothic', '맑은 고딕', 'Gulim']:
    if any(_f == f.name for f in fm.fontManager.ttflist):
        matplotlib.rcParams['font.family'] = _f
        break
matplotlib.rcParams['axes.unicode_minus'] = False

# ======================================================================
#  ▼▼▼  여기 값만 고치면 됩니다  ▼▼▼
# ======================================================================
HORIZONS = ['D+1', 'D+2', 'D+3']        # 예측 지평(가로축)
PATCHTST = [7.4, 7.0, 7.1]              # 딥러닝 낮시간 이용률 평균오차(%포인트)
LGBM     = [12.9, 13.0, 13.1]           # 트리   낮시간 이용률 평균오차(%포인트)

LABEL_PT = '딥러닝 (PatchTST)'
LABEL_LG = '트리 (LGBM)'
C_PT = '#eb6c36'   # 태양광 = 강조 주황
C_LG = '#9aa3b2'   # 비교군 = 회색

TITLE    = '태양광 예측 모델 성능 비교 — 딥러닝 vs 트리'
SUBTITLE = '낮 시간대 이용률 평균오차 · 실제 기상예보를 입력한 경우 (낮을수록 정확)'
YLABEL   = '이용률 평균오차 (%포인트)'
TAKEAWAY = '딥러닝(PatchTST)이 트리 모델(LGBM)보다 오차를 약 45% 줄였습니다'

INK   = '#1a1a1a'   # 본문 글자
MUTED = '#4f5d75'   # 보조 글자
# ======================================================================

output_path = os.environ.get(
    'CHART_OUTPUT',
    os.path.join(os.path.dirname(os.path.abspath(__file__)), 'step6_perf.png'))

x = np.arange(len(HORIZONS))
w = 0.36
fig = Figure(figsize=(7.4, 4.6))
FigureCanvasAgg(fig)
ax = fig.add_subplot(111)

b1 = ax.bar(x - w/2, PATCHTST, w, label=LABEL_PT, color=C_PT)
b2 = ax.bar(x + w/2, LGBM,     w, label=LABEL_LG, color=C_LG)

# 막대 위 값 라벨(막대와 안 겹치게 살짝 띄움)
for bars in (b1, b2):
    for r in bars:
        h = r.get_height()
        ax.text(r.get_x() + r.get_width()/2, h + 0.25, f'{h:.1f}',
                ha='center', va='bottom', fontsize=10, color=INK)

ax.set_ylim(0, max(LGBM) * 1.32)        # 위쪽 여백 — 값 라벨·요약 문구 자리
ax.set_xticks(x)
ax.set_xticklabels(HORIZONS, fontsize=11, color=INK)
ax.set_ylabel(YLABEL, fontsize=10.5, color=MUTED)

# 제목·부제(축 위쪽에 분리해서 — 그래프와 안 겹침)
ax.set_title(TITLE, fontsize=14, fontweight='bold', pad=30, loc='left', color=INK)
ax.text(0, 1.04, SUBTITLE, transform=ax.transAxes, fontsize=10, color=MUTED, va='bottom')

# 요약 문구(막대 위 빈 띠에 한 줄)
ax.text(0.5, 0.95, TAKEAWAY, transform=ax.transAxes, ha='center', va='top',
        fontsize=11, fontweight='bold', color=C_PT)

# 범례는 그래프 아래(막대·글자 안 가림)
ax.legend(loc='upper center', bbox_to_anchor=(0.5, -0.12), ncol=2,
          frameon=False, fontsize=10.5)

# 군더더기 제거
ax.spines[['top', 'right']].set_visible(False)
ax.spines[['left', 'bottom']].set_color('#7a8399')
ax.yaxis.grid(True, alpha=0.25)
ax.set_axisbelow(True)
ax.tick_params(colors=MUTED)

fig.savefig(output_path, dpi=150, bbox_inches='tight', facecolor='white')
print(output_path)

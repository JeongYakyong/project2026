# -*- coding: utf-8 -*-
"""#2 그림 — 태양광·풍력 이용률 예측 정확도: 단순 기준 vs 서비스 제공 모델, 지평별.

데이터 = perf_util_horizon_6.csv (정직 평가, 이용률 기준).
  · 서비스 제공 모델(재훈련 후): 태양광=PatchTST(D1-6)+신규 LGBM(D7-15) 블렌딩 · 풍력=신규 LGBM.
  · 기준선 = 기후값 평년(월×시각 평균) — 전 지평 서빙 가능한 단순 기준.
지표 = 이용률 예측 오차율(%). 낮을수록 정확. 태양광은 낮 시간 기준(밤은 0이라 제외).
출력: 6_perf_channels.png
"""
import os
import numpy as np, pandas as pd
import matplotlib as mpl, matplotlib.pyplot as plt

# ─────────────────────────────────────────────────────────────────────
# ▼▼▼ 여기 값만 바꾸면 그림이 바뀝니다 ▼▼▼
# ─────────────────────────────────────────────────────────────────────
INK, MUTED, SOFT, ACCENT = '#2d3142', '#4f5d75', '#7a8399', '#eb6c36'
SOLAR_C, WIND_C = '#c98a2e', '#3b6ea5'      # 태양광=호박색 · 풍력=파랑

TITLE    = '태양광 · 풍력발전 이용률 정확도 비교'
SUBTITLE = '태양광·풍력 이용률 예측 오차율 — 기후값 평년(단순 기준)과 비교 · 낮을수록 정확'
XLAB     = '예측 거리 (지평)'
YLAB     = '이용률 예측 오차율 (%)'
Y_MAX    = 56
LBL_SM = '태양광, 풍력 (서비스 제공 모델)'
LBL_SB = '태양광, 풍력 (기준선 : 평년값)'
LBL_WM = ' '#풍력 — 서비스 제공 모델
LBL_WB = ' '#풍력 — 기후값 평년'
TXT_SOLAR = ('태양광', 13.6, 26.0)        # 태양광 모델선 근처
TXT_WIND  = ('풍력', 13.6, 47.5)          # 풍력 모델선 근처
FOOT = ('평가 기간 2025-12~2026-06 · 각 발행 시점의 실제 일기예보를 보름 뒤까지 그대로 넣은 정직 평가. '
        '태양광은 낮 시간 기준(밤은 발전 0이라 제외). 기준선=같은 달·시각의 평년 평균값.')
FOOTER_TAG = 'STEP 6 · 전국 신재생 예측 · 2026-06'
# ─────────────────────────────────────────────────────────────────────
# ▲▲▲ 보통은 여기까지만 수정 ▲▲▲
# ─────────────────────────────────────────────────────────────────────

HERE = os.path.dirname(os.path.abspath(__file__))
d = pd.read_csv(os.path.join(HERE, 'perf_util_horizon_6.csv'))
H = d.horizon.values

mpl.rcParams.update({
    'font.family': 'Malgun Gothic', 'axes.unicode_minus': False,
    'figure.facecolor': 'white', 'axes.facecolor': 'white', 'savefig.facecolor': 'white',
    'axes.edgecolor': MUTED, 'axes.labelcolor': INK, 'text.color': INK,
    'xtick.color': MUTED, 'ytick.color': MUTED, 'figure.dpi': 150,
})

def _save(fig, path):
    for ax in fig.axes:
        for lab in ax.get_xticklabels() + ax.get_yticklabels():
            lab.set_fontweight('bold')
    fig.savefig(path, bbox_inches='tight', dpi=150)
    plt.close(fig)

fig, ax = plt.subplots(figsize=(6.0, 4.8))

# 기준선(기후값) = 파선 / 서비스 제공 모델 = 굵은 실선
ax.plot(H, d.solar_clim, color=SOLAR_C, lw=1.6, ls='--', alpha=0.9, zorder=2, label=LBL_SB)
ax.plot(H, d.wind_clim,  color=WIND_C,  lw=1.6, ls='--', alpha=0.9, zorder=2, label=LBL_WB)
ax.plot(H, d.solar_model, color=SOLAR_C, lw=3.0, marker='o', ms=4.6,
        markeredgecolor='white', markeredgewidth=0.6, zorder=5, label=LBL_SM)
ax.plot(H, d.wind_model,  color=WIND_C,  lw=3.0, marker='o', ms=4.6,
        markeredgecolor='white', markeredgewidth=0.6, zorder=5, label=LBL_WM)

for (txt, tx, ty), c in [(TXT_SOLAR, SOLAR_C), (TXT_WIND, WIND_C)]:
    ax.text(tx, ty, txt, fontsize=10.5, color=c, fontweight='bold', ha='left', va='center')

ax.set_xlim(0.5, 15.5); ax.set_ylim(0, Y_MAX)
ax.set_xticks(H); ax.set_xticklabels([f'D+{h}' for h in H], fontsize=8.8)
ax.set_yticks(np.arange(0, Y_MAX + 1, 10))
ax.grid(True, axis='y', linestyle=':', linewidth=0.8, color='#d3d3d3')
ax.set_xlabel(XLAB, fontsize=10); ax.set_ylabel(YLAB, fontsize=10)
ax.set_title(TITLE, fontsize=14, fontweight='bold', color=INK, loc='center', pad=30)
#ax.text(0, 1.03, SUBTITLE, transform=ax.transAxes, fontsize=9.3, color=SOFT, ha='left')
ax.legend(loc='lower center', frameon=False, fontsize=8.6, ncol=2, handlelength=2.0,
          columnspacing=1.6, bbox_to_anchor=(0.5, -0.01))
for s in ('top', 'right'): ax.spines[s].set_visible(False)
for s in ('left', 'bottom'): ax.spines[s].set_color('#d9dce3')
ax.tick_params(length=0)

fig.text(0.012, 0.003, FOOT, fontsize=7.8, color=MUTED)
fig.text(0.012, -0.030, FOOTER_TAG, fontsize=7.2, color=SOFT, fontweight='bold')
fig.subplots_adjust(top=0.82, bottom=0.22, left=0.085, right=0.97)
_save(fig, os.path.join(HERE, '6_perf_channels.png'))
print('saved 6_perf_channels.png')

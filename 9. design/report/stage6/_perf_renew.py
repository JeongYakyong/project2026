# -*- coding: utf-8 -*-
"""#1 그림 — 전체 신재생(태양광+풍력) 이용률 예측 정확도: 단순 기준 vs 서비스 제공 모델, 지평별.

데이터 = perf_util_horizon_6.csv (정직 평가, 이용률 기준).
  · 서비스 제공 모델 = 태양광 PatchTST(D1-6)+신규 LGBM(D7-15) 블렌딩 · 풍력 신규 LGBM (재훈련 후).
  · 기준선 2종: 기후값 평년(월×시각 평균, 전 지평 서빙 가능) · 1주 전 같은 시각.
지표 = 이용률 예측 오차율(%) = 평균 오차 / 평균 이용률 × 100. 낮을수록 정확.
출력: 6_perf_renew.png
"""
import os
import numpy as np, pandas as pd
import matplotlib as mpl, matplotlib.pyplot as plt

# ─────────────────────────────────────────────────────────────────────
# ▼▼▼ 여기 값만 바꾸면 그림이 바뀝니다 ▼▼▼
# ─────────────────────────────────────────────────────────────────────
INK, MUTED, SOFT, ACCENT = '#2d3142', '#4f5d75', '#7a8399', '#eb6c36'
MODEL_C = ACCENT          # 서비스 제공 모델 = 주황(주인공)
CLIM_C  = '#4f5d75'       # 기후값 평년 = 회색 파선
LAG_C   = '#b6bac4'       # 1주 전 = 옅은 회색 점선

TITLE    = '예측 모델과 기준선 신재생 전체 이용률 정확도 비교'
SUBTITLE = '전체 신재생(태양광+풍력) 이용률 예측 오차율 — 단순 기준과 비교 · 낮을수록 정확'
XLAB     = '예측 거리 (지평)'
YLAB     = '이용률 예측 오차율 (%)'
Y_MAX    = 44
LBL_MODEL = '서비스 제공 모델'
LBL_CLIM  = '평년 값'
LBL_LAG   = '1주 전 같은 시각'
TXT_MODEL = ('D+1 - D+15 전 지평에서\n기준선 대비 보다 오차가 작다.', 7.6, 11.5)   # 주황선 아래 빈 공간
FOOT = ('평가 기간 2025-12~2026-06 · 각 발행 시점의 실제 일기예보를 보름 뒤까지 그대로 넣은 정직 평가'
        '(실측이 아니라 예보값이라 거리가 멀수록 어려워진다).')
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
#ax.axvspan(0.5, 15.5, color=ACCENT, alpha=0.04, zorder=0)

ax.plot(H, d.renew_lag, color=LAG_C, lw=1.8, ls=':', zorder=2, label=LBL_LAG)
ax.plot(H, d.renew_clim, color=CLIM_C, lw=1.8, ls='--', zorder=3, label=LBL_CLIM)
ax.plot(H, d.renew_model, color=MODEL_C, lw=3.2, marker='o', ms=5.2,
        markeredgecolor='white', markeredgewidth=0.7, zorder=5, label=LBL_MODEL)

tm, tx, ty = TXT_MODEL
ax.annotate(tm, xy=(11, float(d.renew_model.iloc[10])), xytext=(tx, ty),
            fontsize=9.3, color=ACCENT, fontweight='bold', ha='left', va='center',
            arrowprops=dict(arrowstyle='->', color=ACCENT, lw=1.3))

ax.set_xlim(0.5, 15.5); ax.set_ylim(0, Y_MAX)
ax.set_xticks(H); ax.set_xticklabels([f'D+{h}' for h in H], fontsize=8.8)
ax.grid(True, axis='y', linestyle=':', linewidth=0.8, color='#d3d3d3')
ax.set_yticks(np.arange(0, Y_MAX + 1, 10))
ax.set_xlabel(XLAB, fontsize=10); ax.set_ylabel(YLAB, fontsize=10)
ax.set_title(TITLE, fontsize=14, fontweight='bold', color=INK, loc='center', pad=30)
#ax.text(0, 1.03, SUBTITLE, transform=ax.transAxes, fontsize=9.3, color=SOFT, ha='center')
ax.legend(loc='upper right', frameon=False, fontsize=9.0, handlelength=2.2, bbox_to_anchor=(1.0, 0.25))
for s in ('top', 'right'): ax.spines[s].set_visible(False)
for s in ('left', 'bottom'): ax.spines[s].set_color('#d9dce3')
ax.tick_params(length=0)

fig.text(0.012, 0.003, FOOT, fontsize=7.8, color=MUTED)
fig.text(0.012, -0.030, FOOTER_TAG, fontsize=7.2, color=SOFT, fontweight='bold')
fig.subplots_adjust(top=0.82, bottom=0.20, left=0.085, right=0.97)
_save(fig, os.path.join(HERE, '6_perf_renew.png'))
print('saved 6_perf_renew.png')

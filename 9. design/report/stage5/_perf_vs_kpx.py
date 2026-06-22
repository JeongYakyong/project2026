# -*- coding: utf-8 -*-
"""5단계 성능 비교 — 우리 D+1 모델 vs 전력거래소 하루 전 예측(land_est_demand_da).
왼쪽 = 기존 지평별 차트(이미지 #1, perf_by_horizon.csv), 오른쪽 = D+1 서비스 제공 모델 vs 전력거래소.
정본: eval_finetune_rows.csv(봉인 test) D+1 = pred_ft / 전력거래소 = historical.land_est_demand_da.
출력: 5_perf_vs_kpx.png(오른쪽 단독) / 5_perf_2up.png(1x2 합본)."""
import os, sqlite3
import numpy as np, pandas as pd
import matplotlib as mpl, matplotlib.pyplot as plt
from matplotlib.gridspec import GridSpec

# ════════════════════════════════════════════════════════════════════
# ▼▼▼ 보통은 여기만 고치면 됩니다 (값·라벨·색·제목) ▼▼▼
# ════════════════════════════════════════════════════════════════════
SEASON = '봄'          # 오른쪽 패널 평가 구간: '봄'(3~5월) / '여름' / '겨울' / None(전체 D+1)
SEASON_LABEL = '봄철(3~5월)'   # 부제·각주에 쓸 사람말 라벨

# 색 (집 양식 토큰)
INK, MUTED, SOFT, ACCENT = '#2d3142', '#4f5d75', '#7a8399', '#eb6c36'
BASEC, RULE = '#3b6ea5', '#d9dce3'

# 오른쪽 패널 라벨
R_TITLE   = "하루 전 예측은 ‘전력거래소’보다 정확하다"
R_SUB     = "{0} D+1 예측 오차율"
#— 서비스 제공 모델 vs 전력거래소 하루 전 예측"
R_BARLAB  = ['전력거래소\n하루 전 예측', '서비스 제공 모델\n(하루 전)']
R_REDTEXT = "오차\n절반 이하"

# 왼쪽 패널 라벨 (기존 이미지 #1 그대로)
L_TITLE = "어느 지평에서나 ‘1주 전 패턴’보다 정확하다"
L_SUB   = ""
#"예측 거리별 오차율 — 서비스 제공 모델 vs 단순 기준(baseline)"
# ════════════════════════════════════════════════════════════════════
# ▲▲▲ 보통은 여기까지만 ▲▲▲
# ════════════════════════════════════════════════════════════════════

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, '..', '..', '..'))
DB   = os.path.join(ROOT, '1. data_fetcher_and_db', 'data', 'input_data_land.db')
EVAL = os.path.join(ROOT, '5. land_demand_forecaster', 'training', 'demand_lt', 'eda_scaler', 'eval_finetune_rows.csv')
HORIZON_CSV = os.path.join(HERE, 'perf_by_horizon.csv')

mpl.rcParams.update({
    'font.family': 'Malgun Gothic', 'axes.unicode_minus': False,
    'figure.facecolor': 'white', 'axes.facecolor': 'white', 'savefig.facecolor': 'white',
    'axes.edgecolor': MUTED, 'axes.labelcolor': INK, 'text.color': INK,
    'xtick.color': INK, 'ytick.color': INK, 'figure.dpi': 150,
    'xtick.labelsize': 11, 'ytick.labelsize': 11,
})
def clean(ax):
    for s in ('top', 'right'): ax.spines[s].set_visible(False)
    for s in ('left', 'bottom'): ax.spines[s].set_color(RULE)
    ax.tick_params(length=0)
def mape(a, p):
    a = np.asarray(a, float); p = np.asarray(p, float); m = (a > 0) & np.isfinite(p)
    return float((np.abs(a[m] - p[m]) / a[m]).mean() * 100)

# ── 데이터 ───────────────────────────────────────────────────────────
# 왼쪽: 기존 지평별 결과 그대로
tab = pd.read_csv(HORIZON_CSV)
H = tab.horizon.tolist()

# 오른쪽: D+1 서비스 제공 모델(pred_ft) vs 전력거래소 하루 전(land_est_demand_da)
d = pd.read_csv(EVAL, parse_dates=['timestamp'])
for c in ('horizon_d', 'pred_ft', 'actual'):
    d[c] = pd.to_numeric(d[c], errors='coerce')
g = d[d.horizon_d == 1].dropna(subset=['actual', 'pred_ft']).copy()
con = sqlite3.connect(DB)
h = pd.read_sql('SELECT timestamp, land_est_demand_da FROM historical', con, parse_dates=['timestamp'])
con.close()
g = g.merge(h, on='timestamp', how='left')
g = g[(g.land_est_demand_da > 0) & (g.actual > 0)].copy()
if SEASON is not None:
    g = g[g.season == SEASON]
KPX = mape(g.actual, g.land_est_demand_da)
OUR = mape(g.actual, g.pred_ft)
RED = (KPX - OUR) / KPX * 100
N   = len(g)
print('%s D+1  n=%d  전력거래소=%.2f%%  대비=%.2f%%  (%.0f%% 감소)' % (SEASON_LABEL, N, KPX, OUR, RED))


# ── 왼쪽 패널 그리기 함수 (기존 이미지 #1 재현) ─────────────────────────
def draw_left(ax):
    ax.fill_between(H, tab.model, tab.baseline, color=ACCENT, alpha=0.07, zorder=1)
    ax.plot(H, tab.baseline, color=BASEC, lw=2.2, marker='o', ms=4.2, label='1주 전 같은 시각 (단순 기준)',
            markeredgecolor='white', markeredgewidth=0.6, zorder=3)
    ax.plot(H, tab.model, color=ACCENT, lw=2.8, marker='o', ms=4.6, label='서비스 제공 모델 (PatchTST기반)',
            markeredgecolor='white', markeredgewidth=0.6, zorder=4)
    ax.annotate(f'D+1 오차 절반 이하\n({tab.baseline[0]:.1f}% → {tab.model[0]:.1f}%)',
                xy=(1, tab.model[0]), xytext=(2.2, 1.4),
                fontsize=8.6, color=ACCENT, fontweight='bold', ha='left', va='center',
                arrowprops=dict(arrowstyle='->', color=ACCENT, lw=1.2))
    ax.text(11.4, (tab.model[10] + tab.baseline[10]) / 2, '서비스 제공 모델이\n줄인 오차', fontsize=8.4,
            color=MUTED, ha='center', va='center')
    ax.set_xlim(0.5, 15.5); ax.set_ylim(0, 6.6)
    ax.set_xticks(H); ax.set_xticklabels([f'D+{x}' for x in H], fontsize=9.6, color=INK)
    ax.set_xlabel('예측 거리 (며칠 뒤)', fontsize=11, fontweight='bold')
    ax.set_ylabel('예측 오차율 MAPE (%)', fontsize=11, fontweight ='bold')
    ax.set_title(L_TITLE, fontsize=12.5, fontweight='bold', color=INK, loc='center', pad=26)
    ax.text(0, 1.035, L_SUB, transform=ax.transAxes, fontsize=8.8, color=SOFT, ha='left')
    ax.legend(loc='lower right', frameon=False, fontsize=8.4, handlelength=1.7)
    clean(ax)
    ax.set_axisbelow(True)
    ax.grid(axis='y', color=RULE, lw=0.7)   # 왼쪽=세로 grid


# ── 오른쪽 패널 그리기 함수 (D+1 vs 전력거래소 막대) ─────────────────────
def draw_right(ax, show_ylabel=True):
    vals = [KPX, OUR]; cols = [BASEC, ACCENT]
    bars = ax.bar(R_BARLAB, vals, color=cols, width=0.5, zorder=3)
    for b, v in zip(bars, vals):
        ax.text(b.get_x() + b.get_width() / 2, v + 0.12, f'{v:.2f}%', ha='center', va='bottom',
                fontsize=13, fontweight='bold', color=b.get_facecolor())
    ax.annotate('', xy=(1, OUR + 0.5), xytext=(1, KPX),
                arrowprops=dict(arrowstyle='->', color=INK, lw=1.4))
    ax.text(1.40, (KPX + OUR) / 2, f'{R_REDTEXT}\n(약 {RED:.0f}% 감소)', ha='center', va='center',
            fontsize=10.5, fontweight='bold', color=ACCENT)
    ax.set_ylim(0, 6.6)
    ax.set_xlim(-0.6, 1.8)
    if show_ylabel:
        ax.set_ylabel('예측 오차율 MAPE (%)', fontsize=11, fontweight ='bold')
    ax.set_title(R_TITLE, fontsize=12.5, fontweight='bold', color=INK, loc='center', pad=26)
    ax.text(0.3, 1.035, R_SUB.format(SEASON_LABEL), transform=ax.transAxes, fontsize=9.6, color=MUTED, ha='left')
    clean(ax); ax.tick_params(axis='x', labelsize=11, colors=INK)
    ax.set_axisbelow(True)
    ax.grid(axis='y', color=RULE, lw=0.7)   # 오른쪽=가로 grid


# ════════════════════════════════════════════════════════════════════
# (A) 오른쪽 패널 단독
# ════════════════════════════════════════════════════════════════════
fig, ax = plt.subplots(figsize=(6.0, 4.4))
draw_right(ax)
fig.text(0.012, 0.005,
         f"평가 기간 2025-12~2026-06(봉인 test) · {SEASON_LABEL} D+1 {N:,}시간 · "
         f"전력거래소 하루 전 공식 수요예측과 같은 시각·같은 실측으로 비교.",
         fontsize=7.6, color=MUTED)
fig.subplots_adjust(top=0.80, bottom=0.13, left=0.12, right=0.97)
fig.savefig(os.path.join(HERE, '5_perf_vs_kpx.png'), bbox_inches='tight', dpi=150)
plt.close(fig)

# ════════════════════════════════════════════════════════════════════
# (B) 1x2 합본 — 왼쪽 지평 차트 + 오른쪽 전력거래소 비교
# ════════════════════════════════════════════════════════════════════
fig = plt.figure(figsize=(13.0, 4.9))
gs = GridSpec(1, 2, width_ratios=[1.5, 1.0], wspace=0.22, figure=fig)
axL = fig.add_subplot(gs[0, 0]); draw_left(axL)
axR = fig.add_subplot(gs[0, 1]); draw_right(axR, show_ylabel=True)
fig.text(0.012, 0.012,
         f"평가 기간 2025-12~2026-06(봉인 test). 왼쪽: 전 계절·D+1~15, 단순 기준=1주 전 같은 시각. "
         f"오른쪽: {SEASON_LABEL} D+1 {N:,}시간, 전력거래소 하루 전 공식 수요예측과 같은 시각·같은 실측으로 비교.",
         fontsize=7.8, color=MUTED)
fig.subplots_adjust(top=0.84, bottom=0.17, left=0.055, right=0.985)
fig.savefig(os.path.join(HERE, '5_perf_2up.png'), bbox_inches='tight', dpi=150)
plt.close(fig)
print('saved 5_perf_vs_kpx.png / 5_perf_2up.png')

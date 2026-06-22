# -*- coding: utf-8 -*-
"""공통 · 정직한 평가 '증거' 그래프 — 모델에 넣는 예보 기상 자체의 오차가 지평에 따라 커진다.
대부분의 연구는 이 입력 오차를 0(완벽한 실측)으로 두고 평가하지만, 우리는 예보값을 그대로 떠안는다.
데이터: forecast_horizon(지평별 예보 기온) vs historical(같은 시각 실측 기온), 전국 5개 지점 평균.
출력: honest_input_error.png / honest_input_error.csv"""
import os, sqlite3
import numpy as np, pandas as pd
import matplotlib as mpl, matplotlib.pyplot as plt

# ════════════════════════════════════════════════════════════════════
# ▼▼▼ 보통은 여기만 고치면 됩니다 (값·라벨·색·제목) ▼▼▼
# ════════════════════════════════════════════════════════════════════
HMAX = 15   # 보여줄 최대 지평 (D+1 ~ D+HMAX)
STATIONS = ['daegwallyeong', 'wonju', 'seosan', 'pohang', 'yeonggwang']

INK, MUTED, SOFT, ACCENT = '#2d3142', '#4f5d75', '#7a8399', '#eb6c36'
BASEC, RULE = '#3b6ea5', '#d9dce3'

TITLE  = "먼 미래일수록 '입력 날씨'부터 틀린다 — 그 오차까지 떠안고 평가한다"
SUB    = "모델에 넣는 예보 기온이 실제와 얼마나 다른가 (전국 5개 지점 평균)"
YLAB   = "예보 기온의 평균 오차 (°C)"
BASELABEL = "대부분의 연구가 가정하는 입력\n완벽한 실측 = 오차 0"
OURLABEL  = "우리가 그대로 떠안는\n예보 입력 오차"
# ════════════════════════════════════════════════════════════════════
# ▲▲▲ 보통은 여기까지만 ▲▲▲
# ════════════════════════════════════════════════════════════════════

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, '..', '..', '..'))
DB   = os.path.join(ROOT, '1. data_fetcher_and_db', 'data', 'input_data_land.db')

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

# ── 데이터: 지평별 예보 기온 vs 실측 기온 평균절대오차 ───────────────────
con = sqlite3.connect(DB)
fcols = ['timestamp', 'horizon_d'] + ['temp_' + s for s in STATIONS]
fh = pd.read_sql('SELECT ' + ','.join(fcols) + ' FROM forecast_horizon', con, parse_dates=['timestamp'])
hcols = ['timestamp'] + ['temp_c_' + s for s in STATIONS]
hi = pd.read_sql('SELECT ' + ','.join(hcols) + ' FROM historical', con, parse_dates=['timestamp'])
con.close()
m = fh.merge(hi, on='timestamp', how='inner')
ae = pd.concat([(m['temp_' + s] - m['temp_c_' + s]).abs() for s in STATIONS], axis=1).mean(axis=1)
m['temp_mae'] = ae
g = (m.dropna(subset=['temp_mae']).groupby('horizon_d')['temp_mae'].mean())
H = list(range(1, HMAX + 1))
y = [float(g.get(h, np.nan)) for h in H]
pd.DataFrame({'horizon': H, 'temp_mae_degC': y}).to_csv(os.path.join(HERE, 'honest_input_error.csv'), index=False)
print('D+1=%.2f°C  D+%d=%.2f°C' % (y[0], HMAX, y[-1]))

# ── 그림 ─────────────────────────────────────────────────────────────
fig, ax = plt.subplots(figsize=(8.2, 4.7))
ax.fill_between(H, 0, y, color=ACCENT, alpha=0.09, zorder=1)
ax.axhline(0, color=BASEC, lw=2.2, zorder=2)
ax.plot(H, y, color=ACCENT, lw=3.0, marker='o', ms=5, markeredgecolor='white',
        markeredgewidth=0.6, zorder=4)

# 연구 관행(0선) 라벨
ax.text(7.5, 0.18, BASELABEL, fontsize=9.2, color=BASEC, ha='center', va='bottom', fontweight='bold')
# 우리가 떠안는 입력 오차 영역 라벨
ax.text(10.6, 1.7, OURLABEL, fontsize=9.6, color=ACCENT, ha='center', va='center', fontweight='bold')

# 양 끝 값 강조
ax.annotate(f'D+1 부터 이미\n{y[0]:.1f}°C 틀림', xy=(1, y[0]), xytext=(2.3, 3.4),
            fontsize=9.0, color=INK, fontweight='bold', ha='left', va='center',
            arrowprops=dict(arrowstyle='->', color=INK, lw=1.2))
ax.annotate(f'D+{HMAX} 에는\n{y[-1]:.1f}°C', xy=(HMAX, y[-1]), xytext=(HMAX-0.2, y[-1]+0.9),
            fontsize=9.6, color=ACCENT, fontweight='bold', ha='center', va='bottom')

ax.set_xlim(0.5, HMAX + 0.6)
ax.set_ylim(0, max(y) * 1.28)
ax.set_xticks(H); ax.set_xticklabels([f'D+{h}' for h in H], fontsize=9.6, color=INK)
ax.set_xlabel('예측 거리 (며칠 뒤)', fontsize=11, fontweight='bold')
ax.set_ylabel(YLAB, fontsize=11, fontweight='bold')
ax.set_title(TITLE, fontsize=13, fontweight='bold', color=INK, loc='left', pad=28)
ax.text(0, 1.04, SUB, transform=ax.transAxes, fontsize=9.6, color=MUTED, ha='left')
clean(ax)
ax.set_axisbelow(True)
ax.grid(axis='y', color=RULE, lw=0.7)

fig.text(0.012, 0.005,
         "평가 기간 2025-12~2026-06(봉인 test) · 발표된 예보 기온과 같은 시각 실측의 차이. "
         "대부분의 연구는 이 입력 오차를 0으로 두고(실측을 넣고) 정확도를 보고합니다.",
         fontsize=8.0, color=MUTED)
fig.subplots_adjust(top=0.82, bottom=0.16, left=0.085, right=0.975)
fig.savefig(os.path.join(HERE, 'honest_input_error.png'), bbox_inches='tight', dpi=150)
plt.close(fig)
print('saved honest_input_error.png / honest_input_error.csv')

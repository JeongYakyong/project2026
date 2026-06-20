# -*- coding: utf-8 -*-
"""7단계 · 발전용 가스 예측 성능 (집 양식).
데이터: est_horizon_land(서빙 적재 예측) + historical(실측 gen_gas_kr).
실행: python step7_perf.py  → 같은 폴더에 step7_perf.png / perf_by_horizon.csv 생성
"""
import os, sqlite3
import numpy as np, pandas as pd
import matplotlib as mpl, matplotlib.pyplot as plt

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, '..', '..', '..'))
DB = os.path.join(ROOT, '1. data_fetcher_and_db', 'data', 'input_data_land.db')

# ======================================================================
#  ▼▼▼  바꿀 값(색·라벨·문구·축)은 여기 모여 있습니다  ▼▼▼
# ======================================================================
INK, MUTED, SOFT, ACCENT = '#2d3142', '#4f5d75', '#7a8399', '#eb6c36'
BASEC, RULE = '#9aa0ac', '#d9dce3'              # 단순 기준=회색
C_FILL = ACCENT                                  # 줄인 오차 영역 색

TITLE    = '2주 앞을 내다봐도 오차가 완만하게만 늘어난다'
SUBTITLE = '예측 거리별 오차율 — 우리 가스 모델 vs 단순 기준(1주 전 같은 시각 반복)'
XLABEL   = '예측 거리 (며칠 뒤)'
YLABEL   = '예측 오차율 MAPE (%)  ·  낮을수록 정확'
LAB_MODEL = '우리 가스 모델'
LAB_BASE  = '1주 전 같은 시각 (단순 기준)'
YMAX = 22
# ======================================================================

mpl.rcParams.update({
    'font.family': 'Malgun Gothic', 'axes.unicode_minus': False,
    'figure.facecolor': 'white', 'axes.facecolor': 'white', 'savefig.facecolor': 'white',
    'axes.edgecolor': MUTED, 'axes.labelcolor': INK, 'text.color': INK,
    'xtick.color': MUTED, 'ytick.color': MUTED, 'figure.dpi': 150,
})
def clean(ax):
    for s in ('top', 'right'): ax.spines[s].set_visible(False)
    for s in ('left', 'bottom'): ax.spines[s].set_color(RULE)
    ax.tick_params(length=0)

# ── 실측·예측 로드 ───────────────────────────────────────────────
con = sqlite3.connect(DB)
hist = pd.read_sql('SELECT timestamp, gen_gas_kr FROM historical', con, parse_dates=['timestamp']).sort_values('timestamp')
est = pd.read_sql('SELECT timestamp, horizon_d, est_gas_gen_land FROM est_horizon_land', con, parse_dates=['timestamp'])
con.close()
s = hist.set_index('timestamp')['gen_gas_kr']
est['actual'] = est.timestamp.map(s.to_dict())
est['base168'] = est.timestamp.map(s.shift(freq='168h').to_dict())   # 1주 전 같은 시각
est = est.dropna(subset=['actual']); est = est[est.actual > 0]

def mape(a, p):
    m = (~p.isna()) & (a > 0); return float((np.abs(a[m] - p[m]) / a[m]).mean() * 100)

H = list(range(1, 16))
rows = []
for h in H:
    g = est[est.horizon_d == h]
    rows.append(dict(horizon=h, n=len(g),
                     model=mape(g.actual, g.est_gas_gen_land),
                     baseline=mape(g.actual, g.base168)))
tab = pd.DataFrame(rows)
tab.to_csv(os.path.join(HERE, 'perf_by_horizon.csv'), index=False)
OV_m = mape(est.actual, est.est_gas_gen_land); OV_b = mape(est.actual, est.base168)
imp = (OV_b - OV_m) / OV_b * 100
print('overall model=%.2f baseline=%.2f  개선=%.0f%%' % (OV_m, OV_b, imp))

# ════════════════════════════════════════════════════════════════════
#  지평별 오차율 — 우리 모델 vs 단순 기준
# ════════════════════════════════════════════════════════════════════
fig, ax = plt.subplots(figsize=(7.8, 4.6))
ax.fill_between(H, tab.model, tab.baseline, color=C_FILL, alpha=0.07, zorder=1)
ax.plot(H, tab.baseline, color=BASEC, lw=2.4, marker='o', ms=4.5, label=LAB_BASE,
        markeredgecolor='white', markeredgewidth=0.6, zorder=3)
ax.plot(H, tab.model, color=ACCENT, lw=3.0, marker='o', ms=5, label=LAB_MODEL,
        markeredgecolor='white', markeredgewidth=0.6, zorder=4)

# 양 끝 값 라벨(우리 모델)
ax.annotate(f'하루 뒤 {tab.model[0]:.1f}%', xy=(1, tab.model[0]), xytext=(1.4, tab.model[0]-3.4),
            fontsize=9.3, color=ACCENT, fontweight='bold', ha='left', va='center',
            arrowprops=dict(arrowstyle='->', color=ACCENT, lw=1.2))
ax.annotate(f'2주 뒤에도 {tab.model.iloc[-1]:.1f}%', xy=(15, tab.model.iloc[-1]),
            xytext=(11.2, tab.model.iloc[-1]+3.0),
            fontsize=9.3, color=ACCENT, fontweight='bold', ha='center', va='center',
            arrowprops=dict(arrowstyle='->', color=ACCENT, lw=1.2))
ax.text(8, (tab.model[7] + tab.baseline[7]) / 2 + 0.4, '우리 모델이\n줄인 오차', fontsize=8.8,
        color=MUTED, ha='center', va='center')

ax.set_xlim(0.5, 15.5); ax.set_ylim(0, YMAX)
ax.set_xticks(H); ax.set_xticklabels([f'D+{h}' for h in H], fontsize=8.8)
ax.set_xlabel(XLABEL, fontsize=10)
ax.set_ylabel(YLABEL, fontsize=10)
ax.set_title(TITLE, fontsize=14, fontweight='bold', color=INK, loc='left', pad=30)
ax.text(0, 1.03, SUBTITLE, transform=ax.transAxes, fontsize=9.5, color=SOFT, ha='left')
ax.legend(loc='lower right', frameon=False, fontsize=9.3, handlelength=1.8)
clean(ax)
fig.text(0.012, 0.005,
         f"정직한 백테스트 · 평가 기간 2025-12~2026-06 · 전체 오차 {OV_m:.1f}% (단순 기준 {OV_b:.1f}%). "
         f"가스는 수요·신재생을 뺀 '나머지'라 변동이 커, 수요(약 4%)보다 본질적으로 어렵습니다.",
         fontsize=8.2, color=MUTED)
fig.subplots_adjust(top=0.82, bottom=0.18, left=0.09, right=0.97)
fig.savefig(os.path.join(HERE, 'step7_perf.png'), bbox_inches='tight', dpi=150)
plt.close(fig)
print('saved step7_perf.png')

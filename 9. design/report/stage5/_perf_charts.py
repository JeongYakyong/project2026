# -*- coding: utf-8 -*-
"""5단계 성능 차트 (집 양식). baseline=lag168h vs 우리 모델(PatchTST v4, G-24 지평별 파인튜닝).
데이터 정본: eval_finetune_rows.csv(G-24 봉인 test 186 base) — D1-6=pred_ft(파인튜닝)·D7-15=pred_orig_calib(기존+보정).
baseline 은 같은 행의 historical lag168h. 출력: 5_perf_horizon.png / 5_perf_summary.png / perf_by_horizon.csv"""
import os, sqlite3
import numpy as np, pandas as pd
import matplotlib as mpl, matplotlib.pyplot as plt

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, '..', '..', '..'))
DB = os.path.join(ROOT, '1. data_fetcher_and_db', 'data', 'input_data_land.db')
EVAL = os.path.join(ROOT, '5. land_demand_forecaster', 'training', 'demand_lt', 'eda_scaler', 'eval_finetune_rows.csv')

INK, MUTED, SOFT, ACCENT = '#2d3142', '#4f5d75', '#7a8399', '#eb6c36'
BASEC, RULE = '#3b6ea5', '#d9dce3'
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

# ── 우리 모델(G-24) 예측 + 실측 로드 ────────────────────────────────
d = pd.read_csv(EVAL, usecols=['timestamp', 'horizon_d', 'pred_ft', 'pred_orig_calib', 'actual'],
                parse_dates=['timestamp'])
for c in ('horizon_d', 'pred_ft', 'pred_orig_calib', 'actual'):
    d[c] = pd.to_numeric(d[c], errors='coerce')
d = d.dropna(subset=['actual', 'pred_ft', 'pred_orig_calib'])
# ★ G-24 production = D1-6 파인튜닝본 / D7-15 기존+후처리 보정
d['model'] = np.where(d.horizon_d <= 6, d.pred_ft, d.pred_orig_calib)

con = sqlite3.connect(DB)
hist = pd.read_sql('SELECT timestamp, real_demand_land FROM historical', con, parse_dates=['timestamp']).sort_values('timestamp')
con.close()
s = hist.assign(y=hist.real_demand_land.replace(0, np.nan).interpolate('linear')).set_index('timestamp')['y']
d['base168'] = d.timestamp.map(s.shift(freq='168h').to_dict())   # 1주 전 같은 시각

def mape(a, p):
    a = np.asarray(a, float); p = np.asarray(p, float); m = (a > 0) & np.isfinite(p)
    return float((np.abs(a[m] - p[m]) / a[m]).mean() * 100)

H = list(range(1, 16))
rows = []
for h in H:
    g = d[d.horizon_d == h]
    rows.append(dict(horizon=h, n=len(g), baseline=mape(g.actual, g.base168), model=mape(g.actual, g.model)))
tab = pd.DataFrame(rows)
tab.to_csv(os.path.join(HERE, 'perf_by_horizon.csv'), index=False)
OV_b = mape(d.actual, d.base168); OV_m = mape(d.actual, d.model)
imp = (OV_b - OV_m) / OV_b * 100
print('overall baseline=%.3f model(G-24)=%.3f  개선=%.1f%%' % (OV_b, OV_m, imp))

# ════════════════════════════════════════════════════════════════════
# (P1) 지평별 오차율 — baseline vs 우리 모델
# ════════════════════════════════════════════════════════════════════
fig, ax = plt.subplots(figsize=(7.8, 4.6))
ax.fill_between(H, tab.model, tab.baseline, color=ACCENT, alpha=0.07, zorder=1)
ax.plot(H, tab.baseline, color=BASEC, lw=2.4, marker='o', ms=4.5, label='1주 전 같은 시각 (baseline)',
        markeredgecolor='white', markeredgewidth=0.6, zorder=3)
ax.plot(H, tab.model, color=ACCENT, lw=3.0, marker='o', ms=5, label='우리 모델 (PatchTST v4)',
        markeredgecolor='white', markeredgewidth=0.6, zorder=4)

ax.annotate(f'D+1 오차 절반 이하\n({tab.baseline[0]:.1f}% → {tab.model[0]:.1f}%)',
            xy=(1, tab.model[0]), xytext=(2.2, 1.5),
            fontsize=9, color=ACCENT, fontweight='bold', ha='left', va='center',
            arrowprops=dict(arrowstyle='->', color=ACCENT, lw=1.3))
ax.text(11.6, (tab.model[10] + tab.baseline[10]) / 2, '우리 모델이\n줄인 오차', fontsize=8.8,
        color=MUTED, ha='center', va='center')

ax.set_xlim(0.5, 15.5); ax.set_ylim(0, 6.6)
ax.set_xticks(H); ax.set_xticklabels([f'D+{h}' for h in H], fontsize=8.8)
ax.set_xlabel('예측 거리 (며칠 뒤)', fontsize=10)
ax.set_ylabel('예측 오차율 MAPE (%)  ·  낮을수록 정확', fontsize=10)
ax.set_title('어느 지평에서나 ‘1주 전 패턴’보다 정확하다', fontsize=14, fontweight='bold', color=INK, loc='left', pad=30)
ax.text(0, 1.03, '예측 거리별 오차율 — 우리 모델(PatchTST v4) vs 단순 기준(baseline)', transform=ax.transAxes,
        fontsize=9.5, color=SOFT, ha='left')
ax.legend(loc='lower right', frameon=False, fontsize=9.3, handlelength=1.8)
clean(ax)
fig.text(0.012, 0.005,
         f"평가 기간 2025-12~2026-06(봉인 test) · 전체 오차 baseline {OV_b:.2f}% → 우리 모델 {OV_m:.2f}% (약 {imp:.0f}% 감소). "
         f"가까운 미래(D1-6) 파인튜닝·먼 미래(D7-15) 후처리 보정.",
         fontsize=8.0, color=MUTED)
fig.subplots_adjust(top=0.82, bottom=0.18, left=0.09, right=0.97)
fig.savefig(os.path.join(HERE, '5_perf_horizon.png'), bbox_inches='tight', dpi=150)
plt.close(fig)

# ════════════════════════════════════════════════════════════════════
# (P2) 전체 정확도 요약 바
# ════════════════════════════════════════════════════════════════════
fig, ax = plt.subplots(figsize=(6.2, 4.2))
labels = ['1주 전 같은 시각\n(baseline)', '우리 모델\n(PatchTST v4)']
vals = [OV_b, OV_m]
cols = [BASEC, ACCENT]
bars = ax.bar(labels, vals, color=cols, width=0.52, zorder=3)
for b, v in zip(bars, vals):
    ax.text(b.get_x() + b.get_width() / 2, v + 0.10, f'{v:.2f}%', ha='center', va='bottom',
            fontsize=13, fontweight='bold', color=b.get_facecolor())
ax.annotate('', xy=(1, OV_m + 0.22), xytext=(1, OV_b),
            arrowprops=dict(arrowstyle='->', color=INK, lw=1.4))
ax.text(1.34, (OV_b + OV_m) / 2, f'오차\n약 {imp:.0f}%\n감소', ha='center', va='center',
        fontsize=11, fontweight='bold', color=ACCENT)
ax.set_ylim(0, OV_b * 1.2)
ax.set_ylabel('예측 오차율 MAPE (%)  ·  낮을수록 정확', fontsize=10)
ax.set_title('전체 정확도: 단순 기준 대비 오차 약 3분의 1 감소', fontsize=13.5, fontweight='bold', color=INK, loc='left', pad=30)
ax.text(0, 1.03, '평가 기간 2025-12~2026-06(봉인 test) · D+1~15 전체', transform=ax.transAxes,
        fontsize=9.5, color=SOFT, ha='left')
clean(ax); ax.tick_params(axis='x', labelsize=10.5)
ax.set_xlim(-0.6, 1.7)
fig.subplots_adjust(top=0.80, bottom=0.12, left=0.13, right=0.97)
fig.savefig(os.path.join(HERE, '5_perf_summary.png'), bbox_inches='tight', dpi=150)
plt.close(fig)
print('saved 5_perf_horizon.png / 5_perf_summary.png')

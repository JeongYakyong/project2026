# -*- coding: utf-8 -*-
"""7단계 · 발전용 가스 예측 성능 (집 양식) — 지평별 정확도, 단순 기준(1주 전) 대비.

★정직 평가(봉인 holdout): 데이터 = newchain_gas_sealed_g28.parquet
  = 2026-03까지만 학습한 모델(foldC)로, 학습에 안 쓴 2026-04~06 을 새 체인(새 6단계 + 블렌딩 OFF)
    으로 예측·실측 대조한 결과. (옛 버전은 est_horizon_land 백필=in-sample 낙관이라 교체. 5·6단계와
    동일하게 정직 검증 수치로 그린다.)
실행: python step7_perf.py  → 같은 폴더에 step7_perf.png / perf_by_horizon.csv 생성
"""
import os, sqlite3
import numpy as np, pandas as pd
import matplotlib as mpl, matplotlib.pyplot as plt

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, '..', '..', '..'))
DB = os.path.join(ROOT, '1. data_fetcher_and_db', 'data', 'input_data_land.db')
SEALED = os.path.join(ROOT, '7. land_gas_forecaster', 'training', 'newchain_gas_sealed_g28.parquet')

# ======================================================================
#  ▼▼▼  바꿀 값(색·라벨·문구·축)은 여기 모여 있습니다  ▼▼▼
# ======================================================================
INK, MUTED, SOFT, ACCENT = '#2d3142', '#4f5d75', '#7a8399', '#eb6c36'
BASEC, RULE = '#9aa0ac', '#d9dce3'              # 단순 기준 = 회색
C_FILL = ACCENT                                  # 줄인 오차 영역 색

TITLE    = '지평별 발전용 가스 예측모델 평균 오차율'
SUBTITLE = ''
XLABEL   = '예측 거리 (지평)'
YLABEL   = '예측 오차율 MAPE (%)'
LAB_MODEL = '발전용 가스 예측모델'
LAB_BASE  = '1주 전 같은 시각 (lag168h)'
YMAX = 22
# ======================================================================
#  ▲▲▲  보통은 여기까지만 수정 ▲▲▲
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

def _save(fig, path):   # 저장 직전 모든 축 눈금 글자 굵게(작도규칙 §7, 자동눈금·쌍축 포함)
    for ax in fig.axes:
        for lab in ax.get_xticklabels() + ax.get_yticklabels():
            lab.set_fontweight('bold')
    fig.savefig(path, bbox_inches='tight', dpi=150)
    plt.close(fig)

# ── 정직(봉인) 예측·실측 로드 ───────────────────────────────────────
df = pd.read_parquet(SEALED)
df['timestamp'] = pd.to_datetime(df['timestamp'])
df = df[(df.gen_gas_kr > 0) & df.est_gas_gen_land_raw.notna()].copy()   # raw = 블렌딩 OFF = 현 production
# 단순 기준 = 1주 전(168h 전) 같은 시각의 실측 가스
con = sqlite3.connect(DB)
hist = pd.read_sql('SELECT timestamp, gen_gas_kr FROM historical', con, parse_dates=['timestamp']).sort_values('timestamp')
con.close()
s = hist.set_index('timestamp')['gen_gas_kr']
df['base168'] = df.timestamp.map(s.shift(freq='168h').to_dict())

def mape(a, p):
    a = np.asarray(a, float); p = np.asarray(p, float); m = (a > 0) & np.isfinite(p)
    return float((np.abs(a[m] - p[m]) / a[m]).mean() * 100)

H = list(range(1, 16))
rows = []
for h in H:
    g = df[df.horizon_d == h]
    rows.append(dict(horizon=h, n=len(g),
                     model=mape(g.gen_gas_kr, g.est_gas_gen_land_raw),
                     baseline=mape(g.gen_gas_kr, g.base168)))
tab = pd.DataFrame(rows)
tab.to_csv(os.path.join(HERE, 'perf_by_horizon.csv'), index=False)
OV_m = mape(df.gen_gas_kr, df.est_gas_gen_land_raw); OV_b = mape(df.gen_gas_kr, df.base168)
imp = (OV_b - OV_m) / OV_b * 100
p0, p1 = df.timestamp.min().strftime('%Y-%m'), df.timestamp.max().strftime('%Y-%m')
print('overall model=%.2f baseline=%.2f  개선=%.0f%%  (%s~%s)' % (OV_m, OV_b, imp, p0, p1))

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
ax.annotate(f'하루 뒤 {tab.model[0]:.1f}%', xy=(1, tab.model[0]), xytext=(1.5, tab.model[0] - 3.6),
            fontsize=9.3, color=ACCENT, fontweight='bold', ha='left', va='center',
            arrowprops=dict(arrowstyle='->', color=ACCENT, lw=1.2))
ax.annotate(f'2주 뒤 {tab.model.iloc[-1]:.1f}%', xy=(15, tab.model.iloc[-1]),
            xytext=(13.4, tab.model.iloc[-1] + 3.2),
            fontsize=9.3, color=ACCENT, fontweight='bold', ha='center', va='center',
            arrowprops=dict(arrowstyle='->', color=ACCENT, lw=1.2))
ax.text(8, (tab.model[7] + tab.baseline[7]) / 2 + 0.3, '모델이\n줄인 오차', fontsize=8.8,
        color=MUTED, ha='center', va='center')

ax.set_xlim(0.5, 15.5); ax.set_ylim(0, YMAX)
ax.set_xticks(H); ax.set_xticklabels([f'D+{h}' for h in H], fontsize=8.8)
ax.set_yticks(np.arange(0, YMAX + 1, 5))
ax.set_xlabel(XLABEL, fontsize=10)
ax.set_ylabel(YLABEL, fontsize=10)
ax.set_title(TITLE, fontsize=14, fontweight='bold', color=INK, loc='center', pad=30)
#ax.text(0, 1.03, SUBTITLE, transform=ax.transAxes, fontsize=9.5, color=SOFT, ha='left')
ax.legend(loc='lower right', frameon=False, fontsize=9.3, handlelength=1.8)
clean(ax)
#fig.text(0.012, 0.005,
#         f"정직 평가(학습에 안 쓴 {p0}~{p1} 기간으로 검증) · 전체 오차 {OV_m:.1f}% (단순 기준 {OV_b:.1f}%, 약 {imp:.0f}% 감소). "
#         f"가스는 수요·신재생을 뺀 '나머지'라 변동이 커, 수요(약 4%)보다 본질적으로 어렵습니다.",
#         fontsize=8.0, color=MUTED)
fig.subplots_adjust(top=0.82, bottom=0.18, left=0.09, right=0.97)
_save(fig, os.path.join(HERE, 'step7_perf.png'))
print('saved step7_perf.png')

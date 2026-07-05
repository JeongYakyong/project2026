# -*- coding: utf-8 -*-
"""7단계 진단 · 원인규명 — 모델의 수요→가스 곡선이 저수요에서 실측보다 높다 (집 양식).

메시지: 2026 저부하 과대예측의 원인은 '급전순서 붕괴'가 아니라 **모델의 수요→가스 매핑이
       저수요 구간에서 옛(가스 높던) 수준에 고정**된 것. 냉방수요 낮은 시원한 여름이라
       하루 대부분이 이 저수요 구간에 몰려 편향이 커진다.
데이터: input_data_land_check.db (실측) + lgbm_land_gas_v3.txt (모델 곡선)
실행: python step7_cause_demand_curve.py  → PNG + CSV
"""
import os, sys, sqlite3
import numpy as np, pandas as pd, lightgbm as lgb
import matplotlib as mpl, matplotlib.pyplot as plt

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, '..', '..', '..'))
sys.path.insert(0, os.path.join(ROOT, '7. land_gas_forecaster'))
import serve_land_gas as sg
DB = os.path.join(ROOT, '1. data_fetcher_and_db', 'temp_DB', 'input_data_land_check.db')

# ======================================================================
#  ▼▼▼  바꿀 값(색·라벨·문구·축)  ▼▼▼
# ======================================================================
INK, MUTED, SOFT, RULE = '#2d3142', '#4f5d75', '#7a8399', '#d9dce3'
C_MODEL = '#eb6c36'      # 모델 = 주황
C_2024  = '#c8ccd4'      # 옛해(가스 높던) = 연회색
C_2025  = '#8b93a3'      # 2025 = 중간 회색
C_2026  = '#2d3142'      # 2026 실측 = 짙은 잉크
C_HIST  = '#bcd4e6'      # 2026 수요분포 막대
ZONE    = '#f7d9cc'      # 과대 발산 구간 음영
SUP = '왜 저부하에서 과대예측하나 — 모델의 수요→가스 곡선이 실측보다 높다  (6~7월)'
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
def _save(fig, path):
    for ax in fig.axes:
        for lab in ax.get_xticklabels() + ax.get_yticklabels(): lab.set_fontweight('bold')
    fig.savefig(path, bbox_inches='tight', dpi=150); plt.close(fig)

# ── 데이터 ─────────────────────────────────────────────────────────────
con = sqlite3.connect(DB)
h = pd.read_sql("SELECT timestamp, real_demand_land AS dem, gen_gas_kr AS gas FROM historical "
                "WHERE gen_gas_kr>0 AND real_demand_land>0", con, parse_dates=['timestamp'])
# 모델 곡선용 대표 피처 = 6/20~7/5 D+1 서빙 피처의 중앙값 (probe 와 동일 구성)
e = pd.read_sql("SELECT timestamp, base, est_demand_land, est_market_renew_land FROM est_horizon_land "
                "WHERE timestamp>='2026-06-20' AND timestamp<'2026-07-06' AND horizon_d=1",
                con, parse_dates=['timestamp', 'base'])
con.close()
h['y'] = h.timestamp.dt.year; h['m'] = h.timestamp.dt.month
gser = h.set_index('timestamp').gas.sort_index()
gs = gser.reindex(pd.date_range(gser.index.min(), gser.index.max(), freq='h')).replace(0, np.nan).interpolate('time', limit=6)

# 연도별 실측 수요→가스 곡선 (6~7월, 1000단위 이동평균 느낌으로 2000폭 구간중앙)
def emp_curve(y):
    d = h[(h.y == y) & (h.m.isin([6, 7]))]
    b = pd.cut(d.dem, np.arange(55000, 78001, 1500))
    s = d.groupby(b, observed=True).gas.mean()
    x = [iv.mid for iv in s.index]; return np.array(x), s.values

# 모델 곡선: 대표 피처 고정 + 수요만 스윕
O = e.base.iloc[len(e)//2].normalize() + pd.Timedelta(hours=23)
rep = {
    'renew_util': (e.est_market_renew_land / sg._renew_cap(pd.DatetimeIndex(e.timestamp))).median(),
    'gas_lag168': float(gs.reindex(e.timestamp - pd.Timedelta(hours=168)).median()),
    'gas_lag24': float(gs.reindex(e.timestamp - pd.Timedelta(hours=24)).median()),
    'gas_rec24': float(gs.loc[O - pd.Timedelta(hours=23):O].mean()),
    'gas_rec168': float(gs.loc[O - pd.Timedelta(hours=167):O].mean()),
    'h': 15, 'hour': 15, 'dow': 2, 'doy': 186,
    'nuke_rec24': 20200.0, 'nuke_rec168': 20200.0,
}
booster = lgb.Booster(model_file=sg.MODEL); OFF = sg._OFFSET
grid = np.arange(55500, 77001, 500)
mrows = pd.DataFrame([{**rep, 'real_demand_land': D} for D in grid])
mcurve = booster.predict(mrows[sg.FEATS]) + OFF

# ── 그림 ───────────────────────────────────────────────────────────────
fig, (axL, axR) = plt.subplots(1, 2, figsize=(11.6, 4.6), gridspec_kw={'wspace': 0.26, 'width_ratios': [1.32, 1]})

# 왼쪽: 곡선 비교
axL.axvspan(55500, 64000, color=ZONE, alpha=0.5, zorder=0)
for y, c, lw, lab in [(2024, C_2024, 2.0, '2024 실측'), (2025, C_2025, 2.0, '2025 실측'), (2026, C_2026, 2.8, '2026 실측')]:
    x, v = emp_curve(y); axL.plot(x, v, color=c, lw=lw, zorder=3, label=lab)
axL.plot(grid, mcurve, color=C_MODEL, lw=3.0, zorder=4, label='모델 예측 곡선')
axL.set_title('같은 수요에서 모델이 실측보다 위 (저수요일수록 심함)', fontsize=12, fontweight='bold', color=INK, pad=9)
axL.set_xlabel('전력수요 (MW)', fontsize=10.5); axL.set_ylabel('발전용 가스 (MW)', fontsize=10.5)
axL.set_xlim(55500, 77000); axL.set_ylim(9000, 26000)
axL.legend(loc='upper left', frameon=False, fontsize=9.6, handlelength=1.6)
clean(axL)
axL.annotate('저수요 구간\n모델 +1,500~3,400 과대', xy=(59000, 14700), xytext=(61500, 11200),
             fontsize=9.6, color=C_MODEL, fontweight='bold', ha='left',
             arrowprops=dict(arrowstyle='->', color=C_MODEL, lw=1.4))

# 오른쪽: 2026 수요분포 — 대부분 저수요 발산구간에 몰림
d26 = h[(h.y == 2026) & (h.timestamp >= '2026-06-20') & (h.timestamp < '2026-07-06')]
axR.hist(d26.dem, bins=np.arange(54000, 80001, 2000), color=C_HIST, edgecolor='white', zorder=3)
axR.axvspan(55500, 64000, color=ZONE, alpha=0.5, zorder=0)
axR.axvline(64000, color=C_MODEL, lw=1.6, ls='--', zorder=4)
sh = (d26.dem < 64000).mean() * 100
axR.set_title('2026 장마 수요 분포 — 대부분 저수요 구간', fontsize=12, fontweight='bold', color=INK, pad=9)
axR.set_xlabel('전력수요 (MW)', fontsize=10.5); axR.set_ylabel('시간 수 (6/20~7/5)', fontsize=10.5)
axR.set_xlim(54000, 80000)
clean(axR)
axR.text(63200, axR.get_ylim()[1]*0.92, '과대예측 구간(<64k)에\n전체 시간의 %d%%가 몰림' % round(sh),
         color=C_MODEL, fontsize=9.8, fontweight='bold', ha='right', va='top')

fig.suptitle(SUP, fontsize=13, fontweight='bold', color=INK, y=1.02, x=0.02, ha='left')
_save(fig, os.path.join(HERE, 'step7_cause_demand_curve.png'))

# CSV 근거
out = pd.DataFrame({'demand': grid, 'model_gas': mcurve.round(0)})
out.to_csv(os.path.join(HERE, 'cause_model_demand_curve.csv'), index=False, encoding='utf-8-sig')
print('saved step7_cause_demand_curve.png')
print('2026 수요<64k 시간비중: %.0f%%' % sh)
for y in (2024, 2025, 2026):
    x, v = emp_curve(y); print(y, 'gas@~60k:', round(np.interp(60000, x, v)))
print('model gas@60k:', round(np.interp(60000, grid, mcurve)))

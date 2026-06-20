# -*- coding: utf-8 -*-
"""5단계 EDA 보고서용 차트 (집 양식: 흰 배경·맑은 고딕).
출력: 5_importance.png / 5_temp_demand.png / 5_season_hour.png"""
import os, sqlite3
import numpy as np, pandas as pd
import matplotlib as mpl, matplotlib.pyplot as plt
import lightgbm as lgb

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, '..', '..', '..'))
DB = os.path.join(ROOT, '1. data_fetcher_and_db', 'data', 'input_data_land.db')
MODEL = os.path.join(ROOT, '5. land_demand_forecaster', 'model', 'models', 'lgbm_land_demand_v2hum.txt')

INK, MUTED, SOFT, ACCENT = '#2d3142', '#4f5d75', '#7a8399', '#eb6c36'
RULE = '#d9dce3'
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

# ── 데이터 로드 (4지점: 원주·서산·포항·영광 = 모델 정의) ──────────────
ST = ['wonju', 'seosan', 'pohang', 'yeonggwang']
pull = ['timestamp', 'real_demand_land'] + [f'temp_c_{s}' for s in ST]
con = sqlite3.connect(DB)
df = pd.read_sql(f"SELECT {', '.join(pull)} FROM historical", con, parse_dates=['timestamp'])
con.close()
df = df.sort_values('timestamp').reset_index(drop=True)
df['temp_c'] = df[[f'temp_c_{s}' for s in ST]].mean(axis=1)
y = df['real_demand_land'].replace(0, np.nan)
df['demand'] = y.interpolate('linear').ffill().bfill()
df['hour'] = df.timestamp.dt.hour
df['month'] = df.timestamp.dt.month
df['season'] = df.month.map({12:'겨울',1:'겨울',2:'겨울',3:'봄',4:'봄',5:'봄',
                             6:'여름',7:'여름',8:'여름',9:'가을',10:'가을',11:'가을'})

# ════════════════════════════════════════════════════════════════════
# (B) 피처 중요도 — LGBM(부스팅 트리) gain, 그룹 합산
# ════════════════════════════════════════════════════════════════════
b = lgb.Booster(model_file=MODEL)
gain = dict(zip(b.feature_name(), b.feature_importance(importance_type='gain')))
GROUPS = [
    ('과거 수요 패턴', ['lag336','lag504','rec168','lag168','rec24','lag24']),
    ('요일 · 휴일',    ['day_type','dow_sin','dow_cos']),
    ('기온',           ['temp_c4']),
    ('일사 · 구름',    ['solar_rad','total_cloud','midlow_cloud']),
    ('시간대',         ['hour_sin','hour_cos']),
    ('계절(월)',       ['month_sin','month_cos']),
    ('태양광 보급량',  ['cap_btmppa']),
    ('습도',           ['humidity']),
]
tot = sum(gain.values())
vals = [(name, 100*sum(gain.get(f,0) for f in fs)/tot) for name, fs in GROUPS]
vals.sort(key=lambda x: x[1])
labels = [v[0] for v in vals]; pcts = [v[1] for v in vals]
colors = [ACCENT if l == '기온' else (MUTED if l in ('과거 수요 패턴','요일 · 휴일') else SOFT) for l in labels]

fig, ax = plt.subplots(figsize=(7.4, 4.0))
bars = ax.barh(labels, pcts, color=colors, height=0.66)
for l, p in zip(labels, pcts):
    ax.text(p + 0.6, l, f'{p:.0f}%', va='center', ha='left',
            fontsize=10, color=(ACCENT if l == '기온' else MUTED),
            fontweight=('bold' if l == '기온' else 'normal'))
ax.set_xlim(0, max(pcts) * 1.15)
ax.set_xlabel('모델이 참고하는 비중 (%)', fontsize=10)
ax.set_title('모델은 무엇을 보고 수요를 맞히나', fontsize=14, fontweight='bold', color=INK, loc='left', pad=30)
ax.text(0, 1.03, '부스팅 트리(LGBM)가 참고하는 정보 비중 · 큰 순서', transform=ax.transAxes,
        fontsize=9.5, color=SOFT, ha='left')
clean(ax); ax.tick_params(axis='y', labelsize=10.5)
fig.text(0.012, 0.005,
         "‘과거 수요 패턴’에는 이미 계절·요일·시간 정보가 녹아 있어, 기온이 모델이 추가로 보는 가장 큰 날씨 요인입니다.",
         fontsize=8.6, color=MUTED)
fig.subplots_adjust(top=0.82, bottom=0.20, left=0.20, right=0.95)
fig.savefig(os.path.join(HERE, '5_importance.png'), bbox_inches='tight', dpi=150)
plt.close(fig)

# ════════════════════════════════════════════════════════════════════
# (C) 기온 vs 수요 — 구간별 평균(U자) + 옅은 산점
# ════════════════════════════════════════════════════════════════════
samp = df.sample(min(7000, len(df)), random_state=0)
df['tbin'] = pd.cut(df.temp_c, bins=np.arange(-12, 36, 2))
prof = df.groupby('tbin', observed=False).demand.mean()
cx = [iv.mid for iv in prof.index]

fig, ax = plt.subplots(figsize=(7.4, 4.2))
ax.scatter(samp.temp_c, samp.demand/1000, s=5, c=SOFT, alpha=0.10, edgecolors='none')
ax.plot(cx, np.array(prof.values)/1000, color=ACCENT, lw=2.6, marker='o', ms=5, zorder=5)
ax.set_xlabel('전국 평균 기온 (°C)', fontsize=10)
ax.set_ylabel('전력 수요 (GW)', fontsize=10)
ax.set_title('기온이 오르내리면 전력 수요도 흔들린다', fontsize=14, fontweight='bold', color=INK, loc='left', pad=30)
ax.text(0, 1.03, '추우면 난방, 더우면 냉방 — 양끝에서 수요가 올라가는 U자', transform=ax.transAxes,
        fontsize=9.5, color=SOFT, ha='left')
ax.text(0.04, 0.93, '추울수록\n난방 수요 ↑', transform=ax.transAxes, fontsize=9, color=MUTED, va='top', ha='left')
ax.text(0.96, 0.93, '더울수록\n냉방 수요 ↑', transform=ax.transAxes, fontsize=9, color=MUTED, va='top', ha='right')
clean(ax)
fig.subplots_adjust(top=0.82, bottom=0.14, left=0.11, right=0.96)
fig.savefig(os.path.join(HERE, '5_temp_demand.png'), bbox_inches='tight', dpi=150)
plt.close(fig)

# ════════════════════════════════════════════════════════════════════
# (D) 계절별 시간대 프로파일 — 한낮 눌림(여름 제외) + 계절 레벨 차
# ════════════════════════════════════════════════════════════════════
SEAS = [('겨울', '#3b6ea5'), ('봄', '#4c9a6a'), ('여름', ACCENT), ('가을', '#b5742f')]
fig, ax = plt.subplots(figsize=(7.4, 4.4))
ax.axvspan(9, 15, color=ACCENT, alpha=0.07, zorder=0)
for s, c in SEAS:
    p = df[df.season == s].groupby('hour').demand.mean() / 1000
    lw = 2.8 if s == '여름' else 1.8
    ax.plot(p.index, p.values, color=c, lw=lw, label=s, marker='o', ms=2.5)
ax.text(12, ax.get_ylim()[0] + 0.5, '한낮 09–15시', ha='center', fontsize=8.5, color=MUTED)
ax.set_xlabel('하루 중 시각 (시)', fontsize=10)
ax.set_ylabel('평균 전력 수요 (GW)', fontsize=10)
ax.set_xticks(range(0, 24, 3))
ax.set_title('여름을 빼면, 가장 더운 한낮에 수요가 오히려 눌린다', fontsize=13.5, fontweight='bold', color=INK, loc='left', pad=30)
ax.text(0, 1.03, '계절마다 수요 레벨도 다르다 — 겨울이 가장 높고 봄이 가장 낮다', transform=ax.transAxes,
        fontsize=9.5, color=SOFT, ha='left')
leg = ax.legend(loc='upper left', frameon=False, fontsize=10, ncol=4, columnspacing=1.2, handlelength=1.4,
                bbox_to_anchor=(0, 0.99))
clean(ax)
fig.text(0.012, 0.005,
         "한낮 눌림 = 자가용 태양광이 낮 계통 수요를 끌어내리는 효과(봄·가을에 뚜렷). 여름은 냉방이 더 강해 계속 상승.",
         fontsize=8.6, color=MUTED)
fig.subplots_adjust(top=0.82, bottom=0.20, left=0.10, right=0.97)
fig.savefig(os.path.join(HERE, '5_season_hour.png'), bbox_inches='tight', dpi=150)
plt.close(fig)

print('OK  rows=%d  %s ~ %s' % (len(df), df.timestamp.min().date(), df.timestamp.max().date()))
print('importance(%):', {l: round(p,1) for l, p in zip(labels, pcts)})

# -*- coding: utf-8 -*-
"""5단계 EDA 보고서용 차트 (집 양식: 흰 배경·맑은 고딕).
출력: 5_corr.png / 5_temp_demand.png / 5_season_hour.png"""
import os, sqlite3
import numpy as np, pandas as pd
import matplotlib as mpl, matplotlib.pyplot as plt
import holidays as _holidays

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, '..', '..', '..'))
DB = os.path.join(ROOT, '1. data_fetcher_and_db', 'data', 'input_data_land.db')

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
ST = ['wonju', 'seosan', 'pohang', 'yeonggwang']      # 기온·습도 4지점(모델 정의)
SOL = ['seosan', 'yeonggwang']                         # 일사 2지점
pull = (['timestamp', 'real_demand_land']
        + [f'temp_c_{s}' for s in ST] + [f'humidity_{s}' for s in ST] + [f'solar_rad_{s}' for s in SOL])
con = sqlite3.connect(DB)
df = pd.read_sql(f"SELECT {', '.join(pull)} FROM historical", con, parse_dates=['timestamp'])
con.close()
df = df.sort_values('timestamp').reset_index(drop=True)
df['temp_c'] = df[[f'temp_c_{s}' for s in ST]].mean(axis=1)
df['humidity'] = df[[f'humidity_{s}' for s in ST]].mean(axis=1)
df['solar_rad'] = df[[f'solar_rad_{s}' for s in SOL]].mean(axis=1)
y = df['real_demand_land'].replace(0, np.nan)
df['demand'] = y.interpolate('linear').ffill().bfill()
df['hour'] = df.timestamp.dt.hour
df['month'] = df.timestamp.dt.month
df['season'] = df.month.map({12:'겨울',1:'겨울',2:'겨울',3:'봄',4:'봄',5:'봄',
                             6:'여름',7:'여름',8:'여름',9:'가을',10:'가을',11:'가을'})

# ════════════════════════════════════════════════════════════════════
# (B) 피어슨 상관 — 수요와 각 요인의 선형 상관관계 (모델 무관 데이터 분석)
# ════════════════════════════════════════════════════════════════════
df['feel'] = (df.temp_c - 18).abs()                      # 기온 체감(18°C 기준 절대차)
df['lag24'] = df.demand.shift(24)
df['lag168'] = df.demand.shift(168)
_yrs = list(range(int(df.timestamp.dt.year.min()), int(df.timestamp.dt.year.max()) + 1))
_kr = _holidays.SouthKorea(years=_yrs)
_wend = df.timestamp.dt.dayofweek >= 5
_ishol = df.timestamp.dt.normalize().map(lambda d: d.date() in _kr)
df['nonwork'] = (_wend | _ishol).astype(float)           # 주말·공휴일

CC = [
    ('1주 전 수요',          'lag168'),
    ('하루 전 수요',         'lag24'),
    ('기온 체감(더위·추위)', 'feel'),
    ('일사량',               'solar_rad'),
    ('기온(원본)',           'temp_c'),
    ('습도',                 'humidity'),
    ('주말·공휴일',          'nonwork'),
]
cc = df.dropna(subset=['demand'] + [c for _, c in CC])
rv = [(name, float(np.corrcoef(cc.demand, cc[col])[0, 1])) for name, col in CC]
rv.sort(key=lambda x: x[1])                               # 음→양 (barh 아래→위)
names = [n for n, _ in rv]; rs = [r for _, r in rv]
def barcol(n, r):
    if n.startswith('기온 체감'): return ACCENT
    return '#3b6ea5' if r >= 0 else '#9aa0ac'

fig, ax = plt.subplots(figsize=(7.6, 4.3))
ax.axvline(0, color=MUTED, lw=1, zorder=2)
ax.barh(names, rs, color=[barcol(n, r) for n, r in zip(names, rs)], height=0.66, zorder=3)
for n, r in zip(names, rs):
    ax.text(r + (0.02 if r >= 0 else -0.02), n, f'{r:+.2f}', va='center',
            ha=('left' if r >= 0 else 'right'), fontsize=10,
            color=(ACCENT if n.startswith('기온 체감') else MUTED),
            fontweight=('bold' if n.startswith('기온 체감') else 'normal'))
ax.set_xlim(-0.62, 1.02)
ax.set_xlabel('피어슨 상관계수 r   ·   +1=같이 오르내림 / -1=반대로', fontsize=10)
ax.set_title('무엇이 수요와 함께 움직이나', fontsize=14, fontweight='bold', color=INK, loc='left', pad=30)
ax.text(0, 1.03, '수요와 각 요인의 선형 상관관계(피어슨 r) · 모델과 무관한 데이터 분석', transform=ax.transAxes,
        fontsize=9.5, color=SOFT, ha='left')
ti = names.index('기온(원본)')
ax.annotate('원본 기온은 거의 0\n(더위·추위 둘 다 수요↑인 V자\n→ ‘체감’으로 봐야 보임)',
            xy=(0, ti), xytext=(0.30, ti - 0.55),
            fontsize=8.4, color=MUTED, va='center', ha='left',
            arrowprops=dict(arrowstyle='->', color=SOFT, lw=1.1))
clean(ax); ax.tick_params(axis='y', labelsize=10.5)
fig.text(0.012, 0.005,
         "과거 수요(반복성)가 가장 강하고, 날씨는 기온을 ‘체감’으로 바꿔야 신호가 드러납니다. "
         "일사는 한낮 효과가 계절·태양광에 따라 달라 단순 상관은 작습니다.",
         fontsize=8.0, color=MUTED)
fig.subplots_adjust(top=0.82, bottom=0.20, left=0.22, right=0.96)
fig.savefig(os.path.join(HERE, '5_corr.png'), bbox_inches='tight', dpi=150)
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
print('corr(r):', {n: round(r, 3) for n, r in rv})

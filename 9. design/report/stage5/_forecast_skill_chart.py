# -*- coding: utf-8 -*-
"""5단계 보고서용 — 지평별 예보 정보력(ACC) 감쇠 차트 (집 양식).
데이터 forecast_skill.csv · 출력 5_forecast_skill.png"""
import os
import numpy as np, pandas as pd
import matplotlib as mpl, matplotlib.pyplot as plt

HERE = os.path.dirname(os.path.abspath(__file__))
df = pd.read_csv(os.path.join(HERE, 'forecast_skill.csv'))

INK, MUTED, SOFT, ACCENT = '#2d3142', '#4f5d75', '#7a8399', '#eb6c36'
TEMP =  "#C55D6E"
RULE = '#d9dce3'
mpl.rcParams.update({
    'font.family': 'Malgun Gothic', 'axes.unicode_minus': False,
    'figure.facecolor': 'white', 'axes.facecolor': 'white', 'savefig.facecolor': 'white',
    'axes.edgecolor': MUTED, 'axes.labelcolor': INK, 'text.color': INK,
    'xtick.color': MUTED, 'ytick.color': MUTED, 'figure.dpi': 150,
})

H = list(range(1, 16))
def acc(ch):
    s = df[df.channel == ch].set_index('horizon')['ACC']
    return [s.get(h, np.nan) for h in H]

# 기온만 강조(주황), 나머지는 차분한 색·가는 선
series = [
    ('temp_c',      '기온',       ACCENT,    3.0),
    ('solar_rad',   '일사(햇빛)', '#b5742f', 1.6),
    ('rh',          '습도',       '#3b6ea5', 1.6),
    ('wind',        '풍속',       '#4c9a6a', 1.6),
    ('total_cloud', '구름',       '#9aa0ac', 1.6),
]

fig, ax = plt.subplots(figsize=(7.8, 4.6))

# 먼 미래(D+10~) 음영 — 기온만 살아남는 구간
ax.axvspan(7.0, 9.5, color=TEMP, alpha=0.045, zorder=0)
ax.axvspan(9.5, 15.5, color=INK, alpha=0.045, zorder=0)
# 노이즈 기준선
ax.axhline(0.2, ls='--', lw=1.1, color=SOFT, zorder=1)
ax.text(4.0, 0.225, '평년값 = 약 0.2', va='bottom', ha='right', fontsize=10, color=SOFT)

for ch, label, color, lw in series:
    a = 1.0 if ch == 'temp_c' else 0.9
    mk = dict(marker='o', ms=5.5) if ch == 'temp_c' else dict(marker='o', ms=3.2)
    ax.plot(H, acc(ch), lw=lw, color=color, label=label, alpha=a, zorder=(4 if ch=='temp_c' else 3),
            markeredgecolor='white', markeredgewidth=0.6, **mk)

ax.annotate('기온은 다른 요소대비 대비 정확도 유지.', xy=(7, acc('temp_c')[6]), xytext=(7, 0.92),
            fontsize=9.5, color=ACCENT, fontweight='bold', ha='center', va='bottom',
            arrowprops=dict(arrowstyle='->', color=ACCENT, lw=1.4))

ax.set_xlim(0.5, 15.5); ax.set_ylim(-0.02, 1.0)
ax.set_xticks(H); ax.set_xticklabels([f'D+{h}' for h in H], fontsize=8.8)
ax.set_yticks(np.arange(0, 1.01, 0.2))
ax.set_xlabel('예보지평', fontsize=10)
ax.set_ylabel('예보 정확도  (1 = 완벽)', fontsize=10)
ax.set_title('예보 요소별 지평에 따른 정확도 변화', fontsize=14, fontweight='bold', color=INK, loc='center', pad=30)
#ax.text(0, 1.03, "날씨 항목별 예보 정보력 — 기온만 먼 미래까지 살아남는다", transform=ax.transAxes,
#        fontsize=9.5, color=SOFT, ha='left')
ax.legend(loc='upper right', frameon=False, fontsize=9.5, ncol=1, handlelength=1.6)
for s in ('top', 'right'): ax.spines[s].set_visible(False)
for s in ('left', 'bottom'): ax.spines[s].set_color(RULE)
ax.tick_params(length=0)

#fig.text(0.012, 0.005,
#         "→ 그래서 먼 미래일수록 모델은 노이즈가 된 날씨 예보보다 최근 같은 요일 실측(기준선)·달력에 더 기댑니다.",
#         fontsize=8.6, color=MUTED)
fig.subplots_adjust(top=0.82, bottom=0.18, left=0.09, right=0.97)
fig.savefig(os.path.join(HERE, '5_forecast_skill.png'), bbox_inches='tight', dpi=150)
print('saved 5_forecast_skill.png')

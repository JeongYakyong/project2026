# -*- coding: utf-8 -*-
import os
import numpy as np, pandas as pd
import matplotlib
from matplotlib.figure import Figure
from matplotlib.backends.backend_agg import FigureCanvasAgg
matplotlib.rcParams['font.family'] = 'Malgun Gothic'
matplotlib.rcParams['axes.unicode_minus'] = False

CSV = r"C:\Users\bjkim\Desktop\project2026\5. land_demand_forecaster\training\_eda_forecast_skill.csv"
out = os.environ.get("CHART_OUTPUT", "/tmp/chart_review.png")
df = pd.read_csv(CSV)

H = list(range(1, 16))
def acc(ch):
    s = df[(df.channel == ch)].set_index('horizon')['ACC']
    return [s.get(h, np.nan) for h in H]

series = [
    ('temp_c',      '기온',   '#c0392b', 3.2, 'o'),
    ('rh',          '습도',   '#2980b9', 1.8, 's'),
    ('wind',        '풍속',   '#16a085', 1.8, '^'),
    ('solar_rad',   '일사(햇빛)', '#e67e22', 1.8, 'D'),
    ('total_cloud', '구름',   '#7f8c8d', 1.8, 'v'),
]

fig = Figure(figsize=(11, 6.4))
FigureCanvasAgg(fig)
ax = fig.add_subplot(1, 1, 1)

# 구간 음영: D+1~5 = 모든 예보 유효 / D+10~ = 기온만 생존
ax.axvspan(0.5, 5.5, color='#2ecc71', alpha=0.07, zorder=0)
ax.axvspan(9.5, 15.5, color='#95a5a6', alpha=0.10, zorder=0)

# 노이즈 기준선
ax.axhline(0.2, ls='--', lw=1.2, color='#888', zorder=1)
ax.text(15.3, 0.205, '이 아래는 거의 노이즈\n(평년값과 다를 바 없음)', va='bottom', ha='right',
        fontsize=9.5, color='#666')

for ch, label, color, lw, mk in series:
    ax.plot(H, acc(ch), marker=mk, ms=5.5, lw=lw, color=color, label=label, zorder=3,
            markeredgecolor='white', markeredgewidth=0.6)

# 구간 라벨
ax.text(3, 1.02, 'D+5까지: 모든 날씨 예보가 쓸모 있음', ha='center', fontsize=11,
        color='#1e8449', fontweight='bold')
ax.text(12.5, 1.02, 'D+10 이후: 기온만 살아남음', ha='center', fontsize=11,
        color='#566573', fontweight='bold')

# 기온 강조 주석
ax.annotate('기온은 가장 오래 신뢰할 수 있다',
            xy=(10, acc('temp_c')[9]), xytext=(11.2, 0.74),
            fontsize=10, color='#c0392b',
            arrowprops=dict(arrowstyle='->', color='#c0392b', lw=1.5))

ax.set_xlim(0.5, 15.5); ax.set_ylim(-0.05, 1.06)
ax.set_xticks(H); ax.set_xticklabels([f'D+{h}' for h in H], fontsize=9.5)
ax.set_yticks(np.arange(0, 1.01, 0.2))
ax.set_xlabel('며칠 뒤를 예보하는가 (예보 지평)', fontsize=11.5)
ax.set_ylabel("예보 정보력  (1=완벽 · 0=쓸모없음)", fontsize=11.5)
ax.set_title("예보는 멀어질수록 쓸모가 사라진다 — 날씨 항목별 '예보 정보력'",
             fontsize=14.5, fontweight='bold', pad=26)
ax.legend(loc='upper right', frameon=True, fontsize=10.5, ncol=1, framealpha=0.9)
ax.grid(True, alpha=0.25)
for sp in ['top', 'right']:
    ax.spines[sp].set_visible(False)

fig.text(0.5, -0.01,
         "→ 그래서 학습 때도 '가까운 미래는 정밀한 예보, 먼 미래는 거친 예보'를 흉내 내 입력한다. "
         "먼 미래엔 모델이 자동으로 기온·달력·과거패턴에 기댄다.",
         ha='center', fontsize=9.8, color='#444')

fig.savefig(out, dpi=150, bbox_inches='tight')
print("saved", out)

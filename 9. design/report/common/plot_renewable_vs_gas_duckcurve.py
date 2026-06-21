# -*- coding: utf-8 -*-
"""
친환경 발전 확대가 발전용 가스를 밀어낸다 — 봄철 한낮의 증거 (전국, 시간별 실측)
그림 복원 스크립트.  (원본 renewable_vs_gas_duckcurve_2022_2026.png 의 코드가 유실되어 복원)

데이터 출처(2종):
  ① 신재생 설비용량  : 1. data_fetcher_and_db/second_dataset/
                       HOME_전력거래_시장참여설비용량(전력시장·PPA)_연료원별.csv  (cp949, 월별)
  ②③④ 시간별 발전  : 1. data_fetcher_and_db/data/input_data_land.db  ·  table=historical
                       (gen_gas_kr, gen_solar_market_kr ; 단위 MW → /1000 GW ; gen_gas는 2022~)

주의: 위 용량 CSV는 원본 그림 작성 이후 갱신·재분류되어(신재생 '기타' 분류 변경 등),
      ①의 합계·배수 주석은 현재 데이터 기준으로 다시 계산됩니다(원본 43,019MW·5.4배와 약간 다름).

실행: python plot_renewable_vs_gas_duckcurve.py
출력: renewable_vs_gas_duckcurve_2022_2026.png
"""
import os, sqlite3, calendar
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib as mpl

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CAP_CSV = os.path.join(ROOT, '1. data_fetcher_and_db', 'second_dataset',
                       'HOME_전력거래_시장참여설비용량(전력시장·PPA)_연료원별.csv')
DB = os.path.join(ROOT, '1. data_fetcher_and_db', 'data', 'input_data_land.db')
OUT = os.path.join(HERE, 'renewable_vs_gas_duckcurve_2022_2026.png')

YEARS = [2022, 2023, 2024, 2025, 2026]            # 시간별 가스 실측이 있는 봄철
SPRING = [4, 5, 6]
# 연도별 색 (옅은 주황 → 진한 빨강)
YCOLOR = {2022: '#f3c98a', 2023: '#eea35a', 2024: '#e3743a', 2025: '#cf4429', 2026: '#8c1d1d'}

# ── 데이터 ① 신재생 설비용량 (연도별, 12월 기준) ───────────────────────────
cap = pd.read_csv(CAP_CSV, encoding='cp949')
cap.columns = ['period', 'gubun', 'nuclear', 'coal', 'oil', 'lng', 'pump',
               'nre_etc', 'solar', 'wind', 'etc', 'mkt_sum', 'ppa_sum', 'mkt_ppa_sum']
mon = {m: i for i, m in enumerate(calendar.month_abbr) if m}
cap['year'] = cap['period'].str.split('-').str[1].astype(int) + 2000
cap['month'] = cap['period'].str.split('-').str[0].map(mon)
cap = cap.sort_values(['year', 'month'])
# 각 연도의 마지막(대표) 월
rep = cap.sort_values('month').groupby('year').tail(1).set_index('year').sort_index()
rep = rep.loc[(rep.index >= 2014) & (rep.index <= 2026)]
rep['ppa_sum'] = rep['ppa_sum'].fillna(0.0)        # PPA는 2020~ (이전 0)
# 누적용량(MW): 태양광 / 풍력 / PPA / 신재생 기타
cap_solar, cap_wind, cap_ppa, cap_etc = rep['solar'], rep['wind'], rep['ppa_sum'], rep['nre_etc']
cap_total = cap_solar + cap_wind + cap_ppa + cap_etc

# ── 데이터 ②③④ 시간별 발전 (봄철) ────────────────────────────────────────
con = sqlite3.connect(DB)
hr = pd.read_sql("SELECT timestamp,gen_gas_kr,gen_solar_market_kr FROM historical",
                 con, parse_dates=['timestamp'])
con.close()
hr['year'] = hr.timestamp.dt.year
hr['month'] = hr.timestamp.dt.month
hr['hour'] = hr.timestamp.dt.hour
sp = hr[hr.month.isin(SPRING) & hr.year.isin(YEARS)].copy()
sp['gas'] = sp['gen_gas_kr'] / 1000.0          # GW
sp['solar'] = sp['gen_solar_market_kr'] / 1000.0

# 시간대별 평균 가스(GW)
gas_hour = sp.groupby(['year', 'hour'])['gas'].mean().unstack(0)

# 연도별 한낮(11~15)·심야(0~5) 가스, 한낮 시장 태양광
def band(s, lo, hi, col):
    return s[s.hour.between(lo, hi)].groupby('year')[col].mean()
midday_gas = band(sp, 11, 15, 'gas')
night_gas  = band(sp, 0, 5, 'gas')
midday_sol = band(sp, 11, 15, 'solar')
gap = (midday_gas - night_gas)

# ── 그림 ──────────────────────────────────────────────────────────────────
plt.style.use('seaborn-v0_8-whitegrid')
mpl.rcParams['font.family'] = 'Malgun Gothic'
mpl.rcParams['axes.unicode_minus'] = False
fig, axs = plt.subplots(2, 2, figsize=(18, 11))
ax1, ax2, ax3, ax4 = axs.ravel()

# ① 신재생 설비용량 구성 추이 (누적 영역)
yrs = rep.index.values
ax1.stackplot(yrs, cap_solar, cap_wind, cap_ppa, cap_etc,
              labels=['태양광', '풍력', 'PPA', '신재생 기타'],
              colors=['#22b8c4', '#f0a830', '#8e6fb0', '#5aa96f'], alpha=0.9)
ax1.axvline(2025.5, color='#888', ls='--', lw=1)
t0, t1 = cap_total.iloc[0], cap_total.iloc[-1]
ax1.annotate(f'{t1:,.0f} MW\n(PPA 시장 포함)', xy=(yrs[-1], t1), xytext=(yrs[-1] - 3.2, t1 * 0.78),
             fontsize=10, ha='left', color='#333',
             arrowprops=dict(arrowstyle='->', color='#666'))
ax1.text(0.02, 0.95, f'합계 {t0:,.0f} MW → {t1:,.0f} MW (약 {t1/t0:.1f}배)',
         transform=ax1.transAxes, fontsize=10, va='top', color='#333',
         bbox=dict(boxstyle='round', fc='white', ec='#ccc'))
ax1.set_title('① 친환경 발전용량 구성 추이 (2014~2026)', fontsize=14, fontweight='bold')
ax1.set_ylabel('설비용량 (MW)')
ax1.set_xlim(yrs.min(), yrs.max())
ax1.set_xticks(yrs)
ax1.set_xticklabels([str(y) for y in yrs], rotation=45, fontsize=8)
ax1.legend(loc='upper left', fontsize=9, framealpha=0.9)

# ② 봄철 시간대별 가스 발전 — 덕 커브 심화
for y in YEARS:
    if y in gas_hour.columns:
        lw = 2.6 if y == YEARS[-1] else 1.6
        ax2.plot(gas_hour.index, gas_hour[y], color=YCOLOR[y], lw=lw, label=str(y))
ax2.axvspan(11, 15, color='#f5d76e', alpha=0.25)
ax2.annotate('한낮 가스 발전 심화\n(태양광이 밀어냄)', xy=(13, gas_hour.loc[13].min()),
             xytext=(8, gas_hour.min().min() + 0.3), fontsize=9, color='#a33',
             arrowprops=dict(arrowstyle='->', color='#a33'))
ax2.set_title('② 봄철(4~6월) 시간대별 가스 발전 — 덕 커브 심화', fontsize=14, fontweight='bold')
ax2.set_ylabel('가스 발전 (GW)')
ax2.set_xlabel('시각 (시)')
ax2.set_xticks(range(0, 24, 3))
ax2.legend(title='연도', loc='upper left', fontsize=9, ncol=1)

# ③ 한낮 가스가 심야 수준으로 붕괴 (격차)
x = np.arange(len(YEARS))
ax3.bar(x, midday_gas.reindex(YEARS).values, width=0.55, color='#c0392b',
        label='한낮(11~15시) 가스', zorder=2)
ax3.plot(x, night_gas.reindex(YEARS).values, 'o--', color='#7a8399', lw=1.6,
         label='심야(0~5시) 가스', zorder=3)
ax3.plot(x, midday_sol.reindex(YEARS).values, 's-', color='#e8b800', lw=1.8,
         label='한낮 시장 태양광', zorder=3)
for i, y in enumerate(YEARS):
    ax3.annotate(f'+{gap[y]:.1f}', (i, midday_gas[y] + 0.3), ha='center',
                 fontsize=9, color='#333', fontweight='bold')
g0, g1 = gap[YEARS[0]], gap[YEARS[-1]]
ax3.set_title(f'③ 한낮 가스가 심야 수준으로 붕괴 (격차 +{g0:.1f} → +{g1:.1f} GW)',
              fontsize=14, fontweight='bold')
ax3.set_ylabel('가스 · 태양광 (GW)')
ax3.set_xticks(x)
ax3.set_xticklabels([str(y) for y in YEARS])
ax3.legend(loc='upper right', fontsize=9)

# ④ 한낮 태양광↑ vs 한낮 가스↓ (봄철)
xs = midday_sol.reindex(YEARS).values
ys = midday_gas.reindex(YEARS).values
for i, y in enumerate(YEARS):
    ax4.scatter(xs[i], ys[i], s=120, color=YCOLOR[y], zorder=3, edgecolor='white')
    ax4.annotate(str(y), (xs[i], ys[i]), xytext=(6, 6), textcoords='offset points',
                 fontsize=9, color='#333')
b, a = np.polyfit(xs, ys, 1)              # 기울기 b, 절편 a
xx = np.linspace(xs.min(), xs.max(), 10)
ax4.plot(xx, a + b * xx, '--', color='#888', lw=1.4)
r = np.corrcoef(xs, ys)[0, 1]
ax4.text(0.97, 0.95, f'상관계수 r = {r:+.2f}\n+1GW 태양광 → 가스 {b:+.2f} GW',
         transform=ax4.transAxes, ha='right', va='top', fontsize=10, color='#333',
         bbox=dict(boxstyle='round', fc='white', ec='#ccc'))
ax4.set_title('④ 한낮 태양광↑ vs 한낮 가스↓ (봄철, 2022~2026)', fontsize=14, fontweight='bold')
ax4.set_xlabel('한낮 시장 태양광 (GW)')
ax4.set_ylabel('한낮 가스 (GW)')

fig.suptitle('친환경 발전 확대가 발전용 가스를 밀어낸다 — 봄철 한낮의 증거 (전국, 시간별 실측)',
             fontsize=17, fontweight='bold', y=0.99)
fig.text(0.5, 0.005,
         '자료: 시장친환경발전 input_data_land.db · historical(시간별 발전). '
         'gen_gas_kr(gas market view) · gen_solar_market_kr(시장 태양광). '
         '기간: 시간별 발전 2022년부터(가스 실측 시작). 신재생 설비용량은 KPX 전력거래 시장참여설비용량.',
         ha='center', fontsize=9, color='#999')

fig.tight_layout(rect=[0, 0.02, 1, 0.97])
fig.savefig(OUT, dpi=120, bbox_inches='tight')
print('saved:', OUT)
print(f'  ① 합계 {t0:,.0f}→{t1:,.0f} MW ({t1/t0:.2f}x) | ③ 격차 +{g0:.1f}→+{g1:.1f} | ④ r={r:+.2f}, slope={b:+.2f}')

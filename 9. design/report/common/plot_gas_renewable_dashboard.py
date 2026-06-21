# -*- coding: utf-8 -*-
"""
천연가스 수요와 친환경 발전 — 핵심 지표 한눈에 보기 (보고서용 4패널)

  ① 같은 달 전년대비 변화율(YoY)  — 도시가스 vs 발전 (선)
  ② 같은 달 연도별 변동폭         — 발전이 훨씬 출렁인다 (막대)
  ③ 친환경 발전 설비용량 추이      — 2014~2026 (누적 영역)
  ④ 봄철(4~6월) 시간대별 가스 발전 — 한낮 덕 커브 (선)

문서에 넣어도 잘 보이도록 눈금·축 글씨를 크고 굵게 그린다.
양식: 흰 배경 · 맑은 고딕 · 강조 주황(#eb6c36) — 9. design/drawing_rule.md 준수.

데이터 출처(3종):
  ①② 한국가스공사 용도별 월 공급량 :  (이 폴더) 한국가스공사_용도별 월 공급량_20260331.csv (cp949)
  ③   신재생 설비용량              :  1. data_fetcher_and_db/second_dataset/
                                      HOME_전력거래_시장참여설비용량(전력시장·PPA)_연료원별.csv (cp949)
  ④   시간별 가스 발전             :  1. data_fetcher_and_db/data/input_data_land.db · historical.gen_gas_kr

실행:  python plot_gas_renewable_dashboard.py   →  같은 폴더에 gas_renewable_dashboard.png
"""
import os, sqlite3, calendar
import numpy as np
import pandas as pd
import matplotlib as mpl
from matplotlib.figure import Figure
from matplotlib.backends.backend_agg import FigureCanvasAgg

# ────────────────────────────────────────────────────────────────────────────
# ▼▼▼  보통 여기 값만 고치면 됩니다  ▼▼▼
# ────────────────────────────────────────────────────────────────────────────
# 색 (디자인 양식)
C_CITY   = "#228197"   # 도시가스 (먹색)
C_POWER  = '#eb6c36'   # 발전 (강조 주황)
CAP_COLORS = {'태양광':'#f0a830', '풍력':'#4a9d6a', 'PPA':'#8e6fb0', '신재생 기타':'#9aa3b2'}
YEAR_GRAD  = {2022:'#f3c98a', 2023:'#eea35a', 2024:'#e3743a', 2025:'#cf4429', 2026:'#8c1d1d'}

# 글씨 크기 (문서 삽입용 — 크고 굵게)
FS_TICK    = 16   # 눈금 글씨
FS_AXLABEL = 17   # 축 제목
FS_TITLE   = 18   # 패널 제목
FS_LEGEND  = 14   # 범례
FS_SUPTTL  = 23   # 전체 제목

SPRING = [4, 5, 6]
DUCK_YEARS = [2022, 2023, 2024, 2025, 2026]   # 시간별 가스 실측 구간
YOY_START  = '2020-01'                         # ①② 표시 시작
# ────────────────────────────────────────────────────────────────────────────
# ▲▲▲  여기까지  ▲▲▲
# ────────────────────────────────────────────────────────────────────────────

HERE = os.path.dirname(os.path.abspath(__file__))                       # 9. design/report/common
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))          # 프로젝트 루트
GAS_CSV = os.path.join(HERE, '한국가스공사_용도별 월 공급량_20260331.csv')
CAP_CSV = os.path.join(ROOT, '1. data_fetcher_and_db', 'second_dataset',
                       'HOME_전력거래_시장참여설비용량(전력시장·PPA)_연료원별.csv')
DB = os.path.join(ROOT, '1. data_fetcher_and_db', 'data', 'input_data_land.db')
OUT = os.environ.get('CHART_OUTPUT', os.path.join(HERE, 'gas_renewable_dashboard.png'))

mpl.rcParams['font.family'] = 'Malgun Gothic'
mpl.rcParams['axes.unicode_minus'] = False

# ── 공통: 축을 크고 굵게 ────────────────────────────────────────────────────
def style_axis(ax, title, xlabel=None, ylabel=None):
    ax.set_title(title, fontsize=FS_TITLE, fontweight='bold', pad=12)
    if xlabel: ax.set_xlabel(xlabel, fontsize=FS_AXLABEL, fontweight='bold')
    if ylabel: ax.set_ylabel(ylabel, fontsize=FS_AXLABEL, fontweight='bold')
    ax.tick_params(axis='both', labelsize=FS_TICK, width=1.4, length=6)
    for lab in ax.get_xticklabels() + ax.get_yticklabels():
        lab.set_fontweight('bold')
    ax.grid(True, color='#d8dbe0', lw=0.8, alpha=0.9)
    for s in ax.spines.values():
        s.set_edgecolor('#b9bdc6')

# ── 데이터 ①② 용도별 월 공급량 ─────────────────────────────────────────────
gas = pd.read_csv(GAS_CSV, encoding='cp949')
gas.columns = ['year', 'month', 'category', 'supply']
gas['supply'] /= 1000.0                                # 톤 → 천톤
gas['date'] = pd.to_datetime(dict(year=gas.year, month=gas.month, day=1))
piv = gas.pivot_table(index='date', columns='category', values='supply').sort_index()
CATS = {'도시가스': C_CITY, '발전': C_POWER}
yoy = piv.pct_change(12) * 100.0
yoy_plot = yoy.loc[yoy.index >= YOY_START]

# ── 데이터 ③ 신재생 설비용량 ────────────────────────────────────────────────
cap = pd.read_csv(CAP_CSV, encoding='cp949')
cap.columns = ['period','gubun','nuclear','coal','oil','lng','pump',
               'nre_etc','solar','wind','etc','mkt_sum','ppa_sum','mkt_ppa_sum']
mon = {m: i for i, m in enumerate(calendar.month_abbr) if m}
cap['year']  = cap['period'].str.split('-').str[1].astype(int) + 2000
cap['month'] = cap['period'].str.split('-').str[0].map(mon)
rep = cap.sort_values('month').groupby('year').tail(1).set_index('year').sort_index()
rep = rep.loc[(rep.index >= 2014) & (rep.index <= 2026)]
rep['ppa_sum'] = rep['ppa_sum'].fillna(0.0)
cap_series = {'태양광': rep['solar']/1000, '풍력': rep['wind']/1000,
              'PPA': rep['ppa_sum']/1000, '신재생 기타': rep['nre_etc']/1000}
cap_total = sum(cap_series.values())*1000

# ── 데이터 ④ 시간별 가스 발전 ──────────────────────────────────────────────
con = sqlite3.connect(DB)
hr = pd.read_sql("SELECT timestamp,gen_gas_kr FROM historical", con, parse_dates=['timestamp'])
con.close()
hr['year']  = hr.timestamp.dt.year
hr['month'] = hr.timestamp.dt.month
hr['hour']  = hr.timestamp.dt.hour
sp = hr[hr.month.isin(SPRING) & hr.year.isin(DUCK_YEARS)].copy()
sp['gas'] = sp['gen_gas_kr'] / 1000.0                  # GW
gas_hour = sp.groupby(['year', 'hour'])['gas'].mean().unstack(0)

# ── 그림 (2×2) ─────────────────────────────────────────────────────────────
fig = Figure(figsize=(17, 13))
FigureCanvasAgg(fig)
fig.patch.set_facecolor('white')
ax1 = fig.add_subplot(2, 2, 1); ax2 = fig.add_subplot(2, 2, 2)
ax3 = fig.add_subplot(2, 2, 3); ax4 = fig.add_subplot(2, 2, 4)
for ax in (ax1, ax2, ax3, ax4):
    ax.set_facecolor('white')

# ① YoY 변화율
for cat, color in CATS.items():
    ax1.plot(yoy_plot.index, yoy_plot[cat], marker='o', ms=4.5, lw=2.2, color=color, label=cat)
ax1.axhline(0, color='#333', lw=1.2)
style_axis(ax1, '① 같은 달 전년대비 변화율 (YoY)', ylabel='전년 같은 달 대비 (%)')
ax1.legend(fontsize=FS_LEGEND, loc='upper right', framealpha=0.95, prop={'weight':'bold'})

# ② 같은 달 연도별 변동폭 (막대)
sub = gas[gas.date >= YOY_START]
x = np.arange(12); bw = 0.4
for i, (cat, color) in enumerate(CATS.items()):
    vals = [((s.max()-s.min())/s.mean()*100) if len(s) else np.nan
            for m in range(1, 13)
            for s in [sub[(sub.category == cat) & (sub.month == m)]['supply']]]
    ax2.bar(x + (i-0.5)*bw, vals, width=bw, color=color, label=cat)
style_axis(ax2, '② 발전용 가스와 도시가스의 연도별 변동폭',
           ylabel='(최대 — 최소)/평균 (%)')
ax2.set_xticks(x); ax2.set_xticklabels([f'{m}월' for m in range(1, 13)])
ax2.legend(fontsize=FS_LEGEND, loc='upper right', framealpha=0.95, prop={'weight':'bold'})

# ③ 친환경 발전 설비용량 추이 (누적 영역)
yrs = rep.index.values
ax3.stackplot(yrs, *cap_series.values(), labels=list(cap_series.keys()),
              colors=[CAP_COLORS[k] for k in cap_series], alpha=0.92)
ax3.axvline(2025.5, color='#888', ls='--', lw=1.2)
t0, t1 = cap_total.iloc[0], cap_total.iloc[-1]
ax3.text(0.04, 0.52, f'합계 {t0:,.0f} → {t1:,.0f} MW\n(약 {t1/t0:.1f}배)',
         transform=ax3.transAxes, fontsize=FS_LEGEND+1, fontweight='bold', va='top',
         bbox=dict(boxstyle='round', fc='white', ec='#ccc'))
style_axis(ax3, '③ 친환경 발전 설비용량 추이 (2014~2026)', ylabel='설비용량 (GW)')
ax3.set_xlim(yrs.min(), yrs.max())
ax3.set_xticks(yrs[::2]); ax3.set_xticklabels([str(y) for y in yrs[::2]])
ax3.legend(fontsize=FS_LEGEND, loc='upper left', framealpha=0.95, prop={'weight':'bold'})

# ④ 봄철 시간대별 가스 발전 — 덕 커브
for y in DUCK_YEARS:
    if y in gas_hour.columns:
        lw = 3.4 if y == DUCK_YEARS[-1] else 1.8
        ax4.plot(gas_hour.index, gas_hour[y], color=YEAR_GRAD[y], lw=lw, label=str(y))
ax4.axvspan(11, 15, color='#f5d76e', alpha=0.22)
ax4.annotate('한낮 가스 감소\n(태양광이 밀어냄)', xy=(13, gas_hour.loc[11:15].min().min()),
             xytext=(15.2, gas_hour.min().min()+0.2), fontsize=FS_LEGEND, fontweight='bold',
             color='#a33', arrowprops=dict(arrowstyle='->', color='#a33', lw=1.6))
style_axis(ax4, '④ 봄철(4~6월) 시간대별 가스 발전',
           xlabel='시각 (시)', ylabel='가스 발전 (GW)')
ax4.set_xticks(range(0, 24, 3))
ax4.legend(title='연도', fontsize=FS_LEGEND, loc='upper left', framealpha=0.95,
           prop={'weight':'bold'}, title_fontproperties={'weight':'bold','size':FS_LEGEND})

fig.suptitle('천연가스 수요의 변동과 신새쟁 발전량의 영향력',
             fontsize=FS_SUPTTL, fontweight='bold', y=0.985)
fig.subplots_adjust(left=0.06, right=0.98, top=0.92, bottom=0.07, hspace=0.28, wspace=0.18)
fig.savefig(OUT, dpi=150, facecolor='white')
print('saved:', OUT)

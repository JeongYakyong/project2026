# -*- coding: utf-8 -*-
"""7-B 제주 probe EDA notebook 빌더.
PROJECT.md §5.0.5 / G-9 산출물(제주판). jeju_full.parquet로 net_load -> lng_gen(only_gen 실측) 관계,
시계열 구조, 시간적 안정성, **신재생 대체효과(제주는 강함)**, **2024-06 시범사업 레짐 점검**,
train<->test 분포 겹침을 본다.
실행: python build_7b_eda_nb.py  (생성 후 nbconvert --execute 는 호출측에서)
"""
import nbformat as nbf

nb = nbf.v4.new_notebook()
cells = []

def md(t): cells.append(nbf.v4.new_markdown_cell(t))
def code(t): cells.append(nbf.v4.new_code_cell(t))

md("""# 7-B. 제주 probe — net_load → 가스 발전 EDA (G-9 게이트, 제주판)

> PROJECT.md §5.0.5 / Decision Gate **G-9**(단계마다 적용). 7단계 §4 `7-B 제주 probe`.
> 목적: 제주 모델 착수 전에 **명제(§1.2 검증목표 1)가 제주 데이터에 실제로 있는지** 확인한다.
> 제주는 침투율이 높아(≈17.5%) **계량 신재생만으로 대체효과가 직접 강하다** — 전국(7-0)에서 약했던 그 효과의 입증 무대다.

확인 항목:
1. 타깃(`lng_gen`=`only_gen` 실측 2020–2024) 분포 — 0(가스 꺼짐) 비중
2. `net_load` ↔ `lng_gen` 관계의 강도·형태(부하수준별 비선형, merit-order)
3. 시계열 구조(시·요일·월 주기성, 연도 추세)
4. **시간적 안정성** — 연도별로 같은 net_load의 가스 발전이 표류하는가
5. **★ 신재생 → 가스 대체효과** — 수요 통제 후 직접 측정(제주는 강함, "전국 −0.33 vs 제주 −0.??" 대비)
6. **★ 2024-06 제주 전력거래 시범사업 레짐 점검** — 급전순위는 전/후 동일할 전망이나, 함수 표류를 안전하게 확인·라벨
7. **train ↔ test net_load 분포 겹침** — 외삽 위험

> 정직성: `lng_gen`은 2020–2024 `only_gen` **실측**만 사용한다(2025–2026 `derived`는 net_load 자기참조라 제외).
""")

code("""import pandas as pd, numpy as np
import matplotlib.pyplot as plt
import matplotlib as mpl
from pathlib import Path

mpl.rcParams['figure.dpi'] = 110
mpl.rcParams['axes.grid'] = True
mpl.rcParams['font.size'] = 10
# 한글 폰트(Windows): 깨짐 방지
for _f in ['Malgun Gothic','NanumGothic','AppleGothic']:
    try:
        mpl.rcParams['font.family'] = _f; break
    except Exception: pass
mpl.rcParams['axes.unicode_minus'] = False

DATA = Path('../../1. data_fetcher_and_db/second_dataset/data/jeju_full.parquet')
FIG = Path('fig'); FIG.mkdir(exist_ok=True)
TAB = Path('tab'); TAB.mkdir(exist_ok=True)

raw = pd.read_parquet(DATA)
raw['timestamp'] = pd.to_datetime(raw['timestamp'])
# ★ 실측 타깃만(only_gen 2020-2024). derived(2025-26)는 자기참조라 정확도 산출에서 제외.
df = raw[raw['target_source'] == 'measured'].copy()
df['year'] = df['timestamp'].dt.year
print('실측(only_gen) 사용 행수', len(df), '| 기간', df['timestamp'].min(), '->', df['timestamp'].max())
print('target_source 전체 분포:', dict(raw['target_source'].value_counts()))
df[['net_load','lng_gen','real_demand_jeju','real_renew_gen_jeju','real_solar_gen_jeju','real_wind_gen_jeju']].describe().round(1)
""")

md("## 1. 타깃 분포 — 가스가 꺼지는 시간(0)이 얼마나 되나")
code("""zero_rate = (df['lng_gen'] == 0).mean()
print(f'lng_gen == 0 비율: {zero_rate:.1%}')
print(f'lng_gen > 0 일 때 평균: {df.loc[df.lng_gen>0,"lng_gen"].mean():.1f} MW | 전체 평균 {df.lng_gen.mean():.1f} MW')

fig, ax = plt.subplots(1, 2, figsize=(11, 3.5))
ax[0].hist(df['lng_gen'], bins=60, color='steelblue')
ax[0].set_title('lng_gen 전체 분포'); ax[0].set_xlabel('MW')
ax[1].hist(df.loc[df.lng_gen>0,'lng_gen'], bins=60, color='seagreen')
ax[1].set_title('lng_gen > 0 만'); ax[1].set_xlabel('MW')
plt.tight_layout(); plt.savefig(FIG/'7b_01_target_dist.png'); plt.show()
""")
md("""**읽는 법**: 0 비중이 작으면 가스가 거의 항상 켜져 있다(제주 LNG는 기저+첨두 혼합). 0이 잦으면 저부하에서 merit-order상 꺼지는 임계 거동.""")

md("## 2. net_load ↔ lng_gen 관계 (핵심 — 명제 그 자체)")
code("""r_all = np.corrcoef(df['net_load'], df['lng_gen'])[0,1]
print(f'전체 피어슨 상관 r = {r_all:.3f}')

df['nl_bin'] = pd.qcut(df['net_load'], 20, duplicates='drop')
g = df.groupby('nl_bin', observed=True).agg(
    net_load=('net_load','mean'),
    gas_mean=('lng_gen','mean'),
    gas_std=('lng_gen','std'),
    zero_rate=('lng_gen', lambda s:(s==0).mean()),
    n=('lng_gen','size')).reset_index(drop=True)
g.round(2).to_csv(TAB/'7b_02_netload_vs_gas_binned.csv', index=False)

fig, ax = plt.subplots(1, 2, figsize=(11, 4))
ax[0].scatter(df['net_load'], df['lng_gen'], s=2, alpha=0.05, color='gray')
ax[0].plot(g['net_load'], g['gas_mean'], '-o', color='crimson', ms=4, label='구간 평균')
ax[0].set_xlabel('net_load (MW)'); ax[0].set_ylabel('lng_gen (MW)')
ax[0].set_title(f'관계 (전체 r={r_all:.3f})'); ax[0].legend()
ax[1].plot(g['net_load'], g['zero_rate'], '-o', color='darkorange', ms=4)
ax[1].set_xlabel('net_load (MW)'); ax[1].set_ylabel('가스=0 비율')
ax[1].set_title('부하수준별 가스 꺼짐 비율')
plt.tight_layout(); plt.savefig(FIG/'7b_02_netload_vs_gas.png'); plt.show()
g.round(2)
""")
md("""**읽는 법**: 구간 평균선이 우상향하면 net_load↑ → 가스↑ (명제 직접 증거).
저부하 평탄→고부하 급증이면 **부하수준별 비선형**(merit-order). 트리/구간 모델 유리 신호.""")

md("## 3. 시계열 구조 — 주기성과 연도 추세")
code("""prof_hour = df.groupby('hour')['lng_gen'].mean()
prof_dow  = df.groupby('dow')['lng_gen'].mean()
prof_month= df.groupby('month')['lng_gen'].mean()

fig, ax = plt.subplots(1, 3, figsize=(13, 3.4))
prof_hour.plot(ax=ax[0], marker='o', ms=3); ax[0].set_title('시간대별 평균 가스'); ax[0].set_xlabel('hour')
prof_dow.plot(ax=ax[1], marker='o', ms=3); ax[1].set_title('요일별(0=월)'); ax[1].set_xlabel('dow')
prof_month.plot(ax=ax[2], marker='o', ms=3); ax[2].set_title('월별'); ax[2].set_xlabel('month')
for a in ax: a.set_ylabel('MW')
plt.tight_layout(); plt.savefig(FIG/'7b_03_seasonality.png'); plt.show()

ms = df.set_index('timestamp')['lng_gen'].resample('MS').mean()
fig, ax = plt.subplots(figsize=(11, 3))
ms.plot(ax=ax, color='teal'); ax.set_title('월평균 lng_gen 추이 (2020–2024)'); ax.set_ylabel('MW')
ax.axvline(pd.Timestamp('2024-06-01'), color='crimson', ls='--', lw=1, label='시범사업 시작(2024-06)')
ax.legend()
plt.tight_layout(); plt.savefig(FIG/'7b_03_monthly_trend.png'); plt.show()
""")
md("""**읽는 법**: 시간대 패턴(태양광 시간 가스 저하 등)·월 패턴 → 달력 피처 유효. 월평균 추세의 계단/꺾임은 레짐 신호(6번과 연결).""")

md("## 4. 시간적 안정성 — 같은 net_load의 가스 발전이 연도별로 표류하나 (★)")
code("""bins = np.linspace(df['net_load'].quantile(.01), df['net_load'].quantile(.99), 21)
df['nl_fix'] = pd.cut(df['net_load'], bins)
piv = df.groupby(['year','nl_fix'], observed=True)['lng_gen'].mean().unstack('year')
centers = [iv.mid for iv in piv.index]

fig, ax = plt.subplots(figsize=(9, 5))
for y in piv.columns:
    ax.plot(centers, piv[y].values, marker='o', ms=3, label=str(y))
ax.set_xlabel('net_load (MW, 고정 구간)'); ax.set_ylabel('평균 lng_gen (MW)')
ax.set_title('연도별 net_load → 가스 곡선 (겹치면 안정 / 벌어지면 표류)')
ax.legend(title='year')
plt.tight_layout(); plt.savefig(FIG/'7b_04_yearly_stability.png'); plt.show()

yr = df.groupby('year').agg(n=('lng_gen','size'), lng_mean=('lng_gen','mean'),
        zero_pct=('lng_gen', lambda s:(s==0).mean()*100),
        nl_mean=('net_load','mean'),
        corr=('lng_gen', lambda s: s.corr(df.loc[s.index,'net_load']))).round(2)
yr.to_csv(TAB/'7b_04_yearly.csv')
piv.round(0)
""")
md("""**읽는 법**: 연도 곡선이 거의 겹치면 f(net_load)→가스가 **안정**(좋음, 정직한 검증 가능).
한 방향으로 벌어지면 석탄·신재생 증감으로 가스 급전순위가 **표류** → year/레짐 피처 필요.""")

md("""## 5. ★ 신재생 → 가스 대체효과 (명제의 심장) — 제주는 강하다
명제(§1.2 검증목표 1): 신재생↑ → 가스↓. net_load는 (수요−신재생)이라 신재생의 음효과가 숨는다.
**수요를 통제**하고 `real_renew_gen_jeju`(태양광+풍력) ↔ 가스 관계를 직접 본다.
전국(7-0 5-b)에선 침투율이 낮아 약했다. 제주는 침투율이 높아 **계량 신재생만으로 직접 강해야** 한다.""")
code("""d2 = df.dropna(subset=['real_renew_gen_jeju','real_demand_jeju','net_load','lng_gen']).copy()
print('신재생 평균 %.0fMW (수요의 %.1f%%), 최대 %.0fMW' % (
    d2.real_renew_gen_jeju.mean(), 100*d2.real_renew_gen_jeju.mean()/d2.real_demand_jeju.mean(),
    d2.real_renew_gen_jeju.max()))
print('원상관 corr(신재생,가스)=%+.3f | corr(수요,가스)=%+.3f | corr(net_load,가스)=%+.3f' % (
    np.corrcoef(d2.real_renew_gen_jeju,d2.lng_gen)[0,1],
    np.corrcoef(d2.real_demand_jeju,d2.lng_gen)[0,1],
    np.corrcoef(d2.net_load,d2.lng_gen)[0,1]))

# 수요 통제: 수요 10분위 안에서 부분상관
d2['dem_dec'] = pd.qcut(d2.real_demand_jeju,10,labels=False)
pc = d2.groupby('dem_dec', group_keys=False).apply(
        lambda g: np.corrcoef(g.real_renew_gen_jeju,g.lng_gen)[0,1], include_groups=False)
print('수요분위별 부분상관 corr(신재생,가스):', [round(v,2) for v in pc.values], '| 평균 %+.3f'%pc.mean())

# 회귀계수 (가스 ~ 수요 + 신재생)
import numpy.linalg as la
X=np.column_stack([np.ones(len(d2)),d2.real_demand_jeju,d2.real_renew_gen_jeju])
beta=la.lstsq(X,d2.lng_gen.values,rcond=None)[0]
print('회귀 gas ~ 수요+신재생: 수요계수 %+.3f, 신재생계수 %+.3f (수요고정 시 신재생 +100MW => 가스 %+.1fMW)'
      % (beta[1],beta[2],beta[2]*100))
# 태양광/풍력 분리 회귀
Xs=np.column_stack([np.ones(len(d2)),d2.real_demand_jeju,d2.real_solar_gen_jeju,d2.real_wind_gen_jeju])
bs=la.lstsq(Xs,d2.lng_gen.values,rcond=None)[0]
print('  분리: 태양광계수 %+.3f, 풍력계수 %+.3f' % (bs[2],bs[3]))
pd.DataFrame({'metric':['신재생계수(수요통제)','태양광계수','풍력계수','수요분위 부분상관 평균','원상관'],
             'value':[beta[2],bs[2],bs[3],pc.mean(),np.corrcoef(d2.real_renew_gen_jeju,d2.lng_gen)[0,1]]}
            ).round(3).to_csv(TAB/'7b_05_displacement_reg.csv', index=False)
""")
code("""# 수요대(저/중/고)별 신재생 vs 가스 — 음의 기울기면 대체효과
fig, ax = plt.subplots(1,3, figsize=(13,3.6), sharey=True)
edges = d2.real_demand_jeju.quantile([0,.33,.66,1.0]).values
labels=['저수요','중수요','고수요']
slopes=[]
for i,(lo,hi) in enumerate(zip(edges[:-1],edges[1:])):
    s=d2[(d2.real_demand_jeju>=lo)&(d2.real_demand_jeju<hi)]
    ax[i].scatter(s.real_renew_gen_jeju,s.lng_gen,s=3,alpha=0.08,color='gray')
    b=np.polyfit(s.real_renew_gen_jeju,s.lng_gen,1); slopes.append(b[0])
    xs=np.linspace(s.real_renew_gen_jeju.min(),s.real_renew_gen_jeju.max(),50)
    ax[i].plot(xs,np.polyval(b,xs),'crimson',lw=2)
    ax[i].set_title(f'{labels[i]} (기울기 {b[0]:+.2f})'); ax[i].set_xlabel('신재생 MW')
ax[0].set_ylabel('가스 MW')
plt.tight_layout(); plt.savefig(FIG/'7b_05_renew_displacement.png'); plt.show()
print('수요대별 기울기:', [round(s,3) for s in slopes])
""")
md("""**읽는 법**: 수요대 안에서 기울기가 뚜렷한 음(−)이면 신재생이 가스를 직접 밀어낸다.
**대비 포인트**: 전국 7-0은 신재생계수 ≈ 0(원상관 +0.01, 자가소비 숨음). 제주는 계량 신재생만으로 음(−)이 직접 보여야 명제가 산다.
모델 단계에서 "전국 −0.33(역추정 필요) vs 제주 −0.??(계량 직접)"로 정리한다.""")

md("""## 6. ★ 2024-06 제주 전력거래 시범사업 레짐 점검
2024-06 시범사업(실시간 시장) 시작. **급전순위 자체는 전/후 동일**할 전망이라 `net_load→가스` 함수가 크게 바뀌진 않을 것이다.
그래도 안전하게 **전/후 곡선을 겹쳐 함수 표류를 확인**하고, 라벨을 남긴다(G-9 함수표류 점검 항목).
(참고: 제주 시범사업으로 상당량 PPA 용량이 Grid 계량에 흡수됨 → 계량 신재생만으로 충분. 별도 PPA 산정 불필요. 육지는 미흡수라 PPA 산정 포함이 필수.)""")
code("""REG = pd.Timestamp('2024-06-01')
df['regime'] = np.where(df['timestamp'] >= REG, 'post(시범사업)', 'pre')
# 전/후 net_load->가스 곡선 (공통 구간 binning)
b2 = np.linspace(df['net_load'].quantile(.02), df['net_load'].quantile(.98), 16)
df['nl_b2'] = pd.cut(df['net_load'], b2)
cur = df.groupby(['regime','nl_b2'], observed=True)['lng_gen'].mean().unstack('regime')
ctr = [iv.mid for iv in cur.index]

fig, ax = plt.subplots(1,2, figsize=(12,4))
for col,c in [('pre','steelblue'),('post(시범사업)','crimson')]:
    if col in cur: ax[0].plot(ctr, cur[col].values, '-o', ms=3, color=c, label=col)
ax[0].set_xlabel('net_load (MW)'); ax[0].set_ylabel('평균 lng_gen (MW)')
ax[0].set_title('시범사업 전/후 net_load→가스 (겹치면 표류 없음)'); ax[0].legend()
# net_load 분포 전/후
for col,c in [('pre','steelblue'),('post(시범사업)','crimson')]:
    ax[1].hist(df.loc[df.regime==col,'net_load'], bins=40, density=True, alpha=0.5, color=c, label=col)
ax[1].set_xlabel('net_load (MW)'); ax[1].set_ylabel('density'); ax[1].set_title('전/후 net_load 분포'); ax[1].legend()
plt.tight_layout(); plt.savefig(FIG/'7b_06_regime_pilot.png'); plt.show()

# 전/후 같은 net_load 구간에서 가스 평균차(겹치는 구간만)
both = cur.dropna()
gap = (both['post(시범사업)'] - both['pre']).abs().mean() if 'post(시범사업)' in both else np.nan
print('post 기간 행수:', int((df.regime=='post(시범사업)').sum()), '(2024-06~12)')
print('겹치는 net_load 구간 평균 |가스차|: %.1f MW' % gap)
for col in ['pre','post(시범사업)']:
    sub=df[df.regime==col]
    print(f'  {col}: n={len(sub)} net_load평균 {sub.net_load.mean():.0f} 가스평균 {sub.lng_gen.mean():.1f} corr {sub.net_load.corr(sub.lng_gen):.3f}')
cur.round(1).to_csv(TAB/'7b_06_regime.csv')
""")
md("""**읽는 법**: 두 곡선이 겹치면 시범사업 전후 함수 표류 없음 → 2020–2024 통합 학습 안전.
크게 벌어지면 regime 피처 또는 학습창 조정 필요. (post는 2024-06~12 6개월로 표본이 작아 추세만 참고.)""")

md("## 7. train ↔ test 입력 분포 겹침 — 외삽 위험 (★)")
code("""# 측정구간(2020-2024) 시간순 분할 가정: train 2020-2022 / val 2023 / test 2024
def yr_split(y):
    if y <= 2022: return 'train'
    if y == 2023: return 'val'
    return 'test'   # 2024
df['eda_split'] = df['year'].map(yr_split)
spl = {s: df.loc[df.eda_split==s,'net_load'].dropna() for s in ['train','val','test']}

fig, ax = plt.subplots(figsize=(9, 4))
for s,c in [('train','steelblue'),('val','orange'),('test','crimson')]:
    ax.hist(spl[s], bins=50, density=True, alpha=0.5, label=f'{s} (n={len(spl[s])})', color=c)
ax.set_xlabel('net_load (MW)'); ax.set_ylabel('density'); ax.set_title('split별 net_load 분포 (제주, 연도 기준)')
ax.legend(); plt.tight_layout(); plt.savefig(FIG/'7b_07_split_distribution.png'); plt.show()

tr_lo, tr_hi = spl['train'].min(), spl['train'].max()
te = spl['test']
out = ((te < tr_lo) | (te > tr_hi)).mean()
summ = pd.DataFrame({s:[v.min(),v.quantile(.25),v.median(),v.quantile(.75),v.max(),v.mean()]
                     for s,v in spl.items()},
                    index=['min','q25','median','q75','max','mean']).round(0)
summ.to_csv(TAB/'7b_07_split_netload_summary.csv')
print('train(2020-22) net_load 범위:', round(tr_lo), '~', round(tr_hi))
print(f'train 범위를 벗어난 test(2024) 비율(외삽): {out:.1%}')
summ
""")
md("""**읽는 법**: test(2024)가 train 범위를 크게 벗어나면 외삽 → 검증 신뢰 저하.
분할안은 EDA용 가정이며, 최종 학습창은 모델 단계에서 사용자와 확정한다.""")

md("""## 8. 요약 & 다음 단계 (실측 수치)

**관계는 강하고 안정적, 대체효과는 제주에서 직접 뚜렷 — 명제(검증목표 1)는 제주 데이터에 실제로 있다.**

| 항목 | 결과 | 판정 |
|---|---|---|
| net_load↔가스 상관(2020–24 실측) | **r = 0.723** | 강함. net_load↑→가스↑ 직접 증거 |
| 관계 형태 | 우상향·부하수준별 비선형 | 트리/구간 모델 유리 |
| 타깃 0 비중 | **1.3%** (거의 항상 켜짐) | 영 과다 아님 |
| 시계열 | 시·요일·월 주기성 뚜렷 | 달력 피처 유효 |
| 시간적 안정성 | 연도 곡선 겹침(연 corr 0.72–0.78) | 안정. 표류 없음 |
| **★ 신재생 대체효과** | 원상관 **−0.415**, 수요통제 부분상관 **−0.525**, 회귀 신재생계수 **−0.369**(+100MW→가스 −37MW), 태양광 −0.368·풍력 −0.368 | **제주는 강함** ↔ 전국 ≈0(역추정 −0.33 필요) |
| **★ 시범사업(2024-06) 레짐** | 전/후 corr 0.702→0.832(유지·강화), 겹침구간 가스차 27.8MW(2024 수준상승 혼입) | 구조적 단절 없음. 라벨만 유지 |
| train↔test net_load 겹침 | 외삽 **0.7%**, 평균 train560/val597/test599 | 안전 |

**G-9(제주) 판정 — 통과.** 관계·시계열·안정성·**대체효과(제주의 핵심 증거)**·분포 겹침 모두 양호. 시범사업 레짐 표류 없음(라벨만 보존). 데이터 결손(전국 G-10 같은) 없음 — `only_gen` 실측 2020–2024가 깨끗하다.

**★ 대비 핵심**: 전국(7-0)은 신재생계수 ≈0 → 역추정(7-0b, −0.33)으로 겨우 보였다. 제주는 **계량 신재생만으로 −0.369가 직접** 나온다. §1.2가 "신재생 많은 제주에서 입증"이라 설계한 이유가 데이터로 확인됐다.

**그 다음(§0.6 규율)**: G-9 통과 → **모델 최종 입력 피처를 사용자에게 묻고 확정**(후보: 수요 + 계량 신재생[태양광·풍력 분리 vs 합계] + 달력 + 기온3 + 레짐 라벨 사용 여부) → 7-B 모델 학습 + **net_load별 LNG 추정** + "전국 −0.33 vs 제주 −0.37" 대비표.
""")

nb['cells'] = cells
nbf.write(nb, '7-B_jeju_probe_eda.ipynb')
print('wrote 7-B_jeju_probe_eda.ipynb with', len(cells), 'cells')

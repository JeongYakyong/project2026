# -*- coding: utf-8 -*-
"""7 baseline — 발전용 가스수요(gen_gas_kr) Prophet 가벼운 베이스라인 notebook 빌더.

설계(사용자 요청):
- 데이터: input_data_land.db `historical`, 타깃 gen_gas_kr(시간단위). G-10: 2022-01부터 로드.
- 분할(7-A 동일): train 2022-24 / val 2025 / test 2026(1~6월 부분구간).
- univariate. add_regressor 미사용(net_load 제외가 이번 결정의 핵심).
- Prophet 격자: yearly on/off × 계절성 가법/승법 × 휴일 없음/한국공휴일 = 8개.
- seasonal naive(lag168) = 같은 요일·시각 1주 전 값. 바닥 베이스라인으로 병기.
"""
import nbformat as nbf

nb = nbf.v4.new_notebook(); cells = []
def md(t): cells.append(nbf.v4.new_markdown_cell(t))
def code(t): cells.append(nbf.v4.new_code_cell(t))

md("""# 7 baseline — 발전용 가스수요 Prophet 가벼운 베이스라인

> 목적: `7. land_gas_forecaster`의 **가벼운 시간기반 베이스라인**. 외생변수(net_load 등)를 전혀 쓰지 않고
> 순수 시간 패턴(일·주·연 계절성)만으로 `gen_gas_kr`을 어디까지 설명하는지 본다. 본 모델(7-A LGBM, test MAPE 11.4%)과 대비되는 하한선.

**핵심 결정**: `add_regressor`를 쓰지 않는다 — net_load 제외가 이번 베이스라인의 정의다. (외생변수를 넣는 순간 베이스라인이 아니라 또 하나의 본 모델이 된다.)

## 데이터·학습창
- `input_data_land.db` `historical`, 타깃 `gen_gas_kr`(시간단위).
- **G-10**: 2020–2021은 실측이 아니라 결측을 0으로 채운 값 → **2022-01부터 로드**.
- 분할(7-A 동일): **train 2022–24 / val 2025 / test 2026**. test 2026은 1~6월 부분구간(~3,700행)이라 MAPE 해석 시 감안.
- 시간 인덱스 연속성은 A0에서 0(구멍 없음)으로 확인됨. Prophet 입력은 `ds`(tz-naive) / `y`.

## 모델 구성
1. **seasonal naive (lag168)** — `ŷ(t)=y(t-168)`. 같은 요일·시각 1주 전 실측. 최근 실측을 그대로 쓰는 바닥선.
2. **Prophet ×8** — daily·weekly 계절성 켬 + 격자:
   - yearly 계절성 **on/off** (2022~ 길이상 연주기 효과가 약할 수 있어 둘 다 확인)
   - 계절성 **가법(additive) vs 승법(multiplicative)** (가스 수요는 수준에 따라 진폭이 변할 수 있음)
   - 휴일 **없음 vs 한국 공휴일(KR)** — `day_type`은 외생변수가 아니라 달력 파생이라 시간 패턴에 넣어도 됨. 다만 "순수 시간만"의 경계를 분명히 하려고 **별도 variant로 분리**.

> 평가 방식: Prophet은 train(2022–24)으로 한 번 적합한 뒤 2025–26 전체를 외삽 예측(순수 시간 외삽력 측정). seasonal naive는 1주 전 실측을 쓰므로 정보 조건이 다르다 — 둘은 다른 정보량의 하한선이며, 그 대비 자체가 정보가 된다(아래 결론 참조).
""")

code("""import warnings, logging, os, glob
warnings.filterwarnings('ignore')
logging.getLogger('cmdstanpy').setLevel(logging.ERROR)
logging.getLogger('prophet').setLevel(logging.ERROR)

# Windows 한글(cp949) 로캘 우회: cmdstanpy가 where.exe의 한글 출력을 utf-8로 디코딩하다 죽는 문제.
# 번들 tbb.dll 폴더를 PATH에 미리 올려 where.exe가 곧장 성공하게 만든다(Prophet() 생성 전에 실행돼야 함).
import prophet as _pp
_tbb = glob.glob(os.path.join(os.path.dirname(_pp.__file__),
                              'stan_model', 'cmdstan-*', 'stan', 'lib', 'stan_math', 'lib', 'tbb'))
if _tbb:
    os.environ['PATH'] = _tbb[0] + os.pathsep + os.environ.get('PATH', '')

import sqlite3
import pandas as pd, numpy as np
import matplotlib.pyplot as plt, matplotlib as mpl
from pathlib import Path
from prophet import Prophet
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score

mpl.rcParams['figure.dpi']=110; mpl.rcParams['axes.grid']=True; mpl.rcParams['font.size']=10
mpl.rcParams['font.family']='Malgun Gothic'; mpl.rcParams['axes.unicode_minus']=False
FIG=Path('fig'); FIG.mkdir(exist_ok=True); TAB=Path('tab'); TAB.mkdir(exist_ok=True)
DB=Path('../../1. data_fetcher_and_db/data/input_data_land.db')
print('DB exists:', DB.exists())
""")

md("## 1. 데이터 적재 — historical, 2022-01부터(G-10), ds/y 포맷")
code("""con=sqlite3.connect(DB)
raw=pd.read_sql('SELECT timestamp, gen_gas_kr FROM historical ORDER BY timestamp', con, parse_dates=['timestamp'])
con.close()
print('원본 행수:', len(raw), '| 기간', raw.timestamp.min(), '->', raw.timestamp.max())

# G-10: 2020-2021은 결측-0 → 제외
df=raw[raw.timestamp>='2022-01-01'].copy()
n_before=len(df)
df=df.dropna(subset=['gen_gas_kr'])           # test 2026 말미 미수집 14행 등 제거
print(f'2022+ 적재 {n_before}행 → 결측 제거 후 {len(df)}행 (NaN {n_before-len(df)}개 drop)')

df=df.rename(columns={'timestamp':'ds','gen_gas_kr':'y'}).reset_index(drop=True)
df['ds']=pd.to_datetime(df['ds']).dt.tz_localize(None)   # tz-naive 보장

# 시간 연속성 점검(구멍 = 1시간 간격이 아닌 곳)
gaps=df['ds'].diff().dropna()
n_gap=(gaps!=pd.Timedelta(hours=1)).sum()
print('1시간 간격이 아닌 지점 수(구멍/중복):', int(n_gap))

def split(a,b):
    m=(df['ds']>=a)&(df['ds']<b); return df[m].copy()
tr=split('2022-01-01','2025-01-01'); va=split('2025-01-01','2026-01-01'); te=split('2026-01-01','2027-01-01')
print(f'train {len(tr)} | val {len(va)} | test {len(te)}')
print('test 기간', te.ds.min(),'->',te.ds.max())
""")

md("## 2. 평가지표\n`MAPE`는 1차 지표(가스 최솟값 ≈4,800MW로 분모 안정). R²는 시간외삽 설명력.")
code("""def metrics(y,p):
    y=np.asarray(y,float); p=np.asarray(p,float)
    return dict(MAE=mean_absolute_error(y,p),
                RMSE=mean_squared_error(y,p)**0.5,
                MAPE=np.mean(np.abs((y-p)/y))*100,
                R2=r2_score(y,p))

def eval_on(pred_df, name):
    \"\"\"pred_df: ds,yhat 전체. val/test로 잘라 실측과 ds 기준 병합 후 지표.\"\"\"
    out={}
    for sp,frame in [('val',va),('test',te)]:
        mrg=frame[['ds','y']].merge(pred_df[['ds','yhat']], on='ds', how='inner').dropna()
        out[(name,sp)]=metrics(mrg['y'], mrg['yhat'])
    return out
""")

md("""## 3. seasonal naive (lag168) — 바닥 베이스라인
`ŷ(t)=y(t-168)`. 전체 2022+ 연속 시계열에서 168시간(7일) 시프트. val 초반 일부는 train 말미 실측을 참조한다.""")
code("""naive=df[['ds','y']].copy()
naive['yhat']=naive['y'].shift(168)          # 연속 시계열 기준 1주 전 값
m_naive=eval_on(naive[['ds','yhat']].assign(yhat=naive['yhat']), 'seasonal_naive(lag168)')
print({k:{kk:round(vv,2) for kk,vv in v.items()} for k,v in m_naive.items()})
""")

md("""## 4. Prophet ×8 — 시간 패턴만
train(2022–24)으로 적합 → 2025–26 전체 외삽 예측. `uncertainty_samples=0`(구간추정 생략)으로 가볍게.""")
code("""def run_prophet(yearly, mode, holidays):
    m=Prophet(growth='linear',
              yearly_seasonality=yearly,
              weekly_seasonality=True,
              daily_seasonality=True,
              seasonality_mode=mode,
              uncertainty_samples=0)
    if holidays:
        m.add_country_holidays(country_name='KR')
    m.fit(tr[['ds','y']])
    future=df[['ds']].copy()                  # 실측이 있는 전체 ds에 대해 예측
    fc=m.predict(future)
    return fc[['ds','yhat']]

grid=[]
for yearly in [False, True]:
    for mode in ['additive','multiplicative']:
        for hol in [False, True]:
            grid.append((yearly,mode,hol))

def label(yearly,mode,hol):
    return f"Prophet[{'mult' if mode=='multiplicative' else 'add'}|yr_{'on' if yearly else 'off'}|{'KR휴일' if hol else 'no휴일'}]"

all_metrics={}; preds={}
for yearly,mode,hol in grid:
    name=label(yearly,mode,hol)
    fc=run_prophet(yearly,mode,hol)
    preds[name]=fc
    all_metrics.update(eval_on(fc, name))
    mt=all_metrics[(name,'test')]
    print(f"{name:42s} test MAPE {mt['MAPE']:5.2f}%  R2 {mt['R2']:+.3f}")
""")

md("## 5. 결과표 — 9개 모델 × (val·test)")
code("""rows=[]
src={**m_naive, **all_metrics}
for (name,sp),v in src.items():
    rows.append(dict(model=name, split=sp, **{k:round(val,2) for k,val in v.items()}))
res=pd.DataFrame(rows)
res=res.sort_values(['split','MAPE']).reset_index(drop=True)
res.to_csv(TAB/'metrics.csv', index=False, encoding='utf-8-sig')
# 보기 좋은 피벗(MAPE 중심)
pv=res.pivot(index='model', columns='split', values='MAPE').rename(columns=lambda c:f'MAPE_{c}')
pv=pv.sort_values('MAPE_test')
print(pv.round(2).to_string())
print('\\n저장: tab/metrics.csv')
res
""")

code("""# 최고 Prophet variant(test MAPE 최소)와 naive 식별
prophet_rows=res[(res.split=='test') & (res.model.str.startswith('Prophet'))]
best_name=prophet_rows.sort_values('MAPE').iloc[0]['model']
best_test=all_metrics[(best_name,'test')]; best_val=all_metrics[(best_name,'val')]
naive_test=m_naive[('seasonal_naive(lag168)','test')]
print('best Prophet :', best_name)
print('  val :', {k:round(v,2) for k,v in best_val.items()})
print('  test:', {k:round(v,2) for k,v in best_test.items()})
print('naive  test :', {k:round(v,2) for k,v in naive_test.items()})
""")

md("## 6. 그림 — test 2026 월별 예측 vs 실측 (best Prophet · seasonal naive)")
code("""import matplotlib.dates as mdates
best_fc=preds[best_name].merge(te[['ds','y']], on='ds', how='inner')
naive_te=naive[['ds','yhat']].merge(te[['ds','y']], on='ds', how='inner').dropna()

months=['2026-01','2026-02','2026-03','2026-04','2026-05']        # 26년 월별(1~5월)
ymin=min(best_fc['y'].min(), best_fc['yhat'].min(), naive_te['yhat'].min())*0.95
ymax=max(best_fc['y'].max(), best_fc['yhat'].max(), naive_te['yhat'].max())*1.02

fig,axes=plt.subplots(len(months),1,figsize=(13,1.9*len(months)))
for ax,ml in zip(axes,months):
    s=pd.Timestamp(ml+'-01'); e=s+pd.offsets.MonthBegin(1)
    bf=best_fc[(best_fc.ds>=s)&(best_fc.ds<e)]; nv=naive_te[(naive_te.ds>=s)&(naive_te.ds<e)]
    ax.plot(bf['ds'],bf['y'],   color='black',    lw=0.8, label='실측')
    ax.plot(bf['ds'],bf['yhat'],color='crimson',  lw=0.9, alpha=0.85, label=best_name)
    ax.plot(nv['ds'],nv['yhat'],color='steelblue',lw=0.7, alpha=0.6,  label='naive(lag168)')
    ax.set_xlim(s,e); ax.set_ylim(ymin,ymax); ax.set_ylabel('MW')
    ax.set_title(ml, loc='left', fontsize=10, fontweight='bold')
    ax.xaxis.set_major_locator(mdates.DayLocator(interval=2))
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%d'))
    ax.grid(alpha=0.3)
axes[0].legend(loc='upper right', ncol=3, fontsize=8, framealpha=0.9)
fig.suptitle('test 2026 가스 발전 — 월별 베이스라인 예측 vs 실측', y=0.998, fontsize=13, fontweight='bold')
plt.tight_layout(rect=(0,0,1,0.985)); plt.savefig(FIG/'baseline_test_timeseries.png'); plt.show()
""")

code("""# 한 주(요일·시각 패턴) 확대 — 6월 첫 주
wk=best_fc[(best_fc.ds>='2026-06-01')&(best_fc.ds<'2026-06-08')]
wn=naive_te[(naive_te.ds>='2026-06-01')&(naive_te.ds<'2026-06-08')]
fig,ax=plt.subplots(figsize=(13,3.4))
ax.plot(wk['ds'], wk['y'], color='black', lw=1.2, label='실측')
ax.plot(wk['ds'], wk['yhat'], color='crimson', lw=1.2, label=best_name)
ax.plot(wn['ds'], wn['yhat'], color='steelblue', lw=1.0, alpha=0.7, label='naive(lag168)')
ax.set_title('한 주 확대 (2026-06-01~07) — 일·주 패턴 재현'); ax.set_ylabel('MW'); ax.legend(fontsize=8)
plt.tight_layout(); plt.savefig(FIG/'baseline_week_zoom.png'); plt.show()
""")

md("""## 7. 그림 — 핵심 3개 비교 (MAPE)
전체 8개 격자 대신 **핵심만**: 바닥선(lag168) vs Prophet(연주기·공휴일 켠 상태에서 계절진폭 일정 vs 변동).
가법/승법은 직관적 표현 `계절진폭 = 일정 / 변동`으로 바꿔 표기.""")
code("""KEEP = ['seasonal_naive(lag168)', 'Prophet[add|yr_on|KR휴일]', 'Prophet[mult|yr_on|KR휴일]']

def pretty(name):
    if name.startswith('seasonal_naive'):
        return 'seasonal naive (lag168)\\n1주 전 같은 시각 실측 그대로'
    mode, yr, hol = name[name.find('[')+1:name.find(']')].split('|')
    amp = '계절진폭 = 변동' if mode=='mult' else '계절진폭 = 일정'
    return f'Prophet · 연주기 O · 공휴일 O\\n{amp}'

sub=res[res.model.isin(KEEP)].copy()
sub['label']=sub['model'].map(pretty)
order=sub[sub.split=='test'].sort_values('MAPE')['label'].tolist()
piv=sub.pivot(index='label', columns='split', values='MAPE').reindex(order)

fig,ax=plt.subplots(figsize=(11,4.4))
piv[['val','test']].plot.barh(ax=ax, color=['#9ecae1','#fc9272'], width=0.62)
ax.invert_yaxis(); ax.set_xlabel('MAPE (%) — 낮을수록 정확'); ax.set_ylabel('')
ax.set_title('베이스라인 핵심 비교 — 단순반복 vs Prophet(계절진폭 일정/변동)', fontsize=12.5, fontweight='bold', pad=12)
ax.legend(title='구간', labels=['val 2025','test 2026'], loc='upper right')
ax.set_xlim(0, piv.values.max()*1.15)
for c in ax.containers:
    ax.bar_label(c, fmt='%.1f', fontsize=9.5, padding=3)
ax.grid(axis='x', alpha=0.3)
plt.tight_layout(); plt.savefig(FIG/'baseline_mape_bars.png'); plt.show()
""")

md("""## 8. 요약
- **seasonal naive(lag168)** = 최근 실측(1주 전)을 그대로 쓰는 바닥선. 본 베이스라인 비교의 기준점.
- **Prophet(시간 외삽)** = 외생변수 없이 일·주(·연) 패턴만으로 예측. train 이후를 순수 외삽한 값이라 지평이 길수록 불리.
- 본 모델(7-A LGBM, test MAPE 11.4% / R² 0.78)과의 격차 = **net_load(수요+신재생) 정보가 기여하는 몫**. 베이스라인이 이 격차의 하한을 정량화한다.
- 상세 수치·결론은 `REPORT_baseline.md` 참조.
""")

nb['cells']=cells
nb['metadata']={'kernelspec':{'display_name':'Python 3','language':'python','name':'python3'},
                'language_info':{'name':'python'}}
import pathlib
out=pathlib.Path('baseline_prophet.ipynb')
nbf.write(nb, str(out))
print('wrote', out)

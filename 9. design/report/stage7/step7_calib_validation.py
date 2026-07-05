# -*- coding: utf-8 -*-
"""7단계 · 저수요(밤) 보정 후보 정직 검증 (집 양식).
시간분할(train<6/29, test 6/29~7/5)로 4개 보정을 비교. 핵심 메시지:
  정적 단일식은 드리프트를 못 따라가고(조금만 개선), '시간대모양×최근레벨' 적응보정이 크게 이긴다.
실행: python step7_calib_validation.py
"""
import os, sqlite3
import numpy as np, pandas as pd
import matplotlib as mpl, matplotlib.pyplot as plt

HERE=os.path.dirname(os.path.abspath(__file__)); ROOT=os.path.normpath(os.path.join(HERE,'..','..','..'))
DB=os.path.join(ROOT,'1. data_fetcher_and_db','temp_DB','input_data_land_check.db')
INK,MUTED,RULE='#2d3142','#4f5d75','#d9dce3'
C_C0,C_STAT,C_ADAPT='#c47a7a','#9aa0ac','#eb6c36'

mpl.rcParams.update({'font.family':'Malgun Gothic','axes.unicode_minus':False,'figure.facecolor':'white',
    'axes.facecolor':'white','savefig.facecolor':'white','axes.edgecolor':MUTED,'axes.labelcolor':INK,
    'text.color':INK,'xtick.color':MUTED,'ytick.color':MUTED,'figure.dpi':150})
def clean(ax):
    for s in ('top','right'): ax.spines[s].set_visible(False)
    for s in ('left','bottom'): ax.spines[s].set_color(RULE)
    ax.tick_params(length=0)
def _save(fig,p):
    for ax in fig.axes:
        for l in ax.get_xticklabels()+ax.get_yticklabels(): l.set_fontweight('bold')
    fig.savefig(p,bbox_inches='tight',dpi=150); plt.close(fig)

# ── 검증 재계산(validate_corr 와 동일 로직) ──
con=sqlite3.connect(DB)
h=pd.read_sql('SELECT timestamp, gen_gas_kr AS act FROM historical',con,parse_dates=['timestamp'])
e=pd.read_sql("SELECT timestamp,horizon_d,est_gas_gen_land AS praw FROM est_horizon_land "
              "WHERE timestamp>='2026-06-01' AND timestamp<'2026-07-06' AND horizon_d<=7",con,parse_dates=['timestamp'])
con.close()
m=e.merge(h,on='timestamp').dropna(); m['bias']=m.praw-m.act; m['hour']=m.timestamp.dt.hour; m['day']=m.timestamp.dt.normalize()
SPLIT=pd.Timestamp('2026-06-29'); tr=m[m.day<SPLIT]; te=m[m.day>=SPLIT]
def metrics(corr):
    err=(te.praw-corr)-te.act; return abs(err.mean()), err.abs().mean()
res={}
res['C0\n무보정(현행)']=metrics(0)
knots=np.array([9,11,13,15,17,19,21,24])*1000.0
bk=pd.Series([tr[(tr.praw>=k-1000)&(tr.praw<k+1000)].bias.mean() for k in knots],index=knots).interpolate().bfill().ffill()
res['C5\n예측가스 단일식']=metrics(np.interp(te.praw,knots,bk.values))
shape=tr.groupby('hour').bias.mean(); shape=shape-shape.mean()
d1=m[m.horizon_d==1].groupby('day').bias.mean().reindex(pd.date_range(m.day.min(),m.day.max()))
lvl_series=d1.shift(1).rolling(7,min_periods=3).mean()
lvl=(te.day-pd.to_timedelta(te.horizon_d,'D')).map(lvl_series).values
lvl=np.where(np.isfinite(lvl),lvl,tr.bias.mean())
c4=shape.reindex(te.hour).values+lvl
res['C4\n시간대모양×최근레벨']=metrics(c4)
labels=list(res); bias=[res[k][0] for k in labels]; mae=[res[k][1] for k in labels]
cols=[C_C0,C_STAT,C_ADAPT]

fig,(a1,a2)=plt.subplots(1,2,figsize=(10.6,4.4),gridspec_kw={'wspace':0.25})
x=np.arange(len(labels))
for ax,vals,ttl,ylab in [(a1,bias,'남은 편향 (절댓값, 작을수록 좋음)','편향 (MW)'),(a2,mae,'평균 오차 MAE (작을수록 좋음)','MAE (MW)')]:
    b=ax.bar(x,vals,color=cols,width=0.6,zorder=3)
    for xi,v in zip(x,vals): ax.text(xi,v+30,f'{v:,.0f}',ha='center',va='bottom',fontsize=10,fontweight='bold',color=INK)
    ax.set_title(ttl,fontsize=11.5,fontweight='bold',color=INK,pad=8)
    ax.set_ylabel(ylab,fontsize=10); ax.set_xticks(x); ax.set_xticklabels(labels,fontsize=9.2)
    ax.set_ylim(0,max(vals)*1.18); clean(ax)
fig.suptitle('저수요(밤) 보정 정직 검증 — 정적 단일식 vs 적응형  (held-out 6/29~7/5)',
             fontsize=12.5,fontweight='bold',color=INK,y=1.03,x=0.02,ha='left')
_save(fig,os.path.join(HERE,'step7_calib_validation.png'))
print('saved step7_calib_validation.png')
for k in labels: print(k.replace(chr(10),' '), '→ 편향 %.0f, MAE %.0f'%res[k])

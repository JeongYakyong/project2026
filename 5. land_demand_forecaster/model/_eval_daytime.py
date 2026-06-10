# -*- coding: utf-8 -*-
"""[가벼운 진단] 전국(land) 5-A 낮시간(08~16h) 정확도 vs KPX + 과소/과대 편향 + 맑음/흐림.
제주 2-0c와 동일 진단을 land에 적용해 비대칭손실 필요 여부 판단. (모델 변경 없음, 읽기 전용)
"""
import os, sqlite3, sys
import numpy as np, pandas as pd, lightgbm as lgb
try: sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception: pass
HERE=os.path.dirname(os.path.abspath(__file__))
DB=os.path.normpath(os.path.join(HERE,'..','..','1. data_fetcher_and_db','data','input_data_land.db'))
ST=['daegwallyeong','wonju','seosan','pohang','yeonggwang']; WX=['temp_c','solar_rad','wind_spd']
pull=['timestamp','real_demand_land','land_est_demand_da','day_type']+[f'{w}_{s}' for s in ST for w in WX]
con=sqlite3.connect(DB)
raw=pd.read_sql(f"SELECT {', '.join(pull)} FROM historical",con,parse_dates=['timestamp']); con.close()
raw=raw.sort_values('timestamp').reset_index(drop=True)
for w in WX: raw[w]=raw[[f'{w}_{s}' for s in ST]].mean(axis=1)
raw=raw[['timestamp','real_demand_land','land_est_demand_da','day_type']+WX]
idx=pd.date_range(raw.timestamp.min(),raw.timestamp.max(),freq='h')
d=raw.set_index('timestamp').reindex(idx); d.index.name='timestamp'
d.loc[d.real_demand_land==0,'real_demand_land']=np.nan
d['real_demand_land']=d['real_demand_land'].interpolate(method='time')
for w in WX: d[w]=d[w].interpolate(method='time')
d['day_type']=d['day_type'].ffill().bfill()
dem=d.real_demand_land.values.astype(float); base=d.land_est_demand_da.values.astype(float)
temp=d.temp_c.values; solar=d.solar_rad.values; wind=d.wind_spd.values
hour=d.index.hour.values; dow=d.index.dayofweek.values; month=d.index.month.values; year=d.index.year.values
dtype_arr=d.day_type.values.astype(object); N=len(d)
rec24=pd.Series(dem).rolling(24,min_periods=24).mean().values; rec168=pd.Series(dem).rolling(168,min_periods=168).mean().values
H=np.arange(1,169); origins=np.where((hour==23)&(np.arange(N)>=167)&(np.arange(N)<=N-1-168))[0]
tgt=(origins[:,None]+H[None,:]).ravel(); hh=np.broadcast_to(H,(len(origins),168)).ravel()
def col(a): return a[tgt]
s=pd.DataFrame({'y':col(dem),'h':hh.astype(int),'lag168':dem[tgt-168],
 'lag24':np.where(hh<=24,dem[tgt-24],np.nan),'rec24':np.repeat(rec24[origins],168),'rec168':np.repeat(rec168[origins],168),
 'temp_c':col(temp),'solar_rad':col(solar),'wind_spd':col(wind),
 'hour':col(hour),'dow':col(dow),'month':col(month),'day_type':col(dtype_arr),
 'base':col(base),'tyear':col(year)})
s['hour_sin']=np.sin(2*np.pi*s.hour/24); s['hour_cos']=np.cos(2*np.pi*s.hour/24)
s['dow_sin']=np.sin(2*np.pi*s.dow/7); s['dow_cos']=np.cos(2*np.pi*s.dow/7)
s['month_sin']=np.sin(2*np.pi*s.month/12); s['month_cos']=np.cos(2*np.pi*s.month/12)
s=s[s.y.notna()&s.lag168.notna()].reset_index(drop=True)
s['day_type']=s['day_type'].astype('category')
FEAT=['h','lag168','lag24','rec24','rec168','temp_c','solar_rad','wind_spd','hour_sin','hour_cos','dow_sin','dow_cos','month_sin','month_cos','day_type']
m=lgb.Booster(model_file=os.path.join(HERE,'models','lgbm_land_demand_direct.txt'))
te=s[s.tyear==2026].copy(); te['pred']=m.predict(te[FEAT])
def mape(a,p):
    a=np.asarray(a,float);p=np.asarray(p,float);k=(a>0)&np.isfinite(a)&np.isfinite(p);return float(np.mean(np.abs(a[k]-p[k])/a[k])*100)
te['da']=((te.h-1)//24+1)
day=te[(te.hour>=8)&(te.hour<=16)].copy()
print('=== 전국(land) 5-A 진단 (test 2026, 완전기상) ===')
print('전시간  MAPE  모델 %.2f%% | KPX %.2f%%'%(mape(te.y,te.pred),mape(te.y,te.base)))
print('낮(08-16) MAPE  모델 %.2f%% | KPX %.2f%%'%(mape(day.y,day.pred),mape(day.y,day.base)))
print('낮 편향(pred-actual, MW)  모델 %+.0f | KPX %+.0f  (−=과소예측)'%((day.pred-day.y).mean(),(day.base-day.y).mean()))
day['sq']=pd.qcut(day.solar_rad,4,labels=False,duplicates='drop')
print('\n낮시간 맑음/흐림(일사 4분위) — 모델 vs KPX:')
for q,lab in [(0,'흐림(일사 하위25%)'),(3,'맑음(일사 상위25%)')]:
    g=day[day.sq==q]
    print('  %-16s 모델 MAPE %.2f%% (편향 %+.0fMW) | KPX %.2f%% (편향 %+.0fMW)'
          %(lab,mape(g.y,g.pred),(g.pred-g.y).mean(),mape(g.y,g.base),(g.base-g.y).mean()))
print('\n해석: 낮시간에 모델이 KPX보다 낮고 과소편향이 작으면 → 비대칭 불필요.')

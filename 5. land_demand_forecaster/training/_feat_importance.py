# -*- coding: utf-8 -*-
"""final 모델 순열 피처 중요도(perfect test 2026). 각 피처를 셔플 후 MAPE 악화량(ΔMAPE)으로 랭킹.
ΔMAPE 클수록 모델이 그 피처에 의존. lag_week·temp_c 의 실제 기여 확인용.
실행: python _feat_importance.py
"""
import os, sys, math, joblib
import numpy as np, pandas as pd, torch
from torch.utils.data import DataLoader
try: sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception: pass
import importlib.util
HERE=os.path.dirname(os.path.abspath(__file__))
def _imp(n,p): s=importlib.util.spec_from_file_location(n,p); m=importlib.util.module_from_spec(s); s.loader.exec_module(m); return m
ev=_imp('ev', os.path.join(HERE,'_eval_patchtst_local.py'))
PatchTST=ev.PatchTST_Demand_RevIN; DS=ev.DS
PKL=os.path.join(HERE,'landdemand_final'); CSV=os.path.join(HERE,'demand_raw_land.csv')
meta=joblib.load(os.path.join(PKL,'metadata_landdemand_final.pkl'))
HP=meta['HP']; TEMP_SEL=meta['TEMP_SEL']; SOLAR_SEL=meta['SOLAR_SEL']; WIND_SEL=meta['WIND_SEL']; VAL_END=meta['VAL_END']
BASE_FF=meta['base_future_features']
def weekly_k(off): return 168*math.ceil((off+24)/168)

def build_df():
    df=pd.read_csv(CSV); df['timestamp']=pd.to_datetime(df['timestamp']); df=df.set_index('timestamp').sort_index()
    idx=pd.date_range(df.index.min(),df.index.max(),freq='h'); df=df.reindex(idx)
    df['temp_c']=df[[f'temp_c_{s}' for s in TEMP_SEL]].mean(1)
    df['solar_rad']=df[[f'solar_rad_{s}' for s in SOLAR_SEL]].mean(1)
    df['wind_spd']=df[[f'wind_spd_{s}' for s in WIND_SEL]].mean(1)
    df['total_cloud']=df[[f'total_cloud_{s}' for s in SOLAR_SEL]].mean(1)
    df['midlow_cloud']=df[[f'midlow_cloud_{s}' for s in SOLAR_SEL]].mean(1)
    df.loc[df['real_demand_land']==0,'real_demand_land']=np.nan
    df['Demand']=df['real_demand_land'].interpolate('time').ffill().bfill()
    for c in ['temp_c','solar_rad','wind_spd','total_cloud','midlow_cloud','cap_btmppa']:
        df[c]=df[c].interpolate('time',limit=6).ffill().bfill()
    df['day_type']=df['day_type'].ffill().bfill()
    df['Hour_sin']=np.sin(2*np.pi*df.index.hour/24); df['Hour_cos']=np.cos(2*np.pi*df.index.hour/24)
    df['Doy_sin']=np.sin(2*np.pi*df.index.dayofyear/365); df['Doy_cos']=np.cos(2*np.pi*df.index.dayofyear/365)
    df['is_weekend']=(df['day_type']=='weekend').astype(float); df['is_holiday']=(df['day_type']=='holiday').astype(float)
    df['hour_int']=df.index.hour.astype(np.int64)
    return df

def mape(a,p):
    a,p=np.asarray(a,float),np.asarray(p,float); k=(a>0)&np.isfinite(a)&np.isfinite(p); return float(np.mean(np.abs(a[k]-p[k])/a[k])*100)

@torch.no_grad()
def predict(m, arr, hr, fidx, tidx, off):
    ld=DataLoader(DS(arr,hr,HP['seq_len'],24,fidx,tidx,off),batch_size=256); P,A=[],[]
    for b in ld: pr,_=m(b); P.append(pr.numpy()); A.append(b['future_y'].numpy())
    return np.clip(np.concatenate(P).ravel(),0,None), np.concatenate(A).ravel()

def run(df, hname, off, rng):
    k=weekly_k(off); df=df.copy(); df[f'lag_week_{off}']=df['Demand'].shift(k)
    cols=BASE_FF+[f'lag_week_{off}']; feats=cols+['Demand']
    sub=df.dropna(subset=[f'lag_week_{off}'])
    te=sub[sub.index>=VAL_END].copy()
    sc=joblib.load(os.path.join(PKL,f'{hname}_scaler.pkl')); te[cols]=sc.transform(te[cols])
    arr=te[feats].values.astype(np.float32); hr=te['hour_int'].values.astype(np.int64)
    fidx=[feats.index(c) for c in cols]; tidx=feats.index('Demand'); nf=len(fidx)+1
    m=PatchTST(nf,pred_len=24,**HP); m.load_state_dict(torch.load(os.path.join(PKL,f'best_patchtst_landdemand_{hname}.pth'),map_location='cpu')); m.eval()
    P0,A=predict(m,arr,hr,fidx,tidx,off); base=mape(A,P0)
    imp={}
    for j,c in zip(fidx,cols):
        a2=arr.copy(); a2[:,j]=rng.permutation(a2[:,j])
        P1,_=predict(m,a2,hr,fidx,tidx,off); imp[c]=mape(A,P1)-base
    return base, imp

def main():
    df=build_df(); rng=np.random.default_rng(0)
    targets=[('D1',0),('D7',144),('D15',336)]
    res={}
    for hn,off in targets:
        base,imp=run(df,hn,off,rng); res[hn]=(base,imp)
        print(f'[{hn}] lag{weekly_k(off)} baseline perfect MAPE={base:.3f}')
    cols=BASE_FF+['lag_week']
    print(f'\n순열 ΔMAPE (클수록 의존; perfect 기준)')
    print(f"{'feature':<14}"+''.join(f'{hn:>9}' for hn,_ in targets))
    # lag_week 키가 지평별로 lag_week_{off} 라 통일
    def get(imp,c):
        if c=='lag_week':
            for k in imp:
                if k.startswith('lag_week'): return imp[k]
        return imp.get(c,0.0)
    rows=sorted(cols, key=lambda c:-sum(get(res[hn][1],c) for hn,_ in targets))
    for c in rows:
        print(f'{c:<14}'+''.join(f'{get(res[hn][1],c):>9.3f}' for hn,_ in targets))

if __name__=='__main__': main()

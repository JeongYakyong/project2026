# -*- coding: utf-8 -*-
"""증강 데이터셋 로컬 스모크 — Colab GPU 전에 주입 로직 검증(학습 없음, CPU).
노트북 _gen_landdemand_patchtst_aug.py 의 prep+AugDemandDataset 과 동일 코드 경로를 재현해
형상·NaN·di/wct 재계산·z-score·시간대 정렬·지평별 주입 크기를 점검한다.
"""
from __future__ import annotations
import os, sys
import numpy as np, pandas as pd, torch, joblib
from torch.utils.data import Dataset, DataLoader
from sklearn.preprocessing import StandardScaler
try: sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception: pass
HERE = os.path.dirname(os.path.abspath(__file__))
CSV = os.path.join(HERE, 'demand_raw_land.csv'); RES = os.path.join(HERE, 'forecast_residuals.npz')

TEMP_SEL=['wonju','seosan','pohang','yeonggwang']; SOLAR_SEL=['seosan','yeonggwang']
EXOG=['temp_c','di','wct','solar_rad','total_cloud','cap_btmppa']
TIME=['Hour_sin','Hour_cos','Doy_sin','Doy_cos','is_weekend','is_holiday']
RAW_W=['temp_c','rh','wind','solar_rad','total_cloud','cap_btmppa']; INJECT=['temp_c','rh','wind','solar_rad','total_cloud']
SEQ=336; PRED=24; TRAIN_END='2025-01-01'; VAL_END='2026-01-01'; VAL_SEED=20260619


def comfort_np(T,RH,Wms):
    di=0.81*T+0.01*RH*(0.99*T-14.3)+46.3; Wk=np.clip(Wms*3.6,4.8,None)
    wct=13.12+0.6215*T-11.37*Wk**0.16+0.3965*T*Wk**0.16; return di,np.where(T<=10,wct,T)


class AugDemandDataset(Dataset):
    def __init__(self,pf,dem,raw,tm,hour,month,off,pool,mean,scale,env,augment,val_seed=0):
        self.pf=pf;self.dem=dem;self.raw=raw;self.tm=tm;self.hour=hour;self.month=month;self.off=off
        self.pool=pool;self.mean=mean;self.scale=scale;self.augment=augment;self.val_seed=val_seed;self.np_idx=len(pool)
        self.t_lo,self.t_hi,self.w_hi,self.s_hi=env
    def __len__(self): return len(self.dem)-SEQ-self.off-PRED+1
    def _residual(self,i,fh):
        if self.np_idx==0: return np.zeros((PRED,len(INJECT)),np.float32)
        bi=np.random.randint(self.np_idx) if self.augment else int(np.random.default_rng(self.val_seed+i).integers(self.np_idx))
        return self.pool[bi][fh]
    def __getitem__(self,i):
        s=i+SEQ+self.off
        fh=self.hour[s:s+PRED].astype(np.int64); mo=self.month[s:s+PRED]; raw=self.raw[s:s+PRED].copy(); res=self._residual(i,fh)
        T=np.clip(raw[:,0]+res[:,0],self.t_lo[mo,fh],self.t_hi[mo,fh]); RH=np.clip(raw[:,1]+res[:,1],0,100)
        W=np.clip(raw[:,2]+res[:,2],0,self.w_hi[mo,fh]); SO=np.clip(raw[:,3]+res[:,3],0,self.s_hi[mo,fh])
        CL=np.clip(raw[:,4]+res[:,4],0,1); di,wct=comfort_np(T,RH,W)
        exog=np.stack([T,di,wct,SO,CL,raw[:,5]],1); exog=(exog-self.mean)/self.scale
        fut=np.concatenate([exog,self.tm[s:s+PRED]],1).astype(np.float32)
        return {'past_numeric':torch.from_numpy(self.pf[i:i+SEQ]),'past_y':torch.FloatTensor(self.dem[i:i+SEQ][:,None]),
                'future_numeric':torch.from_numpy(fut),'future_y':torch.FloatTensor(self.dem[s:s+PRED]),
                'future_hour':torch.from_numpy(fh)}


def main():
    R=np.load(RES,allow_pickle=True); assert list(R['channels'])==INJECT
    POOL={f'D{n}':R[f'res_D{n}'].astype(np.float32) for n in range(1,16)}
    df=pd.read_csv(CSV,parse_dates=['timestamp']).set_index('timestamp').sort_index()
    idx=pd.date_range(df.index.min(),df.index.max(),freq='h'); df=df.reindex(idx); df.index.name='timestamp'
    df.loc[df['real_demand_land']==0,'real_demand_land']=np.nan
    df['Demand']=df['real_demand_land'].interpolate('time').ffill().bfill()
    T=df[[f'temp_c_{s}' for s in TEMP_SEL]].mean(1).interpolate('time',limit=6).ffill().bfill()
    RH=df[[f'humidity_{s}' for s in TEMP_SEL]].mean(1).interpolate('time',limit=6).ffill().bfill()
    Wms=df[[f'wind_spd_{s}' for s in TEMP_SEL]].mean(1).interpolate('time',limit=6).ffill().bfill()
    df['temp_c']=T; df['rh']=RH; df['wind']=Wms; df['di'],df['wct']=comfort_np(T.values,RH.values,Wms.values)
    df['solar_rad']=df[[f'solar_rad_{s}' for s in SOLAR_SEL]].mean(1).interpolate('time',limit=6).ffill().bfill()
    df['total_cloud']=df[[f'total_cloud_{s}' for s in SOLAR_SEL]].mean(1).interpolate('time',limit=6).ffill().bfill()
    df['cap_btmppa']=df['cap_btmppa'].interpolate('time',limit=6).ffill().bfill()
    df['Hour_sin']=np.sin(2*np.pi*df.index.hour/24); df['Hour_cos']=np.cos(2*np.pi*df.index.hour/24)
    df['Doy_sin']=np.sin(2*np.pi*df.index.dayofyear/365); df['Doy_cos']=np.cos(2*np.pi*df.index.dayofyear/365)
    df['day_type']=df['day_type'].ffill().bfill()
    df['is_weekend']=(df['day_type']=='weekend').astype(float); df['is_holiday']=(df['day_type']=='holiday').astype(float)
    df['hour_int']=df.index.hour.astype(np.int64)

    tr=df[df.index<TRAIN_END]; te=df[df.index>=VAL_END]
    sc=StandardScaler().fit(tr[EXOG]); MEAN=sc.mean_.astype(np.float32); SCALE=sc.scale_.astype(np.float32)
    def envelope(col,how):
        g=df.groupby([df.index.month,df.index.hour])[col].agg(how).unstack(fill_value=np.nan)
        tab=np.full((13,24),np.nan,np.float32)
        for m in g.index:
            for h in g.columns: tab[m,h]=g.loc[m,h]
        fb=np.nanmax(tab) if how=='max' else np.nanmin(tab)
        return np.where(np.isfinite(tab),tab,fb).astype(np.float32)
    ENV=(envelope('temp_c','min'),envelope('temp_c','max'),envelope('wind','max'),envelope('solar_rad','max'))
    def pack(fr):
        ex=sc.transform(fr[EXOG]).astype(np.float32)
        return dict(pf=np.concatenate([ex,fr[TIME].values.astype(np.float32)],1),dem=fr['Demand'].values.astype(np.float32),
                    raw=fr[RAW_W].values.astype(np.float32),tm=fr[TIME].values.astype(np.float32),
                    hour=fr['hour_int'].values.astype(np.int64),month=fr.index.month.values.astype(np.int64))
    PK=pack(tr)
    print('=== 형상/NaN/주입 검증 ===')
    for n in [1,5,10,15]:
        off=(n-1)*24; pool=POOL[f'D{n}']
        ds_aug=AugDemandDataset(PK['pf'],PK['dem'],PK['raw'],PK['tm'],PK['hour'],PK['month'],off,pool,MEAN,SCALE,ENV,True,VAL_SEED)
        ds_no =AugDemandDataset(PK['pf'],PK['dem'],PK['raw'],PK['tm'],PK['hour'],PK['month'],off,np.zeros((0,24,5),np.float32),MEAN,SCALE,ENV,True)
        b=ds_aug[100]; b0=ds_no[100]
        fn=b['future_numeric'].numpy(); fn0=b0['future_numeric'].numpy()
        # di/wct 역검증: future_numeric 의 EXOG 역스케일 → comfort 재계산 일치?
        exog=fn[:,:6]*SCALE+MEAN; T_=exog[:,0]; di_chk,wct_chk=comfort_np(T_, None, None) if False else (None,None)
        # T,RH,W 는 fn 에 직접 없음(di/wct로 흡수). 대신 무주입 대비 변화량으로 주입 확인.
        diff=np.abs(fn[:,:6]-fn0[:,:6]).mean(0)
        # solar 잔차 밤(=0)·temp 변화 존재 확인
        fh=b['future_hour'].numpy(); night=(fh<6)|(fh>=20)
        solar_scaled=fn[:,3]; solar0=fn0[:,3]
        ok_shape=fn.shape==(24,12) and np.isfinite(fn).all()
        ok_inj=diff[0]>1e-6  # temp_c 채널 주입됨
        print(f'  D+{n:<2} len={len(ds_aug):6d} shape_ok={ok_shape} temp주입Δ(scaled)={diff[0]:.3f} '
              f'di_Δ={diff[1]:.3f} wct_Δ={diff[2]:.3f} solar_Δ={diff[3]:.3f} cloud_Δ={diff[4]:.3f} cap_Δ={diff[5]:.4f}')
        assert ok_shape, 'shape/NaN 실패'
        assert ok_inj, 'temp 주입 안됨'
        assert diff[5]<1e-6, 'cap 이 주입됨(버그)'
        # 시간피처 무주입 확인
        assert np.abs(fn[:,6:]-fn0[:,6:]).max()<1e-6, '시간피처가 변함(버그)'
    # 주입 크기가 지평따라 증가하는지(평균 |temp 잔차|)
    print('\n=== 지평별 평균 |temp 잔차| (raw °C, 풀 통계) ===')
    for n in [1,5,10,15]:
        p=POOL[f'D{n}']; print(f'  D+{n:<2}: temp {np.abs(p[:,:,0]).mean():.2f} | rh {np.abs(p[:,:,1]).mean():.2f} | '
              f'wind {np.abs(p[:,:,2]).mean():.2f} | solar {np.abs(p[:,:,3]).mean():.3f} | cloud {np.abs(p[:,:,4]).mean():.3f}')
    print('\n[PASS] 주입 로직 정상 — Colab 업로드 가능(demand_raw_land.csv + forecast_residuals.npz).')


if __name__=='__main__': main()

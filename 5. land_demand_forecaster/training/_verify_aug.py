# -*- coding: utf-8 -*-
"""훈련 전 확실한 검증 — '증강된 미래기상'이 실제로 받게 될 예보 분포를 재현하는가.

질문 3개를 데이터로 답한다:
 (A) 증강 학습입력(합성예보−실측)의 지평별 bias/RMSE 가 실제 예보오차(EDA)와 일치하는가?  → 분포 일치 증명
 (B) 합성된 미래기상 값이 물리적으로 말이 되는가(기온·습도·일사 범위)?                 → 비현실 조합 없음
 (C) 한 사례를 눈으로: 어느 날 D+10, 실측 기온/일사 vs 합성예보 몇 개.                  → 직관 확인
실행: python _verify_aug.py
"""
from __future__ import annotations
import os, sys
import numpy as np, pandas as pd
from sklearn.preprocessing import StandardScaler
try: sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception: pass
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from _smoke_aug import (AugDemandDataset, comfort_np, TEMP_SEL, SOLAR_SEL, EXOG, TIME,
                        RAW_W, INJECT, SEQ, PRED, TRAIN_END, VAL_END, VAL_SEED)
CSV = os.path.join(HERE, 'demand_raw_land.csv'); RES = os.path.join(HERE, 'forecast_residuals.npz')


def build():
    R = np.load(RES, allow_pickle=True)
    POOL = {f'D{n}': R[f'res_D{n}'].astype(np.float32) for n in range(1, 16)}
    df = pd.read_csv(CSV, parse_dates=['timestamp']).set_index('timestamp').sort_index()
    idx = pd.date_range(df.index.min(), df.index.max(), freq='h'); df = df.reindex(idx); df.index.name='timestamp'
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
    tr=df[df.index<TRAIN_END]
    sc=StandardScaler().fit(tr[EXOG]); MEAN=sc.mean_.astype(np.float32); SCALE=sc.scale_.astype(np.float32)
    def envelope(col,how):
        g=df.groupby([df.index.month,df.index.hour])[col].agg(how).unstack(fill_value=np.nan)
        tab=np.full((13,24),np.nan,np.float32)
        for m in g.index:
            for h in g.columns: tab[m,h]=g.loc[m,h]
        fb=np.nanmax(tab) if how=='max' else np.nanmin(tab)
        return np.where(np.isfinite(tab),tab,fb).astype(np.float32)
    ENV=(envelope('temp_c','min'),envelope('temp_c','max'),envelope('wind','max'),envelope('solar_rad','max'))
    ex=sc.transform(tr[EXOG]).astype(np.float32)
    PK=dict(pf=np.concatenate([ex,tr[TIME].values.astype(np.float32)],1),dem=tr['Demand'].values.astype(np.float32),
            raw=tr[RAW_W].values.astype(np.float32),tm=tr[TIME].values.astype(np.float32),
            hour=tr['hour_int'].values.astype(np.int64),month=tr.index.month.values.astype(np.int64))
    return POOL, PK, MEAN, SCALE, ENV, tr


def unscale_exog(fut_num, MEAN, SCALE):
    """future_numeric(앞6=scaled EXOG) → raw [temp_c,di,wct,solar,cloud,cap]"""
    return fut_num[:, :6]*SCALE + MEAN


def main():
    POOL, PK, MEAN, SCALE, ENV, tr = build()
    rng = np.random.default_rng(0)

    # ===== (A) 증강 입력의 지평별 오차 = 실제 예보오차? =====
    print('======== (A) 증강 학습입력(합성예보−실측) vs 실제 예보오차(EDA) ========')
    print('  지평   합성 temp bias/RMSE   (EDA 실제)   |   합성 solar bias/RMSE   (EDA 실제)')
    eda = pd.read_csv(os.path.join(HERE, '_eda_forecast_error_summary.csv'))
    eda = eda[eda.scope=='전체'].set_index(['horizon','channel'])
    for n in [1, 5, 10, 15]:
        off=(n-1)*24; ds=AugDemandDataset(PK['pf'],PK['dem'],PK['raw'],PK['tm'],PK['hour'],PK['month'],off,POOL[f'D{n}'],MEAN,SCALE,ENV,True,VAL_SEED)
        idxs = rng.integers(0, len(ds), size=3000)
        dt, ds_=[], []
        for i in idxs:
            b=ds[int(i)]; fn=b['future_numeric'].numpy(); raw=PK['raw'][int(i)+SEQ+off:int(i)+SEQ+off+PRED]
            ex=unscale_exog(fn, MEAN, SCALE)
            dt.append(ex[:,0]-raw[:,0])     # 합성 temp − 실측 temp
            ds_.append(ex[:,3]-raw[:,3])    # 합성 solar − 실측 solar
        dt=np.concatenate(dt); ds_=np.concatenate(ds_)
        et=eda.loc[(n,'temp_c')]; es=eda.loc[(n,'solar_rad')]
        print(f'  D+{n:<2}  {dt.mean():+6.2f}/{np.sqrt((dt**2).mean()):5.2f}   '
              f'({et.bias:+.2f}/{et.rmse:.2f})   |   {ds_.mean():+6.2f}/{np.sqrt((ds_**2).mean()):5.2f}   ({es.bias:+.2f}/{es.rmse:.2f})')
    print('  → 합성값의 bias/RMSE 가 EDA 실제 예보오차와 같으면, 학습입력이 서빙분포를 재현한다는 증거.')

    # ===== (B) 합성 미래기상 물리범위 =====
    print('\n======== (B) 합성 미래기상 값 범위(D+15, 가장 큰 주입) — 비현실 조합 없는가 ========')
    off=14*24; ds=AugDemandDataset(PK['pf'],PK['dem'],PK['raw'],PK['tm'],PK['hour'],PK['month'],off,POOL['D15'],MEAN,SCALE,ENV,True,VAL_SEED)
    Ts,RHs,SOs,CLs=[],[],[],[]
    for i in rng.integers(0,len(ds),size=2000):
        b=ds[int(i)]; ex=unscale_exog(b['future_numeric'].numpy(),MEAN,SCALE)
        Ts.append(ex[:,0]); SOs.append(ex[:,3]); CLs.append(ex[:,4])
    Ts=np.concatenate(Ts); SOs=np.concatenate(SOs); CLs=np.concatenate(CLs)
    at=tr['temp_c']; aso=tr['solar_rad']
    print(f'  기온 temp_c : 합성 {Ts.min():.1f}~{Ts.max():.1f}°C  (실측 {at.min():.1f}~{at.max():.1f})')
    print(f'  일사 solar  : 합성 {SOs.min():.2f}~{SOs.max():.2f}    (실측 {aso.min():.2f}~{aso.max():.2f}, clip>=0)')
    print(f'  구름 cloud  : 합성 {CLs.min():.2f}~{CLs.max():.2f}    (0~1 clip)')
    print('  → 합성 범위가 실측 범위를 크게 벗어나지 않으면 OK(꼬리 약간 확장은 정상).')

    # ===== (C) 한 사례 눈으로 =====
    print('\n======== (C) 사례: D+10 어느 날, 실측 vs 합성예보 3개 (낮 09~15시 기온·일사) ========')
    off=9*24; ds=AugDemandDataset(PK['pf'],PK['dem'],PK['raw'],PK['tm'],PK['hour'],PK['month'],off,POOL['D10'],MEAN,SCALE,ENV,True,VAL_SEED)
    i=5000; s=i+SEQ+off; raw=PK['raw'][s:s+PRED]; hours=PK['hour'][s:s+PRED]
    day=(hours>=9)&(hours<=15)
    print('  시각 :', ' '.join(f'{h:>5}' for h in hours[day]))
    print('  실측T:', ' '.join(f'{v:5.1f}' for v in raw[day,0]))
    for k in range(3):
        b=ds[i]; ex=unscale_exog(b['future_numeric'].numpy(),MEAN,SCALE)
        print(f'  합성T:', ' '.join(f'{v:5.1f}' for v in ex[day,0]), f'  (샘플{k+1})')
    print('  실측일사:', ' '.join(f'{v:5.2f}' for v in raw[day,3]))
    for k in range(3):
        b=ds[i]; ex=unscale_exog(b['future_numeric'].numpy(),MEAN,SCALE)
        print(f'  합성일사:', ' '.join(f'{v:5.2f}' for v in ex[day,3]), f'  (샘플{k+1})')
    print('  → 합성이 실측 주변에서 매 샘플 다르게 흔들리면(D+10이라 폭 큼) 증강이 정상 작동.')


if __name__ == '__main__':
    main()

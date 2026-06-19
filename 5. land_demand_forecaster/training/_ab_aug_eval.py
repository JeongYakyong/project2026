# -*- coding: utf-8 -*-
"""aug(예보오차 증강) honest 평가 — forecast_horizon 실예보, 전 15지평, LGBM(캐시) vs aug.
서빙 일관: 불쾌지수=reh·체감기온=wind_spd_10m 으로 forecast 에서 동일 재구성. 외생만 scaler_exog 적용.
실행:  python _ab_aug_eval.py --check   (무게 없이 조립·정직성)
       python _ab_aug_eval.py           (전체 평가; landdemand_aug/ + lgbm 캐시 필요)
"""
from __future__ import annotations
import os, sys, sqlite3, tempfile, importlib.util
import numpy as np, pandas as pd, torch, joblib
import torch.nn as nn, torch.nn.functional as F
try: sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception: pass
HERE=os.path.dirname(os.path.abspath(__file__)); ROOT=os.path.normpath(os.path.join(HERE,'..','..'))
MODELDIR=os.path.join(HERE,'..','model'); PKL=os.path.join(HERE,'landdemand_aug'); CACHE=os.path.join(HERE,'_ab_cache')
DB=os.path.join(ROOT,'1. data_fetcher_and_db','data','input_data_land.db'); DEVICE='cpu'; CHECK='--check' in sys.argv
def _imp(n,p): s=importlib.util.spec_from_file_location(n,p); m=importlib.util.module_from_spec(s); s.loader.exec_module(m); return m
expf=_imp('expf',os.path.join(MODELDIR,'exp_features.py')); bht=expf.bht; SEASON=expf.SEASON

# ── 모델(인라인, final2 자립 — 다른 patchtst 스크립트 삭제해도 무방) ──
class _PWA(nn.Module):
    def __init__(self,q,k,h):
        super().__init__(); self.W_Q=nn.Sequential(nn.Linear(q,h),nn.Tanh(),nn.Linear(h,h)); self.W_K=nn.Sequential(nn.Linear(k,h),nn.Tanh(),nn.Linear(h,h)); self.s=1.0/(h**0.5)
    def forward(self,fw,pw,to):
        Q=self.W_Q(fw).unsqueeze(1); K=self.W_K(pw); a=F.softmax(torch.bmm(Q,K.transpose(1,2))*self.s,dim=-1); return torch.bmm(a,to).squeeze(1),a
class PatchTST(nn.Module):
    def __init__(self,num_features,seq_len=336,pred_len=24,patch_len=24,stride=12,d_model=256,num_heads=4,num_layers=3,d_ff=1024,dropout=0.2,revin_affine=True):
        super().__init__(); self.patch_len=patch_len; self.stride=stride; self.pred_len=pred_len; self.num_patches=(seq_len-patch_len)//stride+1
        self.patch_embedding=nn.Linear(patch_len*num_features,d_model); self.pos_embedding=nn.Parameter(torch.randn(1,self.num_patches,d_model)); self.dropout=nn.Dropout(dropout)
        enc=nn.TransformerEncoderLayer(d_model,num_heads,d_ff,dropout,batch_first=True,norm_first=True); self.transformer_encoder=nn.TransformerEncoder(enc,num_layers)
        nwf=num_features-1; ff=pred_len*nwf; wp=patch_len*nwf; self.weather_attn=_PWA(ff,wp,d_model)
        self.regressor=nn.Sequential(nn.Linear(d_model+ff,256),nn.LeakyReLU(0.1),nn.Dropout(dropout),nn.Linear(256,pred_len)); self.weather_bypass=nn.Linear(ff,pred_len)
        self.revin_affine=revin_affine; self.eps=1e-5
        if revin_affine: self.revin_w=nn.Parameter(torch.ones(1)); self.revin_b=nn.Parameter(torch.zeros(1))
    def forward(self,b):
        pn=b['past_numeric'].to(DEVICE); py=b['past_y'].to(DEVICE); fn=b['future_numeric'].to(DEVICE); B=pn.shape[0]
        mean=py.mean(1,keepdim=True); std=torch.sqrt(py.var(1,keepdim=True,unbiased=False)+self.eps); pyn=(py-mean)/std
        if self.revin_affine: pyn=pyn*self.revin_w+self.revin_b
        xp=torch.cat([pn,pyn],-1); xpp=xp.unfold(1,self.patch_len,self.stride).permute(0,1,3,2).reshape(B,self.num_patches,-1)
        eo=self.transformer_encoder(self.dropout(self.patch_embedding(xpp)+self.pos_embedding)); ff=fn.reshape(B,-1)
        xw=xp[...,:-1].unfold(1,self.patch_len,self.stride).permute(0,1,3,2).reshape(B,self.num_patches,-1); ctx,_=self.weather_attn(ff,xw,eo)
        on=self.regressor(torch.cat([ctx,ff],1))+self.weather_bypass(ff)
        if self.revin_affine: on=(on-self.revin_b)/self.revin_w
        return on*std.squeeze(-1)+mean.squeeze(-1), std.squeeze(-1)
HORIZONS={f'D{n}':(n-1)*24 for n in range(1,8)}   # ★D+1~7만(D+8~15=LGBM)
FORE={'temp':'temp','rh':'reh','wind':'wind_spd_10m','solar':'radiation','cloud':'total_cloud'}

def mape(a,p):
    a,p=np.asarray(a,float),np.asarray(p,float); k=(a>0)&np.isfinite(a)&np.isfinite(p); return float(np.mean(np.abs(a[k]-p[k])/a[k])*100) if k.any() else np.nan

def comfort(T,RH,Wms):
    di=0.81*T+0.01*RH*(0.99*T-14.3)+46.3
    Wk=np.clip(Wms*3.6,4.8,None); wct=13.12+0.6215*T-11.37*Wk**0.16+0.3965*T*Wk**0.16
    return di, np.where(T<=10,wct,T)

# ── 메타/스케일러 (--check 시 합성) ──
if os.path.exists(os.path.join(PKL,'metadata_landdemand_aug.pkl')):
    META=joblib.load(os.path.join(PKL,'metadata_landdemand_aug.pkl')); SCALER=joblib.load(os.path.join(PKL,'scaler_exog.pkl'))
else:
    META=dict(HP=dict(seq_len=336,patch_len=24,stride=12,d_model=256,num_heads=4,num_layers=3,d_ff=1024,dropout=0.2),
              EXOG=['temp_c','di','wct','solar_rad','total_cloud','cap_btmppa'],
              TIME=['Hour_sin','Hour_cos','Doy_sin','Doy_cos','is_weekend','is_holiday'],
              TEMP_SEL=['wonju','seosan','pohang','yeonggwang'], SOLAR_SEL=['seosan','yeonggwang']); SCALER=None
HP=META['HP']; EXOG=META['EXOG']; TIME=META['TIME']; FF=EXOG+TIME; TEMP_SEL=META['TEMP_SEL']; SOLAR_SEL=META['SOLAR_SEL']; SEQ=HP['seq_len']

def add_time(df):
    df=df.copy()
    df['Hour_sin']=np.sin(2*np.pi*df.index.hour/24); df['Hour_cos']=np.cos(2*np.pi*df.index.hour/24)
    df['Doy_sin']=np.sin(2*np.pi*df.index.dayofyear/365); df['Doy_cos']=np.cos(2*np.pi*df.index.dayofyear/365)
    df['is_weekend']=(df['day_type']=='weekend').astype(float); df['is_holiday']=(df['day_type']=='holiday').astype(float)
    return df

def scale_exog(frame):
    out=frame.copy()
    if SCALER is not None: out[EXOG]=SCALER.transform(out[EXOG])
    return out

def load_actual(ppa):
    pull=['timestamp','real_demand_land','day_type']
    pull+=[f'temp_c_{s}' for s in TEMP_SEL]+[f'humidity_{s}' for s in TEMP_SEL]+[f'wind_spd_{s}' for s in TEMP_SEL]
    pull+=[f'solar_rad_{s}' for s in SOLAR_SEL]+[f'total_cloud_{s}' for s in SOLAR_SEL]
    with sqlite3.connect(DB) as con: raw=pd.read_sql(f"SELECT {', '.join(pull)} FROM historical",con,parse_dates=['timestamp'])
    raw=raw.sort_values('timestamp'); idx=pd.date_range(raw.timestamp.min(),raw.timestamp.max(),freq='h')
    d=raw.set_index('timestamp').reindex(idx); d.index.name='timestamp'
    d.loc[d.real_demand_land==0,'real_demand_land']=np.nan; d['Demand']=d['real_demand_land'].interpolate('time').ffill().bfill()
    for c in pull[3:]: d[c]=pd.to_numeric(d[c],errors='coerce').interpolate('time',limit=6).ffill().bfill()
    T=d[[f'temp_c_{s}' for s in TEMP_SEL]].mean(1); RH=d[[f'humidity_{s}' for s in TEMP_SEL]].mean(1); W=d[[f'wind_spd_{s}' for s in TEMP_SEL]].mean(1)
    d['temp_c']=T; d['di'],d['wct']=comfort(T,RH,W)
    d['solar_rad']=d[[f'solar_rad_{s}' for s in SOLAR_SEL]].mean(1); d['total_cloud']=d[[f'total_cloud_{s}' for s in SOLAR_SEL]].mean(1)
    d['cap_btmppa']=expf.cap_for(d.index,ppa); d['day_type']=d['day_type'].ffill().bfill()
    d=add_time(d); d['hour_int']=d.index.hour.astype(np.int64)
    return d

def fh_final2(sc,tg,ppa):
    cols=sorted(set([f'{FORE["temp"]}_{s}' for s in TEMP_SEL]+[f'{FORE["rh"]}_{s}' for s in TEMP_SEL]+[f'{FORE["wind"]}_{s}' for s in TEMP_SEL]+
                    [f'{FORE["solar"]}_{s}' for s in SOLAR_SEL]+[f'{FORE["cloud"]}_{s}' for s in SOLAR_SEL]))
    ext=pd.date_range(tg.min()-pd.Timedelta(hours=3),tg.max()+pd.Timedelta(hours=3),freq='h')
    sel=', '.join(f'"{c}"' for c in ['timestamp']+cols)
    fc=pd.read_sql(f'SELECT {sel} FROM forecast WHERE timestamp BETWEEN ? AND ? ORDER BY timestamp',sc,params=(bht._S(ext[0]),bht._S(ext[-1])),parse_dates=['timestamp']).set_index('timestamp')
    fc=fc.apply(pd.to_numeric,errors='coerce').reindex(ext)
    def mi(cs): return fc[cs].mean(1).interpolate('time',limit=3,limit_area='inside').reindex(tg).values
    T=mi([f'{FORE["temp"]}_{s}' for s in TEMP_SEL]); RH=mi([f'{FORE["rh"]}_{s}' for s in TEMP_SEL]); W=mi([f'{FORE["wind"]}_{s}' for s in TEMP_SEL])
    out=pd.DataFrame(index=tg); out['temp_c']=T; out['di'],out['wct']=comfort(T,RH,W)
    out['solar_rad']=mi([f'{FORE["solar"]}_{s}' for s in SOLAR_SEL]); out['total_cloud']=mi([f'{FORE["cloud"]}_{s}' for s in SOLAR_SEL])
    out['cap_btmppa']=expf.cap_for(tg,ppa)
    valid=out[['temp_c','di','wct','solar_rad']].notna().all(axis=1)
    return out, valid

@torch.no_grad()
def run(lgbm_df):
    ppa=expf.load_capa(); d=load_actual(ppa); dsc=scale_exog(d)   # 과거 외생 z-score
    A_sc=dsc[FF]; dem=d['Demand']
    models={}
    if not CHECK:
        for hn in HORIZONS:
            m=PatchTST(len(FF)+1,pred_len=24,**HP).to(DEVICE); m.load_state_dict(torch.load(os.path.join(PKL,f'best_patchtst_landdemand_{hn}.pth'),map_location=DEVICE)); m.eval(); models[hn]=m
    with sqlite3.connect(DB) as con: bases=[r[0] for r in con.execute('SELECT DISTINCT base FROM forecast_horizon ORDER BY base').fetchall()]
    scdb=bht.build_scratch(os.path.join(tempfile.gettempdir(),'ab_final2.db')); rows=[]
    for base in bases:
        O=pd.Timestamp(base).normalize()+pd.Timedelta(hours=23)
        if O not in A_sc.index: continue
        oi=A_sc.index.get_loc(O)
        if oi-(SEQ-1)<0: continue
        past=A_sc.iloc[oi-(SEQ-1):oi+1].values.astype(np.float32); py=dem.iloc[oi-(SEQ-1):oi+1].values.astype(np.float32)[:,None]
        if not(np.isfinite(past).all() and np.isfinite(py).all()): continue
        bht.set_scratch_forecast(scdb,base)
        for hn,off in HORIZONS.items():
            H=np.arange(off+1,off+25); tg=pd.DatetimeIndex([O+pd.Timedelta(hours=int(h)) for h in H])
            wx,valid=fh_final2(scdb,tg,ppa); F=add_time(wx.assign(day_type=d['day_type'].reindex(tg).values))
            ok=valid.values & F[FF].notna().all(axis=1).values
            if not ok.any(): continue
            if CHECK:
                print(f'  [aug/{hn}] EXOG+TIME={len(FF)} 조립 OK · forecast 결합 OK · 첫블록 valid={int(ok.sum())}'); break
            Fs=scale_exog(F[FF].ffill().bfill());
            pred,_=models[hn]({'past_numeric':torch.from_numpy(past[None]),'past_y':torch.from_numpy(py[None]),'future_numeric':torch.from_numpy(Fs.values.astype(np.float32)[None])})
            pr=np.clip(pred.numpy().ravel(),0,None); pr[~ok]=np.nan
            rows.append(pd.DataFrame({'base':base,'timestamp':tg,'horizon':int(hn[1:]),'pred':pr}))
        if CHECK and base==bases[0]: break
    scdb.close()
    if CHECK: print('\n[--check] PASS — comfort 조립·z-score·forecast 결합 정상. 무게 오면 --check 빼고 실행.'); return None
    P=pd.concat(rows,ignore_index=True)
    g=lgbm_df.merge(P,on=['base','timestamp','horizon'],how='inner').dropna(subset=['actual','pred_lgbm','pred']); g=g[g.actual>0]
    ts=pd.to_datetime(g.timestamp); return g.assign(daypart=np.where((ts.dt.hour>=9)&(ts.dt.hour<=15),'주간','야간'),season=ts.dt.month.map(SEASON))

def grid(g,n):
    gh=g[g.horizon==n]
    if gh.empty: return
    print(f'\n[final2] D+{n} (n={len(gh)})  각 칸=LGBM→aug MAPE%')
    print(f"  {'계절':<5}{'전체':>15}{'주간':>15}{'야간':>15}")
    for s in ['전체','겨울','봄','여름','가을']:
        gs=gh if s=='전체' else gh[gh.season==s]
        if gs.empty: continue
        cells=[]
        for dp in ['전체','주간','야간']:
            gd=gs if dp=='전체' else gs[gs.daypart==dp]
            cells.append('     -     ' if gd.empty else f'{mape(gd.actual,gd.pred_lgbm):5.2f}→{mape(gd.actual,gd.pred):5.2f}')
        print(f"  {s:<5}"+''.join(f'{c:>15}' for c in cells))

def main():
    if CHECK: run(None); return
    lp=os.path.join(CACHE,'lgbm.parquet')
    if not os.path.exists(lp): sys.exit('lgbm 캐시 없음 — 먼저 _ab_honest.py 1회 실행.')
    if not os.path.isdir(PKL): sys.exit('landdemand_aug/ 없음 — Colab 산출물부터 넣어주세요.')
    g=run(pd.read_parquet(lp))
    print('\n======== aug honest 전체 요약 (LGBM→aug) ========')
    print('  '+'  '.join(f'D+{n} {mape(g[g.horizon==n].actual,g[g.horizon==n].pred_lgbm):.1f}→{mape(g[g.horizon==n].actual,g[g.horizon==n].pred):.1f}' for n in range(1,8)))
    print('\n======== 계절×낮밤 상세 ========')
    for n in range(1,8): grid(g,n)
    g.to_parquet(os.path.join(HERE,'_ab_aug_merged.parquet'),index=False); print('\n저장: _ab_aug_merged.parquet')

if __name__=='__main__': main()

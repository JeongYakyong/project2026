# -*- coding: utf-8 -*-
"""6-B — 전국 태양광 이용률: PatchTST(D1/D2/D3 direct) vs LGBM(6-A) 비교.

G-13: 태양광만 D+1/2/3 PatchTST vs LGBM 비교 → 큰 차이 없으면 LGBM 단일(풍력은 LGBM 확정).
가중치: training/landsolar_patchtst/best_patchtst_landsolar_D{1,2,3}.pth (+scaler+metadata, 사용자 학습).
비교: 동일 test 2026 origin(D0 23:00)에서 D+1/2/3 24h 블록 예측.
  - PatchTST: 과거 336h 시퀀스 + 대상일 기상(offset (h-1)*24) → util.
  - LGBM(6-A): 지평무관(기상→util), 대상일 기상으로 예측.
평가: util MAE(전시간/낮 8-17h/흐린날) perfect & forecast + true_solar(MWh) 영향(×total_solar_cap).
산출: tab/6-B_*.csv, fig/6-B_*.png, REPORT_6-B.md
"""
import os, sys, json, sqlite3, warnings
import numpy as np, pandas as pd, torch, joblib, lightgbm as lgb
import torch.nn as nn, torch.nn.functional as F
import matplotlib; matplotlib.use('Agg'); import matplotlib.pyplot as plt
warnings.filterwarnings('ignore')
for _f in ['Malgun Gothic','Gulim']:
    if any(_f==f.name for f in matplotlib.font_manager.fontManager.ttflist):
        plt.rcParams['font.family']=_f; break
plt.rcParams['axes.unicode_minus']=False
DEVICE='cuda' if torch.cuda.is_available() else 'cpu'

HERE=os.path.dirname(os.path.abspath(__file__))
ROOT=os.path.normpath(os.path.join(HERE,'..'))
TRAIN=os.path.join(ROOT,'training','landsolar_patchtst')
MOD=os.path.join(HERE,'models'); FIG=os.path.join(HERE,'fig'); TAB=os.path.join(HERE,'tab')
for d in (FIG,TAB): os.makedirs(d,exist_ok=True)
DB=os.path.normpath(os.path.join(HERE,'..','..','1. data_fetcher_and_db','data','input_data_land.db'))
PPA_CSV=os.path.normpath(os.path.join(HERE,'..','..','1. data_fetcher_and_db','second_dataset','ppa_scale.csv'))

# ── 자산 로드 ──
meta=joblib.load(os.path.join(TRAIN,'metadata_landsolar.pkl'))
scaler=joblib.load(os.path.join(TRAIN,'scaler_landsolar.pkl'))
FF=meta['future_features_solar']; HP=meta['SOLAR_HP']; SEQ=meta['SEQ_LEN']; PL=meta['PRED_LEN']
K_DAMP=meta['K_DAMP']; ST=meta['SOLAR_STATIONS']; HOR=meta['HORIZONS']
mS_lgbm=lgb.Booster(model_file=os.path.join(MOD,'lgbm_land_solar_util.txt'))
meta6a=json.load(open(os.path.join(MOD,'model_meta_6a.json'),encoding='utf-8'))
LGBM_FEATS=meta6a['solar_feats']
recon=json.load(open(os.path.join(MOD,'btm_ppa_recon_6a2.json'),encoding='utf-8')); K=recon['k']; R=recon['r']

# ── PatchTST 아키텍처(생성기와 동일) ──
class Patch_Weather_Attention(nn.Module):
    def __init__(self,q,k,h):
        super().__init__()
        self.W_Q=nn.Sequential(nn.Linear(q,h),nn.Tanh(),nn.Linear(h,h))
        self.W_K=nn.Sequential(nn.Linear(k,h),nn.Tanh(),nn.Linear(h,h)); self.s=1.0/(h**0.5)
    def forward(self,fw,pw,to):
        Q=self.W_Q(fw).unsqueeze(1); K=self.W_K(pw)
        a=F.softmax(torch.bmm(Q,K.transpose(1,2))*self.s,dim=-1); return torch.bmm(a,to).squeeze(1),a
class PatchTST_Weather_Model(nn.Module):
    def __init__(self,num_features,seq_len=336,pred_len=24,patch_len=24,stride=12,
                 d_model=128,num_heads=4,num_layers=3,d_ff=512,dropout=0.2):
        super().__init__()
        self.patch_len=patch_len; self.stride=stride; self.seq_len=seq_len; self.pred_len=pred_len
        self.num_patches=(seq_len-patch_len)//stride+1
        self.patch_embedding=nn.Linear(patch_len*num_features,d_model)
        self.pos_embedding=nn.Parameter(torch.randn(1,self.num_patches,d_model)); self.dropout=nn.Dropout(dropout)
        enc=nn.TransformerEncoderLayer(d_model=d_model,nhead=num_heads,dim_feedforward=d_ff,dropout=dropout,batch_first=True,norm_first=True)
        self.transformer_encoder=nn.TransformerEncoder(enc,num_layers=num_layers)
        self.num_weather_feats=num_features-1; ff=pred_len*self.num_weather_feats; wp=patch_len*self.num_weather_feats
        self.weather_attn=Patch_Weather_Attention(ff,wp,d_model)
        self.regressor=nn.Sequential(nn.Linear(d_model+ff,256),nn.LeakyReLU(0.1),nn.Dropout(dropout),nn.Linear(256,pred_len))
        self.weather_bypass=nn.Linear(ff,pred_len)
    def forward(self,b):
        p=b['past_numeric'].to(DEVICE); py=b['past_y'].to(DEVICE); f=b['future_numeric'].to(DEVICE); B=p.shape[0]
        x=torch.cat([p,py],dim=-1)
        xp=x.unfold(1,self.patch_len,self.stride).permute(0,1,3,2).reshape(B,self.num_patches,-1)
        eo=self.transformer_encoder(self.dropout(self.patch_embedding(xp)+self.pos_embedding))
        ffl=f.reshape(B,-1)
        xw=x[...,:-1].unfold(1,self.patch_len,self.stride).permute(0,1,3,2).reshape(B,self.num_patches,-1)
        ctx,_=self.weather_attn(ffl,xw,eo)
        return self.regressor(torch.cat([ctx,ffl],dim=1))+self.weather_bypass(ffl)

def load_pt(hname):
    m=PatchTST_Weather_Model(len(FF)+1,pred_len=PL,**HP).to(DEVICE)
    m.load_state_dict(torch.load(os.path.join(TRAIN,f'best_patchtst_landsolar_{hname}.pth'),map_location=DEVICE))
    m.eval(); return m
pt={h:load_pt(h) for h in HOR}
print('PatchTST 로드:',list(pt.keys()),'| feats',len(FF))

# ── 데이터: historical(perfect) ──
def damping(ts,rain):
    s=pd.Series(rain.values,index=ts).between_time('06:00','20:00'); d=s.groupby(s.index.date).sum()
    return np.exp(-K_DAMP*pd.Series(ts.dt.date.values).map(d).clip(upper=20).astype(float).values)
pull=['timestamp','gen_solar_utilization_kr','gen_solar_capacity_kr']
for st in ST: pull+=[f'solar_rad_{st}',f'total_cloud_{st}',f'midlow_cloud_{st}',f'rainfall_{st}']
con=sqlite3.connect(DB); H=pd.read_sql(f"SELECT {', '.join(pull)} FROM historical",con,parse_dates=['timestamp'])
F_=pd.read_sql('SELECT * FROM forecast',con,parse_dates=['timestamp']); con.close()
H=H.sort_values('timestamp').reset_index(drop=True)
for c in H.columns:
    if c!='timestamp': H[c]=pd.to_numeric(H[c],errors='coerce')
for c in F_.columns:
    if c!='timestamp': F_[c]=pd.to_numeric(F_[c],errors='coerce')

# ppa_cap → total_solar_cap
ppa=pd.read_csv(PPA_CSV,encoding='cp949'); ppa['ym']=pd.to_datetime(ppa['기간'],format='%b-%y').dt.to_period('M')
ppa=ppa.rename(columns={'PPA 계':'ppa_cap'})[['ym','ppa_cap']].dropna()
H['ym']=H.timestamp.dt.to_period('M'); H=H.merge(ppa,on='ym',how='left'); H['ppa_cap']=H['ppa_cap'].ffill().bfill()
H['total_solar_cap']=H['gen_solar_capacity_kr']+K*(1+R)*H['ppa_cap']

def build_pt_matrix(df, src):
    M=pd.DataFrame(index=df['timestamp'])
    for st in ST:
        if src=='hist':
            rad,tc,mc,rn=f'solar_rad_{st}',f'total_cloud_{st}',f'midlow_cloud_{st}',f'rainfall_{st}'
        else:
            rad,tc,mc,rn=f'radiation_{st}',f'total_cloud_{st}',f'midlow_cloud_{st}',f'rainfall_{st}'
        M[f'solar_rad_{st}']=df[rad].values; M[f'total_cloud_{st}']=df[tc].values; M[f'midlow_cloud_{st}']=df[mc].values
        M[f'solar_damping_{st}']=damping(df['timestamp'], df[rn])
    M['Hour_sin']=np.sin(2*np.pi*M.index.hour/24); M['Hour_cos']=np.cos(2*np.pi*M.index.hour/24)
    M=M.interpolate(limit=3).ffill().bfill()
    S=pd.DataFrame(scaler.transform(M[FF]),index=M.index,columns=FF)
    return S
S_hist=build_pt_matrix(H,'hist'); S_fc=build_pt_matrix(F_,'fc')
util_act=H.set_index('timestamp')['gen_solar_utilization_kr']
py_series=util_act.copy()   # past_y = 실측 이용률(origin까지 known)

# LGBM 피처(평균) — hist & forecast
def lgbm_feats(df, src):
    d=pd.DataFrame(index=df['timestamp'])
    if src=='hist':
        d['solar_rad']=df[[f'solar_rad_{s}' for s in ST]].mean(1).values
        d['total_cloud']=df[[f'total_cloud_{s}' for s in ST]].mean(1).values
        rain=df[[f'rainfall_{s}' for s in ST]].mean(1)
    else:
        d['solar_rad']=df[[f'radiation_{s}' for s in ST]].mean(1).values
        d['total_cloud']=df[[f'total_cloud_{s}' for s in ST]].mean(1).values
        rain=df[[f'rainfall_{s}' for s in ST]].mean(1)
    d['solar_damping']=damping(df['timestamp'],rain)
    d['hour_sin']=np.sin(2*np.pi*d.index.hour/24); d['hour_cos']=np.cos(2*np.pi*d.index.hour/24)
    d['doy_sin']=np.sin(2*np.pi*d.index.dayofyear/365); d['doy_cos']=np.cos(2*np.pi*d.index.dayofyear/365)
    return d
LG_hist=lgbm_feats(H,'hist'); LG_fc=lgbm_feats(F_,'fc')

@torch.no_grad()
def pt_predict(model, Smat, target_day, origin):
    past_idx=pd.date_range(origin-pd.Timedelta(hours=SEQ-1), origin, freq='h')
    fut_idx=pd.date_range(target_day, periods=PL, freq='h')
    pn=Smat.reindex(past_idx)[FF].values; fn=Smat.reindex(fut_idx)[FF].values
    py=py_series.reindex(past_idx).values.reshape(-1,1)
    if np.isnan(pn).any() or np.isnan(fn).any() or np.isnan(py).any(): return None,fut_idx
    b={'past_numeric':torch.FloatTensor(pn).unsqueeze(0),'past_y':torch.FloatTensor(py).unsqueeze(0),
       'future_numeric':torch.FloatTensor(fn).unsqueeze(0)}
    return np.clip(model(b).squeeze(0).cpu().numpy(),0,1), fut_idx

# ── 평가 루프: test 2026 origins × D1/D2/D3 ──
test_days=pd.date_range('2026-01-01','2026-06-04',freq='D')
HMAP={'D1':1,'D2':2,'D3':3}
rows=[]
for cond,Smat,LGmat in [('perfect',S_hist,LG_hist),('forecast',S_fc,LG_hist)]:
    # forecast: 미래기상=forecast(Smat=S_fc), 과거 시퀀스=historical(S_hist), LGBM 미래기상=forecast
    Spast = S_hist
    Sfut  = Smat
    LGuse = LG_fc if cond=='forecast' else LG_hist
    recs=[]
    for hn,hd in HMAP.items():
        off=HOR[hn]
        for D0 in test_days:
            origin=D0+pd.Timedelta(hours=23); tday=D0+pd.Timedelta(days=hd)
            # PatchTST: past=hist, future=cond
            past_idx=pd.date_range(origin-pd.Timedelta(hours=SEQ-1),origin,freq='h')
            fut_idx=pd.date_range(tday,periods=PL,freq='h')
            pn=Spast.reindex(past_idx)[FF].values
            fn=Sfut.reindex(fut_idx)[FF].values
            py=py_series.reindex(past_idx).values.reshape(-1,1)
            if np.isnan(pn).any() or np.isnan(fn).any() or np.isnan(py).any(): continue
            b={'past_numeric':torch.FloatTensor(pn).unsqueeze(0),'past_y':torch.FloatTensor(py).unsqueeze(0),
               'future_numeric':torch.FloatTensor(fn).unsqueeze(0)}
            with torch.no_grad(): pt_pred=np.clip(pt[hn](b).squeeze(0).cpu().numpy(),0,1)
            lg_in=LGuse.reindex(fut_idx)[LGBM_FEATS]
            if lg_in.isna().any().any(): continue
            lg_pred=np.clip(mS_lgbm.predict(lg_in.values),0,1)
            act=util_act.reindex(fut_idx).values
            cap=H.set_index('timestamp')['total_solar_cap'].reindex(fut_idx).values
            cloud=LG_hist.reindex(fut_idx)['total_cloud'].values
            for i,ts in enumerate(fut_idx):
                if np.isnan(act[i]): continue
                recs.append(dict(cond=cond,h=hd,ts=ts,hour=ts.hour,act=act[i],
                                 pt=pt_pred[i],lg=lg_pred[i],cap=cap[i],cloud=cloud[i]))
    rows.extend(recs)
R_=pd.DataFrame(rows)
print('비교 표본', len(R_), '| cond', dict(R_.cond.value_counts()))

# ── 집계: util MAE (전시간/낮/흐린날) + true_solar MWh MAE ──
def agg(df):
    out=[]
    for (cond,h),g in df.groupby(['cond','h']):
        day=g[(g.hour>=8)&(g.hour<=17)]
        # 흐린날: 낮 평균 구름 상위40%
        dd=day.groupby(day.ts.dt.date).cloud.mean(); thr=dd.quantile(0.6) if len(dd) else 0
        cloudy=day[day.ts.dt.date.map(dd)>=thr]
        def mae(x,col): return float(np.abs(x[col]-x['act']).mean()) if len(x) else np.nan
        out.append(dict(cond=cond,h=h,n_day=len(day),
            pt_all=mae(g,'pt'),lg_all=mae(g,'lg'),
            pt_day=mae(day,'pt'),lg_day=mae(day,'lg'),
            pt_cloudy=mae(cloudy,'pt'),lg_cloudy=mae(cloudy,'lg'),
            pt_solarMW=float(np.abs((day.pt-day.act)*day.cap).mean()),
            lg_solarMW=float(np.abs((day.lg-day.act)*day.cap).mean())))
    return pd.DataFrame(out)
A=agg(R_); A.to_csv(os.path.join(TAB,'6-B_compare.csv'),index=False)
pd.set_option('display.width',200)
print('\n=== util MAE (낮 8-17h) + true_solar MW MAE — PatchTST vs LGBM ===')
print(A[['cond','h','n_day','pt_day','lg_day','pt_cloudy','lg_cloudy','pt_solarMW','lg_solarMW']].round(4).to_string(index=False))

# ── 그림 ──
fig,ax=plt.subplots(1,2,figsize=(13,4.3))
for cond,mk in [('perfect','o-'),('forecast','^--')]:
    a=A[A.cond==cond]
    ax[0].plot(a.h,a.pt_day,mk,color='green',label=f'PatchTST {cond}')
    ax[0].plot(a.h,a.lg_day,mk,color='navy',label=f'LGBM {cond}')
ax[0].set_title('태양광 util MAE (낮) by horizon'); ax[0].set_xlabel('D+h'); ax[0].set_xticks([1,2,3]); ax[0].legend(fontsize=8)
for cond,mk in [('perfect','o-'),('forecast','^--')]:
    a=A[A.cond==cond]
    ax[1].plot(a.h,a.pt_solarMW,mk,color='green',label=f'PatchTST {cond}')
    ax[1].plot(a.h,a.lg_solarMW,mk,color='navy',label=f'LGBM {cond}')
ax[1].set_title('true_solar MW MAE (낮) by horizon'); ax[1].set_xlabel('D+h'); ax[1].set_xticks([1,2,3]); ax[1].legend(fontsize=8)
plt.tight_layout(); plt.savefig(os.path.join(FIG,'6-B_compare.png'),bbox_inches='tight'); plt.close()

# ── REPORT ──
def fmt(c,h,col):
    v=A[(A.cond==c)&(A.h==h)][col]; return f'{v.values[0]:.4f}' if len(v) else 'NA'
rep=f"""# 6-B 요약 — 전국 태양광 PatchTST(D1/2/3) vs LGBM(6-A)

## 설정
- 가중치: landsolar_patchtst(d_model={HP['d_model']}·layers={HP['num_layers']}·d_ff={HP['d_ff']}, 14피처 3지점 raw).
- 동일 test 2026 origin(D0 23:00) → D+1/2/3 24h. PatchTST=과거336h+대상일기상, LGBM=6-A(지평무관).
- 평가: util MAE(낮 8-17h·흐린날) + true_solar MW MAE(×total_solar_cap). perfect/forecast.

## 결과 (낮시간 util MAE)
| 지평 | PatchTST perfect | LGBM perfect | PatchTST forecast | LGBM forecast |
|---|---|---|---|---|
| D+1 | {fmt('perfect',1,'pt_day')} | {fmt('perfect',1,'lg_day')} | {fmt('forecast',1,'pt_day')} | {fmt('forecast',1,'lg_day')} |
| D+2 | {fmt('perfect',2,'pt_day')} | {fmt('perfect',2,'lg_day')} | {fmt('forecast',2,'pt_day')} | {fmt('forecast',2,'lg_day')} |
| D+3 | {fmt('perfect',3,'pt_day')} | {fmt('perfect',3,'lg_day')} | {fmt('forecast',3,'pt_day')} | {fmt('forecast',3,'lg_day')} |

표 전체(흐린날·true_solar MW 포함): tab/6-B_compare.csv · fig/6-B_compare.png

## 판단(G-13)
- PatchTST가 LGBM 대비 의미 있는(특히 forecast·흐린날·true_solar MW) 개선이면 태양광=PatchTST(D1~3)+LGBM(D4~) 하이브리드.
- 큰 차이 없으면 **태양광도 LGBM 단일**(파시모니·서빙 단순). 아래 수치로 결정.
"""
open(os.path.join(HERE,'REPORT_6-B.md'),'w',encoding='utf-8').write(rep)
print('\n'+rep)
print('완료 → tab/6-B_compare.csv, fig/6-B_compare.png, REPORT_6-B.md')

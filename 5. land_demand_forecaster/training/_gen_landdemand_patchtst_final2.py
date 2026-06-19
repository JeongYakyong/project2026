# -*- coding: utf-8 -*-
"""train_landdemand_patchtst_colab_final2.ipynb 생성기 — ★최종 PatchTST(피처 재구성판).

확정(사용자, §0.6):
  - temp 4지점(대관령 제외=무인). 불쾌지수(temp+습도)·체감기온(temp+바람) = 여름/겨울 직접 공략.
  - 외생피처 = [temp_c, 불쾌지수, 체감기온, solar_rad, total_cloud, cap_btmppa] → **전역 z-score(StandardScaler, train fit)**.
  - 시간피처 = [Hour/Doy sin·cos, is_weekend, is_holiday] → **정규화 제외(원본)**.
  - 타깃(수요) = **RevIN(affine)**, 출력 역정규화.  손실=단순 MSE(std스케일).  lag·wind·humidity·midlow 제거.
서빙 일관: 불쾌지수=reh, 체감기온=wind_spd_10m 으로 forecast_horizon 에서 동일 재구성(하니스 미러).
산출: best_patchtst_landdemand_{D1..D15}.pth + scaler_exog.pkl + metadata_landdemand_final2.pkl.
"""
import json
from pathlib import Path

OUT = Path(__file__).resolve().parent / "train_landdemand_patchtst_colab_final2.ipynb"
CELLS = []
def md(s):  CELLS.append(("markdown", s.strip("\n")))
def code(s): CELLS.append(("code", s.strip("\n")))

md(r"""
# 전국 수요 PatchTST — ★최종(피처 재구성: comfort + 전역 z-score)

- 외생 = temp_c(4지점)·**불쾌지수**·**체감기온**·solar_rad·total_cloud·cap_btmppa → 전역 z-score.
- 시간피처 = 달력 sin/cos·is_weekend·is_holiday → 원본(정규화 제외).
- 타깃 = 수요 RevIN(affine). 손실 = 단순 MSE. 15모델 direct(D+1..D+15), lag 없음.

**입력**: `demand_raw_land.csv`(humidity·wind 포함 재추출본). **산출**: `_D1.._D15.pth` + `scaler_exog.pkl` + metadata.
""")

code(r"""
import numpy as np, pandas as pd, torch, os, json, joblib
import torch.nn as nn, torch.nn.functional as F
from torch.utils.data import Dataset, DataLoader
from sklearn.preprocessing import StandardScaler
from tqdm.auto import tqdm
DEVICE = 'cuda' if torch.cuda.is_available() else 'cpu'
print('DEVICE =', DEVICE)
""")

code(r"""
CSV_PATH = '/content/demand_raw_land.csv'
OUT_DIR  = '/content/out'; os.makedirs(OUT_DIR, exist_ok=True)
PRED_LEN = 24
HORIZONS = {f'D{n}': (n-1)*24 for n in range(1, 16)}
TRAIN_END = '2025-01-01'; VAL_END = '2026-01-01'
TEMP_SEL  = ['wonju', 'seosan', 'pohang', 'yeonggwang']   # 대관령 제외(무인)
SOLAR_SEL = ['seosan', 'yeonggwang']
HP = dict(seq_len=336, patch_len=24, stride=12, d_model=256, num_heads=4, num_layers=3, d_ff=1024, dropout=0.2)
EPOCHS = 80; BATCH_SIZE = 256; LR = 1e-3; PATIENCE = 12

EXOG = ['temp_c', 'di', 'wct', 'solar_rad', 'total_cloud', 'cap_btmppa']   # 전역 z-score 대상
TIME = ['Hour_sin', 'Hour_cos', 'Doy_sin', 'Doy_cos', 'is_weekend', 'is_holiday']   # 정규화 제외
FUTURE_FEATURES = EXOG + TIME
print('EXOG', EXOG, '| TIME', TIME)
""")

code(r"""
df = pd.read_csv(CSV_PATH); df['timestamp'] = pd.to_datetime(df['timestamp'])
df = df.set_index('timestamp').sort_index()
idx = pd.date_range(df.index.min(), df.index.max(), freq='h'); df = df.reindex(idx); df.index.name='timestamp'
df.loc[df['real_demand_land']==0,'real_demand_land']=np.nan
df['Demand']=df['real_demand_land'].interpolate('time').ffill().bfill()

# 인구권 4지점 평균: 기온·습도·바람
T = df[[f'temp_c_{s}' for s in TEMP_SEL]].mean(1).interpolate('time',limit=6).ffill().bfill()
RH = df[[f'humidity_{s}' for s in TEMP_SEL]].mean(1).interpolate('time',limit=6).ffill().bfill()
Wms = df[[f'wind_spd_{s}' for s in TEMP_SEL]].mean(1).interpolate('time',limit=6).ffill().bfill()
df['temp_c'] = T
# 불쾌지수(기상청): 0.81T + 0.01·RH·(0.99T-14.3) + 46.3
df['di'] = 0.81*T + 0.01*RH*(0.99*T - 14.3) + 46.3
# 체감기온(기상청 겨울, T<=10 & 바람>=4.8km/h): 그 외엔 T
Wk = (Wms*3.6).clip(lower=4.8)
wct = 13.12 + 0.6215*T - 11.37*(Wk**0.16) + 0.3965*T*(Wk**0.16)
df['wct'] = np.where(T<=10, wct, T)
# solar/cloud/cap
df['solar_rad'] = df[[f'solar_rad_{s}' for s in SOLAR_SEL]].mean(1).interpolate('time',limit=6).ffill().bfill()
df['total_cloud'] = df[[f'total_cloud_{s}' for s in SOLAR_SEL]].mean(1).interpolate('time',limit=6).ffill().bfill()
df['cap_btmppa'] = df['cap_btmppa'].interpolate('time',limit=6).ffill().bfill()
# 달력(정규화 제외)
df['Hour_sin']=np.sin(2*np.pi*df.index.hour/24); df['Hour_cos']=np.cos(2*np.pi*df.index.hour/24)
df['Doy_sin']=np.sin(2*np.pi*df.index.dayofyear/365); df['Doy_cos']=np.cos(2*np.pi*df.index.dayofyear/365)
df['day_type']=df['day_type'].ffill().bfill()
df['is_weekend']=(df['day_type']=='weekend').astype(float); df['is_holiday']=(df['day_type']=='holiday').astype(float)
df['hour_int']=df.index.hour.astype(np.int16)
print('rows',len(df),'| di',round(df.di.min(),1),'~',round(df.di.max(),1),'| wct',round(df.wct.min(),1),'~',round(df.wct.max(),1))
FEATURES = FUTURE_FEATURES + ['Demand']
""")

code(r"""
class PatchTSTDemandDataset(Dataset):
    def __init__(self, data, hour, seq_len, pred_len, fidx, tidx, offset):
        self.data=data; self.hour=hour; self.seq_len=seq_len; self.pred_len=pred_len
        self.fidx=fidx; self.tidx=tidx; self.offset=offset
    def __len__(self): return len(self.data)-self.seq_len-self.offset-self.pred_len+1
    def __getitem__(self,i):
        past=self.data[i:i+self.seq_len]; s=i+self.seq_len+self.offset; fut=self.data[s:s+self.pred_len]
        return {'past_numeric':torch.FloatTensor(past[:,self.fidx]),'past_y':torch.FloatTensor(past[:,self.tidx:self.tidx+1]),
                'future_numeric':torch.FloatTensor(fut[:,self.fidx]),'future_y':torch.FloatTensor(fut[:,self.tidx]),
                'future_hour':torch.LongTensor(self.hour[s:s+self.pred_len])}
""")

code(r"""
class Patch_Weather_Attention(nn.Module):
    def __init__(self, q, k, h):
        super().__init__()
        self.W_Q=nn.Sequential(nn.Linear(q,h),nn.Tanh(),nn.Linear(h,h))
        self.W_K=nn.Sequential(nn.Linear(k,h),nn.Tanh(),nn.Linear(h,h)); self.s=1.0/(h**0.5)
    def forward(self, fw, pw, to):
        Q=self.W_Q(fw).unsqueeze(1); K=self.W_K(pw)
        a=F.softmax(torch.bmm(Q,K.transpose(1,2))*self.s,dim=-1); return torch.bmm(a,to).squeeze(1),a

class PatchTST_Demand_RevIN(nn.Module):
    '''외생=입력에서 전역 z-score 완료. 타깃(past_y)만 RevIN(per-instance, affine) + 출력 역정규화.'''
    def __init__(self, num_features, seq_len=336, pred_len=24, patch_len=24, stride=12,
                 d_model=256, num_heads=4, num_layers=3, d_ff=1024, dropout=0.2, revin_affine=True):
        super().__init__()
        self.patch_len=patch_len; self.stride=stride; self.pred_len=pred_len
        self.num_patches=(seq_len-patch_len)//stride+1
        self.patch_embedding=nn.Linear(patch_len*num_features,d_model)
        self.pos_embedding=nn.Parameter(torch.randn(1,self.num_patches,d_model)); self.dropout=nn.Dropout(dropout)
        enc=nn.TransformerEncoderLayer(d_model,num_heads,d_ff,dropout,batch_first=True,norm_first=True)
        self.transformer_encoder=nn.TransformerEncoder(enc,num_layers)
        nwf=num_features-1; ff=pred_len*nwf; wp=patch_len*nwf
        self.weather_attn=Patch_Weather_Attention(ff,wp,d_model)
        self.regressor=nn.Sequential(nn.Linear(d_model+ff,256),nn.LeakyReLU(0.1),nn.Dropout(dropout),nn.Linear(256,pred_len))
        self.weather_bypass=nn.Linear(ff,pred_len)
        self.revin_affine=revin_affine; self.eps=1e-5
        if revin_affine: self.revin_w=nn.Parameter(torch.ones(1)); self.revin_b=nn.Parameter(torch.zeros(1))
    def forward(self, b):
        pn=b['past_numeric'].to(DEVICE); py=b['past_y'].to(DEVICE); fn=b['future_numeric'].to(DEVICE); B=pn.shape[0]
        mean=py.mean(1,keepdim=True); std=torch.sqrt(py.var(1,keepdim=True,unbiased=False)+self.eps)
        pyn=(py-mean)/std
        if self.revin_affine: pyn=pyn*self.revin_w+self.revin_b
        xp=torch.cat([pn,pyn],-1)
        xpp=xp.unfold(1,self.patch_len,self.stride).permute(0,1,3,2).reshape(B,self.num_patches,-1)
        eo=self.transformer_encoder(self.dropout(self.patch_embedding(xpp)+self.pos_embedding))
        ff=fn.reshape(B,-1)
        xw=xp[...,:-1].unfold(1,self.patch_len,self.stride).permute(0,1,3,2).reshape(B,self.num_patches,-1)
        ctx,_=self.weather_attn(ff,xw,eo)
        on=self.regressor(torch.cat([ctx,ff],1))+self.weather_bypass(ff)
        if self.revin_affine: on=(on-self.revin_b)/self.revin_w
        return on*std.squeeze(-1)+mean.squeeze(-1), std.squeeze(-1)

class ScaledMSELoss(nn.Module):
    '''단순 MSE: per-instance std 스케일한 잔차의 제곱(=RevIN 정규화공간 MSE, LTSF 논문 표준). 평가는 MAPE.'''
    def forward(self, pred, target, std): return (((pred-target)/std)**2).mean()
""")

code(r"""
# ── prep: 외생만 전역 z-score(train fit), 시간피처·타깃 원본 ──
tr=df[df.index<TRAIN_END].copy(); va=df[(df.index>=TRAIN_END)&(df.index<VAL_END)].copy(); te=df[df.index>=VAL_END].copy()
scaler=StandardScaler(); tr[EXOG]=scaler.fit_transform(tr[EXOG]); va[EXOG]=scaler.transform(va[EXOG]); te[EXOG]=scaler.transform(te[EXOG])
joblib.dump(scaler, f'{OUT_DIR}/scaler_exog.pkl')
FIDX=[FEATURES.index(c) for c in FUTURE_FEATURES]; TIDX=FEATURES.index('Demand'); NF=len(FIDX)+1
A_TR=tr[FEATURES].values; A_VA=va[FEATURES].values; A_TE=te[FEATURES].values
HR=lambda x:x['hour_int'].values.astype(np.int64); H_TR,H_VA,H_TE=HR(tr),HR(va),HR(te)
print('NF',NF,'(외생',len(EXOG),'+시간',len(TIME),'+타깃) | train',len(tr),'val',len(va),'test',len(te))

def train_one(hname, off):
    crit=ScaledMSELoss(); m=PatchTST_Demand_RevIN(NF,pred_len=PRED_LEN,**HP).to(DEVICE)
    opt=torch.optim.AdamW(m.parameters(),lr=LR,weight_decay=1e-5)
    sch=torch.optim.lr_scheduler.ReduceLROnPlateau(opt,'min',factor=0.5,patience=4)
    USE_AMP=(DEVICE=='cuda'); gs=torch.amp.GradScaler('cuda',enabled=USE_AMP) if USE_AMP else None
    tl=DataLoader(PatchTSTDemandDataset(A_TR,H_TR,HP['seq_len'],PRED_LEN,FIDX,TIDX,off),batch_size=BATCH_SIZE,shuffle=True,drop_last=True)
    vl=DataLoader(PatchTSTDemandDataset(A_VA,H_VA,HP['seq_len'],PRED_LEN,FIDX,TIDX,off),batch_size=BATCH_SIZE)
    best=float('inf'); bad=0; path=f'{OUT_DIR}/best_patchtst_landdemand_{hname}.pth'
    print(f'== {hname} off={off} | feats={NF} train={len(tl.dataset)} val={len(vl.dataset)} AMP={USE_AMP}')
    for ep in range(1,EPOCHS+1):
        m.train()
        for b in tqdm(tl,desc=f'{hname} ep{ep}',leave=False):
            opt.zero_grad()
            if USE_AMP:
                with torch.amp.autocast('cuda'): pr,st=m(b); ls=crit(pr,b['future_y'].to(DEVICE),st)
                gs.scale(ls).backward(); gs.unscale_(opt); torch.nn.utils.clip_grad_norm_(m.parameters(),1.0); gs.step(opt); gs.update()
            else:
                pr,st=m(b); ls=crit(pr,b['future_y'].to(DEVICE),st); ls.backward()
                torch.nn.utils.clip_grad_norm_(m.parameters(),1.0); opt.step()
        m.eval(); v=0.0
        with torch.no_grad():
            for b in vl: pr,st=m(b); v+=crit(pr,b['future_y'].to(DEVICE),st).item()
        v/=max(len(vl),1); sch.step(v)
        if v<best: best=v; bad=0; torch.save(m.state_dict(),path)
        else:
            bad+=1
            if bad>=PATIENCE: print(f'  early stop @ ep{ep}'); break
    return best
""")

code(r"""
def mape(a,p):
    a,p=np.asarray(a,float),np.asarray(p,float); k=(a>0)&np.isfinite(a)&np.isfinite(p)
    return float(np.mean(np.abs(a[k]-p[k])/a[k])*100) if k.any() else np.nan
@torch.no_grad()
def perfect_eval(path, off):
    m=PatchTST_Demand_RevIN(NF,pred_len=PRED_LEN,**HP).to(DEVICE); m.load_state_dict(torch.load(path,map_location=DEVICE)); m.eval()
    ld=DataLoader(PatchTSTDemandDataset(A_TE,H_TE,HP['seq_len'],PRED_LEN,FIDX,TIDX,off),batch_size=256); P,Aa,Hh=[],[],[]
    for b in ld: pr,_=m(b); P.append(pr.cpu().numpy()); Aa.append(b['future_y'].numpy()); Hh.append(b['future_hour'].numpy())
    P=np.clip(np.concatenate(P).ravel(),0,None); Aa=np.concatenate(Aa).ravel(); Hh=np.concatenate(Hh).ravel(); day=(Hh>=9)&(Hh<=15)
    return mape(Aa,P), mape(Aa[day],P[day])

META=dict(model='Cross-Attention PatchTST + RevIN(타깃) + 전역 z-score(외생)',
          target='real_demand_land', loss='ScaledMSE(단순, std스케일=정규화공간 MSE)', revin=True, revin_affine=True, HP=HP, PRED_LEN=PRED_LEN,
          EXOG=EXOG, TIME=TIME, FUTURE_FEATURES=FUTURE_FEATURES, TEMP_SEL=TEMP_SEL, SOLAR_SEL=SOLAR_SEL,
          comfort=dict(di='0.81T+0.01RH(0.99T-14.3)+46.3', wct='기상청 겨울 wind chill(T<=10 & W>=4.8km/h), 그외 T', wind_kmh='m/s*3.6'),
          scaler='scaler_exog.pkl (StandardScaler, EXOG만, train fit)', TRAIN_END=TRAIN_END, VAL_END=VAL_END, horizons={})
print('지평별 학습 + perfect:')
for hname, off in HORIZONS.items():
    best=train_one(hname, off); mp,mpd=perfect_eval(f'{OUT_DIR}/best_patchtst_landdemand_{hname}.pth', off)
    META['horizons'][hname]=dict(offset=off, val_MAE=round(best,5), perfect_MAPE=round(mp,3), perfect_MAPE_day=round(mpd,3),
                                 weight=f'best_patchtst_landdemand_{hname}.pth')
    joblib.dump(META, f'{OUT_DIR}/metadata_landdemand_final2.pkl')
    print(f'  {hname:>3}: perfect {mp:5.2f} / 낮 {mpd:5.2f}')
print('\nmetadata_landdemand_final2.pkl 저장. perfect=상한 — 판정은 repo honest 하니스.')
""")

code(r"""
import shutil
shutil.make_archive('/content/landdemand_final2','zip',OUT_DIR)
print('zip -> /content/landdemand_final2.zip (15가중치 + scaler_exog + metadata_final2)')
try:
    from google.colab import files; files.download('/content/landdemand_final2.zip')
except Exception: pass
""")

md(r"""
## 산출물 적용
`out/` 전체를 repo `5. land_demand_forecaster/training/landdemand_final2/` 에 풀기:
```
best_patchtst_landdemand_{D1..D15}.pth + scaler_exog.pkl + metadata_landdemand_final2.pkl
```
그 뒤 Claude 가 honest 하니스로 **전 15지평 × 낮/밤 × 계절 vs LGBM·하이브리드** 비교 → 최종 채택 결정.
하니스는 metadata 의 EXOG/TIME/TEMP_SEL·comfort 공식으로 forecast_horizon 에서 동일 재구성한다.
""")


def main():
    nb = {"cells": [{"cell_type": k, "metadata": {}, "source": s.splitlines(keepends=True),
                     **({"outputs": [], "execution_count": None} if k == "code" else {})}
                    for k, s in CELLS],
          "metadata": {"kernelspec": {"display_name": "Python 3", "name": "python3"},
                       "language_info": {"name": "python"}, "accelerator": "GPU",
                       "colab": {"provenance": []}}, "nbformat": 4, "nbformat_minor": 5}
    OUT.write_text(json.dumps(nb, ensure_ascii=False, indent=1), encoding="utf-8")
    print("wrote", OUT, "| cells:", len(CELLS))


if __name__ == "__main__":
    main()

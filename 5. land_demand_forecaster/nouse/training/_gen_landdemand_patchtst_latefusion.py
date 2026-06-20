# -*- coding: utf-8 -*-
"""train_landdemand_patchtst_colab_latefusion.ipynb 생성기 — ★시간피처 Late Fusion(final2 기반).

배경: 사용자 설계 — "시간피처는 다른 피처와 섞이면 안 된다(오염 금지). 깨끗·중요하게 들어가야."
final2 는 시간피처를 weather·타깃과 한 패치임베딩에 섞어 넣었음 → 본 변형은 분리한다:
  1. 백본(PatchTST + RevIN + 교차어텐션) = weather(6=temp_c·di·wct·solar·cloud·cap) + 타깃 만 패치화(시간 미오염).
  2. 시간피처(Hour/Doy sin·cos·is_weekend·is_holiday) = 패치화 없이 미래 '시점값' 그대로 → 전용 MLP(time_proj).
  3. Late Fusion: cat([백본 feat, time_proj]) → final_linear (RevIN 정규화공간) → 역정규화.
     weather_bypass = weather 전용 잔차경로(시간 미포함).
final2 와의 유일한 차이 = 위 시간 분리(데이터·전처리·HP·손실 전부 동일). 증강(aug)은 honest 악화로 기각됨(§9-5).
지평: ★D+1~7만(D+8~15=LGBM, 06-19 확정). 산출: landdemand_latefusion/.
판정: repo honest 하니스 `_ab_latefusion_eval.py`(forecast_horizon 실예보).
"""
import json
from pathlib import Path

OUT = Path(__file__).resolve().parent / "train_landdemand_patchtst_colab_latefusion.ipynb"
CELLS = []
def md(s):  CELLS.append(("markdown", s.strip("\n")))
def code(s): CELLS.append(("code", s.strip("\n")))

md(r"""
# 전국 수요 PatchTST — ★시간피처 Late Fusion (final2 기반)

**설계(사용자)**: 시간피처는 weather와 섞지 않는다(오염 금지). 백본은 weather+타깃만, 시간은 전용 경로로 늦게 합류.
- 백본: weather(6)+타깃(RevIN) 패치화·교차어텐션 → feat
- 시간: 미래 시점값 그대로 → 전용 MLP(time_proj)
- Late Fusion: cat([feat, time_proj]) → final_linear(정규화공간) → 역RevIN

final2 와 데이터·전처리·HP·손실 동일, **차이는 시간 분리뿐**. 지평 **D+1~7**.
**입력**: `demand_raw_land.csv`. **산출**: `landdemand_latefusion/`.
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
HORIZONS = {f'D{n}': (n-1)*24 for n in range(1, 8)}   # ★D+1~7만(D+8~15=LGBM)
TRAIN_END = '2025-01-01'; VAL_END = '2026-01-01'
TEMP_SEL  = ['wonju', 'seosan', 'pohang', 'yeonggwang']   # 대관령 제외(무인)
SOLAR_SEL = ['seosan', 'yeonggwang']
HP = dict(seq_len=336, patch_len=24, stride=12, d_model=256, num_heads=4, num_layers=3, d_ff=1024, dropout=0.2)
FUSION = dict(feat_dim=256, time_dim=128)   # Late Fusion 분기 폭
EPOCHS = 80; BATCH_SIZE = 256; LR = 1e-3; PATIENCE = 12

EXOG = ['temp_c', 'di', 'wct', 'solar_rad', 'total_cloud', 'cap_btmppa']   # 전역 z-score 대상(백본 입력)
TIME = ['Hour_sin', 'Hour_cos', 'Doy_sin', 'Doy_cos', 'is_weekend', 'is_holiday']   # 정규화 제외(시간 전용경로)
FUTURE_FEATURES = EXOG + TIME    # 열 순서 = EXOG(앞6)·TIME(뒤6) — 모델이 [:, :, :6]/[:, :, 6:] 로 분리
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
df['di'] = 0.81*T + 0.01*RH*(0.99*T - 14.3) + 46.3
Wk = (Wms*3.6).clip(lower=4.8)
wct = 13.12 + 0.6215*T - 11.37*(Wk**0.16) + 0.3965*T*(Wk**0.16)
df['wct'] = np.where(T<=10, wct, T)
df['solar_rad'] = df[[f'solar_rad_{s}' for s in SOLAR_SEL]].mean(1).interpolate('time',limit=6).ffill().bfill()
df['total_cloud'] = df[[f'total_cloud_{s}' for s in SOLAR_SEL]].mean(1).interpolate('time',limit=6).ffill().bfill()
df['cap_btmppa'] = df['cap_btmppa'].interpolate('time',limit=6).ffill().bfill()
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

class PatchTST_LateFusion(nn.Module):
    '''백본=weather(n_exog)+타깃(RevIN)만 패치화(시간 미오염). 시간=전용 MLP→late concat→final_linear.'''
    def __init__(self, n_exog=6, n_time=6, seq_len=336, pred_len=24, patch_len=24, stride=12,
                 d_model=256, num_heads=4, num_layers=3, d_ff=1024, dropout=0.2,
                 feat_dim=256, time_dim=128, revin_affine=True):
        super().__init__()
        self.n_exog=n_exog; self.n_time=n_time; self.patch_len=patch_len; self.stride=stride; self.pred_len=pred_len
        self.num_patches=(seq_len-patch_len)//stride+1
        nb=n_exog+1
        self.patch_embedding=nn.Linear(patch_len*nb, d_model)
        self.pos_embedding=nn.Parameter(torch.randn(1,self.num_patches,d_model)); self.dropout=nn.Dropout(dropout)
        enc=nn.TransformerEncoderLayer(d_model,num_heads,d_ff,dropout,batch_first=True,norm_first=True)
        self.transformer_encoder=nn.TransformerEncoder(enc,num_layers)
        wf=pred_len*n_exog; wp=patch_len*n_exog
        self.weather_attn=Patch_Weather_Attention(wf,wp,d_model)
        self.backbone_head=nn.Sequential(nn.Linear(d_model+wf, feat_dim), nn.LeakyReLU(0.1), nn.Dropout(dropout))
        self.time_proj=nn.Sequential(nn.Linear(pred_len*n_time, time_dim), nn.GELU(), nn.Dropout(dropout))
        self.final_linear=nn.Linear(feat_dim+time_dim, pred_len)
        self.weather_bypass=nn.Linear(wf, pred_len)
        self.revin_affine=revin_affine; self.eps=1e-5
        if revin_affine: self.revin_w=nn.Parameter(torch.ones(1)); self.revin_b=nn.Parameter(torch.zeros(1))
    def forward(self, b):
        pn=b['past_numeric'].to(DEVICE); py=b['past_y'].to(DEVICE); fn=b['future_numeric'].to(DEVICE); B=pn.shape[0]
        past_x=pn[:,:,:self.n_exog]; fut_x=fn[:,:,:self.n_exog]; time_feat=fn[:,:,self.n_exog:]
        mean=py.mean(1,keepdim=True); std=torch.sqrt(py.var(1,keepdim=True,unbiased=False)+self.eps); pyn=(py-mean)/std
        if self.revin_affine: pyn=pyn*self.revin_w+self.revin_b
        xp=torch.cat([past_x,pyn],-1)                                  # (B,seq,n_exog+1) 시간 없음
        xpp=xp.unfold(1,self.patch_len,self.stride).permute(0,1,3,2).reshape(B,self.num_patches,-1)
        eo=self.transformer_encoder(self.dropout(self.patch_embedding(xpp)+self.pos_embedding))
        wf_flat=fut_x.reshape(B,-1)
        xw=past_x.unfold(1,self.patch_len,self.stride).permute(0,1,3,2).reshape(B,self.num_patches,-1)
        ctx,_=self.weather_attn(wf_flat,xw,eo)
        feat=self.backbone_head(torch.cat([ctx,wf_flat],1))           # 백본 feat (시간 미오염)
        tproj=self.time_proj(time_feat.reshape(B,-1))                 # 시간 전용 경로
        on=self.final_linear(torch.cat([feat,tproj],1))+self.weather_bypass(wf_flat)
        if self.revin_affine: on=(on-self.revin_b)/self.revin_w
        return on*std.squeeze(-1)+mean.squeeze(-1), std.squeeze(-1)

class ScaledMSELoss(nn.Module):
    def forward(self, pred, target, std): return (((pred-target)/std)**2).mean()
""")

code(r"""
# ── prep: 외생만 전역 z-score(train fit), 시간피처·타깃 원본 ──
tr=df[df.index<TRAIN_END].copy(); va=df[(df.index>=TRAIN_END)&(df.index<VAL_END)].copy(); te=df[df.index>=VAL_END].copy()
scaler=StandardScaler(); tr[EXOG]=scaler.fit_transform(tr[EXOG]); va[EXOG]=scaler.transform(va[EXOG]); te[EXOG]=scaler.transform(te[EXOG])
joblib.dump(scaler, f'{OUT_DIR}/scaler_exog.pkl')
FIDX=[FEATURES.index(c) for c in FUTURE_FEATURES]; TIDX=FEATURES.index('Demand')
N_EXOG=len(EXOG); N_TIME=len(TIME)
A_TR=tr[FEATURES].values; A_VA=va[FEATURES].values; A_TE=te[FEATURES].values
HR=lambda x:x['hour_int'].values.astype(np.int64); H_TR,H_VA,H_TE=HR(tr),HR(va),HR(te)
print('n_exog',N_EXOG,'n_time',N_TIME,'| train',len(tr),'val',len(va),'test',len(te))

def make_model():
    return PatchTST_LateFusion(n_exog=N_EXOG, n_time=N_TIME, pred_len=PRED_LEN, **HP, **FUSION).to(DEVICE)

def train_one(hname, off):
    crit=ScaledMSELoss(); m=make_model()
    opt=torch.optim.AdamW(m.parameters(),lr=LR,weight_decay=1e-5)
    sch=torch.optim.lr_scheduler.ReduceLROnPlateau(opt,'min',factor=0.5,patience=4)
    USE_AMP=(DEVICE=='cuda'); gs=torch.amp.GradScaler('cuda',enabled=USE_AMP) if USE_AMP else None
    tl=DataLoader(PatchTSTDemandDataset(A_TR,H_TR,HP['seq_len'],PRED_LEN,FIDX,TIDX,off),batch_size=BATCH_SIZE,shuffle=True,drop_last=True)
    vl=DataLoader(PatchTSTDemandDataset(A_VA,H_VA,HP['seq_len'],PRED_LEN,FIDX,TIDX,off),batch_size=BATCH_SIZE)
    best=float('inf'); bad=0; path=f'{OUT_DIR}/best_patchtst_landdemand_{hname}.pth'
    print(f'== {hname} off={off} | train={len(tl.dataset)} val={len(vl.dataset)} AMP={USE_AMP}')
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
    m=make_model(); m.load_state_dict(torch.load(path,map_location=DEVICE)); m.eval()
    ld=DataLoader(PatchTSTDemandDataset(A_TE,H_TE,HP['seq_len'],PRED_LEN,FIDX,TIDX,off),batch_size=256); P,Aa,Hh=[],[],[]
    for b in ld: pr,_=m(b); P.append(pr.cpu().numpy()); Aa.append(b['future_y'].numpy()); Hh.append(b['future_hour'].numpy())
    P=np.clip(np.concatenate(P).ravel(),0,None); Aa=np.concatenate(Aa).ravel(); Hh=np.concatenate(Hh).ravel(); day=(Hh>=9)&(Hh<=15)
    return mape(Aa,P), mape(Aa[day],P[day])

META=dict(model='PatchTST Late Fusion (백본=weather+타깃, 시간=전용경로 late concat) + RevIN + 전역 z-score(외생)',
          target='real_demand_land', loss='ScaledMSE(단순, std스케일)', revin=True, revin_affine=True, HP=HP, FUSION=FUSION, PRED_LEN=PRED_LEN,
          EXOG=EXOG, TIME=TIME, FUTURE_FEATURES=FUTURE_FEATURES, TEMP_SEL=TEMP_SEL, SOLAR_SEL=SOLAR_SEL,
          comfort=dict(di='0.81T+0.01RH(0.99T-14.3)+46.3', wct='기상청 겨울 wind chill(T<=10 & W>=4.8km/h), 그외 T', wind_kmh='m/s*3.6'),
          fusion_note='백본 입력=EXOG(6)+타깃만(시간 미오염). 시간=미래 시점값 그대로 time_proj→final_linear late concat.',
          scaler='scaler_exog.pkl (StandardScaler, EXOG만, train fit)', TRAIN_END=TRAIN_END, VAL_END=VAL_END, horizons={})
print('지평별 학습 + perfect:')
for hname, off in HORIZONS.items():
    best=train_one(hname, off); mp,mpd=perfect_eval(f'{OUT_DIR}/best_patchtst_landdemand_{hname}.pth', off)
    META['horizons'][hname]=dict(offset=off, val_MAE=round(best,5), perfect_MAPE=round(mp,3), perfect_MAPE_day=round(mpd,3),
                                 weight=f'best_patchtst_landdemand_{hname}.pth')
    joblib.dump(META, f'{OUT_DIR}/metadata_landdemand_latefusion.pkl')
    print(f'  {hname:>3}: perfect {mp:5.2f} / 낮 {mpd:5.2f}')
print('\nmetadata_landdemand_latefusion.pkl 저장. ★판정은 repo honest 하니스 _ab_latefusion_eval.py.')
""")

code(r"""
import shutil
shutil.make_archive('/content/landdemand_latefusion','zip',OUT_DIR)
print('zip -> /content/landdemand_latefusion.zip (7가중치 D+1~7 + scaler_exog + metadata_latefusion)')
try:
    from google.colab import files; files.download('/content/landdemand_latefusion.zip')
except Exception: pass
""")

md(r"""
## 산출물 적용
`out/` 전체를 repo `5. land_demand_forecaster/training/landdemand_latefusion/` 에 풀기:
```
best_patchtst_landdemand_{D1..D7}.pth + scaler_exog.pkl + metadata_landdemand_latefusion.pkl
```
그 뒤 Claude 가 honest 하니스 `_ab_latefusion_eval.py`(forecast_horizon 실예보)로 **latefusion vs final2 vs LGBM**
D+1~7 낮/밤×계절 비교 → 야간 개선 여부·채택 결정(시간 분리가 밤을 끌어올렸는가).
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

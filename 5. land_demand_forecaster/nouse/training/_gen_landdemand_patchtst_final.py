# -*- coding: utf-8 -*-
"""train_landdemand_patchtst_colab_final.ipynb 생성기 — 최종 후보(15모델 + lag앵커 + 단순MAE).

기존 _amp(15모델 direct, AsymMSE) 에서 두 가지 변경:
  ① lag_week 앵커 추가(정직가드): k = off+24 이상 최소 168배수 → D+1~7=lag168, D+8~14=lag336, D+15=lag504.
     (cross-attention 채널로 투입. RevIN이 뺀 절대레벨을 lag가 재주입 = 시너지. honest 누수 0.)
  ② 손실·조기종료 = **단순 MAE**(per-instance std 스케일, 대칭, α 없음).
피처가 지평별(lag_week k 상이)이라 데이터 prep을 지평 루프 안으로. metadata(지평별 k·피처·hp) 저장.

산출: best_patchtst_landdemand_{D1..D15}.pth + {Dn}_scaler.pkl + metadata_landdemand_final.pkl (+ perfect metrics).
사용법: python "5. land_demand_forecaster/training/_gen_landdemand_patchtst_final.py"
입력 CSV: demand_raw_land.csv (동일).
"""
import json
from pathlib import Path

OUT = Path(__file__).resolve().parent / "train_landdemand_patchtst_colab_final.ipynb"
CELLS = []
def md(s):  CELLS.append(("markdown", s.strip("\n")))
def code(s): CELLS.append(("code", s.strip("\n")))

md(r"""
# 전국 수요 PatchTST 최종 후보 — 15모델 direct + lag앵커 + 단순 MAE

기존 _amp 대비: **① lag_week 앵커(정직가드 168/336/504)** ② **손실=단순 MAE**(α 제거).
- lag_week k = off+24 이상 최소 168배수: **D+1~7=lag168 · D+8~14=lag336 · D+15=lag504** (원점서 known, 누수 0).
- RevIN·seq336·입력피처·지점선택·AMP·batch256 유지. 피처가 지평별이라 prep을 지평 루프 안에서.

**입력**: `demand_raw_land.csv`. **산출**: `_D1.._D15.pth` + 지평별 scaler + `metadata_landdemand_final.pkl`.
""")

code(r"""
import numpy as np, pandas as pd, torch, os, math, json, joblib
import torch.nn as nn, torch.nn.functional as F
from torch.utils.data import Dataset, DataLoader
from sklearn.preprocessing import MinMaxScaler
from tqdm.auto import tqdm
DEVICE = 'cuda' if torch.cuda.is_available() else 'cpu'
print('DEVICE =', DEVICE)
""")

code(r"""
CSV_PATH = '/content/demand_raw_land.csv'
OUT_DIR  = '/content/out'; os.makedirs(OUT_DIR, exist_ok=True)
PRED_LEN = 24
HORIZONS = {f'D{n}': (n-1)*24 for n in range(1, 16)}     # D+1..D+15
TRAIN_END = '2025-01-01'; VAL_END = '2026-01-01'
STATIONS  = ['daegwallyeong', 'wonju', 'seosan', 'pohang', 'yeonggwang']
SOLAR_SEL = ['seosan', 'yeonggwang']; WIND_SEL = ['daegwallyeong', 'pohang']
HP = dict(seq_len=336, patch_len=24, stride=12, d_model=256, num_heads=4, num_layers=3, d_ff=1024, dropout=0.2)
EPOCHS = 80; BATCH_SIZE = 256; LR = 1e-3; PATIENCE = 12

def weekly_k(off):
    return 168 * math.ceil((off + 24) / 168)     # D1~7→168, D8~14→336, D15→504
print('lag_week k:', {h: weekly_k(o) for h, o in HORIZONS.items()})
""")

code(r"""
raw = pd.read_csv(CSV_PATH); raw['timestamp'] = pd.to_datetime(raw['timestamp'])
raw = raw.set_index('timestamp').sort_index()
idx = pd.date_range(raw.index.min(), raw.index.max(), freq='h'); raw = raw.reindex(idx); raw.index.name='timestamp'
raw['temp_c']=raw[[f'temp_c_{s}' for s in STATIONS]].mean(1)
raw['solar_rad']=raw[[f'solar_rad_{s}' for s in SOLAR_SEL]].mean(1)
raw['wind_spd']=raw[[f'wind_spd_{s}' for s in WIND_SEL]].mean(1)
raw['total_cloud']=raw[[f'total_cloud_{s}' for s in SOLAR_SEL]].mean(1)
raw['midlow_cloud']=raw[[f'midlow_cloud_{s}' for s in SOLAR_SEL]].mean(1)
raw.loc[raw['real_demand_land']==0,'real_demand_land']=np.nan
raw['Demand']=raw['real_demand_land'].interpolate('time').ffill().bfill()
nc=['temp_c','solar_rad','wind_spd','total_cloud','midlow_cloud','cap_btmppa']
raw[nc]=raw[nc].interpolate('time',limit=6).ffill().bfill()
raw['day_type']=raw['day_type'].ffill().bfill()
raw['Hour_sin']=np.sin(2*np.pi*raw.index.hour/24); raw['Hour_cos']=np.cos(2*np.pi*raw.index.hour/24)
raw['Doy_sin']=np.sin(2*np.pi*raw.index.dayofyear/365); raw['Doy_cos']=np.cos(2*np.pi*raw.index.dayofyear/365)
raw['is_weekend']=(raw['day_type']=='weekend').astype(float); raw['is_holiday']=(raw['day_type']=='holiday').astype(float)
raw['hour_int']=raw.index.hour.astype(np.int16)
print('rows', len(raw))

BASE_FF = ['temp_c','solar_rad','wind_spd','total_cloud','midlow_cloud','cap_btmppa',
           'Hour_sin','Hour_cos','Doy_sin','Doy_cos','is_weekend','is_holiday']
def feature_cols(df, off):
    k = weekly_k(off); df[f'lag_week_{off}'] = df['Demand'].shift(k)   # 정직가드: k≥off+24
    return BASE_FF + [f'lag_week_{off}']
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
""")

code(r"""
class ScaledMAELoss(nn.Module):
    '''단순 MAE: per-instance std 스케일한 |잔차|. 대칭, α 없음.'''
    def forward(self, pred, target, std):
        return (torch.abs(pred - target) / std).mean()
""")

code(r"""
def prep(off):
    cols = feature_cols(raw, off); feats = cols + ['Demand']
    sub = raw.dropna(subset=[f'lag_week_{off}']).copy()
    tr=sub[sub.index<TRAIN_END].copy(); va=sub[(sub.index>=TRAIN_END)&(sub.index<VAL_END)].copy(); te=sub[sub.index>=VAL_END].copy()
    sc=MinMaxScaler((0,1))
    tr[cols]=sc.fit_transform(tr[cols]); va[cols]=sc.transform(va[cols]); te[cols]=sc.transform(te[cols])
    fidx=[feats.index(c) for c in cols]; tidx=feats.index('Demand')
    hr=lambda x:x['hour_int'].values.astype(np.int64)
    return tr[feats].values, va[feats].values, te[feats].values, hr(tr),hr(va),hr(te), sc, fidx, tidx, cols

def train_one(hname, off):
    a_tr,a_va,a_te,h_tr,h_va,h_te,sc,fidx,tidx,cols = prep(off)
    nf=len(fidx)+1; crit=ScaledMAELoss()
    m=PatchTST_Demand_RevIN(nf, pred_len=PRED_LEN, **HP).to(DEVICE)
    opt=torch.optim.AdamW(m.parameters(),lr=LR,weight_decay=1e-5)
    sch=torch.optim.lr_scheduler.ReduceLROnPlateau(opt,'min',factor=0.5,patience=4)
    USE_AMP=(DEVICE=='cuda'); gs=torch.amp.GradScaler('cuda',enabled=USE_AMP) if USE_AMP else None
    tl=DataLoader(PatchTSTDemandDataset(a_tr,h_tr,HP['seq_len'],PRED_LEN,fidx,tidx,off),batch_size=BATCH_SIZE,shuffle=True,drop_last=True)
    vl=DataLoader(PatchTSTDemandDataset(a_va,h_va,HP['seq_len'],PRED_LEN,fidx,tidx,off),batch_size=BATCH_SIZE)
    best=float('inf'); bad=0; path=f'{OUT_DIR}/best_patchtst_landdemand_{hname}.pth'
    print(f'== {hname} off={off} lag{weekly_k(off)} | feats={nf} train={len(tl.dataset)} val={len(vl.dataset)} AMP={USE_AMP}')
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
    joblib.dump(sc, f'{OUT_DIR}/{hname}_scaler.pkl')
    return best, cols, a_te, h_te, fidx, tidx, nf, path
""")

code(r"""
def mape(a,p):
    a,p=np.asarray(a,float),np.asarray(p,float); k=(a>0)&np.isfinite(a)&np.isfinite(p)
    return float(np.mean(np.abs(a[k]-p[k])/a[k])*100) if k.any() else np.nan

@torch.no_grad()
def perfect_eval(path, a_te, h_te, fidx, tidx, off, nf):
    m=PatchTST_Demand_RevIN(nf,pred_len=PRED_LEN,**HP).to(DEVICE); m.load_state_dict(torch.load(path,map_location=DEVICE)); m.eval()
    ld=DataLoader(PatchTSTDemandDataset(a_te,h_te,HP['seq_len'],PRED_LEN,fidx,tidx,off),batch_size=256)
    P,A,H=[],[],[]
    for b in ld: pr,_=m(b); P.append(pr.cpu().numpy()); A.append(b['future_y'].numpy()); H.append(b['future_hour'].numpy())
    P=np.clip(np.concatenate(P).ravel(),0,None); A=np.concatenate(A).ravel(); H=np.concatenate(H).ravel(); day=(H>=9)&(H<=15)
    return mape(A,P), mape(A[day],P[day])

# ── metadata: 서빙/평가가 지평별 lag_week 재구성에 필요한 모든 것 ──
META = dict(model='Cross-Attention PatchTST + RevIN', loss='ScaledMAE(단순, std스케일, α없음)',
            target='real_demand_land', revin=True, revin_affine=True, HP=HP, PRED_LEN=PRED_LEN,
            base_future_features=BASE_FF, anchor='lag_week (지평별 정직가드)',
            STATIONS=STATIONS, SOLAR_SEL=SOLAR_SEL, WIND_SEL=WIND_SEL,
            TRAIN_END=TRAIN_END, VAL_END=VAL_END, horizons={})

print('지평별 학습 + perfect(상한):')
for hname, off in HORIZONS.items():
    best, cols, a_te, h_te, fidx, tidx, nf, path = train_one(hname, off)
    mp, mpd = perfect_eval(path, a_te, h_te, fidx, tidx, off, nf)
    META['horizons'][hname] = dict(offset=off, weekly_k=weekly_k(off), future_features=cols,
                                   val_MAE=round(best,5), perfect_MAPE=round(mp,3), perfect_MAPE_day=round(mpd,3),
                                   scaler=f'{hname}_scaler.pkl', weight=f'best_patchtst_landdemand_{hname}.pth')
    joblib.dump(META, f'{OUT_DIR}/metadata_landdemand_final.pkl')
    print(f'  {hname:>3}: lag{weekly_k(off)} perfect {mp:5.2f} / 낮 {mpd:5.2f}')
print('\nmetadata_landdemand_final.pkl 저장. perfect=상한 — 판정은 repo honest 하니스.')
""")

code(r"""
import shutil
shutil.make_archive('/content/landdemand_final','zip',OUT_DIR)
print('zip -> /content/landdemand_final.zip (15가중치 + 지평별 scaler + metadata_final)')
try:
    from google.colab import files; files.download('/content/landdemand_final.zip')
except Exception: pass
""")

md(r"""
## 산출물 적용
`out/` 전체를 repo `5. land_demand_forecaster/training/landdemand_final/` 에 풀기:
```
best_patchtst_landdemand_{D1..D15}.pth + {Dn}_scaler.pkl + metadata_landdemand_final.pkl
```
그 뒤 Claude 가 honest 하니스로 **LGBM·하이브리드와 전 지평 동일창 비교**(낮/밤·계절) → 최종 채택 결정.
metadata 의 horizons[Dn].weekly_k 로 서빙·평가가 lag_week 를 정직 재구성한다.
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

# -*- coding: utf-8 -*-
"""train_landdemand_sweep_colab.ipynb 생성기 (5-B3: D+5/10/15 HP·피처 딥 스윕).

목적: PatchTST를 장지평(D+5/10/15)에서 LGBM에 근접/추월시킬 HP·피처를 아쉬움없이 탐색.
핵심 가설: 장지평은 예보 기상이 망가져(7-D 병목) 기상 의존이 독 → **자기회귀 앵커 피처
(lag_week, 정직가드)** 가 진짜 지렛대(LGBM이 장지평 이기는 무기). cross-attention이라 lag를
채널로 넣으면 어텐션이 활용 + RevIN이 뺀 절대레벨을 lag가 재주입(시너지).

지평 = D+5(off96)·D+10(off216)·D+15(off336) 만. 각 config가 이 3개를 학습.
피처셋: base / anchor(+lag_week) / anchor2(+lag_week,lag_2week) / perstation(지점raw).
  lag_week 정직가드: k = off+24 이상의 최소 주배수(168배수) → D5=168·D10=336·D15=504 (원점서 known).
HP축: stride·seq_len·patch_len·d_model/layers·dropout.  손실: mae·mse·huber (대칭, std스케일).
선정: val 아닌 **repo honest 하니스(D5/10/15 낮밤분리) vs LGBM·하이브리드**.

산출: out/{config}_{horizon}.pth + {config}_{horizon}_scaler.pkl + registry.json (+ perfect metrics).
사용법: python "5. land_demand_forecaster/training/_gen_landdemand_sweep.py"
입력 CSV: demand_raw_land.csv (5-B 동일).
"""
import json
from pathlib import Path

OUT = Path(__file__).resolve().parent / "train_landdemand_sweep_colab.ipynb"
CELLS = []
def md(s):  CELLS.append(("markdown", s.strip("\n")))
def code(s): CELLS.append(("code", s.strip("\n")))

md(r"""
# 전국 수요 PatchTST — D+5/10/15 HP·피처 딥 스윕 (5-B3)

장지평(D+5/10/15)에서 PatchTST를 끌어올릴 HP·피처를 탐색. **가설: 장지평 지렛대=자기회귀 앵커
(lag_week, 정직가드)**. config 리스트를 한 노트북에서 루프 학습 → repo honest 하니스로 선정.

**입력**: `demand_raw_land.csv`(5-B 동일). **산출**: config×horizon 가중치 + scaler + registry.json.
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
HORIZONS = {'D5': 96, 'D10': 216, 'D15': 336}     # off (h). lag_week k = off+24 이상 최소 168배수
TRAIN_END = '2025-01-01'; VAL_END = '2026-01-01'
STATIONS  = ['daegwallyeong', 'wonju', 'seosan', 'pohang', 'yeonggwang']
SOLAR_SEL = ['seosan', 'yeonggwang']; WIND_SEL = ['daegwallyeong', 'pohang']
EPOCHS = 70; BATCH_SIZE = 256; LR = 1e-3; PATIENCE = 10

DEFAULT_HP = dict(seq_len=336, patch_len=24, stride=12, d_model=256, num_heads=4,
                  num_layers=3, d_ff=1024, dropout=0.2)

# ── 스윕 config: (name, feature_set, hp_override, loss) ──
CONFIGS = [
    ('base',          'base',       {},                              'mae'),
    ('anchor',        'anchor',     {},                              'mae'),   # ★ lag_week
    ('anchor2',       'anchor2',    {},                              'mae'),   # +lag_2week
    ('anchor_s6',     'anchor',     {'stride': 6},                   'mae'),
    ('anchor_seq504', 'anchor',     {'seq_len': 504},                'mae'),
    ('anchor_seq720', 'anchor',     {'seq_len': 720},                'mae'),
    ('anchor_pl48',   'anchor',     {'patch_len': 48, 'stride': 24}, 'mae'),
    ('anchor_big',    'anchor',     {'d_model': 384, 'num_layers': 4},'mae'),
    ('anchor_drop3',  'anchor',     {'dropout': 0.3},                'mae'),
    ('anchor_mse',    'anchor',     {},                              'mse'),
    ('anchor_huber',  'anchor',     {},                              'huber'),
    ('anchor_combo',  'anchor',     {'seq_len': 504, 'stride': 6},   'mae'),
    ('base_seq504',   'base',       {'seq_len': 504},                'mae'),   # 앵커없이 맥락만(분리)
    ('perstation',    'perstation', {},                              'mae'),
]
print(len(CONFIGS), 'configs ×', len(HORIZONS), 'horizons =', len(CONFIGS)*len(HORIZONS), 'trains')
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
wxcols=['temp_c','solar_rad','wind_spd','total_cloud','midlow_cloud','cap_btmppa']
wxcols += [f'{w}_{s}' for s in STATIONS for w in ('temp_c',)] + [f'solar_rad_{s}' for s in SOLAR_SEL]
wxcols += [f'total_cloud_{s}' for s in SOLAR_SEL] + [f'midlow_cloud_{s}' for s in SOLAR_SEL] + [f'wind_spd_{s}' for s in WIND_SEL]
for c in set(wxcols):
    if c in raw: raw[c]=raw[c].interpolate('time',limit=6).ffill().bfill()
raw['day_type']=raw['day_type'].ffill().bfill()
raw['Hour_sin']=np.sin(2*np.pi*raw.index.hour/24); raw['Hour_cos']=np.cos(2*np.pi*raw.index.hour/24)
raw['Doy_sin']=np.sin(2*np.pi*raw.index.dayofyear/365); raw['Doy_cos']=np.cos(2*np.pi*raw.index.dayofyear/365)
raw['is_weekend']=(raw['day_type']=='weekend').astype(float); raw['is_holiday']=(raw['day_type']=='holiday').astype(float)
raw['hour_int']=raw.index.hour.astype(np.int16)
print('rows', len(raw))

CAL = ['Hour_sin','Hour_cos','Doy_sin','Doy_cos','is_weekend','is_holiday']
def weekly_k(off):
    return 168*math.ceil((off+24)/168)   # D5→168·D10→336·D15→504

def feature_cols(df, fset, off):
    '''fset 별 future_features 컬럼 구성. lag_week 는 지평별 정직가드 shift(원점서 known).'''
    if fset == 'perstation':
        wx = ([f'temp_c_{s}' for s in STATIONS] + [f'solar_rad_{s}' for s in SOLAR_SEL] +
              [f'wind_spd_{s}' for s in WIND_SEL] + [f'total_cloud_{s}' for s in SOLAR_SEL] +
              [f'midlow_cloud_{s}' for s in SOLAR_SEL])
    else:
        wx = ['temp_c','solar_rad','wind_spd','total_cloud','midlow_cloud']
    cols = wx + ['cap_btmppa'] + CAL
    if fset in ('anchor','anchor2'):
        k = weekly_k(off); df[f'lag_week_{off}'] = df['Demand'].shift(k); cols += [f'lag_week_{off}']
    if fset == 'anchor2':
        k = weekly_k(off); df[f'lag_2week_{off}'] = df['Demand'].shift(k+168); cols += [f'lag_2week_{off}']
    return cols
""")

code(r"""
class DS(Dataset):
    def __init__(self, data, hour, seq_len, pred_len, fidx, tidx, offset):
        self.data=data; self.hour=hour; self.seq_len=seq_len; self.pred_len=pred_len
        self.fidx=fidx; self.tidx=tidx; self.offset=offset
    def __len__(self): return len(self.data)-self.seq_len-self.offset-self.pred_len+1
    def __getitem__(self,i):
        past=self.data[i:i+self.seq_len]; s=i+self.seq_len+self.offset; fut=self.data[s:s+self.pred_len]
        return {'past_numeric':torch.FloatTensor(past[:,self.fidx]),
                'past_y':torch.FloatTensor(past[:,self.tidx:self.tidx+1]),
                'future_numeric':torch.FloatTensor(fut[:,self.fidx]),
                'future_y':torch.FloatTensor(fut[:,self.tidx]),
                'future_hour':torch.LongTensor(self.hour[s:s+self.pred_len])}

class Patch_Weather_Attention(nn.Module):
    def __init__(self, q, k, h):
        super().__init__()
        self.W_Q=nn.Sequential(nn.Linear(q,h),nn.Tanh(),nn.Linear(h,h))
        self.W_K=nn.Sequential(nn.Linear(k,h),nn.Tanh(),nn.Linear(h,h)); self.s=1.0/(h**0.5)
    def forward(self, fw, pw, to):
        Q=self.W_Q(fw).unsqueeze(1); K=self.W_K(pw)
        a=F.softmax(torch.bmm(Q,K.transpose(1,2))*self.s,dim=-1); return torch.bmm(a,to).squeeze(1),a

class PatchTST(nn.Module):
    def __init__(self, num_features, seq_len, pred_len=24, patch_len=24, stride=12,
                 d_model=256, num_heads=4, num_layers=3, d_ff=1024, dropout=0.2):
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
        self.revin_w=nn.Parameter(torch.ones(1)); self.revin_b=nn.Parameter(torch.zeros(1)); self.eps=1e-5
    def forward(self, b):
        pn=b['past_numeric'].to(DEVICE); py=b['past_y'].to(DEVICE); fn=b['future_numeric'].to(DEVICE); B=pn.shape[0]
        mean=py.mean(1,keepdim=True); std=torch.sqrt(py.var(1,keepdim=True,unbiased=False)+self.eps)
        pyn=(py-mean)/std*self.revin_w+self.revin_b
        xp=torch.cat([pn,pyn],-1)
        xpp=xp.unfold(1,self.patch_len,self.stride).permute(0,1,3,2).reshape(B,self.num_patches,-1)
        eo=self.transformer_encoder(self.dropout(self.patch_embedding(xpp)+self.pos_embedding))
        ff=fn.reshape(B,-1)
        xw=xp[...,:-1].unfold(1,self.patch_len,self.stride).permute(0,1,3,2).reshape(B,self.num_patches,-1)
        ctx,_=self.weather_attn(ff,xw,eo)
        on=self.regressor(torch.cat([ctx,ff],1))+self.weather_bypass(ff)
        on=(on-self.revin_b)/self.revin_w
        return on*std.squeeze(-1)+mean.squeeze(-1), std.squeeze(-1)

def make_loss(kind, delta=1.0):
    def f(pred, target, std):
        e=(pred-target)/std
        if kind=='mae': base=e.abs()
        elif kind=='mse': base=e**2
        else: base=torch.where(e.abs()<delta, 0.5*e**2, delta*(e.abs()-0.5*delta))  # huber
        return base.mean()
    return f
""")

code(r"""
def prep(df, fset, off):
    cols = feature_cols(df, fset, off)
    feats = cols + ['Demand']
    sub = df.dropna(subset=[f'lag_week_{off}'] if fset in ('anchor','anchor2') else []).copy()
    tr=sub[sub.index<TRAIN_END]; va=sub[(sub.index>=TRAIN_END)&(sub.index<VAL_END)]; te=sub[sub.index>=VAL_END]
    sc=MinMaxScaler((0,1)); tr=tr.copy()
    tr[cols]=sc.fit_transform(tr[cols]); va=va.copy(); te=te.copy()
    va[cols]=sc.transform(va[cols]); te[cols]=sc.transform(te[cols])
    fidx=[feats.index(c) for c in cols]; tidx=feats.index('Demand')
    hr=lambda x:x['hour_int'].values.astype(np.int64)
    return (tr[feats].values, va[feats].values, te[feats].values, hr(tr),hr(va),hr(te), sc, fidx, tidx, cols)

def train_one(name, hname, off, fset, hp, loss):
    a_tr,a_va,a_te,h_tr,h_va,h_te,sc,fidx,tidx,cols = prep(raw, fset, off)
    nf=len(fidx)+1
    m=PatchTST(nf, pred_len=PRED_LEN, **hp).to(DEVICE)
    opt=torch.optim.AdamW(m.parameters(),lr=LR,weight_decay=1e-5)
    sch=torch.optim.lr_scheduler.ReduceLROnPlateau(opt,'min',factor=0.5,patience=4)
    crit=make_loss(loss); USE_AMP=(DEVICE=='cuda')
    gs=torch.amp.GradScaler('cuda',enabled=USE_AMP) if USE_AMP else None
    tl=DataLoader(DS(a_tr,h_tr,hp['seq_len'],PRED_LEN,fidx,tidx,off),batch_size=BATCH_SIZE,shuffle=True,drop_last=True)
    vl=DataLoader(DS(a_va,h_va,hp['seq_len'],PRED_LEN,fidx,tidx,off),batch_size=BATCH_SIZE)
    best=float('inf'); bad=0; path=f'{OUT_DIR}/{name}_{hname}.pth'
    for ep in range(1,EPOCHS+1):
        m.train()
        for b in tqdm(tl,desc=f'{name}/{hname} ep{ep}',leave=False):
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
            if bad>=PATIENCE: break
    joblib.dump(sc, f'{OUT_DIR}/{name}_{hname}_scaler.pkl')
    return best, cols, a_te, h_te, fidx, tidx, off, hp, nf, path
""")

code(r"""
def mape(a,p):
    a,p=np.asarray(a,float),np.asarray(p,float); k=(a>0)&np.isfinite(a)&np.isfinite(p)
    return float(np.mean(np.abs(a[k]-p[k])/a[k])*100) if k.any() else np.nan

@torch.no_grad()
def perfect_eval(path, hp, a_te, h_te, fidx, tidx, off, nf):
    m=PatchTST(nf,pred_len=PRED_LEN,**hp).to(DEVICE); m.load_state_dict(torch.load(path,map_location=DEVICE)); m.eval()
    ld=DataLoader(DS(a_te,h_te,hp['seq_len'],PRED_LEN,fidx,tidx,off),batch_size=256)
    P,A,H=[],[],[]
    for b in ld: pr,_=m(b); P.append(pr.cpu().numpy()); A.append(b['future_y'].numpy()); H.append(b['future_hour'].numpy())
    P=np.clip(np.concatenate(P).ravel(),0,None); A=np.concatenate(A).ravel(); H=np.concatenate(H).ravel()
    day=(H>=9)&(H<=15)
    return mape(A,P), mape(A[day],P[day])

registry={}
print('config'.ljust(16),'hz   perfect(전체/낮)')
for name,fset,hpo,loss in CONFIGS:
    hp=dict(DEFAULT_HP); hp.update(hpo)
    registry[name]=dict(feature_set=fset, hp=hp, loss=loss, horizons={})
    for hname,off in HORIZONS.items():
        best,cols,a_te,h_te,fidx,tidx,o,hp2,nf,path=train_one(name,hname,off,fset,hp,loss)
        mp,mpd=perfect_eval(path,hp,a_te,h_te,fidx,tidx,off,nf)
        registry[name]['horizons'][hname]=dict(offset=off, features=cols, weekly_k=(168*math.ceil((off+24)/168) if fset!='base' and fset!='perstation' else None),
                                                val=round(best,5), perfect_MAPE=round(mp,3), perfect_MAPE_day=round(mpd,3))
        print(f'{name.ljust(16)} {hname:>4} {mp:5.2f}/{mpd:5.2f}')
    json.dump(registry, open(f'{OUT_DIR}/registry.json','w'), ensure_ascii=False, indent=1)
print('\nregistry.json 저장. perfect는 상한 — 진짜 판정은 repo honest 하니스.')
""")

code(r"""
import shutil
shutil.make_archive('/content/landdemand_sweep','zip',OUT_DIR)
print('zip -> /content/landdemand_sweep.zip')
try:
    from google.colab import files; files.download('/content/landdemand_sweep.zip')
except Exception: pass
""")

md(r"""
## 산출물 적용
`out/` 전체를 repo `5. land_demand_forecaster/training/landdemand_sweep/` 에 풀기:
```
{config}_{D5,D10,D15}.pth + {config}_{...}_scaler.pkl + registry.json
```
그 뒤 Claude 가 honest 하니스 확장으로 **각 config를 D5/10/15 낮밤분리 vs LGBM·하이브리드** 비교 →
장지평 우승 HP·피처 확정. perfect(registry)는 상한 참고용일 뿐.

## 비용 메모
14 config × 3 지평 = 42 학습. T4 AMP로 batch256. 무거우면 CONFIGS 를 나눠 2~3배치로 실행
(registry/zip 은 누적 저장됨). seq720·big(d384/L4)·perstation 이 제일 무거움.
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

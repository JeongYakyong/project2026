# -*- coding: utf-8 -*-
"""train_landdemand_patchtst_colab_aug.ipynb 생성기 — ★예보오차 증강판(final2 기반).

배경(REPORT_5-B §9): final2 는 미래 기상채널을 '실측(완벽기상)'으로 학습 → 서빙은 forecast_horizon
예보(지평별 bias·정보력붕괴)를 받아 train-serve 분포 불일치(perfect-honest 격차의 근원).
증강: 학습 시 미래채널에 **지평조건부 잔차 부트스트랩**을 주입해 배포분포로 학습한다.

핵심(final2 와의 차이 — 그 외 구조·피처·HP 전부 동일):
  - 미래채널에만 주입(과거채널=실측 유지). 주입 = forecast_residuals.npz 의 해당 지평 D+n 하루(24h) 잔차
    블록을 시간대 정렬해 raw [temp_c·rh·wind·solar_rad·total_cloud] 에 더함 → 물리범위 clip
    → di/wct **재계산**(서빙과 동일 비선형) → 그 뒤 z-score(외생 scaler). cap_btmppa·시간피처=무주입.
  - 지평조건부라 자동으로 "가까운 미래=정밀, 먼 미래=거친"이 구현됨(D+10 일사/구름/풍속 잔차≈기후값오차
    → 합성예보≈노이즈 → 모델이 자동 무시. 근거 ACC표 = REPORT_5-B §9).
  - train=매 에폭 무작위 블록 재샘플(증강). val=표본별 시드 고정(조기종료 안정). test perfect=무주입(상한 참고).
입력: demand_raw_land.csv + forecast_residuals.npz(둘 다 Colab 업로드).
산출: landdemand_aug/best_patchtst_landdemand_{D1..D7}.pth + scaler_exog.pkl + metadata_landdemand_aug.pkl.
판정은 repo honest 하니스 `_ab_aug_eval.py`(forecast_horizon 실예보).
"""
import json
from pathlib import Path

OUT = Path(__file__).resolve().parent / "train_landdemand_patchtst_colab_aug.ipynb"
CELLS = []
def md(s):  CELLS.append(("markdown", s.strip("\n")))
def code(s): CELLS.append(("code", s.strip("\n")))

md(r"""
# 전국 수요 PatchTST — ★예보오차 증강판 (final2 + 지평조건부 잔차 부트스트랩)

final2 와 모델·피처·HP 동일. **유일한 차이 = 미래 기상채널에 지평별 예보오차를 주입**해 학습:
- 미래 raw [temp_c·rh·wind·solar_rad·total_cloud] += (해당 지평 하루 24h 잔차 블록, 시간대 정렬)
- → 물리범위 clip → **di/wct 재계산** → 외생 z-score. (과거채널=실측 유지, cap·시간피처=무주입)
- 지평조건부 = 가까운 미래는 정밀·먼 미래는 거친 예보를 자동 재현(D+10 비기온채널 자동 노이즈화).

**입력**: `demand_raw_land.csv` + `forecast_residuals.npz`. **산출**: `landdemand_aug/`.
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
RES_PATH = '/content/forecast_residuals.npz'   # ★증강 잔차 풀
OUT_DIR  = '/content/out'; os.makedirs(OUT_DIR, exist_ok=True)
PRED_LEN = 24
HORIZONS = {f'D{n}': (n-1)*24 for n in range(1, 8)}   # ★D+1~7만 학습(D+8~15=LGBM, 사용자 확정 06-19)
TRAIN_END = '2025-01-01'; VAL_END = '2026-01-01'
TEMP_SEL  = ['wonju', 'seosan', 'pohang', 'yeonggwang']   # 대관령 제외(무인)
SOLAR_SEL = ['seosan', 'yeonggwang']
HP = dict(seq_len=336, patch_len=24, stride=12, d_model=256, num_heads=4, num_layers=3, d_ff=1024, dropout=0.2)
EPOCHS = 80; BATCH_SIZE = 256; LR = 1e-3; PATIENCE = 12

EXOG = ['temp_c', 'di', 'wct', 'solar_rad', 'total_cloud', 'cap_btmppa']   # 전역 z-score 대상(순서 고정)
TIME = ['Hour_sin', 'Hour_cos', 'Doy_sin', 'Doy_cos', 'is_weekend', 'is_holiday']   # 정규화 제외
FUTURE_FEATURES = EXOG + TIME
RAW_W = ['temp_c', 'rh', 'wind', 'solar_rad', 'total_cloud', 'cap_btmppa']  # 미래 주입 대상 raw(+cap 무주입)
INJECT = ['temp_c', 'rh', 'wind', 'solar_rad', 'total_cloud']              # 실제 잔차 더할 채널(풀 순서와 동일)
VAL_SEED = 20260619
print('EXOG', EXOG, '| TIME', TIME, '| INJECT', INJECT)
""")

code(r"""
# ── 잔차 풀 로드(지평별 (n_blocks,24,5)) ──
RES = np.load(RES_PATH, allow_pickle=True)
assert list(RES['channels']) == INJECT, ('풀 채널순서 불일치', list(RES['channels']))
POOL = {f'D{n}': RES[f'res_D{n}'].astype(np.float32) for n in range(1, 16)}
for n in range(1, 16): print(f'  D{n} 풀 블록수 = {len(POOL[f"D{n}"])}')
""")

code(r"""
df = pd.read_csv(CSV_PATH); df['timestamp'] = pd.to_datetime(df['timestamp'])
df = df.set_index('timestamp').sort_index()
idx = pd.date_range(df.index.min(), df.index.max(), freq='h'); df = df.reindex(idx); df.index.name='timestamp'
df.loc[df['real_demand_land']==0,'real_demand_land']=np.nan
df['Demand']=df['real_demand_land'].interpolate('time').ffill().bfill()

# 인구권 4지점 평균: 기온·습도·바람 (raw 유지 = 미래 주입 대상)
T = df[[f'temp_c_{s}' for s in TEMP_SEL]].mean(1).interpolate('time',limit=6).ffill().bfill()
RH = df[[f'humidity_{s}' for s in TEMP_SEL]].mean(1).interpolate('time',limit=6).ffill().bfill()
Wms = df[[f'wind_spd_{s}' for s in TEMP_SEL]].mean(1).interpolate('time',limit=6).ffill().bfill()
df['temp_c'] = T; df['rh'] = RH; df['wind'] = Wms
# 불쾌지수·체감기온(실측 기준 — 과거채널·scaler fit 용)
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
""")

code(r"""
def comfort_np(T, RH, Wms):
    di = 0.81*T + 0.01*RH*(0.99*T - 14.3) + 46.3
    Wk = np.clip(Wms*3.6, 4.8, None)
    wct = 13.12 + 0.6215*T - 11.37*Wk**0.16 + 0.3965*T*Wk**0.16
    return di, np.where(T <= 10, wct, T)

class AugDemandDataset(Dataset):
    '''과거채널=실측(scaled EXOG+TIME). 미래채널=실측 raw + 지평조건부 잔차 주입 → (월,시각) 관측범위 clip
       → di/wct 재계산 → z-score. clip 으로 물리불가 합성값(예: 한여름 43°C·일사>맑은하늘) 제거.'''
    def __init__(self, past_feat, demand, raw_w, time_arr, hour, month, seq_len, pred_len, offset,
                 pool, mean, scale, env, augment, val_seed=0):
        self.pf=past_feat; self.dem=demand; self.raw=raw_w; self.tm=time_arr; self.hour=hour; self.month=month
        self.seq_len=seq_len; self.pred_len=pred_len; self.offset=offset
        self.pool=pool; self.mean=mean; self.scale=scale; self.augment=augment; self.val_seed=val_seed
        self.t_lo, self.t_hi, self.w_hi, self.s_hi = env   # 각 (13,24) [월,시각] 관측 envelope
        self.np_idx=len(pool)
    def __len__(self): return len(self.dem)-self.seq_len-self.offset-self.pred_len+1
    def _residual(self, i, fut_hour):
        if self.np_idx == 0: return np.zeros((self.pred_len, len(INJECT)), np.float32)
        if self.augment: bi = np.random.randint(self.np_idx)
        else: bi = int(np.random.default_rng(self.val_seed + i).integers(self.np_idx))
        blk = self.pool[bi]                      # (24,5) hour-indexed
        return blk[fut_hour]                     # 시간대 정렬 (pred_len,5)
    def __getitem__(self, i):
        s = i + self.seq_len + self.offset
        past_num = self.pf[i:i+self.seq_len]                 # (seq,12) scaled EXOG+TIME
        past_y   = self.dem[i:i+self.seq_len][:, None]       # (seq,1)
        fut_hour = self.hour[s:s+self.pred_len].astype(np.int64)
        mo = self.month[s:s+self.pred_len]                   # (24,) 월 1~12
        raw = self.raw[s:s+self.pred_len].copy()             # (24,6) [T,RH,W,solar,cloud,cap]
        res = self._residual(i, fut_hour)                    # (24,5)
        # 주입 후 (월,시각) 관측 envelope 로 clip → 물리불가 꼬리 제거(분포 몸통은 보존)
        T  = np.clip(raw[:,0] + res[:,0], self.t_lo[mo, fut_hour], self.t_hi[mo, fut_hour])
        RH = np.clip(raw[:,1] + res[:,1], 0.0, 100.0)
        W  = np.clip(raw[:,2] + res[:,2], 0.0, self.w_hi[mo, fut_hour])
        SO = np.clip(raw[:,3] + res[:,3], 0.0, self.s_hi[mo, fut_hour])
        CL = np.clip(raw[:,4] + res[:,4], 0.0, 1.0)
        di, wct = comfort_np(T, RH, W)
        exog = np.stack([T, di, wct, SO, CL, raw[:,5]], axis=1)   # (24,6) EXOG 순서
        exog = (exog - self.mean) / self.scale                   # z-score
        fut_num = np.concatenate([exog, self.tm[s:s+self.pred_len]], axis=1).astype(np.float32)  # (24,12)
        return {'past_numeric':torch.from_numpy(past_num),'past_y':torch.FloatTensor(past_y),
                'future_numeric':torch.from_numpy(fut_num),'future_y':torch.FloatTensor(self.dem[s:s+self.pred_len]),
                'future_hour':torch.from_numpy(fut_hour)}
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
    '''단순 MSE: per-instance std 스케일한 잔차의 제곱(=RevIN 정규화공간 MSE, LTSF 표준). 평가는 MAPE.'''
    def forward(self, pred, target, std): return (((pred-target)/std)**2).mean()
""")

code(r"""
# ── prep: 외생 scaler 는 실측 EXOG(train)로 fit. 과거채널=scaled EXOG+TIME, 미래=raw+주입(런타임) ──
tr=df[df.index<TRAIN_END].copy(); va=df[(df.index>=TRAIN_END)&(df.index<VAL_END)].copy(); te=df[df.index>=VAL_END].copy()
scaler=StandardScaler(); scaler.fit(tr[EXOG]); joblib.dump(scaler, f'{OUT_DIR}/scaler_exog.pkl')
MEAN=scaler.mean_.astype(np.float32); SCALE=scaler.scale_.astype(np.float32)
NF=len(FUTURE_FEATURES)+1   # 12 + target

# ── (월,시각) 관측 envelope: 합성 미래기상을 실제 관측범위로 clip(물리불가 꼬리 제거) ──
def envelope(col, how):
    g = df.groupby([df.index.month, df.index.hour])[col].agg(how).unstack(fill_value=np.nan)
    tab = np.full((13, 24), np.nan, np.float32)
    for m in g.index:
        for h in g.columns: tab[m, h] = g.loc[m, h]
    # 빈칸은 전월/전역으로 보수적 보정
    col_fb = np.nanmax(tab) if how=='max' else np.nanmin(tab)
    return np.where(np.isfinite(tab), tab, col_fb).astype(np.float32)
ENV = (envelope('temp_c','min'), envelope('temp_c','max'), envelope('wind','max'), envelope('solar_rad','max'))
print('envelope temp_c %.1f~%.1f | wind<=%.1f | solar<=%.2f' %
      (np.nanmin(ENV[0]), np.nanmax(ENV[1]), np.nanmax(ENV[2]), np.nanmax(ENV[3])))

def pack(frame):
    ex=scaler.transform(frame[EXOG]).astype(np.float32)
    past_feat=np.concatenate([ex, frame[TIME].values.astype(np.float32)], axis=1)  # (N,12) EXOG+TIME
    return dict(past_feat=past_feat, demand=frame['Demand'].values.astype(np.float32),
                raw_w=frame[RAW_W].values.astype(np.float32), time_arr=frame[TIME].values.astype(np.float32),
                hour=frame['hour_int'].values.astype(np.int64), month=frame.index.month.values.astype(np.int64))
PK_TR=pack(tr); PK_VA=pack(va); PK_TE=pack(te)
print('NF',NF,'| train',len(tr),'val',len(va),'test',len(te))

def make_ds(pk, off, pool, augment):
    return AugDemandDataset(pk['past_feat'],pk['demand'],pk['raw_w'],pk['time_arr'],pk['hour'],pk['month'],
                            HP['seq_len'],PRED_LEN,off,pool,MEAN,SCALE,ENV,augment,VAL_SEED)

def train_one(hname, off):
    pool=POOL[hname]; crit=ScaledMSELoss(); m=PatchTST_Demand_RevIN(NF,pred_len=PRED_LEN,**HP).to(DEVICE)
    opt=torch.optim.AdamW(m.parameters(),lr=LR,weight_decay=1e-5)
    sch=torch.optim.lr_scheduler.ReduceLROnPlateau(opt,'min',factor=0.5,patience=4)
    USE_AMP=(DEVICE=='cuda'); gs=torch.amp.GradScaler('cuda',enabled=USE_AMP) if USE_AMP else None
    tl=DataLoader(make_ds(PK_TR,off,pool,True),batch_size=BATCH_SIZE,shuffle=True,drop_last=True)
    vl=DataLoader(make_ds(PK_VA,off,pool,False),batch_size=BATCH_SIZE)   # val=주입(시드고정)
    best=float('inf'); bad=0; path=f'{OUT_DIR}/best_patchtst_landdemand_{hname}.pth'
    print(f'== {hname} off={off} | feats={NF} pool={len(pool)} train={len(tl.dataset)} val={len(vl.dataset)} AMP={USE_AMP}')
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
    '''참고용 상한: 미래채널=실측(무주입). 증강모델은 perfect 가 다소 오를 수 있음 — 진짜 판정은 honest.'''
    m=PatchTST_Demand_RevIN(NF,pred_len=PRED_LEN,**HP).to(DEVICE); m.load_state_dict(torch.load(path,map_location=DEVICE)); m.eval()
    pool0=np.zeros((0,24,len(INJECT)),np.float32)   # 무주입
    ld=DataLoader(make_ds(PK_TE,off,pool0,False),batch_size=256); P,Aa,Hh=[],[],[]
    for b in ld: pr,_=m(b); P.append(pr.cpu().numpy()); Aa.append(b['future_y'].numpy()); Hh.append(b['future_hour'].numpy())
    P=np.clip(np.concatenate(P).ravel(),0,None); Aa=np.concatenate(Aa).ravel(); Hh=np.concatenate(Hh).ravel(); day=(Hh>=9)&(Hh<=15)
    return mape(Aa,P), mape(Aa[day],P[day])

META=dict(model='Cross-Attention PatchTST + RevIN(타깃) + 전역 z-score(외생) + ★예보오차 증강',
          target='real_demand_land', loss='ScaledMSE(단순, std스케일=정규화공간 MSE)', revin=True, revin_affine=True, HP=HP, PRED_LEN=PRED_LEN,
          EXOG=EXOG, TIME=TIME, FUTURE_FEATURES=FUTURE_FEATURES, TEMP_SEL=TEMP_SEL, SOLAR_SEL=SOLAR_SEL,
          comfort=dict(di='0.81T+0.01RH(0.99T-14.3)+46.3', wct='기상청 겨울 wind chill(T<=10 & W>=4.8km/h), 그외 T', wind_kmh='m/s*3.6'),
          augment=dict(method='지평조건부 하루24h 잔차 부트스트랩(시간대 정렬)', inject=INJECT, pool='forecast_residuals.npz',
                       note='미래채널만 주입(과거=실측). raw 주입→clip→di/wct 재계산→z-score. cap·시간피처 무주입. val 시드고정.'),
          scaler='scaler_exog.pkl (StandardScaler, EXOG만, train fit)', TRAIN_END=TRAIN_END, VAL_END=VAL_END, horizons={})
print('지평별 증강 학습 + perfect(참고):')
for hname, off in HORIZONS.items():
    best=train_one(hname, off); mp,mpd=perfect_eval(f'{OUT_DIR}/best_patchtst_landdemand_{hname}.pth', off)
    META['horizons'][hname]=dict(offset=off, val_MAE=round(best,5), perfect_MAPE=round(mp,3), perfect_MAPE_day=round(mpd,3),
                                 pool_blocks=int(len(POOL[hname])), weight=f'best_patchtst_landdemand_{hname}.pth')
    joblib.dump(META, f'{OUT_DIR}/metadata_landdemand_aug.pkl')
    print(f'  {hname:>3}: perfect {mp:5.2f} / 낮 {mpd:5.2f} (참고)')
print('\nmetadata_landdemand_aug.pkl 저장. ★판정은 repo honest 하니스 _ab_aug_eval.py (forecast_horizon 실예보).')
""")

code(r"""
import shutil
shutil.make_archive('/content/landdemand_aug','zip',OUT_DIR)
print('zip -> /content/landdemand_aug.zip (7가중치 D+1~7 + scaler_exog + metadata_aug)')
try:
    from google.colab import files; files.download('/content/landdemand_aug.zip')
except Exception: pass
""")

md(r"""
## 산출물 적용
`out/` 전체를 repo `5. land_demand_forecaster/training/landdemand_aug/` 에 풀기:
```
best_patchtst_landdemand_{D1..D7}.pth + scaler_exog.pkl + metadata_landdemand_aug.pkl
```
그 뒤 Claude 가 honest 하니스 `_ab_aug_eval.py`(forecast_horizon 실예보)로 **증강 vs final2 vs LGBM**
D+1~7 지평×낮밤×계절 비교(D+8~15=LGBM 전제) → 낮/밤 컷오프 확정·채택 결정.
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

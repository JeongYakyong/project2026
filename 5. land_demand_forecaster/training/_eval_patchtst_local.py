# -*- coding: utf-8 -*-
"""PatchTST(5-B) 가중치 로컬 재현 평가 — Colab test_metrics.csv 검증용.
perfect-weather(실측 기상 투입) test 2026, 지평별 MAPE/낮MAPE/낮bias.
노트북 eval 과 동일 전처리(저장 scaler 사용, te=2026 슬라이딩).
실행: python "5. land_demand_forecaster/training/_eval_patchtst_local.py"
"""
from __future__ import annotations
import os, sys, joblib
import numpy as np, pandas as pd, torch
import torch.nn as nn, torch.nn.functional as F
from torch.utils.data import Dataset, DataLoader
try: sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception: pass

HERE = os.path.dirname(os.path.abspath(__file__))
PKL = os.path.join(HERE, 'landdemand_patchtst')
CSV = os.path.join(HERE, 'demand_raw_land.csv')
DEVICE = 'cpu'

meta = joblib.load(os.path.join(PKL, 'metadata_landdemand.pkl'))
scaler = joblib.load(os.path.join(PKL, 'scaler_landdemand.pkl'))
HP = meta['HP']; PRED_LEN = meta['PRED_LEN']; HORIZONS = meta['HORIZONS']
future_features = meta['future_features']; features = meta['features']
STATIONS, SOLAR_SEL, WIND_SEL = meta['STATIONS'], meta['SOLAR_SEL'], meta['WIND_SEL']
VAL_END = meta['VAL_END']


# ---- 모델(생성기와 동일) ----
class Patch_Weather_Attention(nn.Module):
    def __init__(self, query_dim, key_dim, hidden_dim):
        super().__init__()
        self.W_Q = nn.Sequential(nn.Linear(query_dim, hidden_dim), nn.Tanh(), nn.Linear(hidden_dim, hidden_dim))
        self.W_K = nn.Sequential(nn.Linear(key_dim, hidden_dim), nn.Tanh(), nn.Linear(hidden_dim, hidden_dim))
        self.scale_factor = 1.0 / (hidden_dim ** 0.5)
    def forward(self, fw, pw, to):
        Q = self.W_Q(fw).unsqueeze(1); K = self.W_K(pw)
        attn = F.softmax(torch.bmm(Q, K.transpose(1, 2)) * self.scale_factor, dim=-1)
        return torch.bmm(attn, to).squeeze(1), attn

class PatchTST_Demand_RevIN(nn.Module):
    def __init__(self, num_features, seq_len=336, pred_len=24, patch_len=24, stride=12,
                 d_model=256, num_heads=4, num_layers=3, d_ff=1024, dropout=0.2, revin_affine=True):
        super().__init__()
        self.patch_len=patch_len; self.stride=stride; self.seq_len=seq_len; self.pred_len=pred_len
        self.num_patches = (seq_len - patch_len) // stride + 1
        self.patch_embedding = nn.Linear(patch_len * num_features, d_model)
        self.pos_embedding = nn.Parameter(torch.randn(1, self.num_patches, d_model))
        self.dropout = nn.Dropout(dropout)
        enc = nn.TransformerEncoderLayer(d_model=d_model, nhead=num_heads, dim_feedforward=d_ff,
                                         dropout=dropout, batch_first=True, norm_first=True)
        self.transformer_encoder = nn.TransformerEncoder(enc, num_layers=num_layers)
        self.num_weather_feats = num_features - 1
        fut_flat = pred_len * self.num_weather_feats; w_patch = patch_len * self.num_weather_feats
        self.weather_attn = Patch_Weather_Attention(fut_flat, w_patch, d_model)
        self.regressor = nn.Sequential(nn.Linear(d_model + fut_flat, 256), nn.LeakyReLU(0.1),
                                       nn.Dropout(dropout), nn.Linear(256, pred_len))
        self.weather_bypass = nn.Linear(fut_flat, pred_len)
        self.revin_affine = revin_affine; self.eps = 1e-5
        if revin_affine:
            self.revin_w = nn.Parameter(torch.ones(1)); self.revin_b = nn.Parameter(torch.zeros(1))
    def forward(self, batch):
        p_num = batch['past_numeric'].to(DEVICE); p_y_raw = batch['past_y'].to(DEVICE)
        f_num = batch['future_numeric'].to(DEVICE); B = p_num.shape[0]
        mean = p_y_raw.mean(1, keepdim=True)
        std  = torch.sqrt(p_y_raw.var(1, keepdim=True, unbiased=False) + self.eps)
        p_y = (p_y_raw - mean) / std
        if self.revin_affine: p_y = p_y * self.revin_w + self.revin_b
        x_past = torch.cat([p_num, p_y], dim=-1)
        xp = x_past.unfold(1, self.patch_len, self.stride).permute(0, 1, 3, 2).reshape(B, self.num_patches, -1)
        enc_out = self.transformer_encoder(self.dropout(self.patch_embedding(xp) + self.pos_embedding))
        fut_flat = f_num.reshape(B, -1)
        xw = x_past[..., :-1].unfold(1, self.patch_len, self.stride).permute(0, 1, 3, 2).reshape(B, self.num_patches, -1)
        context, _ = self.weather_attn(fut_flat, xw, enc_out)
        out_n = self.regressor(torch.cat([context, fut_flat], dim=1)) + self.weather_bypass(fut_flat)
        if self.revin_affine: out_n = (out_n - self.revin_b) / self.revin_w
        return out_n * std.squeeze(-1) + mean.squeeze(-1), std.squeeze(-1)

class DS(Dataset):
    def __init__(self, data, hour, seq_len, pred_len, fidx, tidx, offset=0):
        self.data=data; self.hour=hour; self.seq_len=seq_len; self.pred_len=pred_len
        self.fidx=fidx; self.tidx=tidx; self.offset=offset
    def __len__(self): return len(self.data) - self.seq_len - self.offset - self.pred_len + 1
    def __getitem__(self, i):
        past=self.data[i:i+self.seq_len]; s=i+self.seq_len+self.offset; fut=self.data[s:s+self.pred_len]
        return {'past_numeric':torch.FloatTensor(past[:,self.fidx]),
                'past_y':torch.FloatTensor(past[:,self.tidx:self.tidx+1]),
                'future_numeric':torch.FloatTensor(fut[:,self.fidx]),
                'future_y':torch.FloatTensor(fut[:,self.tidx]),
                'future_hour':torch.LongTensor(self.hour[s:s+self.pred_len])}


def build_df():
    df = pd.read_csv(CSV); df['timestamp'] = pd.to_datetime(df['timestamp'])
    df = df.set_index('timestamp').sort_index()
    idx = pd.date_range(df.index.min(), df.index.max(), freq='h'); df = df.reindex(idx)
    df['temp_c']=df[[f'temp_c_{s}' for s in STATIONS]].mean(1)
    df['solar_rad']=df[[f'solar_rad_{s}' for s in SOLAR_SEL]].mean(1)
    df['wind_spd']=df[[f'wind_spd_{s}' for s in WIND_SEL]].mean(1)
    df['total_cloud']=df[[f'total_cloud_{s}' for s in SOLAR_SEL]].mean(1)
    df['midlow_cloud']=df[[f'midlow_cloud_{s}' for s in SOLAR_SEL]].mean(1)
    df.loc[df['real_demand_land']==0,'real_demand_land']=np.nan
    df['Demand']=df['real_demand_land'].interpolate('time').ffill().bfill()
    nc=['temp_c','solar_rad','wind_spd','total_cloud','midlow_cloud','cap_btmppa']
    df[nc]=df[nc].interpolate('time',limit=6).ffill().bfill()
    df['day_type']=df['day_type'].ffill().bfill()
    df['Hour_sin']=np.sin(2*np.pi*df.index.hour/24); df['Hour_cos']=np.cos(2*np.pi*df.index.hour/24)
    df['Doy_sin']=np.sin(2*np.pi*df.index.dayofyear/365); df['Doy_cos']=np.cos(2*np.pi*df.index.dayofyear/365)
    df['is_weekend']=(df['day_type']=='weekend').astype(float); df['is_holiday']=(df['day_type']=='holiday').astype(float)
    df['hour_int']=df.index.hour.astype(np.int64)
    return df


def mape(a,p):
    a,p=np.asarray(a,float),np.asarray(p,float); m=(a>0)&np.isfinite(a)&np.isfinite(p)
    return float(np.mean(np.abs(a[m]-p[m])/a[m])*100) if m.any() else np.nan
def bias(a,p):
    a,p=np.asarray(a,float),np.asarray(p,float); m=(a>0)&np.isfinite(a)&np.isfinite(p)
    return float(np.mean((p[m]-a[m])/a[m])*100) if m.any() else np.nan


@torch.no_grad()
def eval_h(path, te, hr, fidx, tidx, off, nf):
    m = PatchTST_Demand_RevIN(nf, pred_len=PRED_LEN, **HP).to(DEVICE)
    m.load_state_dict(torch.load(path, map_location=DEVICE)); m.eval()
    ld = DataLoader(DS(te, hr, HP['seq_len'], PRED_LEN, fidx, tidx, off), batch_size=256)
    P,A,Hh=[],[],[]
    for b in ld:
        pr,_=m(b); P.append(pr.numpy()); A.append(b['future_y'].numpy()); Hh.append(b['future_hour'].numpy())
    P=np.clip(np.concatenate(P).ravel(),0,None); A=np.concatenate(A).ravel(); Hh=np.concatenate(Hh).ravel()
    day=(Hh>=9)&(Hh<=15)
    return dict(MAPE=mape(A,P), MAPE_day=mape(A[day],P[day]), bias_day=bias(A[day],P[day]),
                bias_all=bias(A,P), n=len(A))


def main():
    df = build_df()
    df[future_features] = scaler.transform(df[future_features])   # 저장 scaler(train fit)
    te = df[df.index >= VAL_END]
    arr = te[features].values; hr = te['hour_int'].values
    fidx=[features.index(c) for c in future_features]; tidx=features.index('Demand'); nf=len(fidx)+1
    print(f'test rows {len(te)}  ({te.index.min()} ~ {te.index.max()})  nf={nf}')
    print(f"{'지평':>4} {'MAPE':>6} {'낮MAPE':>7} {'낮bias':>7} {'전bias':>7} {'n':>7}")
    rows=[]
    for hn, off in HORIZONS.items():
        r = eval_h(os.path.join(PKL, f'best_patchtst_landdemand_{hn}.pth'), arr, hr, fidx, tidx, off, nf)
        rows.append(dict(horizon=hn, **r))
        print(f"{hn:>4} {r['MAPE']:6.2f} {r['MAPE_day']:7.2f} {r['bias_day']:+7.2f} {r['bias_all']:+7.2f} {r['n']:7d}")
    pd.DataFrame(rows).to_csv(os.path.join(HERE, '_eval_local_perfect.csv'), index=False)
    print('\n저장: _eval_local_perfect.csv  (Colab test_metrics.csv 와 대조)')


if __name__ == '__main__':
    main()

# -*- coding: utf-8 -*-
"""train_landdemand_patchtst360_colab.ipynb 생성기 (5-B2: 단발 pred_len=360 + MAE, α제거).

5-B(15모델 direct)의 honest A/B 결과를 받아 약점보강:
  - honest 전체에서 LGBM v2에 짐(7-D 패턴). PatchTST는 D+1~2·봄낮 bias만 우위, 장지평·밤 약점.
  - 가설: ① 단발 pred_len=360(D+1..15 한 번에) = 지평 공유 학습으로 장지평 robust 기대,
          1모델(15모델 아님)이라 서빙·학습 단순.
          ② α 비대칭 제거 — RevIN만으로 봄낮 bias 이미 +0.03(검증됨), α(1.3)는 위험한 hand-tune.
          ③ 손실·조기종료 = 대칭 MAE(per-instance std 스케일) → MAPE 평가와 정렬.
  - RevIN·seq_len 336·입력피처는 5-B 그대로(검증된 부분 유지).
산출: best_patchtst_landdemand_360.pth + scaler + metadata (단일 가중치).

사용법: python "5. land_demand_forecaster/training/_gen_landdemand_patchtst360.py"
입력 CSV: demand_raw_land.csv (5-B 와 동일, 재추출 불필요).
"""
import json
from pathlib import Path

OUT = Path(__file__).resolve().parent / "train_landdemand_patchtst360_colab.ipynb"
CELLS = []
def md(s):  CELLS.append(("markdown", s.strip("\n")))
def code(s): CELLS.append(("code", s.strip("\n")))

md(r"""
# 전국 수요 PatchTST — 단발 pred_len=360 + MAE, α제거 (5-B2)

5-B(15모델 direct) honest A/B 약점보강. **변경점만**:
- **pred_len 24→360**: 원점에서 D+1..D+15(360h)를 **한 번에** 예측(단일 모델).
- **손실 = 대칭 MAE**(per-instance std 스케일). **α 비대칭 제거**(RevIN이 봄낮 bias를 이미 잡음).
- **조기종료 기준 = val MAE**(MAPE 평가와 정렬).
- RevIN·seq_len 336·입력피처·지점선택 = 5-B 그대로.

**입력**: `demand_raw_land.csv`(5-B 동일). **산출**: `best_patchtst_landdemand_360.pth` + scaler + metadata.
""")

code(r"""
import numpy as np, pandas as pd, torch, os, joblib
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

PRED_LEN = 360            # 단발: D+1..D+15 (15*24)
OFFSET   = 0
TRAIN_END = '2025-01-01'; VAL_END = '2026-01-01'
STATIONS  = ['daegwallyeong', 'wonju', 'seosan', 'pohang', 'yeonggwang']
SOLAR_SEL = ['seosan', 'yeonggwang']; WIND_SEL = ['daegwallyeong', 'pohang']

HP = dict(seq_len=336, patch_len=24, stride=12,
          d_model=256, num_heads=4, num_layers=3, d_ff=1024, dropout=0.2)
EPOCHS = 80; BATCH_SIZE = 256; LR = 1e-3; PATIENCE = 12   # T4 OOM 시 BATCH_SIZE=128
print('PRED_LEN', PRED_LEN, '| 단일 모델')
""")

code(r"""
df = pd.read_csv(CSV_PATH); df['timestamp'] = pd.to_datetime(df['timestamp'])
df = df.set_index('timestamp').sort_index()
idx = pd.date_range(df.index.min(), df.index.max(), freq='h'); df = df.reindex(idx); df.index.name='timestamp'
print('rows:', len(df), '| range:', df.index.min(), '->', df.index.max())

df['temp_c']       = df[[f'temp_c_{s}' for s in STATIONS]].mean(1)
df['solar_rad']    = df[[f'solar_rad_{s}' for s in SOLAR_SEL]].mean(1)
df['wind_spd']     = df[[f'wind_spd_{s}' for s in WIND_SEL]].mean(1)
df['total_cloud']  = df[[f'total_cloud_{s}' for s in SOLAR_SEL]].mean(1)
df['midlow_cloud'] = df[[f'midlow_cloud_{s}' for s in SOLAR_SEL]].mean(1)
df.loc[df['real_demand_land'] == 0, 'real_demand_land'] = np.nan
df['Demand'] = df['real_demand_land'].interpolate('time').ffill().bfill()
num_cols = ['temp_c','solar_rad','wind_spd','total_cloud','midlow_cloud','cap_btmppa']
df[num_cols] = df[num_cols].interpolate('time', limit=6).ffill().bfill()
df['day_type'] = df['day_type'].ffill().bfill()
df['Hour_sin'] = np.sin(2*np.pi*df.index.hour/24);      df['Hour_cos'] = np.cos(2*np.pi*df.index.hour/24)
df['Doy_sin']  = np.sin(2*np.pi*df.index.dayofyear/365); df['Doy_cos'] = np.cos(2*np.pi*df.index.dayofyear/365)
df['is_weekend'] = (df['day_type'] == 'weekend').astype(float)
df['is_holiday'] = (df['day_type'] == 'holiday').astype(float)
df['hour_int'] = df.index.hour.astype(np.int16)

future_features = ['temp_c','solar_rad','wind_spd','total_cloud','midlow_cloud','cap_btmppa',
                   'Hour_sin','Hour_cos','Doy_sin','Doy_cos','is_weekend','is_holiday']
features = future_features + ['Demand']
print('future feats', len(future_features))
""")

code(r"""
class PatchTSTDemandDataset(Dataset):
    '''past=seq_len, gap=offset(=0), future=pred_len(=360). future_hour 는 eval 분리용.'''
    def __init__(self, data_array, hour_array, seq_len, pred_len, future_idx, target_idx, offset=0):
        self.data=data_array; self.hour=hour_array; self.seq_len=seq_len; self.pred_len=pred_len
        self.future_idx=future_idx; self.target_idx=target_idx; self.offset=offset
    def __len__(self):
        return len(self.data) - self.seq_len - self.offset - self.pred_len + 1
    def __getitem__(self, i):
        past = self.data[i: i + self.seq_len]
        s = i + self.seq_len + self.offset
        fut = self.data[s: s + self.pred_len]
        return {'past_numeric':  torch.FloatTensor(past[:, self.future_idx]),
                'past_y':        torch.FloatTensor(past[:, self.target_idx: self.target_idx+1]),
                'future_numeric':torch.FloatTensor(fut[:, self.future_idx]),
                'future_y':      torch.FloatTensor(fut[:, self.target_idx]),
                'future_hour':   torch.LongTensor(self.hour[s: s + self.pred_len])}
""")

code(r"""
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
    '''Cross-Attention Patch-Weather + 타깃 RevIN. forward → (pred_mw, std). 5-B 동형(pred_len만 360).'''
    def __init__(self, num_features, seq_len=336, pred_len=360, patch_len=24, stride=12,
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
        self.regressor = nn.Sequential(nn.Linear(d_model + fut_flat, 512), nn.LeakyReLU(0.1),
                                       nn.Dropout(dropout), nn.Linear(512, pred_len))
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
""")

code(r"""
class ScaledMAELoss(nn.Module):
    '''대칭 MAE: per-instance std 로 스케일한 |잔차|. α 비대칭 없음(RevIN이 봄낮 bias 처리).'''
    def __init__(self): super().__init__()
    def forward(self, pred, target, std):
        return (torch.abs(pred - target) / std).mean()
""")

code(r"""
def prepare_split(df, features, future_features, target_col):
    idx = df.index
    tr = df[idx <  TRAIN_END].copy()
    va = df[(idx >= TRAIN_END) & (idx < VAL_END)].copy()
    te = df[idx >= VAL_END].copy()
    scaler = MinMaxScaler((0, 1))
    tr[future_features] = scaler.fit_transform(tr[future_features])
    va[future_features] = scaler.transform(va[future_features]); te[future_features] = scaler.transform(te[future_features])
    fidx = [features.index(c) for c in future_features]; tidx = features.index(target_col)
    hr = lambda x: x['hour_int'].values.astype(np.int64)
    return (tr[features].values, va[features].values, te[features].values,
            hr(tr), hr(va), hr(te), scaler, fidx, tidx)

def train_model(tr_arr, va_arr, hr_tr, hr_va, fidx, tidx, hp, save_path, epochs=EPOCHS, patience=PATIENCE):
    num_features = len(fidx) + 1
    model = PatchTST_Demand_RevIN(num_features, pred_len=PRED_LEN, **hp).to(DEVICE)
    opt = torch.optim.AdamW(model.parameters(), lr=LR, weight_decay=1e-5)
    sch = torch.optim.lr_scheduler.ReduceLROnPlateau(opt, mode='min', factor=0.5, patience=4)
    crit = ScaledMAELoss()
    USE_AMP = (DEVICE == 'cuda')
    amp_scaler = torch.amp.GradScaler('cuda', enabled=USE_AMP) if USE_AMP else None
    tr_ds = PatchTSTDemandDataset(tr_arr, hr_tr, hp['seq_len'], PRED_LEN, fidx, tidx, offset=OFFSET)
    va_ds = PatchTSTDemandDataset(va_arr, hr_va, hp['seq_len'], PRED_LEN, fidx, tidx, offset=OFFSET)
    tr_ld = DataLoader(tr_ds, batch_size=BATCH_SIZE, shuffle=True, drop_last=True)
    va_ld = DataLoader(va_ds, batch_size=BATCH_SIZE, shuffle=False)
    best = float('inf'); bad = 0
    print(f'== M360 offset={OFFSET}h | feats={num_features} | train_ds={len(tr_ds)} val_ds={len(va_ds)} | AMP={USE_AMP}')
    for ep in range(1, epochs + 1):
        model.train(); tl = 0.0
        for b in tqdm(tr_ld, desc=f'M360 ep{ep}', leave=False):
            opt.zero_grad()
            if USE_AMP:
                with torch.amp.autocast('cuda'):
                    pred, std = model(b); loss = crit(pred, b['future_y'].to(DEVICE), std)
                amp_scaler.scale(loss).backward(); amp_scaler.unscale_(opt)
                torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
                amp_scaler.step(opt); amp_scaler.update()
            else:
                pred, std = model(b); loss = crit(pred, b['future_y'].to(DEVICE), std)
                loss.backward(); torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0); opt.step()
            tl += loss.item()
        model.eval(); vl = 0.0
        with torch.no_grad():
            for b in va_ld:
                pred, std = model(b); vl += crit(pred, b['future_y'].to(DEVICE), std).item()
        tl /= len(tr_ld); vl /= max(len(va_ld), 1); sch.step(vl)
        if vl < best: best = vl; bad = 0; torch.save(model.state_dict(), save_path)
        else:
            bad += 1
            if bad >= patience: print(f'  early stop @ ep{ep}'); break
    print(f'== M360 done. best val MAE={best:.5f} -> {save_path}')
    return best
""")

code(r"""
tr, va, te, hr_tr, hr_va, hr_te, scaler, fidx, tidx = prepare_split(df, features, future_features, 'Demand')
joblib.dump(scaler, f'{OUT_DIR}/scaler_landdemand.pkl')
meta = dict(future_features=future_features, features=features,
            SEQ_LEN=HP['seq_len'], PRED_LEN=PRED_LEN, OFFSET=OFFSET, HP=HP,
            STATIONS=STATIONS, SOLAR_SEL=SOLAR_SEL, WIND_SEL=WIND_SEL,
            target='real_demand_land', revin=True, revin_affine=True, loss='ScaledMAE(대칭, α없음)',
            single_shot=True, TRAIN_END=TRAIN_END, VAL_END=VAL_END,
            note='5-B2 단발 pred_len=360 + 대칭 MAE. α제거. RevIN 유지.')
joblib.dump(meta, f'{OUT_DIR}/metadata_landdemand360.pkl')
train_model(tr, va, hr_tr, hr_va, fidx, tidx, HP, f'{OUT_DIR}/best_patchtst_landdemand_360.pth')
""")

code(r"""
def mape(a, p):
    a, p = np.asarray(a, float), np.asarray(p, float)
    m = (a > 0) & np.isfinite(a) & np.isfinite(p)
    return float(np.mean(np.abs(a[m]-p[m])/a[m])*100) if m.any() else np.nan
def bias(a, p):
    a, p = np.asarray(a, float), np.asarray(p, float); m = (a > 0) & np.isfinite(a) & np.isfinite(p)
    return float(np.mean((p[m]-a[m])/a[m])*100) if m.any() else np.nan

@torch.no_grad()
def eval_blocks(path, hp, arr, hr_arr, fidx, tidx, num_features):
    m = PatchTST_Demand_RevIN(num_features, pred_len=PRED_LEN, **hp).to(DEVICE)
    m.load_state_dict(torch.load(path, map_location=DEVICE)); m.eval()
    ds = PatchTSTDemandDataset(arr, hr_arr, hp['seq_len'], PRED_LEN, fidx, tidx, offset=OFFSET)
    ld = DataLoader(ds, batch_size=128, shuffle=False); P, A, Hh = [], [], []
    for b in ld:
        pred, _ = m(b); P.append(pred.cpu().numpy()); A.append(b['future_y'].numpy()); Hh.append(b['future_hour'].numpy())
    P = np.clip(np.concatenate(P), 0, None); A = np.concatenate(A); Hh = np.concatenate(Hh)   # (N,360)
    print('단발 360 TEST(2026) — 지평블록별 MAPE / 낮MAPE / 낮bias:')
    rows = []
    for n in range(1, 16):
        sl = slice((n-1)*24, n*24)
        a, p, h = A[:, sl].ravel(), P[:, sl].ravel(), Hh[:, sl].ravel()
        day = (h >= 9) & (h <= 15)
        rows.append(dict(horizon=f'D{n}', MAPE=round(mape(a,p),3), MAPE_day=round(mape(a[day],p[day]),3),
                         bias_day=round(bias(a[day],p[day]),3)))
        print(f'  D{n:>2}: MAPE {mape(a,p):.2f}  낮 {mape(a[day],p[day]):.2f}  낮bias {bias(a[day],p[day]):+.2f}')
    import pandas as pd; pd.DataFrame(rows).to_csv(f'{OUT_DIR}/test_metrics_360.csv', index=False)

eval_blocks(f'{OUT_DIR}/best_patchtst_landdemand_360.pth', HP, te, hr_te, fidx, tidx, len(fidx)+1)
print('\n참고: 이건 perfect-weather 상한. 진짜 판정은 repo honest A/B(forecast_horizon)에서 LGBM v2 · 5-B(15모델) 와 동일창 비교.')
""")

code(r"""
import shutil
shutil.make_archive('/content/landdemand_patchtst360', 'zip', OUT_DIR)
print('zip -> /content/landdemand_patchtst360.zip (단일 가중치 + scaler + metadata + test_metrics)')
try:
    from google.colab import files; files.download('/content/landdemand_patchtst360.zip')
except Exception: pass
""")

md(r"""
## 산출물 적용
`out/` 산출물을 repo `5. land_demand_forecaster/demand_patchTST_pkl_360/` 에 복사:
```
best_patchtst_landdemand_360.pth, scaler_landdemand.pkl, metadata_landdemand360.pkl, test_metrics_360.csv
```
그 뒤 Claude 가 honest A/B 하니스(_ab_honest.py)에 360 모델을 끼워 **LGBM v2 · 5-B(15모델) · 5-B2(360)**
세 모델을 동일 bases·forecast 기상·계절×낮밤으로 비교한다.
""")


def main():
    nb = {"cells": [{"cell_type": k, "metadata": {}, "source": s.splitlines(keepends=True),
                     **({"outputs": [], "execution_count": None} if k == "code" else {})}
                    for k, s in CELLS],
          "metadata": {"kernelspec": {"display_name": "Python 3", "name": "python3"},
                       "language_info": {"name": "python"}, "accelerator": "GPU",
                       "colab": {"provenance": []}},
          "nbformat": 4, "nbformat_minor": 5}
    OUT.write_text(json.dumps(nb, ensure_ascii=False, indent=1), encoding="utf-8")
    print("wrote", OUT, "| cells:", len(CELLS))


if __name__ == "__main__":
    main()

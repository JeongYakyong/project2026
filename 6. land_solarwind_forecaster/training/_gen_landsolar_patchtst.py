# -*- coding: utf-8 -*-
"""train_landsolar_patchtst_colab.ipynb 생성기 (6-B: 전국 태양광 PatchTST D1/D2/D3 direct).

배경: 6-A2에서 true_renew(market+PPA+BTM)는 태양광 지배·×3.3이라 태양광 util 정밀도가 작동.
→ 태양광만 PatchTST vs LGBM(6-A)을 D+1/D+2/D+3 비교(풍력은 LGBM 확정).

제주 3단계 PatchTST 아키텍처(Cross-Attention Patch-Weather)를 그대로 재사용. 차이:
  - 지점 = 영광·서산·포항(3지점 raw 채널, 평균 아님 → cross-attention 재사용).
  - 타깃 = gen_solar_utilization_kr(시장 이용률). BTM/PPA도 같은 이용률 공유(6-A2 검증).
  - direct 지평 = D1(offset 0)·D2(24)·D3(48). 학습창 train≤2024 / val 2025 / test 2026.
산출: best_patchtst_landsolar_{D1,D2,D3}.pth + scaler + metadata.

사용법: python "6. land_solarwind_forecaster/training/_gen_landsolar_patchtst.py"
"""
import json
from pathlib import Path

OUT = Path(__file__).resolve().parent / "train_landsolar_patchtst_colab.ipynb"
CELLS = []
def md(s):  CELLS.append(("markdown", s.strip("\n")))
def code(s): CELLS.append(("code", s.strip("\n")))

md(r"""
# 전국 태양광 이용률 PatchTST — direct D+1 / D+2 / D+3 (6-B)

6-A2 결론: true_renew(시장+PPA+BTM)는 태양광 지배(×3.3)라 태양광 util 정밀도가 작동.
→ **태양광만** PatchTST vs LGBM(6-A) 비교(D+1/2/3). **풍력은 LGBM 확정**(제주와 동일).

제주 3단계 Cross-Attention PatchTST 아키텍처 그대로. 차이: 지점=영광·서산·포항(3채널 raw),
타깃=gen_solar_utilization_kr, direct 지평 D1(offset0)/D2(24)/D3(48).

**입력**: `solar_raw_land.csv`(export_landsolar_csv.py 산출). **산출**: `_D1/_D2/_D3.pth` + scaler + metadata.
""")

code(r"""
import numpy as np, pandas as pd, torch, os, joblib
import torch.nn as nn, torch.nn.functional as F
from torch.utils.data import Dataset, DataLoader
from sklearn.preprocessing import MinMaxScaler
from sklearn.metrics import mean_absolute_error
from tqdm.auto import tqdm
DEVICE = 'cuda' if torch.cuda.is_available() else 'cpu'
print('DEVICE =', DEVICE)
""")

code(r"""
CSV_PATH = '/content/solar_raw_land.csv'
OUT_DIR  = '/content/out'; os.makedirs(OUT_DIR, exist_ok=True)

PRED_LEN = 24
# direct 지평: 이름 -> future/target 시작 offset(시간). 24의 배수(일 경계 정렬).
HORIZONS = {'D1': 0, 'D2': 24, 'D3': 48}
TRAIN_END = '2025-01-01'   # train <= 2024
VAL_END   = '2026-01-01'   # val 2025, test 2026
K_DAMP = 0.3               # solar_damping 감쇠(6-A land 동일)

SOLAR_STATIONS = ['yeonggwang', 'seosan', 'pohang']   # 전남·충남·경북 (G-13)
SOLAR_HP = dict(seq_len=336, patch_len=24, stride=12,
                d_model=256, num_heads=4, num_layers=3, d_ff=1024, dropout=0.2)
EPOCHS = 100; BATCH_SIZE = 128; LR = 1e-3
""")

code(r"""
df = pd.read_csv(CSV_PATH); df['timestamp'] = pd.to_datetime(df['timestamp'])
df = df.set_index('timestamp').sort_index()
print('rows:', len(df), '| range:', df.index.min(), '->', df.index.max())
df['Hour_sin'] = np.sin(2*np.pi*df.index.hour/24); df['Hour_cos'] = np.cos(2*np.pi*df.index.hour/24)
df['Year_sin'] = np.sin(2*np.pi*df.index.dayofyear/365); df['Year_cos'] = np.cos(2*np.pi*df.index.dayofyear/365)
num_cols = df.select_dtypes(include='number').columns
df[num_cols] = df[num_cols].interpolate(limit=3); df[num_cols] = df[num_cols].ffill().bfill()

# solar_damping (지점별, 일강수 06-20h 합 exp(-k))
def add_solar_damping(df, st):
    daily = df.groupby(df.index.date)[f'rainfall_{st}'].transform(
        lambda x: x.between_time('06:00', '20:00').sum())
    df[f'solar_damping_{st}'] = np.exp(-K_DAMP * daily.clip(upper=20))
for st in SOLAR_STATIONS: add_solar_damping(df, st)
df['Solar_Utilization'] = df['gen_solar_utilization_kr'].clip(0, 1)

# PatchTST 피처(지점별 raw 채널) — LGBM(평균)과 다르게
future_features_solar = []
for st in SOLAR_STATIONS:
    future_features_solar += [f'solar_rad_{st}', f'total_cloud_{st}', f'midlow_cloud_{st}', f'solar_damping_{st}']
future_features_solar += ['Hour_sin', 'Hour_cos']
features_solar = future_features_solar + ['Solar_Utilization']
print('solar future feats', len(future_features_solar), '=', future_features_solar)
""")

code(r"""
class PatchTSTDatasetH(Dataset):
    def __init__(self, data_array, seq_len, pred_len, future_idx, target_idx, offset=0):
        self.data=data_array; self.seq_len=seq_len; self.pred_len=pred_len
        self.future_idx=future_idx; self.target_idx=target_idx; self.offset=offset
    def __len__(self):
        return len(self.data) - self.seq_len - self.offset - self.pred_len + 1
    def __getitem__(self, idx):
        past = self.data[idx: idx + self.seq_len]
        s = idx + self.seq_len + self.offset
        fut = self.data[s: s + self.pred_len]
        return {'past_numeric': torch.FloatTensor(past[:, self.future_idx]),
                'past_y': torch.FloatTensor(past[:, self.target_idx: self.target_idx+1]),
                'future_numeric': torch.FloatTensor(fut[:, self.future_idx]),
                'future_y': torch.FloatTensor(fut[:, self.target_idx])}
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

class PatchTST_Weather_Model(nn.Module):
    def __init__(self, num_features, seq_len=336, pred_len=24, patch_len=24, stride=12,
                 d_model=128, num_heads=4, num_layers=2, d_ff=256, dropout=0.2):
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
    def forward(self, batch):
        p_num = batch['past_numeric'].to(DEVICE); p_y = batch['past_y'].to(DEVICE); f_num = batch['future_numeric'].to(DEVICE)
        B = p_num.shape[0]
        x_past = torch.cat([p_num, p_y], dim=-1)
        xp = x_past.unfold(1, self.patch_len, self.stride).permute(0, 1, 3, 2).reshape(B, self.num_patches, -1)
        enc_out = self.transformer_encoder(self.dropout(self.patch_embedding(xp) + self.pos_embedding))
        fut_flat = f_num.reshape(B, -1)
        xw = x_past[..., :-1].unfold(1, self.patch_len, self.stride).permute(0, 1, 3, 2).reshape(B, self.num_patches, -1)
        context, _ = self.weather_attn(fut_flat, xw, enc_out)
        return self.regressor(torch.cat([context, fut_flat], dim=1)) + self.weather_bypass(fut_flat)
""")

code(r"""
class DaylightWeightedMSELoss(nn.Module):
    # 흐린날(저이용률) 과대예측 페널티 — 제주 3단계와 동일
    def __init__(self, threshold=0.01, low_util_cutoff=0.25, high_weight=3.0, overpredict_penalty=1.5):
        super().__init__(); self.threshold=threshold; self.low_util_cutoff=low_util_cutoff
        self.high_weight=high_weight; self.overpredict_penalty=overpredict_penalty; self.mse=nn.MSELoss(reduction='none')
    def forward(self, pred, target):
        mask = (target > 0) | (pred > self.threshold)
        if mask.sum() == 0: return torch.tensor(0.0, requires_grad=True, device=pred.device)
        loss_all = self.mse(pred, target); w = torch.ones_like(target)
        cloudy = (target > self.threshold) & (target <= self.low_util_cutoff)
        w[cloudy] = self.high_weight
        w[cloudy & (pred > target)] = self.high_weight * self.overpredict_penalty
        return (loss_all * w)[mask].mean()
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
    return tr[features].values, va[features].values, te[features].values, scaler, fidx, tidx

def train_model(name, tr_arr, va_arr, fidx, tidx, hp, criterion, save_path, offset, epochs=EPOCHS, patience=15):
    num_features = len(fidx) + 1
    model = PatchTST_Weather_Model(num_features, pred_len=PRED_LEN, **hp).to(DEVICE)
    opt = torch.optim.AdamW(model.parameters(), lr=LR, weight_decay=1e-5)
    sch = torch.optim.lr_scheduler.ReduceLROnPlateau(opt, mode='min', factor=0.5, patience=5)
    tr_ds = PatchTSTDatasetH(tr_arr, hp['seq_len'], PRED_LEN, fidx, tidx, offset=offset)
    va_ds = PatchTSTDatasetH(va_arr, hp['seq_len'], PRED_LEN, fidx, tidx, offset=offset)
    tr_ld = DataLoader(tr_ds, batch_size=BATCH_SIZE, shuffle=True, drop_last=True)
    va_ld = DataLoader(va_ds, batch_size=BATCH_SIZE, shuffle=False)
    best = float('inf'); bad = 0
    print(f'== {name} offset={offset}h | feats={num_features} | train_ds={len(tr_ds)} val_ds={len(va_ds)}')
    for ep in range(1, epochs + 1):
        model.train(); tl = 0.0
        for b in tqdm(tr_ld, desc=f'{name} ep{ep}', leave=False):
            opt.zero_grad(); loss = criterion(model(b), b['future_y'].to(DEVICE)); loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0); opt.step(); tl += loss.item()
        model.eval(); vl = 0.0
        with torch.no_grad():
            for b in va_ld: vl += criterion(model(b), b['future_y'].to(DEVICE)).item()
        tl /= len(tr_ld); vl /= max(len(va_ld),1); sch.step(vl)
        if vl < best: best = vl; bad = 0; torch.save(model.state_dict(), save_path)
        else:
            bad += 1
            if bad >= patience: print(f'  early stop @ ep{ep}'); break
    print(f'== {name} done. best val={best:.5f} -> {save_path}')
    return best
""")

code(r"""
s_tr, s_va, s_te, scaler_solar, s_fidx, s_tidx = prepare_split(df, features_solar, future_features_solar, 'Solar_Utilization')
joblib.dump(scaler_solar, f'{OUT_DIR}/scaler_landsolar.pkl')
meta = dict(future_features_solar=future_features_solar, features_solar=features_solar,
            SEQ_LEN=SOLAR_HP['seq_len'], PRED_LEN=PRED_LEN, SOLAR_HP=SOLAR_HP,
            SOLAR_STATIONS=SOLAR_STATIONS, K_DAMP=K_DAMP, HORIZONS=HORIZONS,
            TRAIN_END=TRAIN_END, VAL_END=VAL_END)
joblib.dump(meta, f'{OUT_DIR}/metadata_landsolar.pkl')

for hname, off in HORIZONS.items():
    print('\n' + '='*60 + f'\nHORIZON {hname} (offset {off}h)')
    train_model(f'SOLAR_{hname}', s_tr, s_va, s_fidx, s_tidx, SOLAR_HP,
                DaylightWeightedMSELoss(0.01, 0.25, 3.0, 1.5),
                f'{OUT_DIR}/best_patchtst_landsolar_{hname}.pth', offset=off)
""")

code(r"""
@torch.no_grad()
def eval_mae(path, hp, arr, fidx, tidx, off, num_features, day_only=True):
    m = PatchTST_Weather_Model(num_features, pred_len=PRED_LEN, **hp).to(DEVICE)
    m.load_state_dict(torch.load(path, map_location=DEVICE)); m.eval()
    ds = PatchTSTDatasetH(arr, hp['seq_len'], PRED_LEN, fidx, tidx, offset=off)
    ld = DataLoader(ds, batch_size=256, shuffle=False); P, A = [], []
    for b in ld: P.append(np.clip(m(b).cpu().numpy(),0,1)); A.append(b['future_y'].numpy())
    P = np.concatenate(P); A = np.concatenate(A)
    if day_only:   # 낮시간(예측창 내 8~17h) — 태양광 핵심
        hours = (np.arange(PRED_LEN)[None,:])  # 예측창 시작이 offset+seq라 시각 매핑은 근사; 전체도 같이 출력
    return mean_absolute_error(A.ravel(), P.ravel())

print('PatchTST TEST util MAE (전시간, test 2026):')
for hname, off in HORIZONS.items():
    smae = eval_mae(f'{OUT_DIR}/best_patchtst_landsolar_{hname}.pth', SOLAR_HP, s_te, s_fidx, s_tidx, off, len(s_fidx)+1)
    print(f'  {hname}: solar util MAE = {smae:.4f}')
print('\n참고: LGBM(6-A) 동일 test 전시간 solar util MAE 와 비교 → 6-B 하니스에서 낮시간/흐린날 분리 비교.')
""")

code(r"""
import shutil
shutil.make_archive('/content/landsolar_patchtst', 'zip', OUT_DIR)
print('zip -> /content/landsolar_patchtst.zip (가중치 3개 + scaler + metadata)')
try:
    from google.colab import files; files.download('/content/landsolar_patchtst.zip')
except Exception: pass
""")

md(r"""
## 산출물 적용
`out/` 의 산출물을 repo `6. land_solarwind_forecaster/solarwind_patchTST_pkl/` 에 복사:
```
best_patchtst_landsolar_D1.pth / _D2.pth / _D3.pth
scaler_landsolar.pkl, metadata_landsolar.pkl
```
그 뒤 Claude 가 **6-B 비교 하니스**로 PatchTST vs LGBM(6-A)을 D+1/2/3, perfect+forecast,
낮시간·흐린날 분리로 비교한다. 큰 차이 없으면 태양광도 LGBM 단일(G-13 방침).
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

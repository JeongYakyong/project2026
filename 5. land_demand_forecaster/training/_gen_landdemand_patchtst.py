# -*- coding: utf-8 -*-
"""train_landdemand_patchtst_colab.ipynb 생성기 (5-B: 전국 수요 Cross-Attention PatchTST + RevIN).

구조 변경(2026-06-16, 사용자 확정): 5단계 LGBM → 제주3·6단계 solar 의 Cross-Attention
Patch-Weather + **RevIN**(인스턴스 정규화). 진단 5-0b 근거:
  - 타깃 표현=RevIN(raw MW는 연 표류·스케일로 NN 비친화. RevIN이 표류 흡수·스케일 압축).
  - context length seq_len=336(2주, PACF가 일블록+주간메아리2회까지 → 336 적정. 504 ablation).
  - 낮(09-15h) 과대 비대칭 손실 **약하게**(α=2, v2 LGBM은 8) — BTM 듀크커브 한낮 골 보정.

차이(solar 대비):
  - 타깃 = real_demand_land(MW) → RevIN(과거윈도우 mean/std로 정규화·복원, 학습가능 affine).
  - 입력 = v2 지점선택 공간평균(기온5·일사 서산영광·풍속 대관령포항·구름 서산영광) + cap_btmppa
    + 달력(hour/doy sin·cos) + day_type(is_weekend/is_holiday). **명시 lag/rec 없음**(past_y가 흡수).
  - direct 지평 = D+1..D+15 (offset 0,24,...,336), 15 가중치.
산출: best_patchtst_landdemand_{D1..D15}.pth + scaler + metadata.

사용법: python "5. land_demand_forecaster/training/_gen_landdemand_patchtst.py"
입력 CSV: export_landdemand_csv.py 산출 demand_raw_land.csv (Colab /content 업로드).
"""
import json
from pathlib import Path

OUT = Path(__file__).resolve().parent / "train_landdemand_patchtst_colab.ipynb"
CELLS = []
def md(s):  CELLS.append(("markdown", s.strip("\n")))
def code(s): CELLS.append(("code", s.strip("\n")))

md(r"""
# 전국 수요 Cross-Attention PatchTST + RevIN — direct D+1 .. D+15 (5-B)

5단계 구조 변경: LGBM → **Cross-Attention Patch-Weather + RevIN**(제주3·6단계 solar 구조).
진단 `5-0b`: 타깃표현=RevIN, seq_len=336(2주), 낮 과대 약한 비대칭(α=2).

**입력 채널**(known-future): 기온(5평균)·일사(서산영광)·풍속(대관령포항)·구름(서산영광 total/midlow)
·cap_btmppa·달력(hour/doy sin·cos)·is_weekend·is_holiday. **과거채널** = 위 + 과거수요(past_y, RevIN).
**명시 lag/rec 없음**(트랜스포머 past 윈도우가 자기상관 흡수).

**입력 파일**: `demand_raw_land.csv`(export_landdemand_csv.py). **산출**: `_D1.._D15.pth` + scaler + metadata.
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
CSV_PATH = '/content/demand_raw_land.csv'
OUT_DIR  = '/content/out'; os.makedirs(OUT_DIR, exist_ok=True)

PRED_LEN = 24
# direct 지평: 이름 -> 미래/타깃 시작 offset(시간). 24 배수(일 경계). D+1..D+15.
HORIZONS = {f'D{n}': (n-1)*24 for n in range(1, 16)}
TRAIN_END = '2025-01-01'   # train <= 2024
VAL_END   = '2026-01-01'   # val 2025, test 2026

STATIONS  = ['daegwallyeong', 'wonju', 'seosan', 'pohang', 'yeonggwang']
SOLAR_SEL = ['seosan', 'yeonggwang']
WIND_SEL  = ['daegwallyeong', 'pohang']

# seq_len=336(기본). 504 ablation 시 이 값만 바꿔 재실행.
HP = dict(seq_len=336, patch_len=24, stride=12,
          d_model=256, num_heads=4, num_layers=3, d_ff=1024, dropout=0.2)
EPOCHS = 80; BATCH_SIZE = 256; LR = 1e-3; PATIENCE = 12   # T4: batch 256(헤드룸)
ALPHA = 2.0   # 낮(09-15h) 과대 비대칭 가중(약하게; v2 LGBM은 8). 0이면 순수 MSE.
print('HORIZONS', list(HORIZONS.items()))
""")

code(r"""
df = pd.read_csv(CSV_PATH); df['timestamp'] = pd.to_datetime(df['timestamp'])
df = df.set_index('timestamp').sort_index()
# 시간 연속 인덱스(결측 보간) — origin/horizon 정렬 보장
idx = pd.date_range(df.index.min(), df.index.max(), freq='h'); df = df.reindex(idx); df.index.name='timestamp'
print('rows:', len(df), '| range:', df.index.min(), '->', df.index.max())

# v2 공간평균(지점선택)
df['temp_c']       = df[[f'temp_c_{s}' for s in STATIONS]].mean(1)
df['solar_rad']    = df[[f'solar_rad_{s}' for s in SOLAR_SEL]].mean(1)
df['wind_spd']     = df[[f'wind_spd_{s}' for s in WIND_SEL]].mean(1)
df['total_cloud']  = df[[f'total_cloud_{s}' for s in SOLAR_SEL]].mean(1)
df['midlow_cloud'] = df[[f'midlow_cloud_{s}' for s in SOLAR_SEL]].mean(1)

# 타깃·결측 처리
df.loc[df['real_demand_land'] == 0, 'real_demand_land'] = np.nan
df['Demand'] = df['real_demand_land'].interpolate('time').ffill().bfill()
num_cols = ['temp_c','solar_rad','wind_spd','total_cloud','midlow_cloud','cap_btmppa']
df[num_cols] = df[num_cols].interpolate('time', limit=6).ffill().bfill()
df['day_type'] = df['day_type'].ffill().bfill()

# 달력 + day_type 인코딩(미래 가용)
df['Hour_sin'] = np.sin(2*np.pi*df.index.hour/24);      df['Hour_cos'] = np.cos(2*np.pi*df.index.hour/24)
df['Doy_sin']  = np.sin(2*np.pi*df.index.dayofyear/365); df['Doy_cos'] = np.cos(2*np.pi*df.index.dayofyear/365)
df['is_weekend'] = (df['day_type'] == 'weekend').astype(float)
df['is_holiday'] = (df['day_type'] == 'holiday').astype(float)
df['hour_int'] = df.index.hour.astype(np.int16)   # 손실 낮 가중용(피처 아님)

future_features = ['temp_c','solar_rad','wind_spd','total_cloud','midlow_cloud','cap_btmppa',
                   'Hour_sin','Hour_cos','Doy_sin','Doy_cos','is_weekend','is_holiday']
features = future_features + ['Demand']   # 타깃은 항상 마지막
print('future feats', len(future_features), '=', future_features)
""")

code(r"""
class PatchTSTDemandDataset(Dataset):
    '''sliding window. past=seq_len, gap=offset(direct 지평), future=pred_len.
       future_hour 는 낮 비대칭 손실용(피처 아님).'''
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
    '''Cross-Attention Patch-Weather(solar 동형) + 타깃 RevIN(인스턴스 정규화, 학습가능 affine).
       forward → (pred_mw, std)  : pred 는 MW 복원값, std 는 손실 스케일용 per-instance.'''
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
        # RevIN
        self.revin_affine = revin_affine; self.eps = 1e-5
        if revin_affine:
            self.revin_w = nn.Parameter(torch.ones(1)); self.revin_b = nn.Parameter(torch.zeros(1))
    def forward(self, batch):
        p_num = batch['past_numeric'].to(DEVICE); p_y_raw = batch['past_y'].to(DEVICE)
        f_num = batch['future_numeric'].to(DEVICE); B = p_num.shape[0]
        # --- RevIN normalize (과거 윈도우 통계) ---
        mean = p_y_raw.mean(1, keepdim=True)                                   # (B,1,1)
        std  = torch.sqrt(p_y_raw.var(1, keepdim=True, unbiased=False) + self.eps)
        p_y = (p_y_raw - mean) / std
        if self.revin_affine: p_y = p_y * self.revin_w + self.revin_b
        # --- patch + encoder ---
        x_past = torch.cat([p_num, p_y], dim=-1)
        xp = x_past.unfold(1, self.patch_len, self.stride).permute(0, 1, 3, 2).reshape(B, self.num_patches, -1)
        enc_out = self.transformer_encoder(self.dropout(self.patch_embedding(xp) + self.pos_embedding))
        # --- cross attention (미래 기상 ↔ 과거 기상 패치) ---
        fut_flat = f_num.reshape(B, -1)
        xw = x_past[..., :-1].unfold(1, self.patch_len, self.stride).permute(0, 1, 3, 2).reshape(B, self.num_patches, -1)
        context, _ = self.weather_attn(fut_flat, xw, enc_out)
        out_n = self.regressor(torch.cat([context, fut_flat], dim=1)) + self.weather_bypass(fut_flat)  # (B,pred) norm공간
        # --- RevIN denormalize ---
        if self.revin_affine: out_n = (out_n - self.revin_b) / self.revin_w
        out = out_n * std.squeeze(-1) + mean.squeeze(-1)   # (B,pred) MW
        return out, std.squeeze(-1)
""")

code(r"""
class AsymDaytimeMSE(nn.Module):
    '''per-instance std 로 스케일한 잔차의 MSE. 낮(09-15h) & 과대예측(pred>actual)에 ×alpha.
       부호는 RevIN affine 변환 후에도 보존(std>0) → MW 공간 과대와 동일.'''
    def __init__(self, alpha=2.0): super().__init__(); self.alpha=alpha
    def forward(self, pred, target, std, future_hour):
        err = (pred - target) / std                      # (B,pred) 스케일프리
        w = torch.ones_like(err)
        day  = (future_hour >= 9) & (future_hour <= 15)
        over = err > 0
        w = torch.where(day & over, torch.full_like(w, self.alpha), w)
        return (w * err**2).mean()
""")

code(r"""
def prepare_split(df, features, future_features, target_col):
    idx = df.index
    tr = df[idx <  TRAIN_END].copy()
    va = df[(idx >= TRAIN_END) & (idx < VAL_END)].copy()
    te = df[idx >= VAL_END].copy()
    scaler = MinMaxScaler((0, 1))                  # 외생(기상·달력·capa)만. 타깃은 RevIN.
    tr[future_features] = scaler.fit_transform(tr[future_features])
    va[future_features] = scaler.transform(va[future_features]); te[future_features] = scaler.transform(te[future_features])
    fidx = [features.index(c) for c in future_features]; tidx = features.index(target_col)
    hr = lambda x: x['hour_int'].values.astype(np.int64)
    return (tr[features].values, va[features].values, te[features].values,
            hr(tr), hr(va), hr(te), scaler, fidx, tidx)

def train_model(name, tr_arr, va_arr, hr_tr, hr_va, fidx, tidx, hp, criterion, save_path, offset,
                epochs=EPOCHS, patience=PATIENCE):
    num_features = len(fidx) + 1
    model = PatchTST_Demand_RevIN(num_features, pred_len=PRED_LEN, **hp).to(DEVICE)
    opt = torch.optim.AdamW(model.parameters(), lr=LR, weight_decay=1e-5)
    sch = torch.optim.lr_scheduler.ReduceLROnPlateau(opt, mode='min', factor=0.5, patience=4)
    USE_AMP = (DEVICE == 'cuda')   # T4 텐서코어 혼합정밀 — 속도 ~2배·메모리 절반, 정확도 영향 미미
    amp_scaler = torch.amp.GradScaler('cuda', enabled=USE_AMP) if USE_AMP else None
    tr_ds = PatchTSTDemandDataset(tr_arr, hr_tr, hp['seq_len'], PRED_LEN, fidx, tidx, offset=offset)
    va_ds = PatchTSTDemandDataset(va_arr, hr_va, hp['seq_len'], PRED_LEN, fidx, tidx, offset=offset)
    tr_ld = DataLoader(tr_ds, batch_size=BATCH_SIZE, shuffle=True, drop_last=True)
    va_ld = DataLoader(va_ds, batch_size=BATCH_SIZE, shuffle=False)
    best = float('inf'); bad = 0
    print(f'== {name} offset={offset}h | feats={num_features} | train_ds={len(tr_ds)} val_ds={len(va_ds)} | AMP={USE_AMP}')
    for ep in range(1, epochs + 1):
        model.train(); tl = 0.0
        for b in tqdm(tr_ld, desc=f'{name} ep{ep}', leave=False):
            opt.zero_grad()
            if USE_AMP:
                with torch.amp.autocast('cuda'):
                    pred, std = model(b)
                    loss = criterion(pred, b['future_y'].to(DEVICE), std, b['future_hour'].to(DEVICE))
                amp_scaler.scale(loss).backward()
                amp_scaler.unscale_(opt)
                torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
                amp_scaler.step(opt); amp_scaler.update()
            else:
                pred, std = model(b)
                loss = criterion(pred, b['future_y'].to(DEVICE), std, b['future_hour'].to(DEVICE))
                loss.backward(); torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0); opt.step()
            tl += loss.item()
        model.eval(); vl = 0.0
        with torch.no_grad():
            for b in va_ld:
                pred, std = model(b)
                vl += criterion(pred, b['future_y'].to(DEVICE), std, b['future_hour'].to(DEVICE)).item()
        tl /= len(tr_ld); vl /= max(len(va_ld), 1); sch.step(vl)
        if vl < best: best = vl; bad = 0; torch.save(model.state_dict(), save_path)
        else:
            bad += 1
            if bad >= patience: print(f'  early stop @ ep{ep}'); break
    print(f'== {name} done. best val={best:.5f} -> {save_path}')
    return best
""")

code(r"""
tr, va, te, hr_tr, hr_va, hr_te, scaler, fidx, tidx = prepare_split(df, features, future_features, 'Demand')
joblib.dump(scaler, f'{OUT_DIR}/scaler_landdemand.pkl')
meta = dict(future_features=future_features, features=features,
            SEQ_LEN=HP['seq_len'], PRED_LEN=PRED_LEN, HP=HP, ALPHA=ALPHA,
            STATIONS=STATIONS, SOLAR_SEL=SOLAR_SEL, WIND_SEL=WIND_SEL, HORIZONS=HORIZONS,
            target='real_demand_land', revin=True, revin_affine=True,
            TRAIN_END=TRAIN_END, VAL_END=VAL_END,
            note='5-B Cross-Attention PatchTST+RevIN. direct D+1..D+15. 낮(09-15) 과대 약비대칭 a=2.')
joblib.dump(meta, f'{OUT_DIR}/metadata_landdemand.pkl')

for hname, off in HORIZONS.items():
    print('\n' + '='*60 + f'\nHORIZON {hname} (offset {off}h)')
    train_model(hname, tr, va, hr_tr, hr_va, fidx, tidx, HP, AsymDaytimeMSE(ALPHA),
                f'{OUT_DIR}/best_patchtst_landdemand_{hname}.pth', offset=off)
""")

code(r"""
def mape(a, p):
    a, p = np.asarray(a, float), np.asarray(p, float)
    m = (a > 0) & np.isfinite(a) & np.isfinite(p)
    return float(np.mean(np.abs(a[m]-p[m])/a[m])*100) if m.any() else np.nan

@torch.no_grad()
def eval_h(path, hp, arr, hr_arr, fidx, tidx, off, num_features):
    m = PatchTST_Demand_RevIN(num_features, pred_len=PRED_LEN, **hp).to(DEVICE)
    m.load_state_dict(torch.load(path, map_location=DEVICE)); m.eval()
    ds = PatchTSTDemandDataset(arr, hr_arr, hp['seq_len'], PRED_LEN, fidx, tidx, offset=off)
    ld = DataLoader(ds, batch_size=256, shuffle=False); P, A, Hh = [], [], []
    for b in ld:
        pred, _ = m(b); P.append(pred.cpu().numpy()); A.append(b['future_y'].numpy()); Hh.append(b['future_hour'].numpy())
    P = np.clip(np.concatenate(P).ravel(), 0, None); A = np.concatenate(A).ravel(); Hh = np.concatenate(Hh).ravel()
    day = (Hh >= 9) & (Hh <= 15)
    bias = lambda a, p: float(np.mean((p-a)/a)*100)
    return dict(MAPE=mape(A, P), MAPE_day=mape(A[day], P[day]), bias_day=bias(A[day], P[day]))

print('PatchTST TEST(2026) — 지평별 MAPE / 낮MAPE / 낮bias:')
rows = []
for hname, off in HORIZONS.items():
    r = eval_h(f'{OUT_DIR}/best_patchtst_landdemand_{hname}.pth', HP, te, hr_te, fidx, tidx, off, len(fidx)+1)
    rows.append(dict(horizon=hname, **{k: round(v,3) for k,v in r.items()}))
    print(f'  {hname:>3}: MAPE {r["MAPE"]:.2f}  낮 {r["MAPE_day"]:.2f}  낮bias {r["bias_day"]:+.2f}')
import pandas as pd; pd.DataFrame(rows).to_csv(f'{OUT_DIR}/test_metrics.csv', index=False)
print('\n참고: LGBM v2(5-A_v2) 동일 test perfect MAPE — D+1 3.56 / D+7 4.22 / D+12 5.48. '
      'A/B 정식 비교는 repo 하니스(perfect+forecast_horizon, 낮/공휴일 분리)에서.')
""")

code(r"""
import shutil
shutil.make_archive('/content/landdemand_patchtst', 'zip', OUT_DIR)
print('zip -> /content/landdemand_patchtst.zip (가중치 15개 + scaler + metadata + test_metrics)')
try:
    from google.colab import files; files.download('/content/landdemand_patchtst.zip')
except Exception: pass
""")

md(r"""
## 산출물 적용
`out/` 산출물을 repo `5. land_demand_forecaster/demand_patchTST_pkl/` 에 복사:
```
best_patchtst_landdemand_D1.pth .. _D15.pth
scaler_landdemand.pkl, metadata_landdemand.pkl, test_metrics.csv
```
그 뒤 Claude 가 **PatchTST vs LGBM v2 A/B 하니스**로 perfect + forecast_horizon(실예보),
낮/공휴일 분리 비교. 이기면 `serve_land_demand.py` 교체, 아니면 v2 유지(정직 비교).

## ablation
- **seq_len 504**: HP['seq_len']=504 로 바꿔 재실행(파일명에 _504 suffix 권장) → 336과 비교.
- **α=0**(순수 MSE) vs α=2: 낮 bias 개선 폭 확인.
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

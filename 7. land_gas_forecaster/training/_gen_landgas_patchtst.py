# -*- coding: utf-8 -*-
"""train_landgas_patchtst_colab.ipynb 생성기 (7-D: 수요→가스 직접 PatchTST, direct D1/D2/D3).

실험(7-D): 현행 체인(수요→신재생→가스, 가스=LGBM)을 건너뛰고 **수요 → 가스 직접** PatchTST.
신재생을 명시 계산하지 않고 원시 태양광 기상 + 포항 풍속을 주어, 모델이
"수요 − f(기상) → 가스(순부하 급전)"을 끝단에서 학습(덕커브 내재화). 체인의 신재생
단계 모델링·전파 오차를 따로 물지 않는 게 가설.  6단계 Cross-Attention PatchTST 재사용.

피처 확정(2026-06-15, 사용자):
  타깃   = gen_gas_kr (MW).  ÷LNG_cap 미적용(외삽 회피, LGBM v2와 동일 판단) → train MinMax 고정 스케일러.
  드라이버= real_demand_land(학습=실측 / 서빙=est_demand_land, est_horizon_land).
  태양광 = solar_rad·total_cloud·midlow_cloud·solar_damping @ 영광·서산·포항(3채널 raw).
  풍속   = wind_spd_pohang 1개(=서빙 forecast_horizon wind_spd_10m_pohang).
  달력   = Hour_sin/cos, Year_sin/cos / 자기회귀 past_y = 가스(스케일).
  손실   = 낮(09-15h) 과대예측 ×α 페널티(LGBM v2 비대칭 α=4 정신 계승) — 봄낮 덕커브가 실험 핵심.
  direct 지평 = D1(offset0)/D2(24)/D3(48), pred_len 24.  train≤2024 / val 2025 / test 2026.
산출: best_patchtst_landgas_{D1,D2,D3}.pth + scaler_x + scaler_y + metadata.

사용법: python "7. land_gas_forecaster/training/_gen_landgas_patchtst.py"
"""
import json
from pathlib import Path

OUT = Path(__file__).resolve().parent / "train_landgas_patchtst_colab.ipynb"
CELLS = []
def md(s):  CELLS.append(("markdown", s.strip("\n")))
def code(s): CELLS.append(("code", s.strip("\n")))

md(r"""
# 전국 가스 직접예측 PatchTST — 수요→가스 direct D+1 / D+2 / D+3 (7-D)

현행 체인(수요→신재생→가스, 가스=LGBM)을 건너뛰고 **수요 → 가스 직접** PatchTST.
신재생을 명시 계산하지 않고 원시 태양광 기상 + 포항 풍속을 주어, 모델이
`수요 − f(기상) → 가스`(순부하 급전)을 끝단에서 학습 → 덕커브 내재화. 가설: 체인의
신재생 단계 모델링·전파 오차를 따로 물지 않는다. 6단계 Cross-Attention PatchTST 그대로.

**입력**: `gas_raw_land.csv`(export_landgas_csv.py). **타깃**: gen_gas_kr(MW, 별도 MinMax).
**산출**: `_D1/_D2/_D3.pth` + scaler_x + scaler_y + metadata. 비교 기준 = 체인 가스(LGBM v2) 지평별 MAPE.
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
CSV_PATH = '/content/gas_raw_land.csv'
OUT_DIR  = '/content/out'; os.makedirs(OUT_DIR, exist_ok=True)

PRED_LEN = 24
# direct 지평: 이름 -> future/target 시작 offset(시간). 24의 배수(일 경계 정렬).
HORIZONS = {'D1': 0, 'D2': 24, 'D3': 48}
TRAIN_END = '2025-01-01'   # train <= 2024
VAL_END   = '2026-01-01'   # val 2025, test 2026
K_DAMP = 0.3               # solar_damping 감쇠(6단계 land 동일)
ALPHA  = 4.0               # 낮(09-15h) 과대예측 페널티 배수(LGBM v2 가스 α=4 계승)

SOLAR_STATIONS = ['yeonggwang', 'seosan', 'pohang']   # 전남·충남·경북 (G-13)
GAS_HP = dict(seq_len=336, patch_len=24, stride=12,
              d_model=256, num_heads=4, num_layers=3, d_ff=1024, dropout=0.2)
EPOCHS = 100; BATCH_SIZE = 128; LR = 1e-3
""")

code(r"""
df = pd.read_csv(CSV_PATH); df['timestamp'] = pd.to_datetime(df['timestamp'])
df = df.set_index('timestamp').sort_index()
print('rows:', len(df), '| range:', df.index.min(), '->', df.index.max())
df['Hour_sin'] = np.sin(2*np.pi*df.index.hour/24); df['Hour_cos'] = np.cos(2*np.pi*df.index.hour/24)
df['Year_sin'] = np.sin(2*np.pi*df.index.dayofyear/365); df['Year_cos'] = np.cos(2*np.pi*df.index.dayofyear/365)
df['hour'] = df.index.hour            # 손실 가중(낮 과대예측)용 — 모델 피처 아님
num_cols = df.select_dtypes(include='number').columns
df[num_cols] = df[num_cols].interpolate(limit=3); df[num_cols] = df[num_cols].ffill().bfill()

# solar_damping (지점별, 일강수 06-20h 합 exp(-k)) — 6단계 land 동일
def add_solar_damping(df, st):
    daily = df.groupby(df.index.date)[f'rainfall_{st}'].transform(
        lambda x: x.between_time('06:00', '20:00').sum())
    df[f'solar_damping_{st}'] = np.exp(-K_DAMP * daily.clip(upper=20))
for st in SOLAR_STATIONS: add_solar_damping(df, st)

# 가스 타깃은 2022~ 유효 → 결측/0 구간 제외 후 학습창 분할. 여기선 0을 NaN→보간 금지(타깃 누수),
# 대신 타깃 정규화는 train 구간 가스>0 으로 fit, 학습/평가시 가스 결측 윈도는 마스크.
df['gas_mw'] = pd.to_numeric(df['gen_gas_kr'], errors='coerce')

# PatchTST 입력 피처 — 미래기지값(future) + 자기회귀 타깃
future_features = ['real_demand_land']
for st in SOLAR_STATIONS:
    future_features += [f'solar_rad_{st}', f'total_cloud_{st}', f'midlow_cloud_{st}', f'solar_damping_{st}']
future_features += ['wind_spd_pohang', 'Hour_sin', 'Hour_cos', 'Year_sin', 'Year_cos']
TARGET = 'gas_scaled'   # 정규화 가스(아래에서 생성)
print('future feats', len(future_features), '=', future_features)
""")

code(r"""
# === 타깃 정규화(가스 MW 고정 스케일러) — train(<=2024) 가스>0 으로 fit ===
tr_mask = (df.index < TRAIN_END) & (df['gas_mw'] > 0) & df['gas_mw'].notna()
scaler_y = MinMaxScaler((0, 1)).fit(df.loc[tr_mask, ['gas_mw']].values)
df['gas_scaled'] = scaler_y.transform(df[['gas_mw']].fillna(0).values).ravel()
df['gas_valid'] = (df['gas_mw'] > 0) & df['gas_mw'].notna()   # 윈도 마스크용
print('scaler_y data range (MW):', float(scaler_y.data_min_[0]), '->', float(scaler_y.data_max_[0]))
print('가스>0 비율: train', float(((df.index<TRAIN_END)&df.gas_valid).mean()),
      '| 2026', float(((df.index>=VAL_END)&df.gas_valid).mean()))
""")

code(r"""
class PatchTSTDatasetH(Dataset):
    # past_y/target = gas_scaled, future_numeric = future_features, future_hour = 손실 가중용 시각
    def __init__(self, data_array, hour_array, valid_array, seq_len, pred_len, future_idx, target_idx, offset=0):
        self.data=data_array; self.hour=hour_array; self.valid=valid_array
        self.seq_len=seq_len; self.pred_len=pred_len
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
                'future_y': torch.FloatTensor(fut[:, self.target_idx]),
                'future_hour': torch.FloatTensor(self.hour[s: s + self.pred_len]),
                'future_valid': torch.FloatTensor(self.valid[s: s + self.pred_len])}
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
class DaytimeOverpredictMSE(nn.Module):
    # 낮(09-15h) 과대예측에 ×alpha 페널티 — 봄낮 덕커브 가스급감 과대예측 억제(LGBM v2 비대칭 계승).
    # future_valid(가스>0) 마스크로 결측 타깃 윈도 제외.
    def __init__(self, alpha=4.0, day_lo=9, day_hi=15):
        super().__init__(); self.alpha=alpha; self.day_lo=day_lo; self.day_hi=day_hi
        self.mse = nn.MSELoss(reduction='none')
    def forward(self, pred, batch):
        target = batch['future_y'].to(DEVICE)
        hour = batch['future_hour'].to(DEVICE); valid = batch['future_valid'].to(DEVICE)
        loss_all = self.mse(pred, target); w = valid.clone()        # 결측=0 가중
        day = (hour >= self.day_lo) & (hour <= self.day_hi)
        over = pred > target
        w = torch.where(day & over & (valid > 0), w * self.alpha, w)
        denom = w.sum().clamp_min(1.0)
        return (loss_all * w).sum() / denom
""")

code(r"""
def prepare_split(df, features, future_features, target_col):
    idx = df.index
    tr = df[idx <  TRAIN_END].copy()
    va = df[(idx >= TRAIN_END) & (idx < VAL_END)].copy()
    te = df[idx >= VAL_END].copy()
    scaler_x = MinMaxScaler((0, 1))
    tr[future_features] = scaler_x.fit_transform(tr[future_features])
    va[future_features] = scaler_x.transform(va[future_features]); te[future_features] = scaler_x.transform(te[future_features])
    fidx = [features.index(c) for c in future_features]; tidx = features.index(target_col)
    pack = lambda x: (x[features].values, x['hour'].values, x['gas_valid'].values.astype(float))
    return pack(tr), pack(va), pack(te), scaler_x, fidx, tidx

def train_model(name, tr, va, fidx, tidx, hp, criterion, save_path, offset, epochs=EPOCHS, patience=15):
    num_features = len(fidx) + 1
    tr_arr, tr_hr, tr_vl = tr; va_arr, va_hr, va_vl = va
    model = PatchTST_Weather_Model(num_features, pred_len=PRED_LEN, **hp).to(DEVICE)
    opt = torch.optim.AdamW(model.parameters(), lr=LR, weight_decay=1e-5)
    sch = torch.optim.lr_scheduler.ReduceLROnPlateau(opt, mode='min', factor=0.5, patience=5)
    tr_ds = PatchTSTDatasetH(tr_arr, tr_hr, tr_vl, hp['seq_len'], PRED_LEN, fidx, tidx, offset=offset)
    va_ds = PatchTSTDatasetH(va_arr, va_hr, va_vl, hp['seq_len'], PRED_LEN, fidx, tidx, offset=offset)
    tr_ld = DataLoader(tr_ds, batch_size=BATCH_SIZE, shuffle=True, drop_last=True)
    va_ld = DataLoader(va_ds, batch_size=BATCH_SIZE, shuffle=False)
    best = float('inf'); bad = 0
    print(f'== {name} offset={offset}h | feats={num_features} | train_ds={len(tr_ds)} val_ds={len(va_ds)}')
    for ep in range(1, epochs + 1):
        model.train(); tl = 0.0
        for b in tqdm(tr_ld, desc=f'{name} ep{ep}', leave=False):
            opt.zero_grad(); loss = criterion(model(b), b); loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0); opt.step(); tl += loss.item()
        model.eval(); vl = 0.0
        with torch.no_grad():
            for b in va_ld: vl += criterion(model(b), b).item()
        tl /= len(tr_ld); vl /= max(len(va_ld),1); sch.step(vl)
        if vl < best: best = vl; bad = 0; torch.save(model.state_dict(), save_path)
        else:
            bad += 1
            if bad >= patience: print(f'  early stop @ ep{ep}'); break
    print(f'== {name} done. best val={best:.5f} -> {save_path}')
    return best
""")

code(r"""
features = future_features + [TARGET]
tr, va, te, scaler_x, fidx, tidx = prepare_split(df, features, future_features, TARGET)
joblib.dump(scaler_x, f'{OUT_DIR}/scaler_x_landgas.pkl')
joblib.dump(scaler_y, f'{OUT_DIR}/scaler_y_landgas.pkl')
meta = dict(future_features=future_features, features=features, target='gen_gas_kr (MW)',
            SEQ_LEN=GAS_HP['seq_len'], PRED_LEN=PRED_LEN, GAS_HP=GAS_HP, ALPHA=ALPHA,
            SOLAR_STATIONS=SOLAR_STATIONS, WIND='wind_spd_pohang', K_DAMP=K_DAMP, HORIZONS=HORIZONS,
            TRAIN_END=TRAIN_END, VAL_END=VAL_END,
            note='7-D 수요->가스 직접 PatchTST. 타깃 gas MW MinMax(scaler_y). 서빙시 demand=est_demand_land.')
joblib.dump(meta, f'{OUT_DIR}/metadata_landgas.pkl')

for hname, off in HORIZONS.items():
    print('\n' + '='*60 + f'\nHORIZON {hname} (offset {off}h)')
    train_model(f'GAS_{hname}', tr, va, fidx, tidx, GAS_HP,
                DaytimeOverpredictMSE(ALPHA), f'{OUT_DIR}/best_patchtst_landgas_{hname}.pth', offset=off)
""")

code(r"""
@torch.no_grad()
def eval_horizon(path, hp, te, fidx, tidx, off, num_features):
    arr, hr, vl = te
    m = PatchTST_Weather_Model(num_features, pred_len=PRED_LEN, **hp).to(DEVICE)
    m.load_state_dict(torch.load(path, map_location=DEVICE)); m.eval()
    ds = PatchTSTDatasetH(arr, hr, vl, hp['seq_len'], PRED_LEN, fidx, tidx, offset=off)
    ld = DataLoader(ds, batch_size=256, shuffle=False); P, A, H, V = [], [], [], []
    for b in ld:
        P.append(m(b).cpu().numpy()); A.append(b['future_y'].numpy())
        H.append(b['future_hour'].numpy()); V.append(b['future_valid'].numpy())
    P = np.concatenate(P).ravel(); A = np.concatenate(A).ravel()
    H = np.concatenate(H).ravel(); V = np.concatenate(V).ravel()
    # 정규화 역변환 → MW
    inv = lambda z: scaler_y.inverse_transform(z.reshape(-1,1)).ravel()
    pmw, amw = inv(P), inv(A)
    ok = (V > 0) & np.isfinite(pmw) & np.isfinite(amw) & (amw > 0)
    def mape(a,p): return float(np.mean(np.abs(a-p)/a)*100)
    def bias(a,p): return float(np.mean((p-a)/a)*100)
    day = ok & (H >= 9) & (H <= 15)
    return (mape(amw[ok],pmw[ok]), bias(amw[ok],pmw[ok]),
            mape(amw[day],pmw[day]), bias(amw[day],pmw[day]), int(ok.sum()))

print('PatchTST 직접(수요→가스) TEST 2026 — MW MAPE/bias (전시간 | 낮09-15h):')
print(f'{"지평":>4} | {"전체MAPE":>8} {"bias":>6} | {"낮MAPE":>7} {"낮bias":>6} | {"n":>6}')
for hname, off in HORIZONS.items():
    mp,bi,dmp,dbi,n = eval_horizon(f'{OUT_DIR}/best_patchtst_landgas_{hname}.pth', GAS_HP, te, fidx, tidx, off, len(fidx)+1)
    print(f'{hname:>4} | {mp:7.2f}% {bi:+5.1f} | {dmp:6.2f}% {dbi:+5.1f} | {n:6}')
print('\n비교 기준 = 체인 가스(LGBM v2) 지평별 MAPE (REPORT_7_v2 / horizon_backtest_v2). '
      '낮(09-15h)·봄 구간이 덕커브 핵심 — 직접식 이점은 거기서 드러남.')
""")

code(r"""
import shutil
shutil.make_archive('/content/landgas_patchtst', 'zip', OUT_DIR)
print('zip -> /content/landgas_patchtst.zip (가중치 3개 + scaler_x/scaler_y + metadata)')
try:
    from google.colab import files; files.download('/content/landgas_patchtst.zip')
except Exception: pass
""")

md(r"""
## 산출물 적용
`out/` 산출물을 repo `7. land_gas_forecaster/training/landgas_patchtst/` 에 복사:
```
best_patchtst_landgas_D1.pth / _D2.pth / _D3.pth
scaler_x_landgas.pkl, scaler_y_landgas.pkl, metadata_landgas.pkl
```
그 뒤 Claude 가 **7-D 비교 하니스**로 직접식 PatchTST vs 체인 가스(LGBM v2)를 D+1/2/3,
perfect(실측 demand·기상)+forecast(est_demand_land·forecast_horizon) 두 조건, 낮(09-15h)·봄 분리로 비교.
직접식이 체인 대비 봄낮 MAPE 를 낮추면 G-게이트 상정 후 서빙 편입 검토.
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

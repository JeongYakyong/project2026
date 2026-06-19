# -*- coding: utf-8 -*-
"""전국 수요 PatchTST(final336) 서빙 추론 + 하이브리드 마스크 (라이브 체인·백필 공용).

하이브리드 구조(사용자 확정 06-19):
  - D+1~2  : full PatchTST(final336)
  - D+3~7  : 주간(09~15시)=PatchTST / 야간=LGBM
  - D+8~15 : full LGBM(v2hum)
PatchTST 는 D+1~7 만 추론. LGBM 은 호출측에서 D+1~15 계산.  결합은 combine() 로 시각별 마스크.

서빙 일관: final2/final336 학습과 동일하게 불쾌지수(di)=reh·체감(wct)=wind_spd_10m 로 forecast_horizon
에서 comfort 재구성, 외생만 scaler_exog z-score, 과거는 실측 seq_len(336) 윈도우.
"""
from __future__ import annotations
import os, sqlite3, importlib.util
import numpy as np, pandas as pd, torch, joblib
import torch.nn as nn, torch.nn.functional as F

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, '..'))
DB = os.path.join(ROOT, '1. data_fetcher_and_db', 'data', 'input_data_land.db')
PKL = os.path.join(HERE, 'training', 'landdemand_final336')
DEVICE = 'cpu'
FORE = {'temp': 'temp', 'rh': 'reh', 'wind': 'wind_spd_10m', 'solar': 'radiation', 'cloud': 'total_cloud'}
PATCH_MAX = 7   # PatchTST 사용 최대 지평


def _imp(n, p):
    s = importlib.util.spec_from_file_location(n, p); m = importlib.util.module_from_spec(s); s.loader.exec_module(m); return m
expf = _imp('expf', os.path.join(HERE, 'model', 'exp_features.py')); bht = expf.bht


def comfort(T, RH, Wms):
    di = 0.81*T + 0.01*RH*(0.99*T - 14.3) + 46.3
    Wk = np.clip(Wms*3.6, 4.8, None); wct = 13.12 + 0.6215*T - 11.37*Wk**0.16 + 0.3965*T*Wk**0.16
    return di, np.where(T <= 10, wct, T)


# ── 모델 (final2/final336 구조, 인라인) ──
class _PWA(nn.Module):
    def __init__(self, q, k, h):
        super().__init__(); self.W_Q = nn.Sequential(nn.Linear(q, h), nn.Tanh(), nn.Linear(h, h)); self.W_K = nn.Sequential(nn.Linear(k, h), nn.Tanh(), nn.Linear(h, h)); self.s = 1.0/(h**0.5)
    def forward(self, fw, pw, to):
        Q = self.W_Q(fw).unsqueeze(1); K = self.W_K(pw); a = F.softmax(torch.bmm(Q, K.transpose(1, 2))*self.s, dim=-1); return torch.bmm(a, to).squeeze(1), a
class PatchTST(nn.Module):
    def __init__(self, num_features, seq_len=336, pred_len=24, patch_len=24, stride=12, d_model=256, num_heads=4, num_layers=3, d_ff=1024, dropout=0.2, revin_affine=True):
        super().__init__(); self.patch_len = patch_len; self.stride = stride; self.pred_len = pred_len; self.num_patches = (seq_len-patch_len)//stride+1
        self.patch_embedding = nn.Linear(patch_len*num_features, d_model); self.pos_embedding = nn.Parameter(torch.randn(1, self.num_patches, d_model)); self.dropout = nn.Dropout(dropout)
        enc = nn.TransformerEncoderLayer(d_model, num_heads, d_ff, dropout, batch_first=True, norm_first=True); self.transformer_encoder = nn.TransformerEncoder(enc, num_layers)
        nwf = num_features-1; ff = pred_len*nwf; wp = patch_len*nwf; self.weather_attn = _PWA(ff, wp, d_model)
        self.regressor = nn.Sequential(nn.Linear(d_model+ff, 256), nn.LeakyReLU(0.1), nn.Dropout(dropout), nn.Linear(256, pred_len)); self.weather_bypass = nn.Linear(ff, pred_len)
        self.revin_affine = revin_affine; self.eps = 1e-5
        if revin_affine: self.revin_w = nn.Parameter(torch.ones(1)); self.revin_b = nn.Parameter(torch.zeros(1))
    def forward(self, b):
        pn = b['past_numeric'].to(DEVICE); py = b['past_y'].to(DEVICE); fn = b['future_numeric'].to(DEVICE); B = pn.shape[0]
        mean = py.mean(1, keepdim=True); std = torch.sqrt(py.var(1, keepdim=True, unbiased=False)+self.eps); pyn = (py-mean)/std
        if self.revin_affine: pyn = pyn*self.revin_w+self.revin_b
        xp = torch.cat([pn, pyn], -1); xpp = xp.unfold(1, self.patch_len, self.stride).permute(0, 1, 3, 2).reshape(B, self.num_patches, -1)
        eo = self.transformer_encoder(self.dropout(self.patch_embedding(xpp)+self.pos_embedding)); ff = fn.reshape(B, -1)
        xw = xp[..., :-1].unfold(1, self.patch_len, self.stride).permute(0, 1, 3, 2).reshape(B, self.num_patches, -1); ctx, _ = self.weather_attn(ff, xw, eo)
        on = self.regressor(torch.cat([ctx, ff], 1))+self.weather_bypass(ff)
        if self.revin_affine: on = (on-self.revin_b)/self.revin_w
        return on*std.squeeze(-1)+mean.squeeze(-1), std.squeeze(-1)


@torch.no_grad()
def load_assets():
    """final336 가중치(D1~D7)·scaler·meta 로드."""
    meta = joblib.load(os.path.join(PKL, 'metadata_landdemand_final2.pkl'))
    scaler = joblib.load(os.path.join(PKL, 'scaler_exog.pkl'))
    HP = meta['HP']; EXOG = meta['EXOG']; TIME = meta['TIME']; FF = EXOG + TIME
    models = {}
    for n in range(1, PATCH_MAX+1):
        m = PatchTST(len(FF)+1, pred_len=24, **HP).to(DEVICE)
        m.load_state_dict(torch.load(os.path.join(PKL, f'best_patchtst_landdemand_D{n}.pth'), map_location=DEVICE)); m.eval()
        models[n] = m
    return dict(models=models, scaler=scaler, meta=meta, HP=HP, EXOG=EXOG, TIME=TIME, FF=FF,
                TEMP_SEL=meta['TEMP_SEL'], SOLAR_SEL=meta['SOLAR_SEL'], SEQ=HP['seq_len'])


def _add_time(df, dtv):
    df = df.copy(); idx = df.index
    df['Hour_sin'] = np.sin(2*np.pi*idx.hour/24); df['Hour_cos'] = np.cos(2*np.pi*idx.hour/24)
    df['Doy_sin'] = np.sin(2*np.pi*idx.dayofyear/365); df['Doy_cos'] = np.cos(2*np.pi*idx.dayofyear/365)
    df['is_weekend'] = (np.asarray(dtv) == 'weekend').astype(float); df['is_holiday'] = (np.asarray(dtv) == 'holiday').astype(float)
    return df


def _scale_exog(frame, scaler, EXOG):
    out = frame.copy(); out[EXOG] = scaler.transform(out[EXOG]); return out


def build_history(assets, ppa):
    """실측 과거: 외생 z-score(EXOG)+시간(TIME) FF 배열 + 수요 시계열 (seq 윈도우용)."""
    TEMP_SEL = assets['TEMP_SEL']; SOLAR_SEL = assets['SOLAR_SEL']; EXOG = assets['EXOG']; TIME = assets['TIME']; FF = assets['FF']
    pull = (['timestamp', 'real_demand_land', 'day_type'] + [f'temp_c_{s}' for s in TEMP_SEL]
            + [f'humidity_{s}' for s in TEMP_SEL] + [f'wind_spd_{s}' for s in TEMP_SEL]
            + [f'solar_rad_{s}' for s in SOLAR_SEL] + [f'total_cloud_{s}' for s in SOLAR_SEL])
    with sqlite3.connect(DB) as con:
        raw = pd.read_sql(f"SELECT {', '.join(pull)} FROM historical", con, parse_dates=['timestamp'])
    raw = raw.sort_values('timestamp'); idx = pd.date_range(raw.timestamp.min(), raw.timestamp.max(), freq='h')
    d = raw.set_index('timestamp').reindex(idx); d.index.name = 'timestamp'
    d.loc[d.real_demand_land == 0, 'real_demand_land'] = np.nan
    d['Demand'] = d['real_demand_land'].interpolate('time').ffill().bfill()
    for c in pull[3:]: d[c] = pd.to_numeric(d[c], errors='coerce').interpolate('time', limit=6).ffill().bfill()
    T = d[[f'temp_c_{s}' for s in TEMP_SEL]].mean(1); RH = d[[f'humidity_{s}' for s in TEMP_SEL]].mean(1); W = d[[f'wind_spd_{s}' for s in TEMP_SEL]].mean(1)
    d['temp_c'] = T; d['di'], d['wct'] = comfort(T, RH, W)
    d['solar_rad'] = d[[f'solar_rad_{s}' for s in SOLAR_SEL]].mean(1); d['total_cloud'] = d[[f'total_cloud_{s}' for s in SOLAR_SEL]].mean(1)
    d['cap_btmppa'] = expf.cap_for(d.index, ppa); d['day_type'] = d['day_type'].ffill().bfill()
    d = _add_time(d, d['day_type'].values)
    dsc = _scale_exog(d, assets['scaler'], EXOG)
    return dict(A_sc=dsc[FF], dem=d['Demand'])


def fh_exog(sc, tg, ppa, assets):
    """스크래치 forecast 에서 미래 comfort 외생 재구성 (학습과 동일)."""
    TEMP_SEL = assets['TEMP_SEL']; SOLAR_SEL = assets['SOLAR_SEL']
    cols = sorted(set([f'{FORE["temp"]}_{s}' for s in TEMP_SEL] + [f'{FORE["rh"]}_{s}' for s in TEMP_SEL]
                      + [f'{FORE["wind"]}_{s}' for s in TEMP_SEL] + [f'{FORE["solar"]}_{s}' for s in SOLAR_SEL]
                      + [f'{FORE["cloud"]}_{s}' for s in SOLAR_SEL]))
    ext = pd.date_range(tg.min()-pd.Timedelta(hours=3), tg.max()+pd.Timedelta(hours=3), freq='h')
    sel = ', '.join(f'"{c}"' for c in ['timestamp']+cols)
    fc = pd.read_sql(f'SELECT {sel} FROM forecast WHERE timestamp BETWEEN ? AND ? ORDER BY timestamp',
                     sc, params=(bht._S(ext[0]), bht._S(ext[-1])), parse_dates=['timestamp']).set_index('timestamp')
    fc = fc.apply(pd.to_numeric, errors='coerce').reindex(ext)
    def mi(cs): return fc[cs].mean(1).interpolate('time', limit=3, limit_area='inside').reindex(tg).values
    T = mi([f'{FORE["temp"]}_{s}' for s in TEMP_SEL]); RH = mi([f'{FORE["rh"]}_{s}' for s in TEMP_SEL]); W = mi([f'{FORE["wind"]}_{s}' for s in TEMP_SEL])
    out = pd.DataFrame(index=tg); out['temp_c'] = T; out['di'], out['wct'] = comfort(T, RH, W)
    out['solar_rad'] = mi([f'{FORE["solar"]}_{s}' for s in SOLAR_SEL]); out['total_cloud'] = mi([f'{FORE["cloud"]}_{s}' for s in SOLAR_SEL])
    out['cap_btmppa'] = expf.cap_for(tg, ppa)
    valid = out[['temp_c', 'di', 'wct', 'solar_rad']].notna().all(axis=1)
    return out, valid


@torch.no_grad()
def past_window(hist, O, SEQ):
    """origin O(=base 23:00) 기준 seq_len 과거 윈도우 (past_numeric, past_y) 또는 None."""
    A_sc = hist['A_sc']; dem = hist['dem']
    if O not in A_sc.index: return None
    oi = A_sc.index.get_loc(O)
    if oi-(SEQ-1) < 0: return None
    past = A_sc.iloc[oi-(SEQ-1):oi+1].values.astype(np.float32); py = dem.iloc[oi-(SEQ-1):oi+1].values.astype(np.float32)[:, None]
    if not (np.isfinite(past).all() and np.isfinite(py).all()): return None
    return past, py


@torch.no_grad()
def predict_block(assets, win, sc, O, n, tg, dtv, ppa):
    """지평 n(1~7) 의 24h PatchTST 예측. 결손시 NaN. tg/dtv 는 호출측(체인)과 공유."""
    if win is None or n > PATCH_MAX: return np.full(len(tg), np.nan)
    past, py = win; FF = assets['FF']; EXOG = assets['EXOG']
    wx, valid = fh_exog(sc, tg, ppa, assets)
    Fr = _add_time(wx.assign(_dt=dtv), dtv)
    ok = valid.values & Fr[FF].notna().all(axis=1).values
    pred = np.full(len(tg), np.nan)
    if ok.any():
        Fs = _scale_exog(Fr[FF].ffill().bfill(), assets['scaler'], EXOG)
        out, _ = assets['models'][n]({'past_numeric': torch.from_numpy(past[None]),
                                      'past_y': torch.from_numpy(py[None]),
                                      'future_numeric': torch.from_numpy(Fs.values.astype(np.float32)[None])})
        pr = np.clip(out.numpy().ravel(), 0, None); pr[~ok] = np.nan; pred = pr
    return pred


def use_patch(n, hours):
    """시각별 PatchTST 사용 마스크. D+1~2 full · D+3~7 주간(09~15) · D+8~ 없음."""
    hours = np.asarray(hours)
    if n <= 2: return np.ones(len(hours), bool)
    if n <= PATCH_MAX: return (hours >= 9) & (hours <= 15)
    return np.zeros(len(hours), bool)


def combine(lgbm24, patch24, n, hours):
    """하이브리드 결합: 마스크 위치에서 patch 가 유효하면 patch, 아니면 lgbm 폴백."""
    lg = np.asarray(lgbm24, float); pt = np.asarray(patch24, float)
    m = use_patch(n, hours) & np.isfinite(pt)
    out = lg.copy(); out[m] = pt[m]
    return out

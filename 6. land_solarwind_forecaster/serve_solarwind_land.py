# -*- coding: utf-8 -*-
"""전국 Solar/Wind → net_load 통합 서빙 (6-C). 채널 분리(G-13):

  - SOLAR = PatchTST direct (D+1~D+7, D+12 가중치). 그 외 지평/입력결측은 LGBM(6-A) 폴백.
  - WIND  = LGBM 전 지평(6-A). PatchTST wind 미사용(자기상관 붕괴·forecast 풍속오차 증폭, 비중 작음).
  - 산출 2종: 시장 신재생(→7-A)과 전체 신재생(BTM/PPA 포함 → 7-Ar). 이용률 하나가 둘 다 구동(6-A2).
    total_solar_cap = market_cap + k(1+r)·ppa_cap (6-A2 검증, k·r = btm_ppa_recon_6a2.json).

출력(forecast 테이블, _land 접미사):
  est_solar_util_land, est_wind_util_land,
  est_solar_gen_land(시장), est_wind_gen_land,
  est_market_renew_land(=solar+wind, →7-A net_load),
  est_true_renew_land(+PPA/BTM, →7-Ar), est_true_demand_land(=수요+PPA/BTM, →7-Ar),
  est_net_load_land(=수요 − 시장신재생).

API: predict_land_to_db(origin, horizons=(1..7,12)) / backfill_land_to_db(start,end)
CLI: python serve_solarwind_land.py predict 2026-05-01 --days 1,2,3,4,5,6,7,12
"""
from __future__ import annotations
import os, sys, json, sqlite3
import numpy as np, pandas as pd, torch, joblib, lightgbm as lgb
import torch.nn as nn, torch.nn.functional as F

HERE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.normpath(os.path.join(HERE, '..', '1. data_fetcher_and_db', 'data', 'input_data_land.db'))
PPA_CSV = os.path.normpath(os.path.join(HERE, '..', '1. data_fetcher_and_db', 'second_dataset', 'ppa_scale.csv'))
PT_DIR  = os.path.join(HERE, 'training', 'landsolar_patchtst')
MOD     = os.path.join(HERE, 'model', 'models')
DEVICE  = 'cuda' if torch.cuda.is_available() else 'cpu'

SOLAR_ST = ['yeonggwang', 'seosan', 'pohang']
WIND_ST  = ['daegwallyeong', 'yeonggwang', 'pohang']
SOLAR_PT_HORIZONS = [1, 2, 3, 4, 5, 6, 7, 12]    # 학습된 PatchTST 가중치
LAND_HORIZONS = (1, 2, 3, 4, 5, 6, 7, 12)
DEMAND_COLS = ['est_demand_land', 'land_est_demand_da']   # 5단계 우선 → KPX 폴백
PL = 24

OUT = dict(su='est_solar_util_land', wu='est_wind_util_land', sg='est_solar_gen_land',
           wg='est_wind_gen_land', mr='est_market_renew_land', tr='est_true_renew_land',
           td='est_true_demand_land', nl='est_net_load_land')
OUT_COLS = list(OUT.values())


# ── PatchTST 아키텍처(학습 생성기와 동일) ──
class _Attn(nn.Module):
    def __init__(s, q, k, h):
        super().__init__()
        s.W_Q = nn.Sequential(nn.Linear(q, h), nn.Tanh(), nn.Linear(h, h))
        s.W_K = nn.Sequential(nn.Linear(k, h), nn.Tanh(), nn.Linear(h, h)); s.sf = 1.0/(h**0.5)
    def forward(s, fw, pw, to):
        Q = s.W_Q(fw).unsqueeze(1); K = s.W_K(pw)
        a = F.softmax(torch.bmm(Q, K.transpose(1, 2))*s.sf, dim=-1); return torch.bmm(a, to).squeeze(1), a
class PatchTST_Weather_Model(nn.Module):
    def __init__(s, num_features, seq_len=336, pred_len=24, patch_len=24, stride=12,
                 d_model=128, num_heads=4, num_layers=3, d_ff=512, dropout=0.2):
        super().__init__()
        s.patch_len = patch_len; s.stride = stride; s.seq_len = seq_len; s.pred_len = pred_len
        s.num_patches = (seq_len - patch_len)//stride + 1
        s.patch_embedding = nn.Linear(patch_len*num_features, d_model)
        s.pos_embedding = nn.Parameter(torch.randn(1, s.num_patches, d_model)); s.dropout = nn.Dropout(dropout)
        enc = nn.TransformerEncoderLayer(d_model=d_model, nhead=num_heads, dim_feedforward=d_ff,
                                         dropout=dropout, batch_first=True, norm_first=True)
        s.transformer_encoder = nn.TransformerEncoder(enc, num_layers=num_layers)
        s.num_weather_feats = num_features - 1; ff = pred_len*s.num_weather_feats; wp = patch_len*s.num_weather_feats
        s.weather_attn = _Attn(ff, wp, d_model)
        s.regressor = nn.Sequential(nn.Linear(d_model+ff, 256), nn.LeakyReLU(0.1), nn.Dropout(dropout), nn.Linear(256, pred_len))
        s.weather_bypass = nn.Linear(ff, pred_len)
    def forward(s, b):
        p = b['past_numeric'].to(DEVICE); py = b['past_y'].to(DEVICE); f = b['future_numeric'].to(DEVICE); B = p.shape[0]
        x = torch.cat([p, py], dim=-1)
        xp = x.unfold(1, s.patch_len, s.stride).permute(0, 1, 3, 2).reshape(B, s.num_patches, -1)
        eo = s.transformer_encoder(s.dropout(s.patch_embedding(xp) + s.pos_embedding))
        ffl = f.reshape(B, -1)
        xw = x[..., :-1].unfold(1, s.patch_len, s.stride).permute(0, 1, 3, 2).reshape(B, s.num_patches, -1)
        ctx, _ = s.weather_attn(ffl, xw, eo)
        return s.regressor(torch.cat([ctx, ffl], dim=1)) + s.weather_bypass(ffl)


# ── 자산 로드(메모이즈) ──
_A = None
def load_assets(force=False):
    global _A
    if _A is not None and not force:
        return _A
    meta = joblib.load(os.path.join(PT_DIR, 'metadata_landsolar.pkl'))
    scaler = joblib.load(os.path.join(PT_DIR, 'scaler_landsolar.pkl'))
    FF = meta['future_features_solar']; HP = meta['SOLAR_HP']; SEQ = meta['SEQ_LEN']; K_DAMP = meta['K_DAMP']
    pt = {}
    for n in SOLAR_PT_HORIZONS:
        p = os.path.join(PT_DIR, f'best_patchtst_landsolar_D{n}.pth')
        if not os.path.exists(p): continue
        m = PatchTST_Weather_Model(len(FF)+1, pred_len=PL, **HP).to(DEVICE)
        m.load_state_dict(torch.load(p, map_location=DEVICE)); m.eval(); pt[n] = m
    m_solar = lgb.Booster(model_file=os.path.join(MOD, 'lgbm_land_solar_util.txt'))
    m_wind  = lgb.Booster(model_file=os.path.join(MOD, 'lgbm_land_wind_util.txt'))
    m6a = json.load(open(os.path.join(MOD, 'model_meta_6a.json'), encoding='utf-8'))
    recon = json.load(open(os.path.join(MOD, 'btm_ppa_recon_6a2.json'), encoding='utf-8'))
    # ppa_cap(월)
    ppa = pd.read_csv(PPA_CSV, encoding='cp949'); ppa['ym'] = pd.to_datetime(ppa['기간'], format='%b-%y').dt.to_period('M')
    ppa = ppa.rename(columns={'PPA 계': 'ppa_cap'}).dropna(subset=['ppa_cap']).set_index('ym')['ppa_cap'].sort_index()
    # 기상 기후값 폴백(월,시) — historical train(≤2024) 평균
    canon = []
    for st in SOLAR_ST: canon += [f'solar_rad_{st}', f'total_cloud_{st}', f'midlow_cloud_{st}', f'rainfall_{st}']
    for st in WIND_ST:  canon += [f'wind_spd_{st}', f'wd_sin_{st}', f'wd_cos_{st}']
    canon = list(dict.fromkeys(canon))
    with sqlite3.connect(DB_PATH) as con:
        h = pd.read_sql(f"SELECT timestamp, {', '.join(canon)} FROM historical WHERE timestamp < '2025-01-01'",
                        con, parse_dates=['timestamp']).set_index('timestamp')
    h = h.apply(pd.to_numeric, errors='coerce')
    wx_clim = h.groupby([h.index.month, h.index.hour]).mean()
    _A = dict(pt=pt, scaler=scaler, FF=FF, SEQ=SEQ, K_DAMP=K_DAMP, HP=HP,
              m_solar=m_solar, m_wind=m_wind, SOLAR_FEATS=m6a['solar_feats'], WIND_FEATS=m6a['wind_feats'],
              k=recon['k'], r=recon['r'], ppa=ppa, wx_clim=wx_clim, canon=canon)
    return _A


def _conn(): return sqlite3.connect(DB_PATH)
def _S(t): return t.strftime('%Y-%m-%d %H:%M:%S')


def _damping_series(idx, rain, k):
    s = pd.Series(rain.values, index=idx).between_time('06:00', '20:00'); d = s.groupby(s.index.date).sum()
    return np.exp(-k * pd.Series(idx.date, index=idx).map(d).clip(upper=20).astype(float).values)


def _read(con, table, t0, t1, cols):
    sel = ', '.join(f'"{c}"' for c in ['timestamp'] + cols)
    df = pd.read_sql(f'SELECT {sel} FROM {table} WHERE timestamp BETWEEN ? AND ? ORDER BY timestamp',
                     con, params=(t0, t1), parse_dates=['timestamp']).set_index('timestamp')
    return df.apply(pd.to_numeric, errors='coerce')


# ── 대상일 기상(forecast 우선·기후값 폴백): canon raw 컬럼 24h ──
def _day_weather(con, day, A):
    idx = pd.date_range(day, periods=PL, freq='h')
    fmap = {}
    for st in SOLAR_ST:
        fmap[f'radiation_{st}'] = f'solar_rad_{st}'; fmap[f'total_cloud_{st}'] = f'total_cloud_{st}'
        fmap[f'midlow_cloud_{st}'] = f'midlow_cloud_{st}'; fmap[f'rainfall_{st}'] = f'rainfall_{st}'
    for st in WIND_ST:
        fmap[f'wind_spd_10m_{st}'] = f'wind_spd_{st}'; fmap[f'wd_sin_10m_{st}'] = f'wd_sin_{st}'; fmap[f'wd_cos_10m_{st}'] = f'wd_cos_{st}'
    f = _read(con, 'forecast', _S(idx[0]), _S(idx[-1]), list(fmap)).rename(columns=fmap).reindex(idx)
    need = A['canon']; src = 'forecast'
    if len(f) < PL or f[need].isna().any().any():
        fill = pd.DataFrame({c: [A['wx_clim'].loc[(t.month, t.hour), c] for t in idx] for c in need}, index=idx)
        for c in need: f[c] = f[c].fillna(fill[c]) if c in f else fill[c]
        src = 'clim' if (c not in f or f[need].isna().all().all()) else 'forecast+clim'
    return f[need], src


# ── SOLAR PatchTST direct (origin까지 과거 hist + 대상일 forecast) ──
def _solar_pt(con, origin, n, A):
    FF, SEQ, k = A['FF'], A['SEQ'], A['K_DAMP']
    d = pd.Timestamp(origin).normalize() + pd.Timedelta(days=n)
    offset = (n-1)*24
    first = d - pd.Timedelta(hours=offset+SEQ); last_past = d - pd.Timedelta(hours=offset+1)
    hist_cols = []
    for st in SOLAR_ST: hist_cols += [f'solar_rad_{st}', f'total_cloud_{st}', f'midlow_cloud_{st}', f'rainfall_{st}']
    past = _read(con, 'historical', _S(first), _S(last_past), hist_cols + ['gen_solar_utilization_kr'])
    if len(past) < SEQ or past['gen_solar_utilization_kr'].isna().any():
        raise ValueError(f'past 부족/NaN ({len(past)}/{SEQ})')
    wx, _ = _day_weather(con, d, A)
    fut = wx[hist_cols]
    comb = pd.concat([past[hist_cols], fut]).sort_index().interpolate(limit=3).ffill().bfill()
    M = pd.DataFrame(index=comb.index)
    for st in SOLAR_ST:
        M[f'solar_rad_{st}'] = comb[f'solar_rad_{st}']; M[f'total_cloud_{st}'] = comb[f'total_cloud_{st}']
        M[f'midlow_cloud_{st}'] = comb[f'midlow_cloud_{st}']
        M[f'solar_damping_{st}'] = _damping_series(comb.index, comb[f'rainfall_{st}'], k)
    M['Hour_sin'] = np.sin(2*np.pi*M.index.hour/24); M['Hour_cos'] = np.cos(2*np.pi*M.index.hour/24)
    Sc = pd.DataFrame(A['scaler'].transform(M[FF]), index=M.index, columns=FF)
    past_idx = Sc.index[Sc.index <= last_past][-SEQ:]; fut_idx = pd.date_range(d, periods=PL, freq='h')
    pn = Sc.reindex(past_idx)[FF].values; fn = Sc.reindex(fut_idx)[FF].values
    py = past['gen_solar_utilization_kr'].reindex(past_idx).values.reshape(-1, 1)
    if np.isnan(pn).any() or np.isnan(fn).any() or np.isnan(py).any(): raise ValueError('scaled NaN')
    b = {'past_numeric': torch.FloatTensor(pn).unsqueeze(0), 'past_y': torch.FloatTensor(py).unsqueeze(0),
         'future_numeric': torch.FloatTensor(fn).unsqueeze(0)}
    with torch.no_grad(): return np.clip(A['pt'][n](b).squeeze(0).cpu().numpy(), 0, 1)


# ── LGBM 피처(평균) 빌드 ──
def _lgbm_feats(wx, A):
    d = pd.DataFrame(index=wx.index)
    d['solar_rad'] = wx[[f'solar_rad_{s}' for s in SOLAR_ST]].mean(1)
    d['total_cloud'] = wx[[f'total_cloud_{s}' for s in SOLAR_ST]].mean(1)
    d['solar_damping'] = _damping_series(wx.index, wx[[f'rainfall_{s}' for s in SOLAR_ST]].mean(1), A['K_DAMP'])
    d['wind_spd'] = wx[[f'wind_spd_{s}' for s in WIND_ST]].mean(1)
    d['wd_sin'] = wx[[f'wd_sin_{s}' for s in WIND_ST]].mean(1); d['wd_cos'] = wx[[f'wd_cos_{s}' for s in WIND_ST]].mean(1)
    d['hour_sin'] = np.sin(2*np.pi*d.index.hour/24); d['hour_cos'] = np.cos(2*np.pi*d.index.hour/24)
    d['doy_sin'] = np.sin(2*np.pi*d.index.dayofyear/365); d['doy_cos'] = np.cos(2*np.pi*d.index.dayofyear/365)
    return d


def _latest(con, day, cap_col):
    t0 = _S(pd.Timestamp(day) - pd.Timedelta(hours=1440)); t1 = _S(pd.Timestamp(day) - pd.Timedelta(hours=1))
    s = pd.to_numeric(pd.read_sql(f'SELECT "{cap_col}" FROM historical WHERE timestamp BETWEEN ? AND ?',
                                  con, params=(t0, t1))[cap_col], errors='coerce').dropna()
    return float(s.iloc[-1]) if len(s) else None


def _demand(con, idx):
    cols = [c[1] for c in con.execute('PRAGMA table_info(forecast)')]
    for dc in DEMAND_COLS:
        if dc not in cols: continue
        s = pd.to_numeric(_read(con, 'forecast', _S(idx[0]), _S(idx[-1]), [dc])[dc], errors='coerce').reindex(idx)
        if s.notna().any(): return s.values, dc
    return np.full(len(idx), np.nan), None


def _predict_day(con, origin, n, A):
    d = pd.Timestamp(origin).normalize() + pd.Timedelta(days=n)
    idx = pd.date_range(d, periods=PL, freq='h')
    wx, wsrc = _day_weather(con, d, A)
    feat = _lgbm_feats(wx, A)
    # SOLAR: PatchTST 우선, 실패 시 LGBM 폴백
    ssrc = 'patchtst'
    try:
        if n not in A['pt']: raise ValueError('no PT weight')
        su = _solar_pt(con, origin, n, A)
    except Exception:
        su = np.clip(A['m_solar'].predict(feat[A['SOLAR_FEATS']].values), 0, 1); ssrc = 'lgbm'
    wu = np.clip(A['m_wind'].predict(feat[A['WIND_FEATS']].values), 0, 1)
    # 용량
    scap = _latest(con, d, 'gen_solar_capacity_kr'); wcap = _latest(con, d, 'gen_wind_capacity_kr')
    if scap is None or wcap is None: raise ValueError('capacity 추정 불가')
    ppa_cap = float(A['ppa'].reindex([d.to_period('M')]).ffill().iloc[0]) if len(A['ppa']) else 0.0
    if not np.isfinite(ppa_cap):
        ppa_cap = float(A['ppa'].iloc[-1])
    total_cap = scap + A['k']*(1+A['r'])*ppa_cap
    # 발전·신재생·net_load
    sg = su*scap; wg = wu*wcap                       # 시장 태양광·풍력
    market_renew = sg + wg
    true_solar = su*total_cap; true_renew = true_solar + wg
    ppabtm = su*A['k']*(1+A['r'])*ppa_cap
    dem, dsrc = _demand(con, idx)
    net_load = dem - market_renew
    true_demand = dem + ppabtm
    out = pd.DataFrame({'timestamp': idx.strftime('%Y-%m-%d %H:%M:%S'),
        OUT['su']: su.round(4), OUT['wu']: wu.round(4), OUT['sg']: sg.round(2), OUT['wg']: wg.round(2),
        OUT['mr']: market_renew.round(2), OUT['tr']: true_renew.round(2),
        OUT['td']: np.round(true_demand, 2), OUT['nl']: np.round(net_load, 2)})
    return out, ssrc, wsrc, dsrc


def _upsert(con, out):
    cols = [c[1] for c in con.execute('PRAGMA table_info(forecast)')]
    for c in OUT_COLS:
        if c not in cols: con.execute(f'ALTER TABLE forecast ADD COLUMN "{c}" REAL')
    setc = ', '.join(f'"{c}"=excluded."{c}"' for c in OUT_COLS)
    colc = ', '.join(f'"{c}"' for c in ['timestamp'] + OUT_COLS)
    ph = ', '.join(['?']*(1+len(OUT_COLS)))
    rows = [tuple([r['timestamp']] + [None if pd.isna(r[c]) else float(r[c]) for c in OUT_COLS]) for _, r in out.iterrows()]
    con.executemany(f'INSERT INTO forecast ({colc}) VALUES ({ph}) ON CONFLICT("timestamp") DO UPDATE SET {setc}', rows)


def predict_land_to_db(origin, horizons=LAND_HORIZONS, write=True, verbose=True) -> pd.DataFrame:
    A = load_assets(); o = pd.Timestamp(origin).normalize(); outs = []
    with _conn() as con:
        for n in horizons:
            try:
                out, ssrc, wsrc, dsrc = _predict_day(con, o, n, A)
            except Exception as e:
                if verbose: print(f'  skip D+{n}: {str(e)[:70]}')
                continue
            o2 = out.copy(); o2.insert(1, 'horizon', n); o2['solar_src'] = ssrc; outs.append(o2)
            if write: _upsert(con, out)
            if verbose:
                nl = out[OUT['nl']]; tr = out[OUT['tr']]
                print(f'  D+{n} {(o+pd.Timedelta(days=n)).date()} | solar={ssrc} wind=lgbm dem={dsrc} | '
                      f"net_load {('NaN' if nl.isna().all() else f'{nl.mean():.0f}MW')} | true_renew {tr.mean():.0f}MW")
        if write: con.commit()
    if verbose: print(f'[DB] forecast ← origin {o.date()} | {len(outs)}지평 ({"write" if write else "no-write"})')
    return pd.concat(outs, ignore_index=True) if outs else pd.DataFrame()


def backfill_land_to_db(start, end, horizons=LAND_HORIZONS, verbose=True):
    A = load_assets(); days = pd.date_range(pd.Timestamp(start).normalize(), pd.Timestamp(end).normalize(), freq='D'); done = 0
    with _conn() as con:
        for o in days:
            for n in horizons:
                try:
                    out, *_ = _predict_day(con, o, n, A); _upsert(con, out); done += 1
                except Exception:
                    pass
        con.commit()
    if verbose: print(f'[backfill] {days[0].date()}~{days[-1].date()} | {len(days)}발행일×{len(horizons)}지평, {done}건')


if __name__ == '__main__':
    import argparse
    try: sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception: pass
    p = argparse.ArgumentParser(description='전국 solar/wind 서빙(solar=PatchTST, wind=LGBM)')
    sub = p.add_subparsers(dest='cmd', required=True)
    pp = sub.add_parser('predict'); pp.add_argument('origin'); pp.add_argument('--days', default='1,2,3,4,5,6,7,12'); pp.add_argument('--no-write', action='store_true')
    bf = sub.add_parser('backfill'); bf.add_argument('start'); bf.add_argument('end'); bf.add_argument('--days', default='1,2,3,4,5,6,7,12')
    a = p.parse_args()
    hz = tuple(int(x) for x in a.days.split(','))
    if a.cmd == 'predict': predict_land_to_db(a.origin, horizons=hz, write=not a.no_write)
    else: backfill_land_to_db(a.start, a.end, horizons=hz)

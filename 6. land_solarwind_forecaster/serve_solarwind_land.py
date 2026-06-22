# -*- coding: utf-8 -*-
"""전국 Solar/Wind → net_load 통합 서빙 (6-C). 채널 분리(G-13) + 장지평 재훈련(2026-06-22):

  - SOLAR = PatchTST(D1-6) ↔ 신규 LGBM(_final, D7-15) 부드러운 블렌딩(D7 교차, _blend_w).
            단지평은 PatchTST 우위, 장지평은 지평인지+평년앵커 LGBM 우위(정직 검증). PatchTST 입력결측은 LGBM 단독.
  - WIND  = 신규 LGBM(_final) 전 지평(지평인지+평년앵커, 2지점 대관령·영광).
  - 산출 2종: 시장 신재생(→7-A)과 전체 신재생(BTM/PPA 포함 → 7-Ar). 이용률 하나가 둘 다 구동(6-A2).
    total_solar_cap = market_cap + k(1+r)·ppa_cap (6-A2 검증, k·r = btm_ppa_recon_6a2.json).

출력(forecast 테이블, _land 접미사):
  est_solar_util_land, est_wind_util_land,
  est_solar_gen_land(시장), est_wind_gen_land,
  est_market_renew_land(=solar+wind, →7-A net_load),
  est_true_renew_land(+PPA/BTM, →7-Ar), est_true_demand_land(=수요+PPA/BTM, →7-Ar),
  est_net_load_land(=수요 − 시장신재생).

사용: 통합 체인 serve_chain_land_new.py 가 load_assets()·_predict_day() 를 import 해 호출한다.
  (옛 단독 실행 진입점 predict_land_to_db/backfill_land_to_db 는 체인과 중복이라 제거됨, 2026-06-19.)
"""
from __future__ import annotations
import os, sys, json, sqlite3
import numpy as np, pandas as pd, torch, joblib, lightgbm as lgb
import torch.nn as nn, torch.nn.functional as F

HERE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.normpath(os.path.join(HERE, '..', '1. data_fetcher_and_db', 'data', 'input_data_land.db'))
PPA_CSV = os.path.normpath(os.path.join(HERE, '..', '1. data_fetcher_and_db', 'second_dataset', 'ppa_scale.csv'))
PT_DIR  = os.path.join(HERE, 'training', 'landsolar504')
MOD     = os.path.join(HERE, 'model', 'models')
DEVICE  = 'cuda' if torch.cuda.is_available() else 'cpu'

SOLAR_ST = ['yeonggwang', 'seosan', 'pohang']
WIND_ST  = ['daegwallyeong', 'yeonggwang', 'pohang']
SOLAR_PT_HORIZONS = list(range(1, 16))    # landsolar504 = D+1..D+15 PatchTST 가중치(단지평 D1-6 사용·블렌딩)
LAND_HORIZONS = tuple(range(1, 16))    # D+1..D+15 연속
DEMAND_COLS = ['est_demand_land', 'land_est_demand_da']   # 5단계 우선 → KPX 폴백
PL = 24

# ── 장지평 LGBM(_final): 태양광=PatchTST(D1-6)와 블렌딩 / 풍력=전 지평 ─────────────
#   2026-06-22 재훈련.  지평 인지(horizon_d)+평년(기후값) 앵커로 '멀어질수록 평년 수축'을
#   모델이 직접 학습(손튜닝 블렌딩 가중치 없음).  정직 비교(대상시각 교차검증·전진분할)에서
#   태양광 D7+ -9~-21%p, 풍력 전 지평(전진 70.0→50.2%) 개선 확인.  검증=training/_train_lgbm_lh.py.
LH_SOLAR_ST = ['pohang', 'yeonggwang', 'seosan']     # 태양광 3지점(사용자 확정)
LH_WIND_ST  = ['daegwallyeong', 'yeonggwang']        # 풍력 2지점(사용자 확정)
LH_KDAMP = 0.3
LH_DAY_THR = 0.01                                    # 낮 판정: 평년 태양광 이용률 > 1%
LH_SOLAR_FEATS = ([f'{p}_{st}' for st in LH_SOLAR_ST
                   for p in ('radiation', 'total_cloud', 'midlow_cloud', 'solar_damping')]
                  + ['clim_solar', 'season_grp', 'hour_sin', 'hour_cos', 'horizon_d'])
LH_WIND_FEATS = ([f'{p}_{st}' for st in LH_WIND_ST
                  for p in ('wind_spd_10m', 'wd_sin_10m', 'wd_cos_10m')]
                 + ['clim_wind', 'season_grp', 'hour_sin', 'hour_cos', 'horizon_d'])


def _season_grp(m):              # 가을(10,11)=봄과 한 묶음(사용자 확정)
    if m in (12, 1, 2): return 0
    if m in (6, 7, 8, 9): return 2
    return 1


def _blend_w(n):                 # 태양광 PatchTST→LGBM 인수인계: D5→0, D7→0.5(교차), D9→1
    return float(np.clip((n - 5) / 4.0, 0.0, 1.0))

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
    # 신규 장지평 LGBM(_final) + 메타(피처·평년앵커·낮판정).  옛 _util LGBM 은 nouse 로 이관.
    solar_lgb = lgb.Booster(model_file=os.path.join(MOD, 'lgbm_land_solar_final.txt'))
    wind_lgb  = lgb.Booster(model_file=os.path.join(MOD, 'lgbm_land_wind_final.txt'))
    lh = json.load(open(os.path.join(MOD, 'lh_final_meta.json'), encoding='utf-8'))
    clim_solar = {tuple(int(x) for x in k.split('-')): float(v) for k, v in lh['clim_solar'].items()}
    clim_wind  = {tuple(int(x) for x in k.split('-')): float(v) for k, v in lh['clim_wind'].items()}
    recon = json.load(open(os.path.join(MOD, 'btm_ppa_recon_6a2.json'), encoding='utf-8'))
    # ppa_cap(월)
    ppa = pd.read_csv(PPA_CSV, encoding='cp949'); _g = ppa['기간'].astype(str)
    ppa['ym'] = pd.to_datetime(_g, format='%Y-%m-%d', errors='coerce').fillna(
                pd.to_datetime(_g, format='%b-%y', errors='coerce')).dt.to_period('M')   # ISO/%b-%y 양형식 허용
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
              solar_lgb=solar_lgb, wind_lgb=wind_lgb,
              SOLAR_FEATS=lh['solar_feats'], WIND_FEATS=lh['wind_feats'],
              clim_solar=clim_solar, clim_wind=clim_wind, DAY_THR=float(lh.get('day_thr', LH_DAY_THR)),
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
    # D+5.5(135h) 이후 forecast 는 3h 행만 존재(KIMG 1h 해상도 한계).  4h 이내
    # 구멍은 양옆 실예보의 시간 보간이 기후값보다 정확하므로 기후값 폴백 전에
    # 먼저 메운다 (limit=3 = 앵커 간격 4h 까지만, 신뢰성 한계.  limit_area=
    # 'inside' 로 예보 범위 밖 외삽 금지).  경계 시간(00시/23시)도 보간되도록
    # ±3h 확장 조회 후 대상일로 트림.
    ext = pd.date_range(idx[0] - pd.Timedelta(hours=3), idx[-1] + pd.Timedelta(hours=3), freq='h')
    f = _read(con, 'forecast', _S(ext[0]), _S(ext[-1]), list(fmap)).rename(columns=fmap).reindex(ext)
    f = f.interpolate(method='time', limit=3, limit_area='inside').reindex(idx)
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


# ── 장지평 LGBM 피처 빌드(학습기 _gen_lgbm_lh 와 서빙 공용 SSOT) ──
def _build_lh_feats(wx, n, ctx):
    """그날 기상(wx, 24h) + 평년앵커(월×시각) + 달력 → LGBM 피처.  학습·서빙이 같은 이
    함수를 써서 train-serve 일치 보장.  wx 컬럼 = _day_weather 출력(solar_rad_/total_cloud_/
    midlow_cloud_/rainfall_/wind_spd_/wd_sin_/wd_cos_).  ctx = clim_solar/clim_wind 보유(A 또는 학습 ctx)."""
    idx = wx.index
    hr = np.asarray(idx.hour); mo = np.asarray(idx.month)
    M = pd.DataFrame(index=idx)
    day_m = (hr >= 6) & (hr <= 20)
    for st in LH_SOLAR_ST:
        M[f'radiation_{st}'] = np.asarray(wx[f'solar_rad_{st}'], float)
        M[f'total_cloud_{st}'] = np.asarray(wx[f'total_cloud_{st}'], float)
        M[f'midlow_cloud_{st}'] = np.asarray(wx[f'midlow_cloud_{st}'], float)
        rsum = float(np.nansum(np.asarray(wx[f'rainfall_{st}'], float)[day_m]))   # 그날 주간 강수합
        M[f'solar_damping_{st}'] = float(np.exp(-LH_KDAMP * min(max(rsum, 0.0), 20.0)))
    for st in LH_WIND_ST:
        M[f'wind_spd_10m_{st}'] = np.asarray(wx[f'wind_spd_{st}'], float)
        M[f'wd_sin_10m_{st}'] = np.asarray(wx[f'wd_sin_{st}'], float)
        M[f'wd_cos_10m_{st}'] = np.asarray(wx[f'wd_cos_{st}'], float)
    cs = ctx['clim_solar']; cw = ctx['clim_wind']
    M['clim_solar'] = [cs.get((int(a), int(b)), np.nan) for a, b in zip(mo, hr)]
    M['clim_wind']  = [cw.get((int(a), int(b)), np.nan) for a, b in zip(mo, hr)]
    M['season_grp'] = np.array([_season_grp(int(a)) for a in mo], dtype='int32')
    M['hour_sin'] = np.sin(2*np.pi*hr/24); M['hour_cos'] = np.cos(2*np.pi*hr/24)
    M['horizon_d'] = int(n)
    return M


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
    F = _build_lh_feats(wx, n, A)
    # WIND: 신규 LGBM(전 지평)
    wu = np.clip(A['wind_lgb'].predict(F[A['WIND_FEATS']]), 0, 1)
    # SOLAR LGBM(낮만 예측, 밤=0)
    is_day = np.asarray(F['clim_solar'], float) > A['DAY_THR']
    su_lgb = np.where(is_day, np.clip(A['solar_lgb'].predict(F[A['SOLAR_FEATS']]), 0, 1), 0.0)
    # SOLAR: PatchTST(D1-6) ↔ LGBM(D7-15) 부드러운 블렌딩(D7 교차)
    w = _blend_w(n); ssrc = f'lgb(w{w:.2f})'
    if w < 1.0:
        try:
            if n not in A['pt']: raise ValueError('no PT weight')
            su_patch = _solar_pt(con, origin, n, A)
            su = (1.0 - w) * su_patch + w * su_lgb; ssrc = f'patch{1-w:.2f}+lgb{w:.2f}'
        except Exception:
            su = su_lgb; ssrc = 'lgb(patch실패)'
    else:
        su = su_lgb
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


# 직접 실행(standalone) 진입점은 제거됨(2026-06-19) — 통합 체인 serve_chain_land_new.py 가
# load_assets()·_predict_day() 를 import 해 5→6→7 을 한 번에 돌리고 est_horizon_land 에 쓴다.
# 옛 predict_land_to_db / backfill_land_to_db / _upsert(forecast 테이블 적재)는 체인과 중복이라
# 삭제했다.  이 파일은 이제 체인이 쓰는 라이브러리(모델·예측 함수)로만 남는다.

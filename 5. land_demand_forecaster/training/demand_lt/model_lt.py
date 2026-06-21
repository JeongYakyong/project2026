# -*- coding: utf-8 -*-
"""anchor-residual PatchTST (patchtst_lt v2) — 전국 수요 D+1..D+15 단일구조 모델.

설계 동기(기존 final336 장기 열화 진단):
  · base-window 평균으로 타깃을 RevIN 역정규화 → 8~15일 뒤 수요 레벨 드리프트를 못 따라가 +bias.
  · 인코더가 최근 자기상관에 과의존 → 2주 뒤엔 예보가능신호(미래기상·달력)를 덜 씀.

v2 핵심 변경(EDA 근거, 2026-06-20):
  1) anchor = **daytype_match** — 타깃과 같은 (주말·공휴일 상태) 인 same-DOW 가까운 2주 평균.
     기존 "주 단위 lag 평균" 은 타깃이 공휴일인데 참조주가 평일이면 +19~25% 과대(레벨 오염).
     daytype_match 로 공휴일 bias ~0, 평상시·전 지평도 일관 개선.
  2) **climatology 입력** — (월,시,요일타입) 평균(train) 을 anchor 와 나란히 헤드에 주입.
     anchor(저편향·고분산) ↔ climatology(고편향·저분산) 의 최적 비중을 모델이 지평별로 학습
     → 장기에서 늙은 anchor 의 노이즈를 기후값으로 수축(shrink).
  3) **공휴일 캘린더** = holidays.SouthKorea — 과거/미래 모두 is_holiday·daytype 결정적.
  4) 기상 = temp_c · humidity · solar_rad 3개(di/wct/total_cloud/cap_solar 제거). 습도 날것.
  5) exog scaler = RobustScaler(train_lt 에서). 가중치 D1..D15 15벌 유지.

train/serve 공용. 학습 산출: metadata_lt.pkl(+CLIM 테이블) + scaler_exog.pkl + best_lt_D{1..15}.pth.
"""
from __future__ import annotations
import os, sqlite3, math, json
import numpy as np, pandas as pd
import torch, torch.nn as nn, torch.nn.functional as F
import holidays as _holidays

VERSION = 'lt-v4 (daytype_match anchor + recent-climatology, temp/humidity/solar, RobustScaler)'

TEMP_SEL = ['wonju', 'seosan', 'pohang', 'yeonggwang']      # 인구권 4지점(대관령 무인 제외)
SOLAR_SEL = ['seosan', 'yeonggwang']                         # 태양광 집중지
EXOG = ['temp_c', 'humidity', 'solar_rad']                   # 전역 스케일 대상(RobustScaler)
TIME = ['Hour_sin', 'Hour_cos', 'Doy_sin', 'Doy_cos', 'is_weekend', 'is_holiday']
FW = EXOG + TIME                       # 미래/과거 공변량 = 9
PRED_LEN = 24
HORIZONS = {n: (n - 1) * 24 for n in range(1, 16)}   # 지평 n → offset(h)
CLIM_WEEKS = 13                        # 최근 기후값 = 같은요일·요일타입 최근 K주 평균(정직-lag)
SEASON = {12: '겨울', 1: '겨울', 2: '겨울', 3: '봄', 4: '봄', 5: '봄', 6: '여름', 7: '여름', 8: '여름',
          9: '가을', 10: '가을', 11: '가을'}   # post-hoc bias 보정 키(계절)
# 지평 5구간(초단 D1-3 / 단 D4-6 / 중 D7-9 / 중장 D10-12 / 장 D13-15) — 보정 키(지평)
HGRP5 = {n: ('초단' if n <= 3 else '단' if n <= 6 else '중' if n <= 9 else '중장' if n <= 12 else '장')
         for n in range(1, 16)}


def calib_key(month, hour, n):
    return f'{SEASON[month]}_{hour}_{HGRP5[n]}'

# (cap_ppa 피처는 제거 — 밤 과억제·용량 외삽 불안정으로 v4 에서 폐기. recent-clim 이 낮 staleness 를 담당.)


# ─────────────────── 공휴일 캘린더 ───────────────────
_KRH = {}
def _kr_holidays(years):
    key = tuple(sorted(set(years)))
    if key not in _KRH:
        _KRH[key] = _holidays.SouthKorea(years=list(key))
    return _KRH[key]


def holiday_flags(dtindex):
    """DatetimeIndex → (is_weekend, is_holiday) float 배열. 결정적(과거·미래 동일 규칙)."""
    dtindex = pd.DatetimeIndex(dtindex)
    yrs = range(int(dtindex.year.min()), int(dtindex.year.max()) + 1)
    kr = _kr_holidays(yrs)
    dates = dtindex.normalize()
    is_hol = np.fromiter((d.date() in kr for d in dates), dtype=bool, count=len(dates)).astype(float)
    is_wknd = (dtindex.dayofweek >= 5).astype(float)
    return is_wknd, is_hol


def daytype_code(is_wknd, is_hol):
    """0 평일 / 1 주말 / 2 공휴일."""
    return np.where(np.asarray(is_hol) > 0, 2, np.where(np.asarray(is_wknd) > 0, 1, 0)).astype(int)


# ─────────────────── 피처 빌더 ───────────────────
def build_features(df):
    """raw(historical 스키마) → 모델 피처 프레임. 시간격자 보간 포함.
    필요한 raw 컬럼: real_demand_land, temp_c_{TEMP_SEL}, humidity_{TEMP_SEL}, solar_rad_{SOLAR_SEL}.
    """
    df = df.copy()
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    df = df.set_index('timestamp').sort_index()
    idx = pd.date_range(df.index.min(), df.index.max(), freq='h')
    df = df.reindex(idx); df.index.name = 'timestamp'
    df.loc[df['real_demand_land'] == 0, 'real_demand_land'] = np.nan
    df['Demand'] = df['real_demand_land'].interpolate('time').ffill().bfill()
    df['temp_c'] = df[[f'temp_c_{s}' for s in TEMP_SEL]].mean(1).interpolate('time', limit=6).ffill().bfill()
    df['humidity'] = df[[f'humidity_{s}' for s in TEMP_SEL]].mean(1).interpolate('time', limit=6).ffill().bfill()
    df['solar_rad'] = df[[f'solar_rad_{s}' for s in SOLAR_SEL]].mean(1).interpolate('time', limit=6).ffill().bfill()
    df['Hour_sin'] = np.sin(2 * np.pi * df.index.hour / 24); df['Hour_cos'] = np.cos(2 * np.pi * df.index.hour / 24)
    df['Doy_sin'] = np.sin(2 * np.pi * df.index.dayofyear / 365); df['Doy_cos'] = np.cos(2 * np.pi * df.index.dayofyear / 365)
    is_wknd, is_hol = holiday_flags(df.index)
    df['is_weekend'] = is_wknd; df['is_holiday'] = is_hol
    return df


# ─────────────────── anchor (daytype_match) ───────────────────
def anchor_w0(offset):
    """지평 offset(h) 의 가장 가까운 honest 주 수(lag*168 ≥ offset+24 보장 → 타깃-lag ≤ origin)."""
    return max(1, math.ceil((offset + PRED_LEN) / 168))


def compute_anchor(demand, is_hol, is_wkd, offset, K=8):
    """honest daytype_match 앵커: 타깃과 같은 (주말·공휴일) 상태인 same-DOW 가까운 주 최대 2개 평균.
    demand/is_hol/is_wkd 는 시간격자 정렬 np.array. 가용 lag 부족 시 NaN.
    """
    demand = np.asarray(demand, float)
    is_hol = np.asarray(is_hol); is_wkd = np.asarray(is_wkd)
    N = len(demand); w0 = anchor_w0(offset); t = np.arange(N)
    picks = []
    for j in range(K):
        Lh = 168 * (w0 + j); src = t - Lh; ok = src >= 0
        val = np.full(N, np.nan); match = np.zeros(N, bool)
        match[ok] = (is_hol[src[ok]] == is_hol[ok]) & (is_wkd[src[ok]] == is_wkd[ok])
        val[match] = demand[src[match]]
        picks.append(val)
    stack = np.vstack(picks)                          # (K, N) 가까운 주부터
    fin = np.isfinite(stack); cc = np.cumsum(fin, axis=0)
    take = fin & (cc <= 2)
    num = np.where(take, np.nan_to_num(stack), 0.0).sum(0)
    den = np.minimum(cc[-1], 2)
    return np.where(den > 0, num / np.maximum(den, 1), np.nan)


# ─────────────────── 최근 기후값 (학습 입력) ───────────────────
def compute_recent_clim(demand, is_hol, is_wkd, offset, K=CLIM_WEEKS):
    """최근 기후값: 타깃과 같은 (주말·공휴일) 상태인 same-DOW 최근 K주 평균(정직-lag).
    anchor(가까운 2주, 날카로움)보다 넓은 창이라 저분산·안정적이면서 여전히 최근 → staleness 없음.
    static (월,시,요일타입) 평균과 달리 옛 태양광 레벨에 고정되지 않음.
    """
    demand = np.asarray(demand, float); is_hol = np.asarray(is_hol); is_wkd = np.asarray(is_wkd)
    N = len(demand); w0 = anchor_w0(offset); t = np.arange(N)
    picks = []
    for j in range(K):
        Lh = 168 * (w0 + j); src = t - Lh; ok = src >= 0
        val = np.full(N, np.nan); match = np.zeros(N, bool)
        match[ok] = (is_hol[src[ok]] == is_hol[ok]) & (is_wkd[src[ok]] == is_wkd[ok])
        val[match] = demand[src[match]]
        picks.append(val)
    return np.nanmean(np.vstack(picks), axis=0)


# ─────────────────── Dataset ───────────────────
class AnchorDataset(torch.utils.data.Dataset):
    """과거 seq_len, 지평 offset 의 24h 타깃. anchor·clim 은 미리 계산해 전달."""
    def __init__(self, A, demand, anchor, clim, seq_len, pred_len, offset, fidx, tidx, starts=None):
        self.A = A; self.dem = demand; self.anc = anchor; self.clim = clim
        self.seq_len = seq_len; self.pred_len = pred_len; self.offset = offset
        self.fidx = fidx; self.tidx = tidx
        if starts is not None:
            self.starts = np.asarray(starts, dtype=np.int64); return
        n = len(A); last = n - seq_len - offset - pred_len + 1
        fin = (np.isfinite(anchor) & np.isfinite(demand) & np.isfinite(clim)).astype(np.int32)
        csum = np.concatenate([[0], np.cumsum(fin)])
        i = np.arange(max(last, 0)); s = i + seq_len + offset
        win_ok = (csum[s + pred_len] - csum[s]) == pred_len
        self.starts = i[win_ok].astype(np.int64)

    def __len__(self): return len(self.starts)

    def __getitem__(self, k):
        i = self.starts[k]; s = i + self.seq_len + self.offset
        past = self.A[i:i + self.seq_len]
        fut = self.A[s:s + self.pred_len]
        return {'past_numeric': torch.FloatTensor(past[:, self.fidx]),
                'past_y': torch.FloatTensor(self.dem[i:i + self.seq_len])[:, None],
                'future_numeric': torch.FloatTensor(fut[:, self.fidx]),
                'anchor': torch.FloatTensor(self.anc[s:s + self.pred_len]),
                'clim': torch.FloatTensor(self.clim[s:s + self.pred_len]),
                'future_y': torch.FloatTensor(self.dem[s:s + self.pred_len])}


# ─────────────────── 모델 ───────────────────
class _PWA(nn.Module):
    def __init__(self, q, k, h):
        super().__init__()
        self.W_Q = nn.Sequential(nn.Linear(q, h), nn.Tanh(), nn.Linear(h, h))
        self.W_K = nn.Sequential(nn.Linear(k, h), nn.Tanh(), nn.Linear(h, h)); self.s = 1.0 / (h ** 0.5)

    def forward(self, fw, pw, to):
        Q = self.W_Q(fw).unsqueeze(1); K = self.W_K(pw)
        a = F.softmax(torch.bmm(Q, K.transpose(1, 2)) * self.s, dim=-1)
        return torch.bmm(a, to).squeeze(1), a


class PatchTST_Anchor(nn.Module):
    """anchor-residual + climatology 입력. 출력 = anchor + RESID_STD·resid.
    헤드에 anchor_z·clim_z 둘 다 주입 → 모델이 지평별 anchor↔climatology 수축 비중을 학습.
    과거수요는 per-instance 정규화(인코더 표현용).
    """
    def __init__(self, num_features, dmean, dstd, resid_std, seq_len=336, pred_len=24,
                 patch_len=24, stride=12, d_model=256, num_heads=4, num_layers=3, d_ff=1024, dropout=0.2):
        super().__init__()
        self.patch_len = patch_len; self.stride = stride; self.pred_len = pred_len
        self.num_patches = (seq_len - patch_len) // stride + 1
        self.patch_embedding = nn.Linear(patch_len * num_features, d_model)
        self.pos_embedding = nn.Parameter(torch.randn(1, self.num_patches, d_model)); self.dropout = nn.Dropout(dropout)
        enc = nn.TransformerEncoderLayer(d_model, num_heads, d_ff, dropout, batch_first=True, norm_first=True)
        self.transformer_encoder = nn.TransformerEncoder(enc, num_layers)
        nwf = num_features - 1; ff = pred_len * nwf; wp = patch_len * nwf
        self.weather_attn = _PWA(ff, wp, d_model)
        # 헤드 입력 = [컨텍스트 d_model, 미래공변량 ff, anchor_z pred_len, clim_z pred_len]
        self.regressor = nn.Sequential(nn.Linear(d_model + ff + 2 * pred_len, 256), nn.LeakyReLU(0.1),
                                       nn.Dropout(dropout), nn.Linear(256, pred_len))
        self.weather_bypass = nn.Linear(ff + 2 * pred_len, pred_len)
        self.register_buffer('dmean', torch.tensor(float(dmean)))
        self.register_buffer('dstd', torch.tensor(float(dstd)))
        self.register_buffer('resid_std', torch.tensor(float(resid_std)))
        self.eps = 1e-5

    def forward(self, b, dev=None):
        dev = dev or next(self.parameters()).device
        pn = b['past_numeric'].to(dev); py = b['past_y'].to(dev); fn = b['future_numeric'].to(dev)
        anc = b['anchor'].to(dev); clim = b['clim'].to(dev); B = pn.shape[0]
        mean = py.mean(1, keepdim=True); std = torch.sqrt(py.var(1, keepdim=True, unbiased=False) + self.eps)
        pyn = (py - mean) / std
        xp = torch.cat([pn, pyn], -1)
        xpp = xp.unfold(1, self.patch_len, self.stride).permute(0, 1, 3, 2).reshape(B, self.num_patches, -1)
        eo = self.transformer_encoder(self.dropout(self.patch_embedding(xpp) + self.pos_embedding))
        ff = fn.reshape(B, -1)
        xw = xp[..., :-1].unfold(1, self.patch_len, self.stride).permute(0, 1, 3, 2).reshape(B, self.num_patches, -1)
        ctx, _ = self.weather_attn(ff, xw, eo)
        anc_z = (anc - self.dmean) / self.dstd
        clim_z = (clim - self.dmean) / self.dstd
        head_in = torch.cat([ctx, ff, anc_z, clim_z], 1)
        bypass_in = torch.cat([ff, anc_z, clim_z], 1)
        resid = self.regressor(head_in) + self.weather_bypass(bypass_in)
        return anc + self.resid_std * resid     # 절대 수요


# ─────────────────── 서빙 ───────────────────
def _load_raw(db):
    pull = (['timestamp', 'real_demand_land']
            + [f'temp_c_{s}' for s in TEMP_SEL] + [f'humidity_{s}' for s in TEMP_SEL]
            + [f'solar_rad_{s}' for s in SOLAR_SEL])
    with sqlite3.connect(db) as con:
        return pd.read_sql(f"SELECT {', '.join(pull)} FROM historical", con, parse_dates=['timestamp'])


def _future_grid(con, base, n):
    """forecast_horizon → horizon n 정규 24h 원시 외생(temp_c/humidity/solar_rad)+시간/달력. 3시간격 보간.
    반환: out(DataFrame, FW 컬럼 원시값), tg, ok.
    """
    tg = pd.date_range(pd.Timestamp(base).normalize() + pd.Timedelta(days=n), periods=24, freq='h')
    cols = ([f'temp_{s}' for s in TEMP_SEL] + [f'reh_{s}' for s in TEMP_SEL]
            + [f'radiation_{s}' for s in SOLAR_SEL])
    sel = ', '.join(f'"{c}"' for c in ['timestamp'] + cols)
    lo = (tg[0] - pd.Timedelta(hours=3)).strftime('%Y-%m-%d %H:%M:%S')
    hi = (tg[-1] + pd.Timedelta(hours=3)).strftime('%Y-%m-%d %H:%M:%S')
    fc = pd.read_sql(f'SELECT {sel} FROM forecast_horizon WHERE base=? AND timestamp BETWEEN ? AND ? ORDER BY timestamp',
                     con, params=(base, lo, hi), parse_dates=['timestamp']).set_index('timestamp')
    if fc.empty:
        return None
    fc = fc[~fc.index.duplicated(keep='first')].apply(pd.to_numeric, errors='coerce')
    fc = fc.reindex(fc.index.union(tg)).interpolate('time', limit=4, limit_area='inside').reindex(tg)
    out = pd.DataFrame(index=tg)
    out['temp_c'] = fc[[f'temp_{s}' for s in TEMP_SEL]].mean(1)
    out['humidity'] = fc[[f'reh_{s}' for s in TEMP_SEL]].mean(1)
    out['solar_rad'] = fc[[f'radiation_{s}' for s in SOLAR_SEL]].mean(1)
    out['Hour_sin'] = np.sin(2 * np.pi * tg.hour / 24); out['Hour_cos'] = np.cos(2 * np.pi * tg.hour / 24)
    out['Doy_sin'] = np.sin(2 * np.pi * tg.dayofyear / 365); out['Doy_cos'] = np.cos(2 * np.pi * tg.dayofyear / 365)
    is_wknd, is_hol = holiday_flags(tg)        # 미래 공휴일 결정적
    out['is_weekend'] = is_wknd; out['is_holiday'] = is_hol
    ok = out[['temp_c', 'humidity', 'solar_rad']].notna().all(axis=1).values
    return out, tg, ok


def _serve_lagavg(tg, tg_hol, tg_wkd, dem, tindex, hist_hol, hist_wkd, offset, K, topk):
    """서빙 타깃 24h 의 daytype_match honest 과거평균. anchor=가까운 topk(2)·clim=K주 전체 평균."""
    w0 = anchor_w0(offset); out = np.full(len(tg), np.nan)
    for k, t in enumerate(tg):
        coll = []
        for j in range(K):
            ref = t - pd.Timedelta(hours=168 * (w0 + j))
            if ref in tindex:
                ri = tindex.get_loc(ref)
                if hist_hol[ri] == tg_hol[k] and hist_wkd[ri] == tg_wkd[k]:
                    coll.append(dem[ri])
            if len(coll) >= topk:
                break
        if coll:
            out[k] = float(np.mean(coll))
    return out


def load_serve(db, lt_dir):
    """서빙 자산 1회 로드(체인·standalone 공용). 반환 dict 를 predict_horizon 에 넘긴다."""
    import joblib
    meta = joblib.load(os.path.join(lt_dir, 'metadata_lt.pkl'))
    scaler = joblib.load(os.path.join(lt_dir, 'scaler_exog.pkl'))
    calib = {}                                   # post-hoc (계절×시각×지평) bias 보정(있으면 적용)
    cpath = os.path.join(lt_dir, 'calib_lt.json')
    if os.path.exists(cpath):
        with open(cpath, encoding='utf-8') as f:
            calib = json.load(f)
        print(f'  보정표 적용: calib_lt.json ({len(calib)} 셀)')
    HP = meta['HP']; dmean, dstd = meta['DMEAN'], meta['DSTD']; NF = len(FW) + 1
    feat = build_features(_load_raw(db))
    A_all = feat[FW].copy(); A_all[EXOG] = scaler.transform(A_all[EXOG])
    models = {}
    for n in range(1, 16):
        wp = os.path.join(lt_dir, f'best_lt_D{n}.pth')
        if not os.path.exists(wp):       # 부분 학습(일부 지평만) 도 허용
            continue
        m = PatchTST_Anchor(NF, dmean, dstd, meta['RESID_STD'][f'D{n}'], pred_len=24, **HP)
        m.load_state_dict(torch.load(wp, map_location='cpu')); m.eval()
        models[n] = m
    return dict(scaler=scaler, calib=calib, HP=HP, models=models,
                A_sc=A_all.values.astype(np.float32), dem=feat['Demand'].values.astype(np.float32),
                tindex=feat.index, hist_wkd=feat['is_weekend'].values, hist_hol=feat['is_holiday'].values,
                SEQ=HP['seq_len'], FIDX=list(range(len(FW))))


@torch.no_grad()
def predict_horizon(A, con, base, n, calibrated=True):
    """(base, 지평 n) → (tg, pred[24]) 절대수요. calibrated=True 면 post-hoc 보정 적용(production),
    False 면 원본 raw(보정표 재생성·백테스트용). 불가 시 None. tg=base+n일 00~23시.
    A = load_serve() 자산. con = input_data_land.db 커넥션(forecast_horizon 조회)."""
    if n not in A['models']:
        return None
    tindex = A['tindex']; dem = A['dem']; SEQ = A['SEQ']
    O = pd.Timestamp(base).normalize() + pd.Timedelta(hours=23)
    if O not in tindex:
        return None
    oi = tindex.get_loc(O)
    if oi - (SEQ - 1) < 0:
        return None
    past = A['A_sc'][oi - (SEQ - 1):oi + 1]; py = dem[oi - (SEQ - 1):oi + 1][:, None]
    if not (np.isfinite(past).all() and np.isfinite(py).all()):
        return None
    fg = _future_grid(con, base, n)
    if fg is None:
        return None
    out, tg, ok = fg
    out_sc = out.copy(); out_sc[EXOG] = A['scaler'].transform(out_sc[EXOG].ffill().bfill())
    fut = out_sc[FW].ffill().bfill().values.astype(np.float32)
    tg_wkd = out['is_weekend'].values; tg_hol = out['is_holiday'].values
    anchor = _serve_lagavg(tg, tg_hol, tg_wkd, dem, tindex, A['hist_hol'], A['hist_wkd'], HORIZONS[n], K=8, topk=2)
    clim = _serve_lagavg(tg, tg_hol, tg_wkd, dem, tindex, A['hist_hol'], A['hist_wkd'], HORIZONS[n], K=CLIM_WEEKS, topk=CLIM_WEEKS)
    ok = ok & np.isfinite(anchor) & np.isfinite(clim)
    if not ok.any():
        return None
    anchor = np.where(np.isfinite(anchor), anchor, clim)   # 앵커 결손 시 기후값 폴백
    batch = {'past_numeric': torch.FloatTensor(past[None, :, A['FIDX']]),
             'past_y': torch.FloatTensor(py[None]),
             'future_numeric': torch.FloatTensor(fut[None]),
             'anchor': torch.FloatTensor(anchor[None]), 'clim': torch.FloatTensor(clim[None])}
    pred = np.clip(A['models'][n](batch).numpy().ravel(), 0, None)
    pred[~ok] = np.nan
    if calibrated and A['calib']:
        cf = np.array([A['calib'].get(calib_key(t.month, t.hour, n), 1.0) for t in tg])   # (계절×시각×지평) 보정
        pred = pred * cf
    return tg, pred


@torch.no_grad()
def serve(db, lt_dir, bases, table, calibrated=True):
    """standalone 서빙 → rows[(ts, base, n, demand, 'patchtst_lt')]. (체인은 load_serve+predict_horizon 직접 사용)"""
    A = load_serve(db, lt_dir)
    print(f'  로드된 지평: {sorted(A["models"])}  (보정={calibrated})')
    rows = []
    with sqlite3.connect(db) as con:
        for base in bases:
            for n in sorted(A['models']):
                res = predict_horizon(A, con, base, n, calibrated=calibrated)
                if res is None:
                    continue
                tg, pred = res
                for ts, v in zip(tg, pred):
                    if np.isfinite(v):
                        rows.append((ts.strftime('%Y-%m-%d %H:%M:%S'), base, n, float(v), 'patchtst_lt'))
    return rows

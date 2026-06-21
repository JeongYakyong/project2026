# -*- coding: utf-8 -*-
"""전국 수요 PatchTST 서빙 → est_horizon_land_new (D+1..D+15).

이 스크립트는 SIMPLE TEST/data/input_data_land.db 만 사용한다(self-contained).
- 과거 윈도우: historical 실측 (origin O = base 당일 23:00, seq_len=336)
- 미래 외생   : forecast_horizon (base, horizon_d 구조) 에서 comfort 재구성
- 출력        : est_horizon_land_new(base, timestamp, horizon_d, est_demand_land, model)

모델 두 종류:
  --model final336 : 기존 학습 가중치(교차어텐션 PatchTST, D1~D15). 즉시 실행 가능한 pure-PatchTST 기준선.
  --model lt       : 신규 장기 모델(anchor-residual PatchTST). Colab 학습 후 가중치 투입 시 동작.

용량 피처(cap_btmppa)는 final336 학습 스케일(월별 PPA, kr_elec_capa.csv) 그대로 사용한다.
신규 lt 모델은 in-db gen_solar_capacity_kr 를 쓰므로 model_lt.py 의 빌더를 사용한다.
"""
from __future__ import annotations
import os, sys, argparse, sqlite3
import numpy as np, pandas as pd, torch, joblib
import torch.nn as nn, torch.nn.functional as F

HERE = os.path.dirname(os.path.abspath(__file__))
# 정본 DB = 1. data_fetcher_and_db/data (평면 넘버링, 단일 출처)
DB = os.path.normpath(os.path.join(HERE, '..', '..', '..', '1. data_fetcher_and_db', 'data', 'input_data_land.db'))
# 기존 final336 산출물(가중치/스케일러/메타)
FINAL336 = r'C:\Users\bjkim\Desktop\project2026\5. land_demand_forecaster\training\landdemand_final336'
CAPA_CSV = r'C:\Users\bjkim\Desktop\project2026\1. data_fetcher_and_db\second_dataset\kr_elec_capa.csv'
LT_DIR = os.path.join(HERE, 'weights')   # lt 정본 가중치(v4 = anchor + recent-clim + calib_lt.json)
DEVICE = 'cpu'
TABLE = 'est_horizon_land_raw'   # v4 원본(미보정) 백테스트·보정표 재생성 벤치. production=est_horizon_land(체인)

TEMP_SEL = ['wonju', 'seosan', 'pohang', 'yeonggwang']
SOLAR_SEL = ['seosan', 'yeonggwang']


# ───────────────────────── 공통 유틸 ─────────────────────────
def comfort(T, RH, Wms):
    di = 0.81 * T + 0.01 * RH * (0.99 * T - 14.3) + 46.3
    Wk = np.clip(Wms * 3.6, 4.8, None)
    wct = 13.12 + 0.6215 * T - 11.37 * Wk ** 0.16 + 0.3965 * T * Wk ** 0.16
    return di, np.where(T <= 10, wct, T)


def load_ppa():
    df = pd.read_csv(CAPA_CSV, encoding='euc-kr', header=None, skiprows=2)
    df.columns = ['period', 'region', 'LNG', 'solar', 'wind', 'PPA']
    df = df[df.region.astype(str).str.strip() == '합계'].copy()
    df['ym'] = pd.to_datetime(df.period, format='%b-%y').dt.to_period('M')
    df['PPA'] = pd.to_numeric(df.PPA, errors='coerce')
    return df.dropna(subset=['PPA']).set_index('ym')['PPA'].sort_index()


def cap_for(idx, ppa):
    ym = idx.to_period('M')
    full = pd.period_range(min(ym.min(), ppa.index.min()), max(ym.max(), ppa.index.max()), freq='M')
    return pd.Series(ym).map(ppa.reindex(full).ffill().bfill()).astype(float).values


def add_time(idx, dtv):
    out = pd.DataFrame(index=idx)
    out['Hour_sin'] = np.sin(2 * np.pi * idx.hour / 24); out['Hour_cos'] = np.cos(2 * np.pi * idx.hour / 24)
    out['Doy_sin'] = np.sin(2 * np.pi * idx.dayofyear / 365); out['Doy_cos'] = np.cos(2 * np.pi * idx.dayofyear / 365)
    out['is_weekend'] = (np.asarray(dtv) == 'weekend').astype(float)
    out['is_holiday'] = (np.asarray(dtv) == 'holiday').astype(float)
    return out


# ───────────────────────── 모델 (final336 구조, 인라인) ─────────────────────────
class _PWA(nn.Module):
    def __init__(self, q, k, h):
        super().__init__()
        self.W_Q = nn.Sequential(nn.Linear(q, h), nn.Tanh(), nn.Linear(h, h))
        self.W_K = nn.Sequential(nn.Linear(k, h), nn.Tanh(), nn.Linear(h, h)); self.s = 1.0 / (h ** 0.5)

    def forward(self, fw, pw, to):
        Q = self.W_Q(fw).unsqueeze(1); K = self.W_K(pw)
        a = F.softmax(torch.bmm(Q, K.transpose(1, 2)) * self.s, dim=-1)
        return torch.bmm(a, to).squeeze(1), a


class PatchTST(nn.Module):
    def __init__(self, num_features, seq_len=336, pred_len=24, patch_len=24, stride=12,
                 d_model=256, num_heads=4, num_layers=3, d_ff=1024, dropout=0.2, revin_affine=True):
        super().__init__()
        self.patch_len = patch_len; self.stride = stride; self.pred_len = pred_len
        self.num_patches = (seq_len - patch_len) // stride + 1
        self.patch_embedding = nn.Linear(patch_len * num_features, d_model)
        self.pos_embedding = nn.Parameter(torch.randn(1, self.num_patches, d_model)); self.dropout = nn.Dropout(dropout)
        enc = nn.TransformerEncoderLayer(d_model, num_heads, d_ff, dropout, batch_first=True, norm_first=True)
        self.transformer_encoder = nn.TransformerEncoder(enc, num_layers)
        nwf = num_features - 1; ff = pred_len * nwf; wp = patch_len * nwf
        self.weather_attn = _PWA(ff, wp, d_model)
        self.regressor = nn.Sequential(nn.Linear(d_model + ff, 256), nn.LeakyReLU(0.1), nn.Dropout(dropout), nn.Linear(256, pred_len))
        self.weather_bypass = nn.Linear(ff, pred_len)
        self.revin_affine = revin_affine; self.eps = 1e-5
        if revin_affine:
            self.revin_w = nn.Parameter(torch.ones(1)); self.revin_b = nn.Parameter(torch.zeros(1))

    def forward(self, b):
        pn = b['past_numeric'].to(DEVICE); py = b['past_y'].to(DEVICE); fn = b['future_numeric'].to(DEVICE); B = pn.shape[0]
        mean = py.mean(1, keepdim=True); std = torch.sqrt(py.var(1, keepdim=True, unbiased=False) + self.eps); pyn = (py - mean) / std
        if self.revin_affine: pyn = pyn * self.revin_w + self.revin_b
        xp = torch.cat([pn, pyn], -1)
        xpp = xp.unfold(1, self.patch_len, self.stride).permute(0, 1, 3, 2).reshape(B, self.num_patches, -1)
        eo = self.transformer_encoder(self.dropout(self.patch_embedding(xpp) + self.pos_embedding)); ff = fn.reshape(B, -1)
        xw = xp[..., :-1].unfold(1, self.patch_len, self.stride).permute(0, 1, 3, 2).reshape(B, self.num_patches, -1)
        ctx, _ = self.weather_attn(ff, xw, eo)
        on = self.regressor(torch.cat([ctx, ff], 1)) + self.weather_bypass(ff)
        if self.revin_affine: on = (on - self.revin_b) / self.revin_w
        return on * std.squeeze(-1) + mean.squeeze(-1), std.squeeze(-1)


# ───────────────────────── final336 자산/이력 ─────────────────────────
def load_final336():
    meta = joblib.load(os.path.join(FINAL336, 'metadata_landdemand_final2.pkl'))
    scaler = joblib.load(os.path.join(FINAL336, 'scaler_exog.pkl'))
    HP = meta['HP']; EXOG = meta['EXOG']; TIME = meta['TIME']; FF = meta['FUTURE_FEATURES']
    models = {}
    for n in range(1, 16):
        m = PatchTST(len(FF) + 1, pred_len=24, **HP).to(DEVICE)
        m.load_state_dict(torch.load(os.path.join(FINAL336, f'best_patchtst_landdemand_D{n}.pth'), map_location=DEVICE))
        m.eval(); models[n] = m
    return dict(models=models, scaler=scaler, EXOG=EXOG, TIME=TIME, FF=FF, SEQ=HP['seq_len'])


def build_history(scaler, EXOG, TIME, FF, ppa):
    """historical 실측 → 외생 z-score(EXOG)+시간(TIME)=FF 배열 + 수요 시계열."""
    pull = (['timestamp', 'real_demand_land', 'day_type']
            + [f'temp_c_{s}' for s in TEMP_SEL] + [f'humidity_{s}' for s in TEMP_SEL]
            + [f'wind_spd_{s}' for s in TEMP_SEL]
            + [f'solar_rad_{s}' for s in SOLAR_SEL] + [f'total_cloud_{s}' for s in SOLAR_SEL])
    with sqlite3.connect(DB) as con:
        raw = pd.read_sql(f"SELECT {', '.join(pull)} FROM historical", con, parse_dates=['timestamp'])
    raw = raw.sort_values('timestamp')
    idx = pd.date_range(raw.timestamp.min(), raw.timestamp.max(), freq='h')
    d = raw.set_index('timestamp').reindex(idx); d.index.name = 'timestamp'
    d.loc[d.real_demand_land == 0, 'real_demand_land'] = np.nan
    d['Demand'] = d['real_demand_land'].interpolate('time').ffill().bfill()
    for c in pull[3:]:
        d[c] = pd.to_numeric(d[c], errors='coerce').interpolate('time', limit=6).ffill().bfill()
    T = d[[f'temp_c_{s}' for s in TEMP_SEL]].mean(1); RH = d[[f'humidity_{s}' for s in TEMP_SEL]].mean(1); W = d[[f'wind_spd_{s}' for s in TEMP_SEL]].mean(1)
    d['temp_c'] = T; d['di'], d['wct'] = comfort(T, RH, W)
    d['solar_rad'] = d[[f'solar_rad_{s}' for s in SOLAR_SEL]].mean(1); d['total_cloud'] = d[[f'total_cloud_{s}' for s in SOLAR_SEL]].mean(1)
    d['cap_btmppa'] = cap_for(d.index, ppa); d['day_type'] = d['day_type'].ffill().bfill()
    tf = add_time(d.index, d['day_type'].values)
    for c in TIME:
        d[c] = tf[c].values
    dsc = d.copy(); dsc[EXOG] = scaler.transform(dsc[EXOG])
    return dsc[FF], d['Demand']


def fetch_future(con, base, n, EXOG, TIME, FF, scaler, ppa):
    """forecast_horizon 에서 horizon n 의 정규 24h 그리드(00..23) 외생 재구성.

    장기 지평은 3시간 간격(하루 8점)으로 저장되므로 시간격자에 reindex 후 time 보간한다.
    반환: (FF 스케일 배열[24,F], tg[24], ok 마스크[24]) — 핵심 외생 결손 시각은 ok=False.
    """
    tg = pd.date_range(pd.Timestamp(base).normalize() + pd.Timedelta(days=n), periods=24, freq='h')
    cols = ([f'temp_{s}' for s in TEMP_SEL] + [f'reh_{s}' for s in TEMP_SEL] + [f'wind_spd_10m_{s}' for s in TEMP_SEL]
            + [f'radiation_{s}' for s in SOLAR_SEL] + [f'total_cloud_{s}' for s in SOLAR_SEL])
    sel = ', '.join(f'"{c}"' for c in ['timestamp'] + cols)
    lo = (tg[0] - pd.Timedelta(hours=3)).strftime('%Y-%m-%d %H:%M:%S')
    hi = (tg[-1] + pd.Timedelta(hours=3)).strftime('%Y-%m-%d %H:%M:%S')
    fc = pd.read_sql(f'SELECT {sel} FROM forecast_horizon WHERE base=? AND timestamp BETWEEN ? AND ? ORDER BY timestamp',
                     con, params=(base, lo, hi), parse_dates=['timestamp']).set_index('timestamp')
    if fc.empty:
        return None
    # 중복 timestamp(인접 horizon_d 경계) 제거 후 시간격자 보간
    fc = fc[~fc.index.duplicated(keep='first')].apply(pd.to_numeric, errors='coerce')
    ext = fc.index.union(tg)
    fc = fc.reindex(ext).interpolate('time', limit=4, limit_area='inside').reindex(tg)
    T = fc[[f'temp_{s}' for s in TEMP_SEL]].mean(1); RH = fc[[f'reh_{s}' for s in TEMP_SEL]].mean(1); Wd = fc[[f'wind_spd_10m_{s}' for s in TEMP_SEL]].mean(1)
    out = pd.DataFrame(index=tg)
    out['temp_c'] = T; out['di'], out['wct'] = comfort(T, RH, Wd)
    out['solar_rad'] = fc[[f'radiation_{s}' for s in SOLAR_SEL]].mean(1)
    out['total_cloud'] = fc[[f'total_cloud_{s}' for s in SOLAR_SEL]].mean(1)
    out['cap_btmppa'] = cap_for(tg, ppa)
    # day_type 미래값: 주말/공휴일은 달력 기반(공휴일 테이블 없음 → 주말만 반영)
    dtv = np.where(tg.dayofweek >= 5, 'weekend', 'weekday')
    tf = add_time(tg, dtv)
    for c in TIME:
        out[c] = tf[c].values
    ok = out[['temp_c', 'di', 'wct', 'solar_rad']].notna().all(axis=1).values
    fr = out[FF].ffill().bfill()
    fr[EXOG] = scaler.transform(fr[EXOG])
    return fr.values.astype(np.float32), tg, ok


@torch.no_grad()
def serve_final336(bases):
    a = load_final336(); ppa = load_ppa()
    A_sc, dem = build_history(a['scaler'], a['EXOG'], a['TIME'], a['FF'], ppa)
    SEQ = a['SEQ']
    rows = []
    with sqlite3.connect(DB) as con:
        for base in bases:
            O = pd.Timestamp(base).normalize() + pd.Timedelta(hours=23)
            if O not in A_sc.index:
                continue
            oi = A_sc.index.get_loc(O)
            if oi - (SEQ - 1) < 0:
                continue
            past = A_sc.iloc[oi - (SEQ - 1):oi + 1].values.astype(np.float32)
            py = dem.iloc[oi - (SEQ - 1):oi + 1].values.astype(np.float32)[:, None]
            if not (np.isfinite(past).all() and np.isfinite(py).all()):
                continue
            for n in range(1, 16):
                fut = fetch_future(con, base, n, a['EXOG'], a['TIME'], a['FF'], a['scaler'], ppa)
                if fut is None:
                    continue
                Fs, tg, ok = fut
                out, _ = a['models'][n]({'past_numeric': torch.from_numpy(past[None]),
                                         'past_y': torch.from_numpy(py[None]),
                                         'future_numeric': torch.from_numpy(Fs[None])})
                pr = np.clip(out.numpy().ravel(), 0, None)
                pr[~ok] = np.nan
                for ts, v in zip(tg, pr):
                    if np.isfinite(v):
                        rows.append((ts.strftime('%Y-%m-%d %H:%M:%S'), base, n, float(v), 'patchtst_final336'))
    return rows


def write_rows(rows, reset=False):
    with sqlite3.connect(DB) as con:
        if reset:
            con.execute(f"DROP TABLE IF EXISTS {TABLE}")
        con.execute(f"CREATE TABLE IF NOT EXISTS {TABLE} (timestamp TEXT, base TEXT, horizon_d INT, "
                    f"est_demand_land REAL, model TEXT, PRIMARY KEY(model, base, timestamp))")
        con.executemany(f"INSERT OR REPLACE INTO {TABLE}(timestamp, base, horizon_d, est_demand_land, model) "
                        f"VALUES (?,?,?,?,?)", rows)
        con.commit()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--model', choices=['final336', 'lt'], default='final336')
    ap.add_argument('--days', type=int, default=31, help='최근 N일 base 만 서빙(비교용)')
    ap.add_argument('--lt-dir', default=LT_DIR, help='lt 가중치 폴더')
    ap.add_argument('--reset', action='store_true', help='쓰기 전 테이블 초기화')
    ap.add_argument('--calibrated', action='store_true', help='post-hoc 보정 적용(기본=원본 raw — 보정표 재생성용)')
    args = ap.parse_args()
    with sqlite3.connect(DB) as con:
        all_bases = [r[0] for r in con.execute('SELECT DISTINCT base FROM forecast_horizon ORDER BY base').fetchall()]
    cutoff = pd.Timestamp(all_bases[-1]) - pd.Timedelta(days=args.days)
    bases = [b for b in all_bases if pd.Timestamp(b) >= cutoff]
    print(f'[{args.model}] bases {len(bases)}: {bases[0]} .. {bases[-1]}')
    if args.model == 'final336':
        rows = serve_final336(bases)
    else:
        import model_lt
        rows = model_lt.serve(DB, args.lt_dir, bases, TABLE, calibrated=args.calibrated)
    write_rows(rows, reset=args.reset)
    print(f'wrote {len(rows)} rows ({args.model}) -> {TABLE}')


if __name__ == '__main__':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass
    main()

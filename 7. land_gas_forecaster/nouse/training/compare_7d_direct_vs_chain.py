# -*- coding: utf-8 -*-
"""7-D 비교 하니스 — 수요→가스 직접 PatchTST  vs  체인 가스(LGBM v2).

같은 베이스/시각(forecast_horizon 182 base, 2025-12~2026-06, PatchTST 학습창 밖)에서:
  · 직접 PatchTST (honest) : 과거창=historical 실측, 미래창 기상=forecast_horizon,
                              미래 수요=est_horizon_land.est_demand_land. 출력=가스 MW(scaler_y 역변환).
  · 직접 PatchTST (perfect): 미래창 기상·수요까지 historical 실측 → 모델 상한.
  · 체인 가스(LGBM v2)     : horizon_backtest_v2.parquet 의 est_gas_gen_raw (보정 전 raw, 동일 조건).
  · 실측                   : historical.gen_gas_kr.
양쪽 다 raw(보정 전) 비교. 지평 D+1/2/3/7/12. 전체·낮(09-15h)·계절(봄 강조) 분리 MAPE/bias.

산출: 콘솔 표 + compare_7d_results.parquet(샘플별, 보고서용).
사용법: python "7. land_gas_forecaster/training/compare_7d_direct_vs_chain.py"
"""
from __future__ import annotations
import os, sys, sqlite3, importlib.util
import numpy as np, pandas as pd, torch, joblib

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, '..', '..'))
DB = os.path.join(ROOT, '1. data_fetcher_and_db', 'data', 'input_data_land.db')
PT_DIR = os.path.join(HERE, 'landgas_patchtst')
PARQUET = os.path.join(HERE, 'horizon_backtest_v2.parquet')
DEVICE = 'cuda' if torch.cuda.is_available() else 'cpu'

HZ = [1, 2, 3, 7, 12]
PL = 24
SOLAR_ST = ['yeonggwang', 'seosan', 'pohang']
SEASON = {12: '겨울', 1: '겨울', 2: '겨울', 3: '봄', 4: '봄', 5: '봄',
          6: '여름', 7: '여름', 8: '여름', 9: '가을', 10: '가을', 11: '가을'}


def _imp(name, path):
    s = importlib.util.spec_from_file_location(name, path); m = importlib.util.module_from_spec(s)
    sys.modules[name] = m; s.loader.exec_module(m); return m


# PatchTST 아키텍처는 6단계 서빙 클래스 재사용(동일 구조).
serve6 = _imp('serve_solarwind_land', os.path.join(ROOT, '6. land_solarwind_forecaster', 'serve_solarwind_land.py'))
PatchTST = serve6.PatchTST_Weather_Model


def mape(a, p):
    a, p = np.asarray(a, float), np.asarray(p, float); m = (a > 0) & np.isfinite(a) & np.isfinite(p)
    return float(np.mean(np.abs(a[m]-p[m])/a[m])*100) if m.any() else np.nan


def nbias(a, p):
    a, p = np.asarray(a, float), np.asarray(p, float); m = (a > 0) & np.isfinite(a) & np.isfinite(p)
    return float(np.mean((p[m]-a[m])/a[m])*100) if m.any() else np.nan


def _S(t): return pd.Timestamp(t).strftime('%Y-%m-%d %H:%M:%S')


def _damping(idx, rain, k):
    s = pd.Series(np.asarray(rain, float), index=idx).between_time('06:00', '20:00')
    d = s.groupby(s.index.date).sum()
    return np.exp(-k * pd.Series(idx.date, index=idx).map(d).clip(upper=20).astype(float).values)


def load_assets():
    meta = joblib.load(os.path.join(PT_DIR, 'metadata_landgas.pkl'))
    sx = joblib.load(os.path.join(PT_DIR, 'scaler_x_landgas.pkl'))
    sy = joblib.load(os.path.join(PT_DIR, 'scaler_y_landgas.pkl'))
    FF = meta['future_features']; HP = meta['GAS_HP']; SEQ = meta['SEQ_LEN']; K = meta['K_DAMP']
    HOR = meta['HORIZONS']
    pt = {}
    for name, off in HOR.items():
        n = int(name[1:])
        p = os.path.join(PT_DIR, f'best_patchtst_landgas_{name}.pth')
        if not os.path.exists(p): continue
        m = PatchTST(len(FF)+1, seq_len=SEQ, pred_len=PL, patch_len=HP['patch_len'], stride=HP['stride'],
                     d_model=HP['d_model'], num_heads=HP['num_heads'], num_layers=HP['num_layers'],
                     d_ff=HP['d_ff'], dropout=HP['dropout']).to(DEVICE)
        m.load_state_dict(torch.load(p, map_location=DEVICE)); m.eval(); pt[n] = (m, off)
    return dict(meta=meta, sx=sx, sy=sy, FF=FF, SEQ=SEQ, K=K, pt=pt)


def _read(con, table, t0, t1, cols, base=None):
    sel = ', '.join(f'"{c}"' for c in ['timestamp'] + cols)
    if base is None:
        q = f'SELECT {sel} FROM {table} WHERE timestamp BETWEEN ? AND ? ORDER BY timestamp'
        df = pd.read_sql(q, con, params=(t0, t1), parse_dates=['timestamp'])
    else:
        q = f'SELECT {sel} FROM {table} WHERE base=? AND timestamp BETWEEN ? AND ? ORDER BY timestamp'
        df = pd.read_sql(q, con, params=(base, t0, t1), parse_dates=['timestamp'])
    return df.set_index('timestamp').apply(pd.to_numeric, errors='coerce')


# historical 원천 컬럼(과거창 + perfect 미래 + 실측)
HIST_W = []
for st in SOLAR_ST:
    HIST_W += [f'solar_rad_{st}', f'total_cloud_{st}', f'midlow_cloud_{st}', f'rainfall_{st}']
HIST_W += ['wind_spd_pohang']
HIST_ALL = HIST_W + ['real_demand_land', 'gen_gas_kr']

# forecast_horizon → 학습 피처명 매핑
FC_MAP = {}
for st in SOLAR_ST:
    FC_MAP[f'radiation_{st}'] = f'solar_rad_{st}'
    FC_MAP[f'total_cloud_{st}'] = f'total_cloud_{st}'
    FC_MAP[f'midlow_cloud_{st}'] = f'midlow_cloud_{st}'
    FC_MAP[f'rainfall_{st}'] = f'rainfall_{st}'
FC_MAP['wind_spd_10m_pohang'] = 'wind_spd_pohang'


def _build_M(past_w, fut_w, A):
    """과거+미래 원천 weather/demand 결합 → FF 피처행렬(미정규화)."""
    comb = pd.concat([past_w[HIST_W + ['real_demand_land']], fut_w[HIST_W + ['real_demand_land']]]).sort_index()
    comb = comb.interpolate(limit=3).ffill().bfill()
    M = pd.DataFrame(index=comb.index)
    M['real_demand_land'] = comb['real_demand_land']
    for st in SOLAR_ST:
        M[f'solar_rad_{st}'] = comb[f'solar_rad_{st}']
        M[f'total_cloud_{st}'] = comb[f'total_cloud_{st}']
        M[f'midlow_cloud_{st}'] = comb[f'midlow_cloud_{st}']
        M[f'solar_damping_{st}'] = _damping(comb.index, comb[f'rainfall_{st}'], A['K'])
    M['wind_spd_pohang'] = comb['wind_spd_pohang']
    M['Hour_sin'] = np.sin(2*np.pi*M.index.hour/24); M['Hour_cos'] = np.cos(2*np.pi*M.index.hour/24)
    M['Year_sin'] = np.sin(2*np.pi*M.index.dayofyear/365); M['Year_cos'] = np.cos(2*np.pi*M.index.dayofyear/365)
    return M


def predict_block(con, base, n, A, condition):
    """직접 PatchTST 가스 24h 블록(MW). condition='honest'|'perfect'."""
    if n not in A['pt']:
        return None, None
    model, off = A['pt'][n]
    SEQ, FF = A['SEQ'], A['FF']
    O = pd.Timestamp(base).normalize() + pd.Timedelta(hours=23)
    d = O.normalize() + pd.Timedelta(days=n)                       # 대상일 00:00
    fut_idx = pd.date_range(d, periods=PL, freq='h')
    first = d - pd.Timedelta(hours=off + SEQ); last_past = d - pd.Timedelta(hours=off + 1)   # =O
    past = _read(con, 'historical', _S(first), _S(last_past), HIST_ALL)
    past = past.reindex(pd.date_range(first, last_past, freq='h'))
    if len(past) < SEQ or past['gen_gas_kr'].isna().mean() > 0.1 or past['real_demand_land'].isna().mean() > 0.1:
        return None, None
    # 미래창 weather/demand
    if condition == 'perfect':
        fut = _read(con, 'historical', _S(d), _S(fut_idx[-1]), HIST_W + ['real_demand_land']).reindex(fut_idx)
    else:   # honest: 기상=forecast_horizon, 수요=est_horizon_land
        fw = _read(con, 'forecast_horizon', _S(d), _S(fut_idx[-1]), list(FC_MAP), base=base).rename(columns=FC_MAP)
        dem = _read(con, 'est_horizon_land', _S(d), _S(fut_idx[-1]), ['est_demand_land'], base=base)
        fut = fw.reindex(fut_idx)
        fut['real_demand_land'] = dem['est_demand_land'].reindex(fut_idx)
    fut = fut.reindex(columns=HIST_W + ['real_demand_land'])
    M = _build_M(past, fut, A)
    Sc = pd.DataFrame(A['sx'].transform(M[FF]), index=M.index, columns=FF)
    past_idx = Sc.index[Sc.index <= last_past][-SEQ:]
    pn = Sc.reindex(past_idx)[FF].values; fn = Sc.reindex(fut_idx)[FF].values
    gas_past = past['gen_gas_kr'].reindex(past_idx).values.reshape(-1, 1)
    py = A['sy'].transform(np.nan_to_num(gas_past, nan=float(A['sy'].data_min_[0])))
    if np.isnan(pn).any() or np.isnan(fn).any():
        return None, None
    b = {'past_numeric': torch.FloatTensor(pn).unsqueeze(0),
         'past_y': torch.FloatTensor(py).unsqueeze(0),
         'future_numeric': torch.FloatTensor(fn).unsqueeze(0)}
    with torch.no_grad():
        out = model(b).squeeze(0).cpu().numpy()
    gas_mw = A['sy'].inverse_transform(out.reshape(-1, 1)).ravel()
    return fut_idx, gas_mw


def main():
    A = load_assets()
    print(f'PatchTST 가중치: {sorted(A["pt"])} | device {DEVICE}')
    chain = pd.read_parquet(PARQUET)[['base', 'timestamp', 'horizon', 'est_gas_gen_raw', 'gen_gas_kr']]
    chain['timestamp'] = pd.to_datetime(chain['timestamp'])
    with sqlite3.connect(DB) as con:
        bases = [r[0] for r in con.execute('SELECT DISTINCT base FROM forecast_horizon ORDER BY base')]
        rows = []
        for bi, base in enumerate(bases, 1):
            for n in HZ:
                fi, gh = predict_block(con, base, n, A, 'honest')
                _,  gp = predict_block(con, base, n, A, 'perfect')
                if fi is None:
                    continue
                df = pd.DataFrame({'base': base, 'timestamp': fi, 'horizon': n,
                                   'direct_honest': gh, 'direct_perfect': gp})
                rows.append(df)
            if bi % 30 == 0 or bi == len(bases):
                print(f'  base {bi}/{len(bases)} ({base[:10]})  누적 {sum(len(r) for r in rows)}행')
    r = pd.concat(rows, ignore_index=True)
    r = r.merge(chain, on=['base', 'timestamp', 'horizon'], how='left')
    r['hr'] = r.timestamp.dt.hour; r['day'] = (r.hr >= 9) & (r.hr <= 15)
    r['season'] = r.timestamp.dt.month.map(SEASON)
    r.to_parquet(os.path.join(HERE, 'compare_7d_results.parquet'))

    def line(g, lbl):
        ev = g.dropna(subset=['gen_gas_kr']); ev = ev[ev.gen_gas_kr > 0]
        return (f'{lbl:>10} | 직접(honest) {mape(ev.gen_gas_kr, ev.direct_honest):6.2f}% {nbias(ev.gen_gas_kr, ev.direct_honest):+5.1f} '
                f'| 직접(perfect) {mape(ev.gen_gas_kr, ev.direct_perfect):6.2f}% {nbias(ev.gen_gas_kr, ev.direct_perfect):+5.1f} '
                f'| 체인LGBM {mape(ev.gen_gas_kr, ev.est_gas_gen_raw):6.2f}% {nbias(ev.gen_gas_kr, ev.est_gas_gen_raw):+5.1f} | n {len(ev):5}')

    print('\n' + '=' * 110)
    print('7-D 직접(수요→가스 PatchTST) vs 체인(LGBM v2) — MW MAPE/bias, raw(보정 전), test 2026')
    print('=' * 110)
    print('[전체]')
    for n in HZ: print(line(r[r.horizon == n], f'D+{n}'))
    print('\n[낮 09-15h]')
    for n in HZ: print(line(r[(r.horizon == n) & r.day], f'D+{n} 낮'))
    print('\n[봄 낮 09-15h] — 덕커브 핵심')
    for n in HZ:
        g = r[(r.horizon == n) & r.day & (r.season == '봄')]
        if len(g): print(line(g, f'D+{n} 봄낮'))
    print('\nsaved compare_7d_results.parquet')


if __name__ == '__main__':
    try: sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception: pass
    main()

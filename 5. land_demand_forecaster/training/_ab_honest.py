# -*- coding: utf-8 -*-
"""honest A/B: PatchTST(5-B) vs LGBM v2(5-A_v2) — forecast_horizon 실예보 검증.

두 모델을 **동일 bases·동일 forecast 기상(exp_features.fh_weather)·동일 23:00 origin·
동일 타깃**으로 돌리고 (base,timestamp,horizon) inner-join 해 같은 평가셋에서 비교한다.
- LGBM: exp_features.eval_forecast 정본 그대로(v2 모델+init_score offset).
- PatchTST: 과거창 336h=실측, 미래블록=forecast(fh_weather), RevIN 내부.
출력: 지평별 MAPE/bias, 계절(겨울/봄/여름, 가능한 구간만)×낮/밤 MAPE/bias, 봄낮 집중.

실행: python "5. land_demand_forecaster/training/_ab_honest.py"
"""
from __future__ import annotations
import os, sys, json, glob, sqlite3, tempfile, importlib.util
import numpy as np, pandas as pd, torch, lightgbm as lgb
try: sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception: pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, '..', '..'))
MODELDIR = os.path.join(HERE, '..', 'model')
PKL = os.path.join(HERE, 'landdemand_patchtst')
# 360 단발 가중치 폴더 후보(존재하면 3자 비교에 포함)
PKL360_CANDS = [os.path.join(HERE, 'landdemand_patchtst360'),
                os.path.join(HERE, '..', 'demand_patchTST_pkl_360')]
PKL360 = next((p for p in PKL360_CANDS if os.path.isdir(p)), None)
# 15모델 MAE판(α없음) 폴더(존재하면 비교에 포함)
_pmae = os.path.join(HERE, 'landdemand_patchtst(MAE)')
PKL_MAE = _pmae if os.path.isdir(_pmae) else None
_pmse = os.path.join(HERE, 'landdemand_patchtst(MSE 0 alpha)')   # 실제=MSE+α1.0
PKL_MSE = _pmse if os.path.isdir(_pmse) else None
V2MODEL = os.path.join(MODELDIR, 'models', 'lgbm_land_demand_v2.txt')

# ── parquet 캐시: 비싼 forecast 백테스트(forward) 결과를 모델별로 저장 ──
CACHE = os.path.join(HERE, '_ab_cache'); os.makedirs(CACHE, exist_ok=True)
FORCE = ('--refresh' in sys.argv) or ('--force' in sys.argv)

def _newest_mtime(*paths):
    mt = 0.0
    for p in paths:
        if not p: continue
        if os.path.isdir(p):
            for f in glob.glob(os.path.join(p, '*')): mt = max(mt, os.path.getmtime(f))
        elif os.path.exists(p): mt = max(mt, os.path.getmtime(p))
    return mt

def cached(name, src_mtime, fn):
    """src(무게)보다 캐시가 최신이고 --refresh 아니면 parquet 로드, 아니면 계산 후 저장."""
    path = os.path.join(CACHE, name + '.parquet')
    if (not FORCE) and os.path.exists(path) and os.path.getmtime(path) >= src_mtime:
        df = pd.read_parquet(path); print(f'  [cache 적중] {name} ({len(df)}행) → {os.path.basename(path)}'); return df
    df = fn(); df.to_parquet(path, index=False); print(f'  [cache 저장] {name} ({len(df)}행)'); return df


def _imp(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m

expf = _imp('expf', os.path.join(MODELDIR, 'exp_features.py'))
ev   = _imp('ev', os.path.join(HERE, '_eval_patchtst_local.py'))   # 모델클래스·meta·scaler 재사용
bht  = expf.bht
PatchTST = ev.PatchTST_Demand_RevIN
meta, scaler = ev.meta, ev.scaler
HP, FF, HOR = meta['HP'], meta['future_features'], meta['HORIZONS']
SEQ = HP['seq_len']; PRED = meta['PRED_LEN']; DEVICE = 'cpu'
SEASON = expf.SEASON


def mape(a, p):
    a, p = np.asarray(a, float), np.asarray(p, float); m = (a > 0) & np.isfinite(a) & np.isfinite(p)
    return float(np.mean(np.abs(a[m]-p[m])/a[m])*100) if m.any() else np.nan
def bias(a, p):
    a, p = np.asarray(a, float), np.asarray(p, float); m = (a > 0) & np.isfinite(a) & np.isfinite(p)
    return float(np.mean((p[m]-a[m])/a[m])*100) if m.any() else np.nan


# ---------- LGBM v2 (정본 eval_forecast) ----------
def run_lgbm():
    vmeta = json.load(open(os.path.join(MODELDIR, 'models', 'model_meta_v2.json'), encoding='utf-8'))
    FEAT = vmeta['features']; init = float(vmeta['init_score']); best = int(vmeta['best_iteration'])
    vm = lgb.Booster(model_file=os.path.join(MODELDIR, 'models', 'lgbm_land_demand_v2.txt'))
    d_act = bht.load_actuals(); ppa = expf.load_capa()
    r = expf.eval_forecast(vm, best, FEAT, d_act, ppa, horizons=range(1, 16), offset=init)
    return r[['base', 'timestamp', 'horizon', 'actual', 'pred']].rename(columns={'pred': 'pred_lgbm'})


# ---------- PatchTST (동일 bases·forecast 기상) ----------
def _build_actual_ff(d, ppa):
    """과거창용: 실측 기상 aggregate → future_features 행렬(스케일 전)."""
    A = pd.DataFrame(index=d.index)
    A['temp_c']=d.temp_c; A['solar_rad']=d.solar_rad; A['wind_spd']=d.wind_spd
    A['total_cloud']=d.total_cloud; A['midlow_cloud']=d.midlow_cloud
    A['cap_btmppa']=expf.cap_for(d.index, ppa)
    A['Hour_sin']=np.sin(2*np.pi*d.index.hour/24); A['Hour_cos']=np.cos(2*np.pi*d.index.hour/24)
    A['Doy_sin']=np.sin(2*np.pi*d.index.dayofyear/365); A['Doy_cos']=np.cos(2*np.pi*d.index.dayofyear/365)
    A['is_weekend']=(d.day_type=='weekend').astype(float); A['is_holiday']=(d.day_type=='holiday').astype(float)
    return A[FF]


@torch.no_grad()
def run_patchtst(pkl_dir=PKL, scaler_x=scaler, meta_x=meta, col='pred_patch'):
    """15모델 direct PatchTST를 폴더 단위로 평가(α판·MAE판 공용). 동일 구조(256 hidden)."""
    FFx = meta_x['future_features']; HPx = meta_x['HP']; HORx = meta_x['HORIZONS']
    SEQx = HPx['seq_len']; PREDx = meta_x['PRED_LEN']
    d = expf.load_hist(); ppa = expf.load_capa()
    A = _build_actual_ff(d, ppa)[FFx]
    A_sc = pd.DataFrame(scaler_x.transform(A), index=A.index, columns=FFx)
    dem = d['real_demand_land']; daytype = d['day_type']
    models = {}
    for hn in HORx:
        m = PatchTST(len(FFx)+1, pred_len=PREDx, **HPx).to(DEVICE)
        m.load_state_dict(torch.load(os.path.join(pkl_dir, f'best_patchtst_landdemand_{hn}.pth'), map_location=DEVICE)); m.eval()
        models[hn] = m
    FF, HP, HOR, SEQ, PRED = FFx, HPx, HORx, SEQx, PREDx   # 아래 루프 호환
    with sqlite3.connect(os.path.join(ROOT, '1. data_fetcher_and_db', 'data', 'input_data_land.db')) as con:
        bases = [r[0] for r in con.execute('SELECT DISTINCT base FROM forecast_horizon ORDER BY base').fetchall()]
    sc = bht.build_scratch(os.path.join(tempfile.gettempdir(), f'ab_{col}.db'))
    rows = []
    for base in bases:
        O = pd.Timestamp(base).normalize() + pd.Timedelta(hours=23)
        if O not in A_sc.index: continue
        oi = A_sc.index.get_loc(O)
        if oi - (SEQ-1) < 0: continue
        past_ff = A_sc.iloc[oi-(SEQ-1): oi+1].values.astype(np.float32)        # (SEQ, F)
        past_y  = dem.iloc[oi-(SEQ-1): oi+1].values.astype(np.float32)[:, None] # (SEQ,1)
        if not np.isfinite(past_ff).all() or not np.isfinite(past_y).all(): continue
        bht.set_scratch_forecast(sc, base)
        p_num = torch.from_numpy(past_ff[None]); p_y = torch.from_numpy(past_y[None])
        for hn, off in HOR.items():
            n = int(hn[1:]); h0 = off + 1; H = np.arange(h0, h0 + PRED)
            tg = pd.DatetimeIndex([O + pd.Timedelta(hours=int(h)) for h in H])
            wx, valid = expf.fh_weather(sc, tg)
            F = pd.DataFrame(index=tg)
            F['temp_c']=wx['temp_c'].values; F['solar_rad']=wx['solar_rad'].values; F['wind_spd']=wx['wind_spd'].values
            F['total_cloud']=wx['total_cloud'].values; F['midlow_cloud']=wx['midlow_cloud'].values
            F['cap_btmppa']=expf.cap_for(tg, ppa)
            F['Hour_sin']=np.sin(2*np.pi*tg.hour/24); F['Hour_cos']=np.cos(2*np.pi*tg.hour/24)
            F['Doy_sin']=np.sin(2*np.pi*tg.dayofyear/365); F['Doy_cos']=np.cos(2*np.pi*tg.dayofyear/365)
            dt = daytype.reindex(tg)
            F['is_weekend']=(dt=='weekend').astype(float).values; F['is_holiday']=(dt=='holiday').astype(float).values
            ok = valid.values & F[FF].notna().all(axis=1).values
            if not ok.any(): continue
            F_sc = scaler_x.transform(F[FF].ffill().bfill())   # invalid 행은 ok 마스크로 후처리 제외
            f_num = torch.from_numpy(F_sc.astype(np.float32)[None])
            pred, _ = models[hn]({'past_numeric': p_num, 'past_y': p_y, 'future_numeric': f_num})
            pr = np.clip(pred.numpy().ravel(), 0, None)
            pr[~ok] = np.nan
            rows.append(pd.DataFrame({'base': base, 'timestamp': tg, 'horizon': n,
                                      'actual': dem.reindex(tg).values, col: pr}))
    sc.close()
    return pd.concat(rows, ignore_index=True)


@torch.no_grad()
def run_patchtst360():
    """단발 pred_len=360 모델: base마다 1 forward로 360h 예측 → D+n 블록 슬라이스."""
    import joblib
    meta360 = joblib.load(os.path.join(PKL360, 'metadata_landdemand360.pkl'))
    scaler360 = joblib.load(os.path.join(PKL360, 'scaler_landdemand.pkl'))
    FF3 = meta360['future_features']; HP3 = meta360['HP']; PRED3 = meta360['PRED_LEN']; SEQ3 = HP3['seq_len']
    d = expf.load_hist(); ppa = expf.load_capa()
    A = _build_actual_ff(d, ppa)[FF3]
    A_sc = pd.DataFrame(scaler360.transform(A), index=A.index, columns=FF3)
    dem = d['real_demand_land']; daytype = d['day_type']
    import torch.nn as nn
    mdl = PatchTST(len(FF3)+1, pred_len=PRED3, **HP3)
    # 360 생성기는 regressor hidden=512 (15모델은 256) → 재구성 후 로드
    fut_flat = PRED3 * len(FF3)
    mdl.regressor = nn.Sequential(nn.Linear(HP3['d_model'] + fut_flat, 512), nn.LeakyReLU(0.1),
                                  nn.Dropout(HP3['dropout']), nn.Linear(512, PRED3))
    mdl = mdl.to(DEVICE)
    mdl.load_state_dict(torch.load(os.path.join(PKL360, 'best_patchtst_landdemand_360.pth'), map_location=DEVICE)); mdl.eval()
    with sqlite3.connect(os.path.join(ROOT, '1. data_fetcher_and_db', 'data', 'input_data_land.db')) as con:
        bases = [r[0] for r in con.execute('SELECT DISTINCT base FROM forecast_horizon ORDER BY base').fetchall()]
    sc = bht.build_scratch(os.path.join(tempfile.gettempdir(), 'ab_patch360.db'))
    rows = []
    for base in bases:
        O = pd.Timestamp(base).normalize() + pd.Timedelta(hours=23)
        if O not in A_sc.index: continue
        oi = A_sc.index.get_loc(O)
        if oi - (SEQ3-1) < 0: continue
        past_ff = A_sc.iloc[oi-(SEQ3-1): oi+1].values.astype(np.float32)
        past_y  = dem.iloc[oi-(SEQ3-1): oi+1].values.astype(np.float32)[:, None]
        if not np.isfinite(past_ff).all() or not np.isfinite(past_y).all(): continue
        bht.set_scratch_forecast(sc, base)
        tg = pd.DatetimeIndex([O + pd.Timedelta(hours=int(h)) for h in range(1, PRED3+1)])
        wx, valid = expf.fh_weather(sc, tg)
        F = pd.DataFrame(index=tg)
        F['temp_c']=wx['temp_c'].values; F['solar_rad']=wx['solar_rad'].values; F['wind_spd']=wx['wind_spd'].values
        F['total_cloud']=wx['total_cloud'].values; F['midlow_cloud']=wx['midlow_cloud'].values
        F['cap_btmppa']=expf.cap_for(tg, ppa)
        F['Hour_sin']=np.sin(2*np.pi*tg.hour/24); F['Hour_cos']=np.cos(2*np.pi*tg.hour/24)
        F['Doy_sin']=np.sin(2*np.pi*tg.dayofyear/365); F['Doy_cos']=np.cos(2*np.pi*tg.dayofyear/365)
        dt = daytype.reindex(tg)
        F['is_weekend']=(dt=='weekend').astype(float).values; F['is_holiday']=(dt=='holiday').astype(float).values
        ok = valid.values & F[FF3].notna().all(axis=1).values
        if not ok.any(): continue
        F_sc = scaler360.transform(F[FF3].ffill().bfill())
        pred, _ = mdl({'past_numeric': torch.from_numpy(past_ff[None]),
                       'past_y': torch.from_numpy(past_y[None]),
                       'future_numeric': torch.from_numpy(F_sc.astype(np.float32)[None])})
        pr = np.clip(pred.numpy().ravel(), 0, None); pr[~ok] = np.nan
        hor = (np.arange(PRED3) // 24) + 1   # D+n 블록
        rows.append(pd.DataFrame({'base': base, 'timestamp': tg, 'horizon': hor,
                                  'pred_patch360': pr}))
    sc.close()
    return pd.concat(rows, ignore_index=True)


def report(m, cols):
    """cols: [(label, colname), ...] — 비교할 모델들(첫 항목 기준)."""
    m = m.copy()
    m['ts'] = pd.to_datetime(m['timestamp'])
    m['season'] = m.ts.dt.month.map(SEASON)
    m['daypart'] = np.where((m.ts.dt.hour >= 9) & (m.ts.dt.hour <= 15), '낮', '밤')
    print(f"\n공통 평가셋 행수: {len(m)}  (forecast 가용·전 모델 예측·실측 존재 교집합)")
    labels = [l for l, _ in cols]

    print('\n======== 지평별 MAPE ========')
    print(f"{'지평':>4} | " + ' '.join(f'{l:>7}' for l in labels) + ' | ' + ' '.join(f'{"낮"+l:>8}' for l in labels))
    for n in range(1, 16):
        g = m[m.horizon == n]; gd = g[g.daypart == '낮']
        if g.empty: continue
        print(f" D+{n:>2} | " + ' '.join(f'{mape(g.actual,g[c]):7.2f}' for _, c in cols) +
              ' | ' + ' '.join(f'{mape(gd.actual,gd[c]):8.2f}' for _, c in cols))

    print('\n======== 계절×낮밤 MAPE / bias ========')
    print(f"{'구간':>8} | {'n':>6} | " + ' '.join(f'{"M "+l:>7}' for l in labels) + ' | ' + ' '.join(f'{"b "+l:>7}' for l in labels))
    for s in ['겨울', '봄', '여름', '가을']:
        for dp in ['낮', '밤']:
            g = m[(m.season == s) & (m.daypart == dp)]
            if g.empty: continue
            print(f" {s}{dp:>4} | {len(g):6d} | " + ' '.join(f'{mape(g.actual,g[c]):7.2f}' for _, c in cols) +
                  ' | ' + ' '.join(f'{bias(g.actual,g[c]):+7.2f}' for _, c in cols))

    print('\n======== 전체 요약 (MAPE / 낮MAPE / 낮bias) ========')
    md = m[m.daypart == '낮']
    for l, c in cols:
        print(f" {l:>8}  전체 {mape(m.actual,m[c]):5.2f}  낮 {mape(md.actual,md[c]):5.2f}  낮bias {bias(md.actual,md[c]):+5.2f}")
    m.to_csv(os.path.join(HERE, '_ab_honest_merged.csv'), index=False)
    print('\n저장: _ab_honest_merged.csv')


def main():
    if FORCE: print('  (--refresh: 캐시 무시하고 전부 재계산)')
    print('[1] LGBM v2 ...'); L = cached('lgbm', _newest_mtime(V2MODEL), run_lgbm)
    print('[2] PatchTST 15모델(α) ...'); P = cached('patch_a', _newest_mtime(PKL), run_patchtst)
    cols = [('LGBM', 'pred_lgbm'), ('MSEα1.3', 'pred_patch')]
    m = L.merge(P[['base', 'timestamp', 'horizon', 'pred_patch']], on=['base', 'timestamp', 'horizon'], how='inner')

    def _add(label, folder, col):
        import joblib
        nonlocal m
        meta_x = joblib.load(os.path.join(folder, 'metadata_landdemand.pkl'))
        scaler_x = joblib.load(os.path.join(folder, 'scaler_landdemand.pkl'))
        print(f'[+] {label} ...')
        Px = cached(col, _newest_mtime(folder), lambda: run_patchtst(folder, scaler_x, meta_x, col=col))
        m = m.merge(Px[['base', 'timestamp', 'horizon', col]], on=['base', 'timestamp', 'horizon'], how='inner')
        cols.append((label, col))

    if PKL_MAE: _add('MAEα0', PKL_MAE, 'pred_patch_mae')
    if PKL_MSE: _add('MSEα1.0', PKL_MSE, 'pred_patch_mse')
    if PKL360:
        print('[+] 360 단발 ...'); P3 = cached('patch360', _newest_mtime(PKL360), run_patchtst360)
        m = m.merge(P3[['base', 'timestamp', 'horizon', 'pred_patch360']], on=['base', 'timestamp', 'horizon'], how='inner')
        cols.append(('360', 'pred_patch360'))
    print('[final] inner-join + 집계...')
    sub = [c for _, c in cols]
    m = m.dropna(subset=['actual'] + sub); m = m[m.actual > 0]
    report(m, cols)


if __name__ == '__main__':
    main()

# -*- coding: utf-8 -*-
"""스윕(5-B3) honest 평가: landdemand_sweep/ 의 각 config를 D+5/10/15 forecast_horizon 실예보로
LGBM(캐시)·하이브리드와 동일창 비교. 낮/밤 분리. 장지평 우승 HP·피처 선정.

피처 조립은 학습(_gen_landdemand_sweep.py feature_cols)을 미러 — lag_week 는 지평별 정직가드
(k=off+24 이상 최소 168배수, 원점서 known). base/anchor/anchor2=집계기상(fh_weather),
perstation=지점raw 예보(fh_perstation).

실행:
  python _ab_sweep_eval.py --check     # 무게 없이 피처조립·정직성만 검증(dry)
  python _ab_sweep_eval.py             # 전체 honest 평가(무게 필요)
"""
from __future__ import annotations
import os, sys, math, json, glob, sqlite3, tempfile, importlib.util
import numpy as np, pandas as pd, torch, joblib
try: sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception: pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, '..', '..'))
MODELDIR = os.path.join(HERE, '..', 'model')
SWEEP = next((os.path.join(HERE, d) for d in ['landdemand_final', 'final_patchtst', 'landdemand_sweep']
              if os.path.isdir(os.path.join(HERE, d))), os.path.join(HERE, 'landdemand_sweep'))
CACHE = os.path.join(HERE, '_ab_cache')
DB = os.path.join(ROOT, '1. data_fetcher_and_db', 'data', 'input_data_land.db')
DEVICE = 'cpu'
CHECK = '--check' in sys.argv

def _imp(n, p):
    s = importlib.util.spec_from_file_location(n, p); m = importlib.util.module_from_spec(s); s.loader.exec_module(m); return m
expf = _imp('expf', os.path.join(MODELDIR, 'exp_features.py'))
ev = _imp('ev', os.path.join(HERE, '_eval_patchtst_local.py'))
bht = expf.bht
SEASON = expf.SEASON
PatchTST = ev.PatchTST_Demand_RevIN
HORIZONS = {'D5': 96, 'D10': 216, 'D15': 336}
STATIONS, SOLAR_SEL, WIND_SEL = expf.STATIONS, expf.SOLAR_SEL, expf.WIND_SEL
CAL = ['Hour_sin', 'Hour_cos', 'Doy_sin', 'Doy_cos', 'is_weekend', 'is_holiday']
FORE = {'temp_c': 'temp', 'solar_rad': 'radiation', 'wind_spd': 'wind_spd_10m'}

def weekly_k(off): return 168 * math.ceil((off + 24) / 168)

def mape(a, p):
    a, p = np.asarray(a, float), np.asarray(p, float); k = (a > 0) & np.isfinite(a) & np.isfinite(p)
    return float(np.mean(np.abs(a[k]-p[k])/a[k])*100) if k.any() else np.nan
def bias(a, p):
    a, p = np.asarray(a, float), np.asarray(p, float); k = (a > 0) & np.isfinite(a) & np.isfinite(p)
    return float(np.mean((p[k]-a[k])/a[k])*100) if k.any() else np.nan


def feature_cols(fset, off):
    if fset == 'perstation':
        wx = ([f'temp_c_{s}' for s in STATIONS] + [f'solar_rad_{s}' for s in SOLAR_SEL] +
              [f'wind_spd_{s}' for s in WIND_SEL] + [f'total_cloud_{s}' for s in SOLAR_SEL] +
              [f'midlow_cloud_{s}' for s in SOLAR_SEL])
    else:
        wx = ['temp_c', 'solar_rad', 'wind_spd', 'total_cloud', 'midlow_cloud']
    cols = wx + ['cap_btmppa'] + CAL
    if fset in ('anchor', 'anchor2'): cols += [f'lag_week_{off}']
    if fset == 'anchor2': cols += [f'lag_2week_{off}']
    return cols


def load_actual_wide():
    """실측: 집계기상 + 지점raw기상 + 수요 + day_type (과거창·perstation 공용)."""
    pull = ['timestamp', 'real_demand_land', 'day_type']
    pull += [f'temp_c_{s}' for s in STATIONS] + [f'solar_rad_{s}' for s in SOLAR_SEL]
    pull += [f'total_cloud_{s}' for s in SOLAR_SEL] + [f'midlow_cloud_{s}' for s in SOLAR_SEL] + [f'wind_spd_{s}' for s in WIND_SEL]
    with sqlite3.connect(DB) as con:
        raw = pd.read_sql(f"SELECT {', '.join(pull)} FROM historical", con, parse_dates=['timestamp'])
    raw = raw.sort_values('timestamp'); idx = pd.date_range(raw.timestamp.min(), raw.timestamp.max(), freq='h')
    d = raw.set_index('timestamp').reindex(idx); d.index.name = 'timestamp'
    d.loc[d.real_demand_land == 0, 'real_demand_land'] = np.nan
    d['Demand'] = d['real_demand_land'].interpolate('time').ffill().bfill()
    for c in pull[3:]: d[c] = pd.to_numeric(d[c], errors='coerce').interpolate('time', limit=6).ffill().bfill()
    d['temp_c'] = d[[f'temp_c_{s}' for s in STATIONS]].mean(1)
    d['solar_rad'] = d[[f'solar_rad_{s}' for s in SOLAR_SEL]].mean(1)
    d['wind_spd'] = d[[f'wind_spd_{s}' for s in WIND_SEL]].mean(1)
    d['total_cloud'] = d[[f'total_cloud_{s}' for s in SOLAR_SEL]].mean(1)
    d['midlow_cloud'] = d[[f'midlow_cloud_{s}' for s in SOLAR_SEL]].mean(1)
    d['day_type'] = d['day_type'].ffill().bfill()
    return d


def add_cal_capa(df, ppa):
    df = df.copy()
    df['cap_btmppa'] = expf.cap_for(df.index, ppa)
    df['Hour_sin'] = np.sin(2*np.pi*df.index.hour/24); df['Hour_cos'] = np.cos(2*np.pi*df.index.hour/24)
    df['Doy_sin'] = np.sin(2*np.pi*df.index.dayofyear/365); df['Doy_cos'] = np.cos(2*np.pi*df.index.dayofyear/365)
    df['is_weekend'] = (df['day_type'] == 'weekend').astype(float); df['is_holiday'] = (df['day_type'] == 'holiday').astype(float)
    return df


def fh_perstation(sc, tg):
    """지점별 raw 예보(평균 안 함) — perstation config 용."""
    cols = ([f'{FORE["temp_c"]}_{s}' for s in STATIONS] + [f'{FORE["solar_rad"]}_{s}' for s in SOLAR_SEL] +
            [f'{FORE["wind_spd"]}_{s}' for s in WIND_SEL] + [f'total_cloud_{s}' for s in SOLAR_SEL] + [f'midlow_cloud_{s}' for s in SOLAR_SEL])
    ext = pd.date_range(tg.min()-pd.Timedelta(hours=3), tg.max()+pd.Timedelta(hours=3), freq='h')
    sel = ', '.join(f'"{c}"' for c in ['timestamp']+cols)
    fc = pd.read_sql(f'SELECT {sel} FROM forecast WHERE timestamp BETWEEN ? AND ? ORDER BY timestamp',
                     sc, params=(bht._S(ext[0]), bht._S(ext[-1])), parse_dates=['timestamp']).set_index('timestamp')
    fc = fc.apply(pd.to_numeric, errors='coerce').reindex(ext)
    out = pd.DataFrame(index=tg)
    rename = {}
    for s in STATIONS: rename[f'temp_c_{s}'] = f'{FORE["temp_c"]}_{s}'
    for s in SOLAR_SEL: rename[f'solar_rad_{s}'] = f'{FORE["solar_rad"]}_{s}'
    for s in WIND_SEL: rename[f'wind_spd_{s}'] = f'{FORE["wind_spd"]}_{s}'
    for s in SOLAR_SEL: rename[f'total_cloud_{s}'] = f'total_cloud_{s}'; rename[f'midlow_cloud_{s}'] = f'midlow_cloud_{s}'
    for feat, fcol in rename.items():
        out[feat] = fc[fcol].interpolate('time', limit=3, limit_area='inside').reindex(tg).values
    valid = out.notna().all(axis=1)
    return out, valid


def fh_weather_sel(sc, tg, temp_sel):
    """집계 예보 — temp_c 만 temp_sel 지점평균(solar/wind/cloud은 SOLAR_SEL/WIND_SEL). temp_sel=STATIONS면 fh_weather 동일."""
    cols = sorted(set([f'{FORE["temp_c"]}_{s}' for s in temp_sel] + [f'{FORE["solar_rad"]}_{s}' for s in SOLAR_SEL] +
                      [f'{FORE["wind_spd"]}_{s}' for s in WIND_SEL] + [f'total_cloud_{s}' for s in SOLAR_SEL] + [f'midlow_cloud_{s}' for s in SOLAR_SEL]))
    ext = pd.date_range(tg.min()-pd.Timedelta(hours=3), tg.max()+pd.Timedelta(hours=3), freq='h')
    sel = ', '.join(f'"{c}"' for c in ['timestamp']+cols)
    fc = pd.read_sql(f'SELECT {sel} FROM forecast WHERE timestamp BETWEEN ? AND ? ORDER BY timestamp',
                     sc, params=(bht._S(ext[0]), bht._S(ext[-1])), parse_dates=['timestamp']).set_index('timestamp')
    fc = fc.apply(pd.to_numeric, errors='coerce').reindex(ext)
    def mi(cs): return fc[cs].mean(1).interpolate('time', limit=3, limit_area='inside').reindex(tg).values
    out = pd.DataFrame(index=tg)
    out['temp_c'] = mi([f'{FORE["temp_c"]}_{s}' for s in temp_sel])
    out['solar_rad'] = mi([f'{FORE["solar_rad"]}_{s}' for s in SOLAR_SEL])
    out['wind_spd'] = mi([f'{FORE["wind_spd"]}_{s}' for s in WIND_SEL])
    out['total_cloud'] = mi([f'total_cloud_{s}' for s in SOLAR_SEL]); out['midlow_cloud'] = mi([f'midlow_cloud_{s}' for s in SOLAR_SEL])
    return out, out[['temp_c', 'solar_rad', 'wind_spd']].notna().all(axis=1)


@torch.no_grad()
def run_config(name, cfg, d, ppa, lgbm_df):
    fset = cfg['feature_set']; hp = cfg['hp']
    temp_sel = cfg.get('temp_sel', STATIONS)
    hmap = cfg.get('horizons_map', HORIZONS)
    wt = cfg.get('weight_tmpl', '{name}_{h}.pth'); st = cfg.get('scaler_tmpl', '{name}_{h}_scaler.pkl')
    # 과거창 temp_c 를 temp_sel 로 재집계(train-serve 일관). solar/wind/cloud는 그대로.
    dloc = d.copy(); dloc['temp_c'] = d[[f'temp_c_{s}' for s in temp_sel]].mean(1)
    dW = add_cal_capa(dloc, ppa)
    sc_db = bht.build_scratch(os.path.join(tempfile.gettempdir(), f'sweep_{name}.db'))
    with sqlite3.connect(DB) as con:
        bases = [r[0] for r in con.execute('SELECT DISTINCT base FROM forecast_horizon ORDER BY base').fetchall()]
    dem = d['Demand']; rows = []
    for hname, off in hmap.items():
        wpath = os.path.join(SWEEP, wt.format(name=name, h=hname)); spath = os.path.join(SWEEP, st.format(name=name, h=hname))
        if not CHECK and (not os.path.exists(wpath) or not os.path.exists(spath)):
            print(f'  [skip] {name}/{hname} (무게 또는 scaler 없음)'); continue
        cols = feature_cols(fset, off)
        scaler = None if CHECK else joblib.load(spath)
        nf = len(cols) + 1; SEQ = hp['seq_len']
        # 과거창 실측 피처행렬(스케일 전): 집계or지점 + capa/달력 + (lag_week 실측 shift)
        A = dW.copy()
        if fset in ('anchor', 'anchor2'): A[f'lag_week_{off}'] = A['Demand'].shift(weekly_k(off))
        if fset == 'anchor2': A[f'lag_2week_{off}'] = A['Demand'].shift(weekly_k(off)+168)
        A_sc = A[cols] if CHECK else pd.DataFrame(scaler.transform(A[cols]), index=A.index, columns=cols)
        mdl = None
        if not CHECK:
            mdl = PatchTST(nf, pred_len=24, **hp).to(DEVICE)
            mdl.load_state_dict(torch.load(wpath, map_location=DEVICE)); mdl.eval()
        nchk = 0
        for base in bases:
            O = pd.Timestamp(base).normalize() + pd.Timedelta(hours=23)
            if O not in A_sc.index: continue
            oi = A_sc.index.get_loc(O)
            if oi-(SEQ-1) < 0: continue
            past = A_sc.iloc[oi-(SEQ-1):oi+1].values.astype(np.float32)
            py = dem.iloc[oi-(SEQ-1):oi+1].values.astype(np.float32)[:, None]
            if not (np.isfinite(past).all() and np.isfinite(py).all()): continue
            bht.set_scratch_forecast(sc_db, base)
            H = np.arange(off+1, off+25); tg = pd.DatetimeIndex([O + pd.Timedelta(hours=int(h)) for h in H])
            # 정직성 점검: lag_week 타깃-k 가 원점 이전
            if fset in ('anchor', 'anchor2'):
                assert (tg.max() - pd.Timedelta(hours=weekly_k(off))) <= O, 'lag_week leak!'
            # 미래블록 피처
            if fset == 'perstation': wx, valid = fh_perstation(sc_db, tg)
            else: wx, valid = fh_weather_sel(sc_db, tg, temp_sel)
            Fd = wx.copy(); Fd['day_type'] = d['day_type'].reindex(tg).values
            Fd = add_cal_capa(Fd, ppa)
            if fset in ('anchor', 'anchor2'): Fd[f'lag_week_{off}'] = dem.reindex(tg - pd.Timedelta(hours=weekly_k(off))).values
            if fset == 'anchor2': Fd[f'lag_2week_{off}'] = dem.reindex(tg - pd.Timedelta(hours=weekly_k(off)+168)).values
            ok = valid.values & Fd[cols].notna().all(axis=1).values
            if not ok.any(): continue
            nchk += int(ok.sum())
            if CHECK:
                if nchk > 0: break   # 조립·정직성만 확인되면 다음 지평
                continue
            F_sc = scaler.transform(Fd[cols].ffill().bfill())
            pred, _ = mdl({'past_numeric': torch.from_numpy(past[None]), 'past_y': torch.from_numpy(py[None]),
                           'future_numeric': torch.from_numpy(F_sc.astype(np.float32)[None])})
            pr = np.clip(pred.numpy().ravel(), 0, None); pr[~ok] = np.nan
            rows.append(pd.DataFrame({'base': base, 'timestamp': tg, 'horizon': int(hname[1:]), 'pred': pr}))
        if CHECK:
            print(f'  [{name}/{hname}] cols={nf-1} 조립 OK · 정직성 OK · 첫블록 valid={nchk}')
    sc_db.close()
    if CHECK or not rows: return None
    P = pd.concat(rows, ignore_index=True)
    g = lgbm_df.merge(P, on=['base', 'timestamp', 'horizon'], how='inner').dropna(subset=['actual', 'pred_lgbm', 'pred'])
    g = g[g.actual > 0]; ts = pd.to_datetime(g.timestamp)
    g = g.assign(daypart=np.where((ts.dt.hour >= 9) & (ts.dt.hour <= 15), '주간', '야간'), season=ts.dt.month.map(SEASON))
    return g


def grid(g, name, n):
    gh = g[g.horizon == n]
    if gh.empty: return
    print(f'\n[{name}] D+{n}  (n={len(gh)})   각 칸 = LGBM → {name} MAPE%')
    print(f"  {'계절':<5}{'전체':>15}{'주간':>15}{'야간':>15}")
    for s in ['전체', '겨울', '봄', '여름', '가을']:
        gs = gh if s == '전체' else gh[gh.season == s]
        if gs.empty: continue
        cells = []
        for dp in ['전체', '주간', '야간']:
            gd = gs if dp == '전체' else gs[gs.daypart == dp]
            cells.append('     -     ' if gd.empty else f'{mape(gd.actual, gd.pred_lgbm):5.2f}→{mape(gd.actual, gd.pred):5.2f}')
        print(f"  {s:<5}" + ''.join(f'{c:>15}' for c in cells))


def main():
    reg = json.load(open(os.path.join(SWEEP, 'registry.json'), encoding='utf-8')) if os.path.isdir(SWEEP) and os.path.exists(os.path.join(SWEEP, 'registry.json')) else None
    if reg is None:
        if CHECK:
            reg = {'base': dict(feature_set='base', hp=dict(seq_len=336, patch_len=24, stride=12, d_model=256, num_heads=4, num_layers=3, d_ff=1024, dropout=0.2), loss='mae'),
                   'anchor': dict(feature_set='anchor', hp=dict(seq_len=336, patch_len=24, stride=12, d_model=256, num_heads=4, num_layers=3, d_ff=1024, dropout=0.2), loss='mae'),
                   'perstation': dict(feature_set='perstation', hp=dict(seq_len=336, patch_len=24, stride=12, d_model=256, num_heads=4, num_layers=3, d_ff=1024, dropout=0.2), loss='mae')}
            print('[--check] registry 없음 → 대표 3 config(base/anchor/perstation)로 조립·정직성만 검증')
        else:
            reg = {}
    # 최종 모델(metadata_landdemand_final.pkl) 자동 포함 — TEMP_SEL·전 15지평·anchor·파일명 상이
    fmpath = os.path.join(SWEEP, 'metadata_landdemand_final.pkl')
    if os.path.exists(fmpath):
        fm = joblib.load(fmpath)
        reg['final'] = dict(feature_set='anchor', hp=fm['HP'], loss=fm.get('loss', 'mae'),
                            temp_sel=fm.get('TEMP_SEL', STATIONS),
                            horizons_map={h: v['offset'] for h, v in fm['horizons'].items()},
                            weight_tmpl='best_patchtst_landdemand_{h}.pth', scaler_tmpl='{h}_scaler.pkl')
        print(f"[final 모델 포함] TEMP_SEL={reg['final']['temp_sel']} | 지평 {len(reg['final']['horizons_map'])}개")
    if not reg:
        sys.exit('registry.json·metadata_landdemand_final.pkl 둘 다 없음 — Colab 산출물부터 넣어주세요.')
    d = load_actual_wide(); ppa = expf.load_capa()
    lgbm_df = None
    if not CHECK:
        lp = os.path.join(CACHE, 'lgbm.parquet')
        if not os.path.exists(lp): sys.exit('lgbm 캐시 없음 — 먼저 _ab_honest.py 1회 실행.')
        lgbm_df = pd.read_parquet(lp)
    res = {}
    for name, cfg in reg.items():
        g = run_config(name, cfg, d, ppa, lgbm_df)
        if not CHECK and g is not None: res[name] = g
    if CHECK:
        print('\n[--check] PASS — 피처 조립·정직가드·forecast 결합 정상. 무게 오면 --check 빼고 실행.'); return
    print(f'\n폴더: {os.path.basename(SWEEP)} | 평가 config: {list(res)} | (가을=forecast_horizon에 없음)')
    print('\n======== honest 전체 요약 (config 자체 valid행 기준, LGBM→config) ========')
    for name, g in res.items():
        hs = sorted(g.horizon.unique())
        cells = [f'D+{n} {mape(g[g.horizon==n].actual,g[g.horizon==n].pred_lgbm):4.1f}→{mape(g[g.horizon==n].actual,g[g.horizon==n].pred):4.1f}' for n in hs]
        print(f'  {name:<10} ' + '  '.join(cells))
    print('\n======== 계절×낮밤 상세 (각 칸 LGBM→config) ========')
    for name, g in res.items():
        for n in sorted(g.horizon.unique()):
            grid(g, name, n)
    print('\n저장: _ab_sweep_merged.parquet')
    pd.concat([g.assign(config=name) for name, g in res.items()], ignore_index=True).to_parquet(os.path.join(HERE, '_ab_sweep_merged.parquet'), index=False)


if __name__ == '__main__':
    main()

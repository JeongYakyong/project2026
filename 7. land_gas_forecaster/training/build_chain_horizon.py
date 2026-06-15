# -*- coding: utf-8 -*-
"""Stage 4 — 전국 풀체인(5→6→7) 정직 지평 백테스트 + est_horizon_land 적재 (D+1..15).

수요=v2(D+15, lag168/336/504 정직가드, est_horizon_land 에 이미 적재됨) → 신재생=serve6 _predict_day
(PatchTST {1-7,12,14,15} / 나머지 LGBM 폴백) → 가스=v2(자기회귀, h 1..360).  forecast_horizon 전
base × d=1..15.  기상 폴백은 serve 코드 정책을 따름(기후값 금지 규칙은 해제됨 — 블렌딩 도입 전제).

가스 lag/rec = historical 실측(원점 가용).  가스는 raw(booster+offset, 보정 전)로 적재 — 보정·블렌딩은
Stage 5 에서 이 정직 아카이브 위에 적합.  실측 join 으로 지평별 MAPE/bias 산출.

적재: est_horizon_land 에 est_market_renew_land, est_net_load_land, est_gas_gen_land_raw 컬럼 UPSERT.
산출: 콘솔 지평표 + horizon_backtest_v2.parquet(갱신, 평가/Stage5 용).
"""
from __future__ import annotations
import os, sys, json, sqlite3, importlib.util, tempfile, time, warnings
import numpy as np, pandas as pd, lightgbm as lgb
warnings.filterwarnings('ignore')

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, '..', '..'))
DB = os.path.join(ROOT, '1. data_fetcher_and_db', 'data', 'input_data_land.db')


def _imp(name, path):
    s = importlib.util.spec_from_file_location(name, path); m = importlib.util.module_from_spec(s)
    sys.modules[name] = m; s.loader.exec_module(m); return m


bht = _imp('bht', os.path.join(HERE, 'build_horizon_backtest.py'))
serve6 = _imp('serve_solarwind_land', os.path.join(ROOT, '6. land_solarwind_forecaster', 'serve_solarwind_land.py'))
sg = _imp('serve_land_gas', os.path.join(ROOT, '7. land_gas_forecaster', 'serve_land_gas.py'))

HZ = tuple(range(1, 16))   # D+1..D+15 연속
SEASON = {12: '겨울', 1: '겨울', 2: '겨울', 3: '봄', 4: '봄', 5: '봄', 6: '여름', 7: '여름', 8: '여름', 9: '가을', 10: '가을', 11: '가을'}


def mape(a, p):
    a, p = np.asarray(a, float), np.asarray(p, float); m = (a > 0) & np.isfinite(a) & np.isfinite(p)
    return float(np.mean(np.abs(a[m]-p[m])/a[m])*100) if m.any() else np.nan


def nbias(a, p):
    a, p = np.asarray(a, float), np.asarray(p, float); m = (a > 0) & np.isfinite(a) & np.isfinite(p)
    return float(np.mean((p[m]-a[m])/a[m])*100) if m.any() else np.nan


def nmae(a, p):
    a, p = np.asarray(a, float), np.asarray(p, float); m = np.isfinite(a) & np.isfinite(p)
    return float(np.mean(np.abs(a[m]-p[m]))/np.mean(np.abs(a[m]))*100) if m.any() else np.nan


def build():
    d_act = bht.load_actuals()
    gas_series = sg.load_gas_series()
    booster = lgb.Booster(model_file=sg.MODEL); offset = sg._OFFSET
    A6 = serve6.load_assets()
    rdl = d_act['real_demand_land']; rgt = d_act['renew_gen_total_kr']; gki = d_act['gen_gas_kr']
    with sqlite3.connect(DB) as con:
        bases = [r[0] for r in con.execute('SELECT DISTINCT base FROM forecast_horizon ORDER BY base')]
    sc = bht.build_scratch(os.path.join(tempfile.gettempdir(), 'chain_horizon.db'))
    rows = []; t0 = time.time()
    for bi, base in enumerate(bases, 1):
        O = pd.Timestamp(base).normalize() + pd.Timedelta(hours=23)
        bht.set_scratch_forecast(sc, base)
        with sqlite3.connect(DB) as con:   # 수요(이미 적재된 정직 예측) 읽기
            dem_s = pd.read_sql('SELECT timestamp, est_demand_land FROM est_horizon_land WHERE base=?',
                                con, params=(base,), parse_dates=['timestamp']).set_index('timestamp')['est_demand_land']
        rec24 = float(gas_series.loc[O - pd.Timedelta(hours=23):O].mean())
        rec168 = float(gas_series.loc[O - pd.Timedelta(hours=167):O].mean())
        if not (np.isfinite(rec24) and np.isfinite(rec168)):
            continue
        for n in HZ:
            try:
                h0, h1 = (n-1)*24+1, n*24; H = np.arange(h0, h1+1)
                tg = pd.DatetimeIndex([O + pd.Timedelta(hours=int(h)) for h in H])
                est_dem = dem_s.reindex(tg).values
                out6, *_ = serve6._predict_day(sc, O.normalize(), n, A6)
                mr = pd.Series(out6[serve6.OUT['mr']].values, index=pd.DatetimeIndex(out6['timestamp'])).reindex(tg).values
                m = np.isfinite(est_dem) & np.isfinite(mr)
                if not m.any():
                    continue
                tg2 = tg[m]; H2 = H[m]; dem2 = est_dem[m]; mr2 = mr[m].astype(float)
                gf = pd.DataFrame(index=tg2)
                gf['real_demand_land'] = dem2
                gf['renew_util'] = mr2 / sg._renew_cap(tg2)
                gf['gas_lag168'] = np.where(H2 <= 168, gas_series.reindex(tg2 - pd.Timedelta(hours=168)).values, np.nan)
                gf['gas_lag24'] = np.where(H2 <= 24, gas_series.reindex(tg2 - pd.Timedelta(hours=24)).values, np.nan)
                gf['gas_rec24'] = rec24; gf['gas_rec168'] = rec168
                gf['h'] = H2; gf['hour'] = tg2.hour; gf['dow'] = tg2.dayofweek; gf['doy'] = tg2.dayofyear
                gas_raw = booster.predict(gf[sg.FEATS]) + offset
                rows.append(pd.DataFrame({
                    'base': base, 'timestamp': tg2, 'horizon': n,
                    'est_demand': dem2, 'est_renew': mr2, 'est_net_load': dem2 - mr2,
                    'est_gas_gen_raw': gas_raw,
                    'real_demand_land': rdl.reindex(tg2).values, 'renew_gen_total_kr': rgt.reindex(tg2).values,
                    'gen_gas_kr': gki.reindex(tg2).values,
                    'hour': tg2.hour, 'dow': tg2.dayofweek, 'doy': tg2.dayofyear}))
            except Exception as e:
                continue
        if bi % 30 == 0 or bi == len(bases):
            print(f'  base {bi}/{len(bases)} ({base[:10]})  누적 {len(rows)} blocks  {time.time()-t0:.0f}s')
    sc.close()
    return pd.concat(rows, ignore_index=True)


def write_archive(r):
    data = [(pd.Timestamp(t).strftime('%Y-%m-%d %H:%M:%S'), str(b), int(h), float(mr), float(nl), float(g))
            for b, t, h, mr, nl, g in zip(r.base, r.timestamp, r.horizon, r.est_renew, r.est_net_load, r.est_gas_gen_raw)
            if np.isfinite(g)]
    with sqlite3.connect(DB) as con:
        cols = [c[1] for c in con.execute('PRAGMA table_info(est_horizon_land)')]
        for c in ('est_market_renew_land', 'est_net_load_land', 'est_gas_gen_land_raw'):
            if c not in cols:
                con.execute(f'ALTER TABLE est_horizon_land ADD COLUMN "{c}" REAL')
        con.executemany(
            'INSERT INTO est_horizon_land (timestamp, base, horizon_d, est_market_renew_land, est_net_load_land, est_gas_gen_land_raw) '
            'VALUES (?,?,?,?,?,?) ON CONFLICT(base, timestamp) DO UPDATE SET horizon_d=excluded.horizon_d, '
            'est_market_renew_land=excluded.est_market_renew_land, est_net_load_land=excluded.est_net_load_land, '
            'est_gas_gen_land_raw=excluded.est_gas_gen_land_raw', data)
        con.commit()
    print(f'\nest_horizon_land 갱신: 신재생·net_load·가스(raw) {len(data)}행')


def main():
    r = build()
    r.to_parquet(os.path.join(HERE, 'horizon_backtest_v2.parquet'))
    print(f'\n총 {len(r)}행  base {r.base.nunique()}  기간 {r.timestamp.min()} ~ {r.timestamp.max()}')
    print('=' * 74)
    print('풀체인 정직 지평별 (실측 대조) — 가스는 raw(보정 전)')
    print('=' * 74)
    print(f'{"지평":>5} | {"수요MAPE":>8} {"bias":>6} | {"신재생nMAE":>9} | {"가스MAPE":>8} {"bias":>6} | {"n":>6}')
    for n in HZ:
        g = r[r.horizon == n]
        ev = g.dropna(subset=['gen_gas_kr']); ev = ev[ev.gen_gas_kr > 0]
        dd = g.dropna(subset=['real_demand_land'])
        print(f'  D+{n:>2} | {mape(dd.real_demand_land, dd.est_demand):7.2f}% {nbias(dd.real_demand_land, dd.est_demand):+5.1f} | '
              f'{nmae(dd.renew_gen_total_kr, dd.est_renew):8.1f}% | '
              f'{mape(ev.gen_gas_kr, ev.est_gas_gen_raw):7.2f}% {nbias(ev.gen_gas_kr, ev.est_gas_gen_raw):+5.1f} | {len(ev):6}')
    write_archive(r)


if __name__ == '__main__':
    try: sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception: pass
    main()

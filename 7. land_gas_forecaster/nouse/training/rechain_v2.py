# -*- coding: utf-8 -*-
"""체인 재측정 — v2 수요(G-17)로 가스 백테스트 갱신 (가스 모델은 그대로).

목적(사용자 확정 순서 1): 개선된 수요(lgbm_land_demand_v2)가 가스에 얼마나 전파되는지,
가스 모델·구조는 손대지 않고 측정 + Phase 2 보정 재적합.  build_horizon_backtest 의 수요
단계만 v2 로 교체(지점선택·구름·cap_btmppa·offset), 신재생·가스 파이프라인은 동일.

산출: horizon_backtest_v2.parquet + 콘솔 비교(v1 vs v2, 현행/재적합 보정).  비교 후 사용자
확인 하에 gas_serving_calib.json 갱신.
"""
from __future__ import annotations
import os, sys, json, importlib.util, tempfile
import numpy as np, pandas as pd, lightgbm as lgb

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, '..', '..'))


def _imp(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m


bht = _imp('bht', os.path.join(HERE, 'build_horizon_backtest.py'))
expf = _imp('expf', os.path.join(ROOT, '5. land_demand_forecaster', 'model', 'exp_features.py'))

DMODEL = os.path.join(ROOT, '5. land_demand_forecaster', 'model', 'models', 'lgbm_land_demand_v2.txt')
DMETA = os.path.join(ROOT, '5. land_demand_forecaster', 'model', 'models', 'model_meta_v2.json')
GAS_MODEL = bht.GAS_MODEL
FEAT_V2 = expf.BASEFEAT + ['total_cloud', 'midlow_cloud', 'cap_btmppa']
DTCATS = bht.DTCATS; BLOCKS, LAGW = bht.BLOCKS, bht.LAGW
HZ = [1, 2, 3, 7, 12]
SEASON = {12: '겨울', 1: '겨울', 2: '겨울', 3: '봄', 4: '봄', 5: '봄', 6: '여름', 7: '여름', 8: '여름', 9: '가을', 10: '가을', 11: '가을'}


def predict_demand_v2(sc, d_act, model, offset, ppa, O, n):
    h0, h1 = BLOCKS[n]; H = np.arange(h0, h1 + 1)
    tg = pd.DatetimeIndex([O + pd.Timedelta(hours=int(h)) for h in H])
    dem = d_act['real_demand_land']
    wx, valid = expf.fh_weather(sc, tg)
    df = pd.DataFrame(index=tg)
    df['h'] = H
    df['lag168'] = dem.reindex(tg - pd.Timedelta(hours=168)).values
    df['lag24'] = np.where(H <= 24, dem.reindex(tg - pd.Timedelta(hours=24)).values, np.nan)
    df['rec24'] = float(dem.loc[O - pd.Timedelta(hours=23):O].mean())
    df['rec168'] = float(dem.loc[O - pd.Timedelta(hours=167):O].mean())
    for c in ('temp_c', 'solar_rad', 'wind_spd', 'total_cloud', 'midlow_cloud'):
        df[c] = wx[c].values
    df['cap_btmppa'] = expf.cap_for(tg, ppa)
    df['hour_sin'] = np.sin(2*np.pi*tg.hour/24); df['hour_cos'] = np.cos(2*np.pi*tg.hour/24)
    df['dow_sin'] = np.sin(2*np.pi*tg.dayofweek/7); df['dow_cos'] = np.cos(2*np.pi*tg.dayofweek/7)
    df['month_sin'] = np.sin(2*np.pi*tg.month/12); df['month_cos'] = np.cos(2*np.pi*tg.month/12)
    dt = d_act['day_type'].reindex(tg).values
    df['day_type'] = pd.Categorical(dt, categories=DTCATS)
    ok = valid.values & ~np.isnan(df['lag168'].values)
    pred = np.full(len(tg), np.nan)
    if ok.any():
        pred[ok] = model.predict(df.loc[ok, FEAT_V2]) + offset
    return tg, pred, dt, ok


def build():
    d_act = bht.load_actuals(); ppa = expf.load_capa()
    serve6 = bht._load_serve6(); A6 = serve6.load_assets()
    dmodel = lgb.Booster(model_file=DMODEL)
    offset = float(json.load(open(DMETA, encoding='utf-8'))['init_score'])
    gas = lgb.Booster(model_file=GAS_MODEL)
    lng = bht._lng_cap_series()
    with bht._conn() as con:
        bases = [r[0] for r in con.execute('SELECT DISTINCT base FROM forecast_horizon ORDER BY base').fetchall()]
    sc = bht.build_scratch(os.path.join(tempfile.gettempdir(), 'rechain_v2.db'))
    g = d_act['gen_gas_kr']; nlk = d_act['net_load_kr']; rgt = d_act['renew_gen_total_kr']; rdl = d_act['real_demand_land']
    rows = []
    for bi, base in enumerate(bases, 1):
        O = pd.Timestamp(base).normalize() + pd.Timedelta(hours=23)
        bht.set_scratch_forecast(sc, base)
        for n in HZ:
            try:
                tg, dem_pred, dt, ok = predict_demand_v2(sc, d_act, dmodel, offset, ppa, O, n)
                if not ok.any():
                    continue
                out6, *_ = serve6._predict_day(sc, O.normalize(), n, A6)
                mr = pd.Series(out6[serve6.OUT['mr']].values, index=pd.DatetimeIndex(out6['timestamp'])).reindex(tg).values
                m = ok & ~pd.isna(mr) & ~np.isnan(dem_pred)
                if not m.any():
                    continue
                tg2 = tg[m]; dem2 = dem_pred[m]; mr2 = mr[m].astype(float); dt2 = np.asarray(dt)[m]
                gf = pd.DataFrame(index=tg2)
                gf['real_demand_land'] = dem2; gf['renew_gen_total_kr'] = mr2
                gf['hour'] = tg2.hour; gf['dow'] = tg2.dayofweek; gf['month'] = tg2.month; gf['doy'] = tg2.dayofyear
                gf['day_type'] = pd.Categorical(dt2, categories=DTCATS)
                util = gas.predict(gf[bht.GAS_FEATS]); cap = bht._lng_cap_for(tg2, lng)
                rows.append(pd.DataFrame({
                    'base': base, 'timestamp': tg2, 'horizon': n, 'est_demand': dem2, 'est_renew': mr2,
                    'est_net_load': dem2 - mr2, 'est_gas_gen_raw': util * cap,
                    'real_demand_land': rdl.reindex(tg2).values, 'renew_gen_total_kr': rgt.reindex(tg2).values,
                    'net_load_kr': nlk.reindex(tg2).values, 'gen_gas_kr': g.reindex(tg2).values,
                    'hour': tg2.hour, 'day_type': dt2}))
            except Exception:
                continue
        if bi % 40 == 0 or bi == len(bases):
            print(f'  base {bi}/{len(bases)}  누적 {len(rows)} blocks')
    sc.close()
    return pd.concat(rows, ignore_index=True)


def mape(a, p):
    a, p = np.asarray(a, float), np.asarray(p, float); m = (a > 0) & np.isfinite(a) & np.isfinite(p)
    return float(np.mean(np.abs(a[m]-p[m])/a[m])*100) if m.any() else np.nan


def nbias(a, p):
    a, p = np.asarray(a, float), np.asarray(p, float); m = (a > 0) & np.isfinite(a) & np.isfinite(p)
    return float(np.mean((p[m]-a[m])/a[m])*100) if m.any() else np.nan


def main():
    v2 = build()
    v2.to_parquet(os.path.join(HERE, 'horizon_backtest_v2.parquet'))
    v1 = pd.read_parquet(os.path.join(HERE, 'horizon_backtest.parquet'))
    calib = json.load(open(bht.CALIB_JSON, encoding='utf-8'))
    by_h = {int(k): float(v) for k, v in calib['bias_calib_by_horizon'].items()}

    print('\n수요 입력 bias(전파원):')
    for n in HZ:
        a = v1[v1.horizon == n].dropna(subset=['real_demand_land']); b = v2[v2.horizon == n].dropna(subset=['real_demand_land'])
        print(f'  D+{n:>2}: v1 {nbias(a.real_demand_land,a.est_demand):+.2f}%  → v2 {nbias(b.real_demand_land,b.est_demand):+.2f}%')

    print('\n가스 MAPE — 현행 지평별 보정 적용 (수요만 v1→v2):')
    print('지평 |   v1(기존수요) |   v2(개선수요) | v2 재적합보정')
    new_calib = {}
    for n in HZ:
        a = v1[v1.horizon == n].dropna(subset=['gen_gas_kr']); a = a[a.gen_gas_kr > 0]
        b = v2[v2.horizon == n].dropna(subset=['gen_gas_kr']); b = b[b.gen_gas_kr > 0]
        c = by_h[n]
        nc = float(b.gen_gas_kr.sum() / b.est_gas_gen_raw.sum()); new_calib[n] = nc
        m_v1 = mape(a.gen_gas_kr, a.est_gas_gen_raw * c)
        m_v2 = mape(b.gen_gas_kr, b.est_gas_gen_raw * c)
        m_v2r = mape(b.gen_gas_kr, b.est_gas_gen_raw * nc)
        b_v2 = nbias(b.gen_gas_kr, b.est_gas_gen_raw * c)
        print(f' D+{n:>2} | {m_v1:5.2f}%        | {m_v2:5.2f}% (b{b_v2:+.1f}) | {m_v2r:5.2f}% (c={nc:.4f})')

    print('\n낮(09-15h) 가스 MAPE/bias — v2 재적합 보정:')
    v2['season'] = pd.DatetimeIndex(v2.timestamp).month.map(SEASON)
    day = v2[(v2.hour >= 9) & (v2.hour <= 15)].dropna(subset=['gen_gas_kr']); day = day[day.gen_gas_kr > 0]
    for s in ['겨울', '봄', '여름']:
        gg = day[day.season == s]
        gg = gg.assign(p=gg.est_gas_gen_raw * gg.horizon.map(new_calib))
        print(f'  {s} 낮: MAPE {mape(gg.gen_gas_kr,gg.p):.2f}%  bias {nbias(gg.gen_gas_kr,gg.p):+.2f}%')
    print('\n제안 v2 지평별 보정:', {k: round(v, 5) for k, v in new_calib.items()})


if __name__ == '__main__':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass
    main()

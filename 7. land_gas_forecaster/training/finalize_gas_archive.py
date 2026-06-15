# -*- coding: utf-8 -*-
"""est_horizon_land 의 가스 raw → 최종 가스(보정+블렌딩) 컬럼 채우기.

est_gas_gen_land_raw(booster+offset, 보정 전)에 serve_land_gas 와 동일한 보정(낮/밤×지평) + 기후값
블렌딩(w(h))을 적용해 est_gas_gen_land / est_gas_sendout_ton_land 컬럼을 UPDATE.  서빙과 동일 로직 재사용.
"""
from __future__ import annotations
import os, sys, sqlite3, importlib.util, warnings
import numpy as np, pandas as pd
warnings.filterwarnings('ignore')

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, '..', '..'))
DB = os.path.join(ROOT, '1. data_fetcher_and_db', 'data', 'input_data_land.db')
s = importlib.util.spec_from_file_location('sg', os.path.join(ROOT, '7. land_gas_forecaster', 'serve_land_gas.py'))
sg = importlib.util.module_from_spec(s); s.loader.exec_module(sg)


def main():
    day_c, night_c, conv, w_dict, clim_spec = sg._load_calib()
    lut, fb = sg.load_gas_climatology(clim_spec.get('years', '2022-2024'), clim_spec.get('window_days', 7))
    with sqlite3.connect(DB) as con:
        r = pd.read_sql('SELECT timestamp, base, horizon_d, est_gas_gen_land_raw FROM est_horizon_land '
                        'WHERE est_gas_gen_land_raw IS NOT NULL', con, parse_dates=['timestamp'])
        dt = pd.read_sql('SELECT timestamp, day_type FROM historical', con, parse_dates=['timestamp']).set_index('timestamp')['day_type']
    idx = pd.DatetimeIndex(r.timestamp)
    dtv = dt.reindex(idx).values
    dtv = np.where(pd.isna(dtv), np.where(idx.dayofweek >= 5, 'weekend', 'weekday'), dtv)
    is_day = (idx.hour.values >= 9) & (idx.hour.values <= 15)
    cal = np.array([(day_c.get(int(h), 1.0) if d else night_c.get(int(h), 1.0)) for h, d in zip(r.horizon_d, is_day)])
    gas_cal = r.est_gas_gen_land_raw.values * cal
    clim = sg._clim_vals(idx, dtv, lut, fb)
    wv = sg._blend_w(r.horizon_d.values.astype(float), w_dict)
    final = gas_cal.copy()
    use = np.isfinite(clim)
    final[use] = (1 - wv[use]) * gas_cal[use] + wv[use] * clim[use]
    ton = final * conv

    data = [(float(g), float(t), str(b), pd.Timestamp(ts).strftime('%Y-%m-%d %H:%M:%S'))
            for g, t, b, ts in zip(final, ton, r.base, r.timestamp) if np.isfinite(g)]
    with sqlite3.connect(DB) as con:
        cols = [c[1] for c in con.execute('PRAGMA table_info(est_horizon_land)')]
        for c in ('est_gas_gen_land', 'est_gas_sendout_ton_land'):
            if c not in cols:
                con.execute(f'ALTER TABLE est_horizon_land ADD COLUMN "{c}" REAL')
        con.executemany('UPDATE est_horizon_land SET est_gas_gen_land=?, est_gas_sendout_ton_land=? '
                        'WHERE base=? AND timestamp=?', data)
        con.commit()
        n = con.execute('SELECT COUNT(est_gas_gen_land) FROM est_horizon_land').fetchone()[0]
    print(f'est_horizon_land 최종 가스 채움: {len(data)}행 UPDATE, 비결측 {n}')
    print(f'  블렌딩 평균 변화: gas_cal {np.nanmean(gas_cal):.0f} → final {np.nanmean(final):.0f}MW')


if __name__ == '__main__':
    try: sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception: pass
    main()

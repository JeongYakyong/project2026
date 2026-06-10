# -*- coding: utf-8 -*-
"""BTM/PPA 신재생 과거 역추정 (G-11 옵션 c).

BTM/PPA 실측은 2024-11-23부터만 존재한다. 그 이전(2020-01~2024-10)을 역추정한다.
- PPA: PPA_gen(h) = k * ppa_scale_월간(MW용량) * 태양광이용률(h).  k는 겹침구간 보정.
- BTM: BTM_gen(h) = r * PPA_gen(h).  r은 실측 겹침구간의 BTM/PPA 비율.
- 태양광이용률(gen_solar_utilization_kr)·ppa_scale은 2020-01부터 존재 → 전 구간 추정 가능.

★ 산출물에는 반드시 source 라벨(measured/estimated)을 붙인다(역추정 표기 의무).
출력: data/land_renew_reconstructed.parquet
"""
import sqlite3
import pandas as pd
import numpy as np
from pathlib import Path

HERE = Path(__file__).resolve().parent
DB = HERE.parent / 'data' / 'input_data_land.db'
PPA_CSV = HERE / 'ppa_scale.csv'
OUT = HERE / 'data' / 'land_renew_reconstructed.parquet'

MEAS_START = pd.Timestamp('2024-11-01')   # 이 시점부터 BTM/PPA 실측 사용(2024-11-23 첫 관측)

def main():
    ppa = pd.read_csv(PPA_CSV, encoding='cp949')
    ppa['ym'] = pd.to_datetime(ppa['기간'], format='%b-%y').dt.to_period('M')
    ppa = ppa.rename(columns={'PPA 계': 'ppa_cap'})[['ym', 'ppa_cap']]

    con = sqlite3.connect(DB)
    df = pd.read_sql('''select timestamp, gen_gas_kr, real_demand_land, renew_gen_total_kr,
                        gen_solar_utilization_kr, gen_solar_ppa_kr, gen_solar_btm_kr
                        from historical''', con, parse_dates=['timestamp'])
    con.close()
    df['ym'] = df['timestamp'].dt.to_period('M')
    df = df.merge(ppa, on='ym', how='left')

    # --- 보정상수 (겹침구간: 2024-12 ~ 2026-03, 실측 안정 + ppa_scale 존재) ---
    cal = df[(df['timestamp'] >= '2024-12-01') & (df['timestamp'] < '2026-04-01')].copy()
    cal = cal.dropna(subset=['gen_solar_ppa_kr', 'gen_solar_utilization_kr', 'ppa_cap'])
    k = cal['gen_solar_ppa_kr'].sum() / (cal['ppa_cap'] * cal['gen_solar_utilization_kr']).sum()
    ov = df[df['gen_solar_ppa_kr'] > 0]
    r = ov['gen_solar_btm_kr'].sum() / ov['gen_solar_ppa_kr'].sum()
    print(f'보정상수: PPA k={k:.4f}, BTM/PPA r={r:.4f}')

    # --- 역추정 ---
    df['ppa_est'] = (k * df['ppa_cap'] * df['gen_solar_utilization_kr']).clip(lower=0)
    df['btm_est'] = r * df['ppa_est']

    meas = df['timestamp'] >= MEAS_START
    df['ppa_recon'] = np.where(meas, df['gen_solar_ppa_kr'], df['ppa_est'])
    df['btm_recon'] = np.where(meas, df['gen_solar_btm_kr'], df['btm_est'])
    df['source_btm_ppa'] = np.where(meas, 'measured', 'estimated')   # ★ 역추정 라벨

    # 결측 안전장치(이용률/scale 없는 행)
    df['ppa_recon'] = df['ppa_recon'].fillna(0)
    df['btm_recon'] = df['btm_recon'].fillna(0)

    # 복원된 진짜 신재생/수요 (BTM·PPA는 수요에 차감돼 있으므로 양쪽에 더함)
    df['true_renew'] = df['renew_gen_total_kr'] + df['ppa_recon'] + df['btm_recon']
    df['true_demand'] = df['real_demand_land'] + df['ppa_recon'] + df['btm_recon']

    out = df[['timestamp', 'gen_gas_kr', 'real_demand_land', 'renew_gen_total_kr',
              'ppa_recon', 'btm_recon', 'source_btm_ppa', 'true_renew', 'true_demand']].copy()
    out.to_parquet(OUT, index=False)
    print(f'저장: {OUT.name}  ({len(out)}행)')
    print('source 분포:', dict(out['source_btm_ppa'].value_counts()))
    print('estimated 기간:', out[out.source_btm_ppa=="estimated"].timestamp.min(),
          '~', out[out.source_btm_ppa=="estimated"].timestamp.max())
    yr = out.assign(year=out.timestamp.dt.year).groupby('year')[['ppa_recon','btm_recon','true_renew']].mean().round(0)
    print(yr.to_string())

if __name__ == '__main__':
    main()

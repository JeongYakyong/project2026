"""net_load 관점 end-to-end 비교 (보고서용).

지금까지 비교(compare_old_vs_new.py)는 PatchTST '이용률' 성능만 봤다. 이 스크립트는
**net_load 수준**에서, 우리 1단계 수요모델(new)이 공식 day-ahead 수요(da) 대비
net_load 를 얼마나 개선하는지 본다. 재생에너지 항은 둘 다 우리 PatchTST 추정으로
고정 → 순수하게 '수요 항' 효과만 격리.

정의 (input_data_jeju.db):
  real_net_load_jeju = real_demand_jeju − real_renew_gen_jeju           (진실값, historical)
  est_renew          = est_solar_gen_jeju + est_wind_gen_jeju           (우리 PatchTST, forecast)
  net_load_new       = jeju_est_demand_new − est_renew  (= est_net_load_jeju)   ← 우리 파이프라인
  net_load_da        = jeju_est_demand_da  − est_renew                          ← da 수요 기준

비교: net_load_new vs real,  net_load_da vs real  → MAE / 개선율.

산출(이 폴더): compare_net_load.csv / compare_net_load_summary.txt / compare_net_load.png
DB 저장: historical.real_net_load_jeju,  forecast.est_net_load_da_jeju  (UPSERT)
"""
from __future__ import annotations

import os
import sqlite3
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))      # 6. report only/
ROOT = os.path.normpath(os.path.join(HERE, '..'))       # 프로젝트 루트
DB = os.path.join(ROOT, '1. data_fetcher_and_db', 'data', 'input_data_jeju.db')
OUT_DIR = HERE


def _num(df):
    for c in df.columns:
        df[c] = pd.to_numeric(df[c], errors='coerce')
    return df


def build() -> pd.DataFrame:
    with sqlite3.connect(DB) as con:
        f = pd.read_sql('SELECT timestamp, jeju_est_demand_da, jeju_est_demand_new, '
                        'est_solar_gen_jeju, est_wind_gen_jeju FROM forecast',
                        con, parse_dates=['timestamp']).set_index('timestamp')
        h = pd.read_sql('SELECT timestamp, real_demand_jeju, real_renew_gen_jeju '
                        'FROM historical', con, parse_dates=['timestamp']).set_index('timestamp')
    f, h = _num(f), _num(h)
    df = f.join(h, how='inner').dropna()

    df['real_net_load'] = df['real_demand_jeju'] - df['real_renew_gen_jeju']
    df['est_renew']     = df['est_solar_gen_jeju'] + df['est_wind_gen_jeju']
    df['net_load_new']  = df['jeju_est_demand_new'] - df['est_renew']
    df['net_load_da']   = df['jeju_est_demand_da']  - df['est_renew']
    return df


def mae(a, b):
    return float(np.abs(np.asarray(a) - np.asarray(b)).mean())


def summarize(df: pd.DataFrame) -> str:
    L = []
    L.append(f'비교 구간: {df.index.min()} ~ {df.index.max()}  ({len(df)} 시간, '
             f'{df.index.normalize().nunique()} 일)')
    L.append('재생에너지 항은 양쪽 동일(우리 PatchTST) → 수요항(da vs new) 효과만 격리.')
    L.append('')
    L.append('=== net_load MAE (vs real_net_load, MW, 낮을수록 좋음) ===')
    da = mae(df['net_load_da'],  df['real_net_load'])
    nw = mae(df['net_load_new'], df['real_net_load'])
    L.append(f'  da 수요 기준 net_load : {da:8.2f} MW')
    L.append(f'  new 수요 기준 net_load: {nw:8.2f} MW   (우리 파이프라인)')
    L.append(f'  개선                  : {(da-nw):8.2f} MW  ({(da-nw)/da*100:+.1f}%)')
    L.append('')
    L.append('=== 참고: 항목별 MAE (vs 실측) ===')
    L.append(f'  수요  da  vs real_demand : {mae(df["jeju_est_demand_da"], df["real_demand_jeju"]):7.2f} MW')
    L.append(f'  수요  new vs real_demand : {mae(df["jeju_est_demand_new"], df["real_demand_jeju"]):7.2f} MW')
    L.append(f'  재생  est vs real_renew  : {mae(df["est_renew"], df["real_renew_gen_jeju"]):7.2f} MW  (양쪽 공통)')
    L.append('')
    L.append('=== 월별 net_load MAE (da → new) ===')
    g = df.assign(m=df.index.strftime('%Y-%m')).groupby('m')
    for m, x in g:
        L.append(f'  {m}: {mae(x.net_load_da, x.real_net_load):7.2f} -> '
                 f'{mae(x.net_load_new, x.real_net_load):7.2f} MW  (n={len(x)})')
    return '\n'.join(L)


def plot(df: pd.DataFrame):
    try:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
    except Exception as e:
        print('[plot] skip:', e); return
    d = df.resample('D').mean(numeric_only=True)
    fig, ax = plt.subplots(figsize=(12, 4))
    ax.plot(d.index, d['real_net_load'], 'k-',  lw=2, label='real net_load')
    ax.plot(d.index, d['net_load_da'],  'C1--', label='net_load (da demand)')
    ax.plot(d.index, d['net_load_new'], 'C0-.', label='net_load (new demand, ours)')
    ax.set_title('Net load — daily mean (real vs da-based vs new-based)')
    ax.set_ylabel('net load (MW)'); ax.legend(); ax.grid(alpha=.3)
    fig.tight_layout()
    p = os.path.join(OUT_DIR, 'compare_net_load.png')
    fig.savefig(p, dpi=110); plt.close(fig)
    print('[plot] wrote', p)


def store_db(df: pd.DataFrame):
    """real_net_load_jeju → historical, est_net_load_da_jeju → forecast (UPSERT)."""
    with sqlite3.connect(DB) as con:
        # historical.real_net_load_jeju
        hcols = [c[1] for c in con.execute('PRAGMA table_info(historical)')]
        if 'real_net_load_jeju' not in hcols:
            con.execute('ALTER TABLE historical ADD COLUMN "real_net_load_jeju" REAL')
        con.executemany(
            'INSERT INTO historical ("timestamp","real_net_load_jeju") VALUES (?,?) '
            'ON CONFLICT("timestamp") DO UPDATE SET "real_net_load_jeju"=excluded."real_net_load_jeju"',
            [(t.strftime('%Y-%m-%d %H:%M:%S'), float(v))
             for t, v in df['real_net_load'].items()])
        # forecast.est_net_load_da_jeju
        fcols = [c[1] for c in con.execute('PRAGMA table_info(forecast)')]
        if 'est_net_load_da_jeju' not in fcols:
            con.execute('ALTER TABLE forecast ADD COLUMN "est_net_load_da_jeju" REAL')
        con.executemany(
            'INSERT INTO forecast ("timestamp","est_net_load_da_jeju") VALUES (?,?) '
            'ON CONFLICT("timestamp") DO UPDATE SET "est_net_load_da_jeju"=excluded."est_net_load_da_jeju"',
            [(t.strftime('%Y-%m-%d %H:%M:%S'), round(float(v), 3))
             for t, v in df['net_load_da'].items()])
        con.commit()
    print('[DB] historical.real_net_load_jeju + forecast.est_net_load_da_jeju UPSERT')


def main(write_db=True):
    df = build()
    out = df[['real_net_load', 'net_load_da', 'net_load_new',
              'real_demand_jeju', 'jeju_est_demand_da', 'jeju_est_demand_new',
              'real_renew_gen_jeju', 'est_renew']].round(3)
    out.to_csv(os.path.join(OUT_DIR, 'compare_net_load.csv'), encoding='utf-8-sig')
    summary = summarize(df)
    with open(os.path.join(OUT_DIR, 'compare_net_load_summary.txt'), 'w', encoding='utf-8') as fp:
        fp.write(summary + '\n')
    plot(df)
    if write_db:
        store_db(df)
    print(summary)
    print('\n[OK] compare_net_load.csv / _summary.txt / .png')


if __name__ == '__main__':
    import sys
    main(write_db='--no-write' not in sys.argv)

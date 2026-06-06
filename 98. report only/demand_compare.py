"""제주 수요 예측 3자 비교 — 실제값 vs KPX 예상수요(DA) vs 우리 모델(new).

실행
====
    python "demand_compare.py"

읽기
====
    1. data_fetcher_and_db/data/input_data_jeju.db
      - historical.real_demand_jeju   (실측)
      - historical.jeju_est_demand_da (KPX day-ahead 예상수요 = baseline)
      - forecast.jeju_est_demand_new  (우리 LGBM+PatchTST 모델, 백필값)

저장 (이 스크립트 옆)
=====================
    - demand_compare_hourly.csv        시간별 병합 (timestamp, real, kpx_da, ours)
    - demand_compare_summary.csv       전체 + 월별 지표
    - demand_compare_monthly_mape.png  월별 MAPE 막대그래프 (matplotlib 있을 때만)

비교 구간 = 세 값이 모두 존재하는 겹침 구간 (실측이 있는 과거).
지표는 real_demand > 0 인 시각만 사용 (MAPE 분모 보호).
"""
import os
import sqlite3
import sys

import numpy as np
import pandas as pd

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.normpath(os.path.join(
    HERE, '..', '1. data_fetcher_and_db', 'data', 'input_data_jeju.db'))


def metrics(true, pred):
    """MAE / RMSE / MAPE(%) — NaN·0 안전."""
    t = pd.to_numeric(true, errors='coerce').to_numpy(dtype=float)
    y = pd.to_numeric(pred, errors='coerce').to_numpy(dtype=float)
    m = (~np.isnan(t)) & (~np.isnan(y)) & (t > 0)
    t, y = t[m], y[m]
    e = np.abs(t - y)
    return dict(N=int(len(t)),
                MAE=float(e.mean()),
                RMSE=float(np.sqrt(np.mean((t - y) ** 2))),
                MAPE=float((e / t).mean() * 100))


def main():
    con = sqlite3.connect(DB_PATH)
    h = pd.read_sql('SELECT timestamp, real_demand_jeju, jeju_est_demand_da '
                    'FROM historical', con, parse_dates=['timestamp'])
    f = pd.read_sql('SELECT timestamp, jeju_est_demand_new FROM forecast '
                    'WHERE jeju_est_demand_new IS NOT NULL', con,
                    parse_dates=['timestamp'])
    con.close()

    # 겹침 구간 병합 + 실측 유효행만
    m = h.merge(f, on='timestamp').dropna(subset=['real_demand_jeju'])
    m = m[m['real_demand_jeju'] > 0].sort_values('timestamp').reset_index(drop=True)
    m = m.rename(columns={'real_demand_jeju': 'real',
                          'jeju_est_demand_da': 'kpx_da',
                          'jeju_est_demand_new': 'ours'})

    print(f'DB        : {DB_PATH}')
    print(f'겹침 구간 : {m.timestamp.min().date()} ~ {m.timestamp.max().date()}  '
          f'(N={len(m)})\n')

    # ── 전체 지표 ──
    rows = []
    for name, col in [('KPX_DA', 'kpx_da'), ('OURS_new', 'ours')]:
        s = metrics(m['real'], m[col]); s['model'] = name; s['period'] = 'ALL'
        rows.append(s)
    kpx, ours = rows[0], rows[1]

    print(f'{"":10s} {"N":>5s} {"MAE":>8s} {"RMSE":>8s} {"MAPE":>8s}')
    for r in (kpx, ours):
        print(f'{r["model"]:10s} {r["N"]:5d} {r["MAE"]:8.2f} '
              f'{r["RMSE"]:8.2f} {r["MAPE"]:7.3f}%')
    print(f'{"개선":10s} {"":5s} {kpx["MAE"]-ours["MAE"]:8.2f} '
          f'{kpx["RMSE"]-ours["RMSE"]:8.2f} {kpx["MAPE"]-ours["MAPE"]:7.3f}%p\n')

    # ── 월별 지표 ──
    print('--- 월별 MAPE ---')
    m['ym'] = m['timestamp'].dt.strftime('%Y-%m')
    for ym, g in m.groupby('ym'):
        k = metrics(g['real'], g['kpx_da']); o = metrics(g['real'], g['ours'])
        rows.append({'model': 'KPX_DA',   'period': ym, **k})
        rows.append({'model': 'OURS_new', 'period': ym, **o})
        print(f'  {ym}  KPX {k["MAPE"]:6.3f}%   OURS {o["MAPE"]:6.3f}%   '
              f'(improve {k["MAPE"]-o["MAPE"]:+.3f}%p)')

    # ── 저장 ──
    hourly_csv = os.path.join(HERE, 'demand_compare_hourly.csv')
    summary_csv = os.path.join(HERE, 'demand_compare_summary.csv')
    m[['timestamp', 'real', 'kpx_da', 'ours']].to_csv(hourly_csv, index=False)
    summary = pd.DataFrame(rows)[['period', 'model', 'N', 'MAE', 'RMSE', 'MAPE']]
    summary.to_csv(summary_csv, index=False)
    print(f'\n[저장] {hourly_csv}')
    print(f'[저장] {summary_csv}')

    # ── 차트 (matplotlib 있을 때만) ──
    try:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt

        months = sorted(m['ym'].unique())
        kp = [metrics(m[m.ym == ym]['real'], m[m.ym == ym]['kpx_da'])['MAPE'] for ym in months]
        op = [metrics(m[m.ym == ym]['real'], m[m.ym == ym]['ours'])['MAPE'] for ym in months]
        x = np.arange(len(months)); w = 0.38
        fig, ax = plt.subplots(figsize=(10, 5))
        ax.bar(x - w/2, kp, w, label='KPX day-ahead', color='#b0b0b0')
        ax.bar(x + w/2, op, w, label='Ours (LGBM+PatchTST)', color='#2e7d32')
        ax.set_xticks(x); ax.set_xticklabels(months, rotation=45)
        ax.set_ylabel('MAPE (%)')
        ax.set_title('Jeju demand forecast MAPE by month  (lower = better)')
        ax.legend(); ax.grid(axis='y', alpha=0.3); fig.tight_layout()
        png = os.path.join(HERE, 'demand_compare_monthly_mape.png')
        fig.savefig(png, dpi=130)
        print(f'[저장] {png}')
    except ImportError:
        print('[건너뜀] matplotlib 미설치 — PNG 생략 (pip install matplotlib 후 재실행)')


if __name__ == '__main__':
    main()

"""구버전 vs 신버전 solar/wind 이용률 예측 비교 (보고서용 자료 생성).

세 출처를 timestamp 로 join 한다.
  - 구버전: jeju_energy(use carefully).db / forecast_data
            est_Solar_Utilization, est_Wind_Utilization  (단일지점 모델, 옛 DB)
  - 신버전: input_data_jeju.db / forecast
            est_solar_utilization_jeju, est_wind_utilization_jeju  (3지점 모델)
  - 실측  : input_data_jeju.db / historical
            real_solar_utilization_jeju, real_wind_utilization_jeju

산출(이 폴더):
  compare_old_vs_new.csv         시간별 6열(old/new/actual × solar/wind) join
  compare_old_vs_new_daily.csv   일별 MAE
  compare_summary.txt            전체/월별 MAE 요약표
  compare_solar.png, compare_wind.png   (matplotlib 있으면) 일평균 추이
"""
from __future__ import annotations

import os
import sqlite3
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))      # 6. report only/
ROOT = os.path.normpath(os.path.join(HERE, '..'))       # 프로젝트 루트
NEW_DB = os.path.join(ROOT, '1. data_fetcher_and_db', 'data', 'input_data_jeju.db')
OLD_DB = os.path.join(HERE, 'jeju_energy(use carefully).db')   # 보고서 전용 DB(이 폴더에 동거)
OUT_DIR = HERE


def _read(db, sql):
    with sqlite3.connect(db) as con:
        return pd.read_sql(sql, con, parse_dates=['timestamp'])


def build() -> pd.DataFrame:
    old = _read(OLD_DB,
                'SELECT timestamp, est_Solar_Utilization AS old_solar, '
                'est_Wind_Utilization AS old_wind FROM forecast_data')
    new = _read(NEW_DB,
                'SELECT timestamp, est_solar_utilization_jeju AS new_solar, '
                'est_wind_utilization_jeju AS new_wind FROM forecast')
    act = _read(NEW_DB,
                'SELECT timestamp, real_solar_utilization_jeju AS act_solar, '
                'real_wind_utilization_jeju AS act_wind FROM historical')

    df = old.merge(new, on='timestamp', how='inner').merge(act, on='timestamp', how='inner')
    for c in df.columns:
        if c != 'timestamp':
            df[c] = pd.to_numeric(df[c], errors='coerce')
    df = df.dropna().sort_values('timestamp').reset_index(drop=True)
    return df


def mae(a, b):
    return float(np.abs(np.asarray(a) - np.asarray(b)).mean())


def summarize(df: pd.DataFrame) -> str:
    lines = []
    lines.append(f'비교 구간: {df.timestamp.min()} ~ {df.timestamp.max()}  '
                 f'({len(df)} 시간, {df.timestamp.dt.date.nunique()} 일)')
    lines.append('')
    lines.append('=== 전체 이용률 MAE (vs 실측, 낮을수록 좋음) ===')
    lines.append('  구버전=단일지점 / 신버전=solar:west+south, wind:west+east (다지점)')
    lines.append(f'{"":8s}{"구버전":>14s}{"신버전":>14s}{"개선":>10s}')
    for name, oc, nc, ac in [('Solar', 'old_solar', 'new_solar', 'act_solar'),
                             ('Wind',  'old_wind',  'new_wind',  'act_wind')]:
        o = mae(df[oc], df[ac]); n = mae(df[nc], df[ac])
        imp = (o - n) / o * 100 if o else 0.0
        lines.append(f'{name:8s}{o:14.4f}{n:14.4f}{imp:9.1f}%')
    lines.append('')
    lines.append('=== 월별 Solar MAE / Wind MAE (구 → 신) ===')
    df = df.assign(month=df.timestamp.dt.strftime('%Y-%m'))
    for m, g in df.groupby('month'):
        lines.append(f'  {m}: solar {mae(g.old_solar, g.act_solar):.4f} -> '
                     f'{mae(g.new_solar, g.act_solar):.4f} | '
                     f'wind {mae(g.old_wind, g.act_wind):.4f} -> '
                     f'{mae(g.new_wind, g.act_wind):.4f}  (n={len(g)})')
    return '\n'.join(lines)


def daily_table(df: pd.DataFrame) -> pd.DataFrame:
    g = df.assign(date=df.timestamp.dt.date).groupby('date')
    rows = []
    for d, x in g:
        rows.append(dict(
            date=d,
            solar_old_mae=mae(x.old_solar, x.act_solar),
            solar_new_mae=mae(x.new_solar, x.act_solar),
            wind_old_mae=mae(x.old_wind, x.act_wind),
            wind_new_mae=mae(x.new_wind, x.act_wind),
        ))
    return pd.DataFrame(rows)


def plots(df: pd.DataFrame):
    try:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
    except Exception as e:
        print('[plot] skip:', e); return
    daily = df.assign(date=df.timestamp.dt.date).groupby('date').mean(numeric_only=True)
    for kind, oc, nc, ac in [('solar', 'old_solar', 'new_solar', 'act_solar'),
                             ('wind',  'old_wind',  'new_wind',  'act_wind')]:
        fig, ax = plt.subplots(figsize=(12, 4))
        ax.plot(daily.index, daily[ac], 'k-',  lw=2, label='actual')
        ax.plot(daily.index, daily[oc], 'C1--', label='old (1-station)')
        ax.plot(daily.index, daily[nc], 'C0-.', label='new (3-station)')
        ax.set_title(f'{kind.capitalize()} utilization — daily mean (old vs new vs actual)')
        ax.set_ylabel('utilization (0-1)'); ax.legend(); ax.grid(alpha=.3)
        fig.tight_layout()
        p = os.path.join(OUT_DIR, f'compare_{kind}.png')
        fig.savefig(p, dpi=110); plt.close(fig)
        print('[plot] wrote', p)


def main():
    df = build()
    df.to_csv(os.path.join(OUT_DIR, 'compare_old_vs_new.csv'),
              index=False, encoding='utf-8-sig')
    daily = daily_table(df)
    daily.to_csv(os.path.join(OUT_DIR, 'compare_old_vs_new_daily.csv'),
                 index=False, encoding='utf-8-sig')
    summary = summarize(df)
    with open(os.path.join(OUT_DIR, 'compare_summary.txt'), 'w', encoding='utf-8') as f:
        f.write(summary + '\n')
    plots(df)
    print(summary)
    print('\n[OK] wrote compare_old_vs_new.csv / _daily.csv / compare_summary.txt')


if __name__ == '__main__':
    main()

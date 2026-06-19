# -*- coding: utf-8 -*-
"""지평별 예보 기상오차 정량화 (예보오차 증강 첫 걸음, REPORT_5-B §8 다음 단계).

목적: final2 미래 기상채널(temp_c·불쾌지수 di·체감 wct·solar_rad·total_cloud)이
      서빙 시 받는 forecast_horizon 예보의 (예보−실측) 오차를 지평(D+1..D+15)·낮밤·계절별로 정량화.
      → 이 오차 분포를 학습 시 미래채널에 주입(부트스트랩)하는 증강 설계의 근거.

방법: 서빙 일관 — 모델이 소비하는 집계채널(4지점평균 기온/습도/바람·2지점평균 일사/구름)에서
      base별 시간보간(limit 3h)으로 1시간 격자 복원 후, 동일 timestamp 실측과 대조.
      di·wct 는 (예보 T,RH,W)로 재구성해 실측 (T,RH,W) 재구성본과 대조(서빙과 동일 비선형).

출력: 콘솔 표 + _eda_forecast_error.parquet(지평×시각별 오차 원천), _eda_forecast_error_summary.csv.
"""
from __future__ import annotations
import os, sys, sqlite3
import numpy as np, pandas as pd
try: sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception: pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, '..', '..'))
DB = os.path.join(ROOT, '1. data_fetcher_and_db', 'data', 'input_data_land.db')

TEMP_SEL  = ['wonju', 'seosan', 'pohang', 'yeonggwang']
SOLAR_SEL = ['seosan', 'yeonggwang']
SEASON = {12: '겨울', 1: '겨울', 2: '겨울', 3: '봄', 4: '봄', 5: '봄',
          6: '여름', 7: '여름', 8: '여름', 9: '가을', 10: '가을', 11: '가을'}


def comfort(T, RH, Wms):
    di = 0.81*T + 0.01*RH*(0.99*T - 14.3) + 46.3
    Wk = np.clip(Wms*3.6, 4.8, None)
    wct = 13.12 + 0.6215*T - 11.37*Wk**0.16 + 0.3965*T*Wk**0.16
    return di, np.where(T <= 10, wct, T)


def load_actual():
    """historical 실측을 모델 집계채널로 재구성(load_actual 미러)."""
    cols = (['timestamp'] + [f'temp_c_{s}' for s in TEMP_SEL] + [f'humidity_{s}' for s in TEMP_SEL]
            + [f'wind_spd_{s}' for s in TEMP_SEL] + [f'solar_rad_{s}' for s in SOLAR_SEL]
            + [f'total_cloud_{s}' for s in SOLAR_SEL])
    with sqlite3.connect(DB) as con:
        raw = pd.read_sql(f"SELECT {', '.join(cols)} FROM historical", con, parse_dates=['timestamp'])
    raw = raw.sort_values('timestamp')
    idx = pd.date_range(raw.timestamp.min(), raw.timestamp.max(), freq='h')
    d = raw.set_index('timestamp').reindex(idx); d.index.name = 'timestamp'
    for c in cols[1:]:
        d[c] = pd.to_numeric(d[c], errors='coerce').interpolate('time', limit=6).ffill().bfill()
    T = d[[f'temp_c_{s}' for s in TEMP_SEL]].mean(1)
    RH = d[[f'humidity_{s}' for s in TEMP_SEL]].mean(1)
    W = d[[f'wind_spd_{s}' for s in TEMP_SEL]].mean(1)
    out = pd.DataFrame(index=d.index)
    out['temp_c'] = T; out['di'], out['wct'] = comfort(T, RH, W)
    out['rh'] = RH; out['wind'] = W
    out['solar_rad'] = d[[f'solar_rad_{s}' for s in SOLAR_SEL]].mean(1)
    out['total_cloud'] = d[[f'total_cloud_{s}' for s in SOLAR_SEL]].mean(1)
    return out


def load_forecast():
    """forecast_horizon 을 base별 1시간 보간(limit 3h) 후 집계채널·horizon_d 부여."""
    cols = (['timestamp', 'base', 'horizon_d']
            + [f'temp_{s}' for s in TEMP_SEL] + [f'reh_{s}' for s in TEMP_SEL]
            + [f'wind_spd_10m_{s}' for s in TEMP_SEL]
            + [f'radiation_{s}' for s in SOLAR_SEL] + [f'total_cloud_{s}' for s in SOLAR_SEL])
    sel = ', '.join(f'"{c}"' for c in cols)
    with sqlite3.connect(DB) as con:
        fc = pd.read_sql(f"SELECT {sel} FROM forecast_horizon ORDER BY base, timestamp",
                         con, parse_dates=['timestamp', 'base'])
    num = [c for c in cols if c not in ('timestamp', 'base', 'horizon_d')]
    fc[num] = fc[num].apply(pd.to_numeric, errors='coerce')
    blocks = []
    for base, g in fc.groupby('base'):
        g = g.set_index('timestamp').sort_index()
        hidx = pd.date_range(g.index.min(), g.index.max(), freq='h')
        gi = g[num].reindex(hidx).interpolate('time', limit=3, limit_area='inside')
        gi.index.name = 'timestamp'; gi['base'] = base
        gi['horizon_d'] = ((gi.index.normalize() - base.normalize()).days).astype('Int64')
        blocks.append(gi.reset_index())
    fc = pd.concat(blocks, ignore_index=True)
    T = fc[[f'temp_{s}' for s in TEMP_SEL]].mean(1)
    RH = fc[[f'reh_{s}' for s in TEMP_SEL]].mean(1)
    W = fc[[f'wind_spd_10m_{s}' for s in TEMP_SEL]].mean(1)
    out = pd.DataFrame({'timestamp': fc['timestamp'], 'base': fc['base'], 'horizon_d': fc['horizon_d']})
    out['temp_c'] = T.values; out['di'], out['wct'] = comfort(T.values, RH.values, W.values)
    out['rh'] = RH.values; out['wind'] = W.values
    out['solar_rad'] = fc[[f'radiation_{s}' for s in SOLAR_SEL]].mean(1).values
    out['total_cloud'] = fc[[f'total_cloud_{s}' for s in SOLAR_SEL]].mean(1).values
    return out


CHANNELS = ['temp_c', 'di', 'wct', 'rh', 'wind', 'solar_rad', 'total_cloud']


def main():
    act = load_actual()
    fc = load_forecast()
    fc = fc[(fc.horizon_d >= 1) & (fc.horizon_d <= 15)].copy()
    # 실측 결합 → 오차(예보−실측)
    a = act.reindex(fc.timestamp.values)
    err = pd.DataFrame({'timestamp': fc.timestamp.values, 'horizon_d': fc.horizon_d.values.astype(int)})
    ts = pd.to_datetime(fc.timestamp.values)
    err['hour'] = ts.hour; err['daypart'] = np.where((err.hour >= 9) & (err.hour <= 15), '주간', '야간')
    err['season'] = pd.Series(ts.month, index=err.index).map(SEASON)
    for c in CHANNELS:
        err[f'{c}_fc'] = fc[c].values
        err[f'{c}_act'] = a[c].values
        err[f'{c}_e'] = fc[c].values - a[c].values
    err = err.dropna(subset=[f'{c}_e' for c in CHANNELS], how='all')
    err.to_parquet(os.path.join(HERE, '_eda_forecast_error.parquet'), index=False)

    # ── 요약표: 지평별 bias / RMSE (전체) ──
    print('forecast_horizon base 수:', fc.base.nunique(),
          '| 평가행:', len(err), '| 기간:', ts.min(), '~', ts.max())
    rows = []
    print('\n======== 지평별 예보오차 (예보−실측) : bias / RMSE ========')
    hdr = '  D+   ' + ''.join(f'{c:>22}' for c in CHANNELS)
    print(hdr); print('  ' + '-'*(len(hdr)-2))
    for n in range(1, 16):
        gh = err[err.horizon_d == n]
        cells = []
        for c in CHANNELS:
            e = gh[f'{c}_e'].dropna()
            bias = e.mean(); rmse = np.sqrt((e**2).mean())
            cells.append(f'{bias:+7.2f}/{rmse:6.2f}')
            rows.append(dict(horizon=n, channel=c, scope='전체', bias=bias, rmse=rmse,
                             mae=e.abs().mean(), std=e.std(), n=len(e)))
        print(f'  D+{n:<2}  ' + ''.join(f'{x:>22}' for x in cells))
    print('  (각 칸 = bias / RMSE)')

    # ── 낮 한정 solar/temp (덕커브·여름 핵심) ──
    print('\n======== 주간(09-15h) 한정 : solar_rad / temp_c / di bias·RMSE ========')
    for n in range(1, 16):
        gh = err[(err.horizon_d == n) & (err.daypart == '주간')]
        c_cells = []
        for c in ['temp_c', 'di', 'solar_rad', 'total_cloud']:
            e = gh[f'{c}_e'].dropna()
            c_cells.append(f'{c}={e.mean():+6.2f}/{np.sqrt((e**2).mean()):5.2f}')
            rows.append(dict(horizon=n, channel=c, scope='주간', bias=e.mean(),
                             rmse=np.sqrt((e**2).mean()), mae=e.abs().mean(), std=e.std(), n=len(e)))
        print(f'  D+{n:<2}  ' + '  '.join(c_cells))

    # ── 계절×temp_c bias (계절 편향 확인) ──
    print('\n======== 계절별 temp_c bias (지평 평균) ========')
    for s in ['겨울', '봄', '여름', '가을']:
        gs = err[err.season == s]
        e = gs['temp_c_e'].dropna()
        di = gs['di_e'].dropna(); so = gs['solar_rad_e'].dropna()
        print(f'  {s}: temp_c {e.mean():+.2f}±{e.std():.2f} | di {di.mean():+.2f} | solar {so.mean():+.2f} (n={len(e)})')

    pd.DataFrame(rows).to_csv(os.path.join(HERE, '_eda_forecast_error_summary.csv'),
                             index=False, encoding='utf-8-sig')
    print('\n저장: _eda_forecast_error.parquet (원천), _eda_forecast_error_summary.csv (요약)')


if __name__ == '__main__':
    main()

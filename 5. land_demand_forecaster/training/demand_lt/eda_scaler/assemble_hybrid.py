# -*- coding: utf-8 -*-
"""최종 하이브리드 조립 + 검증.
구성(사용자 확정): D1-6 = ft(파인튜닝) 무보정 / D7-15 = 기존 weights + calib.
방법: weights/ 를 weights_hybrid/ 로 복사 → D1-6 .pth 를 weights_ft 것으로 교체 →
      calib_lt.json 에서 초단·단(=D1-6) 셀 제거(단기 무보정). 기존 weights/(정본)는 불변.
검증: weights_hybrid 로 forecast_horizon 재서빙(calibrated=True) → Hybrid A 수치 재현 확인.
"""
from __future__ import annotations
import os, sys, json, shutil, sqlite3
try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass
import numpy as np, pandas as pd
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import model_lt as M  # noqa

DEMAND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = r'C:\Users\bjkim\Desktop\project2026\1. data_fetcher_and_db\data\input_data_land.db'
W_ORIG = os.path.join(DEMAND, 'weights')
W_FT = os.path.join(DEMAND, 'weights_ft')
W_HYB = os.path.join(DEMAND, 'weights_hybrid')
FT_HORIZONS = range(1, 7)               # D1-6 = ft
DROP_GROUPS = {'초단', '단'}             # D1-6 보정 제거


def assemble():
    if os.path.exists(W_HYB):
        shutil.rmtree(W_HYB)
    shutil.copytree(W_ORIG, W_HYB)       # 기존 전체 복사(가중치·scaler·meta·calib)
    for n in FT_HORIZONS:                 # D1-6 가중치만 ft 로 교체
        shutil.copy(os.path.join(W_FT, f'best_lt_D{n}.pth'), os.path.join(W_HYB, f'best_lt_D{n}.pth'))
    # calib: 초단·단 셀 제거 → D1-6 은 .get()→1.0 (무보정)
    cpath = os.path.join(W_HYB, 'calib_lt.json')
    with open(cpath, encoding='utf-8') as f:
        calib = json.load(f)
    kept = {k: v for k, v in calib.items() if k.rsplit('_', 1)[-1] not in DROP_GROUPS}
    with open(cpath, 'w', encoding='utf-8') as f:
        json.dump(kept, f, ensure_ascii=False, indent=1)
    print(f'조립 완료 → weights_hybrid/')
    print(f'  D1-6 가중치=ft 교체 / D7-15=기존')
    print(f'  calib 셀 {len(calib)} → {len(kept)} (초단·단 {len(calib)-len(kept)}개 제거=단기 무보정)')


def mape(a, p):
    a, p = np.asarray(a, float), np.asarray(p, float); k = (a > 0) & np.isfinite(p)
    return np.mean(np.abs(a[k] - p[k]) / a[k]) * 100
def bias(a, p):
    a, p = np.asarray(a, float), np.asarray(p, float); k = (a > 0) & np.isfinite(p)
    return np.mean((p[k] - a[k]) / a[k]) * 100


def verify():
    print('\n검증: weights_hybrid 재서빙(calibrated=True)…')
    A = M.load_serve(DB, W_HYB)
    rows = []
    with sqlite3.connect(DB) as con:
        bases = [b for (b,) in con.execute('SELECT DISTINCT base FROM forecast_horizon ORDER BY base')]
        for i, base in enumerate(bases):
            for n in sorted(A['models']):
                res = M.predict_horizon(A, con, base, n, calibrated=True)   # production 모드
                if res is None:
                    continue
                tg, pred = res
                for ts, v in zip(tg, pred):
                    if np.isfinite(v):
                        rows.append((ts, n, float(v)))
            if (i + 1) % 60 == 0:
                print(f'   {i+1}/{len(bases)}')
    hyb = pd.DataFrame(rows, columns=['timestamp', 'horizon_d', 'pred'])
    with sqlite3.connect(DB) as con:
        hist = pd.read_sql('SELECT timestamp, real_demand_land AS actual, solar_rad_seosan, solar_rad_yeonggwang FROM historical',
                           con, parse_dates=['timestamp'])
    hist['solar_rad'] = hist[['solar_rad_seosan', 'solar_rad_yeonggwang']].mean(1)
    df = hyb.merge(hist[['timestamp', 'actual', 'solar_rad']], on='timestamp', how='inner')
    df = df[df.actual > 0].copy(); df['hour'] = df.timestamp.dt.hour
    day = df[(df.hour >= 9) & (df.hour <= 15)].copy()
    day['sq'] = pd.qcut(day.solar_rad, 4, labels=['Q1', 'Q2', 'Q3', 'Q4'])
    b = day.groupby('sq', observed=True).apply(lambda x: bias(x.actual, x.pred))
    print(f'\n=== 조립본(weights_hybrid) 봉인 test 재현 ===')
    print(f'  전체 MAPE {mape(df.actual, df.pred):.2f} | 전체 bias {bias(df.actual, df.pred):+.2f} '
          f'| 낮 bias {bias(day.actual, day.pred):+.2f} | 낮 spread {b["Q4"]-b["Q1"]:+.1f}')
    print(f'  (목표 Hybrid A: MAPE 3.95 · 낮 spread +8.9 — 일치하면 배선 정상)')


if __name__ == '__main__':
    assemble()
    verify()

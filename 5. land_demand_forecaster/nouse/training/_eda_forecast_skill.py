# -*- coding: utf-8 -*-
"""지평별 예보 정보력(skill) — 채널별 예보가 '날마다의 변동'을 잡아내는가.

RMSE 는 일사처럼 절대값 작은 채널을 과소평가한다. 진짜 질문은 "예보가 climatology 대비
day-to-day 변동(이상치)을 맞추는가". → (월×시각) 기후평균을 제거한 이상치(anomaly)로:
  - ACC(anomaly correlation): corr(예보이상치, 실측이상치). 1=완벽, 0=기후값과 동급(=노이즈).
  - 설명분산: 1 - Var(예보−실측 이상치)/Var(실측 이상치). 음수면 기후값보다 못함.
사용자 도메인 주장("D+10이면 온도·습도만 신호, 나머지 노이즈") 검증용.
입력: _eda_forecast_error.parquet (이미 생성). 출력: 콘솔 표 + _eda_forecast_skill.csv.
"""
from __future__ import annotations
import os, sys
import numpy as np, pandas as pd
try: sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception: pass
HERE = os.path.dirname(os.path.abspath(__file__))
CHANNELS = ['temp_c', 'rh', 'wind', 'solar_rad', 'total_cloud', 'di', 'wct']


def main():
    df = pd.read_parquet(os.path.join(HERE, '_eda_forecast_error.parquet'))
    ts = pd.to_datetime(df.timestamp)
    df['month'] = ts.dt.month; df['hour'] = ts.dt.hour
    # (월×시각) 기후평균을 실측에서 추정 → 예보·실측 모두에서 제거해 이상치 산출
    rows = []
    print('======== 지평별 예보 정보력 (ACC = 이상치 상관, 1=완벽 / 0=기후값=노이즈) ========')
    print('  D+   ' + ''.join(f'{c:>12}' for c in CHANNELS))
    print('  ' + '-'*(5+12*len(CHANNELS)))
    for n in range(1, 16):
        g = df[df.horizon_d == n]
        cells = []
        for c in CHANNELS:
            sub = g[[f'{c}_fc', f'{c}_act', 'month', 'hour']].dropna()
            if len(sub) < 50:
                cells.append('   -   '); continue
            clim = sub.groupby(['month', 'hour'])[f'{c}_act'].transform('mean')
            fa = sub[f'{c}_fc'] - clim     # 예보 이상치
            aa = sub[f'{c}_act'] - clim    # 실측 이상치
            if aa.std() < 1e-9:
                acc = np.nan
            else:
                acc = np.corrcoef(fa, aa)[0, 1]
            ev = 1 - ((fa - aa).var() / aa.var()) if aa.var() > 1e-9 else np.nan  # 설명분산
            cells.append(f'{acc:6.2f}')
            rows.append(dict(horizon=n, channel=c, ACC=acc, expl_var=ev,
                             anom_std_act=aa.std(), n=len(sub)))
        print(f'  D+{n:<2} ' + ''.join(f'{x:>12}' for x in cells))

    # 일사·구름은 주간 한정 ACC 가 본질 (밤 0 제외)
    print('\n======== 주간(09-15h) 한정 ACC : solar_rad / total_cloud / temp_c / rh ========')
    dfd = df[(df.hour >= 9) & (df.hour <= 15)]
    print('  D+   ' + ''.join(f'{c:>12}' for c in ['temp_c', 'rh', 'solar_rad', 'total_cloud']))
    for n in range(1, 16):
        g = dfd[dfd.horizon_d == n]
        cells = []
        for c in ['temp_c', 'rh', 'solar_rad', 'total_cloud']:
            sub = g[[f'{c}_fc', f'{c}_act', 'month', 'hour']].dropna()
            if len(sub) < 50:
                cells.append('   -   '); continue
            clim = sub.groupby(['month', 'hour'])[f'{c}_act'].transform('mean')
            fa = sub[f'{c}_fc'] - clim; aa = sub[f'{c}_act'] - clim
            acc = np.corrcoef(fa, aa)[0, 1] if aa.std() > 1e-9 else np.nan
            cells.append(f'{acc:6.2f}')
            rows.append(dict(horizon=n, channel=c+'_day', ACC=acc, expl_var=np.nan,
                             anom_std_act=aa.std(), n=len(sub)))
        print(f'  D+{n:<2} ' + ''.join(f'{x:>12}' for x in cells))

    pd.DataFrame(rows).to_csv(os.path.join(HERE, '_eda_forecast_skill.csv'), index=False, encoding='utf-8-sig')
    print('\n저장: _eda_forecast_skill.csv')


if __name__ == '__main__':
    main()

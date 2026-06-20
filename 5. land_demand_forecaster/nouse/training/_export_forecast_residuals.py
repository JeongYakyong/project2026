# -*- coding: utf-8 -*-
"""지평별 예보오차 잔차 풀 export — 증강 학습(Colab) 업로드용.

_eda_forecast_error.parquet 에서 지평(D+1..D+15)별 '하루(00~23시) 24h 잔차 블록'을 모은다.
블록 = (예보−실측) 잔차의 24×5 행렬(채널 = temp_c·rh·wind·solar_rad·total_cloud, raw 단위).
하루 단위로 묶어 **일중 시간구조(밤 일사=0)·일내 시간상관(추운 날은 하루종일 추움)·채널상관**을 보존.
학습 시 모델 D+n 은 자기 지평 풀에서 블록을 뽑아 실측 미래기상에 더한다(→ di/wct 재계산은 학습코드).

출력: forecast_residuals.npz  (res_D1..res_D15 = (n_blocks,24,5) + 메타). Colab 업로드.
"""
from __future__ import annotations
import os, sys
import numpy as np, pandas as pd
try: sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception: pass
HERE = os.path.dirname(os.path.abspath(__file__))
INJECT = ['temp_c', 'rh', 'wind', 'solar_rad', 'total_cloud']   # 주입 raw 채널(고정 순서)


def main():
    df = pd.read_parquet(os.path.join(HERE, '_eda_forecast_error.parquet'))
    df = df.copy()
    ts = pd.to_datetime(df.timestamp)
    df['date'] = ts.dt.normalize(); df['hour'] = ts.dt.hour
    ecols = [f'{c}_e' for c in INJECT]

    out = {}; counts = {}
    for n in range(1, 16):
        gh = df[df.horizon_d == n]
        blocks = []
        for _, g in gh.groupby('date'):
            g = g.sort_values('hour')
            if len(g) != 24 or g.hour.tolist() != list(range(24)):
                continue
            mat = g[ecols].to_numpy(dtype=np.float32)   # (24,5)
            if not np.isfinite(mat).all():
                continue
            blocks.append(mat)
        arr = np.stack(blocks) if blocks else np.zeros((0, 24, len(INJECT)), np.float32)
        out[f'res_D{n}'] = arr; counts[n] = len(arr)

    np.savez_compressed(os.path.join(HERE, 'forecast_residuals.npz'),
                        channels=np.array(INJECT), **out)

    print('======== 지평별 잔차 블록(하루 24h) 수 ========')
    for n in range(1, 16):
        print(f'  D+{n:<2}: {counts[n]:3d} blocks')
    print('\n채널 순서:', INJECT)
    print('저장: forecast_residuals.npz  → Colab 업로드(증강 학습 입력)')


if __name__ == '__main__':
    main()

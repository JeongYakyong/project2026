# -*- coding: utf-8 -*-
"""야간 중심 3자 비교 — LGBM vs final2(증강 전) vs aug(증강). D+1~7.
증강 효과 isolate: final2 와 aug 는 구조·피처·HP 동일, 차이는 '예보오차 증강'뿐.
동일 표본(base,timestamp,horizon inner-join)에서 야간(09~15 외) MAPE·bias 비교.
입력: _ab_final2_merged.parquet + _ab_aug_merged.parquet.
"""
from __future__ import annotations
import os, sys
import numpy as np, pandas as pd
try: sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception: pass
HERE = os.path.dirname(os.path.abspath(__file__))


def mape(a, p):
    a, p = np.asarray(a, float), np.asarray(p, float); k = (a > 0) & np.isfinite(a) & np.isfinite(p)
    return float(np.mean(np.abs(a[k]-p[k])/a[k])*100) if k.any() else np.nan
def nbias(a, p):
    a, p = np.asarray(a, float), np.asarray(p, float); k = (a > 0) & np.isfinite(a) & np.isfinite(p)
    return float(np.mean((p[k]-a[k])/a[k])*100) if k.any() else np.nan


def main():
    f2 = pd.read_parquet(os.path.join(HERE, '_ab_final2_merged.parquet'))
    ag = pd.read_parquet(os.path.join(HERE, '_ab_aug_merged.parquet'))
    f2 = f2[f2.horizon <= 7].rename(columns={'pred': 'pred_final2'})
    ag = ag.rename(columns={'pred': 'pred_aug'})
    g = f2[['base', 'timestamp', 'horizon', 'actual', 'pred_lgbm', 'pred_final2', 'daypart', 'season']].merge(
        ag[['base', 'timestamp', 'horizon', 'pred_aug']], on=['base', 'timestamp', 'horizon'], how='inner')
    g = g[g.actual > 0]
    night = g[g.daypart == '야간']
    print(f'동일표본 n={len(g)} (야간 {len(night)}) | 지평 D+1~7\n')

    # ── 야간 지평별 MAPE (3자) ──
    print('======== 야간(09~15h 외) MAPE : LGBM / final2 / aug ========')
    print(f"  {'지평':<5}{'LGBM':>9}{'final2':>9}{'aug':>9}   {'aug−LGBM':>10}{'aug−final2':>11}")
    for n in range(1, 8):
        gn = night[night.horizon == n]
        l, f, a = mape(gn.actual, gn.pred_lgbm), mape(gn.actual, gn.pred_final2), mape(gn.actual, gn.pred_aug)
        print(f"  D+{n:<3}{l:9.2f}{f:9.2f}{a:9.2f}   {a-l:+10.2f}{a-f:+11.2f}")
    gn = night
    l, f, a = mape(gn.actual, gn.pred_lgbm), mape(gn.actual, gn.pred_final2), mape(gn.actual, gn.pred_aug)
    print(f"  {'전체':<4}{l:9.2f}{f:9.2f}{a:9.2f}   {a-l:+10.2f}{a-f:+11.2f}")

    # ── 야간 bias (과/소예측) ──
    print('\n======== 야간 bias(%) : LGBM / final2 / aug (양=과대) ========')
    print(f"  {'지평':<5}{'LGBM':>9}{'final2':>9}{'aug':>9}")
    for n in range(1, 8):
        gn = night[night.horizon == n]
        print(f"  D+{n:<3}{nbias(gn.actual,gn.pred_lgbm):9.2f}{nbias(gn.actual,gn.pred_final2):9.2f}{nbias(gn.actual,gn.pred_aug):9.2f}")

    # ── 야간 계절×지평 aug vs final2 (증강 순효과) ──
    print('\n======== 야간 계절별 MAPE (final2→aug, Δ) ========')
    print(f"  {'지평':<5}" + ''.join(f'{s:>16}' for s in ['겨울', '봄', '여름']))
    for n in range(1, 8):
        cells = []
        for s in ['겨울', '봄', '여름']:
            gs = night[(night.horizon == n) & (night.season == s)]
            if gs.empty: cells.append('       -        '); continue
            f, a = mape(gs.actual, gs.pred_final2), mape(gs.actual, gs.pred_aug)
            cells.append(f'{f:5.2f}→{a:5.2f}({a-f:+.1f})')
        print(f"  D+{n:<3}" + ''.join(f'{c:>16}' for c in cells))

    print('\n해석 기준: aug−final2 가 음수면 증강이 야간을 개선, 양수면 악화.')


if __name__ == '__main__':
    main()

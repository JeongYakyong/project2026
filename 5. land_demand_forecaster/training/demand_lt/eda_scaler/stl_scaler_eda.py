# -*- coding: utf-8 -*-
"""v4 입력 피처(temp_c·humidity·solar_rad) STL 분해 + 이상치 진단.

목적: 현재 RobustScaler 를 MinMaxScaler 로 바꿔도 되는지 판단.
  - MinMax 는 min/max 에 끌려가므로 '극단 이상치'가 있으면 본문이 좁은 구간에 눌린다.
  - STL(여기선 MSTL: 일24h·주168h) 로 주기/추세를 벗겨낸 잔차(remainder)에서 이상치를 본다.
  - 추가로 min/max 가 분포 본문에서 몇 IQR 떨어져 있는지(=MinMax 취약성)를 직접 계량.

스케일러는 train(<2025-01-01)에서 fit → 진단도 같은 train 창 기준(전체 분포도 함께 출력).
산출: eda_scaler/ 에 MSTL 그림 3장 + 이상치/스케일러 요약 표(CSV·MD).
"""
from __future__ import annotations
import os, sys
try:
    sys.stdout.reconfigure(encoding='utf-8'); sys.stderr.reconfigure(encoding='utf-8')
except Exception:
    pass
import numpy as np, pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from statsmodels.tsa.seasonal import MSTL
from sklearn.preprocessing import RobustScaler, MinMaxScaler

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import model_lt as M  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
CSV = os.path.join(os.path.dirname(HERE), 'land_demand_train.csv')
TRAIN_END = '2025-01-01'
EXOG = M.EXOG  # ['temp_c','humidity','solar_rad']
LABEL = {'temp_c': '기온(4지점 평균, °C)', 'humidity': '습도(4지점 평균, %)',
         'solar_rad': '일사(2지점 평균, MJ/m²·h)'}

plt.rcParams['font.family'] = 'Malgun Gothic'
plt.rcParams['axes.unicode_minus'] = False


def mad_z(x):
    """Iglewicz-Hoaglin 수정 z-score (MAD 기반, 이상치에 강함)."""
    x = np.asarray(x, float)
    med = np.median(x)
    mad = np.median(np.abs(x - med))
    if mad == 0:
        mad = 1e-9
    return 0.6745 * (x - med) / mad


def main():
    feat = M.build_features(pd.read_csv(CSV))
    full = feat[EXOG].copy()
    tr = full.loc[full.index < TRAIN_END]
    print(f'전체 {len(full)}행 ({full.index.min()} ~ {full.index.max()})')
    print(f'train(<{TRAIN_END}) {len(tr)}행 — 스케일러 fit 구간\n')

    rows = []
    for col in EXOG:
        s_full = full[col]
        s_tr = tr[col]
        # ── MSTL 분해 (일·주 주기). 연주기는 추세(LOESS)가 흡수 ──
        res = MSTL(s_full, periods=(24, 168)).fit()
        remainder = res.resid
        rem_tr = remainder.loc[remainder.index < TRAIN_END]

        # 잔차 이상치(전체/ train)
        z_full = mad_z(remainder.values)
        z_tr = mad_z(rem_tr.values)
        out35_full = int(np.sum(np.abs(z_full) > 3.5))
        out35_tr = int(np.sum(np.abs(z_tr) > 3.5))
        out5_tr = int(np.sum(np.abs(z_tr) > 5.0))

        # ── 원시값 분포: MinMax 취약성 = min/max 가 IQR 본문에서 얼마나 떨어졌나 ──
        q1, med, q3 = np.percentile(s_tr, [25, 50, 75])
        iqr = q3 - q1
        lo, hi = s_tr.min(), s_tr.max()
        p01, p99 = np.percentile(s_tr, [1, 99])
        # min/max 가 Q1/Q3 에서 몇 IQR 떨어졌나 (Tukey 1.5 IQR 가 통상 이상치 경계)
        lo_iqr = (q1 - lo) / iqr if iqr else np.nan
        hi_iqr = (hi - q3) / iqr if iqr else np.nan
        # MinMax 로 변환했을 때 본문(1~99%)이 차지하는 비율 — 작을수록 이상치에 눌림
        span = hi - lo
        body_frac = (p99 - p01) / span if span else np.nan

        rows.append(dict(feature=col,
                         n_train=len(s_tr),
                         min=round(lo, 2), p1=round(p01, 2), median=round(med, 2),
                         p99=round(p99, 2), max=round(hi, 2), IQR=round(iqr, 2),
                         min_below_Q1_in_IQR=round(lo_iqr, 2),
                         max_above_Q3_in_IQR=round(hi_iqr, 2),
                         body_1_99_frac_of_range=round(body_frac, 3),
                         resid_out_z35_train=out35_tr,
                         resid_out_z35_train_pct=round(100 * out35_tr / len(rem_tr), 3),
                         resid_out_z5_train=out5_tr,
                         resid_out_z35_full=out35_full))

        # ── 그림: MSTL 4단 + 잔차 이상치 표시 ──
        fig, ax = plt.subplots(4, 1, figsize=(11, 9), sharex=True)
        ax[0].plot(s_full.index, s_full.values, lw=0.4, color='#1f4e79'); ax[0].set_ylabel('원본')
        ax[0].set_title(f'MSTL 분해 — {LABEL[col]}  (일24h·주168h)')
        ax[1].plot(res.trend.index, res.trend.values, lw=0.7, color='#c00000'); ax[1].set_ylabel('추세\n(연주기 포함)')
        seas = res.seasonal.iloc[:, 0] if hasattr(res.seasonal, 'iloc') else res.seasonal
        ax[2].plot(seas.index[:24 * 14], seas.values[:24 * 14], lw=0.6, color='#548235')
        ax[2].set_ylabel('일주기\n(첫 2주)')
        ax[3].plot(remainder.index, remainder.values, lw=0.3, color='#7f7f7f')
        mask = np.abs(z_full) > 3.5
        ax[3].scatter(remainder.index[mask], remainder.values[mask], s=6, color='#e8000b', zorder=3,
                      label=f'|z|>3.5 ({out35_full}개)')
        ax[3].axhline(0, color='k', lw=0.4); ax[3].set_ylabel('잔차'); ax[3].legend(loc='upper right', fontsize=8)
        for a in ax:
            a.axvline(pd.Timestamp(TRAIN_END), color='navy', ls='--', lw=0.8)
        fig.tight_layout()
        out_png = os.path.join(HERE, f'mstl_{col}.png')
        fig.savefig(out_png, dpi=110); plt.close(fig)
        print(f'  [{col}] 그림 저장: {out_png}')

    # ── 요약 표 ──
    summ = pd.DataFrame(rows)
    summ.to_csv(os.path.join(HERE, 'scaler_outlier_summary.csv'), index=False, encoding='utf-8-sig')

    # ── RobustScaler vs MinMaxScaler 변환 분포 비교(본문 압축 정도) ──
    rb = RobustScaler().fit(tr[EXOG]); mm = MinMaxScaler().fit(tr[EXOG])
    rb_tr = pd.DataFrame(rb.transform(tr[EXOG]), columns=EXOG)
    mm_tr = pd.DataFrame(mm.transform(tr[EXOG]), columns=EXOG)
    cmp_rows = []
    for col in EXOG:
        # MinMax 변환 후 본문(1~99%)이 [0,1] 중 얼마나 차지하나 (다시 확인)
        mlo, mhi = np.percentile(mm_tr[col], [1, 99])
        cmp_rows.append(dict(feature=col,
                             robust_min=round(rb_tr[col].min(), 2), robust_max=round(rb_tr[col].max(), 2),
                             minmax_p1=round(mlo, 3), minmax_p99=round(mhi, 3),
                             minmax_body_width=round(mhi - mlo, 3)))
    cmp = pd.DataFrame(cmp_rows)
    cmp.to_csv(os.path.join(HERE, 'scaler_transform_compare.csv'), index=False, encoding='utf-8-sig')

    print('\n=== 이상치/분포 요약 (train fit 구간) ===')
    print(summ.to_string(index=False))
    print('\n=== 스케일러 변환 분포 비교 ===')
    print(cmp.to_string(index=False))


if __name__ == '__main__':
    main()

"""4단계 SMP(A안) 보고서 비교 — DB 결과로 표·그림 생성.

A안 = DA 가격선 + 음수경보. est_smp_jeju == smp_jeju_da(가격선) 이므로
가격선 정확도(=DA를 RT 예측치로 썼을 때 MAE)와 음수경보 성능을 보고한다.

생성물(이 폴더):
  smp_priceline_mae.csv      가격선 MAE — 전체/계절/시간대
  smp_alarm_performance.txt  음수경보 — ROC/PR-AUC, recall/precision/치명, vs DA탐지
  smp_product_april.png      제품 그림(2026-04)
  smp_compare_summary.txt    요약
대상 구간: forecast(예보=서빙조건) ∩ smp_jeju_rt 보유.
"""
from __future__ import annotations

import os
import sqlite3
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib import rc
from sklearn.metrics import roc_auc_score, average_precision_score

rc('font', family=['Malgun Gothic', 'sans-serif'])
plt.rcParams['axes.unicode_minus'] = False

HERE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.normpath(os.path.join(
    HERE, '..', '1. data_fetcher_and_db', 'data', 'input_data_jeju.db'))
SEASON = {12: '겨울', 1: '겨울', 2: '겨울', 3: '봄', 4: '봄', 5: '봄',
          6: '여름', 7: '여름', 8: '여름', 9: '가을', 10: '가을', 11: '가을'}


def load():
    con = sqlite3.connect(DB_PATH)
    f = pd.read_sql("SELECT timestamp, smp_jeju_da, est_smp_jeju, smp_neg_proba_jeju, "
                    "smp_danger_jeju FROM forecast WHERE est_smp_jeju IS NOT NULL",
                    con, parse_dates=['timestamp']).set_index('timestamp')
    h = pd.read_sql("SELECT timestamp, smp_jeju_rt FROM historical WHERE smp_jeju_rt IS NOT NULL",
                    con, parse_dates=['timestamp']).set_index('timestamp')
    con.close()
    d = f.join(h, how='inner')
    d['season'] = d.index.month.map(SEASON)
    return d


def priceline_mae(d):
    rt, est = d['smp_jeju_rt'], d['est_smp_jeju']
    ae = (rt - est).abs()
    rows = [('전체', len(d), round(ae.mean(), 2))]
    for s in ['봄', '여름', '가을', '겨울']:
        m = d['season'] == s
        if m.sum():
            rows.append((s, int(m.sum()), round(ae[m].mean(), 2)))
    tbl = pd.DataFrame(rows, columns=['구간', 'n', 'MAE'])
    by_hour = ae.groupby(d.index.hour).mean().round(2)
    by_hour.index.name = 'hour'
    return tbl, by_hour.rename('MAE')


def alarm_perf(d):
    rt = d['smp_jeju_rt']; da = d['smp_jeju_da']
    proba = d['smp_neg_proba_jeju'].values
    danger = d['smp_danger_jeju'].astype(bool).values
    yneg = (rt < 0).values
    fatal = ((da >= 0).values & yneg)
    out = []
    out.append(f'대상 {len(d)}h ({d.index.min().date()}~{d.index.max().date()})')
    out.append(f'음수(rt<0) {int(yneg.sum())}개  치명(da≥0&rt<0) {int(fatal.sum())}개\n')
    out.append(f'ROC-AUC {roc_auc_score(yneg, proba):.3f}   PR-AUC {average_precision_score(yneg, proba):.3f}\n')

    def rp(nm, pred):
        tp = int((pred & yneg).sum()); fn = int((~pred & yneg).sum()); fp = int((pred & ~yneg).sum())
        ftp = int((pred & fatal).sum())
        rec = tp / (tp + fn) if tp + fn else float('nan')
        frec = ftp / fatal.sum() if fatal.sum() else float('nan')
        prec = tp / (tp + fp) if tp + fp else float('nan')
        out.append(f'  {nm:16s} recall={rec:.3f} 치명recall={frec:.3f} precision={prec:.3f} '
                   f'치명FN={fn} 헛경보FP={fp}')
    out.append('[음수 탐지 비교]')
    rp('모델 경보', danger)
    rp('DA<10 단독', (da < 10).values)
    out.append('\n[계절별 모델 경보 치명recall]')
    for s in ['봄', '여름', '가을', '겨울']:
        m = (d['season'] == s).values
        if (m & fatal).sum():
            ftp = int((danger & fatal & m).sum()); nf = int((fatal & m).sum())
            out.append(f'  {s}: {ftp}/{nf} = {ftp/nf:.3f}')
    return '\n'.join(out)


def plot_april(d, out):
    a = d[(d.index >= '2026-04-01') & (d.index <= '2026-04-30 23:00')]
    rt, da = a['smp_jeju_rt'], a['est_smp_jeju']
    danger = a['smp_danger_jeju'].astype(bool).values
    yneg = (rt < 0).values
    fig, ax = plt.subplots(figsize=(18, 6))
    ax.plot(rt.index, rt.values, color='black', lw=1.0, label='실제 RT SMP')
    ax.plot(da.index, da.values, color='steelblue', lw=1.3, label='예측 가격선 (=DA)')
    ax.axhline(0, color='gray', lw=0.7)
    ax.fill_between(rt.index, min(rt.min(), -80), 0, where=danger, color='red', alpha=0.13,
                    step='post', label='음수경보(모델)')
    ax.scatter(rt.index[yneg], rt.values[yneg], color='red', s=22, zorder=5, label='실제 음수')
    tp = int((danger & yneg).sum()); fn = int((~danger & yneg).sum()); fp = int((danger & ~yneg).sum())
    ax.set_title(f'2026년 4월 제주 음수 SMP 경보 — 음수 {tp+fn}건 중 {tp} 포착(놓침 {fn}), 헛경보 {fp}h')
    ax.set_ylabel('원/kWh'); ax.xaxis.set_major_formatter(mdates.DateFormatter('%m-%d'))
    ax.legend(loc='lower left', fontsize=9, ncol=2)
    plt.tight_layout(); plt.savefig(out, dpi=110); plt.close(fig)


def main():
    d = load()
    tbl, by_hour = priceline_mae(d)
    tbl.to_csv(os.path.join(HERE, 'smp_priceline_mae.csv'), index=False, encoding='utf-8-sig')
    by_hour.to_csv(os.path.join(HERE, 'smp_priceline_mae_hourly.csv'), encoding='utf-8-sig')
    perf = alarm_perf(d)
    open(os.path.join(HERE, 'smp_alarm_performance.txt'), 'w', encoding='utf-8').write(perf)
    plot_april(d, os.path.join(HERE, 'smp_product_april.png'))

    summary = ('[4단계 SMP(A안) 보고서 요약]\n'
               f'대상 {len(d)}h ({d.index.min().date()}~{d.index.max().date()})\n\n'
               '── 가격선 MAE (전체/계절) ──\n' + tbl.to_string(index=False) + '\n\n'
               '── 음수경보 성능 ──\n' + perf + '\n')
    open(os.path.join(HERE, 'smp_compare_summary.txt'), 'w', encoding='utf-8').write(summary)
    print(summary)
    print('[saved] smp_priceline_mae.csv / _hourly.csv / smp_alarm_performance.txt / '
          'smp_product_april.png / smp_compare_summary.txt')


if __name__ == '__main__':
    import sys
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass
    main()

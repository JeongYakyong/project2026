# -*- coding: utf-8 -*-
"""증거물 — 가스 발전량은 완벽 학습이 불가능하다 (급전 재량 = 환원 불가능 오차).

배경(2026-06-15, 사용자): 모델 개선이 아니라 "정확한 천연가스 발전량은 전력거래소(KPX)의
급전 판단이 관여하므로 완벽 학습이 불가능하다"는 결론을 뒷받침할 정량 증거가 목적.

증거② — 환원 불가능한 오차 바닥(oracle):
  같은 가스 모델을 (a) 실측 드라이버 입력(완벽 예측 가정) vs (b) v2 체인 예측 입력 으로 평가.
  (a)가 도달하는 MAPE = 수요·신재생을 완벽히 알아도 못 줄이는 바닥.  (b)-(a) = 예측체인 몫.

증거③ — 동일조건 분산(모델 무관):
  관측 가능한 조건 (계절×시각×요일유형×net_load 구간) 으로 묶었을 때 실측 가스의 분산.
  같은 조건이 여러 가스 값에 대응 → 그 관측치만 쓰는 어떤 예측기(최선=조건부 평균)도
  넘을 수 없는 MAPE 하한.  잔차 = 급전 재량(예비력·제약발전·석탄/원전 정비 등 미관측).

산출: 콘솔 표 + fig/irreducible_*.png (보고서용).
"""
from __future__ import annotations
import os, sys, importlib.util
import numpy as np, pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
FIG = os.path.join(HERE, '..', 'training', 'fig')
os.makedirs(FIG, exist_ok=True)


def _imp(name, path):
    s = importlib.util.spec_from_file_location(name, path); m = importlib.util.module_from_spec(s)
    s.loader.exec_module(m); return m


eg = _imp('eg', os.path.join(HERE, 'exp_gas.py'))
SEASON = eg.SEASON
BLOCKS = eg.BLOCKS
mape, nbias = eg.mape, eg.nbias


# ---------------------------------------------------------------- 증거② oracle
def evidence2(d, samp):
    """oracle(실측입력) vs 체인(예측입력) — 같은 모델, 같은 행(동일 origin·timestamp)에서 비교."""
    feat = eg.G0 + eg.AUTO + ['net_load']     # 가장 강한(비이동) 드라이버 집합 = 가장 낮은 바닥
    model, best = eg.train(samp, feat)

    # 체인 평가행(parquet origin) — 드라이버=예측, 가스lag=실측
    ch = eg.eval_chain(model, best, feat, d).copy()
    ch['pred_chain'] = ch.pred

    # 같은 행에서 드라이버만 실측으로 교체 → oracle (입력 예측오차 = 0)
    t = pd.DatetimeIndex(ch.timestamp)
    ch['real_demand_land'] = d['real_demand_land'].reindex(t).values
    ch['renew_gen_total_kr'] = d['renew_gen_total_kr'].reindex(t).values
    ch['net_load'] = d['net_load_kr'].reindex(t).values
    ok = ch[['real_demand_land', 'renew_gen_total_kr', 'net_load']].notna().all(axis=1)
    ch.loc[ok, 'pred_oracle'] = model.predict(ch.loc[ok, feat], num_iteration=best)

    print('=' * 74)
    print('증거② — 환원 불가능한 오차 바닥 (동일 행: 실측입력 oracle vs 예측입력 체인)')
    print('=' * 74)
    rows = []
    for n, (lo, hi) in BLOCKS.items():
        g = ch[(ch.h >= lo) & (ch.h <= hi)].dropna(subset=['pred_oracle'])
        mo = mape(g.gen_gas_kr, g.pred_oracle); mc = mape(g.gen_gas_kr, g.pred_chain)
        rows.append((n, mo, mc, mc - mo))
    print(f'{"지평":>5} | {"oracle(완벽입력)":>15} | {"체인(예측입력)":>13} | {"입력예측 몫":>10}')
    for n, mo, mc, gap in rows:
        print(f'  D+{n:>2} | {mo:13.2f}%  | {mc:11.2f}%  | {gap:+8.2f}%p')
    print(f'  → 핵심: 수요·신재생을 완벽히 알아도(oracle) 바닥 ~{rows[0][1]:.0f}%는 남고,')
    print(f'         D+1({rows[0][1]:.1f}%)→D+12({rows[-1][1]:.1f}%) 거의 평평 = 지평 불확실성이 아니라 구조적 바닥.')

    # 낮(09-15) 계절별 oracle 바닥
    print('\n낮(09-15h) 계절별 — oracle(완벽입력) 바닥:')
    for s in ['겨울', '봄', '여름']:
        g = ch[(ch.season == s) & (t.hour >= 9) & (t.hour <= 15)].dropna(subset=['pred_oracle'])
        print(f'  {s}낮: oracle MAPE {mape(g.gen_gas_kr, g.pred_oracle):5.2f}%  '
              f'bias {nbias(g.gen_gas_kr, g.pred_oracle):+5.1f}%  (n={len(g)})')
    return ch, rows


# ---------------------------------------------------------------- 증거③ 동일조건 분산
def evidence3(d):
    """모델 무관 — 동일 관측조건 내 실측 가스 분산 = 조건부평균 예측기의 MAPE 하한."""
    df = d.dropna(subset=['gen_gas_kr', 'net_load_kr', 'day_type']).copy()
    df = df[df.gen_gas_kr > 0]
    df = df[df.index.year >= 2023]                       # 최근 계통 체제(2023-2025)
    df['season'] = df.index.month.map(SEASON)
    df['hour'] = df.index.hour
    # net_load 구간: (계절×시각) 안에서 3분위 — merit order x축(잔차수요) 동일수준 묶기
    df['nl_bin'] = (df.groupby(['season', 'hour'])['net_load_kr']
                    .transform(lambda x: pd.qcut(x, 3, labels=False, duplicates='drop')))
    keys = ['season', 'hour', 'day_type', 'nl_bin']
    grp = df.groupby(keys)['gen_gas_kr']
    df['bin_mean'] = grp.transform('mean')
    df['bin_std'] = grp.transform('std')
    df['bin_n'] = grp.transform('size')
    q = df[df.bin_n >= 10].copy()                        # 표본 충분 bin 만

    floor_mape = float(np.mean(np.abs(q.gen_gas_kr - q.bin_mean) / q.gen_gas_kr) * 100)
    cov = float((q.bin_std / q.bin_mean).replace([np.inf, -np.inf], np.nan).dropna().mean() * 100)
    print('\n' + '=' * 70)
    print('증거③ — 동일조건 분산 (모델 무관, 조건부평균 예측기의 MAPE 하한)')
    print('=' * 70)
    print(f'조건 = (계절×시각×요일유형×net_load 3분위), 표본>=10 bin, 2023-2025')
    print(f'  유효 표본 {len(q):,}h / {q.groupby(keys).ngroups} bins')
    print(f'  → 조건부평균 예측기 MAPE 하한 = {floor_mape:5.2f}%')
    print(f'  → bin 내 평균 변동계수(CoV) = {cov:4.1f}%  (동일조건 내 표준편차/평균)')

    # 낮 계절별 하한
    print('\n낮(09-15h) 계절별 — 조건부평균 하한:')
    qd = q[(q.hour >= 9) & (q.hour <= 15)]
    for s in ['겨울', '봄', '여름']:
        g = qd[qd.season == s]
        fm = float(np.mean(np.abs(g.gen_gas_kr - g.bin_mean) / g.gen_gas_kr) * 100)
        print(f'  {s}낮: 하한 MAPE {fm:5.2f}%  (n={len(g)})')

    # 구체 예시 bin — 봄 평일 13시, 중간 net_load
    ex = df[(df.season == '봄') & (df.hour == 13) & (df.day_type == 'weekday') & (df.nl_bin == 1)]
    if len(ex) >= 10:
        print(f'\n[예시] 봄·평일·13시·net_load 중간구간 (n={len(ex)}):')
        print(f'  net_load {ex.net_load_kr.min():.0f}~{ex.net_load_kr.max():.0f}MW (거의 동일조건)인데')
        print(f'  실측 가스 = 평균 {ex.gen_gas_kr.mean():.0f}MW, 범위 {ex.gen_gas_kr.min():.0f}~'
              f'{ex.gen_gas_kr.max():.0f}MW (±{ex.gen_gas_kr.std():.0f}, CoV {ex.gen_gas_kr.std()/ex.gen_gas_kr.mean()*100:.0f}%)')
    return q, floor_mape, cov, df


# ---------------------------------------------------------------- 그림
def figures(rows, q, scatter_df):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    try:
        plt.rcParams['font.family'] = 'Malgun Gothic'
    except Exception:
        pass
    plt.rcParams['axes.unicode_minus'] = False

    # Fig1 (증거②): 지평별 oracle vs 체인 MAPE
    fig, ax = plt.subplots(figsize=(6.2, 3.4))
    ns = [f'D+{r[0]}' for r in rows]; orac = [r[1] for r in rows]; chain = [r[2] for r in rows]
    x = np.arange(len(ns))
    ax.bar(x - 0.2, orac, 0.4, label='oracle(실측 입력)', color='#c44e52')
    ax.bar(x + 0.2, chain, 0.4, label='체인(예측 입력)', color='#dd8452', alpha=0.85)
    ax.set_xticks(x); ax.set_xticklabels(ns)
    ax.set_ylabel('가스 MAPE (%)'); ax.set_title('증거② 환원 불가능한 오차 바닥 — 완벽 입력에도 남는 오차')
    ax.legend(frameon=False, fontsize=9)
    for xi, o in zip(x, orac):
        ax.text(xi - 0.2, o + 0.1, f'{o:.1f}', ha='center', va='bottom', fontsize=8)
    ax.grid(axis='y', alpha=0.3); fig.tight_layout()
    f1 = os.path.join(FIG, 'irreducible_floor.png'); fig.savefig(f1, dpi=130); plt.close(fig)

    # Fig2 (증거③): 봄 낮 가스 vs net_load 산점 — 동일 net_load에서 세로 분산
    s = scatter_df[(scatter_df.season == '봄') & (scatter_df.hour >= 9) & (scatter_df.hour <= 15)]
    fig, ax = plt.subplots(figsize=(6.2, 3.6))
    ax.scatter(s.net_load_kr, s.gen_gas_kr, s=6, alpha=0.25, color='#4c72b0', edgecolors='none')
    # 예시 동일조건(봄·평일·13시·중간 net_load)의 세로 분산 강조
    ex = s[(s.day_type == 'weekday') & (s.hour == 13) & (s.nl_bin == 1)]
    if len(ex) >= 10:
        xc = float(ex.net_load_kr.mean()); lo, hi = float(ex.gen_gas_kr.min()), float(ex.gen_gas_kr.max())
        ax.axvspan(ex.net_load_kr.min(), ex.net_load_kr.max(), color='#c44e52', alpha=0.08)
        ax.annotate('', xy=(xc, hi), xytext=(xc, lo),
                    arrowprops=dict(arrowstyle='<->', color='#c44e52', lw=1.8))
        ax.text(xc + 1500, (lo + hi) / 2, f'동일조건인데\n가스 {lo/1000:.1f}~{hi/1000:.1f}GW',
                color='#c44e52', fontsize=8.5, va='center')
    ax.set_xlabel('net_load = 수요 - 신재생 (MW), merit order 잔차수요')
    ax.set_ylabel('실측 가스 발전 (MW)')
    ax.set_title('증거③ 동일 net_load에도 가스는 넓게 흩어짐 (봄 낮) — 급전 재량')
    ax.grid(alpha=0.3); fig.tight_layout()
    f2 = os.path.join(FIG, 'irreducible_dispersion.png'); fig.savefig(f2, dpi=130); plt.close(fig)
    print(f'\n저장: {f1}\n      {f2}')


def main():
    d = eg.load_cont()
    samp = eg.build_samples(d)
    ch, rows = evidence2(d, samp)
    q, floor_mape, cov, scatter_df = evidence3(d)
    figures(rows, q, scatter_df)


if __name__ == '__main__':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass
    main()

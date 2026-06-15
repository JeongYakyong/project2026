# -*- coding: utf-8 -*-
"""LNG 조달 시나리오 v3 — 가격축 제거, 재고/신뢰성 중심 (WORKORDER_procurement_v3).

배경: 가스공사 도입팀의 실제 결정변수는 "가격 타이밍"이 아니라 **공급 안정성(재고)**. 발전용 가스는
사실상 의무공급이라 "비싸서 안 산다"가 성립 안 함. 따라서 예보 정밀도의 가치는 가격 차익이 아니라
**"같은 공급 안정성(붕괴 0)을 더 적은 재고로 달성 + 같은 재고에서 비상조달을 덜 유발"** 로 측정한다.
(우리 모델은 가스 *수요*를 예측하지 *가격*을 예측하지 않는다.)

v2 대비: JKM/$/비용·가격국면 전부 제거. 수치(σ·붕괴·비상물량)는 동일 로직 — 표현만 톤·일·붕괴로.
정직성: 결과를 정해놓지 않음. 3모델에 정책·하한·안전재고(SS) 동일, 소비예보만 다름(oracle/ours/naive).
파라미터(days-of-supply): FLOOR=14·START=21·CAP=30×daily_max, LEAD=14, 보호구간=15. 헤드라인 SS=3일치(a-priori).
"""
from __future__ import annotations
import os, sys, sqlite3, math
from collections import defaultdict
import numpy as np, pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, '..', '..'))
DB = os.path.join(ROOT, '1. data_fetcher_and_db', 'data', 'input_data_land.db')
FIG = os.path.join(HERE, 'fig'); os.makedirs(FIG, exist_ok=True)

TON_PER_MWH = 0.1521
LEAD = 14; PROT = LEAD + 1
HEADLINE_SS_DAYS = 3
SS_SWEEP_DAYS = [0, 0.5, 1, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10, 12, 14]


def load_actual_daily():
    with sqlite3.connect(DB) as con:
        g = pd.read_sql("SELECT timestamp, gen_gas_kr FROM historical WHERE timestamp>='2025-09-01' AND timestamp<'2026-06-15'",
                        con, parse_dates=['timestamp'])
    g = g[g.gen_gas_kr > 0]
    return g.set_index('timestamp')['gen_gas_kr'].resample('D').sum() * TON_PER_MWH


def load_forecast_daily():
    with sqlite3.connect(DB) as con:
        e = pd.read_sql('SELECT base, horizon_d, est_gas_sendout_ton_land FROM est_horizon_land '
                        'WHERE est_gas_sendout_ton_land IS NOT NULL', con)
    e['base_date'] = pd.to_datetime(e['base']).dt.normalize()
    return e.groupby(['base_date', 'horizon_d'])['est_gas_sendout_ton_land'].sum()


def simulate(fc_fn, days, actual, SS, warmup):
    """순수 재고정책(가격 무관). base-stock(포지션=보유+운송중), S=FLOOR+SS+예보LTD(15일).
    하한 붕괴 시 부족분을 비상 조달(물량만 집계, 가격 미사용)·복구."""
    I = START; arrivals = defaultdict(float)
    for i in range(LEAD):
        if i < len(days):
            arrivals[days[i]] += warmup
    et = 0.0; breaches = 0; traj = []
    for t in days:
        I += arrivals.pop(t, 0.0)
        ltd = sum(fc_fn(t, k) for k in range(1, PROT + 1))
        IP = I + sum(arrivals.values())
        q = max(0.0, (FLOOR + SS + ltd) - IP)
        if q > 0:
            arrivals[t + pd.Timedelta(days=LEAD)] += q
        I -= float(actual.loc[t]) if t in actual.index else 0.0
        if I < FLOOR:
            et += FLOOR - I; I = FLOOR; breaches += 1
        traj.append((t, I))
    tj = pd.DataFrame(traj, columns=['date', 'inv'])
    return dict(breaches=breaches, emerg_tons=et, avg_inv=float(tj.inv.mean()), traj=tj)


def main():
    global FLOOR, START, CAP
    actual = load_actual_daily(); fc = load_forecast_daily()
    win = actual.loc['2025-12-01':'2026-06-14']
    daily_max = float(win.max()); daily_avg = float(win.mean())
    FLOOR, START, CAP = 14 * daily_max, 21 * daily_max, 30 * daily_max
    D = daily_max   # 일수 환산 기준
    print(f'daily 소비: 평균 {daily_avg:,.0f}  최대(daily_max) {daily_max:,.0f} ton')
    print(f'FLOOR(14일) {FLOOR/1e3:,.0f}천t | START(21일) | CAP(30일) | LEAD {LEAD}일 보호 {PROT}일')

    base_dates = set(fc.index.get_level_values(0))
    end = actual.index.max() - pd.Timedelta(days=PROT)

    def full(t):
        return all((t, k) in fc.index for k in range(1, PROT + 1))
    days = [t for t in pd.date_range('2025-12-16', end, freq='D') if t in base_dates and full(t)]
    miss = sum(1 for t in days for k in range(1, PROT + 1) if (t, k) not in fc.index)
    print(f'결정일 {len(days)}개 ({days[0].date()}~{days[-1].date()}), 기후값 폴백 {miss}건 '
          f'{"(★0=정상)" if miss == 0 else "(⚠ 폴백!)"}')

    def f_oracle(t, k):
        d = t + pd.Timedelta(days=k); return float(actual.loc[d]) if d in actual.index else daily_avg

    def f_ours(t, k):
        v = fc.get((t, k)); return float(v) if v is not None and np.isfinite(v) else daily_avg

    def f_naive(t, k):
        d = t + pd.Timedelta(days=k); ref = d - pd.Timedelta(days=7 * math.ceil(k / 7))
        return float(actual.loc[ref]) if ref in actual.index else daily_avg

    models = [('oracle', f_oracle, '#0f172a'), ('ours', f_ours, '#059669'), ('naive', f_naive, '#c44e52')]
    warm = daily_avg

    def sigma(fn):
        e = []
        for t in days:
            a = sum(float(actual.loc[t+pd.Timedelta(days=k)]) for k in range(1, PROT+1) if (t+pd.Timedelta(days=k)) in actual.index)
            e.append(a - sum(fn(t, k) for k in range(1, PROT+1)))
        return float(np.std(e))
    sig = {nm: sigma(fn) for nm, fn, _ in models}

    # 신뢰도 곡선 sweep + 붕괴0 필요 안전재고(일수)
    sweep = {nm: {'breach': [], 'etons': []} for nm, _, _ in models}
    for ssd in SS_SWEEP_DAYS:
        for nm, fn, _ in models:
            r = simulate(fn, days, actual, ssd * D, warm)
            sweep[nm]['breach'].append(r['breaches']); sweep[nm]['etons'].append(r['emerg_tons'] / 1e3)

    def min_ss_days(fn):
        for ssd in np.arange(0, 14.01, 0.25):
            if simulate(fn, days, actual, ssd * D, warm)['breaches'] == 0:
                return float(ssd)
        return 14.0
    minss = {nm: min_ss_days(fn) for nm, fn, _ in models}

    # 헤드라인 표 (SS=3일치)
    SS = HEADLINE_SS_DAYS * D
    res = {nm: simulate(fn, days, actual, SS, warm) for nm, fn, _ in models}
    print('\n' + '=' * 84)
    print(f'★ 헤드라인 (SS={HEADLINE_SS_DAYS}일치={SS/1e3:,.0f}천t, a-priori 고정) — 3모델 동일 SS, 가격 없음')
    print('=' * 84)
    print(f'{"모델":>7} | {"LTD오차σ(천t)":>12} | {"붕괴":>5} | {"비상물량(천t)":>11} | {"평균재고(일)":>11} | {"붕괴0 필요SS(일)":>14}')
    for nm, _, _ in models:
        r = res[nm]
        print(f'{nm:>7} | {sig[nm]/1e3:10.0f} | {r["breaches"]:4}회 | {r["emerg_tons"]/1e3:10.0f} | '
              f'{r["avg_inv"]/D:10.1f} | {minss[nm]:13.2f}')
    u, n = res['ours'], res['naive']
    print(f'\n  ★ ours vs naive: σ {sig["ours"]/1e3:.0f}k vs {sig["naive"]/1e3:.0f}k (ours가 {(1-sig["ours"]/sig["naive"])*100:.0f}% 정밀)')
    print(f'     붕괴0 필요 안전재고 {minss["ours"]:.2f}일 vs {minss["naive"]:.2f}일 (ours가 {minss["naive"]-minss["ours"]:.2f}일 적게)')
    print(f'     @SS=3일 비상물량 {u["emerg_tons"]/1e3:.0f}천t vs {n["emerg_tons"]/1e3:.0f}천t')

    # ── 그림 ──
    import matplotlib; matplotlib.use('Agg'); import matplotlib.pyplot as plt
    plt.rcParams['font.family'] = 'Malgun Gothic'; plt.rcParams['axes.unicode_minus'] = False
    col = {'oracle': '#0f172a', 'ours': '#059669', 'naive': '#c44e52'}

    # 그림1 ★ 신뢰도 곡선 (붕괴 + 비상물량)
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(11, 4))
    for nm in col:
        a1.plot(SS_SWEEP_DAYS, sweep[nm]['breach'], 'o-', color=col[nm], label=nm, ms=4)
        a2.plot(SS_SWEEP_DAYS, sweep[nm]['etons'], 'o-', color=col[nm], label=nm, ms=4)
    for ax in (a1, a2):
        ax.axvline(HEADLINE_SS_DAYS, color='gray', ls=':', lw=0.8); ax.set_xlabel('보유 안전재고 (일치)'); ax.grid(alpha=0.3); ax.legend(frameon=False)
    a1.set_ylabel('공급차질(붕괴) 횟수'); a1.set_title('신뢰도 곡선 — 붕괴 vs 안전재고')
    a2.set_ylabel('비상 조달물량 (천 톤)'); a2.set_title('비상조달 vs 안전재고')
    fig.suptitle('★ 안전재고 sweep — 같은 안정성을 더 적은 재고로 (ours가 oracle~naive 사이)', fontweight='bold')
    fig.tight_layout(); fig.savefig(os.path.join(FIG, 'procurement_reliability.png'), dpi=130); plt.close(fig)

    # 그림2 재고 궤적(@SS=3d, 일수축, 가격 없음)
    fig, ax = plt.subplots(figsize=(11, 4.2))
    for nm in col:
        tj = res[nm]['traj']; ax.plot(tj.date, tj.inv/D, color=col[nm], lw=1.5, label=nm)
    ax.axhline(FLOOR/D, color='red', ls='--', lw=1); ax.axhline(CAP/D, color='gray', ls=':', lw=1)
    ax.text(days[1], FLOOR/D+0.3, 'FLOOR=14일치(공급하한)', color='red', fontsize=8)
    ax.text(days[1], CAP/D-0.7, 'CAP=30일치', color='gray', fontsize=8)
    ax.set_ylabel('보유재고 (일치 = 톤/daily_max)'); ax.legend(frameon=False, ncol=3, loc='upper right')
    ax.set_title(f'LNG 재고 궤적 @ SS={HEADLINE_SS_DAYS}일치 — 3모델 동일정책, 소비예보만 다름 (가격 무관)')
    ax.grid(alpha=0.3); ax.set_xlabel('2025-12 ~ 2026')
    fig.tight_layout(); fig.savefig(os.path.join(FIG, 'procurement_inventory.png'), dpi=130); plt.close(fig)
    print('\nsaved fig/procurement_reliability.png , fig/procurement_inventory.png')


if __name__ == '__main__':
    try: sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception: pass
    main()

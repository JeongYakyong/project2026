# -*- coding: utf-8 -*-
"""가스 bias 격자 분석 — 지평5구간 × 낮/밤 × 계절 (전체평균의 상쇄 함정 회피).

사용자 지시(2026-06-21): 전체구간 평균으로 판단하면 겨울 과소·여름 과대가 상쇄돼 망한다.
수요 보정표(계절×시각×지평)처럼 가스도 잘게 쪼개 bias 를 보고 후처리(셀별 곱셈 보정)를 정한다.

지평 5구간:
  G1 초단기 D+1~2 / G2 단기 D+3~5 / G3 중기 D+6~8 / G4 중장기 D+9~12 / G5 장기 D+13~15
낮 = 09~15h, 그 외 밤.  계절 = 겨울(12,1,2)/봄(3,4,5)/여름(6,7,8)/가을(9,10,11).

입력: newchain_gas_backtest.parquet (validate_newchain_gas.py 전 지평 산출)
출력: 콘솔 격자표 + gas_bias_grid.csv + (시안)gas_calib_grid_proposed.json
       보정계수 = 셀별 sum(실측)/sum(보정전 raw)  → 평균 bias 0 으로 맞추는 곱셈계수.
       ★표본 n 과 안정성(낮은 n 셀은 채택 보류)을 함께 출력해 과적합 판단 근거 제공.
"""
from __future__ import annotations
import os, json
import numpy as np, pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
PARQUET = os.path.join(HERE, 'newchain_gas_backtest.parquet')

HZ_GROUPS = [('G1 초단기 D1-2', range(1, 3)), ('G2 단기 D3-5', range(3, 6)),
             ('G3 중기 D6-8', range(6, 9)), ('G4 중장기 D9-12', range(9, 13)),
             ('G5 장기 D13-15', range(13, 16))]
HZ2G = {h: g for g, rng in HZ_GROUPS for h in rng}
SEASON = {12: '겨울', 1: '겨울', 2: '겨울', 3: '봄', 4: '봄', 5: '봄',
          6: '여름', 7: '여름', 8: '여름', 9: '가을', 10: '가을', 11: '가을'}


def main():
    df = pd.read_parquet(PARQUET)
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    df = df[(df.gen_gas_kr > 0) & df.est_gas_gen_land.notna()].copy()
    df['hgrp'] = df.horizon_d.map(HZ2G)
    df['season'] = df.timestamp.dt.month.map(SEASON)
    df['daypart'] = np.where((df.timestamp.dt.hour >= 9) & (df.timestamp.dt.hour <= 15), '낮', '밤')
    # 지표: bias(부호) = (보정후 est - 실측)/실측 평균.  raw 도 같이.
    df['spe'] = (df.est_gas_gen_land - df.gen_gas_kr) / df.gen_gas_kr * 100
    df['spe_raw'] = (df.est_gas_gen_land_raw - df.gen_gas_kr) / df.gen_gas_kr * 100
    df['ape'] = (df.est_gas_gen_land - df.gen_gas_kr).abs() / df.gen_gas_kr * 100

    gcol = [g for g, _ in HZ_GROUPS]
    scol = ['겨울', '봄', '여름', '가을']

    def grid(metric, agg='mean'):
        t = df.pivot_table(index=['hgrp', 'daypart'], columns='season',
                           values=metric, aggfunc=agg)
        t = t.reindex(pd.MultiIndex.from_product([gcol, ['낮', '밤']], names=['hgrp', 'daypart']))
        return t.reindex(columns=scol)

    print('=' * 78)
    print('가스 bias(%) 격자  —  지평5구간 × 낮/밤 × 계절   [(보정후 est−실측)/실측, +면 과대]')
    print('=' * 78)
    print(grid('spe').round(1).to_string(na_rep='  ·'))
    print('\n[표본수 n]')
    print(grid('spe', 'size').to_string(na_rep='  ·'))
    print('\n[MAPE(%)]')
    print(grid('ape').round(1).to_string(na_rep='  ·'))

    # ── 셀별 보정계수 시안 = sum(실측)/sum(raw) (평균 bias 0) ──
    rows = []
    for (g, dp, s), gg in df.groupby(['hgrp', 'daypart', 'season']):
        n = len(gg)
        factor = float(gg.gen_gas_kr.sum() / gg.est_gas_gen_land_raw.sum())
        # 보정 적용 후 잔여 bias(검산)
        post = (gg.est_gas_gen_land_raw * factor - gg.gen_gas_kr) / gg.gen_gas_kr * 100
        rows.append(dict(hgrp=g, daypart=dp, season=s, n=n,
                         bias_raw=float(gg.spe_raw.mean()), bias_now=float(gg.spe.mean()),
                         factor=round(factor, 4), bias_post=float(post.mean()),
                         mape_now=float(gg.ape.mean())))
    cells = pd.DataFrame(rows).sort_values(['hgrp', 'daypart', 'season'])
    cells.to_csv(os.path.join(HERE, 'gas_bias_grid.csv'), index=False, encoding='utf-8-sig')

    print('\n' + '=' * 78)
    print('셀별 보정계수 시안 (factor = Σ실측/Σraw, bias_now=현재 보정후 부호, n=표본)')
    print('   ★ n 작은 셀(여름·가을)은 채택 보류 후보 — 과적합 위험')
    print('=' * 78)
    show = cells[['hgrp', 'daypart', 'season', 'n', 'bias_now', 'factor', 'bias_post', 'mape_now']]
    print(show.to_string(index=False))

    # 표본 충분 기준(예: n>=300) 셀만 시안 JSON 으로
    THRESH = 300
    proposed = {}
    for r in cells.itertuples(index=False):
        if r.n >= THRESH:
            proposed.setdefault(r.hgrp, {}).setdefault(r.daypart, {})[r.season] = r.factor
    out = {'note': '시안 — 채택 전 검토용. factor=Σ실측/Σraw, n>=%d 셀만.' % THRESH,
           'thresh_n': THRESH, 'factor_by_hgrp_daypart_season': proposed}
    with open(os.path.join(HERE, 'gas_calib_grid_proposed.json'), 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    # 시안 채택 시 전체 MAPE 변화(전 셀 factor 적용, 검산)
    fmap = {(r.hgrp, r.daypart, r.season): r.factor for r in cells.itertuples(index=False)}
    df['f'] = df.apply(lambda x: fmap.get((x.hgrp, x.daypart, x.season), 1.0), axis=1)
    new_est = df.est_gas_gen_land_raw * df.f
    new_ape = (new_est - df.gen_gas_kr).abs() / df.gen_gas_kr * 100
    print('\n' + '-' * 78)
    print(f'현재(보정 OFF·블렌딩 ON) 전체 MAPE {df.ape.mean():.2f}% / bias {df.spe.mean():+.1f}%')
    print(f'격자 보정(전 셀 factor, in-sample) 전체 MAPE {new_ape.mean():.2f}% / bias '
          f'{((new_est-df.gen_gas_kr)/df.gen_gas_kr*100).mean():+.1f}%')
    print('  ※ in-sample 상한이라 낙관편향 — 표본 큰 셀 위주로만 보수 채택 권장.')
    print('\nsaved gas_bias_grid.csv, gas_calib_grid_proposed.json')


if __name__ == '__main__':
    import sys
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass
    main()

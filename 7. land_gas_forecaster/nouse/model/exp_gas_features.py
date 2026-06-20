# -*- coding: utf-8 -*-
"""가스 피처 정식 분석 — 전체 피처리스트 + 중요도(gain/split) + 공선성(상관·VIF).

사용자 요청(2026-06-14): 가스 최종 피처 확정 전 §0.6/G-9 식 검토.  exp_gas 의 후보 전체
피처(G3 superset)에 대해 (1) 역할 (2) LGBM 중요도 (3) 상관행렬 (4) VIF (5) 단조추세(연도상관,
cap_btmppa covariate shift 점검) 를 낸다.
"""
from __future__ import annotations
import os, sys, importlib.util
import numpy as np, pandas as pd, lightgbm as lgb
from numpy.linalg import inv

HERE = os.path.dirname(os.path.abspath(__file__))
exg = importlib.util.spec_from_file_location('exg', os.path.join(HERE, 'exp_gas.py'))
exp_gas = importlib.util.module_from_spec(exg); exg.loader.exec_module(exp_gas)

ROLE = {
    'real_demand_land': '드라이버 — 계량수요 예측(5단계 v2). 가스 주구동',
    'renew_gen_total_kr': '드라이버 — 시장 신재생 예측(6단계)',
    'net_load': '드라이버 — 수요−신재생(historical 실측 학습)',
    'cap_btmppa': '월별 PPA 용량(단조 증가)',
    'h': '지평(1..288) — Global+Horizon',
    'gas_lag168': '가스 자기회귀 — 1주전 같은시각(h>168 NaN)',
    'gas_lag24': '가스 자기회귀 — 1일전(h<=24만)',
    'gas_rec24': '가스 최근레벨 — origin 직전 24h 평균',
    'gas_rec168': '가스 최근레벨 — origin 직전 168h 평균',
    'hour': '달력', 'dow': '달력', 'month': '달력', 'doy': '달력(연중일)',
    'day_type': '달력 — 평일/주말/공휴일(범주)',
}
FULL = ['real_demand_land', 'renew_gen_total_kr', 'net_load', 'cap_btmppa', 'h',
        'gas_lag168', 'gas_lag24', 'gas_rec24', 'gas_rec168',
        'hour', 'dow', 'month', 'doy', 'day_type']
# 공선성 평가용 dense 수치 피처(거의 항상 존재). lag24 는 대부분 NaN 이라 제외, lag168 은 h<=168 부분집합에서.
DENSE = ['real_demand_land', 'renew_gen_total_kr', 'net_load', 'cap_btmppa',
         'gas_lag168', 'gas_rec24', 'gas_rec168', 'hour', 'dow', 'month', 'doy', 'h']


def main():
    d = exp_gas.load_cont()
    samp = exp_gas.build_samples(d)
    samp['tyearnum'] = samp.tyear.astype(int)
    tr = samp[(samp.tyear >= 2022) & (samp.tyear <= 2024)].copy()

    print('=' * 78)
    print('1) 전체 피처 리스트 (가스 G3 superset)')
    print('=' * 78)
    for f in FULL:
        print(f'  {f:20} {ROLE[f]}')

    # 2) 중요도 — 전체 피처로 학습
    m, best = exp_gas.train(samp, FULL)
    imp = pd.DataFrame({'feature': m.feature_name(),
                        'gain': m.feature_importance('gain'),
                        'split': m.feature_importance('split')})
    imp['gain%'] = (imp.gain / imp.gain.sum() * 100).round(1)
    imp = imp.sort_values('gain', ascending=False)
    print('\n' + '=' * 78); print(f'2) 피처 중요도 (전체피처 학습, best_iter {best})'); print('=' * 78)
    print(imp[['feature', 'gain%', 'split']].to_string(index=False))

    # 3) 상관행렬 (dense, h<=168 부분집합에서 lag168 포함)
    sub = tr[tr.h <= 168].dropna(subset=DENSE)
    if len(sub) > 200000:
        sub = sub.sample(200000, random_state=0)
    corr = sub[DENSE].corr()
    print('\n' + '=' * 78); print('3) 상관행렬 (dense 피처, |r|>=0.5 만 표시)'); print('=' * 78)
    cc = corr.copy()
    for i in range(len(cc)):
        for j in range(len(cc)):
            if i <= j or abs(cc.iloc[i, j]) < 0.5:
                cc.iloc[i, j] = np.nan
    pairs = [(cc.index[i], cc.columns[j], cc.iloc[i, j])
             for i in range(len(cc)) for j in range(len(cc)) if pd.notna(cc.iloc[i, j])]
    for a, b, r in sorted(pairs, key=lambda x: -abs(x[2])):
        print(f'  {a:20} ~ {b:20} r = {r:+.3f}')

    # 4) VIF (dense)
    C = corr.values
    vif = np.diag(inv(C))
    print('\n' + '=' * 78); print('4) VIF (>10 위험, >5 주의)'); print('=' * 78)
    vt = pd.DataFrame({'feature': DENSE, 'VIF': vif.round(2)}).sort_values('VIF', ascending=False)
    print(vt.to_string(index=False))

    # 5) 단조추세 점검 (covariate shift) — 연도/타깃 상관
    print('\n' + '=' * 78); print('5) 연도(추세) 상관 + 타깃 상관 (cap_btmppa covariate shift 점검)'); print('=' * 78)
    sub2 = tr.dropna(subset=['cap_btmppa'])
    for f in ['cap_btmppa', 'real_demand_land', 'net_load', 'gas_rec168', 'renew_gen_total_kr']:
        ry = np.corrcoef(sub2['tyearnum'], sub2[f])[0, 1]
        rt = np.corrcoef(sub2[f], sub2['y'])[0, 1]
        print(f'  {f:20} corr(연도)={ry:+.3f}   corr(타깃 gas)={rt:+.3f}')
    # 2026 분포 이탈(외삽) — cap_btmppa train vs test 범위
    te = samp[samp.tyear == 2026]
    print(f'\n  cap_btmppa 범위: train(<=2024) {tr.cap_btmppa.min():.0f}~{tr.cap_btmppa.max():.0f}  '
          f'/ test(2026) {te.cap_btmppa.min():.0f}~{te.cap_btmppa.max():.0f}  '
          f'→ test 가 train 최대 초과 = {te.cap_btmppa.max()>tr.cap_btmppa.max()} (외삽)')


if __name__ == '__main__':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass
    main()

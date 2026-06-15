# -*- coding: utf-8 -*-
"""수요 비대칭 손실 실험 — 낮(09-15h) 과대예측 페널티 (land 부호 = 낮 과대를 아래로).

확정 피처(2026-06-14): 지점선택(일사=서산영광/풍속=대관령포항) + 구름(서산영광) + cap_btmppa.
그 위에서 커스텀 L1 목적함수에 **낮 & pred>actual 인 샘플의 gradient 를 α배** 가중해 낮 과대를
줄인다.  α=1.0 은 V2(대칭 L1)와 동일 기준선.  제주식(낮 과소→위로)과 반대 부호임에 유의.

평가축 = 실예보 백테스트 지평 + 계절×낮.  exp_features 의 데이터·평가 기계를 재사용.
"""
from __future__ import annotations
import os, sys, importlib.util
import numpy as np, pandas as pd, lightgbm as lgb

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location('expf', os.path.join(HERE, 'exp_features.py'))
expf = importlib.util.module_from_spec(spec); spec.loader.exec_module(expf)

FEAT = expf.BASEFEAT + ['total_cloud', 'midlow_cloud', 'cap_btmppa']   # 확정 피처
ALPHAS = [1.0, 2.0, 4.0, 8.0]
# 커스텀 목적함수(L2 비대칭)는 평균 초기화를 안 해 init_score 를 평균으로 직접 준다.
# L2 를 쓰는 이유: L1 커스텀은 grad=±1 이라 lr×±1 로만 움직여 75GW 레벨 수렴이 비현실적.
PARAMS = dict(metric='l1', learning_rate=0.03, num_leaves=255, min_data_in_leaf=100,
              feature_fraction=0.85, bagging_fraction=0.8, bagging_freq=5, lambda_l2=0.2,
              verbosity=-1, random_state=42)


class Shifted:
    """커스텀 목적함수 + init_score 사용 시 predict 는 init_score 를 안 더해주므로 수동 보정."""
    def __init__(s, m, offset): s.m = m; s.offset = offset
    def predict(s, X, num_iteration=None): return s.m.predict(X, num_iteration=num_iteration) + s.offset
    def feature_name(s): return s.m.feature_name()
    def feature_importance(s, *a, **k): return s.m.feature_importance(*a, **k)


def make_obj(is_day, alpha):
    def obj(y_pred, dset):
        resid = y_pred - dset.get_label()          # L2: grad=resid, hess=1
        grad = resid.astype(np.float64); hess = np.ones_like(resid)
        over_day = is_day & (resid > 0)            # 낮 & 과대 → α배 (land: 낮 과대 억제)
        grad[over_day] *= alpha; hess[over_day] *= alpha
        return grad, hess
    return obj


def train_asym(samp, alpha):
    tr = samp[samp.tyear <= 2024]; va = samp[samp.tyear == 2025]
    is_day_tr = ((tr.hour.values >= 9) & (tr.hour.values <= 15))
    init = float(tr.y.mean())
    dtr = lgb.Dataset(tr[FEAT], tr.y, categorical_feature=['day_type'],
                      init_score=np.full(len(tr), init))
    dva = lgb.Dataset(va[FEAT], va.y, categorical_feature=['day_type'], reference=dtr,
                      init_score=np.full(len(va), init))
    params = dict(PARAMS); params['objective'] = make_obj(is_day_tr, alpha)
    m = lgb.train(params, dtr, num_boost_round=4000, valid_sets=[dva], valid_names=['val'],
                  callbacks=[lgb.early_stopping(150, verbose=False)])
    return Shifted(m, init), int(m.best_iteration)


def main():
    d = expf.load_hist(); ppa = expf.load_capa(); d_act = expf.bht.load_actuals()
    samp = expf.build_samples(d, ppa)
    res = {}
    for a in ALPHAS:
        m, best = train_asym(samp, a)
        res[a] = expf.eval_forecast(m, best, FEAT, d_act, ppa)
        print(f'  alpha={a}: best_iter {best}')

    print('\n======== 지평별 MAPE / bias ========')
    print('지평  | ' + ' | '.join(f'a={a:>4}' + ' '*7 for a in ALPHAS))
    for n in [1, 3, 7, 12]:
        cells = []
        for a in ALPHAS:
            g = res[a]; g = g[g.horizon == n]
            cells.append(f'{expf.mape(g.actual,g.pred):5.2f}/{expf.nbias(g.actual,g.pred):+5.2f}')
        print(f' D+{n:>2} | ' + ' | '.join(f'{c:>12}' for c in cells))
    print('\n======== 계절×낮 MAPE / bias ========')
    for s in ['겨울', '봄', '여름']:
        for dp in ['낮', '밤']:
            cells = []
            for a in ALPHAS:
                g = res[a]; g = g[(g.season == s) & (g.daypart == dp)]
                cells.append(f'{expf.mape(g.actual,g.pred):5.2f}/{expf.nbias(g.actual,g.pred):+5.2f}')
            print(f' {s}{dp} | ' + ' | '.join(f'{c:>12}' for c in cells))


if __name__ == '__main__':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass
    main()

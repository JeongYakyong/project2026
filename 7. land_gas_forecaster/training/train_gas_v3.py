# -*- coding: utf-8 -*-
"""7 v3 production 가스 재학습 — 야간 레짐 대응(최근 원전 관성 피처 + walk-forward).

배경(2026-06-21, G-25): 2026 원전 가용량 하락으로 (net_load→가스) 함수가 야간에 이동(concept
shift). v2(학습 2022-24·원전 미반영)는 겨울 밤 과소(−6~9%)·여름 밤 과대(+8~11%). 진단·실험
근거 = REPORT_7-regime_shift_2026.md / exp_gas_regime.py.

확정(사용자):
  · 피처 = v2 MIXED + **nuke_rec24·nuke_rec168**(origin 이하 최근 원전 평균). 원전은 관성이 커
    (corr_24h 0.998·24h대리 MAE 0.9%) 최근값이 미래 원전의 거의 완벽한 대리 → 서빙 가용.
  · 학습 = **walk-forward**(신레짐 포함 전 가용데이터). 실험: 신레짐을 학습에서 빼면 원전 피처가
    외삽으로 악화(옛 covariate shift 재현), 넣으면 개선(oracle MAPE 10.21→9.57%, 여름밤 +8.7→+5.7%).
  · 손실 = v2 동일 커스텀 L2 비대칭(낮09-15h 과대 ×α4). 타깃 = 가스 MW. init_score=평균 가산.

방법:
  1) fold-C(train ≤2026-03 / val 2026-04~06)로 best_iter·held-out 성능 측정(early stopping).
  2) 최종 production = 전 샘플로 best_iter 만큼 재학습(early stop 없음) → 서빙은 항상 최신 포함.
산출: model/lgbm_land_gas_v3.txt + model_meta_gas_v3.json (v2 는 롤백용 보존).
보정(calib)·블렌딩 재적합은 별도 단계(체인 재검증 후) — 이 스크립트는 모델만.
"""
from __future__ import annotations
import os, sys, json, importlib.util
import numpy as np, pandas as pd, lightgbm as lgb

HERE = os.path.dirname(os.path.abspath(__file__))
MODEL_DIR = os.path.join(HERE, '..', 'model')


def _imp(name, path):
    s = importlib.util.spec_from_file_location(name, path); m = importlib.util.module_from_spec(s)
    sys.modules[name] = m; s.loader.exec_module(m); return m


exp = _imp('exp_gas_regime', os.path.join(HERE, 'exp_gas_regime.py'))

ALPHA = 4.0
FEAT = exp.BASE_FEAT + ['nuke_rec24', 'nuke_rec168']
PARAMS = dict(metric='l1', learning_rate=0.03, num_leaves=127, min_data_in_leaf=100,
              feature_fraction=0.85, bagging_fraction=0.8, bagging_freq=5, lambda_l2=0.2,
              verbosity=-1, random_state=42)


def make_obj(is_day, alpha):
    def obj(y_pred, dset):
        resid = y_pred - dset.get_label()
        grad = resid.astype(np.float64); hess = np.ones_like(resid)
        od = is_day & (resid > 0); grad[od] *= alpha; hess[od] *= alpha
        return grad, hess
    return obj


def _train(tr, va, n_round, early):
    is_day = (tr.hour.values >= 9) & (tr.hour.values <= 15)
    init = float(tr.y.mean())
    dtr = lgb.Dataset(tr[FEAT], tr.y, init_score=np.full(len(tr), init))
    p = dict(PARAMS); p['objective'] = make_obj(is_day, ALPHA)
    cbs = []
    valid = None
    if va is not None:
        dva = lgb.Dataset(va[FEAT], va.y, reference=dtr, init_score=np.full(len(va), init))
        valid = [dva]; cbs = [lgb.early_stopping(early, verbose=False)]
    m = lgb.train(p, dtr, num_boost_round=n_round, valid_sets=valid,
                  valid_names=['val'] if valid else None, callbacks=cbs)
    return m, init


def main():
    d = exp.load_cont()
    samp = exp.build_samples(d)
    print(f'샘플 {len(samp)}행, 연도분포: {samp.tyear.value_counts().sort_index().to_dict()}')
    print(f'피처({len(FEAT)}): {FEAT}')

    # 1) fold-C: best_iter + held-out 성능
    tr_c = samp[(samp.tyear <= 2025) | ((samp.tyear == 2026) & (samp.tmonth <= 3))]
    va_c = samp[(samp.tyear == 2026) & (samp.tmonth >= 4)].copy()
    mC, initC = _train(tr_c, va_c, 3000, 120)
    best = int(mC.best_iteration)
    va_c['p'] = mC.predict(va_c[FEAT], num_iteration=best) + initC
    va_c['night'] = ~((va_c.hour >= 9) & (va_c.hour <= 15))
    nt = va_c[va_c.night]
    print(f'\n[fold-C 검증] best_iter={best}')
    print(f'  전체  MAPE {exp.mape(va_c.y, va_c.p):.2f}%  bias {exp.nbias(va_c.y, va_c.p):+.1f}%')
    print(f'  밤    MAPE {exp.mape(nt.y, nt.p):.2f}%  bias {exp.nbias(nt.y, nt.p):+.1f}%')
    # fold-C 모델 저장 — 봉인 체인 검증(train≤2026-03 모델로 2026-04~ base 체인)용. production 아님.
    mC.save_model(os.path.join(MODEL_DIR, 'lgbm_land_gas_v3_foldC.txt'), num_iteration=best)
    json.dump({'init_score': initC, 'best_iteration': best, 'cutoff': '2026-03-31',
               'use': '봉인 체인 검증 전용(validate_newchain_gas --model foldC --base-min 2026-04-01). production 아님.'},
              open(os.path.join(MODEL_DIR, 'model_meta_gas_v3_foldC.json'), 'w', encoding='utf-8'),
              ensure_ascii=False, indent=2)

    # 2) 최종 production = 전 샘플 × best_iter (early stop 없음)
    mF, initF = _train(samp, None, best, 0)
    mF.save_model(os.path.join(MODEL_DIR, 'lgbm_land_gas_v3.txt'))

    # 피처 중요도(원전 기여 확인)
    imp = pd.Series(mF.feature_importance(importance_type='gain'), index=FEAT).sort_values(ascending=False)
    print('\n[중요도 gain] 상위:')
    for k, v in imp.head(8).items():
        print(f'  {k:18} {v/imp.sum()*100:5.1f}%')

    meta = dict(version='v3', features=FEAT, target='gen_gas_kr (MW)',
                architecture='Global+Horizon 가스 자기회귀 다지평(h 1..360=D+15) + 최근원전 관성피처',
                loss=f'custom asymmetric L2 (낮09-15h over-pred ×{ALPHA})', alpha=ALPHA,
                init_score=initF, predict_note='pred = booster.predict(X) + init_score',
                nuke_feat='nuke_rec24/nuke_rec168 = origin 이하 최근 24h/168h 원전 평균(미래 원전 불필요·관성 대리)',
                renew_util='renew_gen_total_kr / (solar_cap+wind_cap), kr_elec_capa.csv 월별',
                autoreg='gas_lag168(h>168 NaN)/lag24(h<=24)/rec24/rec168, historical 실측',
                train='walk-forward 전 가용데이터(2022~최신, 신레짐 포함)',
                best_iteration=best, foldC_val='train≤2026-03 / val 2026-04~06',
                note='v3: 2026 야간 원전↓ 레짐 대응. 최근원전 피처+walk-forward(G-25). v2(2022-24·원전없음) 롤백 보존.')
    json.dump(meta, open(os.path.join(MODEL_DIR, 'model_meta_gas_v3.json'), 'w', encoding='utf-8'),
              ensure_ascii=False, indent=2)
    print(f'\nsaved model/lgbm_land_gas_v3.txt (best_iter {best}, init_score {initF:.0f}, alpha {ALPHA})')
    print('saved model/model_meta_gas_v3.json')


if __name__ == '__main__':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass
    main()

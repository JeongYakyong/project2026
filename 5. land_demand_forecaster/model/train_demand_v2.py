# -*- coding: utf-8 -*-
"""5-A v2 production 재학습 — 확정 피처 + 비대칭(낮 과대) α=8.

확정(2026-06-14, 사용자):
  구조 = Global Model with Horizon Feature (h 피처 단일 모델, 1..360 direct = D+15).
  피처 = 지점선택(일사=서산·영광 / 풍속=대관령·포항 / 기온=5지점) + 구름(서산·영광 total/midlow)
         + cap_btmppa(월별 PPA 용량) + h·lag168·lag24·rec24·rec168·달력·day_type.
  손실 = 커스텀 L2 비대칭 — 낮(09-15h) & pred>actual 일 때 grad/hess ×α(=8). init_score=평균.
  학습창 = train(타깃≤2024)/val(2025), early stopping.  (실예보 백테스트 검증은 exp_asym 참조)

산출: models/lgbm_land_demand_v2.txt + models/model_meta_v2.json (offset·alpha·피처·지점·capa 기록).
exp_features/exp_asym 의 검증된 함수를 그대로 재사용해 실험↔production 일관성을 보장한다.
"""
from __future__ import annotations
import os, sys, json, importlib.util
import numpy as np, pandas as pd, lightgbm as lgb

HERE = os.path.dirname(os.path.abspath(__file__))
MODELS = os.path.join(HERE, 'models')


def _imp(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m


expf = _imp('expf', os.path.join(HERE, 'exp_features.py'))
expa = _imp('expa', os.path.join(HERE, 'exp_asym.py'))

ALPHA = 8.0
FEAT = expf.BASEFEAT + ['total_cloud', 'midlow_cloud', 'cap_btmppa']


def main():
    d = expf.load_hist(); ppa = expf.load_capa()
    samp = expf.build_samples(d, ppa)
    tr = samp[samp.tyear <= 2024]; va = samp[samp.tyear == 2025]
    init = float(tr.y.mean())
    is_day = ((tr.hour.values >= 9) & (tr.hour.values <= 15))
    dtr = lgb.Dataset(tr[FEAT], tr.y, categorical_feature=['day_type'], init_score=np.full(len(tr), init))
    dva = lgb.Dataset(va[FEAT], va.y, categorical_feature=['day_type'], reference=dtr, init_score=np.full(len(va), init))
    params = dict(expa.PARAMS); params['objective'] = expa.make_obj(is_day, ALPHA)
    m = lgb.train(params, dtr, num_boost_round=4000, valid_sets=[dva], valid_names=['val'],
                  callbacks=[lgb.early_stopping(150, verbose=False)])
    best = int(m.best_iteration)
    m.save_model(os.path.join(MODELS, 'lgbm_land_demand_v2.txt'), num_iteration=best)

    meta = dict(
        version='v2', features=FEAT, categorical=['day_type'], target='real_demand_land',
        architecture='Global Model with Horizon Feature (h 피처, 1..360 direct = D+15)',
        loss='custom asymmetric L2 (낮09-15h & over-pred grad/hess ×alpha)', alpha=ALPHA,
        init_score=init, predict_note='pred = booster.predict(X) + init_score (커스텀목적함수라 수동가산)',
        stations=dict(temp_c=expf.STATIONS, solar_rad=expf.SOLAR_SEL, wind_spd=expf.WIND_SEL,
                      cloud=expf.SOLAR_SEL),
        cap_btmppa='kr_elec_capa.csv PPA(합계, 월별, 끝 이후 ffill)',
        best_iteration=best, origin_hour=23, train='target<=2024', val='2025',
        note='5-A v2: 지점선택+구름+cap_btmppa+낮비대칭. 검증=exp_asym(실예보 백테스트). '
             'old lgbm_land_demand_direct.txt 보존(롤백용).')
    json.dump(meta, open(os.path.join(MODELS, 'model_meta_v2.json'), 'w', encoding='utf-8'),
              ensure_ascii=False, indent=2)
    print(f'saved lgbm_land_demand_v2.txt  best_iter={best}  init_score={init:.1f}  alpha={ALPHA}')
    print('features:', FEAT)


if __name__ == '__main__':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass
    main()

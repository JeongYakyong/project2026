# -*- coding: utf-8 -*-
"""5-A v2comfort — v2 와 동일(비대칭 L2 α=8·init_score·학습창), ★피처만 comfort 강화.

v2 대비 변경(사용자 확정 06-19):
  - temp_c(5지점) → temp_c4(4지점, 대관령 제외)
  - wind_spd(생바람) 제거
  - 불쾌지수 di·체감기온 wct 추가(4지점 T·RH·바람, 기상청식)
production v2(lgbm_land_demand_v2.txt)는 건드리지 않고 별도 저장(lgbm_land_demand_v2comfort.txt).
honest 비교는 `_ab_comfort_eval.py`.
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
# v2 BASEFEAT 에서 temp_c·wind_spd 제거 → temp_c4·di·wct + 구름·cap 추가
FEAT = ([f for f in expf.BASEFEAT if f not in ('temp_c', 'wind_spd')]
        + ['temp_c4', 'di', 'wct', 'total_cloud', 'midlow_cloud', 'cap_btmppa'])


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
    m.save_model(os.path.join(MODELS, 'lgbm_land_demand_v2comfort.txt'), num_iteration=best)

    meta = dict(
        version='v2comfort', features=FEAT, categorical=['day_type'], target='real_demand_land',
        architecture='Global Model with Horizon Feature (h 피처, 1..360 direct = D+15)',
        loss='custom asymmetric L2 (낮09-15h & over-pred grad/hess ×alpha)', alpha=ALPHA,
        init_score=init, predict_note='pred = booster.predict(X) + init_score',
        changes_vs_v2='temp_c(5)->temp_c4(4,대관령제외) · wind_spd 제거 · di·wct 추가',
        stations=dict(temp_c4=expf.TEMP_SEL4, solar_rad=expf.SOLAR_SEL, cloud=expf.SOLAR_SEL,
                      comfort_TRHW=expf.TEMP_SEL4),
        best_iteration=best, origin_hour=23, train='target<=2024', val='2025',
        note='v2comfort: comfort(di·wct) 강화 실험. production v2 와 별도. 검증=_ab_comfort_eval.')
    json.dump(meta, open(os.path.join(MODELS, 'model_meta_v2comfort.json'), 'w', encoding='utf-8'),
              ensure_ascii=False, indent=2)
    print(f'saved lgbm_land_demand_v2comfort.txt  best_iter={best}  init_score={init:.1f}  alpha={ALPHA}')
    print('features:', FEAT)


if __name__ == '__main__':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass
    main()

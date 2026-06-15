# -*- coding: utf-8 -*-
"""7 v2 production 가스 재학습 — 5-A식 자기회귀 다지평 + MIXED 비율 + 낮 비대칭(α=4).

확정(2026-06-14, 사용자):
  구조 = Global Model with Horizon Feature (h, 1..288 direct, 가스 자기회귀).  현행 7-A2(동시점
         util)에서 전환 — 가스 자기상관(lag168 0.78)을 활용.
  피처 = real_demand_land(MW), renew_util(신재생만 비율-정규화), gas_lag168/lag24/rec24/rec168,
         h, hour, dow, doy.  (net_load·cap_btmppa·month·day_type 제외.  공선성·covariate shift 검토 G-18.)
  타깃 = 가스 MW (정상 stationary, ÷LNG_cap 은 100% 외삽 유발이라 미적용).
  손실 = 커스텀 L2 비대칭(낮09-15h & 과대 grad/hess ×4).  init_score=평균.
  학습 historical 2022-24 / val 2025.  평가/보정 = v2 체인 백테스트(horizon_backtest_v2.parquet).
명제용 드라이버-only 7-A 는 보존(검증목표). 구버전 7-A2(util) 도 보존(롤백).

산출: models/lgbm_land_gas_v2.txt + model_meta_gas_v2.json + gas_serving_calib.json 갱신(v2 지평별).
"""
from __future__ import annotations
import os, sys, json, importlib.util
import numpy as np, pandas as pd, lightgbm as lgb

HERE = os.path.dirname(os.path.abspath(__file__))


def _imp(name, path):
    s = importlib.util.spec_from_file_location(name, path); m = importlib.util.module_from_spec(s)
    s.loader.exec_module(m); return m


egr = _imp('egr', os.path.join(HERE, 'exp_gas_ratio.py'))
ega = _imp('ega', os.path.join(HERE, 'exp_gas_asym.py'))
CALIB_JSON = os.path.join(HERE, 'gas_serving_calib.json')
ALPHA = 4.0
FEAT = ega.MIXED_FEAT
HZ = [1, 2, 3, 7, 12]


def main():
    d = egr.load_cont(); samp = egr.build_samples(d)
    model, best = ega.train_asym(samp, ALPHA)          # Shifted(booster, init_score)
    booster, offset = model.m, model.off
    booster.save_model(os.path.join(HERE, 'lgbm_land_gas_v2.txt'), num_iteration=best)

    # 체인 백테스트로 보정 재적합 — 낮/밤 분리 지평별(전역 보정이 비대칭 낮교정을 푸는 것 방지).
    r = egr.eval_chain(model, best, FEAT, d, ratio=False)
    r['hr'] = pd.DatetimeIndex(r.timestamp).hour
    r['day'] = (r.hr >= 9) & (r.hr <= 15)
    by_h = {}        # 지평별 {day, night} 보정
    print('지평  calib(낮/밤)        보정후 전체 MAPE/bias')
    for n in HZ:
        lo, hi = egr.BLOCKS[n]
        g = r[(r.h >= lo) & (r.h <= hi)].dropna(subset=['gen_gas_kr']); g = g[g.gen_gas_kr > 0]
        cd = float(g[g.day].gen_gas_kr.sum() / g[g.day].pred.sum())
        cn = float(g[~g.day].gen_gas_kr.sum() / g[~g.day].pred.sum())
        by_h[str(n)] = {'day': round(cd, 5), 'night': round(cn, 5)}
        pc = np.where(g.day, g.pred * cd, g.pred * cn)
        mp = egr.mape(g.gen_gas_kr, pc); bi = egr.nbias(g.gen_gas_kr, pc)
        print(f'D+{n:>2}  {cd:.4f}/{cn:.4f}   {mp:.2f}% / {bi:+.2f}%')
    # 낮 계절별 최종(보정 후)
    def hblock(h):
        for n in HZ:
            lo, hi = egr.BLOCKS[n]
            if lo <= h <= hi:
                return n
        return np.nan
    r['blk'] = r.h.apply(hblock)
    r['cv'] = [by_h[str(int(b))]['day' if dy else 'night'] if pd.notna(b) else np.nan
               for b, dy in zip(r.blk, r.day)]
    print('\n낮(09-15) 계절 최종 — 낮/밤 분리 보정 후:')
    for s in ['겨울', '봄', '여름']:
        g = r[(r.season == s) & r.day].dropna(subset=['gen_gas_kr', 'cv']); g = g[g.gen_gas_kr > 0]
        print(f'  {s}낮: MAPE {egr.mape(g.gen_gas_kr, g.pred*g.cv):.2f}%  bias {egr.nbias(g.gen_gas_kr, g.pred*g.cv):+.2f}%')

    meta = dict(version='v2', features=FEAT, target='gen_gas_kr (MW)',
                architecture='Global+Horizon, 5-A식 가스 자기회귀 다지평(h 1..360 = D+15)',
                loss=f'custom asymmetric L2 (낮09-15h over-pred ×{ALPHA})', alpha=ALPHA,
                init_score=offset, predict_note='pred = booster.predict(X) + init_score',
                renew_util='renew_gen_total_kr / (solar_cap+wind_cap), kr_elec_capa.csv 월별',
                autoreg='gas_lag168(h>168 NaN)/lag24(h<=24)/rec24/rec168, historical 실측(가용=수요와 동일, 누수아님)',
                best_iteration=best, train='2022-2024', val='2025',
                note='7 v2: MIXED(신재생만 util)+자기회귀+낮비대칭. 구 7-A2(util) 보존. 명제는 7-A(드라이버only) 별도.')
    json.dump(meta, open(os.path.join(HERE, 'model_meta_gas_v2.json'), 'w', encoding='utf-8'),
              ensure_ascii=False, indent=2)

    # 보정 json 갱신 (이전 값 legacy 보존) — 낮/밤 분리 지평별
    old = json.load(open(CALIB_JSON, encoding='utf-8'))
    new = dict(bias_calib=by_h['1']['night'],            # 하위호환 스칼라(밤=다수 시간)
               bias_calib_by_horizon_daypart=by_h,       # {horizon: {day, night}}
               bias_calib_prev_7A2util=old.get('bias_calib_by_horizon'),
               bias_calib_legacy_climatology=old.get('bias_calib_legacy_climatology'),
               derivation='v2 가스모델(자기회귀 MW + MIXED + 낮비대칭 α4) 체인 백테스트 Σ실측/Σ예측을 '
                          '낮(09-15h)/밤 분리·지평별로 적합(전역 보정이 비대칭 낮교정을 푸는 것 방지). '
                          'prev_7A2util=구 util×cap 모델 보정(보존).',
               apply='gen_gas_pred = (booster.predict + init_score) × calib(dayahead, daypart). MW 직접.',
               conv_ton_per_mwh=old.get('conv_ton_per_mwh', 0.1521))
    json.dump(new, open(CALIB_JSON, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
    print(f'\nsaved lgbm_land_gas_v2.txt (best_iter {best}, offset {offset:.0f}, alpha {ALPHA})')
    print('calib 갱신:', by_h)


if __name__ == '__main__':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass
    main()

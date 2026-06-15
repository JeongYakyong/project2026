# -*- coding: utf-8 -*-
"""Phase 2 — 가스 bias 보정 지평별 재적합 (실예보 백테스트 기반).

진단(Phase 1)에서 가스 bias 가 지평에 따라 +4%(D+1)→+7.6%(D+12)로 커져 단일 계수(0.96509,
기후값 프록시 val2025 산출)로는 못 잡는 게 드러났다.  horizon_backtest.parquet(실예보)에서
지평별 보정 계수 = Σ(실측 gen_gas_kr)/Σ(보정전 발전량 raw=util×cap) 로 재적합한다.

보정 기준 = 송출량(물량) → 합계 unbiased(에너지가중).  D+4/5/6 등 미적합 지평은 서빙에서
지평 선형보간(serve_land_gas._calib_for_dayahead).  freshest forecast 서빙은 근지평(D+1) 적용.

gas_serving_calib.json 갱신: 옛 단일 계수는 bias_calib_legacy_climatology 로 보존.
"""
from __future__ import annotations
import os, sys, json
import numpy as np, pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
RT = os.path.join(HERE, 'horizon_backtest.parquet')
CALIB_JSON = os.path.join(HERE, '..', 'model', 'gas_serving_calib.json')
HZ = [1, 2, 3, 7, 12]


def main(write=True):
    r = pd.read_parquet(RT)
    old = json.load(open(CALIB_JSON, encoding='utf-8'))
    by_h = {}
    print('지평  n      calib       합계bias후   MAPE후')
    for n in HZ:
        g = r[r.horizon == n].dropna(subset=['gen_gas_kr'])
        g = g[g.gen_gas_kr > 0]
        raw = g.est_gas_gen_raw.values; act = g.gen_gas_kr.values
        c = float(act.sum() / raw.sum())
        by_h[str(n)] = round(c, 5)
        sumbias = (raw * c).sum() / act.sum() - 1
        mape = np.mean(np.abs(act - raw * c) / act) * 100
        print(f'D+{n:>2}  {len(g):>5}   {c:.5f}    {sumbias*100:+.2f}%      {mape:.2f}%')

    new = {
        'bias_calib': by_h['1'],                         # 하위호환 스칼라 = 근지평(D+1)
        'bias_calib_by_horizon': by_h,                   # 지평별(서빙에서 보간 적용)
        'bias_calib_legacy_climatology': old.get('bias_calib'),
        'derivation': ('지평별 Σ(실측 gen_gas_kr)/Σ(util×LNG_cap) — horizon_backtest.parquet '
                       '(실예보 forecast_horizon, 2025-12~2026-06, 181 base). 옛 단일계수는 '
                       'val2025 기후값 프록시 산출이라 legacy 로 보존.'),
        'apply': ('gen_gas_pred = util × LNG_cap × calib(dayahead). dayahead 미적합 지평은 '
                  'serve_land_gas._calib_for_dayahead 가 선형보간. freshest forecast=근지평(D+1).'),
        'conv_ton_per_mwh': old.get('conv_ton_per_mwh', 0.1521),
    }
    print('\n신 json:'); print(json.dumps(new, ensure_ascii=False, indent=2))
    if write:
        json.dump(new, open(CALIB_JSON, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
        print('\nsaved', CALIB_JSON)
    else:
        print('\n(dry-run — 저장 생략)')


if __name__ == '__main__':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass
    main(write='--dry' not in sys.argv)

# -*- coding: utf-8 -*-
"""post-hoc (계절×시각×지평구간) bias 보정표 생성 → lt_dir/calib_lt.json.

est_horizon_land_new(patchtst_lt) 의 **미보정** 예측 vs historical 실측에서
c[(season,hour,hgrp5)] = median(actual/pred) 를 구해 곱셈 보정계수로 저장. serve 가 로드해 적용.
held-out 교차검증으로 일반화·과적합없음 확인(지평15는 과적합 → 5구간이 최적). 데이터 쌓이면 재실행 갱신.
★ 반드시 미보정 서빙 결과로 빌드(보정표 빼고 serve 후 실행). 보정본으로 빌드하면 이중보정.
"""
import os, sqlite3, json, argparse
import numpy as np, pandas as pd
import model_lt as M

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.normpath(os.path.join(HERE, '..', '..', '..', '1. data_fetcher_and_db', 'data', 'input_data_land.db'))
SEASON = M.SEASON
CLAMP = (0.90, 1.10)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--lt-dir', default=os.path.join(HERE, 'weights'))
    ap.add_argument('--model', default='patchtst_lt')
    args = ap.parse_args()
    with sqlite3.connect(DB) as con:
        p = pd.read_sql("SELECT timestamp, horizon_d, est_demand_land AS pred FROM est_horizon_land_raw WHERE model=?",
                        con, params=(args.model,), parse_dates=['timestamp'])
        act = pd.read_sql("SELECT timestamp, real_demand_land AS act FROM historical", con, parse_dates=['timestamp'])
    d = p.merge(act, on='timestamp', how='inner')
    d = d[(d.act > 0) & d.pred.notna() & (d.pred > 0)].copy()
    d['key'] = [M.calib_key(t.month, t.hour, int(n)) for t, n in zip(d.timestamp, d.horizon_d)]
    d['r'] = d.act / d.pred
    g = d.groupby('key')['r'].median().clip(*CLAMP)
    calib = {k: round(float(v), 4) for k, v in g.items()}
    out = os.path.join(args.lt_dir, 'calib_lt.json')
    with open(out, 'w', encoding='utf-8') as f:
        json.dump(calib, f, ensure_ascii=False, indent=0)
    print(f'wrote {out}  ({len(calib)} 셀, n={len(d)})  표본범위 {d.timestamp.min()} .. {d.timestamp.max()}')
    ex = {k: calib[k] for k in ['겨울_13_초단', '겨울_13_장', '여름_13_장'] if k in calib}
    print('보정계수 예(겨울13시 초단/장, 여름13시 장):', ex)


if __name__ == '__main__':
    main()

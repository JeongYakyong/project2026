# -*- coding: utf-8 -*-
"""7-A2-A — 가스 모델을 '서빙(예보) 입력'으로 재학습(A안) + 지평별 검증.

기존 7-A2는 실측(real_demand_land, renew_gen_total_kr)으로 학습 → 서빙은 예보라 train-serve 불일치.
여기서는 build_chained_dataset.py 가 만든 체인 입력(est_demand, est_renew)으로 동일 7-A2 레시피를 재학습한다.

비교 3종 (test 2026, 지평별 D+1/2/3/7/12, 타깃 실측 gen_gas_kr):
  (1) 7-A2-A   : 체인입력 학습 → 체인입력 평가   (train-serve 일관)
  (2) 7-A2(구) : 실측 학습      → 체인입력 평가   (현행, 불일치)
  (3) ORACLE   : 7-A2(구) 실측 학습 → 실측입력 평가 (도달 불가 상한, 참고)

모델: 7-A2 동일 (util=gen_gas_kr/LNG_cap, ×용량 복원, LGBM L1). 풀드(전 지평 stack) 단일 가스모델.
"""
from __future__ import annotations
import os, sys, json
import numpy as np, pandas as pd, lightgbm as lgb
from sklearn.metrics import mean_absolute_error, r2_score

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, '..', '..'))
SD = os.path.join(ROOT, '1. data_fetcher_and_db', 'second_dataset')
DB = os.path.join(ROOT, '1. data_fetcher_and_db', 'data', 'input_data_land.db')
PARQUET = os.path.join(HERE, 'chained_gas_dataset.parquet')
OLD_UTIL = os.path.join(ROOT, '7. land_gas_forecaster', 'model', 'lgbm_land_gas_util.txt')
OUT_MODEL = os.path.join(ROOT, '7. land_gas_forecaster', 'model', 'lgbm_land_gas_util_chained.txt')
OUT_META  = os.path.join(ROOT, '7. land_gas_forecaster', 'model', 'model_meta_util_chained.json')

HORIZONS = [1, 2, 3, 7, 12]
DTCATS = ['holiday', 'weekday', 'weekend']
CAT = ['day_type']
NUM_CHAIN = ['est_demand', 'est_renew', 'hour', 'dow', 'month', 'doy']
FEATS_CHAIN = NUM_CHAIN + CAT
# 구 모델이 기대하는 피처명(실측 학습)
NUM_OLD = ['real_demand_land', 'renew_gen_total_kr', 'hour', 'dow', 'month', 'doy']
FEATS_OLD = NUM_OLD + CAT

PARAMS = dict(objective='regression_l1', n_estimators=2000, learning_rate=0.03, num_leaves=63,
              min_child_samples=50, subsample=0.8, subsample_freq=1, colsample_bytree=0.8,
              random_state=42, n_jobs=-1, verbose=-1)


def load_lng_cap():
    cap = pd.read_csv(os.path.join(SD, 'kr_elec_capa.csv'), encoding='euc-kr').rename(
        columns={'기간': 'period', '지역': 'region', 'LNG': 'LNG_cap'})
    cap = cap[cap['region'] == '합계'].copy()
    cap['ym'] = pd.to_datetime(cap['period'], format='%b-%y').dt.to_period('M')
    cap['LNG_cap'] = pd.to_numeric(cap['LNG_cap'], errors='coerce')
    return cap[['ym', 'LNG_cap']].dropna().sort_values('ym').set_index('ym')['LNG_cap']


def metrics(y, p):
    y, p = np.asarray(y, float), np.asarray(p, float)
    m = y > 0
    return dict(MAE=mean_absolute_error(y, p),
                MAPE=float(np.mean(np.abs((y[m]-p[m])/y[m]))*100),
                R2=r2_score(y, p),
                bias=float(np.mean((p[m]-y[m])/y[m])*100))


def main():
    df = pd.read_parquet(PARQUET)
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    df['ym'] = df['timestamp'].dt.to_period('M')
    lng = load_lng_cap()
    full_ym = pd.period_range(df['ym'].min(), df['ym'].max(), freq='M')
    lng = lng.reindex(full_ym).ffill()
    df['LNG_cap'] = df['ym'].map(lng)
    df = df.dropna(subset=['LNG_cap', 'gen_gas_kr', 'est_demand', 'est_renew']).copy()
    df = df[df['gen_gas_kr'] > 0]
    df['util'] = df['gen_gas_kr'] / df['LNG_cap']
    df['day_type'] = pd.Categorical(df['day_type'], categories=DTCATS)

    tr = df[df.split == 'train']; va = df[df.split == 'val']; te = df[df.split == 'test']
    print('체인 데이터셋:', {k: int(v) for k, v in df.groupby('split').size().items()})
    print('test 지평별:', {int(k): int(v) for k, v in te.groupby('horizon').size().items()})

    # (1) 7-A2-A: 체인입력으로 util 재학습 (풀드)
    mA = lgb.LGBMRegressor(**PARAMS)
    mA.fit(tr[FEATS_CHAIN], tr['util'], eval_set=[(va[FEATS_CHAIN], va['util'])], eval_metric='l1',
           categorical_feature=CAT, callbacks=[lgb.early_stopping(100, verbose=False)])

    # (2) 구 7-A2 (실측 학습) 로드
    mOld = lgb.Booster(model_file=OLD_UTIL)

    # 실측 입력 (ORACLE 평가용): historical 에서 te 타깃 시점 real_demand/renew 조인
    import sqlite3
    with sqlite3.connect(DB) as con:
        act = pd.read_sql('SELECT timestamp, real_demand_land, renew_gen_total_kr FROM historical',
                          con, parse_dates=['timestamp']).set_index('timestamp')
    te = te.copy()
    te['real_demand_land'] = act['real_demand_land'].reindex(te['timestamp']).values
    te['renew_gen_total_kr'] = act['renew_gen_total_kr'].reindex(te['timestamp']).values

    def pred_chain_new(g):   # 7-A2-A
        return mA.predict(g[FEATS_CHAIN]) * g['LNG_cap'].values
    def pred_chain_old(g):   # 구모델 + 체인입력 (이름만 맞춰 투입)
        X = g[['est_demand', 'est_renew', 'hour', 'dow', 'month', 'doy', 'day_type']].copy()
        X.columns = FEATS_OLD
        return mOld.predict(X) * g['LNG_cap'].values
    def pred_oracle(g):      # 구모델 + 실측입력
        X = g[FEATS_OLD].copy()
        return mOld.predict(X) * g['LNG_cap'].values

    print('\n=== test 2026 지평별 gen_gas_kr 정확도 (MAPE% / bias% / R2) ===')
    print(f'{"지평":>5} | {"(1)7-A2-A 체인학습":>22} | {"(2)구7-A2+체인입력":>22} | {"(3)ORACLE 실측":>20}')
    summary = []
    for n in HORIZONS:
        g = te[te.horizon == n]
        if not len(g):
            continue
        y = g['gen_gas_kr'].values
        m1 = metrics(y, pred_chain_new(g))
        m2 = metrics(y, pred_chain_old(g))
        og = g.dropna(subset=['real_demand_land', 'renew_gen_total_kr'])
        m3 = metrics(og['gen_gas_kr'].values, pred_oracle(og))
        print(f'D+{n:>3} | {m1["MAPE"]:6.2f} {m1["bias"]:+6.1f} {m1["R2"]:5.2f} | '
              f'{m2["MAPE"]:6.2f} {m2["bias"]:+6.1f} {m2["R2"]:5.2f} | '
              f'{m3["MAPE"]:6.2f} {m3["bias"]:+6.1f} {m3["R2"]:5.2f}')
        summary.append(dict(horizon=n, new=m1, old=m2, oracle=m3))

    # 저장
    mA.booster_.save_model(OUT_MODEL, num_iteration=mA.best_iteration_)
    meta = dict(features=FEATS_CHAIN, target='util(=gen_gas_kr/LNG_cap)', restore='pred_util × LNG_cap',
                train_inputs='chained serving (est_demand 5-A2, est_renew 6단계, 지평 stack pooled)',
                window='train 2022-2024 / val 2025 / test 2026', horizons=HORIZONS,
                best_iteration=int(mA.best_iteration_),
                summary={f'D+{s["horizon"]}': {'new': {k: round(v, 3) for k, v in s['new'].items()},
                                               'old_on_chain': {k: round(v, 3) for k, v in s['old'].items()},
                                               'oracle': {k: round(v, 3) for k, v in s['oracle'].items()}}
                         for s in summary})
    json.dump(meta, open(OUT_META, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
    print('\nsaved', OUT_MODEL)
    print('saved', OUT_META)


if __name__ == '__main__':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass
    main()

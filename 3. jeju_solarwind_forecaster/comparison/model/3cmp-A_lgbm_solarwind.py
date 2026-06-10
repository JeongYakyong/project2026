"""3cmp-A — solar/wind 이용률 LGBM 학습 (순수기상 horizon-무관 단일모델).

피처 확정(사용자 §0.6, 2026-06-08):
  SOLAR(final): solar_rad·total_cloud·midlow_cloud·solar_damping(west·south)
              + clearsky_rad_ratio(west·south, 흐린날 명시) + hour sin/cos + month sin/cos
  SOLAR(ablation=PatchTST 동일): 위에서 clearsky_ratio·month 제거
  WIND(final): wind_spd·wind_zone(west·east) + 풍향(west sin/cos) + hour sin/cos + year sin/cos

학습창: train ≤2024 / val 2025 / test 2026.
순수기상 horizon-무관: 이용률=f(기상,시각,계절)만 → h 미사용(D+1~D+6 동일 적용).
산출: model/lgbm_solar_util.txt, lgbm_solar_util_ablation.txt, lgbm_wind_util.txt,
      model/clearsky_clim.csv (clearsky 평년, train 기준), model/feat_meta.json.
공개 함수 build_features() 는 비교 하니스(3cmp-B)에서 재사용.
"""
import os, json
import numpy as np
import pandas as pd
import lightgbm as lgb

HERE = os.path.dirname(os.path.abspath(__file__))
CMP  = os.path.normpath(os.path.join(HERE, '..'))
CSV  = os.path.normpath(os.path.join(CMP, '..', 'training', 'solarwind_raw_jeju.csv'))
SU, WU = 'real_solar_utilization_jeju', 'real_wind_utilization_jeju'

SOLAR_FINAL = ['solar_rad_west', 'solar_rad_south', 'total_cloud_west', 'total_cloud_south',
               'midlow_cloud_west', 'midlow_cloud_south', 'solar_damping_west', 'solar_damping_south',
               'clearsky_ratio_west', 'clearsky_ratio_south',
               'hour_sin', 'hour_cos', 'month_sin', 'month_cos']
SOLAR_ABLATION = ['solar_rad_west', 'solar_rad_south', 'total_cloud_west', 'total_cloud_south',
                  'midlow_cloud_west', 'midlow_cloud_south', 'solar_damping_west', 'solar_damping_south',
                  'hour_sin', 'hour_cos']
WIND_FINAL = ['wind_spd_west', 'wind_spd_east', 'wind_zone_west', 'wind_zone_east',
              'wd_sin_west', 'wd_cos_west', 'hour_sin', 'hour_cos', 'year_sin', 'year_cos']

WIND_SPD_CAP, CUTOFF = 20.0, 25.0


def _wind_zone(raw):
    cond = [raw < 15, (raw >= 15) & (raw < 20), (raw >= 20) & (raw < CUTOFF), raw >= CUTOFF]
    return np.select(cond, [0.0, 1.0, 0.5, 0.0], default=0.0)


def _damping(df, st):
    daily = df.groupby(df.index.date)[f'rainfall_{st}'].transform(
        lambda x: x.between_time('06:00', '20:00').sum())
    return np.exp(-0.163 * daily.clip(upper=10))


def build_features(df, clim=None):
    """raw CSV/DB 프레임 → 피처 컬럼 추가. clim=None이면 train으로 clearsky 평년 산출·반환."""
    df = df.copy()
    df['hour_sin'] = np.sin(2 * np.pi * df.index.hour / 24)
    df['hour_cos'] = np.cos(2 * np.pi * df.index.hour / 24)
    df['month_sin'] = np.sin(2 * np.pi * df.index.month / 12)
    df['month_cos'] = np.cos(2 * np.pi * df.index.month / 12)
    df['year_sin'] = np.sin(2 * np.pi * df.index.dayofyear / 365)
    df['year_cos'] = np.cos(2 * np.pi * df.index.dayofyear / 365)
    for st in ['west', 'south']:
        df[f'solar_damping_{st}'] = _damping(df, st)
    for st in ['west', 'east']:
        df[f'wind_zone_{st}'] = _wind_zone(df[f'wind_spd_{st}'])
        df[f'wind_spd_{st}'] = df[f'wind_spd_{st}'].clip(upper=WIND_SPD_CAP)
    # clearsky_ratio: (month,hour)별 train rad 90분위 평년 대비
    if clim is None:
        clim = {}
        for st in ['west', 'south']:
            g = df.groupby([df.index.month, df.index.hour])[f'solar_rad_{st}'].quantile(0.90)
            clim[st] = g
    for st in ['west', 'south']:
        key = list(zip(df.index.month, df.index.hour))
        cs = clim[st].reindex(key).values
        ratio = np.where(cs > 0.05, df[f'solar_rad_{st}'].values / cs, 0.0)
        df[f'clearsky_ratio_{st}'] = np.clip(ratio, 0, 1.5)
    return df, clim


def main():
    df = pd.read_csv(CSV, parse_dates=['timestamp']).set_index('timestamp').sort_index()
    df = df.apply(pd.to_numeric, errors='coerce')
    df['year'] = df.index.year
    tr = df[df.year <= 2024]
    feat_tr, clim = build_features(tr)
    feat_all, _ = build_features(df, clim=clim)
    feat_all['split'] = np.where(feat_all.index.year <= 2024, 'train',
                        np.where(feat_all.index.year == 2025, 'val', 'test'))

    # clearsky 평년 저장
    cs_df = pd.concat({st: clim[st] for st in clim}, axis=1)
    cs_df.columns = [f'clearsky90_{c}' for c in cs_df.columns]
    cs_df.to_csv(os.path.join(HERE, 'clearsky_clim.csv'))

    params = dict(objective='regression_l1', n_estimators=1200, learning_rate=0.03,
                  num_leaves=63, min_child_samples=80, subsample=0.8, subsample_freq=1,
                  colsample_bytree=0.8, reg_lambda=1.0, verbose=-1)

    def fit(feats, target, name):
        tr_m = feat_all[feat_all.split == 'train']
        va_m = feat_all[feat_all.split == 'val']
        Xtr, ytr = tr_m[feats], tr_m[target]
        Xva, yva = va_m[feats], va_m[target]
        m = lgb.LGBMRegressor(**params)
        m.fit(Xtr, ytr, eval_set=[(Xva, yva)],
              callbacks=[lgb.early_stopping(60, verbose=False)])
        m.booster_.save_model(os.path.join(HERE, name))
        imp = pd.Series(m.booster_.feature_importance('gain'), index=feats).sort_values(ascending=False)
        print(f'\n[{name}] best_iter={m.best_iteration_}  중요도(gain) top:')
        print((imp / imp.sum()).round(3).head(8).to_string())
        return m

    print('=' * 60); print('LGBM 학습 (train ≤2024 / val 2025, early stop)')
    m_solar = fit(SOLAR_FINAL, SU, 'lgbm_solar_util.txt')
    m_solar_abl = fit(SOLAR_ABLATION, SU, 'lgbm_solar_util_ablation.txt')
    m_wind = fit(WIND_FINAL, WU, 'lgbm_wind_util.txt')

    json.dump({'SOLAR_FINAL': SOLAR_FINAL, 'SOLAR_ABLATION': SOLAR_ABLATION,
               'WIND_FINAL': WIND_FINAL, 'target_solar': SU, 'target_wind': WU},
              open(os.path.join(HERE, 'feat_meta.json'), 'w'), ensure_ascii=False, indent=2)

    # ---- test 이용률 평가 (perfect weather, horizon-무관) ----
    te = feat_all[feat_all.split == 'test'].copy()
    te['pred_solar'] = np.clip(m_solar.predict(te[SOLAR_FINAL]), 0, 1)
    te['pred_solar_abl'] = np.clip(m_solar_abl.predict(te[SOLAR_ABLATION]), 0, 1)
    te['pred_wind'] = np.clip(m_wind.predict(te[WIND_FINAL]), 0, 1)

    # 낮시간(태양광) + 흐림 regime
    day = te[(te.index.hour >= 8) & (te.index.hour <= 17)].copy()
    day_cloud = day.groupby(day.index.date)['total_cloud_west'].mean()
    cloudy = set(day_cloud[day_cloud >= 0.7].index); sunny = set(day_cloud[day_cloud <= 0.3].index)
    day['regime'] = np.where([d in cloudy for d in day.index.date], 'cloudy',
                    np.where([d in sunny for d in day.index.date], 'sunny', 'mixed'))

    def util_metrics(frame, pred, true):
        e = frame[pred] - frame[true]
        return dict(MAE=round(e.abs().mean(), 4), bias=round(e.mean(), 4),
                    n=len(frame))

    print('\n' + '=' * 60); print('[SOLAR 이용률 test 2026, 낮 8-17h] LGBM(final) vs LGBM(ablation)')
    rows = []
    for r in ['sunny', 'mixed', 'cloudy', 'ALL']:
        sub = day if r == 'ALL' else day[day.regime == r]
        rows.append(dict(regime=r, **{f'final_{k}': v for k, v in util_metrics(sub, 'pred_solar', SU).items()},
                         abl_bias=round((sub['pred_solar_abl'] - sub[SU]).mean(), 4),
                         abl_MAE=round((sub['pred_solar_abl'] - sub[SU]).abs().mean(), 4)))
    sm = pd.DataFrame(rows); print(sm.to_string(index=False))
    sm.to_csv(os.path.join(CMP, 'tab', '3cmp-A_solar_util_test.csv'), index=False)

    print('\n[WIND 이용률 test 2026, 전시간]')
    print(util_metrics(te, 'pred_wind', WU))
    print('\n학습·평가 완료.')


if __name__ == '__main__':
    main()

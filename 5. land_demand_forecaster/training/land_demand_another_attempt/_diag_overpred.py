# -*- coding: utf-8 -*-
"""단기 과대예측 진단: pred 과대가 anchor / climatology / 모델잔차 중 어디서 오나.
지평별로 target 마다 anchor·clim·pred·actual 의 bias 를 분해. 낮/밤·계절·시각별.
"""
import os, sqlite3
import numpy as np, pandas as pd, joblib
import model_lt as M

DB = os.path.normpath(os.path.join(os.getcwd(), '..', '..', '..', '1. data_fetcher_and_db', 'data', 'input_data_land.db'))
LT = 'landdemand_lt v2'
clim_meta = joblib.load(os.path.join(LT, 'metadata_lt.pkl'))['CLIM']

feat = M.build_features(M._load_raw(DB))
dem = feat['Demand'].values.astype(float)
idx = feat.index
is_hol = feat['is_holiday'].values; is_wkd = feat['is_weekend'].values
# 전구간 clim
dcode = M.daytype_code(is_wkd, is_hol)
clim_all = M.apply_climatology(idx.month.values, idx.hour.values, dcode, clim_meta)
pos = {t: i for i, t in enumerate(idx)}

con = sqlite3.connect(DB)
pred = pd.read_sql("SELECT base, timestamp, horizon_d, est_demand_land AS pred FROM est_horizon_land_new "
                   "WHERE model='patchtst_lt'", con, parse_dates=['timestamp'])

SEASON = {12: '겨울', 1: '겨울', 2: '겨울', 3: '봄', 4: '봄', 5: '봄', 6: '여름', 7: '여름', 8: '여름'}


def biaspct(a, b):
    m = np.isfinite(a) & np.isfinite(b) & (b > 0)
    return np.mean((a[m] - b[m]) / b[m]) * 100 if m.any() else np.nan


# anchor 전구간(지평별 캐시)
anc_cache = {}
def anchor_for(n):
    if n not in anc_cache:
        anc_cache[n] = M.compute_anchor(dem, is_hol, is_wkd, M.HORIZONS[n])
    return anc_cache[n]

rows = []
for n in [1, 2, 3, 5]:
    a_ser = anchor_for(n)
    sub = pred[pred.horizon_d == n].copy()
    ii = sub.timestamp.map(pos)
    ok = ii.notna()
    sub = sub[ok]; ii = ii[ok].astype(int).values
    act = dem[ii]; anc = a_ser[ii]; cl = clim_all[ii]; pr = sub.pred.values
    hour = sub.timestamp.dt.hour.values
    seas = sub.timestamp.dt.month.map(SEASON).values
    for label, mask in [('전체', np.ones(len(sub), bool)),
                        ('낮09-15', (hour >= 9) & (hour <= 15)),
                        ('밤', ~((hour >= 9) & (hour <= 15)))]:
        rows.append((n, label, len(act[mask]),
                     biaspct(anc[mask], act[mask]), biaspct(cl[mask], act[mask]), biaspct(pr[mask], act[mask])))

print("지평·구간별 bias(%) — anchor / climatology / pred (양수=과대)")
print("지평 | 구간      |   n   | anchor | clim  | pred")
print("-" * 56)
for n, lab, c, ab, cb, pb in rows:
    print(f"D+{n:<2} | {lab:<8} | {c:>5} | {ab:>+5.1f} | {cb:>+5.1f} | {pb:>+5.1f}")

# 낮 시각별(D+1) — 태양광 억제 시간대(정오) 집중 여부
print("\n[D+1 낮 시각별 bias] (정오 집중이면 태양광 성장 신호)")
a1 = anchor_for(1); s1 = pred[pred.horizon_d == 1].copy()
ii = s1.timestamp.map(pos); ok = ii.notna(); s1 = s1[ok]; ii = ii[ok].astype(int).values
act = dem[ii]; anc = a1[ii]; cl = clim_all[ii]; pr = s1.pred.values; hh = s1.timestamp.dt.hour.values
print("시각 | anchor | clim  | pred")
for h in range(8, 19):
    m = hh == h
    if m.sum():
        print(f"{h:>2}시 | {biaspct(anc[m],act[m]):>+5.1f} | {biaspct(cl[m],act[m]):>+5.1f} | {biaspct(pr[m],act[m]):>+5.1f}")

# 계절별 D+1 pred bias (겨울 과대 확인)
print("\n[D+1 계절별 pred bias]")
for s in ['겨울', '봄', '여름']:
    m = (s1.timestamp.dt.month.map(SEASON).values == s)
    if m.sum():
        print(f"{s} | anchor {biaspct(anc[m],act[m]):>+5.1f} | clim {biaspct(cl[m],act[m]):>+5.1f} | pred {biaspct(pr[m],act[m]):>+5.1f}")

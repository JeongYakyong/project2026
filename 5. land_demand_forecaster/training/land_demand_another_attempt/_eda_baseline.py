# -*- coding: utf-8 -*-
"""1차 baseline 비교: 달력-only PatchTST(=기후값) vs anchor(daytype_match).

'달력·시간만 받는 신경망'의 출력 상한 = 달력 조건부 평균(climatology).
train(<2025) 에서 (month,hour,daytype) 평균을 학습 → 최근 1년 평가.
anchor 는 지평에 따라 늙지만, climatology 는 지평 무관(달력은 항상 known) 정적.
"""
import math
import numpy as np, pandas as pd
import model_lt as M

feat = M.build_features(pd.read_csv('land_demand_train.csv'))
dem = feat['Demand'].values.astype(float)
idx = feat.index
N = len(dem)
hour = idx.hour.values
is_hol = feat['is_holiday'].values.astype(bool)
is_wkd = feat['is_weekend'].values.astype(bool)

# day_type: 0 평일 / 1 주말 / 2 공휴일
dtype = np.where(is_hol, 2, np.where(is_wkd, 1, 0))
month = idx.month.values

tr = idx < '2025-01-01'
recent = idx >= (idx.max() - pd.Timedelta(days=365))
isday = (hour >= 9) & (hour <= 20)

# ── climatology: train 의 (month,hour,daytype) 평균 ──
g = pd.DataFrame({'m': month[tr], 'h': hour[tr], 'd': dtype[tr], 'y': dem[tr]})
table = g.groupby(['m', 'h', 'd'])['y'].mean()
gl_hd = g.groupby(['h', 'd'])['y'].mean()      # 폴백
clim = np.full(N, np.nan)
for i in range(N):
    key = (month[i], hour[i], dtype[i])
    if key in table.index:
        clim[i] = table[key]
    elif (hour[i], dtype[i]) in gl_hd.index:
        clim[i] = gl_hd[(hour[i], dtype[i])]


# ── anchor: daytype_match (확정 설계) ──
def lag(Lh):
    t = np.arange(N); src = t - Lh
    a = np.full(N, np.nan); ok = src >= 0; a[ok] = dem[src[ok]]
    return a

def w0_of(n):
    return max(1, math.ceil(((n - 1) * 24 + 24) / 168))

def daytype_match(n, K=8):
    w0 = w0_of(n); picks = []
    for j in range(K):
        Lh = 168 * (w0 + j); a = lag(Lh); src = np.arange(N) - Lh; ok = src >= 0
        match = np.zeros(N, bool)
        match[ok] = (is_hol[src[ok]] == is_hol[ok]) & (is_wkd[src[ok]] == is_wkd[ok])
        picks.append(np.where(match, a, np.nan))
    stack = np.vstack(picks); out = np.full(N, np.nan)
    for t in range(N):
        col = stack[:, t]; v = col[np.isfinite(col)][:2]
        if len(v): out[t] = v.mean()
    return out


def stat(a, sel):
    m = sel & np.isfinite(a) & (dem > 0)
    if m.sum() == 0: return np.nan, np.nan
    e = (a[m] - dem[m]) / dem[m]
    return float(np.mean(np.abs(e)) * 100), float(np.mean(e) * 100)


print(f"평가창 최근 1년: {idx[recent].min()} .. {idx.max()}   (셀 = MAPE / bias)")
print("\nclimatology(달력-only 1차 best-case)는 지평 무관 = 상수")
mp, bi = stat(clim, recent);      print(f"  climatology 전체 : {mp:5.2f}/{bi:+.1f}")
mp, bi = stat(clim, recent & isday); print(f"  climatology 낮   : {mp:5.2f}/{bi:+.1f}")
mp, bi = stat(clim, recent & ~isday);print(f"  climatology 밤   : {mp:5.2f}/{bi:+.1f}")

print("\nanchor(daytype_match) — 지평별:")
print("지평 |   전체        낮          밤")
for n in [1, 2, 3, 5, 8, 11, 15]:
    a = daytype_match(n)
    o = stat(a, recent); d = stat(a, recent & isday); ni = stat(a, recent & ~isday)
    print(f"D+{n:<2} | {o[0]:5.2f}/{o[1]:+4.1f}  {d[0]:5.2f}/{d[1]:+4.1f}  {ni[0]:5.2f}/{ni[1]:+4.1f}")

# -*- coding: utf-8 -*-
"""anchor 레벨 구성 업그레이드: 단기=최근 anchor, 장기=기후값 블렌드.

anchor_blend(n) = (1-w_n)*daytype_match(n) + w_n*climatology,  w_n 은 지평에 따라 0→상한 램프.
단일 신경망 구조 그대로, 1차 baseline 만 더 안정적으로. honest(둘 다 origin 이전 정보).
"""
import math
import numpy as np, pandas as pd
import model_lt as M

feat = M.build_features(pd.read_csv('land_demand_train.csv'))
dem = feat['Demand'].values.astype(float)
idx = feat.index; N = len(dem)
hour = idx.hour.values
is_hol = feat['is_holiday'].values.astype(bool)
is_wkd = feat['is_weekend'].values.astype(bool)
dtype = np.where(is_hol, 2, np.where(is_wkd, 1, 0)); month = idx.month.values
tr = idx < '2025-01-01'
recent = idx >= (idx.max() - pd.Timedelta(days=365))
isday = (hour >= 9) & (hour <= 20)

g = pd.DataFrame({'m': month[tr], 'h': hour[tr], 'd': dtype[tr], 'y': dem[tr]})
table = g.groupby(['m', 'h', 'd'])['y'].mean(); gl_hd = g.groupby(['h', 'd'])['y'].mean()
clim = np.array([table.get((month[i], hour[i], dtype[i]),
                gl_hd.get((hour[i], dtype[i]), np.nan)) for i in range(N)])

def lag(Lh):
    src = np.arange(N) - Lh; a = np.full(N, np.nan); ok = src >= 0; a[ok] = dem[src[ok]]; return a
def w0_of(n): return max(1, math.ceil(((n - 1) * 24 + 24) / 168))
def daytype_match(n, K=8):
    w0 = w0_of(n); picks = []
    for j in range(K):
        Lh = 168 * (w0 + j); a = lag(Lh); src = np.arange(N) - Lh; ok = src >= 0
        match = np.zeros(N, bool); match[ok] = (is_hol[src[ok]] == is_hol[ok]) & (is_wkd[src[ok]] == is_wkd[ok])
        picks.append(np.where(match, a, np.nan))
    stack = np.vstack(picks); out = np.full(N, np.nan)
    for t in range(N):
        v = stack[:, t][np.isfinite(stack[:, t])][:2]
        if len(v): out[t] = v.mean()
    return out

def stat(a, sel):
    m = sel & np.isfinite(a) & (dem > 0)
    if m.sum() == 0: return np.nan
    e = (a[m] - dem[m]) / dem[m]; return float(np.mean(np.abs(e)) * 100)

# 지평별 블렌드 가중 w_n: D+1=0, 선형 증가, 상한 0.6 @ D>=12
def w_of(n, cap=0.6, start=4, full=12):
    if n <= start: return 0.0
    if n >= full: return cap
    return cap * (n - start) / (full - start)

print(f"평가창 최근 1년   (MAPE, 전체)")
print("지평 | anchor only | climatology | blend(램프) | 최적고정블렌드")
ac = {n: daytype_match(n) for n in [1,2,3,5,8,11,15]}
for n in [1, 2, 3, 5, 8, 11, 15]:
    a = ac[n]
    only = stat(a, recent)
    cl = stat(clim, recent)
    w = w_of(n); bl = stat((1 - w) * a + w * clim, recent)
    # 최적 고정 블렌드(0~0.9 그리드)
    best = min(((stat((1 - ww) * a + ww * clim, recent), ww) for ww in np.arange(0, 0.91, 0.1)))
    print(f"D+{n:<2} |   {only:5.2f}    |    {cl:5.2f}    |   {bl:5.2f}(w={w:.2f}) |  {best[0]:5.2f}(w*={best[1]:.1f})")

# -*- coding: utf-8 -*-
"""가벼운 EDA: 앵커(anchor) 설계가 단기 지평 손해의 원인인지 수치로 확인.

lt는 모델이 잔차 r=y-anchor 만 학습하므로, anchor 자체의 품질(특히 단기)이 성능 상한을 좌우.
현재 anchor = 1~2주 전 같은 시각 평균(주 단위 lag). 하지만 origin=base당일 23:00 이므로
'오늘(base당일) 같은 시각'(lag-24*n) 같은 더 최근 honest 기준도 쓸 수 있다.
지평별로 여러 honest anchor 후보의 anchor-only MAPE 를 비교한다(낮을수록 잔차가 작음=상한 좋음).
"""
import numpy as np, pandas as pd
import model_lt as M

df = pd.read_csv('land_demand_train.csv')
feat = M.build_features(df)
dem = feat['Demand'].values.astype(float)
idx = feat.index
N = len(dem)
hour = idx.hour.values
dow = idx.dayofweek.values

def mape(a, y):
    m = np.isfinite(a) & np.isfinite(y) & (y > 0)
    return float(np.mean(np.abs(a[m] - y[m]) / y[m]) * 100), int(m.sum())

# 타깃 t 의 honest 기준: origin O = (t의 base일) 23:00. base일 = t.day - n.
# lag L(h) 가 honest 하려면 t-L <= O  →  L >= 24n + hour(t) - 23.
def anchor_lag(n, Lh):
    """타깃마다 lag Lh 시간 전 수요. 범위 밖/결측은 NaN."""
    t = np.arange(N)
    src = t - Lh
    a = np.full(N, np.nan)
    ok = src >= 0
    a[ok] = dem[src[ok]]
    return a

def week_anchor(n):
    off = (n - 1) * 24
    import math
    w0 = max(1, math.ceil((off + 24) / 168)); w1 = w0 + 1
    return 0.5 * anchor_lag(n, 168 * w0) + 0.5 * anchor_lag(n, 168 * w1)

def today_anchor(n):
    """base당일 같은 시각(lag 24n). 가장 최근 honest 일단위 기준."""
    return anchor_lag(n, 24 * n)

def today2_anchor(n):
    """base당일 + 전일 평균(lag 24n, 24(n+1))."""
    return 0.5 * anchor_lag(n, 24 * n) + 0.5 * anchor_lag(n, 24 * (n + 1))

def dow_levelcorr(n):
    """주단위 same-DOW anchor 를 최근 수요레벨로 보정.
    factor = mean(base당일 24h) / mean(week anchor 가 참조한 그 주의 같은 24h).
    """
    w = week_anchor(n)
    # 최근 24h(base당일) 평균: lag 24n .. 24n+23 의 평균을 근사 → lag 24n anchor 의 일평균
    base_day = anchor_lag(n, 24 * n)
    # base당일 일평균 / (1주전 일평균) 로 레벨 비율
    wk_ago = anchor_lag(n, 24 * n + 168)
    # 시각별이 아니라 24h 이동평균으로 레벨만
    s = pd.Series(dem, index=idx)
    day_mean = s.shift(24 * n).rolling(24).mean().values
    wkago_mean = s.shift(24 * n + 168).rolling(24).mean().values
    fac = np.where((wkago_mean > 0) & np.isfinite(wkago_mean), day_mean / wkago_mean, 1.0)
    fac = np.clip(fac, 0.85, 1.15)
    return w * fac

cands = {
    'week(현재)': week_anchor,
    'today(lag24n)': today_anchor,
    'today2(24n,24n+24)': today2_anchor,
    'week*levelcorr': dow_levelcorr,
}

# 최근 1년만 평가(최근 분포에서의 anchor 품질)
recent = idx >= (idx.max() - pd.Timedelta(days=365))
isday = (hour >= 9) & (hour <= 20)

print(f"평가창: {idx[recent].min()} .. {idx.max()}  (최근 1년)")
print()
hs = [1, 2, 3, 5, 8, 11, 15]
header = "지평 | " + " | ".join(f"{k:>20}" for k in cands)
print(header); print("-" * len(header))
rows = {}
for n in hs:
    line = f"D+{n:<2} |"
    for k, fn in cands.items():
        a = fn(n)
        mp, cnt = mape(a[recent], dem[recent])
        line += f" {mp:>20.3f}"
        rows.setdefault(k, {})[n] = mp
    print(line)

print("\n[낮 09-20시만]")
print(header); print("-" * len(header))
for n in hs:
    line = f"D+{n:<2} |"
    sel = recent & isday
    for k, fn in cands.items():
        a = fn(n)
        mp, cnt = mape(a[sel], dem[sel])
        line += f" {mp:>20.3f}"
    print(line)

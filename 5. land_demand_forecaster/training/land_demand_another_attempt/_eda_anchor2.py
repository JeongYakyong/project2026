# -*- coding: utf-8 -*-
"""anchor 레벨 구성 EDA — Colab 재학습 전, 어떤 레벨 기준이 안전하게 더 좋은지 못 박기.

모델은 r=y-anchor 만 학습하므로 anchor 의 MAPE·**bias** 가 성능 상한·치우침을 좌우.
지평별·낮/밤·공휴일타깃 슬라이스로 여러 honest 레벨 구성을 비교한다.
모두 honest: 참조 lag(h) ≥ offset+24 → 타깃-lag ≤ origin(base당일 23:00).
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
s = pd.Series(dem, index=idx)


def lag(Lh):
    t = np.arange(N); src = t - Lh
    a = np.full(N, np.nan); ok = src >= 0; a[ok] = dem[src[ok]]
    return a


def w0_of(n):
    return max(1, math.ceil(((n - 1) * 24 + 24) / 168))


# ── 레벨 구성 후보 ──
def week2_mean(n):                      # 현재
    w0 = w0_of(n); return 0.5 * lag(168 * w0) + 0.5 * lag(168 * (w0 + 1))

def week_nearest(n):                    # 가장 가까운 same-DOW 1주만
    return lag(168 * w0_of(n))

def week_median_K(n, K=4):              # 가까운 K개 same-DOW 주 median(이상치/오염에 강함)
    w0 = w0_of(n)
    stack = np.vstack([lag(168 * (w0 + j)) for j in range(K)])
    return np.nanmedian(stack, axis=0)

def levelcorr(base_anchor, n):          # 일평균 레벨 비율로 보정(요일 형태 유지)
    day_mean = s.shift(24 * n).rolling(24).mean().values
    wk_ago = s.shift(24 * n + 168).rolling(24).mean().values
    fac = np.where((wk_ago > 0) & np.isfinite(wk_ago), day_mean / wk_ago, 1.0)
    return base_anchor * np.clip(fac, 0.85, 1.15)

def week2_levelcorr(n):
    return levelcorr(week2_mean(n), n)

def medK_levelcorr(n):
    return levelcorr(week_median_K(n), n)

def daytype_match(n, K=8):              # 같은 주말/공휴일 상태인 same-DOW 주만 평균(레벨 오염 차단)
    w0 = w0_of(n); picks = []
    for j in range(K):
        Lh = 168 * (w0 + j)
        a = lag(Lh)
        src = np.arange(N) - Lh
        ok = src >= 0
        match = np.zeros(N, bool)
        match[ok] = (is_hol[src[ok]] == is_hol[ok]) & (is_wkd[src[ok]] == is_wkd[ok])
        a = np.where(match, a, np.nan)
        picks.append(a)
    stack = np.vstack(picks)
    # 가까운 것부터 최대 2개 평균
    out = np.full(N, np.nan)
    for t in range(N):
        col = stack[:, t]; v = col[np.isfinite(col)][:2]
        if len(v): out[t] = v.mean()
    return out


cands = {
    'week2(현재)': week2_mean,
    'week_nearest': week_nearest,
    'week_medK4': week_median_K,
    'week2+lvlcor': week2_levelcorr,
    'medK+lvlcor': medK_levelcorr,
    'daytype_match': daytype_match,
}

recent = idx >= (idx.max() - pd.Timedelta(days=365))
isday = (hour >= 9) & (hour <= 20)


def stat(a, sel):
    m = sel & np.isfinite(a) & (dem > 0)
    if m.sum() == 0: return np.nan, np.nan
    e = (a[m] - dem[m]) / dem[m]
    return float(np.mean(np.abs(e)) * 100), float(np.mean(e) * 100)


hs = [1, 2, 3, 5, 8, 11, 15]


def block(title, sel):
    print(f"\n### {title}  (n={int((sel).sum())})  — 셀 = MAPE / bias")
    head = "지평 | " + " | ".join(f"{k:>14}" for k in cands)
    print(head); print("-" * len(head))
    for n in hs:
        line = f"D+{n:<2} |"
        for k, fn in cands.items():
            mp, bi = stat(fn(n), recent & sel)
            line += f" {mp:>6.2f}/{bi:>+5.1f}"
        print(line)


print(f"평가창 최근 1년: {idx[recent].min()} .. {idx.max()}")
block("전체", np.ones(N, bool))
block("낮 09-20시", isday)
block("밤", ~isday)
block("공휴일 타깃", is_hol)

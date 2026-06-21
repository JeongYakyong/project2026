# -*- coding: utf-8 -*-
"""fine-tune용 train/val 격자 split 설계·검증.

원칙:
  - 단위 = 타깃 '하루'(24h 블록). 하루를 통째로 train 또는 val 에 배정(시간 내 분할 금지).
  - 시계열 순서 유지 + train/val 을 하루 단위로 교차(격자) → 전 계절이 양쪽에 들어가게.
  - ★요일유형(평일/주말/공휴일)별 층화 systematic 추출 → val 의 유형 비율 ≈ 전체 ≈ train.
  - 공휴일은 드물고 설·추석처럼 뭉쳐 있음 → '연속 공휴일 묶음(cluster)'을 통째로 배정, 묶음 단위 격자.
  - 주말도 토·일 쌍을 통째로 배정(입력창 중복으로 인한 val 독립성 저하 완화).
창: 2024-11-23 ~ 2025-11-30 (forecast_horizon test 2025-12-15~ 와 타깃 무겹침).
"""
from __future__ import annotations
import os, sys
try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass
import numpy as np, pandas as pd
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import model_lt as M  # noqa

HERE = os.path.dirname(os.path.abspath(__file__))
WIN_LO, WIN_HI = '2024-11-23', '2025-11-30'
SEASON = M.SEASON


def build_days():
    days = pd.date_range(WIN_LO, WIN_HI, freq='D')
    is_wknd, is_hol = M.holiday_flags(days)
    dt = M.daytype_code(is_wknd, is_hol)   # 0 평일 / 1 주말 / 2 공휴일
    df = pd.DataFrame({'date': days, 'daytype': dt}); df['season'] = df['date'].dt.month.map(SEASON)
    df['week'] = df['date'].dt.isocalendar().week.astype(int) + df['date'].dt.year * 100
    return df


def cluster_units(df):
    """배정 단위 리스트 생성: 공휴일=연속묶음, 주말=토일쌍(ISO주), 평일=개별 하루."""
    units = []  # (kind, [dates])
    df = df.sort_values('date').reset_index(drop=True)
    i = 0
    while i < len(df):
        d = df.iloc[i]
        if d['daytype'] == 2:                      # 공휴일 묶음
            j = i
            while j < len(df) and df.iloc[j]['daytype'] == 2:
                j += 1
            units.append(('hol', list(df['date'].iloc[i:j]))); i = j
        elif d['daytype'] == 1:                    # 주말: 같은 ISO주 주말 묶음
            wk = d['week']; j = i
            while j < len(df) and df.iloc[j]['daytype'] == 1 and df.iloc[j]['week'] == wk:
                j += 1
            units.append(('wknd', list(df['date'].iloc[i:j]))); i = j
        else:                                      # 평일 개별
            units.append(('wd', [d['date']])); i += 1
    return units


def split(df, p=1/6):
    """층화 systematic: 유형별 단위를 시간순 정렬 후 round(1/p)번째를 val."""
    units = cluster_units(df)
    k = max(2, round(1 / p))
    val_dates = set()
    for kind in ('wd', 'wknd', 'hol'):
        u = [x for x in units if x[0] == kind]
        # 격자 시작점을 살짝 다르게(유형 간 같은 주에 몰리지 않게)
        start = {'wd': k // 2, 'wknd': k // 3, 'hol': 0}[kind]
        for idx in range(start, len(u), k):
            val_dates.update(u[idx][1])
    df = df.copy(); df['split'] = np.where(df['date'].isin(val_dates), 'val', 'train')
    return df


def report(df):
    def share(sub):
        n = len(sub); c = sub['daytype'].value_counts()
        return n, 100*c.get(0,0)/n, 100*c.get(1,0)/n, 100*c.get(2,0)/n
    print(f'창 {WIN_LO} ~ {WIN_HI} | 총 {len(df)}일')
    for name, sub in [('전체', df), ('train', df[df.split=="train"]), ('val', df[df.split=="val"])]:
        n, w, e, h = share(sub)
        print(f'  {name:6s} {n:4d}일 | 평일 {w:5.1f}% 주말 {e:5.1f}% 공휴일 {h:4.1f}%')
    print(f'  → val 비율 {100*len(df[df.split=="val"])/len(df):.1f}%')
    print('\n  [계절별 val 일수] (전 계절 분포 확인)')
    pv = df.pivot_table(index='season', columns='split', values='date', aggfunc='count', observed=True)
    print(pv.to_string())
    print('\n  [공휴일 배정] (묶음 무결성·양쪽 분포)')
    hol = df[df.daytype==2]
    print('   train 공휴일:', sorted(d.strftime('%m-%d') for d in hol[hol.split=="train"]['date']))
    print('   val   공휴일:', sorted(d.strftime('%m-%d') for d in hol[hol.split=="val"]['date']))


if __name__ == '__main__':
    df = build_days()
    for p in (1/6, 1/5):
        print('\n' + '='*60 + f'\n  p = 1/{round(1/p)}  (val 목표 {100*p:.0f}%)\n' + '='*60)
        d = split(df, p); report(d)
        if abs(p - 1/6) < 1e-9:
            d[['date','daytype','season','split']].to_csv(os.path.join(HERE,'finetune_split.csv'), index=False, encoding='utf-8-sig')
            print('  저장: finetune_split.csv (p=1/6)')

# -*- coding: utf-8 -*-
"""훈련 전 누수·견고성 점검:
 (1) demand 결측·gap 크기 → 무제한 시간보간이 미래값을 끌어올 위험 크기.
 (2) holidays 패키지 is_holiday vs 과거 DB day_type 일치율 → 요일타입 오지정 위험.
"""
import os, sqlite3
import numpy as np, pandas as pd
import model_lt as M

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.normpath(os.path.join(HERE, '..', '..', '..', '1. data_fetcher_and_db', 'data', 'input_data_land.db'))

with sqlite3.connect(DB) as con:
    raw = pd.read_sql("SELECT timestamp, real_demand_land, day_type FROM historical ORDER BY timestamp",
                      con, parse_dates=['timestamp'])
raw = raw.set_index('timestamp')
idx = pd.date_range(raw.index.min(), raw.index.max(), freq='h')
raw = raw.reindex(idx)

# (1) demand 결측·gap
dem = raw['real_demand_land'].copy()
dem[dem == 0] = np.nan
nan = dem.isna()
print(f"[1] demand 행수 {len(dem)}  결측 {nan.sum()} ({nan.mean()*100:.3f}%)")
# 연속 결측 run 길이 분포
g = (nan != nan.shift()).cumsum()
runs = nan.groupby(g).sum()
runs = runs[runs > 0]
if len(runs):
    print(f"    연속 결측 구간 {len(runs)}개  최장 {int(runs.max())}h  중앙값 {int(runs.median())}h  "
          f">6h 구간 {int((runs>6).sum())}개")
else:
    print("    연속 결측 없음")

# (2) holidays vs day_type
is_wknd, is_hol = M.holiday_flags(idx)
dt = raw['day_type'].ffill().bfill().values
db_hol = (dt == 'holiday')
pkg_hol = is_hol.astype(bool)
# 주말 제외하고 평일 중 공휴일 판정 비교(주말은 둘 다 자명)
wk = ~is_wknd.astype(bool)
agree = (db_hol == pkg_hol)
print(f"\n[2] holidays 패키지 vs DB day_type  (전체 {len(idx)}h)")
print(f"    공휴일 플래그 일치율 {agree.mean()*100:.3f}%")
only_db = wk & db_hol & ~pkg_hol     # DB는 공휴일인데 패키지는 평일(=패키지가 놓침)
only_pkg = wk & pkg_hol & ~db_hol    # 패키지는 공휴일인데 DB는 평일
print(f"    평일중 DB만 공휴일(패키지 놓침) {int(only_db.sum())}h = {only_db.sum()//24}일분")
print(f"    평일중 패키지만 공휴일(DB는 평일) {int(only_pkg.sum())}h = {only_pkg.sum()//24}일분")
# 어긋난 날짜 샘플
dser = pd.Series(only_db | only_pkg, index=idx)
bad_days = sorted(set(pd.Series(idx[dser.values]).dt.normalize()))
print(f"    어긋난 날 {len(bad_days)}일:", [d.strftime('%Y-%m-%d') for d in bad_days[:12]],
      '...' if len(bad_days) > 12 else '')

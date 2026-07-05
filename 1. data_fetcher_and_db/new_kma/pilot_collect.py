"""pilot_collect.py -- Phase 5.5: 파일럿 수집 시뮬레이션 (운영 DB 에 안 씀).

신 std API 로 '운영과 같은 꼴'의 한 조각을 실제로 수집해 본다:
- 대상: 제주 솔라팜 남쪽 1지점, 최신 12z base 의 D+1 하루(24시간, hf 3..26)
- 변수: 신 아키텍처의 국지(L010) 핵심 10종
- 병렬 workers=6 (운영 검증치) + probe_lib rate-limit 0.3s
- 측정: 소요시간·성공률·재시도(로그의 실호출 상태 코드)
- 산출: pilot_wide_sample.parquet -- forecast_horizon 식 wide 로 조립 가능함을 실증
"""
import sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

import pandas as pd
import probe_lib as pl

tmfc = pl.latest_tmfc(12)
base_kst = (datetime.strptime(tmfc, "%Y%m%d%H")
            .replace(tzinfo=pl.UTC).astimezone(pl.KST))

VARS = ["T2", "RH2", "U10", "V10", "U80", "V80", "GUST",
        "SWDDIR2", "SWDDIF2", "ACSWDNB"]
HFS = list(range(3, 27))     # D+1 00~23 KST (12z base 는 21 KST -- hf3 = 다음날 00시)
X, Y = 664, 259              # L010 솔라팜

def one(task):
    nm, hf = task
    b = pl.fetch_std("KIML", "L010", nm, tmfc, hf, X, Y)
    if not b or "ERROR" in b:
        return nm, hf, None
    vs = [float(t) for l in b.splitlines()
          if l.strip() and not l.startswith("#") for t in l.split()]
    return nm, hf, (vs[0] if vs else None)

tasks = [(nm, hf) for hf in HFS for nm in VARS]
t0 = time.time()
n0 = pl.budget_status()["real_calls"]
with ThreadPoolExecutor(max_workers=6) as ex:
    results = list(ex.map(one, tasks))
elapsed = time.time() - t0
n_real = pl.budget_status()["real_calls"] - n0
ok = sum(1 for _, _, v in results if v is not None)
print(f"파일럿: {len(tasks)}건 중 {ok}건 성공, 실호출 {n_real}건, "
      f"{elapsed:.1f}s ({(n_real / elapsed if elapsed > 0 else 0):.2f} 실호출/s)")

# wide 조립 (forecast_horizon 과 같은 timestamp 축)
recs = {}
for nm, hf, v in results:
    ts = (base_kst + timedelta(hours=hf)).strftime("%Y-%m-%d %H:%M:%S")
    recs.setdefault(ts, {})[nm] = v
wide = pd.DataFrame.from_dict(recs, orient="index").sort_index()
wide.index.name = "timestamp"
# 현행 저장 규약으로 파생 (radiation MJ/m^2/h = GHI(W/m^2) x 0.0036, temp = K -> degC)
wide["ghi"] = wide.SWDDIR2 + wide.SWDDIF2
wide["radiation_MJ"] = (wide.ghi * 0.0036).round(4)
wide["temp_C"] = (wide.T2 - 273.15).round(2)
wide.to_parquet("pilot_wide_sample.parquet")
print(wide[["temp_C", "RH2", "U10", "V10", "GUST", "ghi", "radiation_MJ",
            "ACSWDNB"]].round(2).to_string())
print("\nbudget:", pl.budget_status())

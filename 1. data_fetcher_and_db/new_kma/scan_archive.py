"""scan_archive.py -- Phase 3: tmfc 아카이브(backfill 가능) 깊이 실측.

모델별로 과거 12z 발표를 하나씩 찍어 '조회 가능/불가'를 기록한다.
- 최근 30일: 매일 / 이후: 3일 간격으로 400일 전까지
- 서비스 개시일(NE57 '26-01-19, R030·L010 '26-02-09) 전후가 경계 후보
결과: results/archive_scan.csv
추가: 가장 오래된 가용 발표에서 hf 꼬리(최대 리드) 유지 확인 + 주기 커버리지.
"""
import sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from datetime import datetime, timedelta
import pandas as pd
import probe_lib as pl

CFG = {
    "NE57": {"group": "KIMG", "name": "tsfc", "xy": (1523, 1480), "tail": [288, 285, 135]},
    "R030": {"group": "KIMR", "name": "T2",   "xy": (550, 250),  "tail": [120, 119, 72]},
    "L010": {"group": "KIML", "name": "T2",   "xy": (664, 259),  "tail": [48, 47, 24]},
}

today = datetime.strptime(pl.latest_tmfc(12)[:8], "%Y%m%d")
dates = [today - timedelta(days=k) for k in range(0, 31)]          # 매일 30일
dates += [today - timedelta(days=k) for k in range(33, 401, 3)]    # 3일 간격 400일

def ok_call(model, tmfc, hf):
    cfg = CFG[model]
    x, y = cfg["xy"]
    b = pl.fetch_std(cfg["group"], model, cfg["name"], tmfc, hf, x, y)
    if not b or "ERROR" in b:
        return 0, None
    vs = [float(t) for l in b.splitlines()
          if l.strip() and not l.startswith("#") for t in l.split()]
    return (1, vs[0]) if vs else (0, None)

rows = []
for model in CFG:
    n_ok = 0
    oldest_ok = None
    for d in dates:
        tmfc = d.strftime("%Y%m%d") + "12"
        ok, v = ok_call(model, tmfc, 24)
        rows.append({"model": model, "tmfc": tmfc, "hf": 24, "kind": "depth",
                     "ok": ok, "value": v})
        if ok:
            n_ok += 1
            oldest_ok = tmfc
    print(f"{model}: 12z hf=24 가용 {n_ok}/{len(dates)}  가장 오래된 ok={oldest_ok}")

df = pd.DataFrame(rows)
df.to_csv("results/archive_scan.csv", index=False, encoding="utf-8-sig")
print("budget:", pl.budget_status())

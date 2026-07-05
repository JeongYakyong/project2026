"""scan_lead.py -- Phase 2: 모델·발표주기별 최대 리드와 hf 해상도(1h/3h) 실측.

각 (모델, 발표주기)에 대해 hf 를 촘촘히 찍어 '응답 있음/없음'을 기록한다.
- 12z 는 전수/조밀 스캔 (경계를 정확히 잡는다)
- 00/06/18z 는 스팟 스캔 (주기별 리드 차이만 확인)
결과: results/lead_scan.csv  (model, cycle, hf, ok, value)
"""
import sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import pandas as pd
import probe_lib as pl

# 지점: 솔라팜 남쪽 (Phase 0 변환표), 존재 확인용 변수는 모델별 '정상' 변수 사용
CFG = {
    "NE57": {"group": "KIMG", "name": "tsfc", "xy": (1523, 1480)},
    "R030": {"group": "KIMR", "name": "T2",   "xy": (550, 250)},
    "L010": {"group": "KIML", "name": "T2",   "xy": (664, 259)},
}

# 스캔 그리드
ne57_12 = (list(range(1, 91))                    # 1h 경계 전수
           + list(range(93, 295, 3))             # 3h 구간
           + [294, 300, 312, 324, 336, 348, 360, 372])  # 확장(장지평 존속?)
ne57_spot = [1, 2, 3, 4, 6, 12, 24, 48, 85, 86, 87, 88, 89, 90, 93, 96, 135, 288, 291]
r030_12 = list(range(1, 94))                     # 87 초과 여부 포함 전수
r030_spot = [1, 2, 3, 50, 85, 86, 87, 88, 89, 90]
l010_12 = list(range(1, 55))                     # 48 초과 여부 포함 전수
l010_spot = [1, 2, 24, 47, 48, 49, 50, 51]

PLAN = []
for cyc in [0, 6, 12, 18]:
    PLAN.append(("NE57", cyc, ne57_12 if cyc == 12 else ne57_spot))
    PLAN.append(("R030", cyc, r030_12 if cyc == 12 else r030_spot))
    PLAN.append(("L010", cyc, l010_12 if cyc == 12 else l010_spot))

rows = []
for model, cyc, hfs in PLAN:
    cfg = CFG[model]
    tmfc = pl.latest_tmfc(cyc)
    x, y = cfg["xy"]
    n_ok = 0
    for hf in hfs:
        b = pl.fetch_std(cfg["group"], model, cfg["name"], tmfc, hf, x, y)
        ok = bool(b) and "ERROR" not in b and any(
            l.strip() and not l.startswith("#") for l in b.splitlines())
        val = None
        if ok:
            vs = [float(t) for l in b.splitlines()
                  if l.strip() and not l.startswith("#") for t in l.split()]
            val = vs[0] if vs else None
            ok = val is not None
        n_ok += ok
        rows.append({"model": model, "cycle": cyc, "tmfc": tmfc,
                     "hf": hf, "ok": int(ok), "value": val})
    print(f"{model} {cyc:02d}z tmfc={tmfc}: {n_ok}/{len(hfs)} ok")

df = pd.DataFrame(rows)
df.to_csv("results/lead_scan.csv", index=False, encoding="utf-8-sig")

# 요약: 주기별 최대 리드, 1h 연속 상한(비3배수 hf 가 응답하는 최대), 간격
print("\n=== 요약 ===")
for (m, c), g in df.groupby(["model", "cycle"]):
    okh = g[g.ok == 1].hf.tolist()
    if not okh:
        print(f"{m} {c:02d}z: 응답 없음")
        continue
    non3 = [h for h in okh if h % 3 != 0]
    hourly_max = max(non3) if non3 else 0
    print(f"{m} {c:02d}z: max_hf={max(okh)}  1h구간상한(비3배수 최대)={hourly_max}  "
          f"ok {len(okh)}/{len(g)}")
print("\nbudget:", pl.budget_status())

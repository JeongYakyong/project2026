"""일사 정밀 검증 — "D+1 69% 열세"가 진짜인가 아티팩트인가.
분해: (1) 편향 vs 무작위  (2) 시각 정렬 오류 여부(±1h shift 실험)
     (3) 며칠이 끌어올리나(발행일별)  (4) 시각대별  (5) 맑음/흐림 구분
"""
import sys; sys.stdout.reconfigure(encoding="utf-8")
import sqlite3
import numpy as np, pandas as pd
import eda_lib as L

REG = "land"
def load_db(path):
    con = sqlite3.connect(path)
    df = pd.read_sql("SELECT * FROM forecast_horizon", con,
                     parse_dates=["timestamp", "base"]).rename(columns={"timestamp": "ts"})
    con.close()
    return L.melt_points(df, REG, ["radiation"])

v2 = load_db(L.DB_V2_LAND).rename(columns={"radiation": "v2"})
cur = load_db(L.DB_LAND.parent / "cur_land.db").rename(columns={"radiation": "cur"})
common = sorted(set(v2.base.unique()) & set(cur.base.unique()))
fc = v2[v2.base.isin(common)].merge(
        cur[cur.base.isin(common)], on=["base", "ts", "horizon_d", "sfx"], how="inner")

# 실측·태양고도
ac = L.load_actuals(REG); geo = L.solar_geometry(REG)
al = []
for p in L.POINTS[REG]:
    s = p["sfx"]
    al.append(ac[["ts", f"solar_rad_{s}"]].rename(columns={f"solar_rad_{s}": "act"}).assign(sfx=s))
al = pd.concat(al, ignore_index=True)
df = fc.merge(al, on=["ts", "sfx"], how="left").merge(geo, on=["ts", "sfx"], how="left")
d1 = df[(df.horizon_d == 1) & (df.elev > 8)].dropna(subset=["act", "v2", "cur"]).copy()
d1["hour"] = d1.ts.dt.hour

print(f"D+1 낮 표본 {len(d1)}  (발행일 {d1.base.dt.date.nunique()}, 지점 {d1.sfx.nunique()})")
print("\n=== (1) 편향(bias) vs 평균절대오차(MAE) — 예보−실측 ===")
for nm, col in [("v2 R030 1h", "v2"), ("cur NE57 3h", "cur")]:
    print(f"  {nm:14} MAE={L.mae(d1[col],d1.act):.3f}  bias={L.bias(d1[col],d1.act):+.3f}  "
          f"평균실측={d1.act.mean():.3f}  → 과대비율 {(d1[col]>d1.act).mean()*100:.0f}%")

print("\n=== (2) 시각 정렬 실험 — v2 를 ±1h 옮겨 MAE 재계산 ===")
for sh in (-2, -1, 0, 1, 2):
    tmp = d1[["base", "sfx", "ts", "act"]].copy()
    v2s = df[(df.horizon_d == 1)][["base", "sfx", "ts", "v2"]].copy()
    v2s["ts"] = v2s.ts - pd.Timedelta(hours=sh)   # 예보 시각을 sh 만큼 이동
    j = tmp.merge(v2s, on=["base", "sfx", "ts"], how="left").dropna(subset=["v2", "act"])
    print(f"  shift {sh:+d}h:  MAE={L.mae(j.v2,j.act):.3f}   (n={len(j)})")

print("\n=== (3) 발행일별 MAE — 며칠이 끌어올리나 ===")
g = d1.groupby(d1.base.dt.date).apply(
    lambda x: pd.Series({"v2": L.mae(x.v2, x.act), "cur": L.mae(x.cur, x.act),
                         "실측일평균": x.act.mean(), "n": len(x)}), include_groups=False)
print(g.round(3).to_string())

print("\n=== (4) 시각대별 MAE ===")
h = d1.groupby("hour").apply(
    lambda x: pd.Series({"v2": L.mae(x.v2, x.act), "cur": L.mae(x.cur, x.act),
                         "실측": x.act.mean()}), include_groups=False)
print(h.round(3).to_string())

# (5) 맑음/흐림 구분 — 실측 청명도(일 낮평균 실측/청천)
d1["cs"] = df.set_index(["base","sfx","ts"]).loc[
    list(zip(d1.base,d1.sfx,d1.ts)), "cs_ghi_mj"].values if False else np.nan
# 간단히: 지점·발행일 낮평균 실측 / 낮평균 청천
csmap = geo.set_index(["ts","sfx"]).cs_ghi_mj
d1["cs"] = [csmap.get((t,s),np.nan) for t,s in zip(d1.ts,d1.sfx)]
day_kt = d1.groupby([d1.base.dt.date,"sfx"]).apply(
    lambda x: x.act.sum()/max(x.cs.sum(),1e-6), include_groups=False).rename("dayKt")
d1 = d1.merge(day_kt, left_on=[d1.base.dt.date,"sfx"], right_index=True, how="left")
d1["regime"] = np.where(d1.dayKt>0.55,"맑음(청명>0.55)",
               np.where(d1.dayKt>0.35,"보통","흐림(청명<0.35)"))
print("\n=== (5) 맑음/흐림별 MAE·bias ===")
for r in ["맑음(청명>0.55)","보통","흐림(청명<0.35)"]:
    s=d1[d1.regime==r]
    if len(s):
        print(f"  {r:16} n={len(s):4d}  v2 MAE={L.mae(s.v2,s.act):.3f}(bias{L.bias(s.v2,s.act):+.2f}) "
              f" cur MAE={L.mae(s.cur,s.act):.3f}(bias{L.bias(s.cur,s.act):+.2f})")
d1.to_parquet(L.FIGS.parent/"b1_d1_solar.parquet")
print("\n저장: b1_d1_solar.parquet")

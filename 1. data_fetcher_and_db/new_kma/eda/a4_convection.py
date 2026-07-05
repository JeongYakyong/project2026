"""급변동 감지 신규 변수 — cape(대류잠재)·cinn(억제)·해면기압(전선). 장마철 9일.

핵심 질문:
 (1) 예보 cape 가 실제 강수(대류) 시각을 구분하는가 (환경장 신호로서 타당한가)
 (2) 장마 강수는 상당수 전선성(비대류)이라 cape 만으론 못 봄 -> 해면기압 경향(전선)이
     보완하는가 (사용자 선별 세트: cape+cinn+기압경향+운량 이 상보적이라는 근거)
 (3) 사례: 급변 이벤트에서 신규 변수가 신호를 주는가 (순부하·태양광과 함께)
"""
import sys; sys.stdout.reconfigure(encoding="utf-8")
import sqlite3
import numpy as np, pandas as pd
import eda_lib as L

plt = L.setup_mpl()

# ── (1) cape/cinn vs 실제 강수 (육지+제주 풀, D+1) ────────────────────────
def cape_rain(region):
    fc = L.load_forecast(region)
    c = L.melt_points(fc, region, ["cape", "cinn", "hpbl"])
    c = c[c.horizon_d == 1]
    ac = L.load_actuals(region)
    parts = []
    for p in L.POINTS[region]:
        s = p["sfx"]
        col = f"rainfall_{s}"
        if col not in ac.columns:
            continue
        parts.append(ac[["ts", col]].rename(columns={col: "rain_act"}).assign(sfx=s))
    rain = pd.concat(parts, ignore_index=True)
    return c.merge(rain, on=["ts", "sfx"], how="left")

cr = pd.concat([cape_rain("land"), cape_rain("jeju")], ignore_index=True).dropna(subset=["rain_act"])
cr["rainy"] = cr.rain_act > 0.1
print("=== (1) cape 가 대류 강수를 구분하는가 (D+1) ===")
print(f"  표본 {len(cr)}, 강수시각 {cr.rainy.mean()*100:.0f}%")
print(f"  cape  중앙값  맑음 {cr[~cr.rainy].cape.median():.0f} vs 강수 {cr[cr.rainy].cape.median():.0f} J/kg")
print(f"  cape>500 시 강수확률 {cr[cr.cape>500].rainy.mean()*100:.0f}% vs 전체 {cr.rainy.mean()*100:.0f}%")
# 강수 자체 분류력(AUC 근사) — cape 만
from numpy import trapz
def auc(score, label):
    o = np.argsort(-score.values); lab = label.values[o]
    tp = np.cumsum(lab)/lab.sum(); fp = np.cumsum(1-lab)/(1-lab).sum()
    return float(trapz(tp, fp))
print(f"  cape 단독 강수분류 AUC {auc(cr.cape.fillna(0), cr.rainy.astype(int)):.3f} (0.5=무능)")

# ── (2) 해면기압 경향(전선) — 제주만 mslp 보유 ───────────────────────────
fcj = L.load_forecast("jeju")
mp = L.melt_points(fcj, "jeju", ["mslp", "cape"])
mp = mp[mp.horizon_d <= 2].sort_values(["sfx", "base", "ts"])
# 3시간 기압 경향(hPa/3h)
mp["dp3"] = mp.groupby(["sfx", "base"])["mslp"].diff(3)
acj = L.load_actuals("jeju")
rj = []
for p in L.POINTS["jeju"]:
    s = p["sfx"]; col = f"rainfall_{s}"
    if col in acj.columns:
        rj.append(acj[["ts", col]].rename(columns={col: "rain_act"}).assign(sfx=s))
rj = pd.concat(rj, ignore_index=True)
mp = mp.merge(rj, on=["ts", "sfx"], how="left")
mp["rainy"] = mp.rain_act > 0.1
mm = mp.dropna(subset=["dp3", "rainy"])
print("\n=== (2) 해면기압 급강하(전선) vs 강수 — 제주 ===")
print(f"  기압하강(dp3<-1hPa) 시 강수확률 {mm[mm.dp3<-1].rainy.mean()*100:.0f}%"
      f" vs 안정(|dp3|<0.5) {mm[mm.dp3.abs()<0.5].rainy.mean()*100:.0f}%")
print(f"  |기압경향| 절대값 강수분류 AUC {auc(mm.dp3.abs().fillna(0), mm.rainy.astype(int)):.3f}")

# ── 그림 1: 맑음 vs 강수 시 cape 분포 + 기압경향 ──────────────────────────
fig, axes = plt.subplots(1, 3, figsize=(12, 3.6))
ax = axes[0]
bins = np.linspace(0, 2500, 26)
ax.hist(cr[~cr.rainy].cape.clip(0, 2500), bins=bins, density=True, alpha=0.6,
        color="#9aa5b1", label="맑음")
ax.hist(cr[cr.rainy].cape.clip(0, 2500), bins=bins, density=True, alpha=0.6,
        color="#2b6cb0", label="강수")
ax.set_xlabel("예보 cape (J/kg)"); ax.set_ylabel("밀도")
ax.set_title(f"(가) cape 단독은 장마비를 못 가름 (AUC {auc(cr.cape.fillna(0), cr.rainy.astype(int)):.2f})",
             fontsize=10.5); ax.legend(fontsize=8)

ax = axes[1]
ax.hist(mm[~mm.rainy].dp3.clip(-4, 4), bins=30, density=True, alpha=0.6,
        color="#9aa5b1", label="맑음")
ax.hist(mm[mm.rainy].dp3.clip(-4, 4), bins=30, density=True, alpha=0.6,
        color="#2b6cb0", label="강수")
ax.axvline(0, color="k", lw=0.8)
ax.set_xlabel("3시간 기압경향 (hPa/3h)"); ax.set_ylabel("밀도")
ax.set_title(f"(나) 강수는 기압 하강 쪽에 쏠림 (AUC {auc(mm.dp3.abs().fillna(0), mm.rainy.astype(int)):.2f})",
             fontsize=10.5); ax.legend(fontsize=8)

# ── 그림 2: 사례 타임라인 (제주남, 가장 강수 많은 발행일 D+1~2) ──────────
# 강수 총량 최대인 발행일 선택. 강수(막대) + 해면기압(제 축)으로 전선 통과 확인.
cand = mp[mp.sfx == "south"].copy()
best_base = (cand.assign(r=cand.rain_act.fillna(0)).groupby("base").r.sum().idxmax())
seg = cand[cand.base == best_base].sort_values("ts")
ax = axes[2]
ax2 = ax.twinx()
ax.bar(seg.ts, seg.rain_act.fillna(0), width=0.035, color="#4a90d9", alpha=0.6, label="실측 강수")
ax2.plot(seg.ts, seg.mslp, color="#c0392b", lw=1.8, label="예보 해면기압")
lo, hi = seg.mslp.min(), seg.mslp.max()
ax2.set_ylim(lo - 0.5, hi + 0.5)                 # 기압 자체 범위로 확대
ax.set_ylabel("강수(mm)"); ax2.set_ylabel("해면기압(hPa)", color="#c0392b")
ax2.tick_params(axis="y", labelcolor="#c0392b")
ax.set_title(f"(다) 사례: 제주남 {pd.Timestamp(best_base).date()} 발행 — 비 올 때 기압 저점",
             fontsize=10)
ln1, la1 = ax.get_legend_handles_labels(); ln2, la2 = ax2.get_legend_handles_labels()
ax.legend(ln1+ln2, la1+la2, fontsize=7.5, loc="upper left")
ax.tick_params(axis="x", labelrotation=30, labelsize=7)

fig.suptitle("신규 변수 검증 ④ 급변동 감지 — cape·해면기압 (장마철 9일)", fontsize=12, y=1.03)
fig.tight_layout()
fig.savefig(L.FIGS / "a4_convection.png", bbox_inches="tight", dpi=120)
print("\n저장:", L.FIGS / "a4_convection.png")

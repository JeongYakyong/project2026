"""다일 R030 ACSWDNB 검증 — 서산 D+1 9일(06-26~07-04). 순시합 vs 누적 vs 실측.
probe_lib(예비키·콜캡·캐시우선). ~112 콜(8 신규 base × 14hf, 07-04 는 캐시).
"""
import sys, re, sqlite3
from pathlib import Path
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import numpy as np, pandas as pd
import eda_lib as L
import probe_lib as P

plt = L.setup_mpl()
X, Y = 539, 376        # 서산 R030

def acswdnb_val(body):
    if not body:
        return np.nan
    vals = re.findall(r"^\s*([-+]?[\d.]+e[+-]\d+)\s*$", body, re.M)
    return float(vals[-1]) if vals else np.nan

bases = pd.date_range("2026-06-25 21:00", "2026-07-03 21:00", freq="1D")
print("budget 시작:", P.budget_status())
all_rows = []
for b in bases:
    tmfc = b.strftime("%Y%m%d") + "12"          # 12z UTC = 21:00 KST 당일
    rows = []
    for hf in range(8, 22):
        body = P.fetch_std("KIMR", "R030", "ACSWDNB", tmfc, hf, X, Y)
        rows.append((hf, b + pd.Timedelta(hours=hf), acswdnb_val(body)))
    a = pd.DataFrame(rows, columns=["hf", "ts", "acc"]).sort_values("hf")
    a["dACSWDNB"] = a.acc.diff()
    a["base"] = b
    all_rows.append(a)
acc = pd.concat(all_rows, ignore_index=True)
print("budget 종료:", P.budget_status())

# 순시(v2 R030 D+1) + 실측
con = sqlite3.connect(L.DB_V2_LAND)
inst = pd.read_sql("SELECT timestamp AS ts, base, radiation_seosan AS inst FROM forecast_horizon "
                   "WHERE horizon_d=1", con, parse_dates=["ts", "base"]); con.close()
con = sqlite3.connect(L.DB_LAND)
act = pd.read_sql("SELECT timestamp AS ts, solar_rad_seosan AS act FROM historical "
                  "WHERE timestamp>='2026-06-26' AND timestamp<'2026-07-05'", con, parse_dates=["ts"]); con.close()

df = acc.merge(inst, on=["ts", "base"], how="inner").merge(act, on="ts", how="left")
d = df[(df.ts.dt.hour >= 6) & (df.ts.dt.hour <= 18)].dropna(subset=["act"]).copy()

print(f"\n=== 서산 D+1 다일(9일) 낮 종합 (n={len(d)}) ===")
print(f"  순시 성분합(현행)  MAE {L.mae(d.inst,d.act):.3f}  bias {L.bias(d.inst,d.act):+.3f}")
print(f"  ACSWDNB 누적차분   MAE {L.mae(d.dACSWDNB,d.act):.3f}  bias {L.bias(d.dACSWDNB,d.act):+.3f}"
      f"   → MAE {(1-L.mae(d.dACSWDNB,d.act)/L.mae(d.inst,d.act))*100:+.0f}%")

print("\n발행일별 MAE (순시 → 누적):")
g = d.groupby(d.base.dt.date).apply(lambda x: pd.Series({
    "순시": L.mae(x.inst, x.act), "누적": L.mae(x.dACSWDNB, x.act),
    "실측평균": x.act.mean(), "n": len(x)}), include_groups=False)
g["개선%"] = (1 - g.누적 / g.순시) * 100
print(g.round(3).to_string())

# ── 그림: 발행일별 MAE 막대 + 종합 ────────────────────────────────────────
fig, (a1, a2) = plt.subplots(1, 2, figsize=(12, 3.8), gridspec_kw={"width_ratios": [3, 1]})
x = np.arange(len(g))
a1.bar(x - 0.2, g.순시, 0.4, color="#2b6cb0", label="현행 순시합")
a1.bar(x + 0.2, g.누적, 0.4, color="#1a7f37", label="ACSWDNB 누적")
a1.set_xticks(x); a1.set_xticklabels([str(d)[5:] for d in g.index], fontsize=8)
a1.set_ylabel("일사 MAE (MJ)"); a1.set_title("서산 D+1 발행일별 (낮)", fontsize=11)
a1.legend(fontsize=8.5)
for i in range(len(g)):
    a1.annotate(f"{g['개선%'].iloc[i]:+.0f}%", (i, max(g.순시.iloc[i], g.누적.iloc[i])),
                ha="center", va="bottom", fontsize=7,
                color="#1a7f37" if g['개선%'].iloc[i] > 0 else "#c0392b")
tot = [L.mae(d.inst, d.act), L.mae(d.dACSWDNB, d.act)]
a2.bar(["순시", "누적"], tot, color=["#2b6cb0", "#1a7f37"])
for i, v in enumerate(tot):
    a2.annotate(f"{v:.3f}", (i, v), ha="center", va="bottom", fontsize=9)
a2.set_title(f"9일 종합 ({(1-tot[1]/tot[0])*100:+.0f}%)", fontsize=11); a2.set_ylabel("MAE")
fig.suptitle("다일 검증: R030 ACSWDNB(누적) vs 순시합 — 서산 D+1 9일", fontsize=12, y=1.03)
fig.tight_layout()
fig.savefig(L.FIGS / "c3_multiday_acswdnb.png", bbox_inches="tight", dpi=120)
print("\n저장:", L.FIGS / "c3_multiday_acswdnb.png")

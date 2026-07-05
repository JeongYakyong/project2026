"""R030 ACSWDNB(누적) 소규모 로컬 탐침 — 서빙 창(D+1~5)을 담당하는 R030 에서도
누적차분이 순시합보다 실측에 가까운지 확인.  probe_lib(예비키·콜캡·캐시우선).
대상: 서산 R030(x=539,y=376), base 2026-07-03 12z, D+1(07-04) 낮 hf 8~21 (~14콜).
순시 R030 = v2_land.db forecast_horizon.radiation_seosan (이미 수집됨).
"""
import sys, re, sqlite3
from pathlib import Path
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))   # new_kma/
import numpy as np, pandas as pd
import eda_lib as L
import probe_lib as P

plt = L.setup_mpl()
TMFC = "2026070312"; KST = pd.Timestamp("2026-07-03 21:00")
X, Y = 539, 376        # 서산 R030 격자

def acswdnb_val(body):
    """독립 데이터 줄(예 ' 1.15800e+01 ')만 추출. '#' 주석의 소요시간 등은 제외."""
    if not body:
        return np.nan
    vals = re.findall(r"^\s*([-+]?[\d.]+e[+-]\d+)\s*$", body, re.M)
    return float(vals[-1]) if vals else np.nan

print("budget 시작:", P.budget_status())
rows = []
for hf in range(8, 22):     # hf8 = 07-04 05:00(앵커), hf9~21 = 06:00~18:00
    body = P.fetch_std("KIMR", "R030", "ACSWDNB", TMFC, hf, X, Y)
    rows.append((hf, KST + pd.Timedelta(hours=hf), acswdnb_val(body)))
print("budget 종료:", P.budget_status())

acc = pd.DataFrame(rows, columns=["hf", "ts", "acc_mj"]).sort_values("hf")
acc["dACSWDNB"] = acc.acc_mj.diff()

con = sqlite3.connect(L.DB_V2_LAND)
inst = pd.read_sql("SELECT timestamp AS ts, radiation_seosan AS inst FROM forecast_horizon "
                   "WHERE base='2026-07-03 21:00:00' AND horizon_d=1", con, parse_dates=["ts"]); con.close()
con = sqlite3.connect(L.DB_LAND)
act = pd.read_sql("SELECT timestamp AS ts, solar_rad_seosan AS act FROM historical "
                  "WHERE timestamp>='2026-07-04' AND timestamp<'2026-07-05'", con, parse_dates=["ts"]); con.close()

df = acc.merge(inst, on="ts").merge(act, on="ts", how="left")
d = df[(df.ts.dt.hour >= 6) & (df.ts.dt.hour <= 18)].dropna(subset=["act"]).copy()
print("\n서산 R030 07-04 낮 (누적MJ·차분·순시·실측):")
print(d[["ts", "acc_mj", "dACSWDNB", "inst", "act"]].round(2).to_string(index=False))
print("\n=== 실측 대비 (R030, 서빙 창 모델) ===")
print(f"  순시 성분합(현행)  MAE {L.mae(d.inst,d.act):.3f}  bias {L.bias(d.inst,d.act):+.3f}")
print(f"  ACSWDNB 누적차분   MAE {L.mae(d.dACSWDNB,d.act):.3f}  bias {L.bias(d.dACSWDNB,d.act):+.3f}"
      f"   → MAE {(1-L.mae(d.dACSWDNB,d.act)/L.mae(d.inst,d.act))*100:+.0f}%")

fig, ax = plt.subplots(figsize=(8.6, 4))
ax.fill_between(d.ts, 0, d.act, color="#111", alpha=0.10)
ax.plot(d.ts, d.act, "-o", ms=5, color="#111", lw=2, label="실측(기상청, 시간누적)")
ax.plot(d.ts, d.inst, "-^", ms=4, color="#2b6cb0", lw=1.4,
        label=f"현행 순시합 (bias {L.bias(d.inst,d.act):+.2f}, MAE {L.mae(d.inst,d.act):.2f})")
ax.plot(d.ts, d.dACSWDNB, "-s", ms=4, color="#1a7f37", lw=1.4,
        label=f"R030 ACSWDNB 누적 (bias {L.bias(d.dACSWDNB,d.act):+.2f}, MAE {L.mae(d.dACSWDNB,d.act):.2f})")
ax.set_ylabel("일사 (MJ/m²/h)"); ax.set_ylim(0, 4.0)
ax.set_title("서빙 창 모델 R030: ACSWDNB(누적) vs 순시합 vs 실측 — 서산 07-04(D+1)", fontsize=11)
ax.legend(fontsize=8.5, loc="upper right")
ax.tick_params(axis="x", labelrotation=30, labelsize=8)
fig.tight_layout()
fig.savefig(L.FIGS / "c2_r030_acswdnb.png", bbox_inches="tight", dpi=120)
print("\n저장:", L.FIGS / "c2_r030_acswdnb.png")

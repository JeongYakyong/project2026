"""ACSWDNB(누적 총일사) vs 순시 성분합(SWDDIR2+SWDDIF2) vs 실측 — 로컬 검증(새 콜 0).
캐시(probe_cache, base 07-03 L010) + DB(forecast_horizon_l010) + 실측만 사용.
가설(사용자): 실측은 시간누적이라 ACSWDNB(누적차분)가 순시합보다 실측과 잘 맞을 것.
지점 2개: 서산(육지 L010) + 제주남(태양광, 제주 L010).
"""
import sys; sys.stdout.reconfigure(encoding="utf-8")
import glob, re, os, sqlite3
import numpy as np, pandas as pd
import eda_lib as L

plt = L.setup_mpl()
KST = pd.Timestamp("2026-07-03 21:00")   # base 12z UTC = 21:00 KST
CACHE = L.FIGS.parents[1] / "probe_cache"

def acswdnb(lat_r):
    rows = []
    for f in glob.glob(str(CACHE / "KIML_L010_ACSWDNB_2026070312_hf*.txt")):
        txt = open(f, encoding="latin-1").read()
        m = re.search(r"lon1 = ([\d.]+), lat1 = ([\d.]+)", txt)
        hfm = re.search(r"_hf(\d+)_", os.path.basename(f))
        vals = re.findall(r"^\s*([\d.]+e[+-]\d+)\s*$", txt, re.M)
        if m and hfm and vals and round(float(m.group(2)), 1) == lat_r:
            rows.append((int(hfm.group(1)), float(vals[-1])))
    a = pd.DataFrame(rows, columns=["hf", "acc_mj"]).drop_duplicates("hf").sort_values("hf")
    a["ts"] = KST + pd.to_timedelta(a.hf, unit="h")
    a["dACSWDNB"] = a.acc_mj.diff()
    return a

def one(lat_r, db_v2, radcol, db_act, actcol):
    a = acswdnb(lat_r)
    con = sqlite3.connect(db_v2)
    inst = pd.read_sql(f"SELECT timestamp AS ts, {radcol} AS inst FROM forecast_horizon_l010 "
                       "WHERE base='2026-07-03 21:00:00'", con, parse_dates=["ts"]); con.close()
    con = sqlite3.connect(db_act)
    act = pd.read_sql(f"SELECT timestamp AS ts, {actcol} AS act FROM historical "
                      "WHERE timestamp>='2026-07-04' AND timestamp<'2026-07-05'", con,
                      parse_dates=["ts"]); con.close()
    df = a.merge(inst, on="ts").merge(act, on="ts", how="left")
    return df[(df.ts.dt.hour >= 6) & (df.ts.dt.hour <= 18)].dropna(subset=["act"]).copy()

cases = [
    ("서산 (육지 L010)", 36.8, L.DB_V2_LAND, "radiation_seosan", L.DB_LAND, "solar_rad_seosan"),
    ("제주남 태양광 (L010)", 33.3, L.DB_V2_JEJU, "radiation_south", L.DB_JEJU, "solar_rad_south"),
]

fig, axes = plt.subplots(1, 2, figsize=(12, 4))
for ax, (lab, lat_r, dbv, rc, dba, ac) in zip(axes, cases):
    d = one(lat_r, dbv, rc, dba, ac)
    bi, ba = L.bias(d.inst, d.act), L.bias(d.dACSWDNB, d.act)
    mi, ma = L.mae(d.inst, d.act), L.mae(d.dACSWDNB, d.act)
    print(f"\n[{lab}] 07-04 낮 (n={len(d)}, 실측평균 {d.act.mean():.2f} MJ)")
    print(f"  순시 성분합(현행)  MAE {mi:.3f}  bias {bi:+.3f}")
    print(f"  ACSWDNB 누적차분   MAE {ma:.3f}  bias {ba:+.3f}   → MAE {(1-ma/mi)*100:+.0f}%")
    ax.fill_between(d.ts, 0, d.act, color="#111", alpha=0.10)
    ax.plot(d.ts, d.act, "-o", ms=4.5, color="#111", lw=2, label="실측(기상청, 시간누적)")
    ax.plot(d.ts, d.inst, "-^", ms=3.5, color="#2b6cb0", lw=1.3,
            label=f"현행 순시합 (bias {bi:+.2f}, MAE {mi:.2f})")
    ax.plot(d.ts, d.dACSWDNB, "-s", ms=3.5, color="#1a7f37", lw=1.3,
            label=f"ACSWDNB 누적 (bias {ba:+.2f}, MAE {ma:.2f})")
    ax.set_ylabel("일사 (MJ/m²/h)"); ax.set_title(lab, fontsize=11)
    ax.legend(fontsize=8, loc="upper left"); ax.set_ylim(0, 4.0)
    ax.tick_params(axis="x", labelrotation=30, labelsize=7.5)
fig.suptitle("ACSWDNB(누적) vs 순시 성분합 vs 실측 — 07-04 (base 07-03, 캐시+DB, 새 콜 0)",
             fontsize=12, y=1.02)
fig.tight_layout()
fig.savefig(L.FIGS / "c1_acswdnb_test.png", bbox_inches="tight", dpi=120)
print("\n저장:", L.FIGS / "c1_acswdnb_test.png")

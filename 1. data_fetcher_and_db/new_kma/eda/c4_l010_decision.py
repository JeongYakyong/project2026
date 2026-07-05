"""L010 도입/반려 결정 — 사용자 기준: L010(국지 1.3km)이 R030(3km)·NE57(8km)보다
일사·풍속 등에서 뚜렷이 정밀하면 도입, 큰 차이 없으면 반려.
비교 창 = L010 범위인 D+1~2, 육지 5지점, 실측 대비 MAE (새 콜 0, 전부 DB).
"""
import sys, sqlite3
sys.stdout.reconfigure(encoding="utf-8")
import numpy as np, pandas as pd
import eda_lib as L

plt = L.setup_mpl()
REG = "land"

def melt(path, table, cols):
    con = sqlite3.connect(path)
    df = pd.read_sql(f"SELECT * FROM {table}", con,
                     parse_dates=["timestamp", "base"]).rename(columns={"timestamp": "ts"})
    con.close()
    return L.melt_points(df, REG, cols)

COLS = ["radiation", "temp", "wind_spd_10m"]
l010 = melt(L.DB_V2_LAND, "forecast_horizon_l010", COLS).add_suffix("_l010").rename(
    columns={"base_l010": "base", "ts_l010": "ts", "horizon_d_l010": "horizon_d", "sfx_l010": "sfx"})
r030 = melt(L.DB_V2_LAND, "forecast_horizon", COLS).add_suffix("_r030").rename(
    columns={"base_r030": "base", "ts_r030": "ts", "horizon_d_r030": "horizon_d", "sfx_r030": "sfx"})
ne57 = melt(L.DB_LAND.parent / "cur_land.db", "forecast_horizon", COLS).add_suffix("_ne57").rename(
    columns={"base_ne57": "base", "ts_ne57": "ts", "horizon_d_ne57": "horizon_d", "sfx_ne57": "sfx"})

fc = l010.merge(r030, on=["base", "ts", "horizon_d", "sfx"]).merge(
    ne57, on=["base", "ts", "horizon_d", "sfx"])

ac = L.load_actuals(REG); geo = L.solar_geometry(REG)
al = []
for p in L.POINTS[REG]:
    s = p["sfx"]
    m = {f"solar_rad_{s}": "radiation_act", f"temp_c_{s}": "temp_act", f"wind_spd_{s}": "wind_spd_10m_act"}
    al.append(ac[["ts"] + [c for c in m if c in ac.columns]].rename(columns=m).assign(sfx=s))
al = pd.concat(al, ignore_index=True)
df = fc.merge(al, on=["ts", "sfx"], how="left").merge(geo, on=["ts", "sfx"], how="left")
df["is_day"] = df.elev > 8

VARS = [("radiation", "일사(MJ)", True), ("temp", "기온(°C)", False),
        ("wind_spd_10m", "10m바람(m/s)", False)]
print(f"공통 발행일 {df.base.dt.date.nunique()}, D+1~2 비교 (L010 범위)\n")
rows = []
for h in (1, 2):
    for col, lab, dayonly in VARS:
        s = df[df.horizon_d == h]
        if dayonly:
            s = s[s.is_day]
        r = {"지평": f"D+{h}", "변수": lab,
             "NE57_8km": L.mae(s[f"{col}_ne57"], s[f"{col}_act"]),
             "R030_3km": L.mae(s[f"{col}_r030"], s[f"{col}_act"]),
             "L010_1.3km": L.mae(s[f"{col}_l010"], s[f"{col}_act"]),
             "n": (s[f"{col}_l010"].notna() & s[f"{col}_act"].notna()).sum()}
        rows.append(r)
tab = pd.DataFrame(rows)
tab["L010 vs R030"] = (1 - tab["L010_1.3km"] / tab["R030_3km"]) * 100
for lab in tab.변수.unique():
    print(f"[{lab}]  (양수%=L010이 R030보다 우수)")
    for _, r in tab[tab.변수 == lab].iterrows():
        print(f"  {r.지평}  NE57 {r['NE57_8km']:.3f} | R030 {r['R030_3km']:.3f} | "
              f"L010 {r['L010_1.3km']:.3f}   L010vsR030 {r['L010 vs R030']:+.1f}%  (n={int(r.n)})")
    print()

# ── 그림 ────────────────────────────────────────────────────────────────
fig, axes = plt.subplots(1, 3, figsize=(12, 3.8))
for ax, (col, lab, _) in zip(axes, VARS):
    t = tab[tab.변수 == lab].reset_index(drop=True)
    x = np.arange(len(t)); w = 0.26
    ax.bar(x - w, t["NE57_8km"], w, label="NE57 8km", color="#e08e0b")
    ax.bar(x, t["R030_3km"], w, label="R030 3km", color="#2b6cb0")
    ax.bar(x + w, t["L010_1.3km"], w, label="L010 1.3km", color="#1a7f37")
    ax.set_xticks(x); ax.set_xticklabels(t.지평); ax.set_title(lab, fontsize=10.5)
    if ax is axes[0]:
        ax.set_ylabel("실측 대비 MAE"); ax.legend(fontsize=8)
fig.suptitle("L010 도입 판단: 국지(1.3km) vs 지역(3km) vs 전구(8km) — D+1~2 정밀도 (장마 9일, 육지)",
             fontsize=11.5, y=1.03)
fig.tight_layout()
fig.savefig(L.FIGS / "c4_l010_decision.png", bbox_inches="tight", dpi=120)
print("저장:", L.FIGS / "c4_l010_decision.png")

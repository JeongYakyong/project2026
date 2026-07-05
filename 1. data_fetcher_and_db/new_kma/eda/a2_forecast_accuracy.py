"""예보 정확도 스트레스 테스트 — 장마철 9일, 지평별 실측 대비.
R030 1시간(v2) vs NE57 3시간+보간(현행 cur) 를 같은 발행일·같은 실측으로 A/B.

정직 규율: D+n 24h 블록의 전 시각 평가(24배수 지평만 보면 origin 1시각만 평가되는 낙관편향 회피).
일사·운량은 낮 시각(태양고도>8deg)만.
"""
import sys; sys.stdout.reconfigure(encoding="utf-8")
import sqlite3
import numpy as np, pandas as pd
import eda_lib as L

plt = L.setup_mpl()
REG = "land"

def load_db(path, cols_base):
    con = sqlite3.connect(path)
    df = pd.read_sql("SELECT * FROM forecast_horizon", con,
                     parse_dates=["timestamp", "base"]).rename(columns={"timestamp": "ts"})
    con.close()
    return L.melt_points(df, REG, cols_base)

BASE_COLS = ["radiation", "temp", "wind_spd_10m", "total_cloud", "total_cloud_r030"]
v2  = load_db(L.DB_V2_LAND, BASE_COLS).add_suffix("_v2").rename(
        columns={"base_v2": "base", "ts_v2": "ts", "horizon_d_v2": "horizon_d", "sfx_v2": "sfx"})
cur = load_db(L.DB_LAND.parent / "cur_land.db", BASE_COLS).add_suffix("_cur").rename(
        columns={"base_cur": "base", "ts_cur": "ts", "horizon_d_cur": "horizon_d", "sfx_cur": "sfx"})

# 공통 9 발행일로 교집합
common = sorted(set(v2.base.unique()) & set(cur.base.unique()))
v2 = v2[v2.base.isin(common)]; cur = cur[cur.base.isin(common)]
fc = v2.merge(cur, on=["base", "ts", "horizon_d", "sfx"], how="inner")

# 실측·태양고도 결합
ac = L.load_actuals(REG)
geo = L.solar_geometry(REG)
act_long = []
for p in L.POINTS[REG]:
    s = p["sfx"]
    m = {f"solar_rad_{s}": "radiation_act", f"temp_c_{s}": "temp_act",
         f"wind_spd_{s}": "wind_spd_10m_act", f"total_cloud_{s}": "total_cloud_act"}
    have = {k: v for k, v in m.items() if k in ac.columns}
    sub = ac[["ts"] + list(have)].rename(columns=have).copy(); sub["sfx"] = s
    act_long.append(sub)
act_long = pd.concat(act_long, ignore_index=True)

df = fc.merge(act_long, on=["ts", "sfx"], how="left").merge(geo, on=["ts", "sfx"], how="left")
df["is_day"] = df.elev > 8

print(f"발행일 {len(common)}개, 결합행 {len(df)}, 지평 {sorted(df.horizon_d.unique())}")

# ── 지평별 MAE 표 ────────────────────────────────────────────────────────
# (v2컬럼, cur컬럼, 실측컬럼, 라벨, 낮만)
VARS = [
    ("radiation_v2",        "radiation_cur",   "radiation_act",    "일사(MJ)",     True),
    ("temp_v2",             "temp_cur",        "temp_act",         "기온(°C)",     False),
    ("wind_spd_10m_v2",     "wind_spd_10m_cur","wind_spd_10m_act", "10m바람(m/s)", False),
    ("total_cloud_r030_v2", "total_cloud_cur", "total_cloud_act",  "운량(0~1)",    True),
]
rows = []
for h in range(1, 6):
    sub = df[df.horizon_d == h]
    for vcol, ccol, acol, lab, dayonly in VARS:
        s = sub[sub.is_day] if dayonly else sub
        rows.append({"지평": f"D+{h}", "변수": lab,
                     "v2_1h": L.mae(s[vcol], s[acol]),
                     "cur_3h": L.mae(s[ccol], s[acol]),
                     "n": (s[vcol].notna() & s[acol].notna()).sum()})
tab = pd.DataFrame(rows)
tab["개선%"] = (1 - tab.v2_1h / tab.cur_3h) * 100
print("\n=== 지평별 MAE (v2 R030 1h vs cur NE57 3h+보간) ===")
for lab in tab.변수.unique():
    t = tab[tab.변수 == lab]
    print(f"\n[{lab}]")
    for _, r in t.iterrows():
        print(f"  {r.지평}  v2={r.v2_1h:6.3f}  cur={r.cur_3h:6.3f}  "
              f"개선 {r['개선%']:+5.1f}%  (n={int(r.n)})")

# ── 그림 1: 지평별 개선율 ────────────────────────────────────────────────
fig, axes = plt.subplots(1, 4, figsize=(12.5, 3.4), sharex=True)
for ax, (_, _, _, lab, _) in zip(axes, VARS):
    t = tab[tab.변수 == lab].reset_index(drop=True)
    x = np.arange(len(t))
    ax.bar(x - 0.2, t.cur_3h, 0.4, label="현행 3시간", color="#9aa5b1")
    ax.bar(x + 0.2, t.v2_1h, 0.4, label="신규 1시간(R030)", color="#2b6cb0")
    ax.set_xticks(x); ax.set_xticklabels(t.지평, fontsize=8)
    ax.set_title(lab, fontsize=10)
    for i in range(len(t)):
        imp = t.loc[i, "개선%"]
        ax.annotate(f"{imp:+.0f}%", (i, max(t.loc[i, "v2_1h"], t.loc[i, "cur_3h"])),
                    ha="center", va="bottom", fontsize=7.5,
                    color="#1a7f37" if imp > 0 else "#c0392b")
axes[0].set_ylabel("평균절대오차 (낮을수록 좋음)")
axes[0].legend(fontsize=8, loc="upper left")
fig.suptitle("신규 변수 검증 ② 예보 정확도 — 실측 대비 지평별 (장마철 9일, 육지 5지점)",
             fontsize=12, y=1.03)
fig.tight_layout()
fig.savefig(L.FIGS / "a2_accuracy_horizon.png", bbox_inches="tight", dpi=120)
print("\n저장:", L.FIGS / "a2_accuracy_horizon.png")

# ── 그림 2: 대표 일 일사 일변화 추적 (1h vs 3h vs 실측) ───────────────────
# 서산 D+1, 가장 표본 좋은 발행일 하나
pt = "seosan"
one = df[(df.sfx == pt) & (df.horizon_d == 1)].sort_values("ts")
# 한 발행일(48h D+1 블록) 선택
b0 = sorted(one.base.unique())[3]
seg = one[one.base == b0]
fig, ax = plt.subplots(figsize=(8.4, 3.6))
ax.plot(seg.ts, seg.radiation_act, "-o", ms=4, color="#111", label="실측", zorder=3)
ax.plot(seg.ts, seg.radiation_cur, "--s", ms=3, color="#9aa5b1", label="현행 3시간+보간")
ax.plot(seg.ts, seg.radiation_v2, "-^", ms=3, color="#2b6cb0", label="신규 1시간(R030)")
ax.set_ylabel("일사 (MJ/m²/h)")
ax.set_title(f"장마철 하루 일사 예보 — 서산 D+1 ({pd.Timestamp(b0).date()} 발행)", fontsize=11)
ax.legend(fontsize=8)
fig.autofmt_xdate()
fig.tight_layout()
fig.savefig(L.FIGS / "a2_day_trace.png", bbox_inches="tight", dpi=120)
print("저장:", L.FIGS / "a2_day_trace.png")
tab.to_csv(L.FIGS.parent / "a2_accuracy_table.csv", index=False, encoding="utf-8-sig")

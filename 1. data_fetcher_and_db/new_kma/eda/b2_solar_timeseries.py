"""일사 전체 시계열 + 편향 보정 what-if.
D+1 예보(신규 R030 1h / 현행 NE57 3h)를 실측과 9일 연속으로 겹쳐 본다.
맑은 날·흐린 날이 눈으로 구분되게, 그리고 "한낮 편향만 빼면" 얼마나 좁혀지는지.
"""
import sys; sys.stdout.reconfigure(encoding="utf-8")
import sqlite3
import numpy as np, pandas as pd
import eda_lib as L

plt = L.setup_mpl()
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
ac = L.load_actuals(REG); geo = L.solar_geometry(REG)
al = []
for p in L.POINTS[REG]:
    s = p["sfx"]
    al.append(ac[["ts", f"solar_rad_{s}"]].rename(columns={f"solar_rad_{s}": "act"}).assign(sfx=s))
al = pd.concat(al, ignore_index=True)
df = fc.merge(al, on=["ts", "sfx"], how="left").merge(geo, on=["ts", "sfx"], how="left")
d1 = df[df.horizon_d == 1].copy()          # D+1, 야간 포함(0 근처)

# ── 편향 보정: 낮 시각(elev>8) 지점공통 시각대별 평균편향을 빼기 ────────────
day = d1[d1.elev > 8].copy()
bias_by_hour = (day.assign(h=day.ts.dt.hour)
                    .groupby("h").apply(lambda x: L.bias(x.v2, x.act), include_groups=False))
d1["h"] = d1.ts.dt.hour
d1["v2_bc"] = d1.v2 - d1.h.map(bias_by_hour).fillna(0.0)
d1["v2_bc"] = d1.v2_bc.clip(lower=0)
day = d1[d1.elev > 8]
print("=== 편향 보정 전/후 (D+1 낮) ===")
print(f"  현행 NE57 3h   MAE {L.mae(day.cur,day.act):.3f}")
print(f"  신규 R030 1h   MAE {L.mae(day.v2,day.act):.3f}  (bias {L.bias(day.v2,day.act):+.3f})")
print(f"  신규 편향보정  MAE {L.mae(day.v2_bc,day.act):.3f}  (bias {L.bias(day.v2_bc,day.act):+.3f})")
print(f"  → 한낮 편향만 제거해도 신규가 현행에 근접/역전 가능한지 확인")

# ── 그림 1: 9일 연속 시계열 (2지점) ───────────────────────────────────────
pts = [("seosan", "서산"), ("yeonggwang", "영광")]
fig, axes = plt.subplots(len(pts), 1, figsize=(12, 6.2), sharex=False)
for ax, (sfx, ko) in zip(axes, pts):
    s = d1[d1.sfx == sfx].sort_values("ts")
    ax.fill_between(s.ts, 0, s.act, color="#111", alpha=0.10)
    ax.plot(s.ts, s.act, "-", color="#111", lw=1.6, label="실측")
    ax.plot(s.ts, s.cur, "-", color="#e08e0b", lw=1.1, alpha=0.9, label="현행 3시간")
    ax.plot(s.ts, s.v2, "-", color="#2b6cb0", lw=1.1, alpha=0.9, label="신규 1시간(R030)")
    # 맑음/흐림 일 표시(낮평균 실측)
    for d, sub in s.groupby(s.ts.dt.date):
        pk = sub.act.max()
        lab = "맑음" if pk > 2.6 else ("흐림" if pk < 1.3 else "")
        if lab:
            ax.annotate(lab, (pd.Timestamp(d) + pd.Timedelta(hours=12), pk + 0.15),
                        ha="center", fontsize=7.5, color="#1a7f37" if lab == "맑음" else "#c0392b")
    ax.set_ylabel(f"{ko}\n일사(MJ/m²/h)")
    ax.set_ylim(0, 4.2)
    if ax is axes[0]:
        ax.legend(fontsize=8, ncol=3, loc="upper right")
        ax.set_title("D+1 일사 예보 9일 연속 — 실측 vs 현행 vs 신규 (장마철, 각 그래프=하루 반복)",
                     fontsize=11)
axes[-1].tick_params(axis="x", labelrotation=0, labelsize=8)
fig.tight_layout()
fig.savefig(L.FIGS / "b2_timeseries_9day.png", bbox_inches="tight", dpi=120)
print("\n저장:", L.FIGS / "b2_timeseries_9day.png")

# ── 그림 2: 맑은 날 2 + 흐린 날 2 (서산·영광 중 대비 큰 날) ────────────────
def day_type(sub):
    pk = sub.act.max()
    return "맑음" if pk > 2.6 else ("흐림" if pk < 1.3 else "보통")
cat = []
for (sfx, d), sub in d1.groupby([d1.sfx, d1.ts.dt.date]):
    cat.append((sfx, d, sub.act.max()))
cat = pd.DataFrame(cat, columns=["sfx", "d", "pk"])
cat = cat[cat.pk > 0.6]                       # 거의 무일사 날 제외
# 맑은 2일(최고피크, 지점 다르게) + 흐린 2일(최저피크, 지점 다르게)
def pick(sorted_cat):
    out = []
    for _, r in sorted_cat.iterrows():
        if r.sfx not in [x.sfx for x in out]:
            out.append(r)
        if len(out) == 2:
            break
    return out
clear = pd.DataFrame(pick(cat.sort_values("pk", ascending=False)))
clear["type"] = "맑음"
cloud = pd.DataFrame(pick(cat.sort_values("pk")))
cloud["type"] = "흐림"
sel = pd.concat([clear, cloud])
fig, axes = plt.subplots(2, 2, figsize=(11, 6))
for ax, (_, r) in zip(axes.ravel(), sel.iterrows()):
    s = d1[(d1.sfx == r.sfx) & (d1.ts.dt.date == r.d)].sort_values("ts")
    ax.fill_between(s.ts, 0, s.act, color="#111", alpha=0.10)
    ax.plot(s.ts, s.act, "-o", ms=3, color="#111", lw=1.6, label="실측")
    ax.plot(s.ts, s.cur, "--s", ms=2.5, color="#e08e0b", lw=1.0, label="현행 3시간")
    ax.plot(s.ts, s.v2, "-^", ms=2.5, color="#2b6cb0", lw=1.0, label="신규 1시간")
    ko = dict(L.POINTS[REG][0].items()) and next(p["ko"] for p in L.POINTS[REG] if p["sfx"] == r.sfx)
    ax.set_title(f"[{r.type}] {ko} {r.d}", fontsize=10,
                 color="#1a7f37" if r.type == "맑음" else "#c0392b")
    ax.set_ylabel("일사(MJ/m²/h)"); ax.set_ylim(0, 4.2)
    ax.tick_params(axis="x", labelrotation=30, labelsize=7)
axes[0, 0].legend(fontsize=8, loc="upper right")
fig.suptitle("맑은 날 vs 흐린 날 하루 일사 예보 (D+1)", fontsize=12, y=1.01)
fig.tight_layout()
fig.savefig(L.FIGS / "b2_clear_vs_cloudy.png", bbox_inches="tight", dpi=120)
print("저장:", L.FIGS / "b2_clear_vs_cloudy.png")

# ── 그림 3: 시각대별 편향 + 보정효과 ──────────────────────────────────────
fig, (a1, a2) = plt.subplots(1, 2, figsize=(11, 3.6))
hh = sorted(day.ts.dt.hour.unique())
bv = [L.bias(day[day.ts.dt.hour == h].v2, day[day.ts.dt.hour == h].act) for h in hh]
bc = [L.bias(day[day.ts.dt.hour == h].cur, day[day.ts.dt.hour == h].act) for h in hh]
a1.axhline(0, color="k", lw=0.8)
a1.plot(hh, bc, "-s", color="#e08e0b", label="현행 3시간")
a1.plot(hh, bv, "-^", color="#2b6cb0", label="신규 1시간(R030)")
a1.set_xlabel("시각(시)"); a1.set_ylabel("편향 = 예보-실측 (MJ)")
a1.set_title("(가) 신규는 한낮에 계통적 과대", fontsize=10.5); a1.legend(fontsize=8)
mae_before = [L.mae(day.cur, day.act), L.mae(day.v2, day.act), L.mae(day.v2_bc, day.act)]
a2.bar(["현행\n3시간", "신규\n1시간", "신규\n편향보정후"], mae_before,
       color=["#e08e0b", "#2b6cb0", "#1a7f37"])
for i, v in enumerate(mae_before):
    a2.annotate(f"{v:.3f}", (i, v), ha="center", va="bottom", fontsize=9)
a2.set_ylabel("평균절대오차 (MJ)")
a2.set_title("(나) 한낮 편향만 빼면 크게 좁혀짐", fontsize=10.5)
fig.suptitle("일사 오차의 정체 = 보정 가능한 한낮 과대편향", fontsize=12, y=1.02)
fig.tight_layout()
fig.savefig(L.FIGS / "b2_bias_correction.png", bbox_inches="tight", dpi=120)
print("저장:", L.FIGS / "b2_bias_correction.png")

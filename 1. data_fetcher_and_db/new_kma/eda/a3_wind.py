"""풍력 신규 변수 — 80m 바람·돌풍(gust). 장마철 9일.

핵심 질문:
 (1) 신규 80m 바람이 10m 대비 물리적으로 타당한가 (연직 시어: 80m > 10m)
 (2) 발전기 허브고도(≈80~100m)에 가까운 80m 바람이 실제 풍력 발전과 10m 보다 잘 맞는가
     -> 맞으면 "허브고도 바람 = 풍력에 더 유효한 신규 입력"이라는 근거
"""
import sys; sys.stdout.reconfigure(encoding="utf-8")
import numpy as np, pandas as pd
import eda_lib as L

plt = L.setup_mpl()

def wind_frame(region):
    fc = L.load_forecast(region)
    w = L.melt_points(fc, region, ["wind_spd_10m", "wind_spd_80m", "gust"])
    return w

# (1) 시어 — 전 지점 풀 (육지+제주)
allw = []
for reg in ("land", "jeju"):
    w = wind_frame(reg); w["region"] = reg; allw.append(w)
allw = pd.concat(allw, ignore_index=True)
allw = allw[(allw.wind_spd_10m > 0.3)]         # 미풍 잡음 제거
allw["shear"] = allw.wind_spd_80m / allw.wind_spd_10m
print("=== (1) 연직 시어 80m/10m ===")
print(f"  표본 {len(allw)}, 중앙값 {allw.shear.median():.2f}, "
      f"80m>10m 비율 {(allw.wind_spd_80m>allw.wind_spd_10m).mean()*100:.0f}%")
print(f"  gust>80m(돌풍이 평균풍속 상회) 비율 {(allw.gust>allw.wind_spd_80m).mean()*100:.0f}%")

# (2) 풍력 발전과의 관계 — 제주(국지·직접) + 육지
def wind_vs_gen(region, gen_col, gen_db):
    import sqlite3
    fc = L.load_forecast(region)
    w = L.melt_points(fc, region, ["wind_spd_10m", "wind_spd_80m", "gust"])
    d1 = w[w.horizon_d == 1]
    agg = d1.groupby("ts")[["wind_spd_10m", "wind_spd_80m", "gust"]].mean().reset_index()
    con = sqlite3.connect(gen_db)
    g = pd.read_sql(f"SELECT timestamp AS ts,{gen_col} FROM historical "
                    f"WHERE timestamp>='2026-06-25'", con, parse_dates=["ts"])
    con.close()
    m = agg.merge(g, on="ts", how="inner").dropna()
    return m

res = {}
for region, gen_col, db in [("jeju", "real_wind_gen_jeju", L.DB_JEJU),
                            ("land", "gen_wind_kr", L.DB_LAND)]:
    m = wind_vs_gen(region, gen_col, db)
    r10 = m[["wind_spd_10m", gen_col]].corr().iloc[0, 1]
    r80 = m[["wind_spd_80m", gen_col]].corr().iloc[0, 1]
    rg  = m[["gust", gen_col]].corr().iloc[0, 1]
    res[region] = (m, gen_col, r10, r80, rg)
    print(f"\n=== (2) {region} 풍력발전 상관 (D+1, n={len(m)}) ===")
    print(f"  10m 바람 r={r10:+.3f}   80m 바람 r={r80:+.3f}   돌풍 r={rg:+.3f}")
    print(f"  -> 80m 가 10m 보다 {'우세' if abs(r80)>abs(r10) else '열세'} "
          f"(|Δr|={abs(r80)-abs(r10):+.3f})")

# ── 그림 ────────────────────────────────────────────────────────────────
fig, axes = plt.subplots(1, 3, figsize=(12, 3.6))

# (가) 시어 분포
ax = axes[0]
ax.hist(allw.shear.clip(0.5, 2.5), bins=30, color="#2b6cb0", alpha=0.8)
ax.axvline(1.0, color="#c0392b", ls="--", lw=1.4, label="80m=10m")
ax.axvline(allw.shear.median(), color="#1a7f37", ls="-", lw=1.4,
           label=f"중앙값 {allw.shear.median():.2f}")
ax.set_xlabel("연직 시어 = 80m풍속 / 10m풍속")
ax.set_ylabel("시간 수")
ax.set_title("(가) 80m 바람은 대체로 10m보다 강함", fontsize=10.5)
ax.legend(fontsize=8)

# (나),(다) 제주·육지 80m 바람 vs 발전
for ax, region in zip(axes[1:], ("jeju", "land")):
    m, gen_col, r10, r80, rg = res[region]
    ax.scatter(m.wind_spd_80m, m[gen_col], s=12, alpha=0.5, c="#2b6cb0", edgecolors="none")
    ax.set_xlabel("80m 예보 풍속 (m/s, 지점평균 D+1)")
    ax.set_ylabel(f"{'제주' if region=='jeju' else '전국'} 풍력발전 (MW)")
    ax.set_title(f"({'나' if region=='jeju' else '다'}) {'제주' if region=='jeju' else '전국'}"
                 f"  80m r={r80:+.2f} (10m {r10:+.2f})", fontsize=10.5)

fig.suptitle("신규 변수 검증 ③ 허브고도(80m) 바람·돌풍 — 장마철 9일", fontsize=12, y=1.03)
fig.tight_layout()
fig.savefig(L.FIGS / "a3_wind.png", bbox_inches="tight", dpi=120)
print("\n저장:", L.FIGS / "a3_wind.png")

"""태양광 신규 변수(직달/산란 분리) 물리 검증 — 장마철 9일.

핵심 질문:
 (1) GHI = 직달 + 산란 이 전 지점·전 시각에서 성립하는가 (합 정합)
 (2) 산란비율 kd = 산란/GHI 이 청명도 Kt 와 물리적으로 맞물리는가 (Erbs 관계 대조)
     -> 맞으면 "신규 변수가 물리적으로 일관된 실제 정보"라는 신뢰도 근거
 (3) 장마철에 산란이 실제로 얼마나 지배적인가 (현행 단일 GHI 가 버리는 정보의 크기)
"""
import sys; sys.stdout.reconfigure(encoding="utf-8")
import numpy as np, pandas as pd
import pvlib
import eda_lib as L

plt = L.setup_mpl()
REG = "land"
fc = L.load_forecast(REG)
geo = L.solar_geometry(REG)

# 지점 long: GHI(radiation), 직달, 산란
sol = L.melt_points(fc, REG, ["radiation", "radiation_direct", "radiation_diffuse",
                              "total_cloud", "total_cloud_r030"])
sol = sol.merge(geo, on=["ts", "sfx"], how="left")

# (1) 합 정합
sol["ghi_sum"] = sol.radiation_direct + sol.radiation_diffuse
resid = (sol.radiation - sol.ghi_sum).abs()
print("=== (1) 합 정합 GHI vs 직달+산란 ===")
print(f"  최대 잔차 {resid.max():.5f} MJ, 평균 {resid.mean():.6f} (반올림 4자리 한계)")

# 청명도 Kt = GHI / TOA수평면.  TOA = I0n * cos(zenith).
doy = sol.ts.dt.dayofyear
I0n = np.asarray(pvlib.irradiance.get_extra_radiation(doy))  # W/m^2
cosz = np.sin(np.radians(sol.elev.clip(lower=0)))
toa_mj = I0n * cosz * L.MJ
sol["toa_mj"] = toa_mj
day = sol[(sol.elev > 10) & (sol.toa_mj > 0.05)].copy()   # 낮 시각만
day["Kt"] = (day.radiation / day.toa_mj).clip(0, 1.2)
day["kd"] = (day.radiation_diffuse / day.radiation.replace(0, np.nan)).clip(0, 1)
day = day.dropna(subset=["Kt", "kd"])

# Erbs 상관식(기준 물리 곡선): kd(Kt)
def erbs_kd(kt):
    kt = np.asarray(kt)
    out = np.where(kt <= 0.22, 1 - 0.09*kt,
          np.where(kt <= 0.80,
                   0.9511 - 0.1604*kt + 4.388*kt**2 - 16.638*kt**3 + 12.336*kt**4,
                   0.165))
    return out

# kd 예측(모델 산란비율)과 Erbs 곡선의 근접도
day["kd_erbs"] = erbs_kd(day.Kt)
mae_erbs = (day.kd - day.kd_erbs).abs().mean()
print("\n=== (2) 산란비율 vs 청명도 (물리 일관성) ===")
print(f"  낮 표본 {len(day)}개 (elev>10deg)")
print(f"  모델 kd 와 Erbs 물리곡선 평균절대차 {mae_erbs:.3f} (작을수록 물리 일관)")
print(f"  상관: Kt vs kd  r={day[['Kt','kd']].corr().iloc[0,1]:+.3f} (음이어야 물리적)")

print("\n=== (3) 장마철 산란 지배도 ===")
print(f"  낮 시각 평균 산란비율 kd = {day.kd.mean():.2f}  중앙값 {day.kd.median():.2f}")
print(f"  kd>0.5(산란 우세) 시간 비율: {(day.kd>0.5).mean()*100:.0f}%")
print(f"  운량(R030 1h) vs kd 상관 r={day[['total_cloud_r030','kd']].corr().iloc[0,1]:+.3f}"
      f" (관측 n={day[['total_cloud_r030','kd']].dropna().shape[0]})")

# ── 그림 ────────────────────────────────────────────────────────────────
fig, axes = plt.subplots(1, 3, figsize=(11.5, 3.7))

# (a) 산란비율 vs 청명도 + Erbs 곡선
ax = axes[0]
sc = ax.scatter(day.Kt, day.kd, s=7, alpha=0.35, c="#2b6cb0", edgecolors="none",
                label="KIM 예보(지점·시각)")
kt_line = np.linspace(0.02, 1.0, 200)
ax.plot(kt_line, erbs_kd(kt_line), color="#c0392b", lw=2, label="물리 기준곡선(Erbs)")
ax.set_xlabel("청명도 Kt = 전천일사 / 대기밖일사")
ax.set_ylabel("산란 비율 = 산란 / 전천일사")
ax.set_title("(가) 직달·산란 분리의 물리 일관성", fontsize=11)
ax.legend(fontsize=8, loc="upper right")
ax.set_xlim(0, 1); ax.set_ylim(0, 1.05)

# (b) 장마철 산란비율 분포
ax = axes[1]
ax.hist(day.kd, bins=24, color="#2b6cb0", alpha=0.8)
ax.axvline(day.kd.mean(), color="#c0392b", lw=1.6, ls="--",
           label=f"평균 {day.kd.mean():.2f}")
ax.set_xlabel("산란 비율 (낮 시각)")
ax.set_ylabel("시간 수")
ax.set_title("(나) 장마철엔 산란이 지배적", fontsize=11)
ax.legend(fontsize=8)

# (c) 운량↔산란비율
ax = axes[2]
d2 = day.dropna(subset=["total_cloud_r030"])
ax.scatter(d2.total_cloud_r030, d2.kd, s=8, alpha=0.35, c="#2b6cb0", edgecolors="none")
ax.set_xlabel("1시간 운량 (R030, 0~1)")
ax.set_ylabel("산란 비율")
ax.set_title("(다) 구름 많을수록 산란↑", fontsize=11)
ax.set_xlim(0, 1); ax.set_ylim(0, 1.05)

fig.suptitle("신규 변수 검증 ① 직달/산란 일사 — 장마철 9일 (육지 5지점)",
             fontsize=12, y=1.02)
fig.tight_layout()
fig.savefig(L.FIGS / "a1_solar_physics.png", bbox_inches="tight", dpi=120)
print("\n저장:", L.FIGS / "a1_solar_physics.png")

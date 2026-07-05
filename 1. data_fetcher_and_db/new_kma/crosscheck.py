"""crosscheck.py -- Phase 4: 신구 API 교차검증 + 일사 물리 검증 + ACSWDNB 규칙.

A) 구 grib(kim_grib_pt_tmfc.php, varn 코드) vs 신 std -- 같은 R030 모델을 두 API 로
   읽었을 때 값이 일치하는가 (제주 솔라팜 550,250 -- 신구 X/Y 동일 지점).
B) 일사 삼각검증 (서산, L010): SWDDIR2+SWDDIF2 = GHI 인지, SWDDIR2 가 수평면
   직달인지(= SWDDNI2 x cosZ), NE57 dswrsfc 와의 관계.
C) ACSWDNB(누적 MJ/m^2) 리셋 규칙: hf=1..21 연속열에서 diff 가 순시값과 정합하는지.
결과: results/crosscheck_r030.csv, results/solar_seq.csv
"""
import sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import numpy as np
import pandas as pd
import probe_lib as pl

tmfc = pl.latest_tmfc(12)


def new_val(grp, nwp, nm, hf, x, y):
    b = pl.fetch_std(grp, nwp, nm, tmfc, hf, x, y)
    if not b or "ERROR" in b:
        return None
    vs = [float(t) for l in b.splitlines()
          if l.strip() and not l.startswith("#") for t in l.split()]
    return vs[0] if vs else None


# ── A) 구 grib vs 신 std (R030, 솔라팜 550,250) ────────────────────────────
# 구: varn 멀티 + ef 범위 = 1콜.  varn 0=tmpr(2m K), 17=tmps(skin), 1001=rhwt(2m %),
#     2002/2003=U/V(level 10/80), 2022=gust
old_body = pl.fetch(pl.URL_OLD_GRIB, {
    "group": "KIMR", "nwp": "r030", "data": "U",
    "varn": "0,17,1001,2002,2003,2022",
    "tmfc": tmfc, "ef": "12,21,1", "X": 550, "Y": 250,
})
old_rows = []
for ln in (old_body or "").splitlines():
    s = ln.strip()
    if not s or s.startswith("#"):
        continue
    p = s.split()
    # 포맷: TMFC TMEF VARN LEVEL VALUS NAME... (구 pt 와 동일 계열)
    if len(p) >= 5:
        try:
            old_rows.append({"tmef": p[1], "varn": int(p[2]),
                             "level": int(p[3]), "value": float(p[4])})
        except ValueError:
            continue
old = pd.DataFrame(old_rows)
print(f"[A] 구 grib 응답 행수: {len(old)}")
if len(old):
    print(old.head(8).to_string(index=False))

# 신 std 같은 시각대 (hf 12..21)
NEW_VARS = ["T2", "TSKIN", "RH2", "U10", "V10", "U80", "V80", "GUST"]
new_rows = []
for hf in range(12, 22):
    for nm in NEW_VARS:
        new_rows.append({"hf": hf, "var": nm,
                         "value": new_val("KIMR", "R030", nm, hf, 550, 250)})
new = pd.DataFrame(new_rows)

# 매핑: (varn, level) -> 신 변수명
MAP = {(0, 2): "T2", (17, 0): "TSKIN", (1001, 2): "RH2",
       (2002, 10): "U10", (2003, 10): "V10",
       (2002, 80): "U80", (2003, 80): "V80", (2022, 0): "GUST"}
if len(old):
    old["var"] = old.apply(lambda r: MAP.get((r.varn, r.level)), axis=1)
    old = old.dropna(subset=["var"])
    # tmef(UTC) -> hf
    old["hf"] = (pd.to_datetime(old.tmef, format="%Y%m%d%H")
                 - pd.to_datetime(tmfc, format="%Y%m%d%H")).dt.total_seconds() // 3600
    cmp = old.merge(new, on=["hf", "var"], suffixes=("_old", "_new"))
    cmp["diff"] = cmp.value_new - cmp.value_old
    cmp.to_csv("results/crosscheck_r030.csv", index=False, encoding="utf-8-sig")
    print("\n[A] 신구 R030 비교 (hf 12~21 평균):")
    print(cmp.groupby("var")[["value_old", "value_new", "diff"]]
          .mean().round(3).to_string())
    print("변수별 최대 |diff|:")
    print(cmp.groupby("var")["diff"].apply(lambda s: s.abs().max()).round(3).to_string())

# ── B+C) 일사 시퀀스 (서산 L010 631,635 / R030 539,376) + NE57 dswrsfc ─────
seq = []
for hf in range(0, 22):
    row = {"hf": hf}
    for nm in ["SWDDIR2", "SWDDIF2", "SWDDNI2", "ACSWDNB"]:
        row[nm] = new_val("KIML", "L010", nm, hf, 631, 635)
    if hf % 3 == 0:
        row["dswrsfc_ne57"] = new_val("KIMG", "NE57", "dswrsfc", hf, 1519, 1522)
    for nm in ["SWDDIR2", "SWDDIF2"]:
        row[nm + "_r030"] = new_val("KIMR", "R030", nm, hf, 539, 376)
    seq.append(row)
sq = pd.DataFrame(seq)

# 태양천정각 cosZ (서산 36.7766N 126.4939E, NOAA 근사)
def cos_zenith(dt_utc, lat, lon):
    doy = dt_utc.timetuple().tm_yday
    frac = doy - 1 + (dt_utc.hour + dt_utc.minute / 60) / 24
    g = 2 * np.pi / 365 * frac
    decl = (0.006918 - 0.399912 * np.cos(g) + 0.070257 * np.sin(g)
            - 0.006758 * np.cos(2 * g) + 0.000907 * np.sin(2 * g)
            - 0.002697 * np.cos(3 * g) + 0.00148 * np.sin(3 * g))
    eqtime = 229.18 * (0.000075 + 0.001868 * np.cos(g) - 0.032077 * np.sin(g)
                       - 0.014615 * np.cos(2 * g) - 0.040849 * np.sin(2 * g))
    tst = dt_utc.hour * 60 + dt_utc.minute + eqtime + 4 * lon
    ha = np.radians(tst / 4 - 180)
    la = np.radians(lat)
    return np.sin(la) * np.sin(decl) + np.cos(la) * np.cos(decl) * np.cos(ha)

base = pd.to_datetime(tmfc, format="%Y%m%d%H").tz_localize("UTC")
sq["valid_utc"] = base + pd.to_timedelta(sq.hf, unit="h")
sq["cosZ"] = [max(cos_zenith(t.to_pydatetime(), 36.7766, 126.4939), 0.0)
              for t in sq.valid_utc]
sq["ghi_sum"] = sq.SWDDIR2 + sq.SWDDIF2                 # 후보: 직달수평+산란
sq["dni_cosz"] = sq.SWDDNI2 * sq.cosZ                   # 법선직달 x cosZ
sq["acswdnb_diff_MJ"] = sq.ACSWDNB.diff()               # 시간당 증가분 (MJ)
sq["ghi_sum_MJ"] = sq.ghi_sum * 3600 / 1e6              # 순시 W/m^2 -> MJ/h 환산
sq.to_csv("results/solar_seq.csv", index=False, encoding="utf-8-sig")
print("\n[B] 일사 시퀀스 (서산, KST=UTC+9):")
show = sq[["hf", "cosZ", "SWDDIR2", "SWDDIF2", "SWDDNI2", "dni_cosz",
           "ghi_sum", "ACSWDNB", "acswdnb_diff_MJ", "ghi_sum_MJ", "dswrsfc_ne57"]]
print(show.round(3).to_string(index=False))
print("\nbudget:", pl.budget_status())

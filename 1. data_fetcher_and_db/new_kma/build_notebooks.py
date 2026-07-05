"""build_notebooks.py -- 연구 노트북 4부를 생성하고 실행한다.

모든 노트북은 probe_cache/ 를 통해서만 데이터를 읽으므로 재실행해도
API 실호출이 0 이다 (probe_lib 캐시 우선 설계).
"""
import sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import nbformat as nbf
from nbclient import NotebookClient
from pathlib import Path

HERE = Path(__file__).resolve().parent

PRELUDE = '''\
import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import numpy as np
import pandas as pd
import probe_lib as pl
pd.set_option("display.width", 220)
pd.set_option("display.max_columns", 60)

def std_val(grp, nwp, nm, tmfc, hf, x, y, data="U", level=None):
    """캐시된 신규 std 응답에서 첫 값 (캐시에 없으면 실호출 1회)."""
    b = pl.fetch_std(grp, nwp, nm, tmfc, hf, x, y, data=data, level=level)
    if not b or "ERROR" in b:
        return None
    v = [float(t) for l in b.splitlines()
         if l.strip() and not l.startswith("#") for t in l.split()]
    return v[0] if v else None

TMFC = "2026070312"   # 본 연구의 기준 발표 (2026-07-03 12z) -- 캐시 고정
print("호출 예산 상태:", pl.budget_status())'''


def nb(cells):
    n = nbf.v4.new_notebook()
    n.cells = []
    for kind, src in cells:
        if kind == "md":
            n.cells.append(nbf.v4.new_markdown_cell(src))
        else:
            n.cells.append(nbf.v4.new_code_cell(src))
    return n


# ── nb01: 격자 준비 ──────────────────────────────────────────────────────
nb01 = nb([
    ("md", """# nb01 — 신규 KIM 격자 준비와 8지점 변환

2026-07-01 정책 변경으로 도입된 신규 표준 API(`nph-kim_nc_xy_txt2_std`)는 격자 X/Y 로 지점을 지정한다.
이 노트북은 세 모델의 격자를 확보하고, 운영 8지점(육지 5 + 제주 3)의 X/Y 변환표를 만든다.

| 모델 | nwp | 격자 | 해상도 | 투영 |
|---|---|---|---|---|
| 전구 | NE57 | g576 (4320×2160) | 약 8 km | 위경도 등간격 |
| 지역 | R030 | r030 (1049×839) | 약 3 km | Lambert |
| 국지 | L010 | l010 (1535×1175) | 약 1.3 km | Lambert |

**확인된 함정**: 격자 조회 API(`nph-nwp_latlon_api`, disp=B)는 앞 4바이트가 (행수, 열수) short 2개이고,
돌려주는 격자가 자료 격자보다 행·열이 1 큰 **셀 모서리** 격자다. 4모서리 평균 = 자료 격자(셀 중심)와
1e-5도 수준으로 일치함을 r030 보유 nc 파일로 검증했다. l010 은 이 방법으로 중심 격자를 만들어
`grids/kim_l010_latlon.npz` 로 저장했다."""),
    ("code", PRELUDE),
    ("code", '''\
# 세 격자 로드 (g576/r030 = 제공받은 nc, l010 = API 바이너리 -> 셀 중심 변환 저장본)
grids = {}
for g in ["g576", "r030", "l010"]:
    la, lo = pl.load_grid(g)
    grids[g] = (la, lo)
    print(f"{g}: {la.shape}  위도 {la.min():.2f}~{la.max():.2f}  경도 {lo.min():.2f}~{lo.max():.2f}")'''),
    ("code", '''\
# 검증: r030 모서리 격자(API) 4점 평균 == 셀 중심(nc)
body = pl.fetch(pl.URL_LATLON, {"nwp": "r030", "latlon": "lat", "disp": "B"}, binary=True)
a, b_ = np.frombuffer(body[:4], dtype="<i2")
corner = np.frombuffer(body[4:], dtype="<f4").reshape(a, b_)
center = pl.corners_to_centers(corner)
print("모서리 격자:", corner.shape, "-> 중심:", center.shape)
print("보유 nc 와 최대 차이(도):", float(np.abs(center - grids["r030"][0]).max()))'''),
    ("code", '''\
# 8지점 x 3격자 변환표 + 최근접 격자 이동거리(km)
rows = []
for p in pl.POINTS_ALL:
    r = {"지점": p["name"], "lat": p["lat"], "lon": p["lon"]}
    for g, (la, lo) in grids.items():
        x, y, dkm = pl.find_xy(p["lat"], p["lon"], la, lo)
        r[f"{g}_X"], r[f"{g}_Y"], r[f"{g}_km"] = x, y, round(dkm, 2)
    rows.append(r)
xy = pd.DataFrame(rows)
xy.to_csv("results/grid_xy_table.csv", index=False, encoding="utf-8-sig")
xy'''),
    ("md", """**판정**
- 국지(l010) 도메인은 위도 30.8~45.1, 경도 118.3~133.7 — 육지 5지점(최동단 포항 129.4E, 최북단 대관령 37.7N)을 전부 덮는다. 최근접 격자 거리도 최대 0.62 km 로 셀 반경 안.
- 전구 최근접 거리 ≤ 4.9 km(8 km 격자), 지역 ≤ 2.1 km(3 km 격자) — 모두 정상 범위.
- 실전 검증: 구 pt 엔드포인트에 위경도를 주면 응답 헤더에 X/Y 를 돌려주는데, 우리 변환값과 정확히 일치했다(nb02 참조)."""),
])

# ── nb02: 가용성 + 리드/해상도 ──────────────────────────────────────────
nb02 = nb([
    ("md", """# nb02 — 신규 std API 가용성·최대 리드·시간 해상도 실측

기준 발표 = 2026-07-03 12z. 지점 = 제주 솔라팜(남쪽), 대조 지점 = 서산.

핵심 질문 세 가지:
1. 세 모델에서 일사·운량 등 핵심 변수가 응답하는가?
2. 발표 주기별 최대 예측 지평(hf)과 1h/3h 해상도는?
3. (검증 중 발견) 신규 std API 응답값을 그대로 믿어도 되는가?"""),
    ("code", PRELUDE),
    ("code", '''\
# 응답 포맷 원문 예시 (R030 T2) -- '#' 헤더 + 값 행렬, 헤더에 요청 echo 가 있어 검증에 유용
print(pl.fetch_std("KIMR", "R030", "T2", TMFC, 24, 550, 250, help_=1))'''),
    ("code", '''\
# Phase 1 가용성 스윕 결과 (availability_raw.csv 로 저장돼 있음)
av = pd.read_csv("results/availability_raw.csv")
print("모델별 응답 상태 요약:")
print(av.groupby(["model", "status"]).size().unstack(fill_value=0))
print()
print("R030/L010 에서 '변수 없음(not-found)' = 운량 계열 전부:")
print(av[(av.status == "not-found")][["model", "name"]].to_string(index=False))'''),
    ("md", """## ★발견 1 — 신규 std API 의 전구(NE57) '화면고도 변수' 디코딩 버그

전구를 신규 std API 로 읽으면 **t2m·td2m·rh2m·u10m·v10m·u80m·v80m·gust 가 전 지구 어디를 찍어도
같은 값**(위치 불변)으로 나온다. 반면 구 pt 엔드포인트는 **같은 파일**을 읽어 올바른 값을 준다.
아래 셀이 그 증거다 (서산과 제주 솔라팜, 380 km 거리)."""),
    ("code", '''\
rows = []
for nm in ["t2m", "rh2m", "u10m", "gust", "dswrsfc", "tcld", "tsfc", "tmax", "tmin"]:
    v1 = std_val("KIMG", "NE57", nm, TMFC, 18, 1523, 1480)   # 솔라팜
    v2 = std_val("KIMG", "NE57", nm, TMFC, 18, 1519, 1522)   # 서산
    rows.append({"변수": nm, "솔라팜": v1, "서산": v2,
                 "판정": "고장(위치 불변)" if v1 == v2 else "정상(공간 변화)"})
pd.DataFrame(rows)'''),
    ("code", '''\
# 같은 파일을 구 pt 엔드포인트로 읽으면 정상 (t2m 이 지점별로 다르고 물리적으로 타당)
for label, lat, lon in [("솔라팜", 33.3284, 126.8366), ("서산", 36.7766, 126.4939)]:
    b = pl.fetch(pl.URL_OLD_PT, {"group": "KIMG", "nwp": "NE57", "data": "U",
        "name": "t2m,u10m", "tmfc": TMFC, "hf": "18",
        "lat": f"{lat:.4f}", "lon": f"{lon:.4f}", "disp": "A", "help": "0"})
    vals = [l.split() for l in b.splitlines() if l.strip() and not l.startswith("#")]
    print(label, {v[5].split("(")[0]: float(v[4]) for v in vals})'''),
    ("md", """또한 구 pt 의 t2m(진짜 2m 기온)은 항상 신규 API 의 tmax·tmin(진단 구간 최대/최소) **사이**에
들어간다 — 즉 tmax/tmin 은 정상이고 t2m 만 엉뚱한 자료(성층권 추정 온도, 전 지구 상수)를 읽는다.

**결론: 전구는 구 pt 엔드포인트로 수집을 유지해야 한다** (현행 코드가 이미 그렇게 하고 있음)."""),
    ("code", '''\
# Phase 2 리드·해상도 스캔 결과 요약
ls = pd.concat([pd.read_csv("results/lead_scan.csv"), pd.read_csv("results/lead_scan_ext.csv")])
summary = []
for (m, c), g in ls.groupby(["model", "cycle"]):
    okh = g[g.ok == 1].hf.tolist()
    non3 = [h for h in okh if h % 3 != 0]
    summary.append({"모델": m, "발표(UTC)": f"{c:02d}z", "최대 hf": max(okh) if okh else None,
                    "1h 해상도": "전 구간" if non3 and max(non3) >= max(okh) - 1 else ("없음(3h만)" if not non3 else f"~{max(non3)}h")})
pd.DataFrame(summary).sort_values(["모델", "발표(UTC)"])'''),
    ("md", """## 실측 스펙 (문서와 다른 부분 굵게)

| 모델 | 발표 | 최대 리드 | 해상도 |
|---|---|---|---|
| 전구 NE57 | 00/12z | 288h (D+12) | **3h 간격만** (1h 산출물 자체가 없음) |
| 전구 NE57 | 06/18z | 87h | 3h |
| 지역 R030 | 00/12z | **120h (D+5)** (문서엔 87h) | 1h 전 구간 |
| 지역 R030 | 06/18z | **72h (D+3)** | 1h 전 구간 |
| 국지 L010 | 4주기 모두 | 48h (D+2) | 1h 전 구간 |

- 전구 336/372h 는 응답 없음 → **D+13~15.5 는 영구 소실 확정** (현행 운영은 이미 D+12 로 축소돼 있어 추가 손실은 없음).
- R030 의 120h/1h 는 구 KIMR 운영 특성과 동일 — 제주 체인(D+5 1h)이 그대로 유지 가능."""),
])

# ── nb03: 아카이브 깊이 ─────────────────────────────────────────────────
nb03 = nb([
    ("md", """# nb03 — backfill(과거 발표 조회) 가능 깊이

재훈련·백필 데이터 확보 가능성을 판단하기 위해, 과거 12z 발표를 하루~3일 간격으로
400일 전까지 찍어 조회 가능 여부를 기록했다 (hf=24 고정, 캐시 재생)."""),
    ("code", PRELUDE),
    ("code", '''\
ar = pd.read_csv("results/archive_scan.csv")
ar["date"] = pd.to_datetime(ar.tmfc.astype(str).str[:8])
for m, g in ar.groupby("model"):
    okd = g[g.ok == 1].date
    ng = g[(g.ok == 0) & (g.date >= okd.min())]
    print(f"{m}: 가장 오래된 가용 발표 = {okd.min().date()}  (가용 {len(okd)}건, "
          f"가용 구간 안 결측 {len(ng)}건)")'''),
    ("md", """**결과 — 아카이브는 서비스 개시일부터 전량, 결측 없음**

| 모델 | 개시일(문서) | 실측 최고(最古) tmfc | 깊이(2026-07-04 기준) |
|---|---|---|---|
| 전구 NE57 | 2026-01-19 | 2026-01-19 12z ✓ | 약 166일 |
| 지역 R030 | 2026-02-09 | 2026-02-09 12z ✓ | 약 145일 |
| 국지 L010 | 2026-02-09 | 2026-02-09 12z ✓ | 약 145일 |

개시일 이전 날짜는 전부 응답 없음 → 신모델 이름으로는 구모델 과거 자료가 제공되지 않는다."""),
    ("code", '''\
# 가장 오래된 발표에서도 hf 꼬리(최대 리드)와 4개 발표주기가 온전한가
tc = pd.read_csv("results/archive_tail_cycle.csv")
print(tc.to_string(index=False))
print()
print("전부 ok=1 -> 아카이브는 지평 축약 없이, 4주기 모두 보존")'''),
    ("md", """## 추가 추적 — '1h 전구 자료'가 사라진 정확한 시점

현행 운영 DB 는 07-03 이전까지 전구 1h 자료를 받아왔다. 신규 std 아카이브에는 1h 가 아예 없으므로
(개시일부터 3h 간격만), 구 엔드포인트가 읽던 파일을 날짜별로 역추적했다."""),
    ("code", '''\
# 구 pt 로 비3배수 hf=25 를 과거 날짜에 요청 -- 응답 헤더의 fname 이 결정적 증거
for d in ["20260601", "20260625", "20260630", "20260701", "20260702", "20260703"]:
    b = pl.fetch(pl.URL_OLD_PT, {"group": "KIMG", "nwp": "NE57", "data": "U",
        "name": "t2m,dswrsfc", "tmfc": d + "12", "hf": "25",
        "lat": "33.3284", "lon": "126.8366", "disp": "A", "help": "0"})
    has = b and any(l.strip() and not l.startswith("#") for l in b.splitlines())
    fn = next((l.split("/")[-1].split(",")[0] for l in (b or "").splitlines() if "fname" in l), "")
    print(f"{d} 12z hf=25(1h): {'있음' if has else '없음':3s}  파일={fn}")'''),
    ("md", """**07-01 정책 변경의 실체가 여기서 드러난다**

- 06-30 12z 까지: `g576_v091_glob_sfc.ftNNN` — **1시간 간격** 별도 파일이 존재 (구 엔드포인트가 이걸 읽음)
- 07-01 12z 부터: 그 파일이 사라지고 `g576_v091_glob_etc.2byte.ftNNN` — **3시간 간격**만 생성

즉 "07-03부터 1h 소실"로 관찰됐던 사건의 원인은 **07-01부로 전구 1h 후처리 파일(glob_sfc) 생산이
중단**된 것이다. 과거 1h 자료(glob_sfc, ~06-30)는 지금도 구 엔드포인트로 백필할 수 있다."""),
])

# ── nb04: 교차검증 + 일사 + 운량 + 파일럿 ────────────────────────────────
nb04 = nb([
    ("md", """# nb04 — 신구 교차검증, 일사 물리 검증, 운량 대안, 파일럿 수집

1. 같은 R030 모델을 구 grib API 와 신 std API 로 읽었을 때 값이 일치하는가
2. 신규 일사 3변수(SWDDIR2/SWDDIF2/SWDDNI2)의 물리적 의미와 ACSWDNB(누적) 규칙
3. 지역·국지에 없는 전운량의 대안
4. 파일럿: 신 API 로 운영 꼴의 wide 를 실제로 조립"""),
    ("code", PRELUDE),
    ("code", '''\
# 1) 신구 R030 교차검증 (솔라팜 550,250 -- 신구 같은 격자점, hf 12~21)
cc = pd.read_csv("results/crosscheck_r030.csv")
agg = cc.groupby("var").agg(구API_평균=("value_old", "mean"), 신API_평균=("value_new", "mean"),
                            최대차이=("diff", lambda s: s.abs().max()))
agg.round(3)'''),
    ("md", """**완전 일치** (최대 차이 0.005 = 2byte 패킹 양자화 한계). 신 std API 의 지역·국지 값은 그대로
신뢰할 수 있고, 바람 성분도 회전 없이 일치한다. — 전구의 화면고도 버그(nb02)와 대조적."""),
    ("code", '''\
# 2) 일사 삼각검증 (서산 L010, 2026-07-04 하루)
sq = pd.read_csv("results/solar_seq.csv")
day = sq[sq.cosZ > 0.05].copy()
day["SWDDIR2/(DNIxcosZ)"] = day.SWDDIR2 / day.dni_cosz
print(day[["hf", "cosZ", "SWDDIR2", "SWDDIF2", "SWDDNI2", "dni_cosz", "ghi_sum",
           "SWDDIR2/(DNIxcosZ)"]].round(3).to_string(index=False))'''),
    ("md", """- `SWDDIR2 ≈ SWDDNI2 × cos(천정각)` (비율 1.00) → **SWDDIR2 = 수평면 직달 일사** 확정
- 따라서 **전천일사 GHI = SWDDIR2 + SWDDIF2** (직달수평 + 산란) — 현행 DB 규약(radiation, MJ/m²·h)으로는
  `GHI × 0.0036` 그대로 사용 (현행 dswrsfc 변환식과 동일)
- 덤: 법선면 직달(DNI)·산란 분리는 태양광 모델에 현행보다 **더 풍부한** 입력이다."""),
    ("code", '''\
# ACSWDNB(누적 일사, MJ/m^2) 규칙: 발표 기준 누적(리셋 없음), 시간 차분 = 시간당 에너지
print(sq[["hf", "ACSWDNB", "acswdnb_diff_MJ", "ghi_sum_MJ"]].round(3).to_string(index=False))
print()
print("hf=0 에서 0, 단조 증가, 야간 증가 0 -> 강수 누적(rainc_acc) diff 패턴 재사용 가능")'''),
    ("code", '''\
# 3) 운량 대안: R030 등압면 CLDFRA(레벨별) 결합 vs 전구 tcld
ca = pd.read_csv("results/cloud_alternative.csv")
ca'''),
    ("md", """**운량 판정**
- 지역·국지 신모델 산출물에는 운량 단일면 변수가 **없다** (문서의 LCDC/MCDC/HCDC 는 실제 파일에 미탑재,
  구 grib 의 TCOG/TCOH 도 0 고정 = 사실상 사망).
- 등압면 CLDFRA 레벨 결합(랜덤 오버랩)은 물리적으로 정합(비 오는 제주 ≈ 1.0, 맑은 서산 = 0.0 —
  같은 모델의 일사 예측과도 일치)하지만 시각당 18콜이라 운영 비용이 크다.
- **현행 구조가 이미 정답**: 운량(tcld/mcld/lcld)은 지금도 전구(KIMG)에서 수집한다. 지역·국지를 도입해도
  운량은 전구 병합을 유지하면 되고, 필요 시 CLDFRA 는 EDA·특수 분석용으로만 쓴다."""),
    ("code", '''\
# 4) 파일럿: 신 std 로 수집한 wide 샘플 (솔라팜 D+1 하루, 240건 240 성공, 3.3콜/s)
w = pd.read_parquet("pilot_wide_sample.parquet")
w[["temp_C", "RH2", "U10", "V10", "GUST", "ghi", "radiation_MJ", "ACSWDNB"]].round(2)'''),
    ("md", """## ★발견 2 — 구 pt 엔드포인트가 세 모델을 전부 지원한다

`nph-kim_nc_pt_txt2`(현행 전구 수집기가 쓰는 그 엔드포인트)에 `group=KIMR&nwp=R030` 또는
`group=KIML&nwp=L010` 을 주면 **지역·국지도 그대로 응답**한다. 게다가:
- 위경도 직접 입력 (격자 변환 불필요 — X/Y 를 응답 헤더로 돌려주는데 우리 변환표와 일치)
- **콤마 멀티변수 = 1콜** (신 std 는 변수당 1콜 — 같은 일을 하려면 콜 수 10배 이상)
- 신규 변수(U140/U220, SWDDIR2/SWDDIF2/SWDDNI2, ACSWDNB, TSKIN, PBLH, VIS, RAIN)도 전부 나옴

즉 **기존 수집 엔진(_common.py 의 fetch_one_hf 패턴)에서 group/nwp/name 만 바꾸면 지역·국지 확장이
끝난다.** 신 std API 는 격자 박스 추출(map=S+sub) 같은 특수 용도 외에는 쓸 이유가 없다."""),
    ("code", '''\
# 증거: 구 pt 로 L010 확장 변수 멀티 호출 (1콜)
b = pl.fetch(pl.URL_OLD_PT, {"group": "KIML", "nwp": "L010", "data": "U",
    "name": "U140,V140,U220,V220,TSKIN,PBLH,VIS,SWDDNI2,RAIN",
    "tmfc": TMFC, "hf": "18", "lat": "33.3868", "lon": "126.8802", "disp": "A", "help": "0"})
for ln in b.splitlines():
    if ln.strip() and not ln.startswith("#"):
        print(ln)'''),
    ("code", '''\
# 마무리: 이번 연구의 콜 결산
log = pd.read_csv("probe_cache/calls_log.csv")
real = log[log.cached == 0]
print(f"실호출 {len(real)}건 / 캐시히트 {len(log) - len(real)}건 (하드캡 10,000)")
print(real.groupby("endpoint").size().to_string())'''),
])

for name, nbk in [("nb01_grid_prep", nb01), ("nb02_availability_lead", nb02),
                  ("nb03_archive_depth", nb03), ("nb04_crosscheck_pilot", nb04)]:
    path = HERE / f"{name}.ipynb"
    client = NotebookClient(nbk, timeout=600, kernel_name="python3",
                            resources={"metadata": {"path": str(HERE)}})
    client.execute()
    nbf.write(nbk, path)
    print("executed + saved:", path.name)

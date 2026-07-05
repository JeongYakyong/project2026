"""build_nb05.py -- nb05(임의 위경도 std API + frcc 전운량 대체) 노트북 생성·실행.

전부 probe_cache 재생이라 재실행해도 API 실호출 0.
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
TMFC = "2026070312"
print("호출 예산 상태:", pl.budget_status())'''

cells = [
    ("md", """# nb05 — "임의 위경도" std API(2.2.2)와 frcc 전운량 대체 (2026-07-04 추가 연구)

사용자 확인 요청 두 가지:
1. **`nph-kim_nc_pt_txt2_std`** (문서 2.2.2 "임의 위경도의 자료") — 격자 변환 없이 위경도를 바로 넣는 방식
2. 지역·국지에 없는 **전운량을 등압면 frcc(Fraction of Cloud Cover, GRIB 6032 = nc 파일의 CLDFRA)** 레벨 결합으로
   대체할 수 있는가 — 목표는 **1h 예보(R030 D+5, L010 D+2) 극대화**"""),
    ("code", PRELUDE),
    ("md", """## 1. `nph-kim_nc_pt_txt2_std` 검증 — 이 엔드포인트가 최종 승자

| 확인 항목 | 결과 |
|---|---|
| 위경도 직접 입력 | ✓ (응답 헤더에 변환된 X/Y echo — 우리 변환표와 일치) |
| 콤마 멀티변수 1콜 | ✓ |
| **등압면 data=P + level 생략 = 24레벨 프로파일 1콜** | ✓ (문서의 "level 없으면 각 고도 모두 표출") |
| 전구 화면고도 버그(xy_txt2_std 의 문제) | **없음** — t2m 제주 298.89 / 서산 301.71 (구 pt 와 동일값) |

즉 구세대(typ01 pt)와 같은 정상 디코더에, 신세대(std) 인자 체계까지 갖춘 엔드포인트다.
구 pt 가 폐지되더라도 이쪽으로 갈아타면 된다 — REPORT_03 의 "구 pt 폐지 리스크"가 크게 줄었다."""),
    ("code", '''\
# 증거 1: 멀티변수 + 위경도 (R030 단일면)
b = pl.fetch(pl.URL_PT_STD, {"group": "KIMR", "nwp": "R030", "data": "U",
    "name": "T2,RH2,U10,SWDDIR2,SWDDIF2", "tmfc": TMFC, "hf": "18",
    "lat": "33.3284", "lon": "126.8366", "disp": "A", "help": "0"})
for ln in b.splitlines():
    if ln.strip() and not ln.startswith("#"):
        print(ln)'''),
    ("code", '''\
# 증거 2: CLDFRA 전 레벨 프로파일 1콜 (비 오는 제주 -- 550~600hPa 두꺼운 중층운 + 200hPa 권운)
b = pl.fetch(pl.URL_PT_STD, {"group": "KIMR", "nwp": "R030", "data": "P", "name": "CLDFRA",
    "tmfc": TMFC, "hf": "18", "lat": "33.3284", "lon": "126.8366", "disp": "A", "help": "0"})
rows = [l.split() for l in b.splitlines() if l.strip() and not l.startswith("#")]
prof = pd.DataFrame({"hPa": [int(r[3]) for r in rows], "CLDFRA": [float(r[4]) for r in rows]})
print(prof.set_index("hPa").T.to_string())'''),
    ("code", '''\
# 증거 3: 전구(NE57)도 이 엔드포인트는 정상 (xy_txt2_std 버그와 대조)
for label, lat, lon in [("제주", "33.3284", "126.8366"), ("서산", "36.7766", "126.4939")]:
    b = pl.fetch(pl.URL_PT_STD, {"group": "KIMG", "nwp": "NE57", "data": "U",
        "name": "t2m,u10m", "tmfc": TMFC, "hf": "18",
        "lat": lat, "lon": lon, "disp": "A", "help": "0"})
    vals = {l.split()[5].split("(")[0]: float(l.split()[4])
            for l in b.splitlines() if l.strip() and not l.startswith("#")}
    print(label, vals)'''),
    ("md", """## 2. 운영 최적 경로 — 구 grib 의 ef 범위 호출과 결합

구 grib(`kim_grib_pt_tmfc.php`)은 `varn=6032`(frcc) + `data=P` + `ef=시작,종료,간격` 으로
**여러 시각 × 24레벨을 1콜**에 준다. 실측 한계:
- 96스텝(=2,304행)까지 1콜 OK, 120스텝 요청은 빈 응답 → **D+1~5(120시각)는 2콜로 분할**
- hf 121·122 는 창 밖(R030 최대 120h) — 실패가 아니라 정상 상한"""),
    ("code", '''\
# 증거: ef 범위별 행수 (캐시 재생)
for ef, note in [("3,26,1", "24시각"), ("3,98,1", "96시각(1콜 한계 내)"), ("3,122,1", "120시각(한계 초과->빈 응답)")]:
    b = pl.fetch(pl.URL_OLD_GRIB, {"group": "KIMR", "nwp": "r030", "data": "P",
        "varn": "6032", "tmfc": TMFC, "ef": ef, "X": 550, "Y": 250}, timeout=180)
    n = sum(1 for l in (b or "").splitlines() if l.strip() and not l.startswith("#"))
    print(f"ef={ef:10s} ({note}): {n}행")'''),
    ("md", """## 3. frcc → 전운량 결합 검증 (하루치 1h, 대조 지점 2곳)

결합식 두 가지를 비교했다:
- **랜덤 오버랩**: `1 − Π(1−c)` — 인접 레벨 상관을 무시해 과대 추정 경향
- **max-random(권장)**: 붙어 있는 구름층은 한 덩어리(최대값), 떨어진 덩어리끼리만 랜덤 결합
  — 현행 `MIDLOW_CLOUD` 결합식과 같은 철학의 확장

층별 분해(저층 ≥800hPa / 중층 450~799 / 상층 <450)도 함께 산출 — 현행 tcld/MIDLOW_CLOUD 피처의 1h 대응물."""),
    ("code", '''\
res = pd.read_csv("results/frcc_total_cloud_day.csv")
res[res.point == "솔라팜"].head(12)'''),
    ("code", '''\
# 물리 정합 검증: R030 자체 일사(서산)와의 대조 -- 저층운이 낀 아침에 투과율이 뚝 떨어짐
sq = pd.read_csv("results/solar_seq.csv")
sq["ghi_r030"] = sq["SWDDIR2_r030"] + sq["SWDDIF2_r030"]
m = res[res.point == "서산"].merge(sq[["hf", "cosZ", "ghi_r030"]], on="hf")
day = m[m.cosZ > 0.15].copy()
day["ghi_clear"] = 1100 * day.cosZ ** 1.15          # 간단 맑은하늘 근사
day["transmission"] = (day.ghi_r030 / day.ghi_clear).round(2)
print(day[["hf", "tot_maxrand", "low", "mid", "high", "ghi_r030", "transmission"]]
      .round(3).to_string(index=False))
print()
print("상관(전운량 vs 투과율): r = %.2f (음의 관계 = 정합)"
      % day.tot_maxrand.corr(day.transmission))'''),
    ("md", """**판정**
- 아침 저층운(low 0.61~0.86)에서 투과율 0.53~0.69 로 급락 — **frcc 결합 전운량은 모델 자신의 일사와 정합**.
- 불일치 구간은 전부 얇은 상층 권운(200hPa)이 전운량에 잡히는 경우인데, 일사를 거의 안 깎는다.
  이는 **실제 관측 전운량·NE57 tcld 도 똑같이 갖는 성질**(NE57 hf18: tcld 0.97 인데 일사 755 W/m²)이라
  대체물의 결함이 아니라 전운량이라는 변수의 본래 성질이다.
- 층별 분해가 덤으로 나오므로, 오히려 현행(전구 3h tcld)보다 정보가 풍부하다.

## 4. 결론 — "1h 극대화" 전략의 마지막 조각이 맞춰짐

| 피처 | 1h 공급원 (D+1~5) | 콜 비용/지점 |
|---|---|---|
| 기온·습도·바람(10/80m)·돌풍·강수 | 구 grib ef 범위 (varn 멀티) | 1콜 |
| **운량(전운량+층별)** | **구 grib frcc ef 범위 (data=P)** | **2콜** |
| 일사(GHI=직달+산란, DNI) | pt_txt2_std 멀티변수 (hf 당 1콜) | 120콜 |
| (국지 D+1~2 추가 시) | 같은 방식, L010 | 절반 이하 |

- 일사만 hf 당 1콜이 필요해 비용의 대부분을 차지 — 그래도 지점당 하루 123콜 수준(쿼터의 1% 미만/지점).
- 전구 3h(NE57)는 D+6~12 장지평 전용으로 물러나고, D+1~5 는 전부 1h 로 구성 가능.
- 남은 판단(모델링 관점)은 "R030 1h 예보가 NE57 3h+보간보다 실제로 더 정확한가" — 이는 백필 후
  실측 대조 EDA(G-9)로 확인할 일이다."""),
]

n = nbf.v4.new_notebook()
n.cells = [nbf.v4.new_markdown_cell(s) if k == "md" else nbf.v4.new_code_cell(s)
           for k, s in cells]
client = NotebookClient(n, timeout=600, kernel_name="python3",
                        resources={"metadata": {"path": str(HERE)}})
client.execute()
nbf.write(n, HERE / "nb05_latlon_std_frcc_cloud.ipynb")
print("executed + saved: nb05_latlon_std_frcc_cloud.ipynb")

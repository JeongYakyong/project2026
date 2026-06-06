# file_refine_instruction.md — 데이터 정제·병합 지시서

> **이 문서를 받은 Claude Code에게**: `file_report.md`의 실측 결과를 근거로
> ① 유용 파일을 **정제(clean)**, ② 나뉜 파일을 **병합(merge)**, ③ 불필요/중복 파일을 **따로 격리(archive)** 하고,
> ④ 모든 파일의 처리 결과를 **`DATA_CATALOG.md`** 에 기록해줘.
> 원본은 절대 변경/삭제하지 말 것(작업 디렉터리로 복사해서 처리). 추측으로 값·단위 채우지 말 것.

---

## 0. 산출물 폴더 구조 (목표)

```
/data
  /clean      ← 단일 출처 표준화본 (UTF-8-SIG, 컬럼 strip, dedup, timestamp 통일)
  /merged     ← 병합 마스터 (hourly / daily / monthly)
  /lookup     ← 시계열 아닌 계수표 원형 보존
  /archive    ← 불필요·중복·대체된 파일 + 사유
  DATA_CATALOG.md   ← 26개+ 전 파일의 처리 결과(clean/merge/lookup/archive)와 사유
```

출력 인코딩은 한글 Excel 호환을 위해 **`utf-8-sig`**. 입력 CSV 중 헤더가 깨진 제주 3종은 **`encoding='cp949'`** 로 읽을 것.

---

## 1. ★먼저 — 사용자 확인이 필요한 결정 (Decision Gate)★

아래 4개는 CC가 **임의 결정하지 말고**, 정량 근거만 만들어 `DATA_CATALOG.md` 상단 "결정 필요" 섹션에 정리할 것.
(2번 net_load 공식은 일단 명시값으로 계산하되 "확인 필요" 플래그를 남긴다.)

1. **LNG 정본 선택 — `ONLY_GEN.csv` vs `제주_시간대별전력거래량`**
   두 파일 모두 시간별 LNG(및 Oil)를 제공하나 최댓값이 다름(486.62 vs 476.12).
   → 겹치는 구간(2020-01-01~2024-12-31)에서 `LNG`·`Oil`의 **MAE·상관계수·최대편차·편차 분포**를 산출해 표로 보고.
   결정은 보류하되, 데이터로 본 권고를 한 줄 덧붙일 것.
2. **net_load 정의** — 아래 §4.1 공식으로 계산하되, 기존 파이프라인 정의와 다를 수 있으므로
   원천 컬럼(LNG/Oil/Other/Solar/Wind/HVDC_Total)을 **모두 보존**해 재계산 가능하게 둘 것. 공식엔 "확인 필요" 주석.
3. **기온 커버리지 갭** — 기상 피처 파일(아래)은 **2020-01~2022-10**만 커버.
   기온 민감도 vs net_load 민감도 비교에는 전체 구간 기온이 필요하므로,
   병합 후 **기온 결측 구간(2017~2019, 2022-10~2025)** 을 명시하고 "별도 기온(ASOS) 보강 필요" 플래그.
4. **`daliy_lng_gen` 공급량 단위 미상** — 원본에 단위 표기 없음(톤 추정).
   절대 단위를 만들어내지 말고 "단위 미확정" 표기. 상관/탄력성 분석용으로만 사용 가정.

> 참고: **SMP 데이터는 이번 배치에 없음.** 병합 마스터에 포함하지 말 것. 추후 `timestamp` 키로 외부 join 가능하도록 시간축만 표준화해 둘 것.

---

## 2. 공통 규칙

- 입력 원본은 **읽기 전용** → 작업 폴더로 복사 후 처리.
- 모든 시계열의 시간 컬럼명을 **`timestamp`** 로 통일, dtype datetime, 정시(hourly), tz-naive(KST 가정).
- 컬럼명 앞뒤 공백 **strip**(특히 KPX 화력, 깨진 `일시`).
- 결측·중복·이상치를 채우거나 지우기 전, **건수와 위치를 먼저 보고**하고 처리 방식 명시.
- 단위가 명시 안 된 컬럼은 추정값을 쓰지 말고 "미확정"으로 둘 것.

---

## 3. 단계별 작업

### Step 1 — 정제 → `/data/clean`

| 원본 | 처리 | 비고 |
|---|---|---|
| `ONLY_GEN.csv` | 중복 720건(2023-09 한 달 전체 이중입력) `drop_duplicates(keep='first')` → 43,848행. `timestamp`로 정렬. | dedup 전후 행수 보고 |
| `제주_시간대별전력거래량(17-25).csv` | `encoding='cp949'`. `일시`→`timestamp`. 컬럼 `LNG/Oil/Other/Solar/Wind` 유지. | 연료원별 spine |
| `제주_시간대별HVDC(17-25).csv` | `encoding='cp949'`. `일시`→`timestamp`. **`HVDC_Total`만 채택**(HVDC1+2+3=Total 검증됨). HVDC1/2/3은 clean본에 남기되 병합엔 Total만. | |
| `제주_시간대별발전량(16-24).csv` | **이름과 달리 기상/피처 데이터.** `weather_features_jeju.csv`로 **명확히 개명**해 clean에 저장. `일시`→`timestamp`. | 2020-01~2022-10만 |
| `한국전력거래소_일별 화력발전량_20220630.csv` | 컬럼 strip. `거래일자`→`date`. 제주도 필터본(`kpx_thermal_jeju_daily.csv`)과 전국본 둘 다 저장. | MWh, 2018-01~2022-06 |
| `oil_price_20-26.csv` | `date`로 통일. 주말/휴일 ffill 흔적은 그대로 두되 `is_filled` 플래그 컬럼 추가 가능하면 추가. | $/barrel |
| `한국가스공사_수입단가` | 그대로 정제(연월 datetime화). | $/MMBTU, 2010-01~2026-01 |
| `한국가스공사_총발전량 월별 기온효과` | `연`+`월`→`연월`(datetime, 월초). | 2007-01~2021-06 |
| `daliy_lng_gen_21-26.csv` | `날짜`→`date`. `구분`(일련번호) 드롭. **단위 미확정 표기.** | 전국 일별 |

### Step 2 — 병합 → `/data/merged`

세 해상도 마스터를 만든다(§4 스키마 준수).

1. **`jeju_hourly.csv`** — 시간별 마스터.
   - spine: `제주_시간대별전력거래량` (2017-01-01~2025-01-01).
   - `HVDC_Total` left-join (timestamp).
   - `weather_features_jeju`의 **기온 등 기상 컬럼** left-join(겹치는 구간만, 외부는 NaN).
   - `ONLY_GEN`의 `LNG_Gen/Oil_Gen`은 **`LNG_alt/Oil_alt`** 컬럼으로 left-join(정본 결정 전 비교용).
   - 파생 컬럼 계산(§4.1).
2. **`jeju_daily.csv`** — `jeju_hourly`를 일별 집계(발전·HVDC·net_load 등 **합계**, 기온은 **평균**).
   - 여기에 `daliy_lng_gen`(전국, date), `oil_price`(date), `kpx_thermal_jeju_daily`(date) left-join.
3. **`jeju_monthly.csv`** — `jeju_hourly`를 월별 집계(동일 규칙).
   - 여기에 `수입단가`(연월), `기온효과`(연월), `요금단가 통합본`(연월) left-join.

> 집계 규칙: 발전량·HVDC·net_load = **sum**(MWh), 기온/습도/풍속 등 기상 = **mean**, 강수/일사 = sum 또는 mean(컬럼 성격에 맞게, 선택 명시).

### Step 2b — 요금단가 7개 → 단일 long 테이블 `/data/clean/gas_tariff_2020_2026.csv`

7개 xlsx는 컬럼 구조 동일(병합셀 다중헤더). un-pivot하여 long으로 통합:

목표 스키마: `연월 | 단위(원/Nm³|원/GJ) | 구분(일반발전|집단) | 항목(원료비|공급비|합계) | 값`

- 시트명: 2020~2023=`발전용 천연가스 요금`, 2024~2026=`Sheet1`.
- **2026은 1~6월만 유효**(7~12월 0/NaN은 행 생성 금지).
- **검증 앵커**: 2020년 `원/Nm³ · 일반발전 · 1월` → 원료비 442.49 / 공급비 69.71 / 합계 512.20 이 나와야 함. 안 맞으면 헤더 파싱 재점검.
- 이 long 테이블을 월별 집계해 `jeju_monthly`에 join(`합계` 또는 `원료비` 중 선택은 분석 단계 결정 → 일단 전부 보존).

### Step 3 — 룩업/계수 보존 → `/data/lookup`

| 원본 | 처리 |
|---|---|
| `montly_lng_gen_temp.csv` | **시계열 아님(기온편차×월 수요지수 매트릭스)**. 정제만(인코딩·헤더), `temp_sensitivity_lookup.csv`로 원형 보존. 병합 금지. |

### Step 4 — 불필요·중복 격리 → `/data/archive` (+ 사유 기록)

| 파일 | 사유 |
|---|---|
| `제주 일별 시간대별 연계선 수전전력(HVDC#1/#2/#3)_*.csv` (9개) | 마스터 HVDC(2017~2025-04)와 2025-01~03 **값 중복**. 마스터 종료 이후(2025-04~2026-03) 연장용이나 **2025-07~09 결손**·발전량 데이터 부재로 분석 윈도우 밖 → 병합 제외. **연장이 필요할 때만** 쓰도록 §부록 레시피 첨부. |
| `file_list.txt` | 파일 목록 메타. 분석 비대상. |
| (해당 시) `제주_시간대별발전량(16-24).csv` 원본 | 개명본을 clean에 두므로 원본은 archive(이름 오해 방지). |

> archive는 **삭제가 아니라 이동**. 각 파일 옆 또는 카탈로그에 한 줄 사유 필수.

### Step 5 — `DATA_CATALOG.md` 작성

- 상단: §1 "결정 필요" 4항목 결과(특히 ONLY_GEN vs 전력거래량 비교표, 기온 결측 구간, 단위 미확정 목록).
- 본문: 전 파일 disposition 표 — `원본 | 처리(clean/merge/lookup/archive) | 산출물 경로 | 사유`.
- 각 merged 마스터의 **데이터 딕셔너리**(컬럼·단위·기간·집계규칙)와 **행수·기간·결측 요약**.

---

## 4. 병합 마스터 목표 스키마

### 4.1 `jeju_hourly.csv`
```
timestamp           datetime, 시간별, 2017-01-01~2025-01-01
LNG                 MW(≈MWh/h)  ← 전력거래량
Oil                 MW
Other               MW
Solar               MW
Wind                MW
HVDC_Total          MW (음수=역송)
LNG_alt, Oil_alt    MW  ← ONLY_GEN(겹치는 2020~2024만, 비교용)
기온, 습도, 풍속...   ← weather_features_jeju(2020-01~2022-10만, 외부 NaN)
-- 파생(※ net_load 공식은 "확인 필요" 플래그) --
renewable_MW        = Solar + Wind
total_demand_MW     = LNG + Oil + Other + Solar + Wind + HVDC_Total
net_load_MW         = total_demand_MW - renewable_MW   (= LNG+Oil+Other+HVDC_Total)
```

### 4.2 `jeju_daily.csv`
- `date` + `jeju_hourly` 일집계(발전/HVDC/net_load=sum, 기상=mean) + `lng_supply_nat`(전국,단위미확정) + `oil_dubai/brent/wti` + `kpx_jeju_lng_mwh/kpx_jeju_oil_mwh`(2018~2022-06).

### 4.3 `jeju_monthly.csv`
- `연월` + 월집계 + `import_price_*`($/MMBTU) + `기온효과` + `tariff_*`(원/Nm³·원/GJ, 원료비/공급비/합계).

---

## 5. 검증 체크 (완료 전 필수)
- [ ] ONLY_GEN dedup 후 정확히 43,848행, 중복 0.
- [ ] HVDC `HVDC1+HVDC2+HVDC3 == HVDC_Total` 전 구간 오차 ≈ 0 재확인.
- [ ] 요금단가 검증 앵커(2020 원/Nm³ 일반발전 1월 = 442.49/69.71/512.20) 통과.
- [ ] `jeju_hourly` 기간·행수, 기온 결측 구간 명시.
- [ ] 각 merged 마스터에서 join 키 매칭률(매칭/전체 행) 보고.
- [ ] 단위 미확정·결측 다수 컬럼 목록화.

## 6. 출력물
- `/data/clean/*` , `/data/merged/{jeju_hourly,jeju_daily,jeju_monthly}.csv` , `/data/lookup/temp_sensitivity_lookup.csv` , `/data/clean/gas_tariff_2020_2026.csv` , `/data/archive/*` , `DATA_CATALOG.md`
- 형식: CSV `utf-8-sig`. (원하면 parquet 동시 저장 가능)

## 7. 하지 말 것
- 원본 변경·삭제, 단위·결측 임의 채움, net_load 정본·LNG 정본 임의 확정.
- 모델링·예측 착수(이 단계는 정제·병합까지).
- archive 파일 영구 삭제.

---

## 부록 — HVDC 스냅샷 연장 레시피(필요 시에만)
1. 9개 wide(날짜×`1시`~`24시`) → `melt`로 long(`timestamp`, 회선값).
2. 회선 #1/#2/#3 합산 → `HVDC_Total`.
3. 마스터(2025-04-01까지)와 **중복 구간(2025-01~03) 제거**, 마스터 뒤에 append.
4. **2025-07~09 결손** 주의(보간 금지, 결측 표기). 분석 윈도우(≤2025-01)엔 불필요.

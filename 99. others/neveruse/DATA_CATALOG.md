# DATA_CATALOG.md — 제주 전력/가스 데이터 정제·병합 카탈로그

> 생성: 2026-06-02 · `file_refine_instruction.md` 실행 결과.
> 원본 26개+ 전 파일은 **읽기 전용**으로 유지(변경·삭제 없음). archive는 삭제가 아닌 **복사** 처리.
> 출력 인코딩 `utf-8-sig`. 제주 3종은 `encoding='cp949'`로 로드(헤더 `일시`→`timestamp` 정상 디코드 확인).

---

## A. ★결정 필요(Decision Gate) — CC가 확정하지 않음★

### A-1. LNG 정본 선택: `ONLY_GEN.csv` vs `제주_시간대별전력거래량`
겹치는 구간 **2020-01-01 ~ 2024-12-31, 43,848시간** 비교(전력거래량 `LNG/Oil` vs ONLY_GEN `LNG_Gen/Oil_Gen`):

| 항목 | MAE | 상관계수 | 최대 절대편차 | 편차 mean(거래량−ONLY_GEN) | 편차 std | \|diff\|>1MW 비율 |
|---|---|---|---|---|---|---|
| **LNG** | 10.27 MW | 0.9697 | 173.38 MW | −3.59 MW | 18.35 | 94.87% |
| **Oil** | 24.18 MW | 0.8434 | 258.10 MW | −7.73 MW | 36.31 | 99.04% |

- **데이터 기반 권고(결정은 사용자)**: 두 소스는 **동일 데이터가 아니다**. LNG는 추세 상관 0.97로 높지만 평균 ~3.6MW 낮고 시간별 편차가 크며(MAE 10MW), Oil은 상관 0.84로 더 크게 어긋난다. → **하나를 정본으로 고정하고 한 시계열 안에서 섞지 말 것.** 2020~2024 분석에는 정제·결합 완료본인 `ONLY_GEN`(LNG_Gen/Oil_Gen + HVDC_Total)을, 2017~2019 확장이 필요하면 전력거래량 LNG를 쓰되 **레벨 차이(약 −3.6MW)·기준 상이**를 명시. 두 값 모두 `jeju_hourly`에 `LNG`/`Oil`(거래량)과 `LNG_alt`/`Oil_alt`(ONLY_GEN)로 **병존 보존**해 재선택 가능.

### A-2. net_load 정의 — "확인 필요" 플래그
- 계산식(명시값으로 산출, 원천 컬럼 전부 보존 → 재계산 가능):
  - `renewable_MW = Solar + Wind`
  - `total_demand_MW = LNG + Oil + Other + Solar + Wind + HVDC_Total`
  - `net_load_MW = total_demand_MW − renewable_MW (= LNG + Oil + Other + HVDC_Total)`
- ⚠️ **기존 파이프라인의 net_load 정의와 다를 수 있음.** 위 공식은 잠정값이며, 원천 6컬럼(LNG/Oil/Other/Solar/Wind/HVDC_Total)을 마스터에 보존했으므로 다른 정의로 재계산 가능. **정본 정의는 사용자 확인 필요.**

### A-3. 기온 커버리지 갭 — ASOS 보강 필요
- 기상 피처(`weather_features_jeju`)는 **2020-01-01 ~ 2022-10-23** 만 존재.
- `jeju_hourly` 기준 기온 **결측 구간: 2017-01-01~2019-12-31, 2022-10-23~2025-01-01** (시간별 기온 매칭률 35.1%).
- 기온민감도 vs net_load 민감도 비교에는 전체 구간 기온 필요 → **별도 ASOS(제주 관측) 기온 보강 필요** 플래그.

### A-4. `daliy_lng_gen` 공급량 단위 미확정
- 원본에 단위 표기 없음(톤 추정). 절대 단위 생성 금지.
- 컬럼명을 **`lng_supply_nat_UNIT_UNCONFIRMED`** 로 명시 보존. **전국 단위**(제주 분해 불가) → 상관/탄력성 분석용으로만 가정.

> **SMP 데이터 없음**: 이번 배치에 미포함. 병합 마스터에 넣지 않음. 추후 `timestamp`(또는 `date`/`연월`) 키로 외부 join 가능하도록 시간축만 표준화해 둠.

---

## B. 전 파일 Disposition 표

| 원본 | 처리 | 산출물 경로 | 사유 |
|---|---|---|---|
| `ONLY_GEN.csv` | clean | `data/clean/only_gen.csv` | 중복 720(2023-09 한 달 이중입력) `drop_duplicates` → **43,848행, 중복0**. LNG_alt/Oil_alt 소스 |
| `제주_시간대별전력거래량(17-25).csv` | clean+merge spine | `data/clean/jeju_trade_fuel_hourly.csv` | cp949. 연료원별 spine(LNG/Oil/Other/Solar/Wind), 70,129행 |
| `제주_시간대별HVDC(17-25).csv` | clean+merge | `data/clean/jeju_hvdc_hourly.csv` | cp949. HVDC1/2/3 보존, 병합엔 `HVDC_Total`만(합=Total 오차 0 검증) |
| `제주_시간대별발전량(16-24).csv` | clean(개명)+archive(원본복사) | `data/clean/weather_features_jeju.csv`, `data/archive/...` | **이름과 달리 기상/피처 데이터**. 개명 저장, 원본은 오해방지 위해 archive 복사 |
| `한국전력거래소_일별 화력발전량_20220630.csv` | clean(전국+제주) | `data/clean/kpx_thermal_national_daily.csv`, `data/clean/kpx_thermal_jeju_daily.csv` | 컬럼 strip, MWh. 제주 일별 LNG/유류 검증셋(2018-01~2022-06) |
| `oil_price_20-26.csv` | clean | `data/clean/oil_price_daily.csv` | $/barrel. `is_filled` 플래그 추가(주말/휴일 ffill 682건) |
| `한국가스공사_수입단가_20260131.csv` | clean+merge(월) | `data/clean/gas_import_price_monthly.csv` | $/MMBTU, 연월 datetime화, 2010-01~2026-01 |
| `한국가스공사_총발전량 월별 기온효과_20210630.csv` | clean+merge(월) | `data/clean/gas_temp_effect_monthly.csv` | 연+월→연월. 2007-01~2021-06 |
| `daliy_lng_gen_21-26.csv` | clean+merge(일) | `data/clean/lng_supply_national_daily.csv` | 구분(일련번호) 드롭. **단위 미확정**, 전국 |
| `2020~2026년 발전용 천연가스 요금 단가.xlsx` (7개) | clean(통합 long)+merge(월) | `data/clean/gas_tariff_2020_2026.csv` | un-pivot 통합 936행. 앵커 검증 PASS. 2026은 1~6월만 |
| `montly_lng_gen_temp.csv` | lookup | `data/lookup/temp_sensitivity_lookup.csv` | **시계열 아님**(기온편차×월 수요지수 매트릭스). 원형 보존, 병합 금지 |
| `제주 일별...연계선 수전전력(HVDC#1/2/3)_*.csv` (9개) | archive(복사) | `data/archive/...` | 마스터 HVDC와 2025-01~03 값 중복. 2025-07~09 결손·발전량 부재로 분석윈도우(≤2025-01) 밖 → 병합 제외(연장 레시피는 §E) |
| `file_list.txt` | archive(복사) | `data/archive/file_list.txt` | 파일 목록 메타, 분석 비대상 |

> archive 11개 파일은 모두 **원본 복사본**이며 원본은 루트에 그대로 있음(삭제하지 않음).

---

## C. 병합 마스터 데이터 딕셔너리

### C-1. `data/merged/jeju_hourly.csv` — **70,129행, 2017-01-01 00:00 ~ 2025-01-01 00:00 (시간별)**
| 컬럼 | 단위 | 출처 | 비고 |
|---|---|---|---|
| `timestamp` | datetime(KST,tz-naive) | spine | 정시, 중복0 |
| `LNG`,`Oil`,`Other`,`Solar`,`Wind` | MW(≈MWh/h) | 전력거래량 | 연료원별 거래량 |
| `HVDC_Total` | MW(음수=역송) | HVDC 마스터 | 매칭률 100% |
| `LNG_alt`,`Oil_alt` | MW | ONLY_GEN | 2020~2024만(매칭 62.5%), 정본 비교용 |
| `기온(°C)`,`강수량(mm)`,`풍속(m/s)`,`습도(%)`,`일사(MJ/m2)`,`적설(cm)`,`전운량(10분위)`,`중하층운량(10분위)` | 각 단위 | weather_features | 2020-01~2022-10만(매칭 35.1%) |
| `renewable_MW` | MW | 파생 | Solar+Wind |
| `total_demand_MW` | MW | 파생 | LNG+Oil+Other+Solar+Wind+HVDC_Total |
| `net_load_MW` | MW | 파생 | total_demand−renewable (**정의 확인필요**) |

### C-2. `data/merged/jeju_daily.csv` — **2,923행, 2017-01-01 ~ 2025-01-01 (일별)**
- `jeju_hourly` 일집계: 발전·HVDC·net_load·LNG_alt 등 = **sum(MWh)**, 기온/풍속/습도/운량 = **mean**, 강수/일사/적설 = **sum**.
- left-join: `lng_supply_nat_UNIT_UNCONFIRMED`(전국, 매칭 50.0%), `oil_dubai/brent/wti`(매칭 62.5%), `kpx_jeju_LNG_mwh`/`kpx_jeju_유류_mwh`(2018-01~2022-06, 매칭 56.2%).

### C-3. `data/merged/jeju_monthly.csv` — **97행, 2017-01 ~ 2025-01 (월별)**
- `jeju_hourly` 월집계(동일 규칙) + left-join:
  - `import_*`($/MMBTU, 매칭 100%), `기온효과`(2007-01~2021-06 → 매칭 55.7%),
  - `tariff_{Nm3|GJ}_{일반발전|집단}_{원료비|공급비|합계}`(2020-01~2025-01 구간, 매칭 62.9%).

### C-4. `data/clean/gas_tariff_2020_2026.csv` — **936행 long, 2020-01 ~ 2026-06**
- 스키마: `연월 | 단위(원/Nm3|원/GJ) | 구분(일반발전|집단) | 항목(원료비|공급비|합계) | 값`
- ✔ 검증 앵커: 2020 원/Nm3 일반발전 1월 → 원료비 442.49 / 공급비 69.71 / 합계 512.20 **PASS**.
- 2026은 1~6월만(7~12월 0/NaN은 행 미생성).

### C-5. `data/lookup/temp_sensitivity_lookup.csv` — 9행×13열 (시계열 아님)
- 행=`temp_dev`(기온편차 −4~+4), 열=`1월`~`12월`, 값=수요지수(편차0=100). 병합 금지, 계수표로만 사용.

---

## D. 검증 체크 결과
- [x] ONLY_GEN dedup 후 **정확히 43,848행, 중복 0**.
- [x] HVDC `HVDC1+HVDC2+HVDC3 == HVDC_Total` 전 구간 최대오차 **0.000000**.
- [x] 요금단가 앵커(442.49/69.71/512.20) **PASS**.
- [x] `jeju_hourly` 70,129행 / 2017-01-01~2025-01-01 / 기온 결측구간 명시(§A-3).
- [x] join 매칭률 보고(§C, hourly: HVDC 100%·LNG_alt 62.5%·기온 35.1%).
- [x] 단위 미확정(`lng_supply_nat_UNIT_UNCONFIRMED`)·고결측(기상 컬럼 ~65%) 목록화.

---

## E. 부록 — HVDC 스냅샷 연장 레시피 (분석 윈도우 ≤2025-01 에선 불필요)
1. archive의 9개 wide(날짜×`1시`~`24시`) → `melt`로 long(`timestamp`, 회선값). `N시`=`N:00` 매핑 검증됨.
2. 회선 #1/#2/#3 합산 → `HVDC_Total`.
3. 마스터(2025-04-01까지)와 중복구간(2025-01~03) 제거 후 뒤에 append.
4. **2025-07~09 결손** 주의(보간 금지, 결측 표기). 2026-04 이후 없음.

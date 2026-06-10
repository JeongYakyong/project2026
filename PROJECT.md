# 프로젝트 마스터 문서 — 신재생 → 잔여부하 → 발전용 가스수요 (제주 입증 → 전국 확증)

> **이 문서가 단일 기준 문서(SSOT)다.** 새 대화나 Claude Code 작업을 시작할 때 이 문서를 첨부한다.
> 과거 문서 두 개는 `docs/`에 이력으로 보존한다:
> - `docs/PROJECT_v1.md` — 구 v1. 제주 SMP 예측 데모 정의(완성된 1~4단계 상세 이력).
> - `docs/PROJECT_v2_PRD.md` — 구 v2 PRD. 가스수요로의 방향 전환 근거와 방법론.
> 셋이 충돌하면 **이 문서가 우선한다.**

---

## 0. 문서 운영 규칙

### 0.1 문서 계층
- 이 문서 = 최상위 기준. 새 대화·Claude Code에 첨부하는 문서.
- `docs/PROJECT_v1.md`, `docs/PROJECT_v2_PRD.md` = 이력·참조용(변경하지 않음).

### 0.2 고정 / 가변 구역
- **고정(가급적 안 바꿈)**: §1 목표·명제 · §2 자격 · §5 방법론. 정의가 흔들리면 매번 다른 답이 나온다. 꼭 바꿔야 하면 §8 진행 로그에 "정의 변경"으로 명시한다.
- **수시 갱신**: §3 폴더 구조 · §4 단계 상태 · §7 게이트 · §8 진행 로그.

### 0.3 Decision Gate(G-n) 규칙
- 새 결정거리가 생기면 §7에 `G-n`을 추가한다. 번호는 **증가만** 한다(재사용·재번호 금지).
- 상태: `[ ]`(미해결) → `[x]`(해결: **날짜 + 한 줄 근거**). 해결돼도 **삭제하지 않는다** — 왜 그렇게 정했는지 추적용.
- **착수 규칙**: 관련 게이트가 미해결이면 그 작업을 **시작하지 않는다.** 게이트부터 통과시킨다(작업 쪼개기 원칙).

### 0.4 진행 로그(§8) 규칙
- 형식: `**YYYY-MM-DD — 한 줄 제목**` + 불릿(무엇을 / 결과 / 다음). **최신이 위로**(역순).
- 작업 완료·결정·방향 전환마다 1건. 정확도 수치·파일명까지 적어두면 좋다.

### 0.5 새 대화 시작 패턴
```
첨부한 PROJECT.md가 최상위 정의야.
오늘 작업은 [작업 ID, 예: 7단계 가스 예측기], DoD는 [§4 인용].
관련 게이트 [G-n] 상태부터 확인하고, §5 방법론을 따라줘.
```

### 0.6 개발자 작업 규율 (★ 반드시 지킬 것 — 과거 실패에서 나온 규칙)

이 문서를 처음 보는 Claude/Claude Code가 놓칠 수 있는, 본인 외엔 모르는 배경이다.

**개발자(본인)의 작업 스타일**
- 단계별로 하나씩 구동하면 결과는 낼 수 있다. 즉 개별 기술 역량은 충분하다.
- 약점은 "여러 단계를 이어가는 흐름 관리"다. 의사결정이 안 된 상태에서 무거운 작업을 시작하면 흐름이 끊긴다.
- 따라서 협업 시 "작업 쪼개기 + 의사결정 게이트 명시"가 핵심이다. 큰 덩어리로 던지지 않는다.

**과거에 막혔던 지점(반복 방지용)**
- 전국 확장을 결정하지 못한 채로 18개 지역 선정·대규모 데이터 수집 같은 무거운 작업을 먼저 시작 → 흐름 정지.
- 교훈: "이걸 해야 하는가?"가 정해지기 전에는 작업을 시작하지 않는다. 항상 Decision Gate(§7)를 먼저 통과시킨다.

**문서 표기 규율(★ 신뢰와 직결)**
- 모든 문서는 **자연스럽고 정확한 한국어**로만 쓴다.
- **어려운 한자 표현·일본어·중국어·난해한 조어를 쓰지 않는다.** (과거에 이런 표현 때문에 프로젝트를 통째로 엎은 적이 있다.) 예: "막다른 접근", "실패로 확인된 경로"처럼 평이하게 쓴다.
- 기술 식별자/영문 약어(`net_load`, `SMP`, `gen_gas_kr`, `LGBM`, `PatchTST`, `KOGAS`, `D+1` 등)는 정확성을 위해 그대로 둔다.

**모델링 작업 규율 (★ 모든 단계 공통 — 2026-06-06 추가)**

아래는 7·5·6 등 모든 모델링 단계에 예외 없이 적용한다.

- **시계열 분석 필수**: 모든 모델링은 시계열 분석을 먼저 한다. 모델 착수 전 시계열 구조(주기성·추세·안정성·분포 변화)와 입력↔타깃 관계를 본다(§5.0.5). 건너뛰지 않는다. "한 줄짜리처럼 보여도" 건너뛰지 않는다.
- **피처 선택은 반드시 사용자에게 묻는다**: 어떤 피처를 모델 **최종 입력**으로 쓸지는 절대 임의로 정하지 않는다. 매번 사용자에게 묻고 확정한 뒤 학습한다. 단, 피처 **탐색·후보 분석·상관 점검**은 자유롭게 해도 된다(묻는 대상은 "최종 입력 확정"이지 "탐색"이 아니다).
- **단계마다 보고서용 산출물 필수**: 모든 단계는 보고서용 파일·결과물을 반드시 남긴다(표·그림·요약 + 탐색용 파일). 결과를 코드에만 묻어두지 않는다.
- **notebook 형식 선호**: 과정과 결과를 한눈에 보도록 notebook 형식을 우선한다.

---

## 1. 목표와 명제

### 1.1 한 줄 정의
신재생(태양광·풍력) 변동이 만든 **잔여부하(net_load)**를 가스 발전이 메운다 — 그 관계를 **제주에서 입증**하고 **전국 실측(`gen_gas_kr`)으로 확증**한다. 그리고 결과를 발전사업자에게 유용한 브리핑으로 제공하는 Streamlit 데모를 만든다.

### 1.2 검증 목표 (Thesis)
> 이 프로젝트는 "예측 정확도 자랑"이 아니라 **하나의 명제를 데이터로 입증**하는 것이 목적이다.

- **검증 목표 1 (제주)**: `est_net_load`로 **발전용 가스 수요량의 변화를 예측할 수 있다.** 신재생이 가장 많이 들어오는 제주에서, 신재생 → 잔여부하 → 가스 발전수요의 연결을 입증한다.
- **검증 목표 2 (전국)**: 제주에서 보인 관계가 **전국에서도 성립한다.** 전국은 가스 발전량(`gen_gas_kr`)이 **실측으로 존재**해 데이터 질이 더 좋고, 검증이 더 엄밀하다.

### 1.3 명시적 비목표 (하지 않는 것)
- **전국 단위 SMP 예측 — 시장 구조상 하지 않는다.**
  - 제주: 전력거래 시범사업 적용 지역. 실시간 시장(SMP) 운영 중 → SMP 예측의 의사결정 가치가 있다.
  - 전국: 시범사업 미적용. 실시간 시장 구조가 없어 SMP 예측 자체가 의미를 갖지 못한다.
  - 따라서 전국은 **net_load → 가스 발전 검증까지만** 수행한다. SMP를 "안 한 것"이 아니라 "할 이유가 없는 것"이다.
- 상용 서비스 수준의 보안·확장성(데모 수준으로 충분).
- 전체 지역 커버(1~3개 샘플로 충분).
- 모델 성능 최고치 달성(이미 동작하는 수준 유지, 미세 조정만).

### 1.4 출품 정보
- 대상: 제14회 산업통상부 공공데이터 활용 아이디어 공모전 — 제품 및 서비스 부문.
- 마감: 2026-07-06(D-3 제출 = 7/03).

---

## 2. 자격과 데이터 귀속

- 요건: 산업통상부(산하기관 포함) 데이터 **1개 이상 활용** + 타기관·민간 자유 연계. **확인 완료.**
- **자격 앵커 = KOGAS(한국가스공사, 산업통상부 산하)**: 요금 단가·수입 단가·기온효과·공급량. 모델의 **출력(가스수요/비용) 환산·검증**에 실제로 사용한다.
- 연계(타기관): 전력 데이터(KPX), 기상(기상청), 유가(민간).

---

## 3. 폴더 구조 (재구조화 결과, 2026-06-06)

> 평면 넘버링을 유지한다. 모든 파이프라인이 DB 경로를 상대경로로 참조하므로, 폴더를 깊이 중첩하면 경로가 깨진다. 그래서 중첩 대신 **지역 접두사**(`jeju_*` / `land_*`)로 제주·전국을 대칭으로 묶었다.

```
1. data_fetcher_and_db/        공통 데이터·DB 계층
   ├── core/                   collect_data_{jeju,land}.py, _common.py, postprocess.py
   ├── data/                   input_data_jeju.db, input_data_land.db  ← 모든 파이프라인의 단일 출처
   └── second_dataset/         가스수요 데이터셋 빌더(제주·전국 양쪽 parquet 생성)
2. jeju_demand_forecaster/     [제주·완료] D+1 수요(est_demand)
3. jeju_solarwind_forecaster/  [제주·완료] 신재생 → net_load
4. jeju_smp_forecaster/        [제주·완료] D+1/D+2 SMP + 위험 경보
5. land_demand_forecaster/     [전국·골격] 제주 2단계의 전국판
6. land_solarwind_forecaster/  [전국·골격] 제주 3단계의 전국판(net_load)
7. land_gas_forecaster/        [전국·골격] net_load → 가스 발전 + KOGAS 환산 (★ 새 명제의 핵심)
8. streamlit/                  [예정] 통합 대시보드 + brief_ai
98. report only/               제주 비교·검증 리포트
99. others/                    원천 CSV·EDA·아카이브
```

- 제주(2·3·4 = `jeju_*`)와 전국(5·6·7 = `land_*`)이 한눈에 대칭이다.
- `second_dataset`는 제주·전국 양쪽 parquet를 만드는 **교차-지역 자산**이라 공통 폴더(1)에 둔다.

---

## 4. 단계별 트랙 (핵심)

> 체인의 앞 절반(제주 1~4)은 동작 + 백필 완료. 신규 작업은 뒤 절반(공통 데이터셋 → 전국 5·6·7 → 데모 8)에 집중된다.
> 각 단계는 **상태 · DoD · 유의사항 · 관련 게이트** 순으로 정리한다.

### 제주 트랙 (완료)

**1단계 — 데이터 수집·DB (`1. data_fetcher_and_db`) ✅**
- 상태: 완료. 기상청·KPX 공공 API를 직접 받아 `input_data_jeju.db` / `input_data_land.db`의 `forecast`·`historical` 테이블에 적재(`timestamp` 키 UPSERT).
- DoD: CLI(`collect_data_jeju.py` / `collect_data_land.py`)로 수집 가능. 같은 구간 재실행 시 최신값으로 덮어쓰기(중복 없음).
- **(2026-06-08) 육지 forecast에 습도(`reh_<지점>`)·강수(`rainfall_<지점>`) 추가수집 가능** — KIMG에 `rh2m`/`rainc_acc`/`rainl_acc` 변수 추가(`_common`), 강수는 누적→시간당 diff(`collect_data_land`). 과거분은 `temp_land_backfill.py`로 KIMR 1회 백필(reh/rainfall 동일 컬럼명).
- 유의사항: 수집은 백그라운드(crontab)에서만 돌린다. 사용자 트리거 금지(API 한도 보호).

**2단계 — 수요 예측 (`2. jeju_demand_forecaster`) ✅**
- 상태: 완료. PatchTST 신호 + LGBM으로 D+1 24시간 수요(`est_demand_new`) 예측.
- 결과: 기상을 제주 3지점 공간평균으로 바꿔 재학습 → **Test MAPE 3.98%**(이전 4.29% 대비 개선).
- DoD: `demand_db_pipeline.py`가 `input_data_jeju.db`에서 읽고 `est_demand_new`를 UPSERT.
- 유의사항: 입력은 history 28일(결측 없음) + D+1 24시간 기상 예보.
- **2-A 장지평 확장 ✅(신규, 기존 D+1 그대로 유지)**: land 5-A 틀 이식 — **LGBM 단독·풀드 직접 다지평 1~168h(D+1~D+7)**, origin 23:00. **최종 피처 22개**=h+lag168+rec24/rec168+기상4(기온·습도·일사·풍속, 3지점평균/일사2지점)+**구름4(total/midlow_cloud west·south raw, h≤48)**+**cap_btmppa_mw(BTM/PPA 용량)**+**흐린날피처(solar_deficit·solar_ramp, h≤48)**+달력+day_type. **비대칭 quantile(α=0.60)+낮시간 가중2**로 흐린날 surge 과소예측 공략(사용자 Decision Gate 다회). 산출 `eda/`(2-0·2-0b·2-0c)·`model/`(2-A 노트북·`lgbm_jeju_demand_direct.txt`·리포트·실험스크립트). **test 완전기상 D+1 3.82%→D+7 4.10%/전체 3.99%(전 지평 KPX 6.0% 상회)**. **낮시간(08~16h, ★1순위지표): 완전기상 낮흐림 5.60·낮맑음 6.29 / 실서빙(forecast) 낮전체 8.04·낮흐림 6.87·낮맑음 8.94 — 모두 KPX(9.09/6.90/9.94) 우위(흐림은 근소, 예보품질 한계)**. QM(forecast 분포보정)은 흐린날 순효과 음(−)이라 미적용, cape는 forecast 전용이라 미채택. 서빙=raw forecast.
- **2-B 서빙 ✅**: `serve_jeju_demand_lh.py` — origin(지정일 23:00) 다음 **D+1~D+7 선택형**(`--days 1..7`) → `forecast.jeju_est_demand_lh` UPSERT(★기존 배포 `jeju_est_demand_new` 불변). **직접 다지평이라 원하는 지평만큼 예보만 있으면 됨**(24h 예보→D+1, lag168·rec는 과거 실측). 기상=forecast 우선·없으면 (월,시) 기후값(구름·흐린날피처는 h≤48만). CLI `predict [date] --days N` / `backfill start end`(낮시간 분리 MAPE). 백필 검증(2026-04, forecast 서빙) D+1 전시간 5.2%·낮 8.6% ~ D+7 5.1%.

**3단계 — 신재생 → net_load (`3. jeju_solarwind_forecaster`) ✅**
- 상태: 완료. Cross-Attention PatchTST를 3지점 입력으로 재학습 → 태양광·풍력 이용률 → 발전량 → `net_load`.
- 결과: 단일지점 대비 이용률 solar +6.9%, wind +3.7%. net_load는 DA 기준 대비 +7.0% 개선. 최종 지점 구성은 solar=west+south, wind=west+east(상관이 약하고 예보 편차가 큰 지점은 제외 — 지점 수를 무작정 늘리면 오히려 나빠진다).
- DoD: `solarwind_db_pipeline.py`가 `est_solar/wind_utilization_jeju`·`est_solar/wind_gen_jeju`·`est_net_load_jeju`를 UPSERT.

**4단계 — SMP + 위험 경보 (`4. jeju_smp_forecaster`) ✅**
- 상태: 완료. 제주 실시간 시장(SMP)의 D+1·D+2 예측 + 음수가격 위험 경보.
- 핵심 설계: SMP 점예측은 **실패로 확인된 경로**다(헛경보마다 가격이 크게 튀어 오차가 폭발). 대신 **가격선 = DA(하루 전 가격) 그대로** 두고, 그 위에 **이진 음수경보를 덧씌운다.** 가격은 DA로 두고, 음수 발생만 분류하는 방식이다. 오버레이라 경보를 켜도 가격선 정확도는 그대로다.
- 결과: 음수경보 분류 ROC-AUC TEST 0.973, 치명 구간 recall 0.934. D+2(뒤 24시간)는 DA를 예측해 그 위에 잔차회귀 → TEST MAE 11.79(기준선 lag24 14.30 대비 개선).
- 통합 서빙: `smp_serve.py`가 D+1·D+2 단일 진입점.
- 유의사항(하드 제약): **제주 SMP는 제주 데이터만 사용한다. 전국 SMP 연계는 영구 배제**(설계 원칙). 아래 접근들은 모두 **실패로 확인된 경로**라 다시 시도하지 않는다 — SMP 실시간 가격을 직접 회귀, hurdle 회귀, Transformer, 학습창 임의 절단, 실시간 lag로 인한 정보 누수. 상세는 `4. jeju_smp_forecaster/trial_error.md` 참조.

### 공통 데이터 단계 (완료)

**A0/A1 — 가스수요 데이터셋 (`1. data_fetcher_and_db/second_dataset`) ✅**
- 상태: 완료. 제주·전국 시간별 마스터셋 결합 → 채우기 전 결측·중복·시간구멍 감사 → LNG 타깃 도출 + backfill → 정답/피처/금지 라벨링 → 시간순 분할 → parquet·딕셔너리·감사보고서 출력.
- 결과: 제주·전국 각 56,256행, 중복 0·시간구멍 0. 학습/검증/테스트 기본 피처·타깃 NaN 0.
- 산출물: `second_dataset/data/*.parquet`, `data_dictionary.csv`(63컬럼, 정답/피처/금지 라벨), `audit.json`, `AUDIT_REPORT.md`.
- 유의사항: 이 단계가 끝나야 가스 예측기(7단계) 모델링에 착수한다(게이트 G-6).

### 전국 트랙 (진행 예정)

> 전국은 제주 2·3·4를 미러링하되, **SMP 단계는 없다**(시장 구조상 비대상). 끝은 net_load → 가스 발전 검증이다.

**5단계 — 전국 수요 예측 (`5. land_demand_forecaster`) ✅ (5-0 EDA·5-A 풀드·5-A2 지평별·5-B 서빙 완료)**
- **5-0 EDA ✅**(G-9 통과): 전국 수요 시계열 = 강한 일/주 주기(lag24 0.78·lag168 0.84), 기온 V자(난방 71k / 최저 58k / 냉방 79k MW, 선형상관은 ≈0이라 트리로 잡음), 5지점 기온상관 0.95~0.98(공간평균 타당), train↔test 분포 겹침 안전. **★ 서빙 가능 기상 = `temp_c·solar_rad·wind_spd`**(forecast 테이블에 습도·강수·적설 없음 — 제주와 차이). 산출 `eda/5-0_eda_land.ipynb`·`REPORT_5-0_eda.md`·`fig/`·`tab/`.
- **5-A 모델 ✅**(사용자 확정 §0.6): **LGBM 단독·직접(direct) 다지평 1~168h 단일모델**(재귀 rolling 아님 — 주간 lag168이 전 지평 직접 가용해 오차 누적 회피). 피처 = h, lag168, lag24(h≤24만, 그 외 NaN), rec24/rec168(원점 최근레벨), 기상3(5지점평균), 달력(hour/dow/month sin·cos), day_type. 학습창 train≤2024/val2025/test2026. 평가는 **D+1~D+7(각 24h 전체)** + 정직성 2겹(완전기상 상한↔기후값 하한). **결과 test 2026: D+1 3.56~4.50% / 전체 3.99~5.01% / D+7 4.22~5.31% — KPX 하루전(5.45%)을 전 지평에서 상회**(naive lag168 7.2%). 중요도 lag168·기온·rec168 주도. → 베이스라인 우위로 **PatchTST 불필요**(사용자 결정 규칙 충족). 산출 `model/5-A_land_demand_direct.ipynb`·`lgbm_land_demand_direct.txt`·`model_meta.json`·`REPORT_5-A.md`·`fig/`·`tab/`.
- 보너스: 직접 다지평이라 **일주일(D+7) 앞을 KPX 하루전 수준으로** 예측. 같은 틀을 제주 2단계 장지평 확장에 이식 가능(사용자 요청, 후순위).
- **5-A2 지평별 직접모델(Direct-H) ✅**(사용자 확정): 5-A가 한 모델로 전 지평을 학습한 "풀드"라면, 5-A2는 **날짜마다 모델을 따로**(D+1·D+2·D+3·D+7·D+12 5개). 출력=D+n 하루(24h) 블록. 피처 동일 템플릿(lag_week + rec24/rec168 + 기상3 + 달력 + day_type), **주간앵커 lag_week = target−168(D+1~7) / target−336(D+12)**(D+12는 lag168이 미래라 불가). **test 2026 완전기상: D+1 3.48·D+2 3.76·D+3 3.94·D+7 4.26·D+12 4.59%**(기후값 하한 +0.9%p 내외), 전 지평 KPX(5.3~5.5%) 상회. 풀드 5-A가 ~0.05~0.1%p 근소 우위(데이터 공유). **공휴일 보정 실험**(사용자 지적: lag_week가 7일전 평일을 주입): lag의 day_type(`lag_dt`) A/B → 전체 개선 ≤0.15%p로 작고 공휴일/불일치 부분집합에서 비일관(공휴일 9일뿐 노이즈, 타깃 day_type이 신호 대부분 보유) → **미채택, base 유지**(파시모니). 산출 `model/5-A2_direct_per_horizon.ipynb`·`lgbm_land_demand_D{1,2,3,7,12}.txt`·`model_meta_perhorizon.json`·`REPORT_5-A2.md`·`fig/`·`tab/`.
- **5-B 서빙 ✅**: `serve_land_demand.py` — origin(지정일 23:00) 다음 **D+1~D+7 선택형**(`--days 1..7`) 예측 → `forecast.est_demand_land` UPSERT. 피처 조립은 5-A와 동일(검증: 과거 백필 D+1 4.30%·D+7 5.40% = 5-A 기후값 괄호와 일치). 기상은 **forecast 예보 우선·없으면 (월,시) 기후값 폴백**(`weather_src` 표기). CLI `predict [date] --days N` / `backfill start end`(MAPE 평가).
- **7일 예보 수집(G-12)**: KIMG 전구는 **00/12 UTC=288h(12일)·06/18 UTC=87h**. 현재 생산이 18 UTC라 ~3.6일에 막혔던 것(소스 한계 아님). 결정: **≤72h(D+1~D+3)는 기존 신선 발표, >72h(D+4~D+7)는 12 UTC 단일**(`--kimg-days 7`). 서빙은 무변경(forecast 쌓이면 자동 실예보 사용). 백필(과거 장기 lead 가용 확인)은 사용자가 직접 수행.

**6단계 — 전국 신재생 → net_load (`6. land_solarwind_forecaster`) ✅ 완료**
- 상태: 완료. 채널 분리 — **태양광=PatchTST(D+1~7,D+12 direct)+LGBM 폴백 / 풍력=LGBM 전지평**. 산출 2종: `est_market_renew_land`(시장, →7-A)·`est_true_renew_land`+`est_true_demand_land`(BTM/PPA 포함, →7-Ar 대체효과). 서빙 `serve_solarwind_land.py`. 검증 SOLAR util MAE(낮) 0.087·WIND 0.139.
- DoD: 전국 태양광·풍력 예측 → `net_load`. 전국 DB에 `net_load_kr`·`gen_solar_*`·`gen_wind_kr` 실측으로 검증. 상세 §8(2026-06-08)·6-0~6-C 보고서.
- 구조(G-13, 2026-06-08 확정): **LGBM-direct 다지평 단일**(5-A·3단계 결론 일관) 주력 + PatchTST는 **D+1/D+2/D+3에서만 비교(6-B)** → 큰 차이 없으면 LGBM 단일. 지평 **D+1~D+12**. 타깃 **이용률 정규화**(solar_cap 2.7k→9.4k MW 3.4배 표류 → DB `gen_solar/wind_utilization_kr`)→×용량 복원 → net_load.
- 지점(사용자 확정): **solar=영광+서산+포항**(전남·충남·경북, 용량 61%, solar_rad↔이용률 0.69~0.75), **wind=대관령+영광+포항**(강원·경북·전남, 용량 ~90%, 대관령 풍속↔이용률 0.607 압도). 합집합 4지점 forecast만 로드. **후처리 불가**(land forecast에 강수·cape·tcog 없음 → 제주 solar_damping·tcog 미적용).
- 작업 순서: 6-0 EDA(G-9, 지점별 이용률 관계·용량표류·분포겹침) → 최종 피처 §0.6 질의 → 6-A LGBM-direct → 6-B PatchTST 비교(D+1~3) → 6-C 서빙(`est_net_load_land`).

**7단계 — net_load → 발전용 가스수요 (`7. land_gas_forecaster`) ✅ (7-0~7-C·7-A2-A 체인검증·서빙 완료) ★ 새 명제의 핵심**
- DoD(예정): `net_load → 가스 발전량(LNG)` 예측 모델. 전국은 `gen_gas_kr`(실측)으로 정직하게 검증. 예측 가스 발전량을 KOGAS 단가·수입가로 환산해 가스 수요·비용 산출.
- 데이터: `second_dataset/data/land_*.parquet`(피처 net_load·달력·기온, 타깃 `gen_gas_kr`). 금지 피처(HVDC·유류 발전·타깃 lag)는 딕셔너리의 `forbidden` 참조.
- 작업 순서(쪼개기, 각 단계 보고서 산출물 필수 · notebook 선호):
  - **7-0 EDA/시계열(G-9) ✅**: net_load↔gen_gas_kr 관계·시계열·안정성·분포 겹침 + **신재생 대체효과(5-b)**. 2022+ r=0.83, 데이터 결손(2020-21) 발견→G-10, **신재생→가스 대체효과는 전국에선 약함**(원상관 ~0, 침투율 2.5%·자가소비 숨음) → 제주의 몫. 산출 `eda/`.
  - **7-A 전국 모델 ✅**: LGBM(피처 = 설계 A 분해형: real_demand_land + renew_gen_total_kr + day_type + 달력 hour/dow/month/doy. net_load는 수요−신재생 내포. 기온·year 제외, §0.6 사용자 확정). 학습창 train 2022-24/val 2025/test 2026. **test 2026 실측: MAPE 11.4%·R² 0.78**(베이스라인 수요 단독 R² 0.63). **중요도 real_demand_land 60%·doy 15%·hour 13%·신재생 3.6% → 검증목표 2 확증(수요 주도).** 신재생 부분의존 기울기 −0.017(대체효과 부호는 맞으나 전국은 미미). 산출 `model/`(notebook·`lgbm_land_gas.txt`·metrics·`REPORT_7-A.md`).
  - **7-Ar 실측전용 대체효과 모델 ✅**(G-11): 2024-11+ 실측 BTM/PPA 복원으로 true_demand+true_renew 학습(역추정 미사용). test 2026 R² 0.798·MAPE 12.0%, 신재생 중요도 15.4%, PDP 기울기 음(대체효과를 모델이 직접 담음). 7-A(메인 예측)와 병행. 산출 `model/7-Ar_*`·`lgbm_land_gas_recent.txt`.
  - **7-A2 LNG 용량 이용률 정규화판 ✅**(2026-06-06, 2026 과소예측 보정): 7-A(절대 타깃)가 test 2026을 **bias −5.7% 과소예측**(LNG 설비 증설 2026 +9.6% 미반영). 타깃을 **이용률=gen_gas_kr/LNG_cap 정규화→×용량 복원**(7-B와 동일 논리, 피처는 7-A 동일, 용량은 정규화 제수). 결과 **test 2026 bias −5.7%→+4.0%, MAPE 11.4%→10.5%, R² 0.784→0.863**. 정직한 한계: val 2025 bias +8.3%(2025가 저이용률 연도라 과보정). 용량 `kr_elec_capa.csv`(월별, 끝 이후 ffill). 산출 `model/7-A2_capacity_normalized.ipynb`·`REPORT_7-A2.md`·`lgbm_land_gas_util.txt`·`model_meta_util.json`. **권장 서빙판(절대레벨), 7-C 환산도 7-A2 사용.**
  - **7-B 제주 probe ✅**(2026-06-06): EDA(G-9 제주 통과: net_load↔LNG r=0.723, 대체효과 수요통제 −0.369) → 모델 마감판. **핵심 전환**: 제주 LNG 절대 점예측은 본질적 한계(작은 계통 unit-commitment + 설비 계단). 절대 LNG 2024 점프는 유류→LNG 설비전환(`jeju_gen_capacity.csv`: LNG 333.7→492.5MW, 유류 186→40MW). → §1.2대로 **명제 입증 중심**으로: 타깃을 이용률(lng/cap) 정규화·×용량 복원, **주 학습창 2024-01+ 안정창**. 결과 test R²0.50·MAE37.7, **net_load↔LNG r=0.777 단조증가**, **신재생 대체효과 PDP −0.314**(전국 −0.017 대비 = 명제 마무리). 학습창 비교(2022-08+ 확장)는 fleet 구성표류로 오히려 하락(R²0.36) → 안정창이 맞는 창 확인. 산출 `eda/7-B_*`·`model/7-B_*`·`REPORT_7-B.md`. **추가로 net_load별 LNG 추정 곡선** 제시. 교차-지역 작업이며 명칭만 land 폴더에 둔 것이다.
  - **7-C KOGAS 환산 ✅**(2026-06-06): 예측 발전량(MWh) → **가스 송출량(TON)** 단위변환. 산출 `model/7-C_kogas_conversion.ipynb`+`REPORT_7-C.md`+`fig/7c_*`·`tab/7c_*`.
    - **(1) 변환계수(핵심)**: 집계 발전량↔송출량 corr 0.972. **무절편 단일계수 `송출량(TON)=0.1521×발전량(MWh)`**(열효율 ~43%, 물리적 타당 → **단위 TON 사실상 확인**, G-5 부분 해결). 변환 자체 MAPE 3.6%. 연·월 안정(±2.6%, 겨울 안 부풂=난방혼입 아닌 순수 발전용). 절편식(0.1398×+5781, MAPE 3.39%)은 **연도별 절편 759~9030 불안정**으로 미채택(사용자 확정).
    - **f(기온) 검증(현장 직관)**: 발전기 흡입공기 효율 가설 검증 → corr(변환비,기온) −0.14, f(기온) 추가해도 +0.05%p·부호 반대. **전국 fleet 일집계에선 부분부하·급전구성이 압도해 기온신호 소멸** → 단일계수 유지·문서화(정직성 §5.4).
    - **(2) 최종 산출물**: test 2026 **일별/시간별 예상 송출량(TON)** — **7-A2(이용률 정규화) 적용**. **오차 분해(정직성)**: 변환만 MAPE 3.7%(견고) / **7-A2 end-to-end MAPE 7.3%·bias −3.3%**(7-A 보정 전 13.6%·−13%에서 개선).
    - **(3) 단가·수입가**: 송출량(물량)↔단가(가격) corr ≈0(독립) → 가스비=송출량×열량×고시단가 곱. 월 발전용 가스비 1.7~5.3조원.
    - **(4) 가스가격 메커니즘**: 유가(JCC)·현물(JKM)+환율 →(시차 3~5개월) 수입단가 →×환율 →+공급비 → 발전용 단가. 가격예측 자체는 비목표(§1.3).
    - 자격 앵커(KOGAS, §2·§5.3) 충족.
  - **7-A2-A 체인 검증·서빙 ✅**(2026-06-10, G-14): 5→6→7 실제 체인(예보 입력)으로 정직하게 재검증 + 다른 모델과 동일 지평(D+1/2/3/7/12). **A안(예보입력 재학습) 기각**(현행보다 0.3~0.4%p 나쁨). **채택=현행 7-A2 + 전역 bias보정 ×0.96509**: test 2026 가스 MAPE **~13%**(ORACLE 상한 10.8%, 지평 거의 평평 D+1 13.08%≈D+12 13.16%, 남는 +2.2%p=예보 전파 비가역). 서빙 `serve_land_gas.py`(체인→est_gas_gen_land·est_gas_sendout_ton_land, D+1 백필 MAPE 13.07%). **BTM/PPA=market view 확정·예측모델 불필요**(EDA 전용, G-14). 산출 `training/{build_chained_dataset,retrain_7a2a}.py`·`chained_gas_dataset.parquet`·`model/7-A2-A_chained_validation.ipynb`·`REPORT_7-A2-A.md`·`gas_serving_calib.json`.

### 데모 단계 (예정)

**8단계 — Streamlit 데모 + brief_ai (`8. streamlit`) 🔶 진행 중 (8-0 G-15 확정, 2026-06-10)**
- DoD(예정): 신재생·net_load·가스수요 차트 + 실제값 비교 + 자연어 브리핑(brief_ai). 공개 URL 배포. 상세 사양은 §6 + `8. streamlit/CONCEPT_8-0.md`.
- **8-0 ✅**: 컨셉 문서(`CONCEPT_8-0.md`) + G-15 확정 — 배포=자체 서버(로컬 DB 실시간 읽기) / brief_ai=Gemini API / 갱신=사전 적재 기본+시연용 실행 버튼 / 표시 기간=데이터 보유 범위 / SMP=데모에서 일단 제외(제주는 net_load까지).
- 작업 쪼개기: 8-A 조회 레이어+Tab 2 전국 → 8-B 제주+Tab 1 → 8-C 검증·KOGAS 탭 → 8-D brief_ai → 8-E 배포·시연 영상.

---

## 5. 방법론 (확정)

### 5.0 데이터 단계 (모델링 선행 — 확보·분리) ★
> 이 단계가 끝나기 전에는 모델링에 착수하지 않는다(게이트 G-6, 이미 완료).

**(1) 확보 — 마스터셋 결합**: 모든 소스를 `timestamp`(시간)/`date`(일)/`연월`(월) 키로 정렬·결합. 결합 직후 결측·중복·시간구멍을 **채우기 전에** 먼저 집계 보고한다.

**(2) 분리 — 정답 vs 피처 (누수 차단)**

| 구분 | 컬럼 | 규칙 |
|---|---|---|
| **검증 타깃(정답)** | 가스 발전량 (제주: `only_gen` 실측/도출분, 전국: `gen_gas_kr`) | 피처로 **절대 사용 금지** |
| **모델 입력(피처)** | net_load(real/est), 달력(hour·dow·month·`day_type`), 기온(3지점), 계절·연도추세 | 정답·정답파생 미포함 |
| **금지 피처(누수원)** | HVDC, 유류 발전, 타깃 lag, 실시간 SMP 등 발행지연 변수 | 타깃 도출/지연에 연루 → 제외 |

- **자기참조 차단**: 도출 LNG(제주 2025~2026)는 net_load에서 나온 값 → 이 구간은 정확도 산출에서 제외(데모 표시용). 엄밀한 정확도는 ① 제주 2020–2024 실측, ② 전국 `gen_gas_kr`에서만 낸다.

**(3) 분할 — 시간순(랜덤 금지)**: 권장 train 2020–2023 / val 2024 / test = 전국 2025~(전국은 실측 정답 존재). 제주 동일 골격.

**(4) 산출(게이트)**: 분리·라벨링된 학습셋 + 검증셋 + 데이터 딕셔너리. 이게 끝나야 §5.0.5로 넘어간다.

### 5.0.5 관계 탐색·시계열 분석 (모델링 직전 — 게이트 G-9) ★
> §5.0/G-6은 "데이터가 멀쩡한가"(구조)였다. 이 단계는 "명제가 데이터에 실제로 있는가"(관계)를 본다. 모델 착수 전 필수이며, 모든 모델링 단계에 적용한다.

- **관계**: 핵심 입력(net_load) ↔ 타깃의 강도·형태. 급전순위 때문에 **부하수준별 비선형**일 수 있음(저부하=가스 거의 없음, 고부하=가스가 한계분).
- **시계열 구조**: 주기성(시·요일·월·계절), 추세, 안정성, 분포·이상치·구조적 단절(레짐 변화 시점).
- **시간적 안정성**: 연도별로 같은 입력에 대한 타깃이 표류하는지(석탄·원전·신재생 증감 → 가스 급전순위 위치 변화 → 함수 표류).
- **분포 겹침(covariate shift)**: train↔test 입력 분포가 겹치는지. 벗어나면 모델이 외삽하게 되어 "정직한 검증"이 흔들림 → 모델 전에 확인.
- **산출(게이트 G-9)**: 위를 담은 보고서(표·그림, notebook 선호). 표류·분포 이탈이 있으면 처리 방안(레짐 피처·학습창·기대치)을 정한 뒤 모델 착수.

### 5.1 과거 가스 타깃 시계열 구축 (도출)
1. `net_load = 계통수요 − 신재생`.
2. `fuel_gen = net_load − HVDC` (= 유류 + LNG).
3. LNG/유류 분해: **급전순위(유류 → LNG) 기반, 부하수준별 분해**(merit-order). 저부하는 사실상 유류, 부하가 오를수록 LNG가 한계분을 채운다. 단일 비율보다 충실하다.
   - 제주 2020–2024는 `only_gen` 실측을 그대로 정답으로 사용(도출 불필요).

### 5.2 예측 경로 (서빙 — net_load → LNG)
- forecast에 HVDC가 없으므로, 위 타깃으로 `LNG_gen = f(net_load, 달력, 기온, 계절)`을 학습 → `est_net_load`에 적용해 가스 발전 예측을 낸다. HVDC는 함수가 암묵적으로 흡수한다.

### 5.3 가스 수요·비용 환산 (KOGAS 연결 = 자격 핵심)
- 예측 가스 발전량(MWh) → 발전용 가스 수요/비용으로 환산: `gas_tariff`(원/GJ·Nm³)·`gas_import_price`($/MMBTU)·`gas_temp_effect`를 월 해상도로 join. KOGAS 데이터는 net_load 도출과 독립이라 자기참조 없는 점검 역할도 겸한다.

### 5.4 검증 계층 (정직성 = 강점)

| 레벨 | 정답 | 자기참조 | 산출 |
|---|---|---|---|
| 제주 2020–2024 | `only_gen` 실측 LNG | 없음 | **MAE/MAPE (핵심 수치)** |
| 제주 2025–2026 | 도출 LNG | 있음(주의) | 데모 연속성, "추정" 표기 |
| **전국** | `gen_gas_kr` 실측 | **없음** | **검증 목표 2 — 가장 강한 증거** |
| KOGAS 연결 | 가스 공급량·단가 | 없음 | 방향성 정합 확인 |

---

## 6. Streamlit 데모 사양

### 6.1 페이지 구조
- 사이드바: 날짜 선택, 지역 선택(제주 / 전국), 예측 실행 버튼, (관리자) 캐시 초기화.
- Tab 1. 개요: 프로젝트 한 줄 설명 + 모델 구조 다이어그램.
- Tab 2. 예측 대시보드(핵심): 상단 brief_ai 카드(자연어 브리핑) + 중단 차트(날씨 / net_load / 가스수요 예측 vs 실제) + 하단 시간대별 수치 테이블.
- Tab 3. 모델 검증: MAE/MAPE, 최근 오차 추이, 모델 구조 설명.
- Tab 4. 전국 확장: 전국 net_load → 가스 발전 검증 결과 + 시장 구조 차이 설명 박스("전국은 시범사업 미적용으로 SMP 비대상. net_load·가스수요 예측만으로도 발전사업자 출력 계획에 직접 활용 가능").

### 6.2 brief_ai 사양
- 입력: 예측 결과(날씨·net_load·가스수요 예측값·실제값·통계).
- 출력: 3~5문장 자연어 브리핑(기상 개황 / net_load 변동 / 가스수요 동향 / 발전사업자 액션 제안).
- 모델: Gemini API. API 실패 시 "AI 브리핑 일시 사용 불가" 표시 + 차트는 그대로.
- 목적 메모: brief_ai는 단순 기능이 아니라 공모전 가점 유도가 명시적 의도다. 의미 있는 인사이트가 나오도록 프롬프트에 시간을 투자한다.

### 6.3 운영 정책
| 항목 | 정책 |
|---|---|
| 데이터 수집 | crontab 백그라운드, 사용자 트리거 불가(API 한도 보호) |
| 예측 실행 | 캐시 우선. 캐시 없을 때만 실시간 실행 |
| 예측 실행 버튼 | IP당 시간 N회 제한(무한 클릭 방지) |
| brief_ai 호출 | 같은 날짜+지역은 24시간 캐시(API 비용) |
| 표시 가능 날짜 | 데이터 보유 기간으로 제한 |

---

## 7. Decision Gate (G-n)

> 해결된 게이트도 삭제하지 않는다(추적용). 새 결정거리는 번호를 증가시켜 추가한다.

### 해결됨
- [x] **G-1. net_load 정의** (2026-06-03) — `real_net_load_jeju = 수요 − 신재생 총량`(평균절대차 0.000). 신재생 총량이 태양광+풍력보다 약 10.6MW 큼(기타 신재생 포함). DB 컬럼은 2025-12-13~만 존재 → 2020–2024는 식으로 직접 도출.
- [x] **G-2. only_gen vs DB 정합** (2026-06-03) — 2020–2024 `(net_load − HVDC)` vs `(LNG + 유류)` 상관 0.955, MAE 22.2MW, 편향 +2.4MW. 도출식 점검 통과.
- [x] **G-3. HVDC 가용 구간** (2026-06-03) — 마스터 HVDC는 2017-01~2025-04 결손 0. 이후 구간은 미보유 → 도출은 2025-04까지, 그 이후는 예측 경로로 처리.
- [x] **G-4. 분해 비율 형태** (2026-06-03) — 급전순위 기반 부하수준별 분해(merit-order) 채택. 기준연도 2024. 백테스트에서 단일 비율 대비 MAE −13.7%·MAPE −5.5%p 개선. 산출 `fit_merit_split.py` / `merit_split_2024.json`.
- [x] **G-5. `lng_supply_national_daily` 단위** (2026-06-03 → 2026-06-06 부분해결) — 미확정으로 보류했으나, **7-C에서 사실상 TON으로 확인**: 집계 발전량(MWh) 대비 송출량 회귀계수 0.1521 ton/MWh = 함의 열효율 ~43%로 물리적으로 타당(LNG 55 GJ/ton 기준). 변환 MAPE 3.6%·월/연 안정. = `daliy_lng_gen_21-26.csv`와 동일 시계열. 발전용 송출량(TON)으로 사용 확정.
- [x] **G-6. 데이터 분리 완료 게이트** (2026-06-03) — A0 완료: 결합(중복 0·구멍 0)·정답/피처/금지 라벨링·시간순 분할·딕셔너리. 학습/검증/테스트 기본 피처·타깃 NaN 0. → 모델링 착수 가능.
- [x] **G-10. 전국 `gen_gas_kr` 실측 시작 = 2022-01 (학습창 재정의)** (2026-06-06) — 7-0 EDA에서 발견: 2020(0 비율 100%·max 0)·2021(97% 0)은 가스 실측이 아니라 결측을 0으로 채운 값(실측은 2022-01부터, 2021-12 전환기). A0 감사(G-6)는 NaN만 봐서 통과, `model_usable`이 2020-2021을 잘못 True로 라벨. **해결**: 학습창 재정의 = **train 2022–2024 / val 2025 / test 2026**(parquet의 `split` 컬럼 대신 7-A 로드 시 연도로 재정의). 2020-2021은 **7-A 로드 시 필터**(parquet 유지, 빌더 재빌드 안 함). 빌더 라벨 수정은 보류(필요 시 G-8과 함께). 주의: test=2026은 1~6월 부분 구간(약 3,700행).
- [x] **G-11. BTM/PPA 복원 신재생 반영** (2026-06-06) — (c) 역추정 채택·구현. `ppa_scale.csv`(월간 PPA 시장규모)+태양광이용률로 PPA 역추정(k=0.7108), BTM=0.3153·PPA, 2020-01~2024-10 estimated 라벨(`backfill_btm_ppa.py`→`land_renew_reconstructed.parquet`). 검증: 진짜 신재생계수 −0.332(estimated −0.319≈measured −0.363). **해결(둘 다 유지)**: ① 7-A(현행, 2022-24, 수요+계통신재생, R²0.784, 순수실측 긴이력)=메인 예측 유지 ② 7-Ar(신규, 2024-11+ 실측전용, true_demand+true_renew, R²0.798·MAPE12.0%, 신재생 중요도 15.4%, 순수실측)=대체효과 설명 ③ 7-0b=전 기간 대체효과 EDA(역추정). 복원판 단일화(R²0.766, 학습에 역추정)는 실측전용보다 열세라 미채택.
- [x] **G-9. 관계 검증(EDA) 게이트 — 모든 모델링 선행** (2026-06-06) — 7-0 EDA로 통과. 2022+ 기준 net_load↔gas 상관 r=0.83(강함), 부하수준별 비선형, 타깃 0 비중 0%(항상 켜짐), 연도 안정(표류 없음), train↔test net_load 겹침 안전(외삽 0.7%). 발견된 데이터 결손은 G-10으로 분리·해결. 산출 `7. land_gas_forecaster/eda/`(notebook·리포트·그림6·표3). 이후 모든 모델링 단계도 동일 게이트 적용.
- [x] **G-7. 전국 트랙 진입 순서** (2026-06-06) — **7단계 먼저** 확정. 전국 historical `net_load_kr` 실측으로 net_load → `gen_gas_kr` 검증을 바로 수행(예측기 5·6 없이도 명제 입증 가능). 명제 입증(§1.2 검증목표 2)이 목적이고 마감까지 약 4주라 최단 경로. 예측기 5·6은 7단계 검증 통과 후 후순위.
- [x] **G-12. 전국 수요 모델 구조·지평·7일 예보 수집** (2026-06-07) — ① 구조: **LGBM 단독·직접 다지평**(재귀 아님 — lag168이 전 지평 직접 가용). 풀드(5-A) + 지평별 Direct-H(5-A2) 둘 다 보유, 풀드가 근소 우위. 베이스라인 상회로 PatchTST 불필요. ② 기상 피처: 기온·일사·풍속(예보 가용분만). ③ 공휴일: lag_dt A/B 후 효과 미미로 미채택. ④ **7일 예보 수집**: KIMG 전구 00/12 UTC=288h·06/18 UTC=87h. ≤72h는 기존 신선 발표·>72h는 12 UTC `--kimg-days 7`. 서빙 무변경(예보 쌓이면 자동 사용), 백필은 사용자 직접. 산출 `5. land_demand_forecaster/`(eda·model·serve).

- [x] **G-14. 7단계 체인 서빙 구조 + BTM/PPA 관점** (2026-06-10) — ① **A안(예보입력 재학습) 기각**: 체인입력 재학습이 현행 7-A2(실측학습)보다 0.3~0.4%p 나쁨(노이즈 감쇠·train/test 노이즈구조 차이). ② **채택 서빙 = 현행 7-A2 + 전역 bias보정 ×0.96509**(val2025): test 2026 가스 MAPE ~13%(전 지평 평평, ORACLE 10.8%·차이는 예보전파 비가역). ③ **BTM/PPA = market view 확정, 예측모델 불필요**(사용자: 신재생[market+btm+ppa]→전국 수요에 영향→가스 수요에 영향, EDA에서 이미 확인. 자가소비는 계량수요에 차감되어 숨고 가스는 그리드 net_load에 반응). 예측 체인(5→6→7)은 계량수요+시장신재생만 사용. BTM/PPA·대체효과는 **EDA 전용**(7-0b·7-Ar·제주 7-B). 6단계 est_true_renew/est_true_demand는 예측 미사용·분석용 보존. 산출 `serve_land_gas.py`·`7-A2-A_chained_validation.ipynb`·`REPORT_7-A2-A.md`·`gas_serving_calib.json`.

- [x] **G-13. 6단계 전국 신재생 모델 구조·지점·지평** (2026-06-08) — ① 구조: **LGBM-direct 다지평 단일** 주력(5-A·3단계 결론 일관), **PatchTST는 D+1/D+2/D+3에서만 비교(6-B)** → 큰 차이 없으면 LGBM 단일(사용자 방침). ② 지평 **D+1~D+12**(5-A2·3단계 land 일관). ③ 타깃 **이용률(gen/cap) 정규화→×용량**(solar_cap 3.4배 표류라 절대값 학습 부적합, DB `gen_solar/wind_utilization_kr` 사용). ④ 지점(사용자 확정, 용량·상관 근거): **solar=영광(전남)+서산(충남)+포항(경북)** 용량 61%·solar_rad 상관 0.69~0.75 / **wind=대관령(강원)+영광(전남)+포항(경북)** 용량 ~90%·대관령 풍속상관 0.607 압도. 합집합 4지점. **용량보다 예보↔이용률 상관으로 고른다**(제주 교훈). ⑤ 후처리 불가: land forecast엔 강수·cape·tcog 없음 → solar_damping·tcog 미적용(제주와 차이, 피처 슬림). **최종 피처 입력은 6-0 EDA 후 §0.6대로 확정.**

- [x] **G-15. 8단계 데모 배포·구성** (2026-06-10) — ① **배포 = 자체 서버 호스팅**(로컬 DB 실시간 읽기, Community Cloud 스냅샷 방식 미채택) ② **brief_ai = Gemini API**(기존 §6.2 유지) ③ **갱신 = 사전 적재 기본**(서빙 5→6→7 순서 cron) **+ 시연용 실행 버튼 병행** ④ **표시 기간 = 데이터 보유 범위**(전국 est 백필 2026-02~, 제주 2025-12~) ⑤ **SMP = 데모에서 일단 제외**(제주는 net_load까지, 전국 가스 체인 중심. 필요 시 재논의).

### 열림(전국 트랙)
- [ ] **G-9. 관계 검증(EDA) 게이트 — 모든 모델링 선행** — 모델 착수 전 net_load → 타깃 관계의 강도·형태(부하수준별), 시간적 안정성(함수 표류 여부), train↔test 분포 겹침을 확인(§5.0.5). G-6이 "데이터가 멀쩡한가"였다면 G-9는 "명제가 데이터에 실제로 있는가". 표류·분포 이탈 시 처리 방안을 정한 뒤에만 착수. 단계마다(7·5·6 등) 적용. **피처 최종 입력은 EDA 후 사용자에게 묻고 확정한다(§0.6).**
- [ ] **G-8. 전국 원천 CSV 위치** — `second_dataset/build_dataset.py`의 `CSV` 입력(oil_price, KOGAS, HVDC, only_gen) 실제 경로 확정 필요. 현재 코드의 `"7. data from csv"`는 존재하지 않는 폴더(stale)라 TODO로 표시됨. 빌더 재실행 시에만 영향(현재 parquet는 이미 생성됨).

---

## 8. 진행 로그 (최신이 위로)

**2026-06-10 — 8단계 착수: G-15 확정(8-0) + 가스 백필 + 8-A 전국 체인 대시보드**
- 무엇을: `CONCEPT_8-0.md` 기준으로 G-15 5건 확정(§7) 후 8-A 구현. ① 배포=자체 서버(로컬 DB 실시간 읽기) ② brief_ai=Gemini ③ 사전 적재 기본+시연 버튼 병행 ④ 표시 기간=데이터 보유 범위 ⑤ SMP 데모 제외(제주는 net_load까지).
- **데이터 점검·백필**: `est_gas_gen_land`가 2026-06-01 하루(24행)만 적재된 공백 발견 → `serve_land_gas.py backfill 2026-02-01~05-31`(D+1) 적재, 발전량 MAPE 13.02%·bias +3.1%(7-A2-A 13.07% 재현). 제주는 `jeju_est_demand_lh` 컬럼 부재·`est_net_load_jeju_lh` 1주뿐 → **8-B 전에 제주 서빙 백필 필요**.
- **8-A 완료**: `8. streamlit/app.py` — 읽기 전용 DB 조회 레이어(`st.cache_data` ttl 600s), 사이드바(지역/기준일/지평 D+1~7), Tab 2 전국 = 지표 5종 + 체인 차트 스택(기상 5지점 평균 / 수요 vs 신재생 / net_load / 가스 MW·TON, 실측 점선 오버레이) + 구간 MAPE 캡션(정직성 §5.4) + 시간대별 테이블. 가스비 = 송출량×55GJ/ton×월 단가(`7c_monthly_price_cost.csv`). 과거 구간은 "매일 갱신 D+1" 표시로 정직하게 안내(기준일 고정 다지평은 시연 버튼에서, 8-D). AppTest 검증: D+1·D+7·과거 origin·제주 분기 모두 예외 없음, 2026-03 구간 가스 MAPE 11.9% 표시 확인.
- 다음: 8-B(제주 탭+Tab 1 개요, 선행=제주 서빙 백필) → 8-C(검증·KOGAS 탭) → 8-D(brief_ai·시연 버튼) → 8-E(배포·시연 영상).

**2026-06-10 — 7단계 체인 검증(5→6→7): A안 재학습 기각·bias보정 채택·서빙 신설 + BTM/PPA 결정(G-14)**
- 무엇을: 5(수요)→6(신재생)→7(가스) 연계·정확도를 EDA 건너뛰고 입력 건전성 중심으로 점검. 7-A2를 서빙(예보) 입력으로 재학습(A안) 시도 + 다른 모델과 동일 지평(D+1/2/3/7/12) 검증.
- **연계 점검**: ① 정의 건전 — `renew_gen_total_kr`=`gen_solar_market_kr`+`gen_wind_kr`(잔차 std 0) → 6단계 `est_market_renew_land`가 7 학습피처의 올바른 짝. ② **5→6 단절 발견·복구** — forecast에 `est_demand_land` 컬럼이 없어 6단계가 KPX(`land_est_demand_da`) 폴백 중이었음. `serve_land_demand.py backfill --days 1 --write`로 적재(D+1 MAPE 4.15%). ③ 데이터 제약: 진짜 forecast 기상은 2025-12부터만 존재 → train창은 체인 백필(기후값 폴백)로 생성.
- **체인 데이터셋**: `7. land_gas_forecaster/training/build_chained_dataset.py` → `chained_gas_dataset.parquet`(193,800행, train130,920/val43,800/test19,080). 수요=5-A2 지평별·신재생=6단계 `_predict_day` 지평별·기상=예보→(월,시)기후값·타깃=실측 gen_gas_kr. 입력 bias 전구간 수요 −220~−317MW·신재생 −50~−68MW.
- **★ A안 기각(정직한 음성결과)**: 체인입력 재학습(`retrain_7a2a.py`→`lgbm_land_gas_util_chained.txt`)이 현행 7-A2보다 0.3~0.4%p 나쁨. 체인입력 bias는 작고(수요 0.5%) 진짜오차는 분산(노이즈)→errors-in-variables 감쇠; train(기후값)↔test(실예보) 노이즈구조 차이로 정렬이득 없음. → 미채택(실험 파일만 보존).
- **★ 결과·채택**: test 2026 지평별 가스 MAPE — ORACLE(실측입력 상한) 10.81% / 현행+체인 13.88(D+1)~14.16(D+12)% / A안 14.23~14.58% / **채택=현행 7-A2+전역 bias보정 ×0.96509(val2025) 13.08~13.16%**. **지평 거의 평평**(D+1≈D+12, 입력품질이 지평별 비슷)→D+12까지 D+1 수준. 남는 +2.2%p(vs ORACLE)=예보 전파 비가역오차(§5.4).
- **서빙 신설**: `serve_land_gas.py` — forecast.est_demand_land·est_market_renew_land 읽어 util×LNG_cap×보정 → `est_gas_gen_land`(MW)·×0.1521 → `est_gas_sendout_ton_land`(TON) UPSERT. 검증(D+1 백필 2026-02~05) 발전량 MAPE 13.07%·bias +3.2%. 보정·변환계수 `model/gas_serving_calib.json`.
- **모델 피처 재확인**: 입력=real_demand_land(←5 est_demand_land)+renew_gen_total_kr(←6 est_market_renew_land=시장 solar+wind)+달력4(hour/dow/month/doy)+day_type / 타깃 util=gen_gas_kr/LNG_cap→×용량×보정. 제외=기온·year·net_load(분해 내포)·HVDC·유류·타깃lag(누수).
- 산출 `model/7-A2-A_chained_validation.ipynb`·`REPORT_7-A2-A.md`·fig/tab(7a2a_*)·`gas_serving_calib.json`·`serve_land_gas.py`·`training/{build_chained_dataset,retrain_7a2a}.py`.
- 다음: 8단계 Streamlit 데모(5→6→7 체인 + brief_ai)는 별도 결정.

**2026-06-08 — 6단계 전국 신재생 착수: G-13 확정(구조·지점·지평) + 6-0 EDA 진행**
- 무엇을: 6단계(land_net_load) 시작. 사용자 제공 지역별 발전 TOP5 + DB 5지점(대관령·원주·서산·포항·영광) 매핑·상관 분석 후 G-13 확정.
- 지점 상관(탐색): solar_rad↔solar_util(낮) 영광0.754·서산0.722·원주0.709·포항0.690·대관령0.656 / wind_spd↔wind_util 대관령0.607·영광0.449·서산0.424·포항0.345·원주0.314. **용량 표류 solar_cap 2,746→9,441MW(3.4배)·wind_cap 1,208→1,617MW** → 이용률 정규화 필수.
- 결정(G-13): LGBM-direct 다지평 주력 + PatchTST D+1~3만 비교, D+1~D+12, 이용률 정규화. 지점 solar=영광+서산+포항·wind=대관령+영광+포항(사용자 확정). 후처리 불가(forecast에 강수·cape·tcog 없음).
- **6-0 EDA 완료(G-9 통과)**: ① 이용률 정의 = **시장 태양광 기준**(util×cap=gen_solar_market_kr 상관 1.000, BTM/PPA는 수요에 숨음), net_load 재구성=수요−util×cap (DB net_load_kr와 corr 0.946·평균차 −667MW) → 서빙공식 타당. ② 용량표류 solar 3.44배→정규화 필수, **2022 낮 이용률 0.273 급락**(설비 준공 전 용량 계상 의심, 6-A에서 점검). ③ 공간평균이 단일지점보다 우수(solar 0.786·wind 0.641) → G-13 검증. ④ 풍력 자기상관 lag24 0.447→lag48 0.243 붕괴→direct 근거. ⑤ 흐린/맑은 이용률비 0.51. ⑥ 후처리 불가 확정(forecast에 습도·강수·적설·cape/tcog 없음). ⑦ covariate shift 안전. 산출 `eda/6-0_eda_landsw.ipynb`·`REPORT_6-0_eda.md`·그림5·표4.
- **humidity·rainfall backfill 완료(2026-06-08)**: forecast에 reh·rainfall 5지점 추가(NaN 1.7%, 2025-12-13~). historical은 전 기간 가용 → **6단계 후처리 제약 해소**(rainfall로 solar_damping 부활). 메모리 land-forecast-reh-rain 참조.
- **공선성·중요도 분석(태양광 후보)**: rad·cloud·humidity·solar_damping·clearsky_ratio가 전부 '맑음' 축으로 공선(rad↔clearsky 0.71). VIF clearsky 15.0·humidity 12.0(>10 위험), LGBM gain rad **79%**·나머지 1~3%(perfect 기상 기준 — forecast에선 보완 가능성). 측정 일사가 실제 구름을 이미 반영해 대리변수 한계기여 작음.
- **LGBM 최종 피처 확정(2026-06-08, §0.6)**: **SOLAR = solar_rad + total_cloud + solar_damping(일강수 06-20h합 exp(−k·clip)) + hour·doy(sin/cos), 선택3지점 평균** / **WIND = wind_spd + wd_sin/cos + hour·doy(sin/cos), 선택3지점 평균**. clearsky_ratio·humidity 제거(공선성·중복, 사용자 확정), temp·midlow 미채택, year 미채택(2026 외삽). **solar_damping은 유지**(강수 event = rad 직교정보, perfect 중요도 작아도 forecast 검증 예정). PatchTST 피처는 6-B에서 별도(3지점 raw 시퀀스). **이용률은 lag 없어 지평무관 단일모델(채널당)이 D+1~D+12 전부 서빙.**
- **6-A LGBM-direct 완료**: 시장신재생 이용률 채널별 단일모델(지평무관→D+1~D+12 단일서빙). 공선성 해소 후 VIF<4. 중요도 SOLAR rad 80%·WIND spd 56%. **util MAE: SOLAR 낮 perfect 0.112/forecast 0.127·WIND perfect 0.099/forecast 0.143**(예보 풍속오차로 악화, 제주 동형). **solar_damping 검증 성공: forecast full 0.127<rad-only 0.135**(perfect 중요도 0.7%여도 forecast 보완 — 현장 직관 적중). **net_load nMAE(일관 기준=수요−시장신재생): perfect 0.96% vs 기후값 1.51%·forecast 1.07% vs 1.44% → 베이스라인 상회.** 산출 `model/6-A_landsw_lgbm_direct.ipynb`·`REPORT_6-A.md`·`lgbm_land_{solar,wind}_util.txt`·표3·그림1.
- **★ net_load 정의 규명**: `net_load_kr = gen_total_kr − renew_gen_total_kr`(차이 0), renew_gen_total = **시장 태양광+풍력만**(BTM/PPA·nre·수력 제외, 총발전 기준). 우리 산출물=수요기준 신재생예측이라 ~3,550MW(손실·양수)+BTM/PPA 상수 오프셋. **7-A는 net_load_kr 직접 안 쓰고 real_demand+renew_gen_total 피처 → 6단계(신재생)+5단계(수요) 체인 정합.** net_load_kr은 참조 컬럼.
- **6-A2 전체 신재생(true_renew) 완료**(사용자 지적: market만으론 net_load 불충분, BTM/PPA가 net_load 크기·대체효과에 영향): BTM/PPA는 시장 태양광과 **같은 이용률 공유** → **utilization×capacity 통합**(`total_solar_cap = market_cap + k(1+r)·ppa_cap`, k=0.7108·r=0.3152, 7-0b backfill 재현). 6-A 모델 재사용. **검증(측정구간 2024-11+): util×cap 복원 vs 실측 PPA+BTM MAE 235MW(6.4%)·corr 0.996, 내포 PPA이용률↔시장이용률 corr 0.99**(같은 이용률 가정 실측 확인). 유효 총 태양광=시장 3.35배.
- **★ net_load 산술 동일·신재생 분해가 핵심**: `net_load_true = true_demand−true_renew = net_load_market`(BTM/PPA 상쇄, 평균차 0.0). 진짜 다른 건 **신재생 총량 ~2.8배**(2025 market 2,006→true 5,566MW)이고 이것이 7-0b 대체효과(−0.332) 신호. → 6단계 산출 2종: **est_market_renew(→7-A) · est_true_renew·est_true_demand(→7-Ar)**.
- **true_renew 정밀도(test 2026, PatchTST 판단 근거)**: market MAE 564MW(23.7%)/forecast 664MW(27.9%), **true MAE 1,836MW(27.4%)/forecast 2,112MW(31.6%)**. 복원 근사 하한(util 실측) 393MW → 나머지 ~1,440MW가 util 예측오차. **net_load엔 PatchTST 무의미였으나 true_renew(태양광 지배)엔 정밀도가 작동** → 6-B PatchTST 검토가치 생김. 산출 `model/6-A2_true_renew.ipynb`·`REPORT_6-A2.md`·`btm_ppa_recon_6a2.json`.
- **6-B 범위 확정(사용자, 2026-06-08)**: **풍력=LGBM D+1~D+12 확정**(제주와 동일, 비교 안 함). **태양광만 PatchTST vs LGBM을 D+1/D+2/D+3 비교 후 결정**(true_renew에서 태양광 정밀도가 작동한다는 6-A2 근거). 근거: net_load는 PatchTST 무의미였으나 true_renew(태양광 지배·×3.3)에선 util 예측오차(~1,440MW)가 큰 덩어리. land solar PatchTST 가중치는 제주처럼 사용자가 GPU/Colab 직접 학습(3지점 raw 시퀀스, direct D1/D2/D3 offset 0/24/48). 인프라(export CSV + Colab 노트북 생성기)는 `6. land_solarwind_forecaster/training/`에 제주 패턴 미러링.
- **6-B 완료 — 태양광 PatchTST 큰 차이로 우세(제주와 다름)**: 사용자 학습 가중치(landsolar_patchtst, d_model=128·layers=3·d_ff=512 변경, 14피처 3지점 raw, D1/D2/D3 direct). 동일 test 2026, PatchTST(과거336h+대상일기상) vs LGBM 6-A(기상-only 지평무관). **낮 util MAE: PatchTST perfect 0.038~0.041 vs LGBM 0.112~0.115(~2.8배), forecast 0.070~0.074 vs 0.129~0.131(~1.8배)**. 흐린날도 우위. **true_solar MW MAE(낮) forecast PatchTST ~2,000MW vs LGBM ~3,700MW(~1,700MW 개선)** — true_renew 정밀도 핵심(6-A2)이라 결정적. 우위 상당부분은 past_y(실측 이용률 시퀀스, 서빙 가용=반칙 아님). LGBM 수치는 6-A와 정확 일치(검증). 산출 `model/6-B_compare_solar.py`·`REPORT_6-B.md`·`tab/6-B_compare.csv`·`fig/6-B_compare.png`.
- **채널 분리 확정(G-13 충족)**: **태양광 = PatchTST(D+1/2/3) + LGBM(D+4~D+12 폴백)** 하이브리드(제주 동형) / **풍력 = LGBM 전지평**. 가중치 `training/landsolar_patchtst/`(D1/2/3 + scaler + metadata).
- **6-C 서빙 완료 — 6단계 종료**: 사용자가 PatchTST solar **D+1~D+7, D+12** 학습(이 지평만 서빙). `serve_solarwind_land.py`(자기완결): **태양광=PatchTST(D1~7,D12)+LGBM 폴백·풍력=LGBM 전지평**. 산출 `est_solar/wind_util_land`·`est_market_renew_land`(→7-A)·`est_net_load_land`·`est_true_renew_land`·`est_true_demand_land`(→7-Ar, ×total_solar_cap). 기상 forecast 우선·기후값 폴백, 수요 est_demand_land(5단계)→KPX 폴백. **검증(백필 D+1 2~5월): SOLAR util MAE(낮) 0.087**(PatchTST 재현, LGBM 0.129 우위)·WIND 0.139(6-A 일치). CLI predict/backfill. 산출 `serve_solarwind_land.py`·`REPORT_6-C.md`.
- **wind PatchTST 미연구 결정(사용자 질의)**: 풍력 자기상관 24h 붕괴(past_y 무력)·제주서 forecast 악화·true_renew 비중 작음(태양광 지배)·예보 풍속오차는 모델 무관 → 풍력은 LGBM 유지.
- **다음: 8단계 Streamlit 데모**(신재생→net_load→가스 + brief_ai). 선택: 5단계 serve로 est_demand_land 적재 시 6-C 수요 자동 end-to-end.

**2026-06-08 — 3단계 net_load 점검: PatchTST vs LGBM 비교(흐린날 과대예측·장지평) → 6단계 골격 시사**
- 무엇을: 6단계(land_net_load) 착수 전, 3단계 제주 net_load 예측기(PatchTST 기반)의 성능·장지평 가능성·흐린날 과대예측을 LGBM과 비교. 산출 `3. jeju_solarwind_forecaster/comparison/`(eda·model·fig·tab + `REPORT_3cmp-0_eda.md`·`REPORT_3cmp-B_comparison.md`).
- 설계(사용자 확정): 평가=이용률+net_load 둘 다 / 기상=실측(perfect) 우선·forecast 보조 / PatchTST 장지평=재귀 롤링 / LGBM=순수기상 horizon-무관 단일모델. **피처(§0.6 확정)**: SOLAR=PatchTST피처(solar_rad·cloud·midlow·damping west·south)+clearsky_ratio+month, WIND=PatchTST 동일(spd·zone west·east+풍향+hour+year).
- 3cmp-0 EDA(G-9 통과): 용량 표류 큼(solar 254→405·wind 258→364MW)이나 이용률 정규화로 연도 안정. solar_rad +0.88·cloud −0.54 주구동. **흐린날(1109일)>맑은날(536일)**, 흐린날 정오 이용률 ~0.33 vs 맑은날 ~0.80. **wind 자기상관 24h 후 급붕괴(0.31→0.11)** → 재귀 롤링 wind 장지평 불리 근거.
- **핵심 결과 ① 실측기상**: solar/net_load MAE 사실상 동률. PatchTST는 재귀 롤링이라 지평 늘수록 음의 bias·MAE 열화(D+1 net_load nMAE 6.6%→D+6 6.9%), LGBM은 평평(7.2%→7.1%). **실측기상에선 흐린날 과대예측 없음**(PatchTST −0.005·LGBM +0.008) → 사용자 관찰은 모델 탓 아님.
- **핵심 결과 ② forecast(실서빙 D+1)**: 흐린날 과대예측 재현(PatchTST +0.054·LGBM +0.078·ablation +0.057) → **원인=forecast 기상 오차(공통), LGBM도 해소 못 함**(clearsky_ratio가 틀린 예보일사 증폭해 근소 더 심). net_load는 **LGBM 우위(10.6% vs 11.3%)**, wind 예보편차도 PatchTST가 크게 증폭(+0.12 vs +0.07) → LGBM이 forecast에 견고.
- 결론: D+1 단기=PatchTST 강점, **장지평·실서빙 견고성=LGBM-direct 우위**. 흐린날 과대는 forecast 보정 과제(모델 교체 무관). → **6단계 전국 net_load는 LGBM-direct 단일로 시작 권고**(land 5·7과 일관).
- 후처리 확인(사용자): 구버전 solar_sigmoid 후처리는 **`solar_damping` 피처가 대체**(비교에서 양쪽 적용됨), wind cut-off(25m/s↑→0)는 **wind PatchTST가 이미 학습**. → 비교 재실행 불필요·유효.
- **하이브리드 결정(사용자)**: 실사용 핵심 **D+1~D+3=PatchTST**(D+2/D+3는 **direct 지평별 재학습**, 재귀 롤링 아님) + 시연 장지평 **LGBM-direct**. 통합 서빙 wrapper로 묶음(2·5단계 이원 구조와 일관). **3cmp-D 학습노트북 `training/train_solarwind_direct_d2d3_colab.ipynb`+생성기 `_gen_notebook_direct.py`**(Dataset future/target에 offset만 추가, 아키텍처·피처·손실(흐린날 과대페널티 포함)·스케일러·metadata 전부 D+1과 동일·재사용. HORIZONS 딕셔너리만 수정=offset 24배수 일경계. 사용자가 GPU로 D2~D6 학습 중). PatchTST/LGBM 경계는 노트북 지평별 test MAE로 실측 결정(경험상 ~D+3~4).
- **지평 범위(사용자 확정)**: 제주는 **D+7까지**, 전국 6단계는 **D+12까지**(land 5-A2와 일관).
- **LGBM 서빙 본체 완성(3cmp-E)**: `serve_solarwind_lgbm.py`(+`lgbm_models/`). **util은 지평 무관(lag 없음)이라 단일 모델 1개(채널당)가 D+1·2·3·7 전부 서빙** — 지평별 가중치 불필요(수요 5-A2와 결정적 차이). forecast 기상 우선·없으면 (월,시) 기후값 폴백(2-B·5-B 패턴). net_load=수요(forecast)−gen. 출력 `est_*_jeju_lgbm`(PatchTST D+1 출력과 분리). 검증: 폴백 정상, 서빙 정확도=3cmp-C(낮 solar MAE 0.109·wind 0.129) 일치, DB write 확인.
- **피처 중요도(LGBM)**: solar=rad_west 57%+hour 18%+clearsky_ratio 14%(상위3=88%), wind=spd_west 57%+spd_east 17%+year 11%. wind_zone 거의 미사용(풍속 clip20로 cutout 표현 약함, 극단풍속 희소라 영향 작음).
- **ramp/vol 피처 실험·기각(사용자 제안)**: 실측기상선 wind +5.5% 개선이나 **forecast에선 악화**(0.131→0.133) — 예보 풍속이 매끄러워 ramp가 노이즈. solar는 애초 무효. → 서빙=base 피처 유지(2단계 QM 교훈과 동형).
- **forecast 전용변수 분석(3cmp-2, 사용자 제안)**: cape/hpbl/gust/cinn/tcog는 모델입력 불가(historical 없음) → 후처리 후보. **데이터품질: cape 83%·cinn 97%가 9999 sentinel·tcoh 상수0**(허위상관 주의). **tcog(대류운)만 의미**: 대류일(tcog>0, ~7%) solar 과대(−0.069)·wind 과소(+0.132)로 양채널 일관·해석 명확. cape/cinn/tcoh/gust/hpbl 미사용. → **후처리는 서빙 본체 다음, tcog 1개만 가볍게, 평가는 랜덤스플릿(계절 골고루, 사용자 지시)**. 산출 `comparison/REPORT_3cmp-2_*`.
- **3cmp-G direct PatchTST vs LGBM(가중치 D2~D6 학습 완료, `solarwind_patchTST_pkl/`)**: 실측기상 test 2026. **핵심: 지평이 아니라 채널로 갈림** — SOLAR=PatchTST 우위(실측 D+1~5·forecast도 흐린날 포함), WIND=LGBM 전지평 우위(PatchTST는 forecast 풍속오차 증폭). direct solar D+2 최저(0.0625), direct wind는 D+3+ 악화.
- **하이브리드 확정·완성(사용자, 채널분리)**: **solar=PatchTST(D+1~6 direct, D+7+ LGBM 폴백) + wind=LGBM 전지평**. 통합 서빙 **`serve_solarwind_hybrid.py`**(단일 진입점 D+1~7, solar direct는 offset이 origin↔target 메워 재귀 아님, wind/cap/demand/폴백은 serve_solarwind_lgbm 재사용, 출력 `est_*_jeju_lh`). **end-to-end 검증(forecast D+1): 하이브리드 net_load nMAE 13.63% < LGBM단독 14.10%**(채널분리가 두 단독보다 우수). DB write 확인. 산출 `comparison/REPORT_3cmp-G_hybrid.md`·`tab/3cmp-G_*`·`fig/3cmp-G_*`.
- **D+7 solar PatchTST 반영(2026-06-08)**: 사용자가 D+7 가중치 추가학습(`solarwind_patchTST_pkl/_D7`) → 하이브리드 `SOLAR_PT_HORIZONS=[2..7]`, solar D+1~7 전부 PatchTST. (D+7 solar 실측 MAE PatchTST 0.0702 vs LGBM 0.0663 — LGBM 근소우위지만 단순화 위해 PatchTST 통일, 사용자 수용. D+8+ LGBM 폴백.)
- **tcog 후처리 완성(3cmp-3, 가볍게)**: 대류일(tcog>0, ~7%) 보정 `corrected=clip(pred+beta*tcog_station,0,1)`. **지점 선택(잔차적합 비교+사용자 직관)**: **solar=tcog_south(beta −0.074, 대류일 MAE −10.1%)·wind=tcog_east(beta +0.062, −10.7%)**. 단일지점이 평균보다 우수(south는 태양광 용량 집중·사용자 직관 일치; **west는 wind 모델 주피처(57%)라 잔차에 잉여 → east가 직교정보**). **5-fold 랜덤스플릿(계절 골고루, 사용자 지시) 검증, 비대류일 무해.** `serve_solarwind_hybrid.py` 토글 `APPLY_TCOG`로 통합(`est_*_jeju_lh`, src 태그 `+tcog`), beta·지점=`lgbm_models/tcog_postproc.json`. cape/cinn/tcoh/gust/hpbl 미사용(3cmp-2: cape 83%·cinn 97% 9999 sentinel·tcoh 상수0).
- **3단계 점검·하이브리드 작업 종료**. 남은 것: 6단계 land_net_load에 채널분리(solar=PatchTST·wind=LGBM) 골격 이식(전국 D+12, land 재학습 필요 여부 EDA 후).

**2026-06-07 — 제주 2단계 2-0c: 낮시간 surge 공략(비대칭손실+흐린날피처) + forecast bias/QM 검증 → 2-A 최종확정**
- 문제정의(사용자): KPX est_demand_da 약점=낮시간 BTM 변동 미반영. 진단(낮 08~16h, 완전기상): KPX는 **맑은날 +43.6MW 과대(BTM 차감 실패)**, 흐린날 −25MW 과소. baseline 모델은 맑음 압도하나 **흐린날 −47MW로 KPX보다 더 과소예측(7.62 vs 6.90)** → 흐린날 surge가 표적.
- 설계(사용자 결정: cap×이용률 BTM추정 금지·비대칭손실·흐린날 특화피처): **흐린날피처 solar_deficit(1−일사/평년)·solar_ramp(h≤48)** + **비대칭 quantile + 낮가중**. cape/tcog는 historical에 없어(forecast 전용) 미채택, 쓸 구름=midlow/total_cloud(west·south raw).
- forecast bias 점검(사용자 지적): historical↔forecast 분포차 존재(습도+7·풍속+1.7·구름+0.1, 기온·일사는 corr 0.94+). **QM(quantile mapping)으로 정렬했으나 흐린날 순효과 음(−)** — 흐린날 열위는 주변bias 아닌 예보 event-skill(구름 corr 0.56) 문제라 QM 미해결. → QM 미적용.
- alpha 재튜닝(서빙=forecast 기준, 사용자 지적): α=0.60 raw가 TEST 낮흐림 6.87·낮맑음 8.94로 **둘 다 KPX 우위·전체 최고정확도**. (α↑+QM은 강건하나 전체 손해) → **채택 α=0.60 raw**.
- **2-A 최종(22피처, quantile0.60+낮가중2)**: 완전기상 D+1 3.82/전체 3.99. 낮(실서빙 forecast) 전체 8.04·흐림 6.87·맑음 8.94 — 모두 KPX 상회. 산출 `eda/2-0c`(개념)·`model/_exp_*·_eval_*` 스크립트·갱신된 2-A.
- 다음: 2-B 서빙(raw forecast, D+1~D+7 UPSERT) — 사용자 요청 시.

**2026-06-07 — 제주 2단계: 배포모델 비교 + KPX 잔차 BTM/PPA 원인분석(2-0b)**
- 배포 PatchTST+LGBM(D+1) vs 신규 직접 다지평(D+1) 동일 구간(2026-03-22~05-31, 실측기상): **배포 4.06% ≈ 신규 4.12%(동률)**, PatchTST단독 6.04·KPX 6.01. → 신규는 PatchTST 없이 동급 D+1 + D+7 확장이 이점. (`model/_compare_deployed.py`, `tab/2-A_deployed_compare.csv`)
- **사용자 제공**: 전력거래소 제주 PPA+BTM 태양광 용량(월별 MW, 2019-2025) → `data/jeju_ppa_btm_capacity_mw.csv`(2026 캐리포워드). 비계량 발전 ≈ 용량×태양광이용률(land `backfill_btm_ppa.py`와 동일 원리).
- 2-0b EDA(`eda/2-0b_residual_btm.ipynb`·REPORT): 사용자 가설 검증. **실제 신재생 침투율(계량+비계량) 2026 ~30%**(계량 26%). KPX 잔차(real−est)는 **낮시간 집중·최근연도 확대**. 낮(9~16h) 잔차↔총운량 **+0.37**, ↔일사 −0.13. **맑은날 vs 흐린날(평일·월내 일사 상하위25%): 흐림이 낮수요 +106MW 높고 심야엔 −31MW** → 비계량 태양광이 맑은날 낮 계통수요를 끌어내림(est 없이 real만으로 입증). 잔차↔BTM/PPA서프라이즈(용량×(이용률−평년)) **−0.34**(R² 0.117, +구름 0.147), **연도별 상관이 용량과 함께 강화: 2020 −0.41→2026 −0.64**. 정직성: 선형은 낮시간 잔차의 ~15%만 설명(부호·방향 전부 가설 일치, 나머지는 비선형·KPX자체오차).
- 모델 시사점(피처변경=Decision Gate, 미확정): 현 2-A는 일사는 있으나 **구름·BTM/PPA 용량 없음** → 후보 ①구름(total/midlow_cloud, 예보존재) ②BTM/PPA용량×평년이용률 ③forecast cape. 서빙시 비계량추정은 예보일사/예보이용률로 대체 필요.
- 피처 A/B 실험 + 채택(사용자 Decision Gate): baseline 대비 +구름@h≤48(D+1 3.93·D+2 4.09, 단 D+3+ 악화), +BTM용량(전체 4.28→4.14·전지평 고르게), +둘다(전체 4.12) 비교. forecast 변수 상관(낮시간): midlow_cloud +0.38·total_cloud +0.34·**cape −0.25(historical 없음→학습불가, 후처리만)**·tcog +0.13·tcoh 사용불가. **채택=구름(west·south raw, h≤48)+BTM용량** → 2-A 최종 20피처 재학습(D+1 3.97·전체 4.14). cape는 forecast 전용이라 미채택.

**2026-06-07 — 제주 2단계 장지평 확장(2-A): 풀드 직접 다지평 LGBM 추가(기존 D+1 그대로)**
- 무엇을: land 5-A 틀을 제주로 이식. 기존 PatchTST+LGBM D+1 파이프라인은 손대지 않고, **LGBM 단독·풀드 직접 다지평 1~168h(D+1~D+7)** 신규 모델 추가. `eda/`(2-0)·`model/`(2-A) 신설.
- 피처 확정(사용자 Decision Gate, 두 차례 질의): 15개 = h+lag168+rec24/rec168+기상4(기온·습도·일사·풍속, 제주3지점평균·일사2지점)+달력(hour/dow/month sin·cos)+day_type. **land 5-A 대비 lag24 제거·h 유지(중요도 낮지만 풀드 구조상 필요)·month 추가·습도 추가**(제주 forecast엔 reh 있어 서빙가능 — land와 차이).
- 2-0 EDA(G-9 통과): lag24 0.894/lag168 0.822, 기온 V자(선형상관 ≈0), rec24 0.69/rec168 0.65, train↔test 겹침 안전. 학습창=기존 제주 2단계와 동일(train ≤2025-02/val ~2026-03-21/test 2026-03-22~05-31).
- 결과 test: **완전기상 D+1 4.13%→D+7 4.36%(전 지평 KPX 6.0% 상회, 거의 평평 — lag168이 전 지평 동일 가용)**. 단 **기후값(무기상정보) 하한 6.8~7.1%로 KPX보다 나쁨** → 제주는 기상예보 품질 의존도가 land보다 큼(정직성: 운영은 두 괄호 사이). D+1 비교: LGBM직접(완전) 4.13% > PatchTST단독 6.06% > KPX 5.94% > naive 8.80%. 중요도 lag168 37%·기온 15%·습도 6%·rec168 6%, h 0.4%.
- 다음: 2-B 서빙 연결(`forecast` UPSERT, D+1~D+7 선택형) — 사용자 요청 시.

**2026-06-07 — 5단계 마무리: 5-B 서빙 + 7일 예보(G-12) + 5-A2 지평별 모델 + 공휴일 실험**
- 5-B 서빙: `serve_land_demand.py`, D+1~D+7 선택형(`--days`) → `forecast.est_demand_land` UPSERT. 기상 예보 우선·없으면 (월,시) 기후값 폴백. 백필 검증 D+1 4.30%·D+7 5.40%(5-A 기후값 괄호 일치).
- 7일 예보 수집(G-12 신설·해결): KIMG 전구 발표별 예보길이 확인 — **00/12 UTC=288h(12일)·06/18 UTC=87h**(hf probe로 검증). 현재 18 UTC라 87h 캡이었음. 결정: **≤72h는 기존 신선 발표, >72h(D+4~)는 12 UTC 단일** `--kimg-days 7`. 서빙 무변경. 백필은 사용자 직접.
- 5-A2 지평별 직접모델(Direct-H, 사용자 요청): D+1·D+2·D+3·D+7·D+12 5개(D+n 하루 블록). lag_week=target−168(D+1~7)/−336(D+12). test 2026 완전기상 3.48~4.59%, 전 지평 KPX 상회. 풀드 5-A가 ~0.05~0.1%p 근소 우위.
- 공휴일 실험(사용자 지적): lag_week가 7일 전 평일을 주입 → 공휴일 MAPE 2배. lag_dt(lag 시점 day_type) A/B → 전체 개선 ≤0.15%p, 문제 부분집합 비일관(D+7 악화)·표본 9일 → **미채택**. 타깃 day_type이 신호 대부분 보유 확인.
- 다음: 6단계 전국 신재생 / 제주 2단계 장지평 확장(후순위) / 5-A2 서빙 연결(선택).

**2026-06-06 — 5단계 전국 수요: 5-0 EDA + 5-A 직접 다지평 LGBM 완료 (D+1 3.6~4.5%, KPX 우위)**
- 무엇을: 전국 수요 예측기(5단계) 착수. 5-0 EDA(G-9 통과): 강한 일/주 주기(lag168 0.84), 기온 V자(58k~79k MW), 5지점 공간평균 타당, **서빙 가능 기상 = 기온·일사·풍속**(예보에 습도·강수·적설 없음 — 제주와 차이), train↔test 겹침 안전. 베이스라인 KPX 하루전 MAPE ~5.5%.
- 5-A(사용자 확정): **LGBM 단독·직접(direct) 다지평 1~168h 단일모델**(재귀 아님 — lag168이 전 지평 직접 가용해 오차 누적 회피. "PatchTST predict_length 다르게"의 LGBM판). 피처 = h+lag168+lag24(h≤24)+rec24/rec168+기상3+달력+day_type. 평가 D+1~D+7(각 24h 전체), 정직성 2겹(완전기상 상한↔기후값 하한).
- 결과 test 2026: **D+1 3.56~4.50% / 전체 3.99~5.01% / D+7 4.22~5.31% — KPX 하루전 5.45%를 전 지평 상회**(naive lag168 7.2%). 중요도 lag168·기온·rec168 주도. → 베이스라인 우위로 PatchTST 불필요.
- 곡절(정직성): 24의 배수 지평(23:00 origin)만 보면 23시 한 시각만 평가돼 낙관편향(1.88%) → D+1~D+7 블록(전 시각)으로 재집계. 기상은 forecast 발행 리드타임 미저장이라 예보오차 직접측정 불가 → 완전기상/기후값 괄호로 표현.
- 다음: 5-B 서빙(`est_demand_land` UPSERT) / 6단계 신재생 / 제주 2단계 장지평 확장(후순위).

**2026-06-06 — 7-A2 이용률 정규화로 2026 과소예측 보정 + 7-C end-to-end 갱신**
- 무엇을: 7-C에서 발견한 7-A의 2026 과소예측(bias −5.7%)을 보정. 원인 = LNG 설비 증설(`kr_elec_capa.csv`: 2022 41,788→2026 48,388MW, train 대비 +9.6%). 같은 수요에서 2026 가스발전만 +13% 점프(이용률로 보면 2022 수준 정렬).
- 처리(7-B 동일 논리): 타깃을 이용률(gen/cap) 정규화→×용량 복원, 피처는 7-A 동일. 결과 **test 2026 bias −5.7%→+4.0%, MAPE 11.4%→10.5%, R² 0.784→0.863**. 정직한 한계: val 2025 bias +8.3%(2025 저이용률 연도 과보정). 산출 `model/7-A2_*`·`REPORT_7-A2.md`·`lgbm_land_gas_util.txt`.
- 7-C 갱신: 송출량 예측에 7-A2 적용 → **end-to-end MAPE 13.6%→7.3%, bias −13%→−3.3%**. 변환계수(0.1521)는 그대로.
- 다음: (선택) 2025 저이용률 원인 분석 / 8단계 Streamlit 데모 / 예측기 5·6.

**2026-06-06 — 7-C KOGAS 환산 완료: 발전량(MWh)→송출량(TON) 단일계수 0.1521**
- 무엇을: 전력거래소 시간별 발전량을 일집계해 KOGAS 일간 송출량(TON)에 회귀. 산출 `model/7-C_kogas_conversion.ipynb`+`REPORT_7-C.md`+`fig/7c_*`·`tab/7c_*`.
- 변환계수(핵심): corr 0.972, **무절편 단일계수 0.1521 ton/MWh**(열효율 ~43% 물리적 타당 → 단위 TON 확인, G-5 부분해결). 변환 MAPE 3.6%, 연·월 안정(겨울 안 부풂=발전용만, 난방혼입 아님).
- 변환식 결정 곡절(사용자): 처음 무절편 lean → "전국 LNG=0 불가라 절편 넣자"(절편식) → 연도별 절편 759~9030 불안정 확인 후 **"그냥 절편 빼자"로 무절편 단일계수 최종 확정**.
- f(기온) 검증(현장 직관 "겨울 효율↑"): corr(변환비,기온) −0.14, f(기온) 추가 +0.05%p·부호 반대 → 전국 fleet 일집계에선 부분부하·급전구성이 압도해 기온신호 소멸. 단일계수 유지·문서화(정직성).
- 최종 산출: test 2026 일별/시간별 예상 송출량(TON). **오차 분해**: 변환만 MAPE 3.7%(견고) / **7-A가 2026 가스발전 −10% 과소예측** / end-to-end 13.6%(7-A 바닥편향 전파, 변환 문제 아님). 단가·수입가는 물량과 독립(corr≈0) → 가스비=곱.
- 다음: (선택) 7-A 2026 과소예측 보정 검토 / 8단계 Streamlit 데모 / 예측기 5·6.

**2026-06-06 — 7-B 제주 probe 완료(EDA G-9 + 마감 모델). 명제 입증 중심으로 전환**
- 무엇을: 제주 `only_gen` 실측으로 net_load → LNG 검증. EDA(G-9 제주): net_load↔LNG r=0.723, 0비중 1.3%, 대체효과 수요통제 신재생계수 −0.369(전국 ≈0 대비). 산출 `eda/7-B_jeju_probe_eda.ipynb`+`REPORT_7-B_eda.md`.
- **막힘→전환**: 첫 모델이 베이스라인보다 나빴음(test R²0.25). 진단 결과 2024-01 절대 LNG 점프 = **유류→LNG 설비전환**(사용자 제공 `jeju_gen_capacity.csv`: LNG_cap 333.7→492.5, 유류 186→40MW). 제주 LNG는 작은 계통이라 절대 점예측 본질적 한계. → §1.2대로 정확도가 아닌 **명제(관계·방향) 입증**으로 목표 재정렬.
- 처리(사용자 확정): 타깃 이용률(lng/cap) 정규화→×용량 복원, **주 학습창 2024-01+ 안정창**. 피처 수요+신재생합계+달력(7-A 동일 basis). 결과 net_load↔LNG r=0.777 단조증가, test R²0.50·MAE37.7(베이스 −0.24), **신재생 PDP −0.314**(전국 −0.017). net_load별 LNG 추정 곡선 산출.
- 학습창 비교(사용자 요청): 2022-08+ 확장(n 3배)은 동일 test에서 R²0.50→0.36 하락 — 2022-23 유류많은 fleet 구성표류 오염. **2024+가 맞는 창** 확인(대체효과는 두 창 −0.31~−0.34 일치). 산출 `model/7-B_jeju_gas_lgbm.ipynb`+`REPORT_7-B.md`+`lgbm_jeju_gas.txt`.
- 부수 결정: PPA(`jeju_ppa_cumulative_gen.csv`)는 7-B 미사용(2024-06 시범사업으로 PPA가 Grid 계량에 흡수 → 제주는 계량 신재생만으로 충분. 육지는 미흡수라 PPA 산정 필수). 누적발전량→용량 역산은 출력제어로 비물리적이라 부적합.
- 다음: **7-C KOGAS 환산**(`daliy_lng_gen_21-26.csv` → 단가·수입가로 수요·비용) + 제주·전국 명제 대비표.

**2026-06-06 — G-11 해결: 7-Ar 실측전용 대체효과 모델 추가(둘 다 유지)**
- 무엇을: BTM/PPA 실측만(2024-11+)으로 true_demand+true_renew LGBM 학습. 사용자 질문("실측전용 가능? 데이터 작지?")에 데이터로 답: train ~8천행 충분, **test 2026 R² 0.798·MAPE 12.0%로 오히려 최고**(train·test 동일 최신 레짐). 신재생 중요도 15.4%, 순수 실측. 산출 `model/7-Ar_*`·`lgbm_land_gas_recent.txt`.
- 최종 모델 lineup: 7-A(현행, 긴 이력 순수실측)=메인 예측 / 7-Ar(실측전용)=대체효과 설명 / 7-0b=전 기간 대체효과 EDA(역추정). 복원 단일화판(R²0.766)은 미채택.
- 다음: 7-B 제주 probe.

**2026-06-06 — 7-0b: BTM/PPA 역추정으로 전 기간 대체효과 입증(신재생계수 −0.33, 역추정≈실측)**
- 무엇을: 자가소비(BTM)·PPA가 계량수요에 숨어 7-0(5-b)에서 대체효과가 안 보였던 것 규명. G-11에서 (c) 역추정 채택(사용자 `ppa_scale.csv` 제공).
- 역추정(`second_dataset/backfill_btm_ppa.py` → `land_renew_reconstructed.parquet`): PPA=k·ppa_scale·태양광이용률(k=0.7108, 검증오차 ±5%), BTM=0.3153·PPA. 2020-01~2024-10 estimated 라벨, 2024-11+ measured.
- 검증(가스 실측 2022+): 수요 통제 신재생계수 계통분 +0.105 → **복원 −0.332**. estimated −0.319 ≈ measured −0.363 → **역추정 타당**. 한낮·저수요에서 특히 명확(제주형 패턴 전국 상존). 산출 `eda/7-0b_*`(notebook·REPORT·그림3·표2).
- 남은 결정(G-11): 7-A를 (true_demand,true_renew) 복원 피처로 재학습 vs 현행 유지+발표 EDA. 다음: 결정 → 7-B 제주 probe.

**2026-06-06 — 7-A 전국 가스 모델 최종(설계 A 분해형): test 2026 R² 0.78 / MAPE 11.4%**
- 무엇을: gen_gas_kr 동시점 회귀. 피처를 여러 설계로 비교 후 사용자 확정(§0.6). 산출 `7. land_gas_forecaster/model/`(notebook·`lgbm_land_gas.txt`·`metrics.csv`·`REPORT_7-A.md`·그림+PDP).
- 신재생 대체효과 EDA(5-b) 추가: 명제(신재생↑→가스↓)를 수요 통제하에 직접 확인 → **전국은 약함**(원상관 +0.01, 회귀 신재생계수 ≈0, 침투율 2.5%·자가소비 태양광 숨음). 저수요 시간대만 음(−). → 대체효과 입증은 제주(7-B).
- 피처 설계 비교(test R²): A 수요+신재생 0.784 / C net_load+수요 0.783 / D 셋다 0.754 / B net_load+신재생 0.610. 트리는 수요(절대규모)를 직접 줘야 강함. **A 채택**(예측 최고 + 신재생 명시로 대체효과 관찰 + 제주와 동일 basis).
- 최종 피처: real_demand_land + renew_gen_total_kr + day_type + 달력(hour/dow/month/doy). 결과: 베이스라인(수요 단독) R² 0.63, **LGBM R² 0.78·MAPE 11.4%·MAE 2,236**. 중요도 수요 60%·doy 15%·hour 13%·신재생 3.6%. 신재생 PDP 기울기 −0.017(부호는 대체, 크기 미미).
- 다음: 7-B 제주 probe(same basis, only_gen 2020-24 + net_load별 LNG 추정, 대체효과 제주 확인), 7-C KOGAS 환산(일별 `daliy_lng_gen_21-26.csv`).

**2026-06-06 — G-10 해결: 학습창 train 2022-24 / val 2025 / test 2026, 2020-21 로드시 필터**
- 무엇을: EDA 발견에 따라 전국 학습창 재정의. parquet `split` 컬럼(train 2020-23) 대신 7-A 로드 시 연도로 분할. 2020-2021(결측-0)은 로드 시 필터, parquet·빌더는 그대로(재빌드 안 함).
- 다음: 피처 최종 입력 사용자 확정(§0.6) → 7-A 학습.

**2026-06-06 — 7-0 EDA 완료(관계 강함, r=0.83) + 데이터 결손 발견(G-10 신설)**
- 무엇을: 7단계 첫 작업으로 전국 net_load → gen_gas_kr EDA notebook 작성·실행(`7. land_gas_forecaster/eda/7-0_eda_land.ipynb`, 그림 6·표 3·`REPORT_7-0_eda.md`).
- 결과(2022+ 실측): 상관 **r=0.83**(강함), 부하수준별 비선형, 타깃 0 비중 0%(항상 켜짐), 연도 안정(60-65k 가스 ~17,500MW 일정), train↔test net_load 겹침 안전(외삽 0.7%). → 명제(검증목표 2)는 데이터에 실제로 있음.
- **★ 발견(G-10)**: `gen_gas_kr` 실측은 **2022-01부터**. 2020(100% 0)·2021(97% 0)은 결측을 0으로 채운 값이고 `model_usable`이 잘못 True. **공식 분할 train=2020–2023은 절반이 가짜** → 학습창 2022+ 재정의 필요. EDA 먼저 안 했으면 가짜 데이터로 학습할 뻔(EDA-first 규율의 실증).
- 다음: G-10 확정(학습창/분할 + 라벨 수정 방식) → 피처 최종 입력 질의 → 7-A.

**2026-06-06 — 모델링 작업 규율 4건 추가 + G-9(관계 EDA 게이트) 신설**
- 무엇을: §0.6에 모든 모델링 공통 규율 추가 — ①시계열 분석 필수 ②피처 최종 입력은 반드시 사용자 확정(탐색은 자유) ③단계마다 보고서 산출물 필수 ④notebook 형식 선호.
- §5.0.5(관계 탐색·시계열 분석) 단계 신설, G-9 게이트 추가(명제가 데이터에 실제로 있는가 = 관계·시간적 안정성·train↔test 분포 겹침). G-6(구조)과 구분.
- 7단계 순서 재정의: 7-0 EDA(G-9) → 피처 확정 질의 → 7-A 전국 모델 → 7-B 제주 probe(+ net_load별 LNG 발전량 추정) → 7-C KOGAS 환산.
- 배경: 직전에 EDA 없이 7-A 모델로 직행하려다 잡음. 명제 자체가 관계 주장이라 EDA가 1차 증명. 다음: 7-0 EDA 착수.

**2026-06-06 — G-7 해결: 전국 7단계를 먼저 착수하기로 결정**
- 무엇을: 전국 트랙 진입 순서(G-7)를 확정. 예측기 5·6을 만들기 전에 7단계(net_load → `gen_gas_kr`)를 먼저 한다.
- 근거: 명제 입증이 목적이라 전국 historical `net_load_kr` 실측만으로 검증 가능(예측기 불필요). `land_train/val/test.parquet` 이미 생성돼 있어 즉시 착수 가능. G-8(원천 CSV 경로)은 데이터셋 재빌드 시에만 필요해 현재 비차단.
- 다음: 7단계 모델링 착수 — `land_*.parquet`로 `gen_gas_kr` 회귀(누수 차단: 딕셔너리 `forbidden` 제외), 제주 probe(`only_gen` 2020–2024)까지.

**2026-06-06 — 프로젝트 재구조화 + 통합 마스터 문서 작성**
- 목표가 제주 SMP(v1)에서 가스수요·전국 검증(v2)으로 피벗됨에 따라 폴더를 정리.
- 평면 넘버링 유지(중첩 금지 — DB 경로가 상대경로라 깊이가 바뀌면 깨짐). 제주 모델 폴더에 `jeju_` 접두사(2·3·4), 전국 골격 신설(5·6·7), `5.streamlit→8`, `6.report only→98`, `99.others` 유지.
- `7. second_dataset`(가스 데이터셋 빌더)를 `1. data_fetcher_and_db/second_dataset/`로 편입하고 `build_dataset.py`·`fit_merit_split.py`의 DB/OUT 경로 보정(이동으로 깊이 +1, 기존 stale 상수 정리). DB 경로 해석 검증 완료, 제주 파이프라인 4종 경로 정상 확인.
- 구 `PROJECT.md`(v1)·`project2.land.md`(v2)는 `docs/`로 이력 보존(헤더에 대체됨 표기). 이 통합본이 새 SSOT.
- 다음: 전국 트랙(G-7 결정 → 7단계 가스 예측기) 또는 8단계 데모.

**2026-06-03 — A0 데이터 확보·분리 + A1 가스 타깃 완료 (G-1~G-6 해결)**
- `second_dataset`에 빌더(`build_dataset.py`, `make_dictionary.py`, `fit_merit_split.py`) 작성·실행. 제주·전국 시간별 마스터셋 결합 → 감사 → LNG 타깃 도출+backfill → 라벨링 → 시간순 분할.
- 결과: 제주·전국 각 56,256행, 중복 0·시간구멍 0, 학습/검증/테스트 NaN 0. 분해는 급전순위 부하수준별(merit-order, 단일 비율 대비 MAE −13.7%). 산출 `data/*.parquet`·`data_dictionary.csv`·`audit.json`·`AUDIT_REPORT.md`.
- 다음: 가스 예측기 착수(제주 `only_gen` 실측, 전국 `gen_gas_kr` 정직 검증).

**2026-06-03 — 방향 전환(PRD 확정): SMP → 발전용 가스수요**
- 검증 목표 1·2 정의(제주 입증 → 전국 확증). 방법론(도출=타깃 / 학습=예측 2단, 검증 3계층) 확정. 전국 트랙을 보너스에서 핵심 증거로 격상.

**2026-06-05 — 4단계 제주 SMP 완료**
- D+1: 가격선 = DA 그대로 + 이진 음수경보 오버레이. 음수경보 ROC-AUC 0.973, 치명 recall 0.934. D+2: DA 예측 + 잔차회귀, TEST MAE 11.79. 통합 서빙 `smp_serve.py`.
- 하드 제약: 제주 SMP는 제주 데이터만. SMP 점예측·실시간 직접 회귀 등은 실패로 확인된 경로(재시도 금지). 상세 `4. jeju_smp_forecaster/trial_error.md`.

**2026-06-01 — 3단계 신재생 → net_load 완료**
- 3지점 입력 PatchTST 재학습. 이용률 solar +6.9%·wind +3.7%, net_load DA 대비 +7.0%. 서빙 `solarwind_db_pipeline.py`, `est_net_load_jeju` 백필.

**2026-06-01 — 2단계 수요 예측 재구축 완료**
- 입력을 CSV에서 `input_data_jeju.db` 직접 로드로 전환. 제주 3지점 공간평균으로 LGBM 재학습 → Test MAPE 4.29% → 3.98%. 서빙 `demand_db_pipeline.py`.

---

## 9. 제출 패키지 체크리스트 (D-3 기준)
- [ ] 참가 신청서(서명 스캔)
- [ ] 참가자 서약서(서명 스캔)
- [ ] 개인정보 수집·이용 동의서(서명 스캔)
- [ ] 공모전 기획서 PDF(데이터 명세 = §2 귀속, 본문 = §1 명제·§5 방법론)
- [ ] 시연 영상 또는 스크린샷(§6 데모 동작 시점부터 누적)
- [ ] 서비스 링크 최종 동작 확인

---

## 부록 A. 새 대화 시작 가이드

### A.1 첨부할 것
1. 이 `PROJECT.md`(필수).
2. (선택) 직전 대화의 핵심 결정 1~2줄.
3. (선택) 작업 대상 코드 파일(Claude Code 사용 시).

### A.2 자주 쓰는 지시
- 전체 맥락 환기: "PROJECT.md가 프로젝트 전반 정의야. 이걸 기준으로 답해줘."
- 특정 단계 작업: "지금 §4의 7단계(가스 예측기)를 구현 중이야. §5 방법론을 따라줘."
- 진행 점검: "§7 Decision Gate 기준으로 지금 상태 점검해줘."
- 의사결정: "§0.6의 과거 막힘 패턴을 피하려면 지금 결정해야 할 게 뭐야?"

### A.3 문서 갱신 규칙
- §1·§2·§5는 가급적 안 바꾼다(정의가 흔들리면 답이 매번 달라진다).
- §4 단계 상태·§7 게이트·§8 로그는 작업 완료 시마다 갱신.
- §0.6 작업 규율은 새로운 막힘 패턴이 발견될 때만 추가.

### A.4 대화 종료 전 자가 체크
- 고정 구역(§1·2·5)을 건드릴 결정이 있었나?
- 새로 생기거나 해결된 게이트(G-n)가 있나?
- §8 로그에 남길 작업·결정이 있나?

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
- 로그가 약 2주를 넘으면 오래된 항목은 `docs/PROJECT_LOG.md`로 그대로 이관한다(내용 무수정, §8엔 최근분만 유지).

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
신재생(태양광·풍력) 변동이 만든 **잔여부하(net_load)**를 가스 발전이 메운다 — 그 관계를 **제주에서 입증**하고 **전국 실측(`gen_gas_kr`)으로 확증**한다. 그리고 결과를 산자부, 가스공사 등 가스 판매, 도입업자에게 유용한 브리핑으로 제공하는 Streamlit 데모를 만든다.

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
- 데이터 인벤토리·가용 윈도우의 초기 정의 = `docs/PROJECT_v2_PRD.md` §4 참조(동결 이력, 이후 변동은 §4 단계 상태·§8 로그가 우선).

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

### 전국 트랙 (완료·운영 중)

> 전국은 제주 2·3·4를 미러링하되, **SMP 단계는 없다**(시장 구조상 비대상). 끝은 net_load → 가스 발전 검증이다.

> **★ 현재 운영 구조 (2026-06-19 기준 — 5·6·7 정본)**
> - **DB(input_data_land.db) = 3테이블**: `historical`(실측·KPX DA·ASOS) · `forecast_horizon`(기상예보 아카이브, 서빙 입력) · `est_horizon_land`(예측 출력 아카이브, streamlit·API 소스). 옛 `forecast` 테이블은 폐기.
> - **서빙 = 단일 통합 체인 `7. land_gas_forecaster/serve_chain_land_new.py`** (5→6→7 한 번에 → est_horizon_land). 단계별 단독 실행 스크립트는 폐기, 5·6·7 폴더는 production 핵심만 두고 나머지 각 폴더 `nouse/`로 격리.
> - **모델**: 수요=**PatchTST v4(anchor-residual + recent-climatology), 지평별 하이브리드**(G-24: D1-6=head 파인튜닝 무보정·D7-15=기존+post-hoc 보정. 옛 lgbm-하이브리드는 G-23 폐기) / 신재생 solar=PatchTST(landsolar504 전지평)·wind=LGBM / 가스=LGBM 자기회귀 v2 + 보정·기후값 블렌딩.
> - 단계별 상세·이력은 아래 각 단계 + §7 게이트 + §8 로그. 운영 정본 요약은 메모리 land-stages-done.

**5단계 — 전국 수요 예측 (`5. land_demand_forecaster`) ✅ (… + ★★G-24 지평별 파인튜닝 하이브리드 production 정본)**
- **(2026-06-21, G-24) ★★production 정본 = 지평별 하이브리드.** BTM 태양광 폭증(2025~)으로 한낮 계량수요 과대(맑을수록 심함, solar 조건부)→보정표가 구조적으로 못 잡음. **D1-6 = head 파인튜닝본(인코더 동결, 신체제 2024-11~2025-11 격자 split 학습) + 보정 제거(무보정)** / **D7-15 = 기존 v4 + 보정 유지**(ft 장지평 과적합이라 대체 불가). 봉인 test(forecast_horizon 186 base): 전체 MAPE 3.95(G-23 3.89 동급)·단기 낮 solar spread 7.8→4.6. 배포=`weights/`(원본 백업 `weights_v4_orig/`), calib 360→216셀. 서빙 경로 무변경(`serve_chain_land_new.py:LT_DIR`). `calibrate_lt.py`는 D7-15만 굽도록 수정 완료(SKIP_GROUPS)라 재실행 안전. 코드 `training/demand_lt/{finetune_lt.py, finetune_land_lt_colab.ipynb, eda_scaler/}`·`weights/FINETUNE_NOTE.md`·`ARCHITECTURE_lt_v4.md §9`. 상세 §7 G-24·§8(06-21)·메모리 [[land-demand-midday-btm-finetune]].
- **(2026-06-20, G-23) ★정본구조 = 단일 PatchTST v4 + post-hoc 보정. lgbm-하이브리드(G-21) 폐기 — 더 이상 사용·재시도 금지.** (※G-24 에서 v4 의 가중치·보정이 지평별로 차등됨 — D1-6 만 파인튜닝.) 단일구조 anchor-residual PatchTST 15벌 = **anchor(daytype_match: 주말·공휴일 매칭 same-DOW 최근2주) + recent-climatology(같은요일·요일타입 최근13주, static은 BTM/PPA 태양광성장으로 한낮 stale) + 기상 temp/humidity/solar + RobustScaler + 미래공휴일 holidays.SouthKorea**. **post-hoc 보정**(계절×시각×지평5구간 곱셈, `calib_lt.json`)은 모델과 분리된 후처리층 — 언제든 따로 갱신(재학습 불필요). honest 186-base(전계절): 보정후 전체 4.44→**3.92**·낮 7.72→6.55·밤 3.10→2.83·겨울 3.86·여름 3.46, **전 구간·지평별 bias(±0.4%)까지 하이브리드 추월**. 기각=cap_ppa(밤 과억제·용량외삽)·지평15보정(과적합). **배선 완료**: `serve_chain_land_new.py`가 `model_lt.predict_horizon` 호출(수요가 가스 입력피처라 가스도 v4기반). 코드=`5.../training/demand_lt/`(가중치 `weights/`). 테이블: `est_horizon_land`(production=보정 v4+신재생+가스)·`est_horizon_land_raw`(미보정 벤치)·`old_method_est_demand`(폐기 하이브리드 동결). 상세 §8(06-20)·`training/demand_lt/REPORT_lt_v2.md`·메모리 [[land-demand-patchtst-hybrid]]. (서버 배포 사용자 수동.)
- **(2026-06-19, G-21, ⛔폐기 — G-23으로 대체) PatchTST 하이브리드 서빙**: D+1~2 patch(final336)/D+3~7 주간patch·야간lgbm/D+8~15 lgbm(v2hum). honest 4.395. ★이 하이브리드는 G-23에서 단일 v4로 대체됨. `serve_demand_patch.py`·`landdemand_final336/`·LGBM v2hum 는 더 이상 서빙에 안 쓰임(아카이브/정리 대상). 이력만 보존. 상세 `training/REPORT_5-B.md §9~12`.
- **(2026-06-14, G-17) v2 재정교화**: 지점선택+구름(서산영광)+cap_btmppa+낮 비대칭 손실(α=8). 봄 낮 9.43→7.91%·backfill D+1 4.30→3.56%. 서빙=`lgbm_land_demand_v2.txt`(현 하이브리드 LGBM은 v2hum). 상세 §7 G-17·§8(06-14)·`model/REPORT_5-A_v2.md`.
- **5-0 EDA ✅**(G-9 통과): 전국 수요 시계열 = 강한 일/주 주기(lag24 0.78·lag168 0.84), 기온 V자(난방 71k / 최저 58k / 냉방 79k MW, 선형상관은 ≈0이라 트리로 잡음), 5지점 기온상관 0.95~0.98(공간평균 타당), train↔test 분포 겹침 안전. **★ 서빙 가능 기상 = `temp_c·solar_rad·wind_spd`**(forecast 테이블에 습도·강수·적설 없음 — 제주와 차이). 산출 `eda/5-0_eda_land.ipynb`·`REPORT_5-0_eda.md`·`fig/`·`tab/`.
- **5-A 모델 ✅**(사용자 확정 §0.6): **LGBM 단독·직접(direct) 다지평 1~168h 단일모델**(재귀 rolling 아님 — 주간 lag168이 전 지평 직접 가용해 오차 누적 회피). 피처 = h, lag168, lag24(h≤24만, 그 외 NaN), rec24/rec168(원점 최근레벨), 기상3(5지점평균), 달력(hour/dow/month sin·cos), day_type. 학습창 train≤2024/val2025/test2026. 평가는 **D+1~D+7(각 24h 전체)** + 정직성 2겹(완전기상 상한↔기후값 하한). **결과 test 2026: D+1 3.56~4.50% / 전체 3.99~5.01% / D+7 4.22~5.31% — KPX 하루전(5.45%)을 전 지평에서 상회**(naive lag168 7.2%). 중요도 lag168·기온·rec168 주도. → 베이스라인 우위로 **PatchTST 불필요**(사용자 결정 규칙 충족). 산출 `model/5-A_land_demand_direct.ipynb`·`lgbm_land_demand_direct.txt`·`model_meta.json`·`REPORT_5-A.md`·`fig/`·`tab/`.
- 보너스: 직접 다지평이라 **일주일(D+7) 앞을 KPX 하루전 수준으로** 예측. 같은 틀을 제주 2단계 장지평 확장에 이식 가능(사용자 요청, 후순위).
- **5-A2 지평별 직접모델(Direct-H) ✅**(사용자 확정): 5-A가 한 모델로 전 지평을 학습한 "풀드"라면, 5-A2는 **날짜마다 모델을 따로**(D+1·D+2·D+3·D+7·D+12 5개). 출력=D+n 하루(24h) 블록. 피처 동일 템플릿(lag_week + rec24/rec168 + 기상3 + 달력 + day_type), **주간앵커 lag_week = target−168(D+1~7) / target−336(D+12)**(D+12는 lag168이 미래라 불가). **test 2026 완전기상: D+1 3.48·D+2 3.76·D+3 3.94·D+7 4.26·D+12 4.59%**(기후값 하한 +0.9%p 내외), 전 지평 KPX(5.3~5.5%) 상회. 풀드 5-A가 ~0.05~0.1%p 근소 우위(데이터 공유). **공휴일 보정 실험**(사용자 지적: lag_week가 7일전 평일을 주입): lag의 day_type(`lag_dt`) A/B → 전체 개선 ≤0.15%p로 작고 공휴일/불일치 부분집합에서 비일관(공휴일 9일뿐 노이즈, 타깃 day_type이 신호 대부분 보유) → **미채택, base 유지**(파시모니). 산출 `model/5-A2_direct_per_horizon.ipynb`·`lgbm_land_demand_D{1,2,3,7,12}.txt`·`model_meta_perhorizon.json`·`REPORT_5-A2.md`·`fig/`·`tab/`.
- **5-B 서빙 ✅** (현재는 통합 체인이 대체): 운영 서빙은 `7.../serve_chain_land_new.py`(5→6→7 한 번에 → `est_horizon_land`). 옛 단독 실행 스크립트 `serve_land_demand.py`는 체인과 중복이라 `99. others`로 아카이브(2026-06-19). 아래는 그 옛 스크립트 이력: origin(지정일 23:00) 다음 **D+1~D+15 선택형**(`--days 1..15`, G-19 확장) 예측 → `forecast.est_demand_land` UPSERT. 피처 조립은 5-A와 동일(검증: 과거 백필 D+1 4.30%·D+7 5.40% = 5-A 기후값 괄호와 일치). 기상은 **forecast 예보 우선·없으면 (월,시) 기후값 폴백**(`weather_src` 표기). CLI `predict [date] --days N` / `backfill start end`(MAPE 평가).
- **7일 예보 수집(G-12)**: KIMG 전구는 **00/12 UTC=288h(12일)·06/18 UTC=87h**. 현재 생산이 18 UTC라 ~3.6일에 막혔던 것(소스 한계 아님). 결정: **≤72h(D+1~D+3)는 기존 신선 발표, >72h(D+4~D+7)는 12 UTC 단일**(`--kimg-days 7`). 서빙은 무변경(forecast 쌓이면 자동 실예보 사용). 백필(과거 장기 lead 가용 확인)은 사용자가 직접 수행.

**6단계 — 전국 신재생 → net_load (`6. land_solarwind_forecaster`) ✅ 완료**
- 상태: 완료. 채널 분리 — **태양광=PatchTST direct 전 지평(D+1~D+15)+LGBM 폴백(입력결측 시만) / 풍력=LGBM 전지평**. **(2026-06-19) 가중치 구조 `landsolar_patchtst`(seq336·D{1-7,12,14,15} 10개) → `landsolar504`(seq504·d_model256·D1~D15 전 15개)로 교체** — 빈 지평(8-11,13) LGBM 폴백이 사라지고 전 지평 PatchTST. 서빙 `serve_solarwind_land.py`의 `PT_DIR`·`SOLAR_PT_HORIZONS=1..15`만 교체(피처 동일, 아키텍처는 메타 HP로 자동). 검증: 15개 가중치 strict 로드·체인서 D+8~13 solar=patchtst 확인. 산출 2종: `est_market_renew_land`(시장, →7-A)·`est_true_renew_land`+`est_true_demand_land`(BTM/PPA 포함, →7-Ar 대체효과). 검증 SOLAR util MAE(낮) 0.087·WIND 0.139.
- DoD: 전국 태양광·풍력 예측 → `net_load`. 전국 DB에 `net_load_kr`·`gen_solar_*`·`gen_wind_kr` 실측으로 검증. 상세 §8(2026-06-08)·6-0~6-C 보고서.
- 구조(G-13, 2026-06-08 확정): **LGBM-direct 다지평 단일**(5-A·3단계 결론 일관) 주력 + PatchTST는 **D+1/D+2/D+3에서만 비교(6-B)** → 큰 차이 없으면 LGBM 단일. 지평 **D+1~D+12**. 타깃 **이용률 정규화**(solar_cap 2.7k→9.4k MW 3.4배 표류 → DB `gen_solar/wind_utilization_kr`)→×용량 복원 → net_load.
- 지점(사용자 확정): **solar=영광+서산+포항**(전남·충남·경북, 용량 61%, solar_rad↔이용률 0.69~0.75), **wind=대관령+영광+포항**(강원·경북·전남, 용량 ~90%, 대관령 풍속↔이용률 0.607 압도). 합집합 4지점 forecast만 로드. **후처리 불가**(land forecast에 강수·cape·tcog 없음 → 제주 solar_damping·tcog 미적용).
- 작업 순서: 6-0 EDA(G-9, 지점별 이용률 관계·용량표류·분포겹침) → 최종 피처 §0.6 질의 → 6-A LGBM-direct → 6-B PatchTST 비교(D+1~3) → 6-C 서빙(`est_net_load_land`).

**7단계 — net_load → 발전용 가스수요 (`7. land_gas_forecaster`) ✅ (7-0~7-C·7-A2-A·실예보 재검증/지평별 보정 G-16 완료) ★ 새 명제의 핵심**
- **(2026-06-14, G-16) 실예보 지평 재검증·보정**: forecast_horizon으로 정직 재측정 → "지평 평평"은 기후값 프록시 허상, 가스 MAPE D+1 13.0%→D+12 17.0% 정직 상승(ORACLE ~10.3% 평평). 지평별 bias 보정 재적합. 상세 §7 G-16·§8(06-14)·`training/REPORT_horizon_diagnosis.md`.
- **(2026-06-14, G-18) v2 재정교화**: 5-A식 가스 자기회귀 다지평 + MIXED(신재생만 util) + 낮 비대칭(α4) + 낮/밤 분리보정. 봄 낮 24.46→19.77%·D+1 13.02→12.22%. 서빙=`lgbm_land_gas_v2.txt`. 상세 §7 G-18·§8(06-14)·`model/REPORT_7_v2.md`. 구 7-A2(util)·드라이버only 7-A 보존.
- **(2026-06-15, G-19) 풀체인 D+15 확장 + 기후값 블렌딩**: 수요·가스 v2를 D+15(h360)로 정직 재학습(수요 lag168이 D+8+ 미래누설 → **lag168/336/504 가용성 NaN가드**로 수정), 솔라 PatchTST D14/15 활성화(전 지평 연속, 빈 지평 LGBM 폴백). 풀체인 정직 백테스트(182 base×D+1~15)→ **`est_horizon_land`**(forecast_horizon 양식, 64,939행) 적재. ★**기후값 폴백 금지 하드규칙 해제**(사용자: "기후값=우리 평년 모델")→**장지평 블렌딩 도입**: final=(1-w(h))·예보보정+w·가스기후값(우리 historical doy±7×시각×요일유형), w 0(D+1~4)→0.5(D+15). 정직 가스 전체 13.96→13.72%(여름 장지평 −3%p, 겨울·봄 무해). 상세 §7 G-19·§8(06-15)·`training/{build_chain_horizon,analyze_blending}.py`.
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
- **8-0 ✅**: 컨셉 문서(`CONCEPT_8-0.md`) + G-15 확정 — 배포=자체 서버(로컬 DB 실시간 읽기) / brief_ai=Gemini API / 갱신=사전 적재 기본+시연용 실행 버튼 / 표시 기간=데이터 보유 범위 / SMP=제주 페이지 메뉴로 포함(⑤ 번복).
- **8-A 🔶(전국 — 기능 완료, 디자인 개편 남음)**: 확정 디자인 v2(`CONCEPT_8-0.md` §3.4) — 멀티 페이지(전국/제주) + 메뉴(종합/수요 예측/데이터 현황/SMP[제주만]). `app.py`·`common.py`·`page_land.py`·`page_jeju.py`. 전국 전 메뉴 동작(KPX sukub 실시간·기상개황 8권역 지도·데이터 현황 히트맵 포함), 제주는 골격+데이터 현황만. **마감 조건 = 디자인 품질 개편(frontend-design 플러그인, 다음 세션)**.
- 작업 쪼개기: 8-A 디자인 개편 → 8-B 제주(종합·수요·SMP, 선행=제주 서빙 백필) → 8-C 검증·KOGAS 탭 → 8-D brief_ai → 8-E 배포·시연 영상.

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
- [x] **G-24. 전국 수요(5) 한낮 과대 = BTM 드리프트 → 지평별 파인튜닝 하이브리드 production** (2026-06-21) — G-23(단일 v4+보정)의 한낮 과대를 근본 진단·구조 개선. **진단**: 계량수요는 BTM 차감 그리드값인데 BTM+PPA 태양광이 2025년 폭증(한낮 0→16GW, 2026-03 용량 21GW)→**regime flip**(4·5월 한낮−새벽 부호 +→−, 덕커브). residual head 가 <2025(BTM≈0) 학습이라 한낮 봉우리 stale. **오차가 solar_rad 조건부**(보정전 낮 bias 흐림 −2%→맑음 +8%, r=+0.42). ★**보정표는 (계절·시각·지평) 키라 solar 조건부 spread 를 못 줄임**(range 10.3≈raw, 흐림 −5.3% 악화) — 구조적으로 head 재학습이 답. **레벨(anchor/clim)은 21GW 잘 추적**(stale 한 건 head 뿐). scaler(Robust→MinMax)는 별개 축(이상치 없어 안전하나 한낮 과대 무관, Demand 타깃은 스케일 안 됨). **해법=head-only 파인튜닝**(`finetune_lt.py`, 인코더·cross-attn 동결·regressor+weather_bypass만, 2024-11~2025-11 신체제, Colab GPU). **split**: train/val=historical(실측 기상)·**격자 split p=1/6**(요일유형·계절 층화, `make_split.py`→`finetune_split.csv`), **test=forecast_horizon(예보 기상 186 base, 2025-12-15~2026-06-18)** 봉인(train 은 2025-11-30 에서 끊어 무겹침). **봉인 test 결정**(eval_finetune.py): ft 효과가 **D1-6 에 집중**(낮 solar range 초단 7.3→3.3·단 8.9→5.9, D7+ 미미+MAPE 악화=장지평 과적합). → **지평별 선택 하이브리드 채택**(사용자: 보정이 5구간 차등하듯 파인튜닝도 단기만): **D1-6=ft 무보정 / D7-15=기존 v4+보정 유지**(D7-15 보정 빼면 낮 +4.4% 복귀=ft 대체 불가). 전체 MAPE 3.95(G-23 production 3.89 동급)·단기 낮 spread 7.8→4.6(41%↓). 0.6 잔여 bias 는 무시(잡으려다 과적합). **배포 완료**(가중치 git 미추적이라 이름변경 무손실): `weights/`(원본)→`weights_v4_orig/`(롤백 백업)·`weights_hybrid/`→`weights/`(경로 그대로라 서빙코드 무수정, serve_chain_land_new.py:LT_DIR·serve_land_new.py 둘 다 여기 읽음). calib_lt.json 360→216셀(초단·단 144 제거). D1-6=ft·D7-15=원본 md5 확인, 체인 --no-write 전구간 정상. ★**calibrate_lt.py 를 D7-15(중·중장·장)만 굽도록 수정**(`SKIP_GROUPS={'초단','단'}`, 초단·단 스킵 주석 보존) → **재실행해도 D1-6 무보정 유지(footgun 제거)**. 문서: `weights/FINETUNE_NOTE.md`·`ARCHITECTURE_lt_v4.md §9`·체인 주석. 산출 `training/demand_lt/{finetune_lt.py,finetune_land_lt_colab.ipynb,eda_scaler/}`(REPORT_demand_solar.md·REPORT_stl_scaler.md·eval/그림). 메모리 [[land-demand-midday-btm-finetune]]. **남음(선택)**: cron 자동 신weights 사용(과거 일치 원하면 --backfill)·deploy/ 서버 동기화·장지평 calib 제거용 약한 재파인튜닝.
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

- [x] **G-15. 8단계 데모 배포·구성** (2026-06-10) — ① **배포 = 자체 서버 호스팅**(로컬 DB 실시간 읽기, Community Cloud 스냅샷 방식 미채택) ② **brief_ai = Gemini API**(기존 §6.2 유지) ③ **갱신 = 사전 적재 기본**(서빙 5→6→7 순서 cron) **+ 시연용 실행 버튼 병행** ④ **표시 기간 = 데이터 보유 범위**(전국 est 백필 2026-02~, 제주 2025-12~) ⑤ **SMP = 데모에서 일단 제외** → **번복(2026-06-10 설계 개편)**: 제주 페이지에 "SMP 예측" 메뉴 포함(사용자 확정, 8-B에서 구현).

- [x] **G-16. 전국 지평 아카이브(forecast_horizon) 기반 재검증·보정** (2026-06-14) — 새 `forecast_horizon`(육지 181 base·실예보 D+1~12, 2025-12~2026-06)으로 5→6→7 체인을 정직하게 재측정. **하드 규칙: 기후값 폴백 금지**(예보 진짜 없는 시각은 제외, ≤4h 보간만 허용 — 사용자 지시). 발견: ① 기존 "지평 평평(D+1≈D+12 ~13%)"은 **기후값 프록시(`chained_gas_dataset.parquet`)의 허상**. 실예보로 보면 가스 MAPE **D+1 13.0%→D+7 14.9%→D+12 17.0%**로 정직하게 상승. ② **ORACLE(실측입력) 바닥 ~10.3% 평평** — 실예보−ORACLE 격차(D+1 +2.6%p→D+12 +6.7%p)는 **예보 입력 품질**이지 가스모델 학습 문제 아님 → **가스(7) 재학습 무효 재확인(G-14 A안, 프록시 아닌 실예보로도 성립)**. ③ 수요가 실예보에서 체계적 양bias(+1.3~3.4%, 프록시는 −0.3%로 부호 반대)→가스 +4~7.6% 과대. **해결(Phase 2)**: bias 보정을 **지평별 재적합**(Σ실측/Σraw, 송출량=물량 기준 합계 unbiased) — calib D+1 0.95594~D+12 0.93419, 서빙은 dayahead 선형보간(`serve_land_gas._calib_for_dayahead`), freshest=근지평. 옛 단일계수 0.96509는 legacy 보존. 검증 backfill D+1 MAPE 13.07→12.93%·bias +3.2→+2.2%. **재학습은 보류**(사용자: 일단 보정·이력 더 쌓이면 재정교화 고려). 산출 `training/{build_horizon_backtest,diagnose_horizon,fit_calib}.py`·`horizon_backtest.parquet`·`REPORT_horizon_diagnosis.md`·`fig/tab`·`gas_serving_calib.json`. **남음(Phase 3)**: 지평별 서빙출력 이력 테이블 `est_horizon_land`(forecast_horizon 대칭)+8단계 데모 실예보 소스 전환.

- [x] **G-17. 수요(5) 모델 피처 엔지니어링 + 낮 비대칭 (v2 production)** (2026-06-14) — G-16 진단(수요가 낮09-15h·봄에 +6%대 체계 과대→가스 전파) 후속. 사용자 확정: **구조 = Global Model with Horizon Feature 유지**(pooled vs direct 실예보 동률, 먼 지평 pooled 근소 우위). **피처 = 지점선택(일사=서산·영광/풍속=대관령·포항/기온5) + 구름(서산·영광) + cap_btmppa(월별 PPA, kr_elec_capa.csv)**. ★ cap_btmppa(BTM 듀크커브 신호)가 핵심 — land 5-A엔 빠져 있었음(제주 2-A엔 있었음). **손실 = 커스텀 L2 비대칭, 낮&과대(pred>actual) grad/hess ×8**(land 부호=낮 과대를 아래로, 제주식 반대·복붙 금지). 결과(실예보 백테스트): 봄 낮 9.43%/+6.25 → **7.91%/+3.90%**(MAPE −1.5%p·bias 거의 절반), 겨울 낮 8.10→**6.23%**, D+7 5.16→4.22%·D+12 6.37→5.48%, 밤·전체 무해. production: `train_demand_v2.py`→`lgbm_land_demand_v2.txt`+`model_meta_v2.json`, `serve_land_demand.py` v2(지점선택·구름·cap_btmppa·offset가산), **backfill D+1 4.30→3.56%**. 구버전 보존(롤백). 산출 `model/REPORT_5-A_v2.md`·`exp_{weather_agg,features,asym}.py`·`compare_pooled_vs_direct.py`. **남음**: 가스 체인 전파 + 가스 동일 사고(BTM/PPA·horizon 피처) 적용 + Phase 2 보정 재적합.

- [x] **G-18. 가스(7) 모델 재정교화 — 자기회귀 다지평 + MIXED 비율 + 낮 비대칭 (v2)** (2026-06-14) — 사용자 통찰: 가스도 자기 과거가 있으니 5-A처럼 자기회귀 직접 다지평으로(구 7-A2 동시점이 가스 자기상관 lag168 0.78을 버림). 가스 가용성=수요와 동일 → 가스 lag 누수 아님(§5 '타깃 lag 금지' override, 명제는 드라이버-only 7-A 보존). **피처 MIXED**: real_demand_land(MW)·renew_util(신재생만 비율)·gas_lag168/lag24/rec24/rec168·h·hour·dow·doy. **제외 net_load**(수요와 VIF 126·r 0.986 중복)·**cap_btmppa**(가스 corr −0.016·연도 corr 0.935·test 100% 외삽=covariate shift, 실험서 악화)·month·day_type. **★ MW vs 비율 종합검토**: 가스·수요는 정상(corr~0)→MW, 신재생만 표류(외삽 14%→util 3%)→util. 전부-비율은 가스÷LNG_cap(100% 외삽) 수입으로 +6~9% 과대(cap_btmppa 함정). **MIXED 최고**. 타깃=가스 MW. **손실**=낮(09-15h) 과대 비대칭 L2 α=4(α8은 과보정). **보정**=낮/밤 분리 지평별(전역보정이 비대칭 낮교정 푸는 것 방지). 결과(v2 수요+가스): D+1 13.02→12.22%·D+12 17.03→15.12%·**봄 낮 24.46→19.77%(−4.7%p)**·겨울 낮 20.02→16.06%·여름 낮 17.80→14.25%. production `train_gas_v2.py`→`lgbm_land_gas_v2.txt`+`model_meta_gas_v2.json`+`serve_land_gas.py` 전면 v2, 구 7-A2·7-A 보존. 산출 `model/REPORT_7_v2.md`·`exp_gas{,_features,_ratio,_asym}.py`. **남음**: DB 체인 v2 재적재 + Phase 3.

- [x] **G-19. 전국 풀체인 지평 확장(D+15) + 기후값 블렌딩 + est_horizon_land** (2026-06-15) — 사용자: 전체 체인을 forecast_horizon 전 구간에서 정직 검증해야 명제 완성. ① **정직성 결함 수정**: 수요 v2의 lag168이 D+8+에서 미래누설(타깃−168h가 원점보다 미래·백테스트가 과거라 채워져 장지평 과대평가). → **lag168/336/504 가용성 NaN가드**(h≤k & 과거일 때만; 5-A2 LAGW 일반화, 사용자 확정). 서빙(`serve_land_demand` 캡 7→15·lag336/504)·학습(`exp_features.BASEFEAT/build_samples`) 일관 적용. ② **모델 지평 확장**: 수요 v2(exp_features HMAX 168→360)·가스 v2(exp_gas_ratio HMAX 288→360) 재학습, 솔라 PatchTST D14/D15 가중치 활성화(`SOLAR_PT_HORIZONS`·`LAND_HORIZONS`=1..15, 빈 8-11/13은 LGBM 폴백). ③ **풀체인 정직 백테스트(D+1~15)** `build_chain_horizon.py`(182 base)→ **`est_horizon_land`**(forecast_horizon 양식: base·horizon_d·timestamp, 64,939행, 미래 보존) 적재 = Phase 3 지평출력 테이블. 정직 가스(보정후) D+1 12.6→D+12 14.9→D+15 15.3%, 수요 3.4→5.6%, 신재생 nMAE 16→44%. ④ **★ 하드규칙 변경 — G-16의 "백테스트 기후값 폴백 절대 금지" 해제**: 사용자가 "기후값도 우리가 만든 평년 모델"로 재정의하고 **장지평 블렌딩**을 도입. ⑤ **기후값 정의+블렌딩(MAPE 최소·계절 검증, Option A 단조)**: 가스 기후값=우리 historical(2022-24) doy±7일 슬라이딩×시각×요일유형(한국 급변동 대응 오버랩). final=(1-w(h))·예보보정+w·기후값, w 0(D+1~4)→0.5(D+15). 전체 13.96→13.72%, 여름 장지평 −3%p(D+15 20.7→17.9), 겨울·봄 손해 없음(앙상블 효과). 서빙 `serve_land_gas.py`+`gas_serving_calib.json`(`blend_weight_by_horizon`·`climatology`) 통합. **한계**: 평가창 겨울~초여름(여름=6월만·가을 없음)→여름/가을 쌓이면 w 재조정. 산출 `training/{build_chain_horizon,analyze_blending,finalize_gas_archive}.py`·`model/{review,archive}_demand_horizon.py`·`fig/{chain_horizon_v2,blend_overall,blend_by_season}.png`. **운영 forecast 스냅샷 재적재는 사용자가 서버에서 직접 수행.**

- [x] **G-21. 전국 수요(5) PatchTST 하이브리드 production 서빙** (2026-06-19) — 사용자: final2(낮 오버라이드 후보)를 실제 서빙에 반영. ① **구조 확정**: D+1~2 full PatchTST(`final336`=seq336+comfort+MSE) / D+3~7 주간(09~15)=PatchTST·야간=LGBM / D+8~15 LGBM. ② **3건 기각**(한 변수씩 honest 검증): **예보오차 증강**(forecast_horizon 지평별 (예보−실측) 잔차 부트스트랩 주입 — 용량반응 악화, 예보오차는 invariant 대상 nuisance 아님·학습 때 날씨 흐리면 날씨→수요 관계만 뭉개짐, perfect-honest 격차는 예보 환원불가 오차), **시간 Late Fusion**(백본 weather+타깃만·시간 전용경로 late concat — honest≈final2, D+1만 우위), **comfort di/wct**(VIF 665/351/155 다중공선성·honest 악화). ③ **LGBM 피처강화=v2hum**: temp_c(5)→temp_c4(4,대관령제외)·생바람 제거·**raw humidity 추가**(di/wct 폐기) — VIF 클린(temp_c4 7.7), v2 대비 밤−0.04·여름낮−0.32·전체 동률. exp_features에 temp_c4·humidity·di·wct 빌드 추가(학습·서빙·honest 공유, additive — v2 무영향). ④ **honest(n=63,064)**: 기존 LGBM 4.495→하이브리드 **4.395**·낮 7.92→**7.67**. 이득 D+1~7 집중(D+1 −0.69). 계절별 낮=**봄 주도**(D+1~7 −1.47, 덕커브)·겨울 +0.03·여름낮 +0.86(PatchTST 약점이나 6월 한달 표본→마스크 예외 안 둠=과적합 회피, watch-item). ⑤ **서빙**: `serve_demand_patch.py`(final336 D1~7 추론·comfort 재구성·seq336 과거창·하이브리드 마스크) 신설 → `serve_chain_land_new.py`가 v2→v2hum 교체 + 결합 → **est_horizon_land 3컬럼**(`est_demand_land`=합본·step7 입력 불변 / `est_demand_lgbm` / `est_demand_patch`). 검증: D+1·2 land=patch 24h / D+3~7 7h / D+8+ patch NULL, ALTER 자동·적재 정상. ⑥ **기후값 블렌딩=demand엔 불필요**(v2→v2hum 기상피처 대폭변경에도 D+8~15 ±0.06 = 장지평 수요 기상입력 둔감·자기회귀 lag336/504 지배; 가스 G-19와 상황 다름). streamlit 신컬럼 노출도 스킵. ⑦ **정리**: 기각 가중치(aug·latefusion·final2[seq504]·v2comfort)·노트북·npz 358MB→루트 `nouse/`(재현 생성기·평가코드는 원위치 보존). 산출 `serve_demand_patch.py`·`training/landdemand_final336/`·`models/lgbm_land_demand_v2hum.txt`·`train_demand_v2hum.py`·`_ab_comfort_eval.py`·갱신 `exp_features.py`·`serve_chain_land_new.py`·`REPORT_5-B.md §9~12`. **서버 배포(weights+`serve_chain_land_new --backfill 전체`)는 사용자 수동.**

- [x] **G-20. 제주 2·3단계 새 DB 구조 재설계 — 진단·강건성·피처 확정** (2026-06-17) — 제주를 육지처럼 새 DB 구조(`forecast_horizon`=기상아카이브 / `est_horizon_jeju`=서빙결과 / `historical`이 `*_da` 보존 / 레거시 `forecast` 폐기)로 옮기기 전에, 현행 2(수요)·3(신재생→net_load) 모델을 jeju `forecast_horizon`(180 base·D+1~7) 실예보로 정직 재검증(육지 G-16 미러). **SMP(4)는 이번 범위 제외**(점예측=잠긴 실패경로). ① **진단**(`3. jeju_solarwind_forecaster/training/build_horizon_backtest_jeju.py`→`horizon_backtest_jeju.parquet` 178base·58,745행, forecast+ORACLE 모드 / `diagnose_horizon_jeju.py` / `REPORT_horizon_diagnosis_jeju.md`): 육지 패턴 재현 — **ORACLE(입력완벽) 평평 바닥선**(수요 D+1~7 4.1~4.4%·태양광nMAE낮~0.07·net_load nMAE~7.2%) vs **실예보 지평열화**(수요 4.60→6.67%·태양광nMAE낮 0.102→0.180·net_load 8.75→15.14%)=격차는 예보품질(특히 태양광 고침투). **수요 bias 거의0**(육지 +1.3~3.4% 양bias 없음). ② **결론 — 모델 재설계 ROI 낮음**: 수요 2-A는 이미 v2 피처(cap_btmppa·구름·비대칭) 보유(육지가 역수입)·bias 없음. 신재생은 열화가 예보 cloud/radiation 스킬(비가역, 3단계 기존결론 정량확인). → 실질작업=서빙 전환. ③ **전제 갭 복구**: jeju KIMG 일사예보가 `radiation_south` 단일지점뿐이라 `forecast_horizon`에 `radiation_west` 없었음(태양광 모델 필수입력)→사용자가 west(+east) 180base 전체 재수집·적재. ④ **강건성 점검(D+1 8% 목표)**: 풍력=모델 천장근처(ORACLE 0.087~0.105, "겨울 헤드룸"은 착시=바람세서 이용률큼·CV는 겨울최저, 풍속설명 천장근접), east 풍향 1회 실험→**forecast 악화로 복귀**(실측≠예보 교훈, west/east 풍향 중복). 태양광=후처리 헤드룸 없음(서빙가용 신호 기준 잘 보정됨, 남은건 예보 분산). ⑤ **피처 확정(사용자, LGBM 한정·PatchTST 미재학습)**: solar_damping·clearsky_ratio south단독, wind_zone east단독 → forecast 중립(악화 없음). ⑥ **★야간 0 마스크**: 태양광이 밤·해질녘 가짜이용률(겨울18h~0.15·밤 최대92MW, 코드에 야간마스크 전무)→**pvlib 태양고도<5° 강제0**(`serve_solarwind_hybrid._daylight_mask`, 제주 33.38N/126.55E·KST). 밤 est_solar 정확히0·여름 실일조 보존·net_load D+7 nMAE 15.13→14.62%. `_predict_day`에 넣어 백테스트·새서빙 자동전파. ⑦ **★서빙 전환 완료**: `serve_chain_jeju_new.py`(2→3→`est_horizon_jeju` 신설, PK base·timestamp + est_demand/solar_util/wind_util/solar_gen/wind_gen/net_load_jeju) = 육지 serve_chain_land_new 미러. 기상=forecast_horizon·day_type=공휴일달력·`forecast` 테이블 미접촉. 검증 backfill 8 base→1344행 D+1~7, 야간 태양광 0 반영. **남음 = deploy 래퍼+crontab(사용자 수동)·streamlit 제주 소스전환(8-B)·est_horizon_jeju 전구간 backfill.**

- [x] **G-22. 제주 SMP(4) est_horizon_jeju 재배선 — forecast 폐기 사전작업** (2026-06-20) — 제주 `forecast` 테이블 제거 목표의 SMP 부분. **재배선(재모델링 아님)**: SMP 입력(net_load·est_demand·smp_jeju_da)을 `train_smp_db.load_forecast`가 forecast에서 읽던 것을 `est_horizon_jeju`(+historical DA)로, 출력 18컬럼을 신설 `est_smp_horizon_jeju`로. 모델은 historical 학습이라 불변·피처(06-05 확정) 유지. 사용자 확정=① 재배선(잠긴 코드 무수정 스크래치 재사용) ② 핵심3컬럼만(est_smp·smp_neg_proba·smp_danger, D+1/D+2). 신설 `serve_smp_horizon_jeju.py`(monkeypatch 2지점: DB_PATH·d2 with_target=False). 검증(`validate_smp_horizon_jeju.py`, parquet 178base 음수147h): D+1 recall0.84/prec0.39·D+2 0.81/0.40·D+1가격 MAE0.00 = 기존(0.86/0.38·0.86/0.37·A안) 동등 → 성능보존. **+ 같은 날 forecast 테이블 DROP 완료**(백업 후·안전확인·수집기 build() 미래DA→historical 컬럼단위 upsert로 은퇴·SMP cron④ 신설). 제주 DB=4테이블. streamlit 제주 페이지는 전면 재작성 예정(옛 8-B 플랜 폐기). 상세 §8 로그.

### 열림(전국 트랙)
- [ ] **G-9. 관계 검증(EDA) 게이트 — 모든 모델링 선행** — 모델 착수 전 net_load → 타깃 관계의 강도·형태(부하수준별), 시간적 안정성(함수 표류 여부), train↔test 분포 겹침을 확인(§5.0.5). G-6이 "데이터가 멀쩡한가"였다면 G-9는 "명제가 데이터에 실제로 있는가". 표류·분포 이탈 시 처리 방안을 정한 뒤에만 착수. 단계마다(7·5·6 등) 적용. **피처 최종 입력은 EDA 후 사용자에게 묻고 확정한다(§0.6).**
- [ ] **G-8. 전국 원천 CSV 위치** — `second_dataset/build_dataset.py`의 `CSV` 입력(oil_price, KOGAS, HVDC, only_gen) 실제 경로 확정 필요. 현재 코드의 `"7. data from csv"`는 존재하지 않는 폴더(stale)라 TODO로 표시됨. 빌더 재실행 시에만 영향(현재 parquet는 이미 생성됨).

---

## 8. 진행 로그 (최신이 위로)

> 2026-06-07 이전 로그는 `docs/PROJECT_LOG.md`로 이관(무수정 보존).

**2026-06-21 — 가스(7) 새 체인 정직 재검증 (5·6 구조변경 영향 점검, 구조변경 불필요 확인)**
- 배경: 5단계가 PatchTST v4+지평별 파인튜닝(G-24), 6단계가 landsolar504(06-19)로 바뀜 → 가스 예보기 튜닝 필요성 분석 요청. 서빙(`serve_chain_land_new.py`)은 이미 새 구조지만, 가스 공개 정확도(13.72%)·후처리(낮/밤 보정·블렌딩)는 **옛 수요(하이브리드)·옛 6단계로 측정·적합된 값**이라 실제 새 체인 성능이 미측정 상태였음.
- 방법: 옛 `build_horizon_backtest.py`(옛 수요 5-A2 + 옛 가스 7-A2 util, 이동·수정 금지 대상)는 안 건드리고, **현재 배포 체인 함수 `serve_chain_land_new.build_base`(v4 수요 + landsolar504 + 가스 v2 + 낮/밤보정 + 블렌딩)를 그대로 재사용**해 forecast_horizon 186 base 전체에서 실측 대조. 누수 없음(기상=그 base 실예보, 가스 자기회귀 시드는 origin 이하만). 신규 `training/validate_newchain_gas.py` → `newchain_gas_backtest.parquet`(20,688 평가행).
- **결과(가스 MAPE, 보정 OFF·블렌딩 ON)**: 전체 **12.81%**(옛 공개 13.72% 대비 −0.9%p) / D+1 11.89·D+2 12.21·D+3 12.76·D+7 13.32·D+12 13.93%. **장지평 개선폭 큼 = 새 수요가 훨씬 정확**(수요 MAPE D+1 2.44→D+12 4.79%, 옛 ~5.4% 대비)해 가스 전파오차 감소.
- **★한낮 이중보정 우려 → 해소 확인**: 옛 가스 v2 가 잡으려던 "봄 낮 가스 과대(+11%·MAPE 19.77%)"가 사라짐 — 봄 낮 bias −1.8%·낮 전체 bias −0.6%(≈중립, 부호 역전 없음). 5단계 파인튜닝이 한낮 과대를 수요 단에서 근본 제거 → 가스 낮 비대칭(α4)+낮보정은 이제 약간 불필요하나 무해.
- **남는 과제(5·6과 무관)**: 계절 bias 갈림 = 겨울 −4.6 / 봄 −3.4 / 여름 +7.5%(밤 −3.7%). 가스 모델 기존 문제(2022–24 학습·절대 MW 타깃 → 2026 LNG 증설 미반영 과소 + 여름 과대)이고 bias 보정이 06-15부터 OFF 인 이유와 동일. 여름·가을 표본은 아직 얇음(여름 n=2096, 가을 0).
- **결론**: 가스 **구조 변경 불필요**. 5·6 변경에도 서빙 정상·정확도 개선·한낮 부호 역전 없음. 사용자 결정에 따라 2단계(후처리 w(h)·보정표 새 오차로 재적합, 필요시 α 완화)는 보류(데이터 더 쌓인 뒤 재적합 권장). 산출 `training/{validate_newchain_gas.py, newchain_gas_backtest.parquet}`.

**2026-06-21 — 전국 수요(5) 한낮 과대 진단 + 지평별 파인튜닝 하이브리드 배포 (G-24)**
- 출발: G-23 v4 의 한낮(09~15시) 과대예측이 왜 남나. **진단**: 타깃 `real_demand_land`=BTM 차감 그리드 계량값인데, BTM+PPA 태양광이 **2025년 폭증**(한낮 12~14시 0→16GW, 2026-03 용량 21GW). 4·5월 "한낮−새벽" 계량수요 부호가 2024년 +에서 **2025년부터 −(덕커브)** 로 뒤집힘 = 학습창(<2025, BTM≈0)과 현재가 다른 세상. residual head 가 옛 "한낮 봉우리"를 얹어 과대. **★오차가 solar_rad 조건부**(보정전 낮 bias 흐림 −2%→맑음 +8%, r=+0.42).
- **핵심 통찰**: post-hoc 보정표는 키가 (계절·시각·지평)뿐이라 **solar 조건부 spread 를 구조적으로 못 줄임**(낮 range 보정 10.3≈raw 10.4, 흐린 날 오히려 −5.3% 악화). **레벨은 anchor/clim 이 21GW 를 잘 추적**(최근 계량수요 1~4주 lag) — stale 한 건 residual head 의 관계뿐. scaler Robust→MinMax 검토는 별개(이상치 없어 안전하나 한낮 과대와 무관, Demand 타깃은 애초 스케일 안 됨).
- **해법 = head-only 파인튜닝**(`finetune_lt.py`): 기존 가중치 로드→인코더·cross-attn **동결**, `regressor`+`weather_bypass`(5.2%)만 재학습. scaler/DMEAN/DSTD/RESID_STD/HP 전부 보존. 신체제(2024-11~2025-11)만 학습. Colab GPU 노트북(`finetune_land_lt_colab.ipynb`).
- **split 설계**(사용자와 확정): train/val=historical(실측 기상)·**격자 split p=1/6**(하루단위 교차·요일유형(평일/주말/공휴일)·계절 층화 systematic, 공휴일묶음·주말쌍 무결, `make_split.py`→`finetune_split.csv`). **test=forecast_horizon(예보 기상, 186 base 2025-12-15~2026-06-18)** 봉인 — 소스가 달라야 서빙현실(예보오차) 반영. train 은 2025-11-30 에서 끊어 test 와 무겹침.
- **봉인 test 결정**(eval_finetune.py, 60,668행): ft 단독은 production(3.89) 미달(MAPE 4.40)이나 **보정이 못 하는 solar spread 를 줄임**(10.4→8.2). 지평그룹 분해 → **효과가 D1-6 집중**(낮 solar range 초단 7.3→3.3·단 8.9→5.9, D7+ 미미+MAPE 악화=장지평 과적합). → 사용자 결정: **"보정이 5구간 차등하듯 파인튜닝도 단기만"** = 지평별 선택.
- **채택·검증**: **D1-6=ft 무보정 / D7-15=기존 v4+보정 유지**. D7-15 보정 제거 비교했으나 낮 +4.4% 과대 복귀(ft 가 장지평 과적합이라 대체 불가)→보정 유지. 하이브리드 봉인 test = MAPE 3.95(production 동급)·단기 낮 spread 7.8→4.6(41%↓). 잔여 낮 bias +0.6 은 무시(과적합 회피).
- **배포·정리**(사용자: 헷갈리지 않게): 가중치 git 미추적 → **이름변경 무손실 배포**. `weights/`(원본)→`weights_v4_orig/`(롤백 백업)·`weights_hybrid/`→`weights/`(서빙 경로 `serve_chain_land_new.py:LT_DIR` 그대로라 코드 무수정). calib_lt.json 360→216셀(초단·단 제거). weights_ft·weights.zip 삭제. md5 로 D1-6 교체·D7-15 원본 확인, 체인 5→6→7 `--no-write` 전구간 정상(base 2026-06-18 수요 62,917MW). `calibrate_lt.py`는 D7-15(중·중장·장)만 굽도록 수정(SKIP_GROUPS, 초단·단 스킵 주석 보존) → 재실행 안전. 분석 아카이브 `eda_scaler/`(REPORT 2종·스크립트·그림·duck_curve_flip.png 보존).
- 메모리 [[land-demand-midday-btm-finetune]] 신설 + [[land-stages-done]]·[[land-demand-patchtst-hybrid]] 갱신(옛 단일모델/lgbm-하이브리드 설명 stale 수정). **커밋·서버 배포는 사용자 수동.**

**2026-06-20 — 제주 SMP(4단계) est_horizon_jeju 재배선 + forecast 테이블 폐기 완료 (G-22)**
- 목표(사용자): 제주 DB의 레거시 `forecast` 테이블을 궁극적으로 제거. 막는 둘 중 ⓑ SMP를 먼저 처리(ⓐ streamlit 8-B는 후속). SMP는 **D+2까지만** 지원.
- **혼선 정리(선행)**: PROJECT.md 347줄 "제주 forecast 현역"은 06-15 시점 문장이라 06-17 G-20 전환을 못 담은 것. 실제 = 제주 예측 정본은 이미 `est_horizon_jeju`(06:30 cron). forecast가 남은 이유는 ⓐ streamlit 데모 ⓑ SMP뿐. forecast 예측컬럼 갱신 cron은 0건(동결). → 347줄 보충 포인터·메모리 [[jeju-rebuild-newdb]] 오독금지 항목 추가.
- **진단 = 재모델링 아니라 재배선**: SMP 입력피처(`net_load`=est_net_load_jeju·`est_demand`=jeju_est_demand_new·`smp_jeju_da`)를 `train_smp_db.load_forecast` 가 forecast 에서 읽음(단일 통로). 모델은 historical 실측으로 학습→forecast 폐기와 무관(재학습 불필요). 피처도 2026-06-05 확정분 유지. **바뀌는 건 입출력 테이블뿐**. SMP 점예측은 잠긴 실패경로라 모델 손대지 않음.
- **사용자 확정**: ① 방식=**재배선**(잠긴 모델·스크래치 무수정 재사용, serve_chain_jeju_new 패턴) ② 출력=**핵심 3컬럼만**(`est_smp`·`smp_neg_proba`·`smp_danger`, 깊이/위험레이어/고확신 제외).
- **★서빙 러너 신설** `4. jeju_smp_forecaster/serve_smp_horizon_jeju.py`: est_horizon_jeju(horizon_d 1~3) → 스크래치 `forecast` 형태 주입(컬럼 rename·smp_jeju_da는 historical)→ 잠긴 `smp_db_pipeline`(D+1)·`smp_d2_pipeline`(D+2) 무수정 호출 → 핵심3컬럼 수확 → **신설 `est_smp_horizon_jeju`**(PK base·timestamp + horizon_d·est_smp·smp_neg_proba·smp_danger). monkeypatch 2지점만(DB_PATH·d2 load_forecast `with_target=False`로 미래행 보존 — 원본 d2는 rt inner-join이라 backfill 전용). 스크래치에 horizon 1~3 적재=D+2 lead/shift24 경계 NaN 방지(수확은 1·2). Windows 파일잠김(with-블록 미close)은 gc.collect 회수.
- **검증 통과** `training/validate_smp_horizon_jeju.py`→`REPORT_smp_horizon_validation_jeju.md`: 로컬 forecast 예측은 06-01 동결·est_horizon은 8 base(여름·이벤트0)뿐이라 직접비교 불가 → `horizon_backtest_jeju.parquet`(178 base·Dec~Jun, 음수 147h/52일)를 입력으로 러너 재사용. **D+1 경보 recall 0.84/prec 0.39**(기존 θ=0.25 0.86/0.38 동등)·**D+2 0.81/0.40**(설계점 0.86/0.37 동등)·**D+1 가격선 MAE 0.00**(A안 DA통과 완전일치)·D+2 11.73. 야간마스크 net_load는 한낮 음수가격에 영향 없음 정량확인. → 재배선이 성능 보존.
- **★forecast 테이블 폐기 완료(같은 날, 사용자 "과감하게 drop")**: 제주 DB는 이제 **4테이블 = historical·forecast_horizon·est_horizon_jeju·est_smp_horizon_jeju**. drop 전 안전확인(`smp_jeju_da`는 historical 56,568행 완비·forecast에만 있는 시각 0 / forecast 유일컬럼은 전부 동결 레거시 예측)·백업(`99. others/forecast_jeju_backup_2026-06-20.parquet` 4,248행) 후 DROP+VACUUM. 러너는 forecast 없이도 정상(스크래치 자체 생성).
- **수집기 은퇴 처리(forecast 재생성 차단)**: ⓐ `collect_data_jeju.build()` → 미래 *_da 를 forecast 대신 **historical 에 컬럼단위 UPSERT**(신규 `upsert_da_to_historical`, ON CONFLICT+COALESCE — partial_upsert의 INSERT OR REPLACE는 행 전체교체라 실측 NULL파괴 위험, 격리 테스트로 실측 보존 실증). weather 출력 제거(forecast_horizon이 정본). ⓑ `run_backfill`(weather→forecast 백필)=폐기(RuntimeError, backfill_jeju_forecast.py로 대체). ⓒ deploy: `run_serve_smp_jeju.sh`(④ 06:40) 신설·crontab 정리(run_collect_jeju 1줄=historical만, forecast-days 7줄 폐지).
- **streamlit 8-B 플랜 폐기(사용자)**: 제주 페이지는 **처음부터 재작성**(forecast 의존 전제가 사라짐). 재작성 시 net_load·수요=est_horizon_jeju, SMP=est_smp_horizon_jeju, 기상=forecast_horizon, DA·실측=historical 사용. = 별도 신규 작업(옛 8-B 점진전환 계획 무효).
- **결과 검증·정확도 확인(사용자 "값을 직접 보고싶다")**: `training/inspect_smp_examples.py`(parquet 178base 서빙→사례·그림)·`fig/smp_inspect_spring.png`. **D+1 가격선=DA 정확히 일치(A안 확인)**·봄 음수일 52일 중 49일 경보 적중(94%). **D+2 가격선(예측 DA) MAE 11.73원**(나이브 lag24 14.32 대비 +2.60 개선=−18%)·bias +0.58·상관 0.639·음수경보 recall0.81/prec0.40(계절 무관 baseline 우위). 실예시 2026-05-01: DA(가격선) 한낮 0원인데 rt −70 → dangerzone가 정확히 경보(=DA로 안 보이는 음수위험 포착).
- **target 명확화(사용자 질문 "rt 아니라 DA 예측 맞지?")**: 맞음. 가격선 target=**SMP_DA**(D+1 발표값 그대로·D+2 DA잔차회귀), dangerzone=**음수(rt<5) 이진 경보**. rt 점예측 안 함(잠긴 실패경로). 오해 소지였던 `train_smp_db.TARGET_REG`(이름이 회귀 암시) → **`RT_COL`로 개명**(실제 용도=음수 라벨·채점용 rt 컬럼, 회귀 타깃 아님 주석) — train_binary_smp·smp_calibrate 동반 갱신.
- **죽은 SMP 서빙 코드 정리(사용자 확인)**: forecast 폐기로 실행 즉시 깨지는 옛 코드 3개를 `4. jeju_smp_forecaster/no use/dead_forecast_pipelines_2026-06-20/`로 이동(README 동봉) — `smp_serve.py`(옛 통합 서빙, 대체=serve_smp_horizon_jeju)·`smp_depth_pipeline.py`·`smp_softest_pipeline.py`(깊이·위험레이어, 핵심3컬럼서 제외). depth/softest는 smp_serve만 import → 셋 함께 이동 무회귀. 운영 폴더 라이브=`serve_smp_horizon_jeju`·`smp_db_pipeline`·`smp_d2_pipeline`·`train_smp_db` 4개(스크래치 경유, 실 forecast 미접촉). (98 report only의 compare_* 분석 스크립트는 forecast 의존이나 보고용이라 보류.)
- **남음**: 서버 반영(weights·crontab 갱신·`serve_smp_horizon_jeju --backfill` 누적, 사용자 수동) · 제주 streamlit 페이지 신규 작성 · est_horizon_jeju/est_smp_horizon_jeju 전구간 backfill. 메모리 [[jeju-smp-done]]·[[jeju-rebuild-newdb]]·[[streamlit-step8-progress]] 갱신.

**2026-06-19(b) — 전국 서빙 단일화 정리: 솔라504 전환·est_horizon_land 전구간 재구축·forecast 테이블 폐기·단독 실행 스크립트 정리**
- **6단계 솔라 가중치 교체**: `landsolar_patchtst`(seq336·D{1-7,12,14,15} 10개) → **`landsolar504`(seq504·d_model256·D1~D15 전 15개)**. 빈 지평(8-11,13) LGBM 폴백 사라짐=전 지평 PatchTST. 피처 동일이라 `serve_solarwind_land.py`의 `PT_DIR`·`SOLAR_PT_HORIZONS=1..15`만 교체(아키텍처는 메타 HP로 자동). 15개 strict 로드·체인서 D+8~13 solar=patchtst 검증.
- **est_horizon_land 전구간 재구축**: 기존 backfill이 하이브리드 이전 수요+504 이전 솔라라 혼선 → 낡은 값 전부 삭제 후 `serve_chain_land_new --backfill 186`으로 현행 모델 재적재(66,368행·186 base·2025-12-16~2026-06-30·D+1~15). 레거시 forecast 테이블의 옛 예측 컬럼 11개도 NULL 처리.
- **forecast 테이블 폐기(land)**: 전국 DB는 이제 **3테이블 구조 = est_horizon_land(예측)·forecast_horizon(기상 아카이브)·historical(실측)**. 옛 forecast 테이블 DROP(수집은 이미 forecast_horizon으로 이전됨, 예측은 est_horizon_land로 이전됨). **제주 forecast는 (이 시점엔) 현역이라 유지**(제주는 아직 forecast 기반). ※**갱신(06-17, G-20)**: 제주 예측 서빙도 `serve_chain_jeju_new.py`→`est_horizon_jeju`로 전환 완료(forecast 미접촉). 따라서 제주 예측 정본은 이미 `est_horizon_jeju`이고, 레거시 `forecast.jeju_*`가 남은 이유는 ⓐ streamlit 데모(8-B 미전환)와 ⓑ SMP(4단계, 체인 범위 밖·`est_horizon_jeju` 대응물 없음) 둘뿐이다. forecast의 제주 예측 컬럼을 갱신하는 cron은 없다(동결).
- **단계별 단독 실행 스크립트 정리**: 통합 체인 `serve_chain_land_new.py`가 5→6→7을 한 번에 돌리므로 단계별 직접 실행은 체인과 중복 → `serve_land_demand.py`는 `99. others`로 아카이브(아무것도 import 안 함), `serve_solarwind_land.py`·`serve_land_gas.py`는 체인이 import하는 라이브러리 함수만 남기고 forecast에 쓰던 단독 실행부(`predict_*_to_db`·`backfill_*_to_db`·`__main__`) 제거. 체인 무회귀 확인.
- 메모리 [[land-stages-done]]·[[streamlit-step8-progress]]·[[land-demand-patchtst-hybrid]] 갱신.

**2026-06-19 — 전국 수요(5) 하이브리드 production 서빙 반영 (G-21)**
- 무엇을: final2 후속 — PatchTST를 서빙에 반영. **하이브리드 확정**: D+1~2 full PatchTST(final336=seq336+comfort+MSE) / D+3~7 주간(09~15)=PatchTST·야간=LGBM / D+8~15 LGBM(**v2hum**).
- **기각 3건**: 예보오차 증강(용량-반응 악화 — 예보오차는 invariant 대상 nuisance 아님, 학습 때 날씨 흐리면 관계만 뭉개짐), 시간 Late Fusion(honest≈final2, D+1만 우위), comfort di/wct(VIF 665/351/155 다중공선성·악화). → **raw humidity 채택=v2hum**(temp 4지점·생바람 제거, di/wct 폐기).
- **honest(n=63,064)**: 기존 LGBM v2 4.495→**하이브리드 4.395**·낮 7.92→**7.67**·밤 동률. 이득 D+1~7 집중(**D+1 −0.69**·D+3 −0.31). **계절별 낮: 봄 주도**(D+1~7 −1.47, 덕커브)·겨울 +0.03·**여름낮은 PatchTST 약점(+0.86)이나 표본작음→마스크 예외 안 둠**(과적합 회피, watch-item).
- 서빙: `7.../serve_chain_land_new.py`(수요 v2→v2hum + `5.../serve_demand_patch.py`(final336 D1~7) 결합)→**est_horizon_land 3컬럼**(`est_demand_land`=합본·step7 입력 불변 / `est_demand_lgbm` / `est_demand_patch`). exp_features에 temp_c4·humidity·di·wct 빌드 추가(공유). **기후값 블렌딩=demand엔 불필요**(장지평 수요는 기상입력 둔감, 자기회귀 지배 — 가스 G-19와 상황 다름). 미사용 가중치 358MB→루트 `nouse/`. 상세 `REPORT_5-B.md §9~12`, 메모리 [[land-demand-patchtst-hybrid]]. **서버 배포(weights+`--backfill` 재적재)는 사용자 수동.**

**2026-06-18 — 전국 수요(5) PatchTST 최종 final2 + 낮 하이브리드 (5-B 결론)**
- 무엇을: 피처 재구성으로 PatchTST 최종화. final2 = Cross-Attention PatchTST+RevIN(타깃)+**전역 z-score(외생)**+**comfort(불쾌지수·체감기온)**+temp 4지점(대관령 무인 제외)+**seq_len 504**+**MSE 손실**(LTSF표준, 평가 MAPE). lag·wind·humidity·midlow_cloud 제거(중요도≈0). 서빙일관=forecast reh·wind_spd_10m로 comfort 재구성.
- **honest(forecast_horizon, n=63,064)**: 하이브리드(낮 09-15h×D+1~12=final2·그외=LGBM) **전체 4.35**(LGBM 4.495)·**낮 7.43**(7.92, −0.49%p)·밤 3.08(=LGBM)·봄 4.40·여름 3.84.
- **seq504가 장지평 낮 역전**(낮 우위 D+1~9→D+1~12·14, 사용자 "10일+ 개선" 적중)·**comfort가 여름 파탄 해결**(D+5 여름낮 10.01→5.41). **밤=구조적 LGBM**(자기회귀), final2 단독은 LGBM에 짐 → 하이브리드 필수.
- 결정: production=LGBM 백본 유지, final2 낮 오버라이드=업그레이드 후보(서빙 미반영). 탐색 모델(360·MAE·anchor 등) 정리. **★다음=예보오차 증강**(train 실측↔serve 예보 분포격차 교정). 상세 `5.../training/REPORT_5-B.md §8`, 메모리 [[land-demand-patchtst-hybrid]].

**2026-06-17 — 전국 수요(5) PatchTST 전환 탐색: 낮×D+1~5 하이브리드 (5-B)**
- 무엇을: 5단계를 LGBM(5-A_v2)→Cross-Attention PatchTST+RevIN(제주3·6단계 solar 구조)로 바꿀지 honest 검증. 5-0b 사전진단(타깃표현=RevIN·seq_len 336)→15모델 direct + 단발 360, 손실 ablation(MSEα1.3/MAEα0/MSEα1.0).
- **honest 5자 비교**(forecast_horizon 동일 63,064행, `_ab_honest.py`): 전체 MAPE LGBM v2 **4.49** < PatchTST 최선(MAEα0) 4.86 < MSEα1.3·1.0 5.02 < 단발360 5.39. **perfect 상한에선 PatchTST 압승(D+1 2.43 vs 3.48)이나 honest서 전 변형 패배**(7-D·G-16 재현, 병목=예보품질).
- **★낮/밤 분리 핵심**: PatchTST는 **낮 D+1~5만 LGBM 우위**(기상 구동), 밤은 D+2+ 전부 LGBM 승(순수 자기회귀, lag168/336 앵커 압승, PatchTST 기상장치는 밤 잡음). 밤 17/24h가 낮 강점 덮음.
- **최적 = 낮(09–15h)×D+1~5만 PatchTST 오버라이드 + 나머지 LGBM**: 전체 4.495→**4.399**·낮 7.92→**7.59**·D+1낮 5.87→4.15. 오버라이드 모델 = MAEα0(정확도) 또는 MSEα1.3(봄낮 bias +0.03, 가스체인 안전).
- **손실 ablation**: MAE>MSE(전체 MAPE) / MSE+α1.3>MAE(낮 bias, α≈1.2~1.3이 0점). 단발360·MSEα1.0·전면교체 기각.
- 결정: **production=LGBM v2 유지(현행)**, 하이브리드=업그레이드 후보(서빙 반영 미결). 상세 `5.../training/REPORT_5-B.md`, 메모리 [[land-demand-patchtst-hybrid]].

**2026-06-17 — 제주 2·3단계 새 DB 재설계 1단계: 진단·강건성·피처 확정 (G-20)**
- 무엇을: 제주를 육지처럼 새 DB 구조(`forecast_horizon`+`est_horizon_jeju`, `forecast` 폐기, `*_da`는 historical)로 옮기기 전, 현행 수요(2)·신재생(3) 모델을 jeju forecast_horizon 실예보로 처음 정직 재검증(육지 G-16 미러). SMP(4)는 범위 제외.
- **진단**: 육지 패턴 재현 — ORACLE 평평 바닥선(수요~4.1%·태양광nMAE낮~0.07·net_load~7.2%) vs 실예보 지평열화(수요 4.6→6.7%·태양광 0.102→0.180·net_load 8.75→15.14%). 격차=예보품질(특히 태양광). 수요 bias~0(육지 양bias 없음). → **모델 재설계 ROI 낮음**(2-A는 이미 v2 피처 보유=육지가 역수입, 신재생 열화는 비가역 예보스킬). 실질작업=서빙 전환.
- **전제 복구**: jeju KIMG 일사예보=`radiation_south` 단일지점→`forecast_horizon`에 west 일사 없었음(태양광 필수)→사용자가 west(+east) 180base 재수집.
- **강건성(D+1 8% 목표)**: 풍력=모델 천장근처(8% 비현실적, "겨울 헤드룸"은 이용률 크기 착시), east 풍향 실험→forecast 악화로 복귀(실측≠예보). 태양광=후처리 헤드룸 없음(잘 보정됨, 남은건 예보 분산).
- **피처 확정(사용자, LGBM 한정)**: solar_damping·clearsky south단독·wind_zone east단독(forecast 중립). **★야간 0 마스크**: pvlib 태양고도<5° 강제0(밤 가짜태양광 최대92MW→0, 여름 실일조 보존, net_load D+7 15.13→14.62%).
- 산출 `3. jeju_solarwind_forecaster/training/`(build_horizon_backtest_jeju·diagnose_horizon_jeju·exp_wind_east_dir·REPORT_horizon_diagnosis_jeju.md·parquet·fig 2). 백업 `lgbm_models/*_pre_simplify`.
- **★서빙 전환 완료(같은 날)**: `serve_chain_jeju_new.py` 신설(2→3→`est_horizon_jeju`, 육지 serve_chain_land_new 미러). 기상=forecast_horizon·day_type=공휴일달력·`forecast` 미접촉·야간마스크 자동전파. 검증 backfill 8 base→1344행 D+1~7. **다음=deploy 래퍼+crontab(사용자 수동)·streamlit 제주 소스전환(8-B)·전구간 backfill.**

**2026-06-15 — 전국 풀체인 지평 확장(D+15) + 기후값 블렌딩 + est_horizon_land (G-19)**
- 무엇을: 가스 성능 우려에서 출발해, "체인 전체를 forecast_horizon 전 구간에서 정직 검증해야 프로젝트가 완성된다"는 사용자 방침으로 5→6→7 전 단계를 D+15까지 정합·검증.
- **정직성 결함 발견·수정**: 수요 v2 lag168이 D+8 이상에서 "타깃−168h=원점보다 미래"라 실서빙 불가인데, 백테스트는 전 구간 과거라 그 값이 채워져 장지평 수요가 누설로 부풀려져 있었음. → lag168/336/504 가용성 NaN가드(h≤k & 과거)로 재설계(학습·서빙·백테스트 일관). 가스는 이미 동일 가드 보유.
- **지평 확장**: 수요(HMAX 168→360)·가스(288→360) 재학습. 솔라 PatchTST D14/D15 가중치가 디스크에 있으나 코드 미등록이라 잠자던 것 활성화(`SOLAR_PT_HORIZONS`·`LAND_HORIZONS`=1..15, 빈 지평은 LGBM 폴백 → 솔라/풍력 전 지평 가능).
- **풀체인 정직 백테스트**: `build_chain_horizon.py`(182 base×D+1~15)→ `est_horizon_land`(base·horizon_d·timestamp = forecast_horizon 양식, 64,939행, 미래 타깃 보존) 적재 = Phase 3 지평출력 테이블. 정직 가스(보정후) D+1 12.6→D+12 14.9→D+15 15.3%.
- **★ 하드규칙 변경**: G-16의 "백테스트 기후값 폴백 절대 금지"를 사용자가 해제("기후값=우리가 만든 평년 모델"). 가스 기후값(우리 historical 2022-24, doy±7일 슬라이딩×시각×요일유형)과 예보를 지평별 w로 블렌딩. final=(1-w)·예보보정+w·기후값, w 0(D+1~4)→0.5(D+15). 전체 13.96→13.72%, 여름 장지평 −3%p, 겨울·봄 무해(앙상블). MAPE 최소+계절 균형으로 선정(Option A 단조). 서빙·config 통합.
- 한계/남음: 평가창 겨울~초여름(여름=6월만·가을 없음)→데이터 쌓이면 블렌딩 w 재조정. 운영 forecast 스냅샷 재적재는 사용자가 서버에서 직접. 8단계 데모를 est_horizon_land 소스로 전환.

**2026-06-14 — 가스(7) v2: 자기회귀 다지평 + MIXED 비율 + 낮 비대칭(G-18)**
- 무엇을: 가스 모델을 5-A식 자기회귀 직접 다지평으로 전환(구 7-A2 동시점→가스 자기상관 lag168 0.78 활용). 사용자 통찰("가스도 과거 참고해 예측")+가용성 확인(가스=수요와 동일 마지막 실측, 누수 아님).
- **피처 분석(중요도·VIF·covariate shift)**: net_load 제외(수요와 VIF 126·r 0.986)·cap_btmppa 제외(가스 corr −0.016·연도 0.935·test 100% 외삽)·month 제외(doy와 VIF 145)·day_type 제외.
- **MW vs 비율 종합검토(사용자 지시)**: 가스·수요 정상(corr~0)→MW / 신재생만 표류(외삽 14%)→util. 전부-비율은 가스÷LNG_cap(100%외삽) 역효과(+6~9% 과대). **MIXED(신재생만 util) 채택**.
- **손실**=낮 과대 비대칭 α=4, **보정**=낮/밤 분리 지평별(전역보정이 낮교정 푸는 것 방지).
- 결과(v2 수요+가스 체인): D+1 13.02→12.22%·D+12 17.03→15.12%·**봄낮 24.46→19.77%·겨울낮 20.02→16.06%·여름낮 17.80→14.25%**(낮=사용자 1순위).
- production `train_gas_v2.py`·`lgbm_land_gas_v2.txt`·`serve_land_gas.py(v2)`·`REPORT_7_v2.md`·`exp_gas*`. 구 7-A2·드라이버only 7-A 보존. **다음=DB 체인 v2 재적재+Phase 3.**

**2026-06-14 — 수요(5) v2: 피처 엔지니어링 + 낮 비대칭 손실(G-17)**
- 무엇을: G-16 진단에서 수요가 낮(09-15h)·봄에 +6%대 체계 과대예측(가스로 전파)임이 드러나 수요 모델을 재정교화. 구조는 Global+Horizon 유지(pooled vs direct 실예보 동률), 피처·손실로 공략.
- **피처(사용자 확정)**: 단순 5평균 → 지점선택(일사=서산·영광/풍속=대관령·포항) + 구름(서산·영광) + **cap_btmppa(월별 PPA 용량)**. cap_btmppa 가 결정타 — BTM 듀크커브 신호가 land 5-A엔 통째로 빠져 있었음(제주 2-A엔 존재). 중요도 6.7%.
- **손실**: 커스텀 L2 비대칭(낮&과대 grad/hess ×8). ★land 부호 = 낮 과대를 아래로(제주식 반대, 복붙 금지 — 메모리 경고 데이터로 확인). 
- 결과(실예보 백테스트): 봄 낮 9.43%/+6.25 → **7.91%/+3.90%**(MAPE −1.5%p·bias 절반), 겨울 낮 8.10→6.23%, D+7 5.16→4.22%, D+12 6.37→5.48%, 밤·전체 무해. production backfill D+1 4.30→**3.56%**.
- 산출 `train_demand_v2.py`·`lgbm_land_demand_v2.txt`·`model_meta_v2.json`·`serve_land_demand.py(v2)`·`REPORT_5-A_v2.md`·`exp_{weather_agg,features,asym}.py`. 구버전 보존(롤백). **다음=가스 체인 전파+가스 동일 피처사고+Phase 2 보정 재적합.**

**2026-06-14 — 전국 지평 재검증·보정(G-16): "지평 평평"은 기후값 프록시 허상, 실예보로 정직 재측정 + 지평별 bias 보정**
- 무엇을: 사용자가 구축한 `forecast_horizon`(실예보 지평 아카이브, 육지 181 base·D+1~12)으로 5→6→7 체인을 처음으로 정직하게 재측정. 기존 7-A2-A 검증의 기상 입력이 사실상 전부 (월,시) 기후값 프록시였던 한계를 교체. **사용자 하드 규칙: 데이터 진짜 없을 때 기후값 폴백 절대 금지**(결과를 크게 망침) — ≤4h 보간(외삽 금지)만 허용, 진짜 결측은 평가 제외.
- **Phase 0 빌더**(`training/build_horizon_backtest.py`→`horizon_backtest.parquet` 21,358행): forecast_horizon[base] 실예보를 스크래치 connection으로 6단계 `_predict_day`에 주입(서빙 코드 무수정, con 인자 활용)·수요는 forecast_horizon 기상으로 5-A2 D{n} 재조립·가스는 7-A2 적용. D+7~12 3h 해상도는 ≤4h 보간으로 1h 복원(기후값 아님).
- **Phase 1 진단**(`diagnose_horizon.py`·`REPORT_horizon_diagnosis.md`·fig/tab): 가스 MAPE 실예보 **D+1 13.02→D+3 13.54→D+7 14.85→D+12 17.03%**(정직 상승) vs 프록시 13.0~13.2%(가짜 평평) vs **ORACLE(실측입력) ~10.3% 평평**. 수요 MAPE 3.55→6.49%·신재생 nMAE 15.8→39.8%(멀수록 악화). 격차=예보 품질→**가스 재학습 무효 재확인**.
- **Phase 2 보정**(`fit_calib.py`): 가스 bias가 지평의존(+4→+7.6%)이라 단일계수 불가 → **지평별 재적합**(송출량 물량 기준 Σ실측/Σraw). calib D+1 0.95594~D+12 0.93419, `serve_land_gas.py`가 dayahead 선형보간 적용(`_calib_for_dayahead`), freshest=근지평. 옛 0.96509=legacy 보존. backfill D+1 MAPE 13.07→12.93%·bias +3.2→+2.2%.
- 사용자 결정: 재학습은 보류(일단 보정, 이력 더 쌓이면 net_load 외 LGBM 모델들 재정교화 고려). **다음=Phase 3**: 지평별 서빙출력 이력 테이블 `est_horizon_land`(forecast_horizon 대칭)+8단계 데모를 실예보 지평 소스로 전환.

**2026-06-11(c) — 8단계 8-A: 디자인 개편 1차(브리핑 콘솔 테마) + 표준 날짜 컨트롤 + 기상개황 실측 병기**
- **디자인 시스템**: 기상개황 지도(weather_map.py)의 토큰을 전 페이지로 확장 — ink #0f172a / green #059669, Pretendard 본문 + IBM Plex Mono 수치. `.streamlit/config.toml` 네이티브 테마(라이트 캔버스 #f4f6f9 + **다크 잉크 사이드바**, 루트와 `8. streamlit/`에 동일 복제 — 항상 같이 수정) + `common.inject_style()` 전역 CSS(지표·차트·지도 iframe=흰 카드, 사이드바 radio=내비 메뉴, date_input 중앙정렬) + plotly 템플릿 "briefing" pio 기본 등록 + `page_header()`(eyebrow+체인 pill). **탭=알약 버튼**(기본 테두리 #94a3b8, 선택=다크 잉크 채움). 테두리 위계(사용자): 위젯 #94a3b8 / 카드 #cbd5e1 / 차트 그리드는 연하게 유지.
- **표준 날짜 컨트롤 `C.day_navigator(prefix, ndays=, refresh=)`** = "◀ 어제 | 날짜 | 내일 ▶ | 새로고침 | (기간 슬라이더) | 캡션", '오늘' 버튼 폐지. **종합은 탭별 독립 배치(사용자: 상단 공유는 디자인 무너짐 — 한 번 시도 후 번복)**: 예측확인/발전데이터/장지평=표준, 기상개황=refresh=False 슬림. 수요 예측=메뉴 상단 공통(ndays 1~7). 장지평=네비 행 오른쪽에 끝 날짜 select_slider(시작일 date_input 제거, 적재 밖 가드).
- **예측 확인 재배치(사용자)**: ⚙️ 표시 데이터 popover를 네비 행(새로고침 오른쪽)으로(`render_series_compare(gear_col=)`), 지표 4개를 plot 아래·AI 브리핑 위로 — 일별 송출량/최대·최소 시간당/가스발전 합(가스비 제거), 범례 캡션 제거. 헤더 제목="가스 송출량 예측 브리핑"·브라우저 타이틀="전국 가스송출량 예측 대쉬보드".
- **기상개황 과거·당일 실측 병기(A안 채택, B안 지도 토글은 보류)**: `_PREFIX` 매핑으로 historical(temp_c_/solar_rad_/wind_spd_)을 같은 권역 계산·같은 bin에 통과(`zone_actual`) + 이용률 실측 `national_util_actual`(KPX gen_*_utilization_kr, 같은 집계). 테이블 셀=`예보 → 실측`(과거 모드는 활성도 라벨 생략), metric delta=실측. 캡션에 "예보=rolling D+1 발행분" 정직성 명시. 실측 미적재는 예보만(제주 로컬 stale → 서버 배포 시 해소). 과거 날짜 est util 백필 없음 → 예측 "—"+실측만 나오는 날 있음(서빙 백필로 해소 가능).
- **버그 수정**: Leaflet 숨은 탭(크기 0) 초기화로 지도 빈 화면 → ResizeObserver+fitKorea 지연 맞춤. 데이터 현황 radio→segmented_control(재클릭 해제 None → `or` 기본값 폴백 필수).
- 검증=AppTest 스모크(메뉴·탭 전환·과거 날짜) 예외 0. **다음**: 사용자 화면 확인 후 잔여 폴리시 → 8-B(제주).

**2026-06-11(b) — 8단계: 기상개황 재설계(visual.md A안 + 활성도 실측 교정) + 데이터 현황 개편**
- **기상개황 전면 재구축**(`weather_map.py` 재작성, IDW choropleth 폐기): `9. design/visual.md` Decision Gate 사용자 확정 — **A안(Leaflet HTML 임베드**, 프로토타입 `renewable_capacity_map.html` 디자인 보존, 데이터만 렌더 시 주입) / **한 지도 모드 전환**(신재생 강도[용량×활성도]·일사·풍속 — HTML 내부 JS라 전환 시 rerun 없음) / 테이블은 러프. 기준 시간=**09–15시 평균**(일사·기온·풍속·강수, 시각 선택 없음), 권역 라벨=하늘상태 이모지+권역명·기온, 날짜=`day_navigator` 재사용, 지도=fitBounds로 전국+제주 자동 맞춤(한국 밖 이동·축소 잠금). 하단=전국 이용률 예측 metric(**평균+그날 최대**, `est_solar/wind_util_land`)+8권역 간략 테이블. 제주=jeju DB 고산(west) 실데이터(§7 보간 금지 준수), 기상 없으면 회색+이용률만 fallback. **DB 단위 함정: radiation=MJ/m²·h(W/m² 아님)·total_cloud=0~1 비율(0~10 아님)**.
- **활성도 bin 실측 교정(사용자 확정 3건)**: historical 2022-01~2026-06(1,620일) 5지점 평균 기상↔실제 전국 이용률(`gen_solar/wind_utilization_kr`) 역산. ① 태양광=경계 유지(0.2/0.4/0.6/0.8, spearman 0.68)+활성도를 기대 이용률로 교정(95%→**61%** 등 12/23/36/49/61) ② 풍력=파워커브 경계(3/6/9/13) 폐기(지점 평균 6년간 ≥9m/s 0일·68%가 "정지 0%" 오표시) → **ASOS 스케일 [2/3/4.5/6 m/s)=11/21/44/72/77%**(spearman 0.75) ③ 청천일사=월별 관측 P97. 강도맵 기준=최대 권역×최상 bin(SA/WA_MAX). **하늘상태 4분류 확정**: 맑음(운량<0.5)/약간흐림/흐림(≥0.85)/비(0.3mm/h, 겨울 눈) — 운량 0.5까지 일사 감쇄 미미(비율~0.7)·0.85부터 급락(0.26) 근거. 주의: 전국 기준 교정을 권역 단일 지점에 적용=**권역 간 상대 신호**(권역별 발전량 데이터 부재의 구조적 한계, 데모 수용).
- **데이터 현황 개편(사용자 사양)**: 컨트롤을 본문 탭 위로(historical/forecast radio + 과거 프리셋 1주~3개월/직접 선택[forecast는 미래 날짜 가능] + forecast 미래 지평 radio) + 탭 3개 — ① **fetcher 요약 히트맵**(계열별 대표 2~3개, `[ASOS 관측] solar_rad_seosan` 라벨: historical=ASOS/sukub/발전실적/DA·SMP/파생 이용률, forecast=KIMG/DA·SMP/서빙 5·6·7) ② **전체 피처 히트맵**(6시간 블록 적재율 0~1, 흰→초록, 행 없는 구간도 reindex로 0% 노출, 현재 시각 빨간 점선) ③ **DB 직접 조회**(기본 선택=fetcher별 대표 1개씩, multiselect). 헬퍼 `common.table_columns/table_range/coverage_heat`, 기존 신선도 요약은 expander. 구 `land_weather_at` 제거.
- **지평별 저장 구조 확인(사용자 질문)**: forecast 테이블=timestamp 단일 키 "최신 발행 스냅샷"(미래 구간 upsert 덮어씀 → 과거 행엔 사실상 D+1 발행분만 잔존). 지평별 이력은 7-A2-A `chained_gas_dataset.parquet`(D+1/2/3/7/12)뿐. DB 보존 원하면 (timestamp, horizon) 이력 테이블+서빙 append 후속 — 데모 검증엔 parquet로 충분.
- **8-A는 미완(사용자 강조 — 핵심 단계)**: 기능은 닫혔으나 디자인 품질 개편 필요. **다음 세션 = frontend-design 플러그인으로 디자인 수정** → 이후 8-B(제주, 선행=제주 서빙 백필).

**2026-06-11 — 8단계 보조: functions.md (1~7단계 CLI·산출물 레퍼런스) + API 매칭 원칙 + 검증 탭**
- 무엇을: 8-A 최종 다듬기에 앞서 `8. streamlit/functions.md` 작성 — 1~7단계 수집기·서빙의 "무엇을 받고 무엇을 DB에 쓰는가" 요약(수집기 2종+fetcher 허브, 제주 2/3/4·전국 5/6/7 서빙, KOGAS 환산).
- 핵심 정리: 단계별 `--days` 의미 차이 표(2-B·5-B·7=정수 범위 / 3·6-C=콤마 지평 목록 / 2-B backfill 기본 no-write), 앱이 읽는 핵심 컬럼 전국·제주 대응표, net_load_kr 오프셋 주의.
- **API 매칭 원칙(사용자 확정)**: ① 예측 조회=하루 단위(00~23시) ② 실측(fetch_kpx_land/fetch_land_power/fetch_kpx_jeju)=실시간 새로고침 가능(표시 전용) ③ 예측=DB 우선·없을 때만 제한 실행 ④ 시각화 주인공=예측 vs 실측 비교.
- **검증 탭 신설(수요 예측 메뉴, 사용자 선택=체인 스택 4행)**: 하루 단위 날짜 네비 + 수요/신재생/net_load/가스 4행 비교(실측 solid·예측 dot, x축 공유) + 패널별 MAPE·MAE·bias 배지 + 최근 30일 오차 추이 expander + 예측 없는 날짜는 "예측 생성" 제한 실행 버튼(서빙 5→6→7 subprocess). **신재생만 nMAE**(심야 분모≈0으로 일별 MAPE 81%까지 폭발 → nMAE 19.4%로 정상화, 6단계 보고서와 동일 처리). 실측은 `fetch_land_power`(가스·신재생)·sukub(수요) live 보강(`land_day_compare`).
- 30일 오차 추이 정합: 수요 3.3%·net_load 6.3%·가스 11.9%(체인 검증 ~13%와 일치).
- **종합 탭 개편(사용자)**: '현황' → **'예측 확인'** 개명. 검증 탭과 동일한 하루 단위 날짜 네비(공용 헬퍼 `day_navigator`, 기본=오늘) + 선택일 24시간 예측 기본 + 예측 없는 날짜 제한 실행 버튼(`missing_forecast_block` 공용화). plot은 **시리즈 8종**(수요/가스/신재생/net_load 각 실측·예측)을 ⚙️ popover 체크박스로 선택(기본 6종 on, net_load off). 실측은 sukub+발전실적 live 보강 — DB가 어제 19시까지여도 오늘 24h 전부 표시됨을 확인.
- **누적(발전 믹스) 보기 추가(사용자 제안=전력거래소식)**: stacked 5그룹 단순화(원전 기저→기타발전[석탄·수력·양수·유류·기타]→가스→태양광+풍력→BTM+PPA 추정) + **총수요 선**(수요는 쌓지 않고 선으로 — 이중계상 방지) + **가스발전 예측 dot 오버레이**(차별점). `land_day_mix` 로더(live 보강 동일). 검증: 06-10 14시 KPX 화면과 정합(원자력 19.1k·BTM+PPA ~16k·총수요 ~80k).
- **발전데이터 탭 분리 + 누적 다듬기(사용자 피드백)**: 누적믹스를 종합>**발전데이터** 별도 탭으로 이동(예측 확인=선 전용 환원, 사용자 "선은 완벽" 확정). ① 색 투명화(rgba 0.45) ② **예측 dot 누적기준 정렬** — 가스 예측=원전+기타 베이스 위, 태양광+풍력 예측=+가스 베이스 위(점선↔실측 띠 윗변 간격=오차) ③ **미수집 절단** — 가스≤0/결측 시간은 면적 미표시(0 수렴 절벽 해결, 오늘은 수집 시각까지만 그려짐) ④ **전력수요 예측 점선 추가** — 총수요 선과 같은 기준이 되도록 `est_true_demand_land`(계량수요 예측+BTM/PPA 추정, 6단계) 사용, 실선은 연한 회청(#455a64)·점선은 밝은 회청(#78909c)으로 조화(5/20 총수요 예측 MAPE 5.0%).
- **장지평 예측 탭 개편(사용자)**: 추상 "D+1~D+N" slider → **시작일 선택(기본 오늘) + 끝 날짜 슬라이더**(라벨 "MM-DD (D+k)"), 범위는 `est_demand_land` 실제 적재 한계에서 동적(cron 밀려도 거짓 범위 없음). **D+12는 보류**(슬라이더+D+12 버튼 안 대신): 5-B 수요 서빙이 D+7까지라 수요 입력이 필요한 가스 체인도 D+7 한계 — **후속 = 5-A2 D+12 모델 서빙 연결 후 확장**. 기상개황 탭은 수정사항 많아 다음 세션 계속(사용자).
- **비교 plot 공통화(사용자)**: 예측 확인·장지평 탭이 같은 컴포넌트(`render_series_compare`, ⚙️ 선택) 사용. 시리즈 8종→**9종**: +**KPX 수요예측(land_est_demand_da, dash 선)** — 전력거래소 하루전 수요예측과 직접 비교(기본 off). 데이터 레이어는 `land_day_compare`→`land_range_compare`(구간 일반화, live 보강은 오늘±3일·미래 제외). 장지평도 과거~오늘 구간은 실측 오버레이. 참고: 로컬 forecast의 land_est_demand_da는 마지막 수집일(06-10)까지만 — 서버 cron 운영에선 매일 갱신.
- **시간 선택 통일(사용자)**: ① 장지평 시작일 **과거 개방**(적재 시작 02-02~, 끝 날짜 슬라이더 최대 14일 창, D+표기는 미래만) ② **수요 예측 메뉴 = 공통 시간 컨트롤**(◀ 전일/날짜[과거 가능]/익일 ▶/오늘/새로고침 + 기간 슬라이더 1~7일)을 4개 탭(전력수요/순수요/천연가스/검증)이 공유 — 검증 탭 자체 네비 제거, 구간 기준 지표로 전환 ③ 전력수요 탭에 **KPX 수요예측(DA) dash** 추가(전력거래소 비교).
- **장지평 지평 모드(사용자 질문 "5/20+14일=??"에서 발견·해결)**: forecast 테이블은 timestamp당 1값이라 과거 구간은 rolling D+1 백필 — "과거 고정 origin 장지평"이 아니었음(중요 정직성 이슈). 해결 = **과거 시작일이면 지평 radio(D+1/2/3/7/12) 모드**: 7-A2-A `chained_gas_dataset.parquet`(지평별 수요·신재생, 2022-01~)에서 읽고 가스는 7-A2 모델 즉석 계산(serve_land_gas 자산 재사용, `land_horizon_compare`). 가스 MAPE 지표로 **지평 평평을 화면에서 입증**(5/20 시작 2주: D+7 발행 12.6% ≈ D+12 12.5%). 미래 시작일은 기존 고정 origin 모드.
- 참고: 사용자가 `9. design` 재구성 중(기존 자산 `old design/` 이동, `renewable_capacity_map.html`·`visual.md` 신규) — weather_map은 두 경로 탐색 + 부재 시 안내로 방어(다음 세션 기상개황 개편 예정).
- **기상개황 인포그래픽(사용자 요청=그래프 대신 지도 한 장)**: `weather_map.py` 신설 — 시도 choropleth(5지점 예보를 IDW로 17개 시도 보간 → 서울 포함 전 국토 커버) + 신재생 중요지역 원(태양광 주황 2025·풍력 청록 2023, `9. design/태양광_풍력_지역별_TOP5.txt` 비중∝크기·진하기) + 수집 5지점/참고 13지점 마커(`reselected_asos_map.html` 좌표). 컨트롤=오늘·내일/변수 3종/시각 slider + 5지점 카드. 시도 경계는 southkorea-maps geojson을 0.24MB로 단순화해 동봉. IDW 검증: 서울 17.1(원주15·서산20 사이)·강원 13.0(대관령10 쪽) — 타당.
- 다음 세션(사용자 지정): **기상개황 + 데이터 현황 수정**(기상개황은 `9. design`의 신규 `renewable_capacity_map.html`·`visual.md` 참조) → 이후 8-B(제주, 선행=제주 서빙 백필).

**2026-06-10 — 8단계 착수: G-15 확정(8-0) + 가스 백필 + 8-A 전국 체인 대시보드**
- 무엇을: `CONCEPT_8-0.md` 기준으로 G-15 5건 확정(§7) 후 8-A 구현. ① 배포=자체 서버(로컬 DB 실시간 읽기) ② brief_ai=Gemini ③ 사전 적재 기본+시연 버튼 병행 ④ 표시 기간=데이터 보유 범위 ⑤ SMP 데모 제외(제주는 net_load까지).
- **데이터 점검·백필**: `est_gas_gen_land`가 2026-06-01 하루(24행)만 적재된 공백 발견 → `serve_land_gas.py backfill 2026-02-01~05-31`(D+1) 적재, 발전량 MAPE 13.02%·bias +3.1%(7-A2-A 13.07% 재현). 제주는 `jeju_est_demand_lh` 컬럼 부재·`est_net_load_jeju_lh` 1주뿐 → **8-B 전에 제주 서빙 백필 필요**.
- **8-A v1**: 단일 `app.py`(기준일 선택 + 체인 차트 스택). 사용자 디자인 개편 요청으로 같은 날 v2로 대체.
- **8-A v2(확정 디자인, 사용자 설계)**: **멀티 페이지(전국/제주, st.navigation)** + 사이드바 radio 메뉴 — **종합**(현황: 일일 송출량+수요실측 solid·가스예측 dot 오늘 24h+KPX sukub 실시간 새로고침(표시 전용)+AI brief 자리 / 기상개황: 간략 / 장지평: slider D+1~7+송출량 합)·**수요 예측**(공용 slider+탭3: 전력수요/순수요/천연가스)·**데이터 현황**(적재·신선도 테이블)·**SMP 예측(제주만, G-15 ⑤ 번복)**. 선 규약 실측=solid·예측=dot. 파일 `app.py`+`common.py`+`page_land.py`+`page_jeju.py`. 상세 `CONCEPT_8-0.md` §3.4.
- **사전 적재(체인)**: origin 2026-06-09에서 5(`--days 7`=D+1..7 범위)→6(`--days 1,..,7`=지평 목록·의미 다름 주의)→7 실행, 06-10~16 168h 적재(가스 평균 17,213MW·송출 439,841TON). 6·7의 `--days` 의미 차이로 1차 실행이 D+7만 적재됐던 것 수정.
- AppTest 검증: 전국 3메뉴(sukub 실시간 수신 확인)·제주 4메뉴 전부 예외 없음, 장지평 합계가 서빙 출력과 일치(439,841TON).
- 다음: 8-B(제주 종합·수요·SMP, 선행=제주 서빙 백필) → 8-C(검증·KOGAS) → 8-D(brief_ai·시연 버튼) → 8-E(배포·시연 영상).

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

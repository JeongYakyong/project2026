# CLAUDE.md — 매 세션 공통 규약 (상세는 PROJECT.md)

## ★ 최상위 규칙 — 한국어 표기 (어떤 일이 있어도 위반 금지)
모든 문서·보고서·주석·대화는 **자연스럽고 정확한 한국어**로만 쓴다. **어려운 한자 표현·일본어·중국어·난해한 조어 절대 금지.** 과거에 이런 표현 때문에 프로젝트를 통째로 엎은 적이 있다(PROJECT.md §0.6, 신뢰와 직결). 예: "막다른 접근", "실패로 확인된 경로"처럼 평이하게 쓴다. 기술 식별자·영문 약어(`net_load`, `SMP`, `LGBM`, `D+1` 등)는 정확성을 위해 그대로 둔다.

## 문서 체계 (SSOT)
- **루트 `PROJECT.md`가 단일 기준 문서(SSOT)** — 목표·단계 상태·Decision Gate·진행 로그. 충돌 시 항상 PROJECT.md 우선.
- `docs/PROJECT_v1.md`·`docs/PROJECT_v2_PRD.md` = 동결 이력(수정 금지). `docs/PROJECT_LOG.md` = §8에서 이관된 과거 진행 로그.
- 단계별 상세 결과는 각 폴더의 `REPORT_*.md`, 서빙 CLI·DB 컬럼 레퍼런스는 `8. streamlit/functions.md`.

## 폴더 지도
`1. data_fetcher_and_db`(수집·DB, 단일 출처) · `2~4. jeju_*`(제주: 수요/신재생/SMP) · `5~7. land_*`(전국: 수요/신재생/가스) · `8. streamlit`(데모) · `9. design` · `98. report only` · `99. others` · `deploy/`(서버 배포). 평면 넘버링 유지 — 폴더 중첩 금지(상대경로 DB 참조가 깨짐).

## 작업 규율 (PROJECT.md §0.6 — 예외 없음)
1. **모델링 전 시계열 EDA 필수**(G-9 게이트) — 주기성·추세·안정성·분포 겹침·입력↔타깃 관계 확인 후 착수.
2. **피처 최종 입력은 반드시 사용자에게 묻고 확정** — 탐색·후보 분석은 자유, 최종 확정은 임의 금지.
3. **단계마다 보고서용 산출물 필수** — 표·그림·요약을 남긴다. 결과를 코드에만 묻어두지 않는다.
4. **notebook 형식 선호** — 과정+결과를 한눈에.
- Decision Gate(§7) 미해결이면 그 작업은 시작하지 않는다(작업 쪼개기 원칙).

## 하드 제약 (재시도 금지)
- **제주 SMP는 제주 데이터만** — 육지 SMP 연계 영구 배제. SMP 점예측·실시간 직접 회귀 등은 실패로 확인된 경로(`4. jeju_smp_forecaster/trial_error.md`).
- **BTM/PPA = market view 확정**(G-14) — 예측 체인(5→6→7)은 계량수요+시장신재생만. BTM/PPA·대체효과는 EDA 전용(7-0b·7-Ar·7-B).
- **수집 실행은 crontab/서버에서만** — 대화에서 수집 트리거 금지(API 한도 보호).
- 7-A2에 원자력 피처 추가 금지(covariate shift로 악화 확인, 2026-06-06).

## 함정 모음
- **서빙 CLI `--days` 의미가 단계마다 다름**: 2-B·5-B·7=D+1..N 정수 범위 / 3 하이브리드·6-C=콤마 지평 목록(`--days 1,2,7`) / 2-B backfill은 기본 no-write(`--write` 필요). 상세 표=`8. streamlit/functions.md`.
- **DB 단위**: `radiation`=MJ/m²·h(W/m² 아님) · `total_cloud`=0~1 비율(0~10 아님).
- **Windows 한글 인코딩**: `json.dump`·파일 쓰기에 `encoding='utf-8'` 명시(기본 cp949). 일부 원천 CSV는 euc-kr.
- **지평 평가의 낙관편향**: 24배수 지평만 보면 origin(23:00) 한 시각만 평가됨 — 반드시 D+n 24h 블록(전 시각)으로 평가.
- forecast 테이블은 timestamp 단일 키 "최신 발행 스냅샷"(과거 행=사실상 rolling D+1). 지평별 이력은 `forecast_runs` 테이블·`chained_gas_dataset.parquet`.
- 서빙 기상 폴백 순서: forecast → 시간 보간(limit 4h, 외삽 금지) → (월,시) 기후값(최후수단).

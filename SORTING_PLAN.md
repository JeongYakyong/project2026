# SORTING_PLAN.md — project2026 마감 정리 계획 (세션 간 인수인계 문서)

> **목적**: 공모전 1차 탈락(RETROSPECTIVE.md)으로 프로젝트를 마감하되, 재사용 가치가 있는 핵심 자산만
> `C:\Users\bjkim\Desktop\project2026_sorted`로 복사해 깨끗한 새 git 저장소로 만든다.
> **원본 project2026은 어떤 파일도 수정·삭제하지 않는다(읽기 전용).**
>
> **사용법**: 새 세션은 이 파일 하나만 읽으면 재조사 없이 이어서 작업할 수 있다.
> 각 세션이 끝나면 §1 체크박스와 "진행 메모"를 갱신한다.
> 이 파일 자체는 git에 커밋하지 않는다(원본 쪽 작업 문서).

작성: 2026-07-13 (세션 1). 조사 근거: 탐색 에이전트 4회 — 전체 인벤토리 + cron→sh→진입 .py→로드 파일까지 서빙 의존성 전수 추적.

---

## 0. 확정된 결정 사항 (사용자 확인 완료, 재질문 불필요)

1. **모델 가중치(.pth/.pkl/lgbm .txt, 현역 ~450MB)** = sorted에 **로컬 복사하되 git에서는 제외**(.gitignore). sorted 폴더 자체는 바로 실행 가능, GitHub에는 코드+문서만.
2. **폴더 구조** = 기존 넘버링(`1. data_fetcher_and_db` ~ `10. citygas_forecaster`) **그대로 유지**. 코드 곳곳에 폴더명이 상대경로로 박혀 있어 이름을 바꾸면 실행이 깨진다. 내용물만 핵심으로 추린다.
3. **공모전 제출물** = **전부 제외**. 신청서 PDF/HWP(`98. report only`), 루트 pptx 3개. 원본 폴더에만 보관.
4. **폐기 실험 REPORT md(~30개)** = 코드·데이터는 버리되 보고서 md만 **`docs/archive/`로 모아 보존**.

## 1. 세션 로드맵

- [x] **세션 1 (2026-07-13)** — 전체 조사 + 이 계획 문서 작성
- [x] **세션 2 (2026-07-14) — 복사 1차**: sorted 폴더 생성 → 루트 문서·docs(archive 포함)·폴더 1~4(수집+제주 파트) 복사 (§2·§3 매니페스트대로)
- [x] **세션 3 (2026-07-14) — 복사 2차**: 폴더 5~10·9. design·deploy 복사 + 신규 .gitignore 생성(§5 전문 그대로) + 로컬 전용(DB·.env·가중치) 복사 확인
- [x] **세션 4 (2026-07-14) — 검증**: import 스모크 → 실서빙 1회(§6) → 누락 보완. (★git init+최초 커밋은 사용자 지시로 목록에서 제외·보류(2026-07-14) — 시점은 추후 사용자가 결정. 세션 6 push 전에는 필요하므로 그때 §6-4 미노출 확인과 함께 수행)
- [ ] **세션 5 — md 문서 정리**: sorted 최상위 README.md 신규 작성(소개·아키텍처·실행법), PROJECT.md(139KB) 처리 방향 결정(사용자와), functions.md 정합 점검. ★**리팩토링(sorted의 `REFACTOR_PLAN.md` R1~R5) 완료 뒤로 순연**(2026-07-14 결정) — 폴더명·경로가 확정돼야 README를 한 번만 쓴다
- [ ] **세션 6 — 메모리 정리 + 기타**: Claude 메모리(~30개) 프로젝트 종료 반영 정리, GitHub 원격 생성·push(사용자와), 기존 project2026 원격·서버(pull 미러) 운영 지속 여부 결정. ★git init은 REFACTOR_PLAN R1에서 실행하기로 변경(2026-07-14) — push만 여기서

> ★2026-07-14 추가: sorted에서 **구조 변경+서빙체인 리팩토링**을 먼저 진행하기로 함(폴더 리네임 `0N_` 형식·refdata/·project_paths.py·체인 가독성 리팩토링). 계획 SSOT = **sorted 루트 `REFACTOR_PLAN.md`** — 그쪽 작업은 그 파일만 읽으면 됨.

### 진행 메모 (세션마다 추가)
- 2026-07-13 세션 1: 조사 완료·계획 확정. 아직 sorted 폴더 미생성.
- 2026-07-14 세션 2: 복사 1차 완료. sorted 생성 후 매니페스트 135개(동일경로 101 + archive 34) 전량 복사 — 사전 검증에서 누락 0. 루트 문서 6·docs 동결 4·폴더 1(core 15 + second_dataset 9 + 문서 9 + 로컬 전용 DB 6·.env)·폴더 2(7)·폴더 3(27)·폴더 4(17) + `docs/archive/` 34개(새 이름 규칙 적용) + 목차 README.md 신규 작성(출처·한 줄 설명 표). 현재 sorted 총 136파일·255MB(폴더1 160M·폴더3 90M — DB·가중치 포함). 원본 git status 무변경 확인. 복사 스크립트는 세션 스크래치(`session2_copy.sh`) — 세션 3은 §2 폴더 5~10·9. design·deploy + §5 .gitignore 생성 + §3 잔여(7. parquet 3종·9. design/common CSV 3종)부터.
- 2026-07-14 세션 3: 복사 2차 완료. 244개 전량 복사(사전 존재 검증·사후 크기 대조 모두 통과) — 폴더 5(32)·6(25)·7(18: git 대상 15+§3 parquet 3)·8(13)·9(128: 루트 4+지도 json 1+report 123)·10(15)·deploy(13). §5 .gitignore 전문 그대로 sorted 루트에 생성. 로컬 전용 확인 완료: DB 6종·.env·가중치(.pth/.pkl/lgbm .txt)·parquet 3종·report CSV(한국가스공사 3종은 `9. design/report/common/`에 있었음 — §3의 "9. design/common"은 이 경로를 뜻함). 현재 sorted 총 381파일·607MB. 원본 git status 무변경 확인. 참고 3건: ① report/는 "전체" 규칙대로 복사하되 중복 4개만 제외(`복사본` 1, `(1)` 3) — 단 `asia_lng...(1).html`·`pipeline_overview3 (1).html`은 (1) 없는 원본이 없어 sorted에는 미포함(원본 폴더에는 그대로 있음). ② 세션 1 조사 이후 stage7에 추가된 산출물(step7_perf·gas_corr·bias_lowload_2026·cause_demand_curve·calib_validation + CSV 4종)도 "report/ 전체" 규칙으로 포함했음. ③ `5./training/demand_lt/calibrate_lt.py`(calib_lt.json 재현 스크립트)는 매니페스트에 없어 복사 안 함 — 재현 스크립트 성격이라 세션 4~5에서 포함 여부 판단 권장. 복사 스크립트는 세션 스크래치(`session3_copy.sh`+`session3_filelist.txt`). 세션 4는 §6 검증(import 스모크→실서빙 1회→git init, ★수집기 실행 금지·deploy .sh는 `git update-index --chmod=+x`)부터.
- 2026-07-14 세션 4(검증만 — git init은 사용자 지시로 보류): **누락 보완 0건, 전부 통과.** ① import 스모크 17종 전체 통과 — 체인·서빙 4(전국·제주·SMP·도시가스)·수집기 3(import만, 실행 안 함)·streamlit 10. 스모크 요령 2가지: 수집기는 스크립트 폴더가 sys.path에 있어야 통과(실제 실행 `python 경로/스크립트.py`와 같은 조건 — 루트 기준 runpy로 돌리면 가짜 실패), `page_land.py`는 임포트·파일 로드 전부 성공 후 D+12 팝업(`@st.dialog`)이 streamlit 런타임 밖이라 예외로 끝남(streamlit run에서는 정상 — 통과로 판정). ② 실서빙 4회 전부 성공, 0행 없음: 도시가스 12행(D+1~12)·제주 체인 168행(D+1~7)·전국 체인 286행(D+1~12, 수요 v4 15지평+보정표 216셀+가스 v3 로드 확인)·제주 SMP 48행(D+1·2). 가중치·화이트리스트 CSV·지도 json·import 시점 로드(model_meta 등) 전부 정상. ③ 안전 확인: 원본 project2026 DB 6종 mtime/size 무변경(스냅샷 대조), 서빙 산출은 sorted 쪽 DB에만 기록(est_horizon_* 최신 base 1건씩 추가 — 무해), 원본 git status 무변경. 남은 것: git init+최초 커밋+§6-4(.env·가중치 미노출, CSV 7종 노출 확인)+deploy .sh chmod — push 결정(세션 6) 때 함께. 다음은 세션 5(md 문서 정리).

## 2. 복사 매니페스트 — git 추적 대상

> 복사는 PowerShell(Copy-Item/robocopy)로, 경로에 공백·점이 있으니 반드시 따옴표.
> 디렉토리 구조는 원본과 동일하게 재현. 여기 없는 파일은 복사하지 않는다.

### 루트
- `PROJECT.md`, `CLAUDE.md`, `RETROSPECTIVE.md`, `project_original.txt`, `.gitattributes`
- `.streamlit/config.toml` (루트 복제본 — 실행 위치가 달라도 적용되도록 둔 것)
- `.gitignore`는 복사하지 말고 §5의 신규본으로 생성

### docs/
- 기존 4개: `PROJECT_LOG.md`, `PROJECT_LOG2.md`, `PROJECT_v1.md`, `PROJECT_v2_PRD.md` (동결 이력)
- 신설 `docs/archive/` — §4의 REPORT md 회수 목록 + 목차 `README.md`(각 파일이 어느 폴더에서 왔고 왜 기각됐는지 한 줄씩)

### 1. data_fetcher_and_db
**core/ (수집 파이프라인 — import 그래프로 확정한 15개):**
- 현행 cron 진입점: `collect_forecast_new.py`, `collect_data_land_new.py`, `collect_data_jeju.py`
- 라이브러리(cron에서는 폐기지만 위 진입점들이 import — 파일 필수): `collect_data_land.py`, `collect_forecast_runs.py`, `collect_data_jeju_new.py`
- 공용 모듈: `api_fetchers_land.py`, `api_fetchers_jeju.py`, `api_fetchers_kim2.py`, `_common.py`, `postprocess.py`
  (`postprocess.py`는 서빙 체인도 동적 import — serve_chain_land_new.py:54)
- v2 컷오버 대기 세트: `collect_forecast_v2.py`, `core/temp/backfill_frcc_cols.py`(crontab 선택 줄이 참조)
- 수동 보수 도구: `backfill_jeju_forecast.py`, `collect_l010_archive.py`

**second_dataset/:**
- 런타임 화이트리스트 CSV 4종(이름 정확히): `kr_elec_capa.csv`, `ppa_scale.csv`, `한국가스공사_도시가스 민수용 일별 유효일수_20210901.csv`, `한국가스공사_도시가스 산업용 일별 유효일수_20210901.csv`
- 빌드 스크립트+문서: `build_dataset.py`, `make_dictionary.py`, `fit_merit_split.py`, `README.md`, `AUDIT_REPORT.md`

**기타:** `REPORT_forecast_v2.md`(컷오버 절차서), `requirements.txt`, `.env.example`, `datalist.txt`, `new_kma/REPORT_01_신규정책_요약.md` ~ `REPORT_05_kma_new_EDA.md` 5개(md만 — 실험물·nc·캐시는 제외)

### 2. jeju_demand_forecaster
- `serve_jeju_demand_lh.py` (제주 체인 2단계 — build_horizon_backtest_jeju.py:43이 로드)
- `model/models/lgbm_jeju_demand_direct.txt` + `model_meta_direct.json` (현역 모델+메타)
- `model/_build_2a.py` (위 모델 재현 스크립트)
- `data/jeju_ppa_btm_capacity_mw.csv` (런타임 화이트리스트)
- `INPUT_SPEC.md`, `README.md`

### 3. jeju_solarwind_forecaster
- 서빙: `serve_chain_jeju_new.py`(cron 진입점), `serve_solarwind_hybrid.py`, `serve_solarwind_lgbm.py`, `solarwind_db_pipeline.py`
- `training/build_horizon_backtest_jeju.py` (체인이 `_imp`로 로드 — 숨은 의존성)
- `training/solarwind_raw_jeju.csv` (런타임 화이트리스트 — 빠지면 3단계 전체가 FileNotFoundError로 죽은 사고 이력)
- 재현 도구: `training/fit_wind_qm.py`, `training/export_solarwind_csv.py`
- 가중치 `solarwind_models/` **5개 전부**: `metadata.pkl`, `MinMax_scaler_solar.pkl`, `MinMax_scaler_wind.pkl`, `best_patchtst_solar_model.pth`, `best_patchtst_wind_model.pth` (wind pth는 예측엔 미사용이나 load_assets가 로드 — 없으면 크래시)
- 가중치 `solarwind_patchTST_pkl/`: `best_patchtst_solar_model_D2.pth`~`D7.pth` **solar 6개만** (wind D2~D7 6개는 하이브리드가 wind=LGBM이라 미사용 — 제외)
- `lgbm_models/` 5개: `feat_meta.json`, `lgbm_solar_util.txt`, `lgbm_wind_util.txt`, `tcog_postproc.json`, `wind_qm.json` (`*_pre_simplify*`·`*_exp_east*`는 제외)
- 문서: `README.md`, `training/REPORT_wind_qm.md`(현역 wind_qm.json 설명), `requirements.txt`

### 4. jeju_smp_forecaster
- 서빙: `serve_smp_horizon_jeju.py`(cron 진입점), `smp_db_pipeline.py`, `smp_d2_pipeline.py`, `train_smp_db.py`(공용 로더)
- `training/` 서빙 import 3종+보정: `train_binary_smp.py`, `train_smp_d2_da.py`, `smp_phase2_depth.py`, `smp_calibrate.py`
- 가중치 `models_weight/` 4개: `smp_binary.pkl`, `smp_d2_da.pkl`, `smp_depth_lookup.json`, `smp_calibrator.pkl`
- 문서: `REPORT_smp_horizon_validation_jeju.md`, `smp_step4_report.md`, `추가작업_report.md`, `trial_error.md`(★하드 제약 기록 — CLAUDE.md가 참조, 반드시 포함), `requirements.txt`

### 5. land_demand_forecaster
- `model/exp_features.py` (★serve_chain_land_new.py:50이 import — 폴더 내 유일한 현역 model/ 파일)
- `training/demand_lt/` — 현역 수요 모델 전체:
  - `model_lt.py`, `train_lt.py`, `finetune_lt.py`, `eval_land_new.py`, `serve_land_new.py`
  - `weights/` 19개: `best_lt_D1.pth`~`best_lt_D15.pth`, `metadata_lt.pkl`, `scaler_exog.pkl`, `calib_lt.json`, `metadata_ft.json`, `FINETUNE_NOTE.md`
  - 문서: `ARCHITECTURE_lt_v4.md`, `REPORT_lt_v2.md`, `README.md`, `eda_scaler/REPORT_demand_solar.md`, `eda_scaler/REPORT_stl_scaler.md` (md만 — eda_scaler 데이터는 제외)
- 폴더 `README.md`

### 6. land_solarwind_forecaster
- `serve_solarwind_land.py` (체인+build_horizon_backtest가 import)
- `training/landsolar504/` 17개: `best_patchtst_landsolar_D1.pth`~`D15.pth`, `metadata_landsolar.pkl`, `scaler_landsolar.pkl`
- `model/models/` 4개: `lgbm_land_solar_final.txt`, `lgbm_land_wind_final.txt`, `lh_final_meta.json`, `btm_ppa_recon_6a2.json`
- 재현: `training/_train_lgbm_lh.py`, `training/_gen_lgbm_lh.py`
- `README.md`

### 7. land_gas_forecaster
- `serve_chain_land_new.py` (★전국 체인 cron 진입점), `serve_land_gas.py`
- `training/build_horizon_backtest.py` (★숨은 의존성 — exp_features.py가 동적 import)
- `model/`: `lgbm_land_gas_v3.txt`, `model_meta_gas_v3.json`(import 시점 로드), `gas_serving_calib.json`(관리자 메뉴가 읽고 씀), 롤백 보존 `lgbm_land_gas_v2.txt`+`model_meta_gas_v2.json` (foldC 2종은 제외)
- **`model/tab/7c_monthly_price_cost.csv`** — ★조사에서 발견한 **7번째 런타임 CSV**(기존 .gitignore 화이트리스트 누락분). common.py:21 단가 환산이 읽음 — 없으면 streamlit 단가 표시·AI 브리핑·API 죽음. §5 화이트리스트에 추가했음.
- 재현: `training/train_gas_v3.py`
- 문서(현행 모델 관련 — 제자리 유지): `training/REPORT_7-blend_off.md`, `REPORT_7-regime_shift_2026.md`, `REPORT_7-v3_retrain.md`, `REPORT_newchain_revalidation.md`, 폴더 `README.md`

### 8. streamlit
- 앱 10개: `app.py`, `page_land.py`, `page_jeju.py`, `common.py`, `brief_ai.py`, `brief_store.py`, `gas_price_store.py`, `gen_briefs_land.py`, `serve_api.py`, `weather_map.py`
- `.streamlit/config.toml`, `functions.md`(서빙 CLI·DB 컬럼 레퍼런스), `CONCEPT_8-0.md`
- 제외: `old_gemini.py`(import 0건+의존 모듈 부재로 실행 불가), `새 폴더/`(빈 폴더)

### 9. design
- `drawing_rule.md`(다이어그램 SSOT), `visual.md`
- `report/` 전체 — `공모전_제출보고서_초안.md`, `stage1/`·`stage5/`·`stage6/`·`stage7/`·`stage8/`·`stage10/`·`common/`의 html·png·렌더 py (단 `복사본`·`(1)` 붙은 중복 파일은 제외)
- **`old design/skorea_provinces_simplified.json`** — ★weather_map.py의 실존 유일 지도 폴백. `old design/` 나머지는 다 버리되 이 json만 **같은 경로**(`9. design/old design/`)로 복사
- `data_sources.html`, `renewable_capacity_map.html`
- 제외: `old design/` 나머지(7.4MB), `citygas_template.pptx`, `_test_weather_tab.html`

### 10. citygas_forecaster
- `serve_citygas_daily.py`(cron 진입점), `build_citygas_daily.py`, `model_params.json`, `_report_numbers.json`
- `REPORT_citygas_daily.md`, `MODEL_SUMMARY.md`, `fig/` 전체

### deploy (13개 중 11개)
- 현행 9: `run_collect_forecast.sh`, `run_collect_land_new.sh`, `run_collect_jeju.sh`, `run_serve_chain_land.sh`, `run_serve_chain_jeju.sh`, `run_serve_smp_jeju.sh`, `run_serve_citygas.sh`, `run_gen_briefs.sh`, `run_serve_api.sh`
- 준비됨 2: `run_collect_forecast_v2.sh`(컷오버 대기), `run_collect_l010.sh`
- `crontab.example`, `DEPLOY.md`
- 제외 2: `run_collect_land.sh`, `run_collect_runs.sh` (crontab이 "제거할 것" 명시 — 대상 .py는 라이브러리로 이미 포함)
- ★주의: .sh는 실행권한(+x) 이슈 이력 있음 — 세션 4에서 `git update-index --chmod=+x` 적용

## 3. 복사 매니페스트 — 로컬 전용 (git이 무시, 실행용)

- `1. data_fetcher_and_db/data/`: `input_data_land.db`(105M), `input_data_jeju.db`(51M), `ai_briefings.db`, `gas_tariff.db`(브리핑·단가 이력), `v2_land.db`, `v2_jeju.db`(v2 격리 지평 아카이브)
- `1. data_fetcher_and_db/.env` — ★API 키(KMA_API_KEY+_SUB들, KPX_API_KEY, GEMINI_API_KEY). **절대 git에 들어가면 안 됨** — 복사 후 `git status`로 미노출 확인
- §2에 적힌 가중치 전부(.pth/.pkl/lgbm .txt — 복사 대상이지만 §5 규칙으로 git이 무시)
- `7. land_gas_forecaster/training/newchain_gas_sealed.parquet`, `newchain_gas_backtest.parquet`, `newchain_gas_sealed_g28.parquet` (봉인 검증셋 ~2.3MB)
- `9. design/common/`의 한국가스공사 원본 CSV 3종 (report 그림 재현용)

## 4. docs/archive/ 회수 목록 (기각 실험 REPORT md — 원 경로 → 새 이름)

새 이름 규칙: `<폴더번호>_<원파일명>` (출처 추적 가능하게). 목차 README.md에 한 줄 설명 붙임.

- `2. jeju_demand_forecaster/eda/REPORT_2-0_eda.md`, `eda/REPORT_2-0b_residual_btm.md`, `model/REPORT_2-A.md`
- `3. jeju_solarwind_forecaster/comparison/REPORT_3cmp-0_eda.md`, `REPORT_3cmp-2_forecast_only_vars.md`, `REPORT_3cmp-B_comparison.md`, `REPORT_3cmp-G_hybrid.md`, `training/REPORT_horizon_diagnosis_jeju.md`
- `5. land_demand_forecaster/nouse/eda/REPORT_5-0_eda.md`, `REPORT_5-0b.md`, `nouse/model/REPORT_5-A.md`, `REPORT_5-A2.md`, `REPORT_5-A_v2.md`, `nouse/training/REPORT_5-B.md`
- `6. land_solarwind_forecaster/nouse/REPORT_6-C.md`, `nouse/eda/REPORT_6-0_eda.md`, `nouse/model/REPORT_6-A.md`, `REPORT_6-A2.md`, `REPORT_6-B.md`
- `7. land_gas_forecaster/nouse/baseline/REPORT_baseline.md`, `nouse/eda/REPORT_7-0_eda.md`, `REPORT_7-0b_btm_ppa.md`, `REPORT_7-B_eda.md`, `nouse/model/REPORT_7-A.md`, `REPORT_7-A2.md`, `REPORT_7-A2-A.md`, `REPORT_7-B.md`, `REPORT_7-C.md`, `REPORT_7_irreducible.md`, `REPORT_7_v2.md`, `nouse/procurement/REPORT_procurement.md`, `nouse/training/REPORT_7-D_direct_vs_chain.md`, `REPORT_horizon_diagnosis.md`
- `99. others/neveruse/DATA_CATALOG.md` (원천 데이터가 원본 폴더에만 남는다는 포인터 역할 — README에 명시)

제외(회수 안 함): 작업지시 메모류(`smp_step4_instruction.md`, `추가작업.md`, `WORKORDER_procurement_*.md`, `file_inspect.md` 등), `no use/` 안 README들.

## 5. 신규 .gitignore 전문 (세션 3에서 이대로 생성)

```gitignore
# ===== Secrets =====
.env
.env.*
!.env.example

# ===== Databases (대용량, collect_data_*.py 로 재생성 가능) =====
*.db
*.db.bak*
*.sqlite
*.sqlite3

# ===== Generated datasets / data dumps =====
*.parquet
*.csv
*.xlsx
*.xls
*.zip
*.pptx

# ===== 모델 가중치 (로컬 보관 · git 제외 — 재현은 각 폴더 training 스크립트) =====
*.pth
*.pkl
lgbm_*.txt

# ===== 런타임 서빙 필수 정적 참조표 (위 *.csv 무시의 예외) =====
# 서버 cron/streamlit 서빙체인이 읽는 작은 참조 CSV. 빠지면 FileNotFoundError 로
# 매 지평이 조용히 버려져 "산출 없음"(0행)이 된다. 학습용 대용량 CSV 는 계속 무시.
!1. data_fetcher_and_db/second_dataset/kr_elec_capa.csv
!1. data_fetcher_and_db/second_dataset/ppa_scale.csv
!1. data_fetcher_and_db/second_dataset/한국가스공사_도시가스 민수용 일별 유효일수_20210901.csv
!1. data_fetcher_and_db/second_dataset/한국가스공사_도시가스 산업용 일별 유효일수_20210901.csv
# 제주 2·3단계 체인 서빙 런타임 참조 (serve_chain_jeju_new → est_horizon_jeju).
!2. jeju_demand_forecaster/data/jeju_ppa_btm_capacity_mw.csv
!3. jeju_solarwind_forecaster/training/solarwind_raw_jeju.csv
# 가스 단가 환산표 — streamlit(common.gas_tariff_by_month)·AI 브리핑·API 가 읽음.
# (2026-07-13 정리 조사에서 발견된 7번째 런타임 CSV — 구 저장소에선 화이트리스트 누락이었음)
!7. land_gas_forecaster/model/tab/7c_monthly_price_cost.csv

# ===== Submission / binary docs =====
*.hwpx
*.hwp

# ===== Python =====
__pycache__/
*.pyc
*.pyo
*.pyd
.ipynb_checkpoints/
*.egg-info/
.venv/
venv/
env/

# ===== OS =====
Thumbs.db
desktop.ini
.DS_Store
~$*
```

## 6. 검증 절차 (세션 4)

1. **★수집기(collect_*)는 절대 실행 금지** — API 호출 한도 보호(CLAUDE.md 하드 제약). import 확인만.
2. import 스모크 테스트 (sorted 폴더 기준, 각 폴더에서 `python -c "import ..."` 또는 spec 로드):
   - `7./serve_chain_land_new`, `3./serve_chain_jeju_new`, `4./serve_smp_horizon_jeju`, `10./serve_citygas_daily`
   - streamlit: `app`, `page_land`, `page_jeju`, `common`, `brief_ai`, `serve_api`, `weather_map`
   - core: `collect_forecast_new`, `collect_data_land_new`, `collect_data_jeju` (import만!)
   - import 시점 로드(model_meta_gas_v3.json 등) 누락이 여기서 잡힘
3. 실서빙 1회 (로컬 DB 사본에 쓰므로 안전 — 원본·서버 DB 무접촉):
   - 가벼운 순서로 `serve_citygas_daily` → `serve_chain_jeju_new` (시간 되면 `serve_chain_land_new`도)
   - 런타임 load_assets 누락(가중치·화이트리스트 CSV·지도 json)이 여기서 잡힘. **0행 산출도 실패로 간주**(조용한 FileNotFoundError 삼킴 이력)
4. `git init` 후 `git status`에서 확인: `.env`·`*.db`·가중치(.pth/.pkl/lgbm_*.txt) **미노출**, 화이트리스트 CSV 7종 **노출**
5. 원본 project2026 무변경: 원본 쪽 `git status`가 (SORTING_PLAN.md 신규 외) clean 유지
6. 예상 결과 규모: git 추적 ~300파일 미만 / 코드+md+그림 ~40MB, 로컬 총 ~850MB

## 7. 제외 확정 목록 (근거 요약 — 복사하지 않는 것들)

| 대상 | 근거 |
|---|---|
| `98. report only/` 전체, 루트 pptx 3개 | 사용자 결정(제출물 제외). `jeju_energy(use carefully).db` 포함 — 원본에만 |
| `99. others/` 전체(DATA_CATALOG.md만 회수) | 원천 데이터·EDA 보관소. neveruse/ 45MB 등 |
| `5./serve_demand_patch.py`, `training/landdemand_final336/`(166MB), `model/models/lgbm_land_demand_v2hum.txt`+`model_meta_v2hum.json`(36MB) | 호출 0건 확정 — 현역은 demand_lt v4 단일. 코드 주석도 "하이브리드 폐기" 명시 |
| `5./training/demand_lt/weights_v4_orig/`(162MB) | weights/의 파인튜닝 이전 순수 중복 백업 |
| 폴더 5·6·7 `nouse/`(총 385MB), 폴더 3·4 `no use/`(25MB), `solarwind_direct/`(빈 폴더) | 명시적 폐기 표식. REPORT md만 §4로 회수 |
| `1./data/`의 `*.bak*`·`bf_*`·`cur_*`·`dryrun_*` DB, `temp_DB/`(158MB) | 검증 잔재·백업 — 현행 DB 6개만 §3으로 |
| `1./core/temp/` 나머지(마이그레이션·검증 일회성), `1./new_kma/` 실험물(.nc·probe_cache·results·ipynb) | 완료된 일회성 작업. REPORT 5개만 보존 |
| `3./solarwind_patchTST_pkl/`의 wind D2~D7 pth 6개 | 하이브리드는 wind=LGBM — 코드가 solar D2~D7만 로드 |
| `7./model/lgbm_land_gas_v3_foldC.txt`+meta, `powerDemandPerform_2026-06.xlsx` | 서빙 미로드 |
| 실험 노트북 전체(ipynb ~45개), `eda/`·`comparison/`·`model/` 실험 스크립트·fig·tab | 결과는 REPORT md에 요약됨 |
| `8./old_gemini.py`, `새 폴더/` | 실행 불가 코드·빈 폴더 |
| `9./old design/`(json 1개 제외), `citygas_template.pptx`, 중복 html | 구버전 디자인 |
| 외부 스킬 폴더 3개(`claude-code-skills/` 등), `.claude/` | 프로젝트 코드 아님 |
| `docs/` 외 위치의 `__pycache__/` 전부 | 캐시 |

## 8. 남은 결정 사항 (해당 세션에서 사용자에게 물을 것)

- **세션 5**: PROJECT.md(139KB·574줄) 처리 — 그대로 보존 vs 요약본 새로 쓰고 원본은 docs/로 이동. sorted README.md의 어조·독자 수준(메모리 "Report visual audience level" 참고).
- **세션 6**: GitHub 원격 이름·공개 여부. 기존 project2026 원격(1.8GB 히스토리)과 서버 pull 미러 운영 지속 여부 — ★서버는 기존 repo를 pull하므로 새 repo로 갈아타려면 서버 쪽 전환 작업 별도 필요. Claude 메모리 정리 범위.

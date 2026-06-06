# 5. land_demand_forecaster (육지/전국 수요 예측) — 미구현(골격)

> 제주 `2. jeju_demand_forecaster`의 육지(전국) 대응 폴더. 아직 모델 코드는 없고 폴더 골격만 있다.

## 목표
전국 계통수요(D+1, 24시간)를 예측한다. 제주 수요 예측기와 동일한 구조(PatchTST 신호 + LGBM)를 따른다.

## 입력 / 출력 (예정)
- 입력: `1. data_fetcher_and_db/data/input_data_land.db`
  - historical: `real_demand_land`, 전국 기상(다지점), `day_type`
  - forecast: 전국 기상 예보(D+1 24h)
- 출력: forecast 테이블에 `est_demand_land`(가칭) UPSERT

## 참고
- 미러 대상 코드: `2. jeju_demand_forecaster/` (`demand_db_pipeline.py`, `patchtst_lgbm_train_db.py`)
- 학습/검증 데이터: `1. data_fetcher_and_db/second_dataset/data/land_train|val|test.parquet`
- 착수 전 루트 `PROJECT.md`의 해당 단계 Decision Gate를 먼저 확인할 것.

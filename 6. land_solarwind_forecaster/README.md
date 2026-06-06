# 6. land_solarwind_forecaster (육지/전국 신재생 → net_load) — 미구현(골격)

> 제주 `3. jeju_solarwind_forecaster`의 육지 대응 폴더. 폴더 골격만 있다.

## 목표
전국 태양광·풍력 발전을 예측해 `net_load`(잔여부하 = 계통수요 − 신재생)를 산출한다.

## 입력 / 출력 (예정)
- 입력:
  - `1. data_fetcher_and_db/data/input_data_land.db` (historical 신재생 실측·설비용량, forecast 기상)
  - `5. land_demand_forecaster` 출력(전국 수요 예측)
- 출력: forecast 테이블에 `est_net_load_land`(가칭) 등 UPSERT
- 참고: 전국 DB에는 `net_load_kr`, `gen_solar_*`, `gen_wind_kr` 실측이 있어 검증이 쉽다.

## 참고
- 미러 대상 코드: `3. jeju_solarwind_forecaster/` (`solarwind_db_pipeline.py`, `training/`)
- 착수 전 루트 `PROJECT.md`의 해당 단계 Decision Gate를 먼저 확인할 것.

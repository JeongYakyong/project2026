# 7. land_gas_forecaster (net_load → 발전용 가스수요) — 미구현(골격) ★ 새 명제의 핵심

> 제주에는 SMP 단계(`4. jeju_smp_forecaster`)가 있지만, 전국은 실시간 시장이 없어 SMP 예측 대상이 아니다.
> 대신 전국은 **net_load → 가스 발전량(`gen_gas_kr`) 예측**이 검증의 핵심이다. 전국은 가스 발전량 실측이 존재해 가장 엄밀한 증거가 된다.

## 목표
- `net_load → 가스 발전량(LNG)` 예측 모델. 전국은 `gen_gas_kr`(실측)을 정답으로 정직하게 검증한다.
- 예측한 가스 발전량을 KOGAS 단가·수입가로 환산해 **발전용 가스 수요·비용**을 산출한다(산업통상부 자격 앵커).

## 입력 / 출력 (예정)
- 입력: `1. data_fetcher_and_db/second_dataset/data/land_train|val|test.parquet`
  - 피처: `net_load`(real/est), 달력(hour·dow·month·day_type), 기온, 계절·연도추세
  - 타깃: `gen_gas_kr` (가스 발전량 실측)
- 금지 피처(누수원): HVDC, 유류 발전, 타깃 lag 등 — `second_dataset`의 데이터 딕셔너리에서 `forbidden`으로 라벨링됨
- 출력: 가스 발전량 예측 + 가스수요/비용 환산 결과

## 참고
- 데이터 준비: `1. data_fetcher_and_db/second_dataset/` (`build_dataset.py`가 `land_*.parquet` 생성)
- 제주 probe 대응: 같은 모델을 제주 2020–2024 `only_gen` 실측으로도 학습/검증한다. 즉 이 단계는 제주·전국을 함께 다루는 교차-지역 작업이며, 명칭만 land 폴더에 둔 것이다.
- 착수 전 루트 `PROJECT.md`의 방법론(데이터 분리·누수 차단)과 Decision Gate를 먼저 확인할 것.

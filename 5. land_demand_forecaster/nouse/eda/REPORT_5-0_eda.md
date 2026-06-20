# 5-0 EDA 요약 — 전국 수요 예측 (G-9)

## 데이터
- 타깃 real_demand_land: 2020-01 ~ 2026-06-05, 56,352행. 결측 300(시간보간), 0값 없음. 33k~97k MW.
- 베이스라인 land_est_demand_da(KPX 하루전): 연도별 MAPE 5.0~6.0% (2026 5.29%). 이걸 이기는 게 목표.
- 학습창: train 2020-2024 / val 2025 / test 2026(1~6월 부분, ~3,744행).

## 시계열 구조
- 강한 일주기/주주기/계절성. 시간 자기상관 lag24=+0.778, lag168=+0.836.
- 기온↔수요 U자(냉난방). 5지점 평균기온↔수요 상관 -0.018.
- 연도별 레벨 표류는 비교적 완만(연평균 6.1만~6.6만 MW) → 강한 레짐 단절 없음.

## 서빙 제약 (예보에 있는 변수만 입력 가능)
- 서빙 가능(O): temp_c, solar_rad, wind_spd, total_cloud, midlow_cloud (5지점 평균)
- 서빙 불가(X): humidity, rainfall, snow_depth  ← forecast 테이블에 없음 (제주와 차이: 제주는 습도 있었음)
- day_type, land_est_demand_da 는 forecast 에도 존재.

## train↔test 분포
- 2026 test 가 train 분포 안에 안전히 겹침(외삽 미미) → 정직한 검증 가능.

## 다음 단계 결정거리 (사용자 확정 필요, §0.6)
1. 모델 구조: (A) 제주처럼 PatchTST 신호 + LGBM  vs  (B) LGBM 단독(lag/roll/달력/기상)
2. 최종 피처: 위 '서빙 가능' 기상 + 달력(hour/dow/month sin·cos) + lag_24h/roll_mean_24h + day_type

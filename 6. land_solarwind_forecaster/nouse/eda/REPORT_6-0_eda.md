# 6-0 EDA 요약 — 전국 신재생 → net_load (G-9)

## 데이터 / 타깃
- 타깃: gen_solar_utilization_kr · gen_wind_utilization_kr (이용률 0~1). 2020-01~2026-06, 56,352행.
- 용량 표류: solar_cap 2746→9441MW
  (×3.4), wind_cap 완만 → **이용률 정규화 필수**(G-13).
- 학습창: train 2020–2024 / val 2025 / test 2026(부분).

## 시계열 구조
- 태양광: 강한 일주기(밤 0·정오 피크)+계절. 자기상관 lag24=+0.871.
- 풍력: 자기상관 lag1=+0.987→lag24=+0.447→lag48=+0.243
  (24h 이후 붕괴 → 재귀 롤링 장지평 불리, **direct 설계 근거**, 3단계 제주와 동형).

## 지점/공간평균 (G-13 검증)
- 태양광 선택3지점(영광·서산·포항) 평균 일사↔이용률 상관(낮) +0.786.
- 풍력 선택3지점(대관령·영광·포항) 평균 풍속↔이용률 상관 +0.641.

## 서빙 가능 피처 (★ 후처리 불가)
- 서빙 가능(O): solar_rad(radiation)·total_cloud·midlow_cloud·temp·wind_spd_10m·풍향 (지점별).
- 서빙 불가(X): humidity·rainfall·snow·cape·tcog ← forecast 없음.
  → **제주식 후처리(강수기반 solar_damping·tcog 보정) 불가**. 구름 변수로만 흐린날 대응.

## net_load 구성
- net_load = 수요 − 신재생. 태양광+풍력 외 기타 신재생(수력·바이오)이 일부 포함 → 9절 수치 참조.

## 다음 단계 결정거리 (사용자 확정, §0.6)
1. 모델 구조: LGBM-direct 다지평 단일(주력) + PatchTST D+1~3 비교(6-B) — G-13대로.
2. 최종 피처 후보:
   - SOLAR: solar_rad(3지점평균) + total_cloud_s + midlow_cloud_s + hour(sin/cos) + month/doy + (지점 raw?)
   - WIND : wind_spd(3지점평균) + wd_sin/cos + hour + month/doy + (year? 풍력 자기상관 약)
   - 공통: 이용률은 지평 무관(lag 없음) → 단일 모델이 전 지평 서빙(3단계 LGBM과 동일).

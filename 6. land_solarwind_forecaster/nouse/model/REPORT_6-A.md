# 6-A 요약 — 전국 신재생 → net_load (LGBM-direct)

## 구조
- 시장 신재생 이용률(0~1) 채널별 LGBM 단일모델(**lag 없어 지평무관 → D+1~D+12 단일모델 서빙**) → ×용량.
- 산출물 = **est_renew = 시장 태양광(market) + 풍력**. net_load = 수요 − est_renew (수요는 5단계 예측).
- 피처(§0.6 확정): SOLAR=['solar_rad', 'total_cloud', 'solar_damping', 'hour_sin', 'hour_cos', 'doy_sin', 'doy_cos'], WIND=['wind_spd', 'wd_sin', 'wd_cos', 'hour_sin', 'hour_cos', 'doy_sin', 'doy_cos'] (선택3지점 평균, solar_damping k=0.3).
- 학습창 train≤2024 / val 2025 / test 2026. solar best_iter=169, wind=169.

## 공선성(최종 피처) — clearsky_ratio·humidity 제거 후 VIF 전부 <4 (안전, §2).

## 중요도(gain) — SOLAR rad 80%·hour/doy·cloud·damping 보조 / WIND wind_spd 56%.
- **solar_damping 검증(★)**: forecast 낮 util MAE full 0.127 < rad-only 근사 0.135
  → perfect 중요도는 0.7%로 작아도 **forecast 일사 오차를 보완**(현장 직관·정직성 캐럿 일치).

## 정확도 (test 2026)
- util MAE: SOLAR 낮 perfect 0.112 / forecast 0.127.
  WIND perfect 0.099 / forecast 0.143(예보 풍속오차로 악화, 제주 동형).
- **net_load nMAE(일관 기준, 수요−시장신재생)**: perfect LGBM 0.96% vs 기후값 1.51% /
  forecast LGBM 1.07% vs 기후값 1.44% → **LGBM이 기후값 베이스라인 상회**.

## ★ net_load 기준 규명 (6-C 연결용, 중요)
- DB `net_load_kr` = **gen_total_kr(총발전) − renew_gen_total_kr**(차이 정확히 0). renew_gen_total = **시장 태양광+풍력만**(BTM/PPA·nre·수력 제외).
- 즉 net_load_kr은 **총발전 기준**. 우리 재구성은 **수요 기준**(real_demand − 시장신재생)이라 ~3,550MW(손실·양수·연계선)+BTM/PPA 만큼 상수 오프셋(§6 basis_gap≈−4,300).
- **7단계(7-A)는 net_load_kr을 직접 안 쓰고 real_demand + renew_gen_total을 피처로 받음** → 6단계 산출물(시장신재생 예측)+5단계(수요)가 체인에 정확히 맞음. net_load_kr은 참조 컬럼.

## 정직성
- net_load 평가는 수요 실측 고정(신재생 오차만 분리). end-to-end(수요예측 결합)는 6-C.
- forecast 구간 2025-12~2026-06 한정(리드타임 미태깅, 5-A 동일 한계). 2022 이용률 저표류는 train 포함(영향 점검: 안정).

## 다음
- 6-B: PatchTST vs LGBM 비교 (D+1/D+2/D+3) — 큰 차이 없으면 LGBM 단일(G-13).
- 6-C: 서빙(est_solar/wind_gen_land·est_net_load_land UPSERT), 5단계 수요예측 결합.

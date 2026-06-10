# 7-A2-A 보고서 — 전국 가스 체인 검증(5·6→7) + bias보정

## 한 줄 결론
서빙 체인(5단계 수요예측 → 6단계 신재생예측 → 7단계 가스)을 정직하게 평가하니 **test 2026 가스발전 MAPE ~13%**(ORACLE 상한 10.8%, 차이 +2.2%p는 예보 전파 비가역오차).
**A안(예보입력 재학습)은 효과 없어 기각**, 대신 **전역 bias보정 ×0.96509**로 ~14%→~13% 개선. **지평 거의 평평**(D+1≈D+12).

## 검증 구조
- 체인 데이터셋 `training/chained_gas_dataset.parquet`(193,800행). 수요=5-A2 지평별, 신재생=6단계 지평별, 기상=예보→(월,시)기후값 폴백, 타깃=실측 gen_gas_kr.
- 진짜 forecast 기상은 2025-12부터만 존재 → train창은 기후값기상 백필(서빙 하한 모드). test 2026 D+1~3은 실예보.
- 모델=기존 7-A2(util=gen_gas_kr/LNG_cap, ×용량복원). 동시점 회귀라 지평은 입력(5·6)에 내포.

## 지평별 정확도 (test 2026 MAPE %)
| 지평 | ORACLE(상한) | 현행+체인 | A안 재학습 | **현행+bias보정(권장)** |
|---|---|---|---|---|
| D+1  | 10.81 | 13.88 | 14.23 | **13.08** |
| D+2  | 10.81 | 13.93 | 14.33 | **13.01** |
| D+3  | 10.81 | 14.10 | 14.46 | **13.08** |
| D+7  | 10.81 | 14.16 | 14.57 | **13.10** |
| D+12 | 10.81 | 14.16 | 14.58 | **13.16** |

## 발견
1. **A안 기각(정직한 음성결과)**: 체인입력 재학습이 현행보다 0.3~0.4%p 나쁨. 체인입력 bias는 작고(수요 0.5%) 진짜오차는 분산(노이즈) → errors-in-variables 감쇠만 발생. train(기후값)↔test(실예보) 노이즈구조 차이로 정렬이득도 없음.
2. **지평 평평**: D+1(13.88%)≈D+12(14.16%). 가스 정확도는 지평이 아니라 상류 입력품질에 의존 → **D+12까지 D+1 수준** 가스예측 가능.
3. **bias보정이 지렛대**: val2025 전역계수 ×0.96509 하나로 전지평 bias +6~8%→+2.5~4.3%, MAPE −1%p. 지평별 계수도 동일범위→단일 전역계수 충분.
4. **남는 +2.2%p**(체인 vs ORACLE)는 수요·신재생 예보의 전파오차로 비가역(§5.4 정직성).

## 모델 피처 (재확인)
- 입력: real_demand_land(서빙=5단계 est_demand_land) + renew_gen_total_kr(서빙=6단계 est_market_renew_land, =solar_market+wind) + hour/dow/month/doy + day_type.
- 타깃: util=gen_gas_kr/LNG_cap → ×LNG_cap(월별 ffill) → ×bias_calib. 송출량(TON)=발전량(MWh)×0.1521(7-C).
- 제외: 기온·year·net_load(분해 내포)·HVDC·유류·타깃lag(누수).

## 서빙
- `serve_land_gas.py` : forecast.est_demand_land·est_market_renew_land 읽어 est_gas_gen_land·est_gas_sendout_ton_land UPSERT. 검증(D+1 백필 2026-02~05): 발전량 MAPE 13.07%·bias +3.2%.
- 보정계수·변환계수: `model/gas_serving_calib.json`.

## 산출물
- training/chained_gas_dataset.parquet, training/build_chained_dataset.py, training/retrain_7a2a.py
- model/lgbm_land_gas_util_chained.txt(A안, 미채택·기록), model/gas_serving_calib.json
- serve_land_gas.py
- fig/7a2a_horizon_mape.png, fig/7a2a_bias.png, fig/7a2a_pred_d1.png, tab/7a2a_horizon_metrics.csv

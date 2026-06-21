# weights/ 구성 메모 — 지평별 하이브리드 (2026-06-21 배포)

이 폴더 = **production 수요 모델 가중치**. `7. land_gas_forecaster/serve_chain_land_new.py`(LT_DIR)와
`serve_land_new.py` 가 읽는 정본. 지평별로 가중치·보정을 **차등** 적용한다.

## 구성
| 지평 | 가중치 | 보정(calib) |
|---|---|---|
| **D1-6** | ★파인튜닝본(인코더 동결·head만 재학습) | **없음** (calib_lt.json 에서 초단·단 셀 제거) |
| **D7-15** | 기존 v4(<2025 학습) | 유지 (중·중장·장 셀) |

## 근거 (상세 = eda_scaler/REPORT_demand_solar.md §D·E)
BTM 태양광 폭증(2025~, 2026-03 용량 21GW)으로 한낮 계량수요 과대예측(맑을수록 심함). 레벨은 anchor 가
추적하나 residual head 가 <2025(BTM≈0)에서 학습돼 한낮 봉우리를 얹음. 보정표는 (계절·시각·지평) 키라
solar 조건부 spread 를 못 줄임 → **단기는 파인튜닝이 구조적으로 우수**(낮 solar spread 7.8→4.6),
**장지평은 ft 가 과적합**이라 보정 유지. 봉인 test(forecast_horizon 186 base): 전체 MAPE 3.95(기존
production 3.89 동급)·낮 spread 10.3→8.9.

## 자산
- `best_lt_D1-6.pth` = 파인튜닝본 / `best_lt_D7-15.pth` = 기존.
- `calib_lt.json` = 216셀(D7-15 중·중장·장만). 빌더 `calibrate_lt.py`는 **D7-15만 굽도록 수정됨**(`SKIP_GROUPS={'초단','단'}`) → 데이터 쌓여 재실행해도 D1-6 무보정 유지(안전).
- `scaler_exog.pkl`·`metadata_lt.pkl` = 기존 보존(HP·DMEAN/DSTD/RESID_STD 불변).
- `metadata_ft.json` = 파인튜닝 전/후 val 기록.
- 원본 백업 = `../weights_v4_orig`(롤백용, 며칠 운영 확인 후 삭제 가능).
- 재현 = `finetune_land_lt_colab.ipynb` + `eda_scaler/finetune_split.csv`(격자 split p=1/6).

## 향후
D7-15 보정도 없애려면 장지평 전용 "약한" 재파인튜닝(에폭↓·lr↓·최근월 가중)으로 +4.4% 낮 bias 를
과적합 없이 줄이는 시도 필요(현재는 보정 유지가 정답).

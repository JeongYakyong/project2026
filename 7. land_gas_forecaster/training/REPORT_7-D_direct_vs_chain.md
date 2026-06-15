# 7-D — 수요→가스 직접 PatchTST vs 체인(LGBM v2) 비교  2026-06-15

## 1. 배경·가설
현행 가스 예측은 **체인**이다: 수요(5, LGBM) → 신재생(6, PatchTST+LGBM) → 가스(7, LGBM v2).
가스는 사실상 잔여 급전(순부하 ≈ 수요 − 신재생)의 LNG 메리트오더 반응이라, 봄낮 가스 급감은
태양광 덕커브(r=−0.80)다. 체인은 그 덕커브를 6단계 `renew_util`로 **명시 계산해 넘기므로 수요
오차 + 신재생 오차가 둘 다 가스로 전파**된다.

**가설**: 6단계를 건너뛰고 수요 + 원시 기상을 PatchTST에 직접 주어 `수요 − f(기상) → 가스`를
끝단에서 학습하면, 신재생 단계의 모델링·전파 오차를 따로 물지 않아 더 정확할 것이다.

## 2. 설계
- **모델**: 6단계 Cross-Attention PatchTST 재사용. direct 지평 D+1/2/3/7/12(offset 0/24/48/144/264), pred_len 24.
- **피처(확정 2026-06-15)**:
  - 타깃 = `gen_gas_kr` MW(÷LNG_cap 미적용=외삽 회피), train MinMax 고정(`scaler_y`, 5780~38558MW).
  - 드라이버 = `real_demand_land`(학습=실측 / 서빙=`est_demand_land`, `est_horizon_land`).
  - 태양광 = `solar_rad·total_cloud·midlow_cloud·solar_damping` @ 영광·서산·포항(3채널 raw).
  - 풍속 = `wind_spd_pohang` 1개(=서빙 forecast_horizon `wind_spd_10m_pohang`).
  - 달력 = Hour/Year sin·cos / 자기회귀 past_y = 가스(scaler_y). 손실 = 낮 09-15h 과대예측 ×α(=1.5).
- **학습**: train ≤2024 / val 2025 (Colab GPU).
- **평가**: forecast_horizon 182 base(2025-12~2026-06, **학습창 밖 2026 out-of-sample**), 21,840행.
  - 직접(honest): 과거창=historical 실측, 미래 기상=forecast_horizon, 미래 수요=`est_demand_land`.
  - 직접(perfect): 미래 기상·수요까지 실측 → 모델 상한.
  - 체인 LGBM: `horizon_backtest_v2.parquet`의 `est_gas_gen_raw`(동일 honest 입력, 보정 전 raw).
  - 양쪽 모두 raw(보정 전) 비교, 실측 = historical `gen_gas_kr`.

## 3. 결과 (MW MAPE / bias%, raw)

### 전체
| 지평 | 직접(honest) | 직접(perfect=상한) | 체인 LGBM |
|---|---|---|---|
| D+1 | 13.19 / −1.9 | **11.03** / −1.9 | 12.81 / −4.0 |
| D+2 | 13.86 / −0.8 | **12.02** / −1.4 | 12.86 / −3.7 |
| D+3 | 13.67 / −1.7 | **11.54** / −1.5 | 13.07 / −3.7 |
| D+7 | 16.65 / −5.2 | **12.18** / −5.7 | 13.84 / −3.3 |
| D+12 | 17.13 / −2.2 | **12.14** / −5.2 | 15.20 / −2.2 |

### 낮 09-15h
| 지평 | 직접(honest) | 직접(perfect) | 체인 LGBM |
|---|---|---|---|
| D+1 | 17.12 / +4.1 | **11.83** / +1.0 | 15.24 / −1.7 |
| D+7 | 20.69 / +5.8 | **12.05** / −1.4 | 17.96 / +2.4 |
| D+12 | 23.62 / +10.8 | **11.98** / −3.6 | 21.49 / +5.3 |

### 봄 낮 09-15h — 덕커브 핵심
| 지평 | 직접(honest) | 직접(perfect) | 체인 LGBM |
|---|---|---|---|
| D+1 | 18.54 / +7.7 | **12.16** / +2.4 | 16.19 / −0.7 |
| D+3 | 18.05 / +2.5 | **12.66** / −0.8 | 17.31 / −0.9 |
| D+7 | 23.81 / +8.5 | **12.39** / −0.2 | 20.91 / +3.9 |
| D+12 | 27.85 / +14.1 | **12.01** / −2.5 | 24.92 / +7.1 |

## 4. 해석
1. **honest(실전 예보)에선 직접식이 체인에 거의 전 지평·전 구간에서 진다.** 특히 덕커브 핵심인
   봄낮에서 더 크게 과대(+bias)다. → 가설과 반대. **체인의 명시적 신재생 중간단계가 예보오차에
   더 견고**하다.
2. **perfect 상한이 매우 좋고 지평에 평평하다(전부 ~12%, 봄낮도 ~12%).** 즉 수요+기상→가스
   매핑 자체는 우수하고 지평 감쇠가 없다(같은 함수, 입력만 바뀜). **병목은 모델이 아니라 입력(예보
   기상·수요) 품질**이다 — 이 실험의 가장 값진 진단.
3. honest 봄낮 bias는 +(과대)인데 perfect는 ≈0 → **예보 기상오차가 태양광을 덜 빼서 가스를
   부풀린다.** 직접식이 이 변환을 체인보다 못 한다. (α=1.5는 낮 과대를 약하게만 눌렀음. 계획값
   4.0이 bias는 줄일 수 있으나, perfect↔honest 간극의 본질인 weather 변동성은 못 줄여 큰 역전은
   기대난망.)

## 5. 결론
**직접 PatchTST는 서빙 기준으로 체인(LGBM v2)을 이기지 못함 → 직접식 기각, 체인 유지.**
다만 perfect 상한(~12% 평지평)이 honest(17~28%)보다 5~15pt 좋다는 사실은 "남은 가스 정확도는
가스 모델이 아니라 **상류 예보(기상·수요) 품질**에 막혀 있다"는 진단을 준다. 가스 정확도를 더
끌어올리려면 가스 모델 교체가 아니라 예보 기상·수요 입력 개선이 지렛대다.

## 6. 산출물·재현
- 학습 노트북 생성기: `_gen_landgas_patchtst.py` → `train_landgas_patchtst_colab.ipynb`(Colab GPU).
- 학습용 CSV: `export_landgas_csv.py` → `gas_raw_land.csv`(2022~, 39,024시간).
- 가중치: `landgas_patchtst/best_patchtst_landgas_{D1,D2,D3,D7,D12}.pth` + `scaler_x/scaler_y/metadata`.
- 비교 하니스: `compare_7d_direct_vs_chain.py` → `compare_7d_results.parquet`(샘플별).
- 재현: `python "7. land_gas_forecaster/training/compare_7d_direct_vs_chain.py"`.

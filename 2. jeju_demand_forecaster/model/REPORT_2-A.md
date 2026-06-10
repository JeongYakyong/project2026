# 2-A 보고서 — 제주 수요 장지평 직접 다지평 LGBM

## 구조 (사용자 확정 — Decision Gate)
- LGBM 단독, **풀드 직접(direct) 다지평** 1~168h(D+1~D+7) 단일모델. 재귀 아님.
- 피처 22개: h, lag168, rec24, rec168, 기상4(기온·습도·일사·풍속), **구름4(total/midlow_cloud west·south raw, h≤48)**,
  **cap_btmppa_mw(BTM/PPA 용량)**, **흐린날피처(solar_deficit·solar_ramp, h≤48)**, 달력(hour/dow/month sin·cos), day_type.
- **비대칭 손실 quantile(α=0.60) + 낮시간(08~16h) 가중2** — KPX가 못 잡는 흐린날 낮 surge 과소예측 공략(2-0c).
  예측은 ~0.60분위(의도적 상향). 구름은 east가 forecast에 없어 west·south raw. **서빙=raw forecast(QM 미적용)**.
- 학습창: train ≤2025-02 / val ~2026-03-21 / test 2026-03-22~05-31. best_iter=149.
- 기존 PatchTST+LGBM **D+1** 파이프라인은 그대로 유지(별도 운영).

## 결과 (test) — MAPE %
| 지평 | 완전기상(상한) | 기후값(하한) | KPX 하루전 | naive lag168 |
|---|---|---|---|---|
| D+1 | 3.82 | 6.84 | 5.94 | 8.80 |
| D+2 | 3.88 | 6.85 | 6.01 | 8.75 |
| D+3 | 4.00 | 6.88 | 6.01 | 8.75 |
| D+7 | 4.10 | 6.94 | 6.01 | 8.75 |
| 전체 | 3.99 | 6.90 | 6.00 | 8.76 |

## ★ 낮시간(08~16h) 정확도 — KPX가 못 잡는 흐린날 surge (1순위 지표, tab/2-A_daytime.csv)
| | 낮전체 | 낮흐림 | 낮맑음 | 전체 |
|---|---|---|---|---|
| KPX 하루전 | 9.09 | 6.90 | 9.94 | 6.00 |
| 모델 완전기상(상한) | 6.16 | 5.60 | 6.29 | 3.99 |
| 모델 forecast기상(실서빙) | 8.04 | 6.87 | 8.94 | 4.80 |
- 비대칭(quantile 0.60)+낮가중2+흐린날피처로 흐린날 surge 과소예측을 공략 → 완전기상에선 흐림·맑음 모두 KPX 압도.
- 실서빙(forecast)에선 맑음·낮전체는 KPX 우위 유지, 흐림은 예보(구름·일사) 품질 한계로 KPX와 비등(예보 본질 문제, 2-0c).
- QM(분포보정)은 흐린날 순효과 음이라 미적용. cape 등은 forecast 전용이라 미채택.

## D+1 PatchTST 비교 (tab/2-A_d1_compare.csv)
- 신규 LGBM 직접(완전기상) 3.82% / (기후값) 6.84%
- PatchTST 단독 6.06% / KPX 하루전 5.94%
- 참고: 배포 PatchTST+LGBM D+1 자체 평가 ≈3.98%(구간/집계 상이).

## 산출물
- models/lgbm_jeju_demand_direct.txt, models/model_meta_direct.json
- fig/2-A_mape_horizon.png, fig/2-A_daytime.png, fig/2-A_importance_example.png
- tab/2-A_mape_by_dayahead.csv, tab/2-A_daytime.csv, tab/2-A_d1_compare.csv, tab/2-A_importance.csv

# 6-A2 요약 — 전체 신재생(true_renew) 예측 (market+PPA+BTM)

## 방식
- BTM/PPA = 시장 태양광과 같은 이용률 공유 → **utilization×capacity 통합**.
  total_solar_cap = market_cap + k(1+r)·ppa_cap (k=0.7108, r=0.3152).
  est_true_solar = solar_util × total_solar_cap. 6-A 모델 재사용(새 모델 없음).
- 유효 총 태양광 용량/시장 용량 ≈ 2.8배 → true_renew도 ~2.8배.

## 복원 검증 (측정구간 2024-11+)
- util×(k(1+r)ppa_cap) 이 실측 (PPA+BTM) 재현: §2 MAE/corr. 내포 PPA 이용률↔시장 이용률 상관 높음(같은 이용률 가정 타당).

## true_renew 정밀도 (test 2026)
- market: MAE 564MW (23.7%) / true: MAE 1836MW (27.4%) [perfect]
- forecast: market 27.9% / true 31.6%
- 복원 근사 하한(util 실측) recon_only_MAE = 393MW.

## 산출물 (6-C 서빙 대상)
- est_market_renew(→7-A), est_true_renew·est_true_demand(→7-Ar 대체효과). net_load 숫자는 6-A와 동일(상쇄).

## PatchTST(6-B) 판단
- true_MAEpct vs market_MAEpct 비교가 근거: §4 표. 태양광이 true_renew를 지배하므로 정밀도 이득이 여기서 드러남.
- estimated 구간(2024-11 이전)은 역추정 라벨 — 정확도 핵심수치는 measured(test 2026) 기준.

## 다음
- 6-B: PatchTST vs LGBM (D+1/2/3) — §4 결과로 결정.
- 6-C: 서빙(est_market_renew·est_true_renew·est_true_demand UPSERT) + 5단계 수요 결합.

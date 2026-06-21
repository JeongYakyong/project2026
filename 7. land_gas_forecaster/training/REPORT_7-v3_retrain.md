# 가스(7) v3 재훈련 — 야간 레짐 대응(최근 원전 관성 피처 + walk-forward) 2026-06-21 (G-25)

## 한 줄
2026 원전 가동 하락으로 야간 (net_load→가스) 함수가 이동(concept shift)해 v2(2022–24 학습·원전
미반영)가 겨울 밤 과소·여름 밤 과대였다. **최근 원전 관성 피처 + walk-forward 재훈련**으로 야간
bias 를 구조적으로 제거했다(후처리 아님).

## 진단 (→ REPORT_7-regime_shift_2026.md)
- 새 체인 정직 재검증에서 가스 bias 를 지평5구간×낮/밤×계절로 쪼개니 **밤이 계절별로 깨끗·단조**
  치우침(겨울 밤 −6~−9%, 여름 밤 +8~+11%). 전체 평균(−2.8%)이 상쇄로 숨김.
- 동일 net_load(깊은 밤)에서 **가스+원전 ≈ 일정** → 2026 빠진 원전(~2,400MW)을 가스가 1:1 대체.
  야간 회귀식 2026 분리(기울기 0.43 vs 2023–25 0.20~0.30) = concept shift.
- 모델 피처는 원전을 못 보고(피처 금지), 학습창은 옛 원전(~21k) 기준 → 야간 구조적 오차.

## 핵심 통찰 + 실험 (exp_gas_regime.py)
- **원전은 관성이 매우 큼**: corr(원전ₜ, 원전ₜ₋₂₄ₕ)=0.998, 24h 전 값으로 대리 시 MAE 124MW(0.9%).
  → "최근 원전"이 미래 원전의 거의 완벽한 대리값이고 서빙 가용(미래 원전 불필요). 옛 '원전 금지'는
  구체적 EDA 없이 내린 결정 → walk-forward 로 신레짐을 학습창에 넣으면 그때의 외삽(covariate shift)
  우려가 풀린다(사용자 재검토).
- **결정적 실험(oracle 피처)**:
  - (B) train ≤2025(신레짐 미포함) → test 2026: 최근원전 피처가 **악화**(겨울밤 −7.9→−10.2). 학습
    범위 밖 외삽 = 옛 실패 재현.
  - (C) walk-forward train ≤2026-03 → test 2026-04~06: 최근원전 피처가 **개선**(전체 MAPE
    10.21→9.57%, 여름밤 +8.7→+5.7%). → **원전 피처 + walk-forward 는 한 묶음일 때만 작동.**

## 확정 (사용자)
- **피처 = v2 MIXED + nuke_rec24 + nuke_rec168**(origin 이하 최근 24h/168h 원전 평균).
- **학습 = walk-forward**(신레짐 포함 전 가용데이터). 손실 = v2 동일 α4 낮 비대칭. 타깃 = 가스 MW.
- production = fold-C 로 best_iter(546) 잡고 **전 샘플로 재학습**(서빙은 항상 최신 포함).

## 결과
| 구분 | v2 | **v3** |
|---|---|---|
| 모델품질 oracle (fold-C 봉인 train≤2026-03/test2026-04~06) | 10.72% | **9.61%** (밤 bias −0.1%) |
| **체인 봉인** (foldC 모델 × 2026-04~06 base, out-of-sample) | — | **12.36% / bias +0.2%** |
| └ 밤 | (구조적 −3.7%·계절갈림) | **10.94% / bias +0.7%** ✅ |
| └ 봄 / 여름 | 13.11 / 12.70% | **12.73 / 11.25%** |
| 체인 in-sample 전구간 (낙관·참고) | 12.81% | 9.04% (밤 7.39%) |

- **야간 레짐 bias 구조 제거**: v2 밤 −6~+11% 계절갈림 → v3 봉인 밤 bias +0.7% 중심화. 후처리 아닌
  모델이 원인(원전)을 직접 학습. 원전 피처 중요도 gain 3.3%(nuke_rec24 1.6 + nuke_rec168 1.7).
- bias 가 이미 중심화 → **calib 계속 OFF 가 맞음**(후처리 불필요).

## 정직한 한계
- **겨울 밤(v2 최악 구간)은 out-of-sample 검증 불가** — 신레짐 첫 겨울이 2026 Jan–Feb 뿐이라
  "저원전 겨울 학습 + 저원전 겨울 봉인검증"할 과거가 없다. production 은 그 구간을 학습에 넣고
  generalization 을 믿는다(봄·여름 fold-C 로 간접 입증). 확실한 검증은 데이터가 더 쌓여야.
- **여름 잔여 과대(+5.4%)**: 여름 2026 표본 얇음(6월 위주). 가을 데이터 없음.
- **운영 함의**: 원전 피처는 신레짐을 학습에 포함해야 작동 → 주기적 재학습(walk-forward) 전제.
  현재는 1회 재학습(전 데이터). 블렌딩 기후값(2022–24)은 옛 레짐이라 장지평에서 야간 과소를
  되돌릴 미세 위험 → 봉인 D+12 bias +2.7%로 현재는 무해, 데이터 쌓이면 기후값 연도 갱신 검토.

## production 반영
- 모델: `model/lgbm_land_gas_v3.txt` + `model_meta_gas_v3.json`. v2 롤백 보존. 봉인검증용
  `lgbm_land_gas_v3_foldC.txt`(production 아님).
- 서빙: `serve_land_gas.py`(MODEL/META→v3, FEATS+nuke, `load_nuke_series` 추가),
  `serve_chain_land_new.py`(ctx['nuke_series'] + build_base 에 nuke_rec24/168 주입). 최신 base
  --no-write 정상(2026-06-18 가스 16,645MW).
- 산출: `training/{exp_gas_regime.py, train_gas_v3.py, validate_newchain_gas.py(--model/--base-min),
  newchain_gas_backtest.parquet(in-sample), newchain_gas_sealed.parquet(봉인)}`.
- (서버 배포 = 사용자 수동. est_horizon_land 재적재도 사용자 서버에서.)

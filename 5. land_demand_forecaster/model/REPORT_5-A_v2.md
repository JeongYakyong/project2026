# 5-A v2 — 전국 수요 모델 피처 엔지니어링 + 낮 비대칭 (2026-06-14)

> 배경: G-16 실예보 진단에서 수요가 **낮(09-15h)·봄에 체계적 과대예측**(+6%대)이고 이게 가스로
> 전파됨이 드러남. 사용자 방향 = 구조는 그대로(Global Model with Horizon Feature) + **피처
> 엔지니어링·비대칭 손실로 공략**. 구버전 `lgbm_land_demand_direct.txt` 는 롤백용 보존.

## 결정(사용자 확정, §0.6 — decision gate 닫음)
- **구조**: Global Model with Horizon Feature (h 피처 단일 LGBM, 1..168 direct). pooled vs direct
  실예보 비교에서 사실상 동률(오히려 먼 지평 pooled 근소 우위)이라 단순한 pooled 유지.
- **기상 지점선택**(단순 5평균 → 용량집중지): **일사=서산·영광(충남·전남)** / **풍속=대관령·포항
  (강원·경북)** / 기온=5지점. 무관 지점 노이즈 제거.
- **신규 피처**: 구름 **total_cloud·midlow_cloud(서산·영광)** + **cap_btmppa(월별 PPA 용량,
  kr_elec_capa.csv)** — 빠져 있던 BTM 듀크커브 신호. (제주 2-A엔 있었으나 land엔 부재였음.)
- **손실**: 커스텀 L2 비대칭 — **낮(09-15h) & 과대예측(pred>actual) 일 때 grad/hess ×8**
  (land 부호 = 낮 과대를 아래로. 제주식[낮 과소→위로]과 반대, 복붙 금지). init_score=평균(64125).

## 실예보 백테스트 결과 (forecast_horizon, 2025-12~2026-06)
봄 낮(★1순위 전이철)·겨울 낮의 여정:

| 구간 | 원래(5평균·L1) | +지점선택 | +구름·cap_btmppa | **+비대칭 α=8 (최종)** |
|---|---|---|---|---|
| 봄 낮 | 9.43% / +6.25% | 9.40% / +6.28% | 8.29% / +4.92% | **7.91% / +3.90%** |
| 겨울 낮 | 8.10% / +5.77% | 7.48% / +5.77% | 6.29% / +3.15% | **6.23% / +2.64%** |
| 여름 낮 | 5.64% | 6.15% | 4.89% | **4.72% / +1.39%** |
| D+7(전체) | 5.16% | 4.94% | 4.27% | **4.22%** |
| D+12(전체) | 6.37% | 6.14% | 5.49% | **5.48%** |

(셀 = MAPE% / bias%. cap_btmppa 중요도 6.7% — 신규 피처 중 최대.)

- **봄 낮 MAPE −1.5%p·bias 거의 절반(+6.25→+3.90%)**, 겨울 낮 −1.9%p. 밤·전체는 무해(밤
  +0.05~0.1%p, 전체 지평 오히려 약간 개선).
- cap_btmppa 가 핵심(낮 과대를 직접 깎음), 비대칭이 잔여 낮 과대를 마무리. 구름은 미미하나 무해.
- 남은 봄 낮 +3.9% = 예보 입력 분산(비가역) + BTM 듀크커브 본질 불확실성.

## production 반영
- 학습/저장: `train_demand_v2.py` → `models/lgbm_land_demand_v2.txt` + `model_meta_v2.json`
  (offset=init_score, alpha, 피처·지점선택·capa 기록).
- 서빙: `serve_land_demand.py` 가 v2 모델 로드 + 지점선택/구름/cap_btmppa 조립 + **offset 가산**
  (커스텀 목적함수라 predict 에 init_score 수동 더함). **backfill D+1 MAPE 4.30→3.56%**.
- 실험 자산(재현): `exp_weather_agg.py`(지점선택), `exp_features.py`(구름·cap_btmppa 누적),
  `exp_asym.py`(α 스윕), `compare_pooled_vs_direct.py`(pooled≈direct 근거).

## 다음
- **가스 체인 전파**: 개선된 est_demand_land → 7단계 재실행 + 가스 bias 보정(Phase 2) 재적합
  (수요 양bias 감소로 보정계수 변동). 가스 모델도 같은 사고(BTM/PPA·horizon 피처) 검토.
- 유지보수: 현재 train≤2024/val2025(검증 일관). 추후 2025 포함 재학습은 BTM 성장 반영에 유리.

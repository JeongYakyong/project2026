# 7 v2 — 가스 모델 재정교화 (자기회귀 다지평 + MIXED 비율 + 낮 비대칭) 2026-06-14

> 배경: G-16/G-17 후속. 수요 v2 로 가스가 −0.5~1%p 개선됐으나 **봄 낮 가스 +11% 과대**가 남음
> (가스 모델 자체가 솔라 트로프를 과대). 사용자 통찰: 가스도 자기 과거가 있으니 수요(5-A)처럼
> 자기회귀 다지평으로. 구 7-A2(동시점 util)는 그 강한 자기상관(lag168 0.78)을 버리고 있었음.

## 결정(사용자 확정, G-18 — decision gate 닫음)
- **구조**: Global Model with Horizon Feature — 5-A식 **가스 자기회귀 직접 다지평**(h 1..288).
  구 7-A2(동시점)에서 전환. 가스 가용성=수요와 동일(같은 KPX 피드) → 가스 lag 누수 아님
  (§5 '타깃 lag 금지'의 보수적 기본을 현장 판단으로 override). 명제는 드라이버-only 7-A 로 보존.
- **피처(MIXED)**: real_demand_land(MW) · **renew_util**(신재생만 비율) · gas_lag168/lag24/rec24/
  rec168 · h · hour · dow · doy. **제외**: net_load(수요와 VIF 126·r 0.986 중복) · cap_btmppa
  (가스 corr −0.016·연도 corr 0.935·test 100% 외삽=covariate shift, 실험서 악화) · month(doy와 VIF 145) · day_type.
- **MW vs 비율 종합 검토(사용자 지시 7)**: 가스·수요는 **정상(corr~0)** → MW 유지. **신재생만 표류**
  (연도 corr +0.187·외삽 14%→util 로 3%) → util. **전부-비율은 역효과**(가스÷LNG_cap=100% 외삽 수입
  → +6~9% 과대, cap_btmppa 함정과 동일). **MIXED(신재생만 util)가 최고**.
- **타깃 = 가스 MW**(÷LNG_cap 미적용 — LNG_cap 외삽 수입 회피. 구 7-A2 와 차이).
- **손실**: 커스텀 L2 비대칭(낮09-15h & 과대 grad/hess ×4). α 스윕서 전체-낮 균형점=4(α8은 전체 과보정).
- **보정**: **낮/밤 분리 지평별**(전역 보정이 비대칭 낮교정을 다시 푸는 것 방지).

## 결과 (실예보 체인 백테스트, v2 수요 입력)
| 구간 | 원래(7-A2+v1수요) | **v2 수요+가스** |
|---|---|---|
| D+1 | 13.02% | **12.22%** |
| D+7 | 14.85% | **13.34%** |
| D+12 | 17.03% | **15.12%** |
| **봄 낮** | 24.46% | **19.77%** (−4.7%p) |
| 겨울 낮 | 20.02% | **16.06%** |
| 여름 낮 | 17.80% | **14.25%** |

- 가스 자기회귀가 솔라 트로프 수준을 anchor + 낮 비대칭이 과대 억제 + 낮/밤 보정이 그걸 보존.
- 자기회귀 perfect-importance 는 낮지만(demand 50%) 서빙(노이즈 드라이버)에서 G1>G0 로 기여
  (수요 solar_damping 과 동형). renew_util 이 covariate shift 제거.

## production 반영
- 학습/저장: `train_gas_v2.py` → `lgbm_land_gas_v2.txt` + `model_meta_gas_v2.json`(offset·alpha·피처·
  renew_util·autoreg 기록). 보정 `gas_serving_calib.json`(낮/밤 분리 지평별, 이전값 보존).
- 서빙: `serve_land_gas.py` 전면 v2(자기회귀 origin 기반 다지평 + 체인 demand·renew_util + offset 가산
  + 낮/밤 보정). predict/backfill/CLI 동일. 코드 검증 완료(predict 168h·backfill 동작).
- 보존: 구 7-A2(`lgbm_land_gas_util.txt`)·드라이버-only 7-A(명제). 롤백 가능.
- 실험 자산: `exp_gas.py`(자기회귀), `exp_gas_features.py`(중요도·VIF·covariate shift),
  `exp_gas_ratio.py`(MW vs 비율 vs MIXED), `exp_gas_asym.py`(α 스윕).

## 다음 (finalization)
- **DB 체인 재적재**: serve_land_demand(v2)→serve_solarwind→serve_land_gas(v2) 백필로 DB est_* 를
  v2 로 갱신(현재 DB 는 v1 수요라 서빙 backfill MAPE 14%가 v2 백테스트 12.2%로 수렴). cron 은 자동.
- Phase 3(지평 출력 테이블 est_horizon_land) + 8단계 데모 반영.

---

## v2.1 (G-19, 2026-06-15) — 풀체인 D+15 확장 + 기후값 블렌딩

> 배경: 가스 장지평 성능 점검 중 "체인 전체를 forecast_horizon 전 구간에서 정직 검증해야 한다"는
> 사용자 방침. 수요·신재생·가스를 D+15까지 정합시키고, 기후값 블렌딩을 도입.

### 정직성 결함 수정 (중요)
구 v2 백테스트의 D+8+ 수요는 **lag168 미래누설**로 부풀려져 있었음(타깃−168h가 원점보다 미래인데
백테스트는 전 구간 과거라 채워짐). → **lag168/336/504 가용성 NaN가드**(h≤k & 과거일 때만; 가스의
gas_lag168 가드를 수요로 일반화, 5-A2 LAGW 사상). 학습(`exp_features`)·서빙(`serve_land_demand`
캡 7→15)·백테스트 일관 적용.

### 지평 확장
- 수요 v2 `HMAX 168→360`, 가스 v2 `HMAX 288→360` 재학습. 솔라 PatchTST D14/D15 가중치 활성화
  (`LAND_HORIZONS`=1..15, 빈 8-11/13은 LGBM 폴백 → 솔라·풍력 전 지평 가능).

### 풀체인 정직 백테스트 (forecast_horizon 182 base × D+1~15)
`build_chain_horizon.py` → **`est_horizon_land`** 적재(base·horizon_d·timestamp, 64,939행, 미래 보존).

| 지평 | 수요 MAPE | 신재생 nMAE | 가스(보정후) |
|---|---|---|---|
| D+1 | 3.44% | 15.8% | 12.61% |
| D+7 | 4.31% | 30.5% | 13.52% |
| D+12 | 5.36% | 40.3% | 14.91% |
| D+15 | 5.58% | 43.8% | 15.30% |

### 기후값 정의 + 블렌딩 (★ 하드규칙 변경)
- G-16의 "백테스트 기후값 폴백 절대 금지"를 사용자가 **해제**("기후값=우리가 만든 평년 모델").
- **가스 기후값** = 우리 historical(2022-24) **doy±7일 슬라이딩 × 시각 × 요일유형** 평균(한국 급변동
  대응 오버랩, 폴백=시각만). 누설 차단 위해 학습연도만 사용.
- **블렌딩**: `final = (1-w(h))·예보보정 + w·기후값`, w = 0(D+1~4) → 0.5(D+15)(단조, Option A).
  지평별 w는 정직 백테스트 MAPE 최소로 적합, **전체 + 계절 동시 검증**.

| | D+1 | D+7 | D+12 | D+15 | 전체 |
|---|---|---|---|---|---|
| 예보(보정) | 12.61 | 13.52 | 14.91 | 15.30 | 13.96% |
| **+블렌딩** | 12.61 | 13.46 | **14.43** | **14.59** | **13.72%** |

- 계절: 여름 장지평 −3%p(D+15 20.7→17.9), 겨울·봄 손해 없음(개별 기후값이 더 나빠도 섞으면
  오차 상쇄 = 앙상블 효과). 그림 `training/fig/{chain_horizon_v2,blend_overall,blend_by_season}.png`.

### production
- 서빙 `serve_land_gas.py`: 기후값 빌더 + 블렌딩 통합. `gas_serving_calib.json`에
  `bias_calib_by_horizon_daypart`(15지평)·`blend_weight_by_horizon`·`climatology` 기록(이전값 보존).
- 산출 `training/{build_chain_horizon,analyze_blending,finalize_gas_archive}.py`,
  `model/{review,archive}_demand_horizon.py`.
- **한계**: 평가창 겨울~초여름(여름=6월만·가을 없음) → 여름/가을 데이터 쌓이면 블렌딩 w 재조정.
- 운영 forecast 스냅샷 재적재는 사용자가 서버에서 직접 수행.

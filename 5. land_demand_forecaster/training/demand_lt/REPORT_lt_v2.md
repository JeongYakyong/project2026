# REPORT — land_demand_lt v2 설계 근거 EDA (2026-06-20)

목표: D+1~D+15를 하이브리드 스위칭 없이 **단일구조 한 종류로** 커버. 약간의 정확도를 내주더라도
구조를 단순화하되, 현 production `hybrid_old` 를 위협할 수 있는지 본다. 학습은 Colab(GPU).

평가창: 최근 1년(2025-06-20 ~ 2026-06-20), anchor-only 기준(모델은 r=y-anchor 만 학습하므로
anchor 의 MAPE·bias 가 성능 상한·치우침을 좌우).

## 1. 기존 lt vs hybrid_old (eval_land_new.csv, 정직 백테스트)
- lt(구버전)는 final336 의 장기 +4~5% bias 는 잡았으나, **hybrid_old 를 종합적으로 못 이김**
  (단기 D+1~2 약 +0.7 MAPE 열세, 중·장기는 동등~약우세). → 단기 손해를 줄일 레버 탐색.

## 2. 앵커 후보 비교 (`_eda_anchor.py`,`_eda_anchor2.py`)
"오늘(lag-24n) 같은 최근 기준" 가설은 **기각** — 요일 구조가 최근성보다 중요해 today 가 더 나쁨.
여러 honest 레벨 구성 비교 결과(전체 MAPE / bias):

| 지평 | week2(기존) | week2+레벨보정 | **daytype_match** |
|---|---|---|---|
| D+1 | 6.16 / +0.6 | 5.76 / +0.4 | **5.29 / +0.4** |
| D+8 | 7.31 / +0.7 | 7.70 / +0.7 | **6.45 / +0.4** |
| D+15 | 8.58 / +0.8 | 8.55 / +0.8 | **7.67 / +0.3** |

**공휴일 타깃**에서 격차가 결정적 — 기존 앵커는 참조주(평일)를 그대로 가져와 과대:

| 지평 | week2(기존) | **daytype_match** |
|---|---|---|
| 공휴일 D+1 | 20.0 / **+19.1** | **11.9 / +1.8** |
| 공휴일 D+15 | 25.9 / **+24.8** | **17.1 / −1.1** |

→ **anchor = daytype_match 확정**(주말·공휴일 상태 매칭 same-DOW 가까운 2주 평균). 모든 슬라이스·지평 개선.

## 3. 달력-only 2단계 vs anchor (`_eda_baseline.py`)
"달력·시간만 받는 1차 PatchTST + 잔차 2차" 검토. 달력-only 신경망 출력 상한 = 기후값(climatology).

| | climatology(정적) | anchor D+1 | anchor D+8 | anchor D+15 |
|---|---|---|---|---|
| 전체 MAPE | 5.76 | 5.29 | 6.45 | 7.67 |

- 단기·밤은 anchor 우세(최근성), **장기는 정적 기후값이 늙은 anchor 보다 우세**.
- 그러나 2단계는 (a) 1차가 최근 레벨을 몰라 잔차에 레벨드리프트가 통째로 남고(결국 past_y 필요),
  (b) 학습 신경망이 1→2개로 늘어 **더 단순하지도 않음**. → **2단계 기각.**

## 4. anchor↔climatology 블렌드 (`_eda_blend.py`) — 보석
정적 기후값을 anchor 에 섞으면(편향-분산 수축) **전 지평 개선**:

| 지평 | anchor만 | 기후값만 | **최적 블렌드** |
|---|---|---|---|
| D+1 | 5.29 | 5.76 | **4.61** (기후값 0.4) |
| D+8 | 6.45 | 5.76 | **5.05** (0.6) |
| D+15 | 7.67 | 5.76 | **5.27** (0.7) |

w*(블렌드 비중)는 평가창 튜닝이라 낙관 가능 → **기후값을 헤드 입력으로 넣어 모델이 비중을 학습**
(지평별 15벌이라 지평에 맞는 수축을 자동). 수동튜닝·과적합 회피.

## 5. 확정 스펙 (Colab 한 판)
| 항목 | 결정 |
|---|---|
| anchor | daytype_match |
| 레벨 보강 | climatology(월·시·요일타입 평균)를 헤드 학습 입력으로 주입 |
| 공휴일 | `holidays.SouthKorea` 결정적 캘린더(과거·미래) |
| 기상 피처 | temp · humidity · solar (di·wct·cloud·cap 제거, 습도 날것) |
| exog scaler | StandardScaler → RobustScaler |
| past_y RevIN | 유지(인코더 표현용) |
| 가중치 | D1~D15 15벌 |

상한 기대치: anchor baseline 이 5.29/6.45/7.67 → 블렌드로 ~4.6/5.0/5.3. 잔차 헤드가 그 위에서 추가 감소
→ hybrid_old(D+1 2.33 … D+15 5.09) 위협 가능. **확정은 Colab 학습 후 eval_land_new.csv 재비교.**

## 다음 단계
Colab 학습 → `landdemand_weigth_lt/` 교체 → `serve_land_new.py --model lt` → `eval_land_new.py` 재평가.
lt 가 hybrid_old 를 못 넘으면 계획대로 hybrid 유지로 선회.

---

# v3 추가 (2026-06-20 오후) — 단기 과대예측 진단·처방

## v2 정직 백테스트 결과 (186 base 전 아카이브)
- 32 base(5~6월·여름多) 에선 v2 가 hybrid 압도처럼 보였으나, **전 계절(겨울 포함) 로는 v2 가 약간 열세**:
  전체 4.44(hyb) vs 4.60(lt), 겨울 4.56 vs 4.88. **여름만 v2 우세**(4.04 vs 3.76).
- 원인 = **체계적 과대예측**(낮 bias +4.3%, 겨울 +3.2%).

## 진단 (`_diag_overpred.py`) — 범인은 stale climatology
지평·구간별 bias 분해(양수=과대):

| D+1 | anchor | **climatology** | pred |
|---|---|---|---|
| 낮 | +1.4 | **+6.1** | +3.1 |
| 밤 | +0.6 | +0.4 | +0.4 |

낮 시각별 clim bias 가 **정오 정점(13시 +8.7%)** → 정확히 태양광 발전 곡선. static 기후값(2020~24)이
BTM/PPA 태양광 성장 **이전** 레벨을 들고 있어 한낮 계량수요 억제를 과소반영 → 과대. anchor(2주)는 멀쩡.
여름은 anchor 과소(−1.8)와 clim 과대(+1.9)가 상쇄돼 우연히 좋았던 것.

## 처방 (둘 다, EDA 검증)
1. **clim = 최근 기후값**: static (월,시,요일타입) 학습테이블 폐기 → **같은요일·요일타입 최근 13주 평균
   (정직-lag)**. 한낮 bias 정오 +5.3→+2.3, 낮 전체 +3.6→+1.9 로 절반↓. staleness 제거·서빙 단순화.
2. **cap_ppa 피처**: `kr_elec_capa.csv` 의 **PPA 용량**(BTM/PPA, 2020 7.7GW→2026 21GW, 월별 carry-forward).
   `gen_solar_capacity_kr` 은 시장분 전용이라 부적합. 모델이 설비 추세로 solar→억제를 스케일.
   ⚠️ 학습 최대(2024 ~16GW) 너머로 외삽(서빙 21GW) → 보조신호로만, 레벨은 최근 anchor/clim 이 방어.

→ **lt-v3**(EXOG=temp·humidity·solar·cap_ppa, 피처 10개). 학습·서빙·평가 코드 반영·스모크 검증 완료.

---

# v4 (2026-06-20 저녁) — cap_ppa 폐기, recent-clim 만 채택

## v3 전 지평 정직 백테스트 (186 base)
recent-clim + cap_ppa 둘 다 넣은 v3 결과: **낮·겨울은 개선됐으나 밤이 회귀**.
- 낮 7.72→7.12(✅) · 겨울 4.56→4.29(✅) · 여름 4.04→3.89(✅)
- **밤 3.10→3.40(❌)** · 봄 4.45→4.75(❌) · 전체 4.44 vs 4.49(거의 동률) · bias 과대(+)→과소(−)

## 밤 회귀 분해 (`_diag_overpred.py`, 밤 bias%)
| 지평 | anchor | recent_clim | **pred** |
|---|---|---|---|
| D+1 밤 | +0.6 | +1.9 | **−0.4** |
| D+5 밤 | +0.5 | +2.0 | **−1.7** |
| D+11 밤 | +1.0 | +2.6 | **−1.9** |

밤에 anchor·clim 은 둘 다 +(정상)인데 **pred 만 −로 끌려내려감** → 레벨 기준이 아니라 **피처 경로(cap_ppa)** 가 원인.
BTM 태양광은 밤에 수요를 안 깎는데, cap_ppa 가 하루 종일 같은 값이라 모델이 **밤에도 억제 적용**. 게다가 D+5 는
낮·밤 모두 과소 → cap_ppa 의 **용량 외삽(서빙 21GW>학습 16GW) 불안정**이 실측으로 확인됨.

## 판단 — cap_ppa 폐기 (A안)
cap_ppa 의 낮 효익(+1.9→+1.55, 한계)보다 밤 과억제·외삽 불안정의 실(失)이 큼. **recent-clim 이 이미 낮
staleness 를 담당**하므로 cap_ppa 제거. → **lt-v4**(EXOG=temp·humidity·solar, 피처 9개 = v2 구조와 동일,
단 clim 만 static→recent). 외삽 위험 소멸. 학습·서빙 코드 반영·스모크 검증 완료. 재학습 후 전 계절 재평가로 확정.

## v4 전 지평 결과 + post-hoc 보정 (확정)
v4 15지평 honest 186-base: **전 구간·전 계절에서 hybrid 추월**(전체 4.44→4.37·낮 7.72→7.64·밤 3.10→3.02·여름
4.04→3.71). 단 한낮 bias +3.6% 잔존(겨울 정오 +6%·장지평 +7%까지, recent-clim 잔여+학습기간 외 태양광성장).

**post-hoc (계절×시각×지평5구간) bias 보정 채택**(`calibrate_lt.py`→`calib_lt.json`, 곱셈 median(act/pred) clamp
0.9~1.1, serve 자동적용). granularity 교차검증(`_calib_validate.py`): **시각만=무효**(겨울과대·여름과소 상쇄),
**계절 필수**, 3구간≈5구간, **지평15=과적합**(여름낮 6.05→6.28 악화) → **5구간 최적**. held-out=in-sample(gap≈0).

**최종 v4+보정 vs hybrid**: 전체 4.44→**3.92**·낮 7.72→**6.55**·밤 3.10→2.83·겨울 4.56→3.86·봄 4.45→4.06·
여름 4.04→3.46. **전 구간 승 + 지평별 bias ±0.4% 평평**(겨울 D13 +7%→소멸). 보정계수가 지평·계절 의존 증명:
겨울13시 초단 ×0.954 < 장 ×0.930(장지평일수록 더 깎음), 여름13시 장 ×1.025(여름 장지평은 과소→올림).
운영: calibrate_lt 는 **미보정 서빙결과로 빌드**(이중보정 금지), 데이터 쌓이면 롤링 갱신.

## production 배선 완료 (06-20)
- **체인 배선**: `7. land_gas_forecaster/serve_chain_land_new.py` 의 수요 계산을 하이브리드(lgbm+patch)→
  `model_lt.predict_horizon(v4+보정)` 으로 교체. `model_lt` 에 `load_serve`/`predict_horizon`(+`calibrated`) 노출.
  수요가 가스 입력피처라 가스도 v4 기반(검증: 기존대비 수요 +0.3%·가스 +0.15%, 폭주없음·행수동일).
- **테이블 체계**:
  - `est_horizon_land` = production(체인, v4 **보정** + 신재생 + 가스). est_demand_lgbm/patch 컬럼 제거.
  - `est_horizon_land_raw` = v4 **원본(미보정)** 벤치(`serve_land_new.py` 기본 raw, `--calibrated` 옵션). 구 _new 개명.
  - `old_method_est_demand` = 폐기 하이브리드 수요 동결 아카이브(66,368행). eval 의 hybrid_old 비교기준.
- **부수 수정**: 사용자가 `ppa_scale.csv` 를 ISO 날짜·2020년이전 삭제로 바꿈(무해, 우리 2020+만 사용). 소비처
  `serve_solarwind_land.py`·`backfill_btm_ppa.py` 를 ISO/`%b-%y` 양형식 robust 파싱으로 보강.
- 서버 배포 = 사용자 수동(`serve_chain_land_new.py --backfill 전체` 1회 → 일일 cron). model_lt 코드는
  `5. land_demand_forecaster/training/demand_lt/` 에 위치(체인이 import), 가중치=`demand_lt/weights/`.

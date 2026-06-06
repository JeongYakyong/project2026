# A0 데이터 확보·분리 — 감사 보고서

> PRD §5.0(데이터 단계) 산출물. 게이트 **G-6**(데이터 분리 완료) 통과 근거.
> 생성: `build_dataset.py` + `make_dictionary.py`. 수치는 `data/audit.json` 기준(2026-06-03).

## 0. 한 줄 결론
제주·전국 마스터셋 결합 완료, **중복 0 / 시간구멍 0**, 학습·검증·테스트 구간 핵심 피처·타깃 **NaN 0**.
정답/피처/금지 라벨링 + 시간순 split + 데이터 딕셔너리 완비 → **A2(예측기) 착수 가능**.

---

## 1. 게이트 확인 결과 (데이터 근거)

| 게이트 | 결과 | 근거 수치 |
|---|---|---|
| **G-1 net_load 정의** | `demand − renew_total` 확정 | `real_net_load_jeju` vs `demand−renew` 평균절대차 **0.000** / vs `demand−solar−wind` = 8.02. renew_total은 solar+wind보다 ~10.6MW 큼(기타 신재생 포함) |
| **G-2 only_gen 정합** | 도출식 sanity 통과 | 2020–2024 `(net_load−HVDC)` vs `(LNG+Oil)` 상관 **0.955**, 평균절대차 22.2MW, 편향 +2.4MW |
| **G-3 HVDC 결손** | 마스터 2017-01~**2025-04-01 결손 0** | 스냅샷 연장본(~2026-04) 미보유 → 도출은 2025-04까지. 2025-07~09 결손 이슈는 *해당 구간 미보유*라 비해당 |
| **G-4 분해 비율** | **merit-order 부하수준별**(2024 기준) 채택 | 단일 스칼라(0.5421) 대비 백테스트 MAE −13.7%/MAPE −5.5pp. 급전순위(유류→LNG) 반영. §3 참고 |
| **G-5 lng_supply 단위** | 미확정 유지 | `lng_supply_national_daily` 절대단위 생성 금지, 상관/스케일 분석용으로만 보류 |

> ⚠️ **중요(G-1 영향)**: DB의 `real_net_load_jeju`는 2025-12-13부터만 채워져 있음(52,200/56,256 NaN).
> 따라서 2020–2024 학습 구간 net_load는 확정식 `demand − renew_total`로 **직접 도출**한다(코드 반영됨).

---

## 2. 결합·감사 (채우기 전, PRD §5.0-1)

| 마스터 | 행수 | 기간 | 중복 | 시간구멍 |
|---|---|---|---|---|
| 제주 (`jeju_master`) | 56,256 | 2020-01-01 ~ 2026-06-01 (시간별) | 0 | 0 |
| 전국 (`land_master`) | 56,256 | 2020-01-01 ~ 2026-06-01 (시간별) | 0 | 0 |

**결측은 의도된 것만 잔존**: HVDC(2025-04 이후)·only_gen(2024 이후)·forecast/예보 외생은 구조적으로 NaN.
→ 학습/검증/테스트 split의 **기본 피처(`feature`)·타깃엔 NaN 0** (검증 완료). 미사용 컬럼은 임의 채우기 금지.

---

## 3. A1 — LNG 타깃 시계열 (도출 + backfill, PRD §5.1)

| target_source | 행수 | 구간 | 자기참조 | 용도 |
|---|---|---|---|---|
| `measured` | 43,848 | 2020-01 ~ 2024-12 | 없음 | **엄밀 학습·검증** (only_gen 실측) |
| `derived` | 2,161 | 2025-01 ~ 2025-04 | 있음 | 데모 연속성("추정" 표기) |
| `none` | 10,247 | 2025-04 ~ 2026-06 | — | HVDC 없음 → 예측경로(5.2) |

- 도출식: `fuel_gen = net_load − HVDC`, `lng = merit_split(fuel_gen)`, 하한 0 클립.
- **분해함수 = merit-order(급전순위) 부하수준별** (`fit_merit_split.py`, 기준연도 2024).
  유류→LNG 급전순서 반영: `oil_hat = Isotonic(fuel_gen)` 단조회귀 → `lng = fuel_gen − oil_hat`.
  저부하(fuel<~125MW)는 사실상 유류 100%, 부하↑에 따라 LNG 점유율 0.1→0.6 상승.
- **왜 2024 기준?** 연도별 LNG 점유율: 2020–23 ≈ 0.39–0.47 → **2024 = 0.54**(oil_max 487→381MW, LNG 증설 레짐). 도출 대상 2025-01~04는 2024 직후 동일 레짐 → 2024로 적합(PRD §5.1).
- **백테스트(2024 내 랜덤 50/50 ×5)** — 분해함수 품질(참 fuel 기준):

  | 모델 | MAE | MAPE |
  |---|---|---|
  | 단일 스칼라 0.5421 | 43.8 MW | 28.9% |
  | **merit-order(부하수준별)** | **37.7 MW** | **23.4%** |
  | 개선 | **−13.7%** | **−5.5pp** |

- **end-to-end 도출(2024, `net_load−HVDC`→LNG)**: MAE 44.4MW, MAPE 36.3%
  (분해함수 오차 + fuel 프록시 오차 ~22MW(G-2) 합산. 실제 서빙 입력 기준 정직 추정).
- **물리 검증(derived 2025-01~04)**: 저부하(fuel<150) LNG 평균 17MW(유류 지배), 고부하(fuel>400) LNG share 0.59, 1.2%는 전량 유류 → 급전순위 거동 확인.
- `derived` 구간은 **정확도 산출에서 제외**(데모 "추정"). 엄밀 정확도는 ① 제주 `measured`(2020–24) ② 전국 `gen_gas_kr` 실측에서만.

---

## 4. 분리·라벨링 (PRD §5.0-2) — 누수 차단

데이터 딕셔너리: `data/data_dictionary.csv` (63컬럼). 역할별 요약:

| region | target | feature | feature_aux | forbidden |
|---|---|---|---|---|
| 제주 | 1 (`lng_gen`) | 16 | 7 | 6 |
| 전국 | 1 (`gen_gas_kr`) | 18 | 3 | 4 |

- **target**: 제주 `lng_gen`, 전국 `gen_gas_kr` — 피처 절대 금지.
- **feature(기본 입력)**: net_load, 기온(제주3·전국5), 달력(hour/dow/month/doy/year + sin·cos), day_type.
- **forbidden(누수원)**: HVDC·fuel_gen·oil 발전·타깃원천·RT SMP / 전국 동시결정 발전원(oil·coal·nuclear·wind).
- **feature_aux(선택)**: net_load 구성요소(demand·renew)·유가·DA SMP — 누수는 아니나 기본 제외 권장.
- **서빙 정합**: forecast의 `est_net_load_jeju` 기반 `jeju_serving`에 기본 feature **전부 존재**(parity 확인). HVDC는 forecast에 없어 자연 배제 → 금지 규칙과 일치.

---

## 5. 시간순 Split (PRD §5.0-3, 랜덤 금지)

| split | 제주 | 전국 | 구간 |
|---|---|---|---|
| train | 35,064 | 35,064 | 2020 ~ 2023 |
| val | 8,784 | 8,784 | 2024 |
| test | — | 12,401 | 2025 ~ (전국만, 실측 정답 존재) |
| demo | 2,161 | — | 제주 2025-01~04 (derived, 정확도 제외) |

- 제주 test는 forecast 구간에 실측 LNG가 없어 별도 두지 않음 → 정확도는 train/val(실측)에서 산출, 예측은 `jeju_serving`으로 데모.
- 전국은 전 구간 `gen_gas_kr` 실측 → train/val/test 모두 정직한 검증 가능(**검증목표 2 최강 증거**).

---

## 6. 산출물 (`data/`)

| 파일 | 내용 |
|---|---|
| `jeju_master.parquet` | 제주 시간별 마스터(라벨·split·target 포함) |
| `jeju_full.parquet` | **제주 전 구간 모델링용**(누수컬럼 제외, 전 행). `model_usable`=실측(2020–24)만 True |
| `land_full.parquet` | **전국 전 구간 모델링용**(누수컬럼 제외, 전 행). `model_usable`=전 구간 True(완전 실측) |
| `jeju_train/val.parquet` | 제주 실측 학습·검증 분할 |
| `jeju_serving.parquet` | 예측경로 입력(est_net_load, 4,104행, 2025-12~2026-06) |
| `land_master.parquet` | 전국 시간별 마스터 |
| `land_train/val/test.parquet` | 전국 시간순 분할 |
| `kogas_monthly.parquet` | A3 환산 참조(tariff·수입단가·기온효과, 월별 234행) |
| `data_dictionary.csv` | 컬럼 역할(target/feature/aux/forbidden) |
| `audit.json` | 본 보고서 원천 수치 |

---

## 7. 후속(A2)을 위한 권고
1. 모델 입력은 딕셔너리 `role==feature`만 기본 사용. `feature_aux`는 ablation으로 검증 후 추가.
2. 제주 LNG 예측기: `lng_gen = f(net_load, 달력, 기온, 계절)` → `jeju_serving`에 적용.
3. 전국 검증기: `gen_gas_kr = f(net_load_kr, 달력, 기온5, 계절)` → test(2025~) 정직 평가.
4. `derived`/`demo` 구간 수치는 차트에 "추정" 표기, 정확도 지표에서 제외.

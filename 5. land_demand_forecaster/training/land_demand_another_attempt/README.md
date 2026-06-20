# land_demand_lt v2 — 전국 수요 단일구조 PatchTST (anchor-residual + climatology)

`input_data_land.db`(정본 = `1. data_fetcher_and_db/data`) 대상. **D+1~D+15를 하이브리드 스위칭 없이
한 구조(15벌 가중치)로 커버**하는 것이 목표. 결과는 `est_horizon_land_new` 에 저장.

## 왜 새 구조인가 (기존 final336 진단)
기존 교차어텐션 PatchTST(final336)는 타깃을 base-window 평균으로 RevIN 역정규화 → 장기(D+8~15)에서
레벨 드리프트를 못 따라가 **+4~5% 과대예측**. 그래서 레벨을 모델 밖 **anchor** 로 분리하고 모델은
잔차만 학습하는 구조로 바꿈.

## v2 설계 (EDA 근거, 2026-06-20 — `REPORT_lt_v2.md`)
- **anchor = daytype_match (핵심)**: 타깃과 같은 **(주말·공휴일) 상태**인 same-DOW 가까운 2주 평균.
  - 기존 "주 단위 lag 평균" 은 타깃이 공휴일인데 참조주가 평일이면 **+19~25% 과대(레벨 오염)**.
  - daytype_match 로 공휴일 bias **~0**, 평상시·전 지평·밤도 일관 개선(anchor-only MAPE 전체 6.16→5.29).
- **climatology 학습 입력**: train 의 (월,시,요일타입) 평균을 anchor 와 나란히 헤드에 주입.
  anchor(저편향·고분산)↔climatology(고편향·저분산)의 **지평별 최적 수축 비중을 모델이 학습**.
  장기에서 늙은 anchor 노이즈를 기후값으로 눌러줌(블렌드 anchor-only MAPE D+1 5.29→4.61, D+15 7.67→5.27).
- **공휴일 캘린더** = `holidays.SouthKorea` — 과거·미래 결정적(음력·대체공휴일 포함). 미래도 is_holiday·anchor 정상.
- **기상 = temp_c · humidity · solar_rad 3개**. di/wct/total_cloud/cap_solar 제거, **습도 날것**.
  solar 는 BTM/PPA 태양광이 계량수요(net)를 직접 깎으므로 유지(도메인 근거).
- **exog scaler = RobustScaler**(이상치 견고). past_y per-instance 정규화(RevIN)는 인코더 표현용 유지.
- 가중치 **D1..D15 15벌 유지**. 입출력 인터페이스 동일 → 서빙 드롭인.

## 파일
| 파일 | 역할 |
|---|---|
| `model_lt.py` | 공용 단일 소스: 피처·공휴일·daytype_match anchor·climatology·Dataset·`PatchTST_Anchor`·`serve()` |
| `train_lt.py` | 학습기(D1..D15). `python train_lt.py` |
| `export_train_csv.py` | 정본 DB `historical` → `land_demand_train.csv`(Colab 업로드용, 최소컬럼) |
| `make_notebook.py` | `train_land_lt_colab.ipynb` 생성기 |
| `train_land_lt_colab.ipynb` | **Colab 학습 노트북**(holidays 설치 셀 포함) |
| `serve_land_new.py` | 서빙 → `est_horizon_land_new` (`--model final336` | `lt`) |
| `landdemand_weigth_lt/` | Colab 학습 산출물 **투입 위치**(`best_lt_D*.pth`,`scaler_exog.pkl`,`metadata_lt.pkl`) |
| `_eda_*.py` | 근거 EDA(앵커 후보·기후값 비교·블렌드). 재현용 |

> ⚠️ 현재 `landdemand_weigth_lt/` 안의 가중치는 **구 구조(clim 입력 없음)** 라 새 `model_lt.py` 로는
> 로드 불가(shape 불일치). **Colab 재학습 후 새 산출물로 교체해야 동작.**

## 워크플로
1. **학습 데이터 추출**: `python export_train_csv.py` → `land_demand_train.csv`(56,702행·12컬럼).
2. **Colab 학습**: `train_land_lt_colab.ipynb` → GPU 런타임 → `model_lt.py`,`train_lt.py`,
   `land_demand_train.csv` 업로드 → holidays 설치 → 실행 → `landdemand_lt.zip` 다운로드(약 1~2시간).
3. **투입**: zip 을 `landdemand_weigth_lt/` 에 풀기.
4. **서빙**: `python serve_land_new.py --model lt --days 31` → `est_horizon_land_new` 를 `patchtst_lt` 로 갱신.
5. **평가**: `python eval_land_new.py` → `eval_land_new.csv`(hybrid_old·final336·lt 지평별 MAPE/bias 비교).

## 비교 기준
`eval_land_new.csv` 에 production `hybrid_old`(목표 = 이걸 단일구조로 위협/대체) 와 pure `final336`,
신규 `lt` 가 지평별·낮/밤·계절 슬라이스로 들어있음. 학습 후 lt 를 다시 채워 재비교.

> 서빙 origin = base 당일 23:00(production 관례). 미래 외생은 `forecast_horizon` 재구성(3시간격 보간).
> anchor 결손 시각은 climatology 로 폴백.

# demand_lt — 전국 수요 production 정본 (단일 PatchTST v4: anchor-residual + recent-climatology + post-hoc 보정)

`input_data_land.db`(정본 = `1. data_fetcher_and_db/data`) 대상. **D+1~D+15를 하이브리드 스위칭 없이
한 구조(15벌 가중치 + 보정)로 커버.** 하이브리드는 폐기. production 출력 = `est_horizon_land`(체인).
이 폴더(`5. land_demand_forecaster/training/demand_lt/`)가 학습·서빙 코드의 단일 소스, 가중치=`weights/`.

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
| `weights/` | **정본 가중치**(`best_lt_D*.pth`,`scaler_exog.pkl`,`metadata_lt.pkl`,`calib_lt.json`) |
| `calibrate_lt.py` | post-hoc (계절×시각×지평5구간) 보정표 빌더 → `calib_lt.json` |
| `ARCHITECTURE_lt_v4.md` | **구조 명세(시각화용 단일 소스)** — 입력·forward·텐서모양·보정·서빙 흐름 |
| `REPORT_lt_v2.md` | 설계 근거·EDA·진단·기각(v2~v4 이력) |
| `_eda_*.py`·`_diag_*.py`·`_check_*.py` | 근거 EDA·진단. 재현용 |

## ★ production 정본 (06-20 배선 완료)
**전국 수요 = 단일모델 patchtst_lt v4 + post-hoc 보정.** 하이브리드 폐기.
- **production 서빙**: `7. land_gas_forecaster/serve_chain_land_new.py`(5→6→7 체인)가 `model_lt.predict_horizon`
  으로 v4 보정수요를 계산 → `est_horizon_land`(streamlit·step7 소비). 서버 cron 1줄. 배포=사용자 수동.
- **벤치(개발용)**: `serve_land_new.py --model lt`(기본 raw·`--calibrated`) → `est_horizon_land_raw`(미보정).
  보정표 재생성·백테스트 소스.
- **평가**: `eval_land_new.py` → `eval_land_new.csv`(raw v4 vs `old_method_est_demand`(폐기 하이브리드 동결) vs 실측).

## 워크플로 (재학습 시)
1. `python export_train_csv.py` → `land_demand_train.csv`(12컬럼).
2. Colab `train_land_lt_colab.ipynb`(holidays 설치 셀·버전 가드) → `landdemand_lt.zip`.
3. zip 을 `weights/` 에 교체.
4. `python serve_land_new.py --model lt` → `est_horizon_land_raw`(raw) → `python calibrate_lt.py`(보정표 갱신).
5. `python eval_land_new.py` 로 hybrid 대비 재확인.

> 서빙 origin = base 당일 23:00. 미래 외생 = `forecast_horizon` 재구성(3시간격 보간). anchor 결손 시각은
> 최근 기후값으로 폴백. 미래 공휴일 = `holidays.SouthKorea`.

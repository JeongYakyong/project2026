# 진행 로그 아카이브 2 (PROJECT.md §8에서 이관, 2026-06-08 ~ 2026-06-21)

> 루트 `PROJECT.md` §8의 오래된 항목을 그대로 옮겨 보존한다(최신이 위로, 내용 무수정).
> 2026-06-07 이전은 `docs/PROJECT_LOG.md`, 현행 로그는 PROJECT.md §8. 이관 규칙은 §0.4 참조.

**2026-06-21 — 8단계 전국 '일일 송출량' 탭 + 도시가스 on/off 구현 (G-26 후속)**
- 무엇을: 전국 종합 메뉴에 **새 탭 '일일 송출량'**(일단위 ton/day) 신설. 기본=발전용 일 송출량 막대, **'도시가스 합산' 토글** ON 시 도시가스를 위에 쌓은 **누적 막대(총 송출량)**. 사용자 확정(새 탭 + 누적 막대).
- 데이터: `common.py`에 `land_citygas_horizon`(est_horizon_citygas, latest/asof/fixed 정리축·`has_table` 가드)·`land_daily_sendout`(발전용 시간당→일합 + 도시가스 일단위, 둘 다 TON 그대로 합) 추가. `COLOR["citygas"]`(#f2a93b)·적재현황 COVERAGE 항목 추가.
- UI: `page_land.py` `render_daily_sendout`(day_navigator + 끝날짜 슬라이더 15일창 + st.toggle + go.Bar 누적 + 기간 합 지표 3개 발전용/도시가스/총). 탭 등록 `예측 확인 · 일일 송출량 · 발전데이터 · 기상개황 · 장지평 예측`.
- 검증: 실DB로 `land_daily_sendout` 점검 — 발전용 일합 49k~71k·도시가스 26.6k~30.3k ton/day, 합산 정상(여름 75k~101k ton/day). AppTest 스모크 = 일일 송출량 탭 토글 렌더·예외 0(토글 on/off 모두).
- **발견(별개·기존 버그)**: 기상개황 탭(`render_weather`→`weather_map.zone_day`)이 제주 `forecast` 테이블(06-20 DROP, G-22)을 읽어 예외 — 제주 forecast_horizon 전환 미반영분. 이번 작업과 무관, 제주 페이지 재작성 때 같이 처리(남음).
- **남음**: 서버 cron 도시가스 서빙 설치(미설치)·기상개황 제주 forecast→forecast_horizon 전환. 커밋·서버 반영 = 사용자 수동.

**2026-06-21 — 도시가스(10단계) SSOT 반영 + 최종 산출물 확장(발전용 + 도시가스 보조) (G-26)**
- 무엇을: 06-20 구축한 일단위 도시가스 송출 모델(`10. citygas_forecaster`)이 PROJECT.md(SSOT)에 전혀 없어 반영. 동시에 최종 산출물을 '발전용 가스(핵심) + 도시가스(보조·참고)'로 확장. 정리 범위 = **추가·정합만**(기존 본문 보존).
- **위상 결정(사용자)**: 핵심 명제(§1.2)는 발전용 가스 그대로 유지. 도시가스는 net_load·신재생과 무관한 **기온 기반 별개 동인**이라 명제 입증의 일부가 아니라 **보조·참고**(최종 송출량 그림 완성용). = 명제 정의 변경 아님(산출물 확장).
- **모델 요약**(상세 §4 보조 트랙·메모리): 검증 가능한 월 수요모델(`850287+3239·HDD+649·추세`, R²0.984·MAPE4.4%) → 일별 기온으로 하루 분해(요일·공휴일 보정은 기저부하에만 — 전체에 곱하면 피크 과대) → 일 송출량. 일 실측 없어 연1점 일최대 앵커로 간접검증(재현 오차 2.25%). 서빙 `serve_citygas_daily.py`→`est_horizon_citygas`(forecast_horizon 5지점 기온만 의존, 전구간 백필 186 base·D+1~15). 데이터는 전부 KOGAS(자격 앵커 강화).
- **streamlit 설계 확정(사용자)**: 기본 화면 = 발전용 시간당 송출량, **도시가스 on/off 토글** → 켜면 일간 집계에서 발전용 일 합 + 도시가스로 '총 송출량'. (구현은 8단계 후속.)
- **단위 점검(같은 날, 사용자 요청)**: 도시가스 원천(`용도별 월 공급량`·`연도별 일일 최대`)은 단위 표기가 없으나 **TON으로 확인** — 일최대 CSV 한 테이블에 발전(7-C에서 TON 확정, 일최대 105,531)·도시가스(117,836)가 같은 스케일, 월 3,074,285÷31일=99,170/day(일최대와 정합), 연 환산이 한국 LNG 도입량과 맞음. 발전용 ton/h·도시가스 ton/day로 **합산 단위 환산 불필요**(G-26 '단위 정합' 항목 해결). `build_citygas_daily.py`·`model_params.json`·`MODEL_SUMMARY.md` units 표기 갱신.
- **문서 정합**: §1.1 최종 산출물 문단·§2 KOGAS 앵커 보강·§3 폴더지도(5·6·7 골격→완료·8 진행중·9 design·10 citygas 추가)·§4 보조 트랙·§6.4·§7 G-26 추가. 메모리 citygas-daily-forecaster·streamlit-step8-progress·land-stages-done·MEMORY.md 갱신.
- **남음**: streamlit 일일 송출량 토글 구현(8단계)·서버 cron 실제 설치. 커밋·서버 반영 = 사용자 수동.

**2026-06-21 — 가스(7) v3 재훈련: 야간 레짐(2026 원전↓) 대응 (G-25)**
- 출발: 같은 날 가스 재검증(아래)에서 "구조변경 불필요"로 끝냈으나, bias 를 **지평5구간×낮/밤×계절**로 더 쪼개니(사용자 지시: 전체평균은 겨울 과소·여름 과대가 상쇄돼 망함) **밤이 계절별 단조 치우침**(겨울 밤 −6~−9%·여름 밤 +8~+11%) 발견.
- 진단 전환(사용자 현장 통찰): 깔끔한 밤 bias = 보정할 노이즈가 아니라 **모델이 야간을 구조적으로 오판** = 2025+ 레짐 변화를 좁은 학습창(2022–24)이 못 담음. **데이터 확인(G-9)**: 동일 net_load 깊은 밤에서 **가스+원전 ≈ 일정(~35k)** → 2026 빠진 원전 ~2,400MW 를 가스가 1:1 대체. 야간 회귀식 2026 분리(기울기 0.43 vs 2023–25 0.20~0.30)=concept shift. `REPORT_7-regime_shift_2026.md`·`fig/7-regime_shift_2026.png`.
- 해법(사용자 확정): 원전은 관성 큼(corr_24h 0.998·24h 대리 MAE 0.9%) → 미래 원전(서빙 불가·금지) 대신 **origin 이하 '최근 원전'**(nuke_rec24/168) 피처. 옛 원전 금지(covariate shift)는 EDA 없이 내린 결정이라 재검토 → **walk-forward 로 신레짐을 학습창에 넣으면 외삽 해소**. ★실험(exp_gas_regime.py): (B) 신레짐 학습 제외 시 원전피처 악화(외삽=옛 실패 재현)/(C) walk-forward 시 개선(oracle 10.21→9.57%) — 둘이 한 묶음.
- 재훈련(train_gas_v3.py): 피처=v2 MIXED+nuke_rec24/168, α4 비대칭 계승, fold-C best_iter(546)→전 샘플 재학습. **결과**: oracle 봉인 10.72→**9.61%**, **체인 봉인(foldC×2026-04~06 base) 12.36%·밤 bias +0.7%**(v2 밤 −3.7% 구조갈림 제거), 봄·여름 봉인 v2 추월. bias 중심화로 **calib 계속 OFF**. 원전 중요도 gain 3.3%.
- 정직한 한계: 겨울 밤(v2 최악)은 신레짐 첫 겨울이 2026 Jan–Feb 뿐이라 out-of-sample 검증 불가(in-sample 7.7%)·여름 표본 얇음·블렌딩 기후값(옛 레짐) 장지평 미세위험(현재 무해 D+12 +2.7%). 운영=원전피처는 주기적 재학습 전제.
- 배포: `model/lgbm_land_gas_v3.txt`+meta(v2 롤백 보존), `serve_land_gas.py`(FEATS+nuke·load_nuke_series)·`serve_chain_land_new.py`(nuke_rec 주입) 무손실 배선, 최신 base(2026-06-18) --no-write 정상(가스 16,645MW). 상세 §7 G-25·`training/REPORT_7-v3_retrain.md`. (서버 배포·재적재 사용자 수동.)

**2026-06-21 — 가스(7) 새 체인 정직 재검증 (5·6 구조변경 영향 점검, 구조변경 불필요 확인)**
- 배경: 5단계가 PatchTST v4+지평별 파인튜닝(G-24), 6단계가 landsolar504(06-19)로 바뀜 → 가스 예보기 튜닝 필요성 분석 요청. 서빙(`serve_chain_land_new.py`)은 이미 새 구조지만, 가스 공개 정확도(13.72%)·후처리(낮/밤 보정·블렌딩)는 **옛 수요(하이브리드)·옛 6단계로 측정·적합된 값**이라 실제 새 체인 성능이 미측정 상태였음.
- 방법: 옛 `build_horizon_backtest.py`(옛 수요 5-A2 + 옛 가스 7-A2 util, 이동·수정 금지 대상)는 안 건드리고, **현재 배포 체인 함수 `serve_chain_land_new.build_base`(v4 수요 + landsolar504 + 가스 v2 + 낮/밤보정 + 블렌딩)를 그대로 재사용**해 forecast_horizon 186 base 전체에서 실측 대조. 누수 없음(기상=그 base 실예보, 가스 자기회귀 시드는 origin 이하만). 신규 `training/validate_newchain_gas.py` → `newchain_gas_backtest.parquet`(20,688 평가행).
- **결과(가스 MAPE, 보정 OFF·블렌딩 ON)**: 전체 **12.81%**(옛 공개 13.72% 대비 −0.9%p) / D+1 11.89·D+2 12.21·D+3 12.76·D+7 13.32·D+12 13.93%. **장지평 개선폭 큼 = 새 수요가 훨씬 정확**(수요 MAPE D+1 2.44→D+12 4.79%, 옛 ~5.4% 대비)해 가스 전파오차 감소.
- **★한낮 이중보정 우려 → 해소 확인**: 옛 가스 v2 가 잡으려던 "봄 낮 가스 과대(+11%·MAPE 19.77%)"가 사라짐 — 봄 낮 bias −1.8%·낮 전체 bias −0.6%(≈중립, 부호 역전 없음). 5단계 파인튜닝이 한낮 과대를 수요 단에서 근본 제거 → 가스 낮 비대칭(α4)+낮보정은 이제 약간 불필요하나 무해.
- **남는 과제(5·6과 무관)**: 계절 bias 갈림 = 겨울 −4.6 / 봄 −3.4 / 여름 +7.5%(밤 −3.7%). 가스 모델 기존 문제(2022–24 학습·절대 MW 타깃 → 2026 LNG 증설 미반영 과소 + 여름 과대)이고 bias 보정이 06-15부터 OFF 인 이유와 동일. 여름·가을 표본은 아직 얇음(여름 n=2096, 가을 0).
- **결론**: 가스 **구조 변경 불필요**. 5·6 변경에도 서빙 정상·정확도 개선·한낮 부호 역전 없음. 사용자 결정에 따라 2단계(후처리 w(h)·보정표 새 오차로 재적합, 필요시 α 완화)는 보류(데이터 더 쌓인 뒤 재적합 권장). 산출 `training/{validate_newchain_gas.py, newchain_gas_backtest.parquet}`.
- ⚠️ **이 "구조변경 불필요" 결론은 같은 날 위 항목(G-25)에서 번복됨** — bias 를 지평5구간×낮/밤×계절 격자로 더 쪼개니 야간 레짐 변화가 드러나 v3 재훈련으로 이어짐. 이 항목은 그 직전까지의 판단 이력으로만 보존.

**2026-06-21 — 전국 수요(5) 한낮 과대 진단 + 지평별 파인튜닝 하이브리드 배포 (G-24)**
- 출발: G-23 v4 의 한낮(09~15시) 과대예측이 왜 남나. **진단**: 타깃 `real_demand_land`=BTM 차감 그리드 계량값인데, BTM+PPA 태양광이 **2025년 폭증**(한낮 12~14시 0→16GW, 2026-03 용량 21GW). 4·5월 "한낮−새벽" 계량수요 부호가 2024년 +에서 **2025년부터 −(덕커브)** 로 뒤집힘 = 학습창(<2025, BTM≈0)과 현재가 다른 세상. residual head 가 옛 "한낮 봉우리"를 얹어 과대. **★오차가 solar_rad 조건부**(보정전 낮 bias 흐림 −2%→맑음 +8%, r=+0.42).
- **핵심 통찰**: post-hoc 보정표는 키가 (계절·시각·지평)뿐이라 **solar 조건부 spread 를 구조적으로 못 줄임**(낮 range 보정 10.3≈raw 10.4, 흐린 날 오히려 −5.3% 악화). **레벨은 anchor/clim 이 21GW 를 잘 추적**(최근 계량수요 1~4주 lag) — stale 한 건 residual head 의 관계뿐. scaler Robust→MinMax 검토는 별개(이상치 없어 안전하나 한낮 과대와 무관, Demand 타깃은 애초 스케일 안 됨).
- **해법 = head-only 파인튜닝**(`finetune_lt.py`): 기존 가중치 로드→인코더·cross-attn **동결**, `regressor`+`weather_bypass`(5.2%)만 재학습. scaler/DMEAN/DSTD/RESID_STD/HP 전부 보존. 신체제(2024-11~2025-11)만 학습. Colab GPU 노트북(`finetune_land_lt_colab.ipynb`).
- **split 설계**(사용자와 확정): train/val=historical(실측 기상)·**격자 split p=1/6**(하루단위 교차·요일유형(평일/주말/공휴일)·계절 층화 systematic, 공휴일묶음·주말쌍 무결, `make_split.py`→`finetune_split.csv`). **test=forecast_horizon(예보 기상, 186 base 2025-12-15~2026-06-18)** 봉인 — 소스가 달라야 서빙현실(예보오차) 반영. train 은 2025-11-30 에서 끊어 test 와 무겹침.
- **봉인 test 결정**(eval_finetune.py, 60,668행): ft 단독은 production(3.89) 미달(MAPE 4.40)이나 **보정이 못 하는 solar spread 를 줄임**(10.4→8.2). 지평그룹 분해 → **효과가 D1-6 집중**(낮 solar range 초단 7.3→3.3·단 8.9→5.9, D7+ 미미+MAPE 악화=장지평 과적합). → 사용자 결정: **"보정이 5구간 차등하듯 파인튜닝도 단기만"** = 지평별 선택.
- **채택·검증**: **D1-6=ft 무보정 / D7-15=기존 v4+보정 유지**. D7-15 보정 제거 비교했으나 낮 +4.4% 과대 복귀(ft 가 장지평 과적합이라 대체 불가)→보정 유지. 하이브리드 봉인 test = MAPE 3.95(production 동급)·단기 낮 spread 7.8→4.6(41%↓). 잔여 낮 bias +0.6 은 무시(과적합 회피).
- **배포·정리**(사용자: 헷갈리지 않게): 가중치 git 미추적 → **이름변경 무손실 배포**. `weights/`(원본)→`weights_v4_orig/`(롤백 백업)·`weights_hybrid/`→`weights/`(서빙 경로 `serve_chain_land_new.py:LT_DIR` 그대로라 코드 무수정). calib_lt.json 360→216셀(초단·단 제거). weights_ft·weights.zip 삭제. md5 로 D1-6 교체·D7-15 원본 확인, 체인 5→6→7 `--no-write` 전구간 정상(base 2026-06-18 수요 62,917MW). `calibrate_lt.py`는 D7-15(중·중장·장)만 굽도록 수정(SKIP_GROUPS, 초단·단 스킵 주석 보존) → 재실행 안전. 분석 아카이브 `eda_scaler/`(REPORT 2종·스크립트·그림·duck_curve_flip.png 보존).
- 메모리 [[land-demand-midday-btm-finetune]] 신설 + [[land-stages-done]]·[[land-demand-patchtst-hybrid]] 갱신(옛 단일모델/lgbm-하이브리드 설명 stale 수정). **커밋·서버 배포는 사용자 수동.**

**2026-06-20 — 제주 SMP(4단계) est_horizon_jeju 재배선 + forecast 테이블 폐기 완료 (G-22)**
- 목표(사용자): 제주 DB의 레거시 `forecast` 테이블을 궁극적으로 제거. 막는 둘 중 ⓑ SMP를 먼저 처리(ⓐ streamlit 8-B는 후속). SMP는 **D+2까지만** 지원.
- **혼선 정리(선행)**: PROJECT.md 347줄 "제주 forecast 현역"은 06-15 시점 문장이라 06-17 G-20 전환을 못 담은 것. 실제 = 제주 예측 정본은 이미 `est_horizon_jeju`(06:30 cron). forecast가 남은 이유는 ⓐ streamlit 데모 ⓑ SMP뿐. forecast 예측컬럼 갱신 cron은 0건(동결). → 347줄 보충 포인터·메모리 [[jeju-rebuild-newdb]] 오독금지 항목 추가.
- **진단 = 재모델링 아니라 재배선**: SMP 입력피처(`net_load`=est_net_load_jeju·`est_demand`=jeju_est_demand_new·`smp_jeju_da`)를 `train_smp_db.load_forecast` 가 forecast 에서 읽음(단일 통로). 모델은 historical 실측으로 학습→forecast 폐기와 무관(재학습 불필요). 피처도 2026-06-05 확정분 유지. **바뀌는 건 입출력 테이블뿐**. SMP 점예측은 잠긴 실패경로라 모델 손대지 않음.
- **사용자 확정**: ① 방식=**재배선**(잠긴 모델·스크래치 무수정 재사용, serve_chain_jeju_new 패턴) ② 출력=**핵심 3컬럼만**(`est_smp`·`smp_neg_proba`·`smp_danger`, 깊이/위험레이어/고확신 제외).
- **★서빙 러너 신설** `4. jeju_smp_forecaster/serve_smp_horizon_jeju.py`: est_horizon_jeju(horizon_d 1~3) → 스크래치 `forecast` 형태 주입(컬럼 rename·smp_jeju_da는 historical)→ 잠긴 `smp_db_pipeline`(D+1)·`smp_d2_pipeline`(D+2) 무수정 호출 → 핵심3컬럼 수확 → **신설 `est_smp_horizon_jeju`**(PK base·timestamp + horizon_d·est_smp·smp_neg_proba·smp_danger). monkeypatch 2지점만(DB_PATH·d2 load_forecast `with_target=False`로 미래행 보존 — 원본 d2는 rt inner-join이라 backfill 전용). 스크래치에 horizon 1~3 적재=D+2 lead/shift24 경계 NaN 방지(수확은 1·2). Windows 파일잠김(with-블록 미close)은 gc.collect 회수.
- **검증 통과** `training/validate_smp_horizon_jeju.py`→`REPORT_smp_horizon_validation_jeju.md`: 로컬 forecast 예측은 06-01 동결·est_horizon은 8 base(여름·이벤트0)뿐이라 직접비교 불가 → `horizon_backtest_jeju.parquet`(178 base·Dec~Jun, 음수 147h/52일)를 입력으로 러너 재사용. **D+1 경보 recall 0.84/prec 0.39**(기존 θ=0.25 0.86/0.38 동등)·**D+2 0.81/0.40**(설계점 0.86/0.37 동등)·**D+1 가격선 MAE 0.00**(A안 DA통과 완전일치)·D+2 11.73. 야간마스크 net_load는 한낮 음수가격에 영향 없음 정량확인. → 재배선이 성능 보존.
- **★forecast 테이블 폐기 완료(같은 날, 사용자 "과감하게 drop")**: 제주 DB는 이제 **4테이블 = historical·forecast_horizon·est_horizon_jeju·est_smp_horizon_jeju**. drop 전 안전확인(`smp_jeju_da`는 historical 56,568행 완비·forecast에만 있는 시각 0 / forecast 유일컬럼은 전부 동결 레거시 예측)·백업(`99. others/forecast_jeju_backup_2026-06-20.parquet` 4,248행) 후 DROP+VACUUM. 러너는 forecast 없이도 정상(스크래치 자체 생성).
- **수집기 은퇴 처리(forecast 재생성 차단)**: ⓐ `collect_data_jeju.build()` → 미래 *_da 를 forecast 대신 **historical 에 컬럼단위 UPSERT**(신규 `upsert_da_to_historical`, ON CONFLICT+COALESCE — partial_upsert의 INSERT OR REPLACE는 행 전체교체라 실측 NULL파괴 위험, 격리 테스트로 실측 보존 실증). weather 출력 제거(forecast_horizon이 정본). ⓑ `run_backfill`(weather→forecast 백필)=폐기(RuntimeError, backfill_jeju_forecast.py로 대체). ⓒ deploy: `run_serve_smp_jeju.sh`(④ 06:40) 신설·crontab 정리(run_collect_jeju 1줄=historical만, forecast-days 7줄 폐지).
- **streamlit 8-B 플랜 폐기(사용자)**: 제주 페이지는 **처음부터 재작성**(forecast 의존 전제가 사라짐). 재작성 시 net_load·수요=est_horizon_jeju, SMP=est_smp_horizon_jeju, 기상=forecast_horizon, DA·실측=historical 사용. = 별도 신규 작업(옛 8-B 점진전환 계획 무효).
- **결과 검증·정확도 확인(사용자 "값을 직접 보고싶다")**: `training/inspect_smp_examples.py`(parquet 178base 서빙→사례·그림)·`fig/smp_inspect_spring.png`. **D+1 가격선=DA 정확히 일치(A안 확인)**·봄 음수일 52일 중 49일 경보 적중(94%). **D+2 가격선(예측 DA) MAE 11.73원**(나이브 lag24 14.32 대비 +2.60 개선=−18%)·bias +0.58·상관 0.639·음수경보 recall0.81/prec0.40(계절 무관 baseline 우위). 실예시 2026-05-01: DA(가격선) 한낮 0원인데 rt −70 → dangerzone가 정확히 경보(=DA로 안 보이는 음수위험 포착).
- **target 명확화(사용자 질문 "rt 아니라 DA 예측 맞지?")**: 맞음. 가격선 target=**SMP_DA**(D+1 발표값 그대로·D+2 DA잔차회귀), dangerzone=**음수(rt<5) 이진 경보**. rt 점예측 안 함(잠긴 실패경로). 오해 소지였던 `train_smp_db.TARGET_REG`(이름이 회귀 암시) → **`RT_COL`로 개명**(실제 용도=음수 라벨·채점용 rt 컬럼, 회귀 타깃 아님 주석) — train_binary_smp·smp_calibrate 동반 갱신.
- **죽은 SMP 서빙 코드 정리(사용자 확인)**: forecast 폐기로 실행 즉시 깨지는 옛 코드 3개를 `4. jeju_smp_forecaster/no use/dead_forecast_pipelines_2026-06-20/`로 이동(README 동봉) — `smp_serve.py`(옛 통합 서빙, 대체=serve_smp_horizon_jeju)·`smp_depth_pipeline.py`·`smp_softest_pipeline.py`(깊이·위험레이어, 핵심3컬럼서 제외). depth/softest는 smp_serve만 import → 셋 함께 이동 무회귀. 운영 폴더 라이브=`serve_smp_horizon_jeju`·`smp_db_pipeline`·`smp_d2_pipeline`·`train_smp_db` 4개(스크래치 경유, 실 forecast 미접촉). (98 report only의 compare_* 분석 스크립트는 forecast 의존이나 보고용이라 보류.)
- **남음**: 서버 반영(weights·crontab 갱신·`serve_smp_horizon_jeju --backfill` 누적, 사용자 수동) · 제주 streamlit 페이지 신규 작성 · est_horizon_jeju/est_smp_horizon_jeju 전구간 backfill. 메모리 [[jeju-smp-done]]·[[jeju-rebuild-newdb]]·[[streamlit-step8-progress]] 갱신.

**2026-06-19(b) — 전국 서빙 단일화 정리: 솔라504 전환·est_horizon_land 전구간 재구축·forecast 테이블 폐기·단독 실행 스크립트 정리**
- **6단계 솔라 가중치 교체**: `landsolar_patchtst`(seq336·D{1-7,12,14,15} 10개) → **`landsolar504`(seq504·d_model256·D1~D15 전 15개)**. 빈 지평(8-11,13) LGBM 폴백 사라짐=전 지평 PatchTST. 피처 동일이라 `serve_solarwind_land.py`의 `PT_DIR`·`SOLAR_PT_HORIZONS=1..15`만 교체(아키텍처는 메타 HP로 자동). 15개 strict 로드·체인서 D+8~13 solar=patchtst 검증.
- **est_horizon_land 전구간 재구축**: 기존 backfill이 하이브리드 이전 수요+504 이전 솔라라 혼선 → 낡은 값 전부 삭제 후 `serve_chain_land_new --backfill 186`으로 현행 모델 재적재(66,368행·186 base·2025-12-16~2026-06-30·D+1~15). 레거시 forecast 테이블의 옛 예측 컬럼 11개도 NULL 처리.
- **forecast 테이블 폐기(land)**: 전국 DB는 이제 **3테이블 구조 = est_horizon_land(예측)·forecast_horizon(기상 아카이브)·historical(실측)**. 옛 forecast 테이블 DROP(수집은 이미 forecast_horizon으로 이전됨, 예측은 est_horizon_land로 이전됨). **제주 forecast는 (이 시점엔) 현역이라 유지**(제주는 아직 forecast 기반). ※**갱신(06-17, G-20)**: 제주 예측 서빙도 `serve_chain_jeju_new.py`→`est_horizon_jeju`로 전환 완료(forecast 미접촉). 따라서 제주 예측 정본은 이미 `est_horizon_jeju`이고, 레거시 `forecast.jeju_*`가 남은 이유는 ⓐ streamlit 데모(8-B 미전환)와 ⓑ SMP(4단계, 체인 범위 밖·`est_horizon_jeju` 대응물 없음) 둘뿐이다. forecast의 제주 예측 컬럼을 갱신하는 cron은 없다(동결).
- **단계별 단독 실행 스크립트 정리**: 통합 체인 `serve_chain_land_new.py`가 5→6→7을 한 번에 돌리므로 단계별 직접 실행은 체인과 중복 → `serve_land_demand.py`는 `99. others`로 아카이브(아무것도 import 안 함), `serve_solarwind_land.py`·`serve_land_gas.py`는 체인이 import하는 라이브러리 함수만 남기고 forecast에 쓰던 단독 실행부(`predict_*_to_db`·`backfill_*_to_db`·`__main__`) 제거. 체인 무회귀 확인.
- 메모리 [[land-stages-done]]·[[streamlit-step8-progress]]·[[land-demand-patchtst-hybrid]] 갱신.

**2026-06-19 — 전국 수요(5) 하이브리드 production 서빙 반영 (G-21)**
- 무엇을: final2 후속 — PatchTST를 서빙에 반영. **하이브리드 확정**: D+1~2 full PatchTST(final336=seq336+comfort+MSE) / D+3~7 주간(09~15)=PatchTST·야간=LGBM / D+8~15 LGBM(**v2hum**).
- **기각 3건**: 예보오차 증강(용량-반응 악화 — 예보오차는 invariant 대상 nuisance 아님, 학습 때 날씨 흐리면 관계만 뭉개짐), 시간 Late Fusion(honest≈final2, D+1만 우위), comfort di/wct(VIF 665/351/155 다중공선성·악화). → **raw humidity 채택=v2hum**(temp 4지점·생바람 제거, di/wct 폐기).
- **honest(n=63,064)**: 기존 LGBM v2 4.495→**하이브리드 4.395**·낮 7.92→**7.67**·밤 동률. 이득 D+1~7 집중(**D+1 −0.69**·D+3 −0.31). **계절별 낮: 봄 주도**(D+1~7 −1.47, 덕커브)·겨울 +0.03·**여름낮은 PatchTST 약점(+0.86)이나 표본작음→마스크 예외 안 둠**(과적합 회피, watch-item).
- 서빙: `7.../serve_chain_land_new.py`(수요 v2→v2hum + `5.../serve_demand_patch.py`(final336 D1~7) 결합)→**est_horizon_land 3컬럼**(`est_demand_land`=합본·step7 입력 불변 / `est_demand_lgbm` / `est_demand_patch`). exp_features에 temp_c4·humidity·di·wct 빌드 추가(공유). **기후값 블렌딩=demand엔 불필요**(장지평 수요는 기상입력 둔감, 자기회귀 지배 — 가스 G-19와 상황 다름). 미사용 가중치 358MB→루트 `nouse/`. 상세 `REPORT_5-B.md §9~12`, 메모리 [[land-demand-patchtst-hybrid]]. **서버 배포(weights+`--backfill` 재적재)는 사용자 수동.**

**2026-06-18 — 전국 수요(5) PatchTST 최종 final2 + 낮 하이브리드 (5-B 결론)**
- 무엇을: 피처 재구성으로 PatchTST 최종화. final2 = Cross-Attention PatchTST+RevIN(타깃)+**전역 z-score(외생)**+**comfort(불쾌지수·체감기온)**+temp 4지점(대관령 무인 제외)+**seq_len 504**+**MSE 손실**(LTSF표준, 평가 MAPE). lag·wind·humidity·midlow_cloud 제거(중요도≈0). 서빙일관=forecast reh·wind_spd_10m로 comfort 재구성.
- **honest(forecast_horizon, n=63,064)**: 하이브리드(낮 09-15h×D+1~12=final2·그외=LGBM) **전체 4.35**(LGBM 4.495)·**낮 7.43**(7.92, −0.49%p)·밤 3.08(=LGBM)·봄 4.40·여름 3.84.
- **seq504가 장지평 낮 역전**(낮 우위 D+1~9→D+1~12·14, 사용자 "10일+ 개선" 적중)·**comfort가 여름 파탄 해결**(D+5 여름낮 10.01→5.41). **밤=구조적 LGBM**(자기회귀), final2 단독은 LGBM에 짐 → 하이브리드 필수.
- 결정: production=LGBM 백본 유지, final2 낮 오버라이드=업그레이드 후보(서빙 미반영). 탐색 모델(360·MAE·anchor 등) 정리. **★다음=예보오차 증강**(train 실측↔serve 예보 분포격차 교정). 상세 `5.../training/REPORT_5-B.md §8`, 메모리 [[land-demand-patchtst-hybrid]].

**2026-06-17 — 전국 수요(5) PatchTST 전환 탐색: 낮×D+1~5 하이브리드 (5-B)**
- 무엇을: 5단계를 LGBM(5-A_v2)→Cross-Attention PatchTST+RevIN(제주3·6단계 solar 구조)로 바꿀지 honest 검증. 5-0b 사전진단(타깃표현=RevIN·seq_len 336)→15모델 direct + 단발 360, 손실 ablation(MSEα1.3/MAEα0/MSEα1.0).
- **honest 5자 비교**(forecast_horizon 동일 63,064행, `_ab_honest.py`): 전체 MAPE LGBM v2 **4.49** < PatchTST 최선(MAEα0) 4.86 < MSEα1.3·1.0 5.02 < 단발360 5.39. **perfect 상한에선 PatchTST 압승(D+1 2.43 vs 3.48)이나 honest서 전 변형 패배**(7-D·G-16 재현, 병목=예보품질).
- **★낮/밤 분리 핵심**: PatchTST는 **낮 D+1~5만 LGBM 우위**(기상 구동), 밤은 D+2+ 전부 LGBM 승(순수 자기회귀, lag168/336 앵커 압승, PatchTST 기상장치는 밤 잡음). 밤 17/24h가 낮 강점 덮음.
- **최적 = 낮(09–15h)×D+1~5만 PatchTST 오버라이드 + 나머지 LGBM**: 전체 4.495→**4.399**·낮 7.92→**7.59**·D+1낮 5.87→4.15. 오버라이드 모델 = MAEα0(정확도) 또는 MSEα1.3(봄낮 bias +0.03, 가스체인 안전).
- **손실 ablation**: MAE>MSE(전체 MAPE) / MSE+α1.3>MAE(낮 bias, α≈1.2~1.3이 0점). 단발360·MSEα1.0·전면교체 기각.
- 결정: **production=LGBM v2 유지(현행)**, 하이브리드=업그레이드 후보(서빙 반영 미결). 상세 `5.../training/REPORT_5-B.md`, 메모리 [[land-demand-patchtst-hybrid]].

**2026-06-17 — 제주 2·3단계 새 DB 재설계 1단계: 진단·강건성·피처 확정 (G-20)**
- 무엇을: 제주를 육지처럼 새 DB 구조(`forecast_horizon`+`est_horizon_jeju`, `forecast` 폐기, `*_da`는 historical)로 옮기기 전, 현행 수요(2)·신재생(3) 모델을 jeju forecast_horizon 실예보로 처음 정직 재검증(육지 G-16 미러). SMP(4)는 범위 제외.
- **진단**: 육지 패턴 재현 — ORACLE 평평 바닥선(수요~4.1%·태양광nMAE낮~0.07·net_load~7.2%) vs 실예보 지평열화(수요 4.6→6.7%·태양광 0.102→0.180·net_load 8.75→15.14%). 격차=예보품질(특히 태양광). 수요 bias~0(육지 양bias 없음). → **모델 재설계 ROI 낮음**(2-A는 이미 v2 피처 보유=육지가 역수입, 신재생 열화는 비가역 예보스킬). 실질작업=서빙 전환.
- **전제 복구**: jeju KIMG 일사예보=`radiation_south` 단일지점→`forecast_horizon`에 west 일사 없었음(태양광 필수)→사용자가 west(+east) 180base 재수집.
- **강건성(D+1 8% 목표)**: 풍력=모델 천장근처(8% 비현실적, "겨울 헤드룸"은 이용률 크기 착시), east 풍향 실험→forecast 악화로 복귀(실측≠예보). 태양광=후처리 헤드룸 없음(잘 보정됨, 남은건 예보 분산).
- **피처 확정(사용자, LGBM 한정)**: solar_damping·clearsky south단독·wind_zone east단독(forecast 중립). **★야간 0 마스크**: pvlib 태양고도<5° 강제0(밤 가짜태양광 최대92MW→0, 여름 실일조 보존, net_load D+7 15.13→14.62%).
- 산출 `3. jeju_solarwind_forecaster/training/`(build_horizon_backtest_jeju·diagnose_horizon_jeju·exp_wind_east_dir·REPORT_horizon_diagnosis_jeju.md·parquet·fig 2). 백업 `lgbm_models/*_pre_simplify`.
- **★서빙 전환 완료(같은 날)**: `serve_chain_jeju_new.py` 신설(2→3→`est_horizon_jeju`, 육지 serve_chain_land_new 미러). 기상=forecast_horizon·day_type=공휴일달력·`forecast` 미접촉·야간마스크 자동전파. 검증 backfill 8 base→1344행 D+1~7. **다음=deploy 래퍼+crontab(사용자 수동)·streamlit 제주 소스전환(8-B)·전구간 backfill.**

**2026-06-15 — 전국 풀체인 지평 확장(D+15) + 기후값 블렌딩 + est_horizon_land (G-19)**
- 무엇을: 가스 성능 우려에서 출발해, "체인 전체를 forecast_horizon 전 구간에서 정직 검증해야 프로젝트가 완성된다"는 사용자 방침으로 5→6→7 전 단계를 D+15까지 정합·검증.
- **정직성 결함 발견·수정**: 수요 v2 lag168이 D+8 이상에서 "타깃−168h=원점보다 미래"라 실서빙 불가인데, 백테스트는 전 구간 과거라 그 값이 채워져 장지평 수요가 누설로 부풀려져 있었음. → lag168/336/504 가용성 NaN가드(h≤k & 과거)로 재설계(학습·서빙·백테스트 일관). 가스는 이미 동일 가드 보유.
- **지평 확장**: 수요(HMAX 168→360)·가스(288→360) 재학습. 솔라 PatchTST D14/D15 가중치가 디스크에 있으나 코드 미등록이라 잠자던 것 활성화(`SOLAR_PT_HORIZONS`·`LAND_HORIZONS`=1..15, 빈 지평은 LGBM 폴백 → 솔라/풍력 전 지평 가능).
- **풀체인 정직 백테스트**: `build_chain_horizon.py`(182 base×D+1~15)→ `est_horizon_land`(base·horizon_d·timestamp = forecast_horizon 양식, 64,939행, 미래 타깃 보존) 적재 = Phase 3 지평출력 테이블. 정직 가스(보정후) D+1 12.6→D+12 14.9→D+15 15.3%.
- **★ 하드규칙 변경**: G-16의 "백테스트 기후값 폴백 절대 금지"를 사용자가 해제("기후값=우리가 만든 평년 모델"). 가스 기후값(우리 historical 2022-24, doy±7일 슬라이딩×시각×요일유형)과 예보를 지평별 w로 블렌딩. final=(1-w)·예보보정+w·기후값, w 0(D+1~4)→0.5(D+15). 전체 13.96→13.72%, 여름 장지평 −3%p, 겨울·봄 무해(앙상블). MAPE 최소+계절 균형으로 선정(Option A 단조). 서빙·config 통합.
- 한계/남음: 평가창 겨울~초여름(여름=6월만·가을 없음)→데이터 쌓이면 블렌딩 w 재조정. 운영 forecast 스냅샷 재적재는 사용자가 서버에서 직접. 8단계 데모를 est_horizon_land 소스로 전환.

**2026-06-14 — 가스(7) v2: 자기회귀 다지평 + MIXED 비율 + 낮 비대칭(G-18)**
- 무엇을: 가스 모델을 5-A식 자기회귀 직접 다지평으로 전환(구 7-A2 동시점→가스 자기상관 lag168 0.78 활용). 사용자 통찰("가스도 과거 참고해 예측")+가용성 확인(가스=수요와 동일 마지막 실측, 누수 아님).
- **피처 분석(중요도·VIF·covariate shift)**: net_load 제외(수요와 VIF 126·r 0.986)·cap_btmppa 제외(가스 corr −0.016·연도 0.935·test 100% 외삽)·month 제외(doy와 VIF 145)·day_type 제외.
- **MW vs 비율 종합검토(사용자 지시)**: 가스·수요 정상(corr~0)→MW / 신재생만 표류(외삽 14%)→util. 전부-비율은 가스÷LNG_cap(100%외삽) 역효과(+6~9% 과대). **MIXED(신재생만 util) 채택**.
- **손실**=낮 과대 비대칭 α=4, **보정**=낮/밤 분리 지평별(전역보정이 낮교정 푸는 것 방지).
- 결과(v2 수요+가스 체인): D+1 13.02→12.22%·D+12 17.03→15.12%·**봄낮 24.46→19.77%·겨울낮 20.02→16.06%·여름낮 17.80→14.25%**(낮=사용자 1순위).
- production `train_gas_v2.py`·`lgbm_land_gas_v2.txt`·`serve_land_gas.py(v2)`·`REPORT_7_v2.md`·`exp_gas*`. 구 7-A2·드라이버only 7-A 보존. **다음=DB 체인 v2 재적재+Phase 3.**

**2026-06-14 — 수요(5) v2: 피처 엔지니어링 + 낮 비대칭 손실(G-17)**
- 무엇을: G-16 진단에서 수요가 낮(09-15h)·봄에 +6%대 체계 과대예측(가스로 전파)임이 드러나 수요 모델을 재정교화. 구조는 Global+Horizon 유지(pooled vs direct 실예보 동률), 피처·손실로 공략.
- **피처(사용자 확정)**: 단순 5평균 → 지점선택(일사=서산·영광/풍속=대관령·포항) + 구름(서산·영광) + **cap_btmppa(월별 PPA 용량)**. cap_btmppa 가 결정타 — BTM 듀크커브 신호가 land 5-A엔 통째로 빠져 있었음(제주 2-A엔 존재). 중요도 6.7%.
- **손실**: 커스텀 L2 비대칭(낮&과대 grad/hess ×8). ★land 부호 = 낮 과대를 아래로(제주식 반대, 복붙 금지 — 메모리 경고 데이터로 확인). 
- 결과(실예보 백테스트): 봄 낮 9.43%/+6.25 → **7.91%/+3.90%**(MAPE −1.5%p·bias 절반), 겨울 낮 8.10→6.23%, D+7 5.16→4.22%, D+12 6.37→5.48%, 밤·전체 무해. production backfill D+1 4.30→**3.56%**.
- 산출 `train_demand_v2.py`·`lgbm_land_demand_v2.txt`·`model_meta_v2.json`·`serve_land_demand.py(v2)`·`REPORT_5-A_v2.md`·`exp_{weather_agg,features,asym}.py`. 구버전 보존(롤백). **다음=가스 체인 전파+가스 동일 피처사고+Phase 2 보정 재적합.**

**2026-06-14 — 전국 지평 재검증·보정(G-16): "지평 평평"은 기후값 프록시 허상, 실예보로 정직 재측정 + 지평별 bias 보정**
- 무엇을: 사용자가 구축한 `forecast_horizon`(실예보 지평 아카이브, 육지 181 base·D+1~12)으로 5→6→7 체인을 처음으로 정직하게 재측정. 기존 7-A2-A 검증의 기상 입력이 사실상 전부 (월,시) 기후값 프록시였던 한계를 교체. **사용자 하드 규칙: 데이터 진짜 없을 때 기후값 폴백 절대 금지**(결과를 크게 망침) — ≤4h 보간(외삽 금지)만 허용, 진짜 결측은 평가 제외.
- **Phase 0 빌더**(`training/build_horizon_backtest.py`→`horizon_backtest.parquet` 21,358행): forecast_horizon[base] 실예보를 스크래치 connection으로 6단계 `_predict_day`에 주입(서빙 코드 무수정, con 인자 활용)·수요는 forecast_horizon 기상으로 5-A2 D{n} 재조립·가스는 7-A2 적용. D+7~12 3h 해상도는 ≤4h 보간으로 1h 복원(기후값 아님).
- **Phase 1 진단**(`diagnose_horizon.py`·`REPORT_horizon_diagnosis.md`·fig/tab): 가스 MAPE 실예보 **D+1 13.02→D+3 13.54→D+7 14.85→D+12 17.03%**(정직 상승) vs 프록시 13.0~13.2%(가짜 평평) vs **ORACLE(실측입력) ~10.3% 평평**. 수요 MAPE 3.55→6.49%·신재생 nMAE 15.8→39.8%(멀수록 악화). 격차=예보 품질→**가스 재학습 무효 재확인**.
- **Phase 2 보정**(`fit_calib.py`): 가스 bias가 지평의존(+4→+7.6%)이라 단일계수 불가 → **지평별 재적합**(송출량 물량 기준 Σ실측/Σraw). calib D+1 0.95594~D+12 0.93419, `serve_land_gas.py`가 dayahead 선형보간 적용(`_calib_for_dayahead`), freshest=근지평. 옛 0.96509=legacy 보존. backfill D+1 MAPE 13.07→12.93%·bias +3.2→+2.2%.
- 사용자 결정: 재학습은 보류(일단 보정, 이력 더 쌓이면 net_load 외 LGBM 모델들 재정교화 고려). **다음=Phase 3**: 지평별 서빙출력 이력 테이블 `est_horizon_land`(forecast_horizon 대칭)+8단계 데모를 실예보 지평 소스로 전환.

**2026-06-11(c) — 8단계 8-A: 디자인 개편 1차(브리핑 콘솔 테마) + 표준 날짜 컨트롤 + 기상개황 실측 병기**
- **디자인 시스템**: 기상개황 지도(weather_map.py)의 토큰을 전 페이지로 확장 — ink #0f172a / green #059669, Pretendard 본문 + IBM Plex Mono 수치. `.streamlit/config.toml` 네이티브 테마(라이트 캔버스 #f4f6f9 + **다크 잉크 사이드바**, 루트와 `8. streamlit/`에 동일 복제 — 항상 같이 수정) + `common.inject_style()` 전역 CSS(지표·차트·지도 iframe=흰 카드, 사이드바 radio=내비 메뉴, date_input 중앙정렬) + plotly 템플릿 "briefing" pio 기본 등록 + `page_header()`(eyebrow+체인 pill). **탭=알약 버튼**(기본 테두리 #94a3b8, 선택=다크 잉크 채움). 테두리 위계(사용자): 위젯 #94a3b8 / 카드 #cbd5e1 / 차트 그리드는 연하게 유지.
- **표준 날짜 컨트롤 `C.day_navigator(prefix, ndays=, refresh=)`** = "◀ 어제 | 날짜 | 내일 ▶ | 새로고침 | (기간 슬라이더) | 캡션", '오늘' 버튼 폐지. **종합은 탭별 독립 배치(사용자: 상단 공유는 디자인 무너짐 — 한 번 시도 후 번복)**: 예측확인/발전데이터/장지평=표준, 기상개황=refresh=False 슬림. 수요 예측=메뉴 상단 공통(ndays 1~7). 장지평=네비 행 오른쪽에 끝 날짜 select_slider(시작일 date_input 제거, 적재 밖 가드).
- **예측 확인 재배치(사용자)**: ⚙️ 표시 데이터 popover를 네비 행(새로고침 오른쪽)으로(`render_series_compare(gear_col=)`), 지표 4개를 plot 아래·AI 브리핑 위로 — 일별 송출량/최대·최소 시간당/가스발전 합(가스비 제거), 범례 캡션 제거. 헤더 제목="가스 송출량 예측 브리핑"·브라우저 타이틀="전국 가스송출량 예측 대쉬보드".
- **기상개황 과거·당일 실측 병기(A안 채택, B안 지도 토글은 보류)**: `_PREFIX` 매핑으로 historical(temp_c_/solar_rad_/wind_spd_)을 같은 권역 계산·같은 bin에 통과(`zone_actual`) + 이용률 실측 `national_util_actual`(KPX gen_*_utilization_kr, 같은 집계). 테이블 셀=`예보 → 실측`(과거 모드는 활성도 라벨 생략), metric delta=실측. 캡션에 "예보=rolling D+1 발행분" 정직성 명시. 실측 미적재는 예보만(제주 로컬 stale → 서버 배포 시 해소). 과거 날짜 est util 백필 없음 → 예측 "—"+실측만 나오는 날 있음(서빙 백필로 해소 가능).
- **버그 수정**: Leaflet 숨은 탭(크기 0) 초기화로 지도 빈 화면 → ResizeObserver+fitKorea 지연 맞춤. 데이터 현황 radio→segmented_control(재클릭 해제 None → `or` 기본값 폴백 필수).
- 검증=AppTest 스모크(메뉴·탭 전환·과거 날짜) 예외 0. **다음**: 사용자 화면 확인 후 잔여 폴리시 → 8-B(제주).

**2026-06-11(b) — 8단계: 기상개황 재설계(visual.md A안 + 활성도 실측 교정) + 데이터 현황 개편**
- **기상개황 전면 재구축**(`weather_map.py` 재작성, IDW choropleth 폐기): `9. design/visual.md` Decision Gate 사용자 확정 — **A안(Leaflet HTML 임베드**, 프로토타입 `renewable_capacity_map.html` 디자인 보존, 데이터만 렌더 시 주입) / **한 지도 모드 전환**(신재생 강도[용량×활성도]·일사·풍속 — HTML 내부 JS라 전환 시 rerun 없음) / 테이블은 러프. 기준 시간=**09–15시 평균**(일사·기온·풍속·강수, 시각 선택 없음), 권역 라벨=하늘상태 이모지+권역명·기온, 날짜=`day_navigator` 재사용, 지도=fitBounds로 전국+제주 자동 맞춤(한국 밖 이동·축소 잠금). 하단=전국 이용률 예측 metric(**평균+그날 최대**, `est_solar/wind_util_land`)+8권역 간략 테이블. 제주=jeju DB 고산(west) 실데이터(§7 보간 금지 준수), 기상 없으면 회색+이용률만 fallback. **DB 단위 함정: radiation=MJ/m²·h(W/m² 아님)·total_cloud=0~1 비율(0~10 아님)**.
- **활성도 bin 실측 교정(사용자 확정 3건)**: historical 2022-01~2026-06(1,620일) 5지점 평균 기상↔실제 전국 이용률(`gen_solar/wind_utilization_kr`) 역산. ① 태양광=경계 유지(0.2/0.4/0.6/0.8, spearman 0.68)+활성도를 기대 이용률로 교정(95%→**61%** 등 12/23/36/49/61) ② 풍력=파워커브 경계(3/6/9/13) 폐기(지점 평균 6년간 ≥9m/s 0일·68%가 "정지 0%" 오표시) → **ASOS 스케일 [2/3/4.5/6 m/s)=11/21/44/72/77%**(spearman 0.75) ③ 청천일사=월별 관측 P97. 강도맵 기준=최대 권역×최상 bin(SA/WA_MAX). **하늘상태 4분류 확정**: 맑음(운량<0.5)/약간흐림/흐림(≥0.85)/비(0.3mm/h, 겨울 눈) — 운량 0.5까지 일사 감쇄 미미(비율~0.7)·0.85부터 급락(0.26) 근거. 주의: 전국 기준 교정을 권역 단일 지점에 적용=**권역 간 상대 신호**(권역별 발전량 데이터 부재의 구조적 한계, 데모 수용).
- **데이터 현황 개편(사용자 사양)**: 컨트롤을 본문 탭 위로(historical/forecast radio + 과거 프리셋 1주~3개월/직접 선택[forecast는 미래 날짜 가능] + forecast 미래 지평 radio) + 탭 3개 — ① **fetcher 요약 히트맵**(계열별 대표 2~3개, `[ASOS 관측] solar_rad_seosan` 라벨: historical=ASOS/sukub/발전실적/DA·SMP/파생 이용률, forecast=KIMG/DA·SMP/서빙 5·6·7) ② **전체 피처 히트맵**(6시간 블록 적재율 0~1, 흰→초록, 행 없는 구간도 reindex로 0% 노출, 현재 시각 빨간 점선) ③ **DB 직접 조회**(기본 선택=fetcher별 대표 1개씩, multiselect). 헬퍼 `common.table_columns/table_range/coverage_heat`, 기존 신선도 요약은 expander. 구 `land_weather_at` 제거.
- **지평별 저장 구조 확인(사용자 질문)**: forecast 테이블=timestamp 단일 키 "최신 발행 스냅샷"(미래 구간 upsert 덮어씀 → 과거 행엔 사실상 D+1 발행분만 잔존). 지평별 이력은 7-A2-A `chained_gas_dataset.parquet`(D+1/2/3/7/12)뿐. DB 보존 원하면 (timestamp, horizon) 이력 테이블+서빙 append 후속 — 데모 검증엔 parquet로 충분.
- **8-A는 미완(사용자 강조 — 핵심 단계)**: 기능은 닫혔으나 디자인 품질 개편 필요. **다음 세션 = frontend-design 플러그인으로 디자인 수정** → 이후 8-B(제주, 선행=제주 서빙 백필).

**2026-06-11 — 8단계 보조: functions.md (1~7단계 CLI·산출물 레퍼런스) + API 매칭 원칙 + 검증 탭**
- 무엇을: 8-A 최종 다듬기에 앞서 `8. streamlit/functions.md` 작성 — 1~7단계 수집기·서빙의 "무엇을 받고 무엇을 DB에 쓰는가" 요약(수집기 2종+fetcher 허브, 제주 2/3/4·전국 5/6/7 서빙, KOGAS 환산).
- 핵심 정리: 단계별 `--days` 의미 차이 표(2-B·5-B·7=정수 범위 / 3·6-C=콤마 지평 목록 / 2-B backfill 기본 no-write), 앱이 읽는 핵심 컬럼 전국·제주 대응표, net_load_kr 오프셋 주의.
- **API 매칭 원칙(사용자 확정)**: ① 예측 조회=하루 단위(00~23시) ② 실측(fetch_kpx_land/fetch_land_power/fetch_kpx_jeju)=실시간 새로고침 가능(표시 전용) ③ 예측=DB 우선·없을 때만 제한 실행 ④ 시각화 주인공=예측 vs 실측 비교.
- **검증 탭 신설(수요 예측 메뉴, 사용자 선택=체인 스택 4행)**: 하루 단위 날짜 네비 + 수요/신재생/net_load/가스 4행 비교(실측 solid·예측 dot, x축 공유) + 패널별 MAPE·MAE·bias 배지 + 최근 30일 오차 추이 expander + 예측 없는 날짜는 "예측 생성" 제한 실행 버튼(서빙 5→6→7 subprocess). **신재생만 nMAE**(심야 분모≈0으로 일별 MAPE 81%까지 폭발 → nMAE 19.4%로 정상화, 6단계 보고서와 동일 처리). 실측은 `fetch_land_power`(가스·신재생)·sukub(수요) live 보강(`land_day_compare`).
- 30일 오차 추이 정합: 수요 3.3%·net_load 6.3%·가스 11.9%(체인 검증 ~13%와 일치).
- **종합 탭 개편(사용자)**: '현황' → **'예측 확인'** 개명. 검증 탭과 동일한 하루 단위 날짜 네비(공용 헬퍼 `day_navigator`, 기본=오늘) + 선택일 24시간 예측 기본 + 예측 없는 날짜 제한 실행 버튼(`missing_forecast_block` 공용화). plot은 **시리즈 8종**(수요/가스/신재생/net_load 각 실측·예측)을 ⚙️ popover 체크박스로 선택(기본 6종 on, net_load off). 실측은 sukub+발전실적 live 보강 — DB가 어제 19시까지여도 오늘 24h 전부 표시됨을 확인.
- **누적(발전 믹스) 보기 추가(사용자 제안=전력거래소식)**: stacked 5그룹 단순화(원전 기저→기타발전[석탄·수력·양수·유류·기타]→가스→태양광+풍력→BTM+PPA 추정) + **총수요 선**(수요는 쌓지 않고 선으로 — 이중계상 방지) + **가스발전 예측 dot 오버레이**(차별점). `land_day_mix` 로더(live 보강 동일). 검증: 06-10 14시 KPX 화면과 정합(원자력 19.1k·BTM+PPA ~16k·총수요 ~80k).
- **발전데이터 탭 분리 + 누적 다듬기(사용자 피드백)**: 누적믹스를 종합>**발전데이터** 별도 탭으로 이동(예측 확인=선 전용 환원, 사용자 "선은 완벽" 확정). ① 색 투명화(rgba 0.45) ② **예측 dot 누적기준 정렬** — 가스 예측=원전+기타 베이스 위, 태양광+풍력 예측=+가스 베이스 위(점선↔실측 띠 윗변 간격=오차) ③ **미수집 절단** — 가스≤0/결측 시간은 면적 미표시(0 수렴 절벽 해결, 오늘은 수집 시각까지만 그려짐) ④ **전력수요 예측 점선 추가** — 총수요 선과 같은 기준이 되도록 `est_true_demand_land`(계량수요 예측+BTM/PPA 추정, 6단계) 사용, 실선은 연한 회청(#455a64)·점선은 밝은 회청(#78909c)으로 조화(5/20 총수요 예측 MAPE 5.0%).
- **장지평 예측 탭 개편(사용자)**: 추상 "D+1~D+N" slider → **시작일 선택(기본 오늘) + 끝 날짜 슬라이더**(라벨 "MM-DD (D+k)"), 범위는 `est_demand_land` 실제 적재 한계에서 동적(cron 밀려도 거짓 범위 없음). **D+12는 보류**(슬라이더+D+12 버튼 안 대신): 5-B 수요 서빙이 D+7까지라 수요 입력이 필요한 가스 체인도 D+7 한계 — **후속 = 5-A2 D+12 모델 서빙 연결 후 확장**. 기상개황 탭은 수정사항 많아 다음 세션 계속(사용자).
- **비교 plot 공통화(사용자)**: 예측 확인·장지평 탭이 같은 컴포넌트(`render_series_compare`, ⚙️ 선택) 사용. 시리즈 8종→**9종**: +**KPX 수요예측(land_est_demand_da, dash 선)** — 전력거래소 하루전 수요예측과 직접 비교(기본 off). 데이터 레이어는 `land_day_compare`→`land_range_compare`(구간 일반화, live 보강은 오늘±3일·미래 제외). 장지평도 과거~오늘 구간은 실측 오버레이. 참고: 로컬 forecast의 land_est_demand_da는 마지막 수집일(06-10)까지만 — 서버 cron 운영에선 매일 갱신.
- **시간 선택 통일(사용자)**: ① 장지평 시작일 **과거 개방**(적재 시작 02-02~, 끝 날짜 슬라이더 최대 14일 창, D+표기는 미래만) ② **수요 예측 메뉴 = 공통 시간 컨트롤**(◀ 전일/날짜[과거 가능]/익일 ▶/오늘/새로고침 + 기간 슬라이더 1~7일)을 4개 탭(전력수요/순수요/천연가스/검증)이 공유 — 검증 탭 자체 네비 제거, 구간 기준 지표로 전환 ③ 전력수요 탭에 **KPX 수요예측(DA) dash** 추가(전력거래소 비교).
- **장지평 지평 모드(사용자 질문 "5/20+14일=??"에서 발견·해결)**: forecast 테이블은 timestamp당 1값이라 과거 구간은 rolling D+1 백필 — "과거 고정 origin 장지평"이 아니었음(중요 정직성 이슈). 해결 = **과거 시작일이면 지평 radio(D+1/2/3/7/12) 모드**: 7-A2-A `chained_gas_dataset.parquet`(지평별 수요·신재생, 2022-01~)에서 읽고 가스는 7-A2 모델 즉석 계산(serve_land_gas 자산 재사용, `land_horizon_compare`). 가스 MAPE 지표로 **지평 평평을 화면에서 입증**(5/20 시작 2주: D+7 발행 12.6% ≈ D+12 12.5%). 미래 시작일은 기존 고정 origin 모드.
- 참고: 사용자가 `9. design` 재구성 중(기존 자산 `old design/` 이동, `renewable_capacity_map.html`·`visual.md` 신규) — weather_map은 두 경로 탐색 + 부재 시 안내로 방어(다음 세션 기상개황 개편 예정).
- **기상개황 인포그래픽(사용자 요청=그래프 대신 지도 한 장)**: `weather_map.py` 신설 — 시도 choropleth(5지점 예보를 IDW로 17개 시도 보간 → 서울 포함 전 국토 커버) + 신재생 중요지역 원(태양광 주황 2025·풍력 청록 2023, `9. design/태양광_풍력_지역별_TOP5.txt` 비중∝크기·진하기) + 수집 5지점/참고 13지점 마커(`reselected_asos_map.html` 좌표). 컨트롤=오늘·내일/변수 3종/시각 slider + 5지점 카드. 시도 경계는 southkorea-maps geojson을 0.24MB로 단순화해 동봉. IDW 검증: 서울 17.1(원주15·서산20 사이)·강원 13.0(대관령10 쪽) — 타당.
- 다음 세션(사용자 지정): **기상개황 + 데이터 현황 수정**(기상개황은 `9. design`의 신규 `renewable_capacity_map.html`·`visual.md` 참조) → 이후 8-B(제주, 선행=제주 서빙 백필).

**2026-06-10 — 8단계 착수: G-15 확정(8-0) + 가스 백필 + 8-A 전국 체인 대시보드**
- 무엇을: `CONCEPT_8-0.md` 기준으로 G-15 5건 확정(§7) 후 8-A 구현. ① 배포=자체 서버(로컬 DB 실시간 읽기) ② brief_ai=Gemini ③ 사전 적재 기본+시연 버튼 병행 ④ 표시 기간=데이터 보유 범위 ⑤ SMP 데모 제외(제주는 net_load까지).
- **데이터 점검·백필**: `est_gas_gen_land`가 2026-06-01 하루(24행)만 적재된 공백 발견 → `serve_land_gas.py backfill 2026-02-01~05-31`(D+1) 적재, 발전량 MAPE 13.02%·bias +3.1%(7-A2-A 13.07% 재현). 제주는 `jeju_est_demand_lh` 컬럼 부재·`est_net_load_jeju_lh` 1주뿐 → **8-B 전에 제주 서빙 백필 필요**.
- **8-A v1**: 단일 `app.py`(기준일 선택 + 체인 차트 스택). 사용자 디자인 개편 요청으로 같은 날 v2로 대체.
- **8-A v2(확정 디자인, 사용자 설계)**: **멀티 페이지(전국/제주, st.navigation)** + 사이드바 radio 메뉴 — **종합**(현황: 일일 송출량+수요실측 solid·가스예측 dot 오늘 24h+KPX sukub 실시간 새로고침(표시 전용)+AI brief 자리 / 기상개황: 간략 / 장지평: slider D+1~7+송출량 합)·**수요 예측**(공용 slider+탭3: 전력수요/순수요/천연가스)·**데이터 현황**(적재·신선도 테이블)·**SMP 예측(제주만, G-15 ⑤ 번복)**. 선 규약 실측=solid·예측=dot. 파일 `app.py`+`common.py`+`page_land.py`+`page_jeju.py`. 상세 `CONCEPT_8-0.md` §3.4.
- **사전 적재(체인)**: origin 2026-06-09에서 5(`--days 7`=D+1..7 범위)→6(`--days 1,..,7`=지평 목록·의미 다름 주의)→7 실행, 06-10~16 168h 적재(가스 평균 17,213MW·송출 439,841TON). 6·7의 `--days` 의미 차이로 1차 실행이 D+7만 적재됐던 것 수정.
- AppTest 검증: 전국 3메뉴(sukub 실시간 수신 확인)·제주 4메뉴 전부 예외 없음, 장지평 합계가 서빙 출력과 일치(439,841TON).
- 다음: 8-B(제주 종합·수요·SMP, 선행=제주 서빙 백필) → 8-C(검증·KOGAS) → 8-D(brief_ai·시연 버튼) → 8-E(배포·시연 영상).

**2026-06-10 — 7단계 체인 검증(5→6→7): A안 재학습 기각·bias보정 채택·서빙 신설 + BTM/PPA 결정(G-14)**
- 무엇을: 5(수요)→6(신재생)→7(가스) 연계·정확도를 EDA 건너뛰고 입력 건전성 중심으로 점검. 7-A2를 서빙(예보) 입력으로 재학습(A안) 시도 + 다른 모델과 동일 지평(D+1/2/3/7/12) 검증.
- **연계 점검**: ① 정의 건전 — `renew_gen_total_kr`=`gen_solar_market_kr`+`gen_wind_kr`(잔차 std 0) → 6단계 `est_market_renew_land`가 7 학습피처의 올바른 짝. ② **5→6 단절 발견·복구** — forecast에 `est_demand_land` 컬럼이 없어 6단계가 KPX(`land_est_demand_da`) 폴백 중이었음. `serve_land_demand.py backfill --days 1 --write`로 적재(D+1 MAPE 4.15%). ③ 데이터 제약: 진짜 forecast 기상은 2025-12부터만 존재 → train창은 체인 백필(기후값 폴백)로 생성.
- **체인 데이터셋**: `7. land_gas_forecaster/training/build_chained_dataset.py` → `chained_gas_dataset.parquet`(193,800행, train130,920/val43,800/test19,080). 수요=5-A2 지평별·신재생=6단계 `_predict_day` 지평별·기상=예보→(월,시)기후값·타깃=실측 gen_gas_kr. 입력 bias 전구간 수요 −220~−317MW·신재생 −50~−68MW.
- **★ A안 기각(정직한 음성결과)**: 체인입력 재학습(`retrain_7a2a.py`→`lgbm_land_gas_util_chained.txt`)이 현행 7-A2보다 0.3~0.4%p 나쁨. 체인입력 bias는 작고(수요 0.5%) 진짜오차는 분산(노이즈)→errors-in-variables 감쇠; train(기후값)↔test(실예보) 노이즈구조 차이로 정렬이득 없음. → 미채택(실험 파일만 보존).
- **★ 결과·채택**: test 2026 지평별 가스 MAPE — ORACLE(실측입력 상한) 10.81% / 현행+체인 13.88(D+1)~14.16(D+12)% / A안 14.23~14.58% / **채택=현행 7-A2+전역 bias보정 ×0.96509(val2025) 13.08~13.16%**. **지평 거의 평평**(D+1≈D+12, 입력품질이 지평별 비슷)→D+12까지 D+1 수준. 남는 +2.2%p(vs ORACLE)=예보 전파 비가역오차(§5.4).
- **서빙 신설**: `serve_land_gas.py` — forecast.est_demand_land·est_market_renew_land 읽어 util×LNG_cap×보정 → `est_gas_gen_land`(MW)·×0.1521 → `est_gas_sendout_ton_land`(TON) UPSERT. 검증(D+1 백필 2026-02~05) 발전량 MAPE 13.07%·bias +3.2%. 보정·변환계수 `model/gas_serving_calib.json`.
- **모델 피처 재확인**: 입력=real_demand_land(←5 est_demand_land)+renew_gen_total_kr(←6 est_market_renew_land=시장 solar+wind)+달력4(hour/dow/month/doy)+day_type / 타깃 util=gen_gas_kr/LNG_cap→×용량×보정. 제외=기온·year·net_load(분해 내포)·HVDC·유류·타깃lag(누수).
- 산출 `model/7-A2-A_chained_validation.ipynb`·`REPORT_7-A2-A.md`·fig/tab(7a2a_*)·`gas_serving_calib.json`·`serve_land_gas.py`·`training/{build_chained_dataset,retrain_7a2a}.py`.
- 다음: 8단계 Streamlit 데모(5→6→7 체인 + brief_ai)는 별도 결정.

**2026-06-08 — 6단계 전국 신재생 착수: G-13 확정(구조·지점·지평) + 6-0 EDA 진행**
- 무엇을: 6단계(land_net_load) 시작. 사용자 제공 지역별 발전 TOP5 + DB 5지점(대관령·원주·서산·포항·영광) 매핑·상관 분석 후 G-13 확정.
- 지점 상관(탐색): solar_rad↔solar_util(낮) 영광0.754·서산0.722·원주0.709·포항0.690·대관령0.656 / wind_spd↔wind_util 대관령0.607·영광0.449·서산0.424·포항0.345·원주0.314. **용량 표류 solar_cap 2,746→9,441MW(3.4배)·wind_cap 1,208→1,617MW** → 이용률 정규화 필수.
- 결정(G-13): LGBM-direct 다지평 주력 + PatchTST D+1~3만 비교, D+1~D+12, 이용률 정규화. 지점 solar=영광+서산+포항·wind=대관령+영광+포항(사용자 확정). 후처리 불가(forecast에 강수·cape·tcog 없음).
- **6-0 EDA 완료(G-9 통과)**: ① 이용률 정의 = **시장 태양광 기준**(util×cap=gen_solar_market_kr 상관 1.000, BTM/PPA는 수요에 숨음), net_load 재구성=수요−util×cap (DB net_load_kr와 corr 0.946·평균차 −667MW) → 서빙공식 타당. ② 용량표류 solar 3.44배→정규화 필수, **2022 낮 이용률 0.273 급락**(설비 준공 전 용량 계상 의심, 6-A에서 점검). ③ 공간평균이 단일지점보다 우수(solar 0.786·wind 0.641) → G-13 검증. ④ 풍력 자기상관 lag24 0.447→lag48 0.243 붕괴→direct 근거. ⑤ 흐린/맑은 이용률비 0.51. ⑥ 후처리 불가 확정(forecast에 습도·강수·적설·cape/tcog 없음). ⑦ covariate shift 안전. 산출 `eda/6-0_eda_landsw.ipynb`·`REPORT_6-0_eda.md`·그림5·표4.
- **humidity·rainfall backfill 완료(2026-06-08)**: forecast에 reh·rainfall 5지점 추가(NaN 1.7%, 2025-12-13~). historical은 전 기간 가용 → **6단계 후처리 제약 해소**(rainfall로 solar_damping 부활). 메모리 land-forecast-reh-rain 참조.
- **공선성·중요도 분석(태양광 후보)**: rad·cloud·humidity·solar_damping·clearsky_ratio가 전부 '맑음' 축으로 공선(rad↔clearsky 0.71). VIF clearsky 15.0·humidity 12.0(>10 위험), LGBM gain rad **79%**·나머지 1~3%(perfect 기상 기준 — forecast에선 보완 가능성). 측정 일사가 실제 구름을 이미 반영해 대리변수 한계기여 작음.
- **LGBM 최종 피처 확정(2026-06-08, §0.6)**: **SOLAR = solar_rad + total_cloud + solar_damping(일강수 06-20h합 exp(−k·clip)) + hour·doy(sin/cos), 선택3지점 평균** / **WIND = wind_spd + wd_sin/cos + hour·doy(sin/cos), 선택3지점 평균**. clearsky_ratio·humidity 제거(공선성·중복, 사용자 확정), temp·midlow 미채택, year 미채택(2026 외삽). **solar_damping은 유지**(강수 event = rad 직교정보, perfect 중요도 작아도 forecast 검증 예정). PatchTST 피처는 6-B에서 별도(3지점 raw 시퀀스). **이용률은 lag 없어 지평무관 단일모델(채널당)이 D+1~D+12 전부 서빙.**
- **6-A LGBM-direct 완료**: 시장신재생 이용률 채널별 단일모델(지평무관→D+1~D+12 단일서빙). 공선성 해소 후 VIF<4. 중요도 SOLAR rad 80%·WIND spd 56%. **util MAE: SOLAR 낮 perfect 0.112/forecast 0.127·WIND perfect 0.099/forecast 0.143**(예보 풍속오차로 악화, 제주 동형). **solar_damping 검증 성공: forecast full 0.127<rad-only 0.135**(perfect 중요도 0.7%여도 forecast 보완 — 현장 직관 적중). **net_load nMAE(일관 기준=수요−시장신재생): perfect 0.96% vs 기후값 1.51%·forecast 1.07% vs 1.44% → 베이스라인 상회.** 산출 `model/6-A_landsw_lgbm_direct.ipynb`·`REPORT_6-A.md`·`lgbm_land_{solar,wind}_util.txt`·표3·그림1.
- **★ net_load 정의 규명**: `net_load_kr = gen_total_kr − renew_gen_total_kr`(차이 0), renew_gen_total = **시장 태양광+풍력만**(BTM/PPA·nre·수력 제외, 총발전 기준). 우리 산출물=수요기준 신재생예측이라 ~3,550MW(손실·양수)+BTM/PPA 상수 오프셋. **7-A는 net_load_kr 직접 안 쓰고 real_demand+renew_gen_total 피처 → 6단계(신재생)+5단계(수요) 체인 정합.** net_load_kr은 참조 컬럼.
- **6-A2 전체 신재생(true_renew) 완료**(사용자 지적: market만으론 net_load 불충분, BTM/PPA가 net_load 크기·대체효과에 영향): BTM/PPA는 시장 태양광과 **같은 이용률 공유** → **utilization×capacity 통합**(`total_solar_cap = market_cap + k(1+r)·ppa_cap`, k=0.7108·r=0.3152, 7-0b backfill 재현). 6-A 모델 재사용. **검증(측정구간 2024-11+): util×cap 복원 vs 실측 PPA+BTM MAE 235MW(6.4%)·corr 0.996, 내포 PPA이용률↔시장이용률 corr 0.99**(같은 이용률 가정 실측 확인). 유효 총 태양광=시장 3.35배.
- **★ net_load 산술 동일·신재생 분해가 핵심**: `net_load_true = true_demand−true_renew = net_load_market`(BTM/PPA 상쇄, 평균차 0.0). 진짜 다른 건 **신재생 총량 ~2.8배**(2025 market 2,006→true 5,566MW)이고 이것이 7-0b 대체효과(−0.332) 신호. → 6단계 산출 2종: **est_market_renew(→7-A) · est_true_renew·est_true_demand(→7-Ar)**.
- **true_renew 정밀도(test 2026, PatchTST 판단 근거)**: market MAE 564MW(23.7%)/forecast 664MW(27.9%), **true MAE 1,836MW(27.4%)/forecast 2,112MW(31.6%)**. 복원 근사 하한(util 실측) 393MW → 나머지 ~1,440MW가 util 예측오차. **net_load엔 PatchTST 무의미였으나 true_renew(태양광 지배)엔 정밀도가 작동** → 6-B PatchTST 검토가치 생김. 산출 `model/6-A2_true_renew.ipynb`·`REPORT_6-A2.md`·`btm_ppa_recon_6a2.json`.
- **6-B 범위 확정(사용자, 2026-06-08)**: **풍력=LGBM D+1~D+12 확정**(제주와 동일, 비교 안 함). **태양광만 PatchTST vs LGBM을 D+1/D+2/D+3 비교 후 결정**(true_renew에서 태양광 정밀도가 작동한다는 6-A2 근거). 근거: net_load는 PatchTST 무의미였으나 true_renew(태양광 지배·×3.3)에선 util 예측오차(~1,440MW)가 큰 덩어리. land solar PatchTST 가중치는 제주처럼 사용자가 GPU/Colab 직접 학습(3지점 raw 시퀀스, direct D1/D2/D3 offset 0/24/48). 인프라(export CSV + Colab 노트북 생성기)는 `6. land_solarwind_forecaster/training/`에 제주 패턴 미러링.
- **6-B 완료 — 태양광 PatchTST 큰 차이로 우세(제주와 다름)**: 사용자 학습 가중치(landsolar_patchtst, d_model=128·layers=3·d_ff=512 변경, 14피처 3지점 raw, D1/D2/D3 direct). 동일 test 2026, PatchTST(과거336h+대상일기상) vs LGBM 6-A(기상-only 지평무관). **낮 util MAE: PatchTST perfect 0.038~0.041 vs LGBM 0.112~0.115(~2.8배), forecast 0.070~0.074 vs 0.129~0.131(~1.8배)**. 흐린날도 우위. **true_solar MW MAE(낮) forecast PatchTST ~2,000MW vs LGBM ~3,700MW(~1,700MW 개선)** — true_renew 정밀도 핵심(6-A2)이라 결정적. 우위 상당부분은 past_y(실측 이용률 시퀀스, 서빙 가용=반칙 아님). LGBM 수치는 6-A와 정확 일치(검증). 산출 `model/6-B_compare_solar.py`·`REPORT_6-B.md`·`tab/6-B_compare.csv`·`fig/6-B_compare.png`.
- **채널 분리 확정(G-13 충족)**: **태양광 = PatchTST(D+1/2/3) + LGBM(D+4~D+12 폴백)** 하이브리드(제주 동형) / **풍력 = LGBM 전지평**. 가중치 `training/landsolar_patchtst/`(D1/2/3 + scaler + metadata).
- **6-C 서빙 완료 — 6단계 종료**: 사용자가 PatchTST solar **D+1~D+7, D+12** 학습(이 지평만 서빙). `serve_solarwind_land.py`(자기완결): **태양광=PatchTST(D1~7,D12)+LGBM 폴백·풍력=LGBM 전지평**. 산출 `est_solar/wind_util_land`·`est_market_renew_land`(→7-A)·`est_net_load_land`·`est_true_renew_land`·`est_true_demand_land`(→7-Ar, ×total_solar_cap). 기상 forecast 우선·기후값 폴백, 수요 est_demand_land(5단계)→KPX 폴백. **검증(백필 D+1 2~5월): SOLAR util MAE(낮) 0.087**(PatchTST 재현, LGBM 0.129 우위)·WIND 0.139(6-A 일치). CLI predict/backfill. 산출 `serve_solarwind_land.py`·`REPORT_6-C.md`.
- **wind PatchTST 미연구 결정(사용자 질의)**: 풍력 자기상관 24h 붕괴(past_y 무력)·제주서 forecast 악화·true_renew 비중 작음(태양광 지배)·예보 풍속오차는 모델 무관 → 풍력은 LGBM 유지.
- **다음: 8단계 Streamlit 데모**(신재생→net_load→가스 + brief_ai). 선택: 5단계 serve로 est_demand_land 적재 시 6-C 수요 자동 end-to-end.

**2026-06-08 — 3단계 net_load 점검: PatchTST vs LGBM 비교(흐린날 과대예측·장지평) → 6단계 골격 시사**
- 무엇을: 6단계(land_net_load) 착수 전, 3단계 제주 net_load 예측기(PatchTST 기반)의 성능·장지평 가능성·흐린날 과대예측을 LGBM과 비교. 산출 `3. jeju_solarwind_forecaster/comparison/`(eda·model·fig·tab + `REPORT_3cmp-0_eda.md`·`REPORT_3cmp-B_comparison.md`).
- 설계(사용자 확정): 평가=이용률+net_load 둘 다 / 기상=실측(perfect) 우선·forecast 보조 / PatchTST 장지평=재귀 롤링 / LGBM=순수기상 horizon-무관 단일모델. **피처(§0.6 확정)**: SOLAR=PatchTST피처(solar_rad·cloud·midlow·damping west·south)+clearsky_ratio+month, WIND=PatchTST 동일(spd·zone west·east+풍향+hour+year).
- 3cmp-0 EDA(G-9 통과): 용량 표류 큼(solar 254→405·wind 258→364MW)이나 이용률 정규화로 연도 안정. solar_rad +0.88·cloud −0.54 주구동. **흐린날(1109일)>맑은날(536일)**, 흐린날 정오 이용률 ~0.33 vs 맑은날 ~0.80. **wind 자기상관 24h 후 급붕괴(0.31→0.11)** → 재귀 롤링 wind 장지평 불리 근거.
- **핵심 결과 ① 실측기상**: solar/net_load MAE 사실상 동률. PatchTST는 재귀 롤링이라 지평 늘수록 음의 bias·MAE 열화(D+1 net_load nMAE 6.6%→D+6 6.9%), LGBM은 평평(7.2%→7.1%). **실측기상에선 흐린날 과대예측 없음**(PatchTST −0.005·LGBM +0.008) → 사용자 관찰은 모델 탓 아님.
- **핵심 결과 ② forecast(실서빙 D+1)**: 흐린날 과대예측 재현(PatchTST +0.054·LGBM +0.078·ablation +0.057) → **원인=forecast 기상 오차(공통), LGBM도 해소 못 함**(clearsky_ratio가 틀린 예보일사 증폭해 근소 더 심). net_load는 **LGBM 우위(10.6% vs 11.3%)**, wind 예보편차도 PatchTST가 크게 증폭(+0.12 vs +0.07) → LGBM이 forecast에 견고.
- 결론: D+1 단기=PatchTST 강점, **장지평·실서빙 견고성=LGBM-direct 우위**. 흐린날 과대는 forecast 보정 과제(모델 교체 무관). → **6단계 전국 net_load는 LGBM-direct 단일로 시작 권고**(land 5·7과 일관).
- 후처리 확인(사용자): 구버전 solar_sigmoid 후처리는 **`solar_damping` 피처가 대체**(비교에서 양쪽 적용됨), wind cut-off(25m/s↑→0)는 **wind PatchTST가 이미 학습**. → 비교 재실행 불필요·유효.
- **하이브리드 결정(사용자)**: 실사용 핵심 **D+1~D+3=PatchTST**(D+2/D+3는 **direct 지평별 재학습**, 재귀 롤링 아님) + 시연 장지평 **LGBM-direct**. 통합 서빙 wrapper로 묶음(2·5단계 이원 구조와 일관). **3cmp-D 학습노트북 `training/train_solarwind_direct_d2d3_colab.ipynb`+생성기 `_gen_notebook_direct.py`**(Dataset future/target에 offset만 추가, 아키텍처·피처·손실(흐린날 과대페널티 포함)·스케일러·metadata 전부 D+1과 동일·재사용. HORIZONS 딕셔너리만 수정=offset 24배수 일경계. 사용자가 GPU로 D2~D6 학습 중). PatchTST/LGBM 경계는 노트북 지평별 test MAE로 실측 결정(경험상 ~D+3~4).
- **지평 범위(사용자 확정)**: 제주는 **D+7까지**, 전국 6단계는 **D+12까지**(land 5-A2와 일관).
- **LGBM 서빙 본체 완성(3cmp-E)**: `serve_solarwind_lgbm.py`(+`lgbm_models/`). **util은 지평 무관(lag 없음)이라 단일 모델 1개(채널당)가 D+1·2·3·7 전부 서빙** — 지평별 가중치 불필요(수요 5-A2와 결정적 차이). forecast 기상 우선·없으면 (월,시) 기후값 폴백(2-B·5-B 패턴). net_load=수요(forecast)−gen. 출력 `est_*_jeju_lgbm`(PatchTST D+1 출력과 분리). 검증: 폴백 정상, 서빙 정확도=3cmp-C(낮 solar MAE 0.109·wind 0.129) 일치, DB write 확인.
- **피처 중요도(LGBM)**: solar=rad_west 57%+hour 18%+clearsky_ratio 14%(상위3=88%), wind=spd_west 57%+spd_east 17%+year 11%. wind_zone 거의 미사용(풍속 clip20로 cutout 표현 약함, 극단풍속 희소라 영향 작음).
- **ramp/vol 피처 실험·기각(사용자 제안)**: 실측기상선 wind +5.5% 개선이나 **forecast에선 악화**(0.131→0.133) — 예보 풍속이 매끄러워 ramp가 노이즈. solar는 애초 무효. → 서빙=base 피처 유지(2단계 QM 교훈과 동형).
- **forecast 전용변수 분석(3cmp-2, 사용자 제안)**: cape/hpbl/gust/cinn/tcog는 모델입력 불가(historical 없음) → 후처리 후보. **데이터품질: cape 83%·cinn 97%가 9999 sentinel·tcoh 상수0**(허위상관 주의). **tcog(대류운)만 의미**: 대류일(tcog>0, ~7%) solar 과대(−0.069)·wind 과소(+0.132)로 양채널 일관·해석 명확. cape/cinn/tcoh/gust/hpbl 미사용. → **후처리는 서빙 본체 다음, tcog 1개만 가볍게, 평가는 랜덤스플릿(계절 골고루, 사용자 지시)**. 산출 `comparison/REPORT_3cmp-2_*`.
- **3cmp-G direct PatchTST vs LGBM(가중치 D2~D6 학습 완료, `solarwind_patchTST_pkl/`)**: 실측기상 test 2026. **핵심: 지평이 아니라 채널로 갈림** — SOLAR=PatchTST 우위(실측 D+1~5·forecast도 흐린날 포함), WIND=LGBM 전지평 우위(PatchTST는 forecast 풍속오차 증폭). direct solar D+2 최저(0.0625), direct wind는 D+3+ 악화.
- **하이브리드 확정·완성(사용자, 채널분리)**: **solar=PatchTST(D+1~6 direct, D+7+ LGBM 폴백) + wind=LGBM 전지평**. 통합 서빙 **`serve_solarwind_hybrid.py`**(단일 진입점 D+1~7, solar direct는 offset이 origin↔target 메워 재귀 아님, wind/cap/demand/폴백은 serve_solarwind_lgbm 재사용, 출력 `est_*_jeju_lh`). **end-to-end 검증(forecast D+1): 하이브리드 net_load nMAE 13.63% < LGBM단독 14.10%**(채널분리가 두 단독보다 우수). DB write 확인. 산출 `comparison/REPORT_3cmp-G_hybrid.md`·`tab/3cmp-G_*`·`fig/3cmp-G_*`.
- **D+7 solar PatchTST 반영(2026-06-08)**: 사용자가 D+7 가중치 추가학습(`solarwind_patchTST_pkl/_D7`) → 하이브리드 `SOLAR_PT_HORIZONS=[2..7]`, solar D+1~7 전부 PatchTST. (D+7 solar 실측 MAE PatchTST 0.0702 vs LGBM 0.0663 — LGBM 근소우위지만 단순화 위해 PatchTST 통일, 사용자 수용. D+8+ LGBM 폴백.)
- **tcog 후처리 완성(3cmp-3, 가볍게)**: 대류일(tcog>0, ~7%) 보정 `corrected=clip(pred+beta*tcog_station,0,1)`. **지점 선택(잔차적합 비교+사용자 직관)**: **solar=tcog_south(beta −0.074, 대류일 MAE −10.1%)·wind=tcog_east(beta +0.062, −10.7%)**. 단일지점이 평균보다 우수(south는 태양광 용량 집중·사용자 직관 일치; **west는 wind 모델 주피처(57%)라 잔차에 잉여 → east가 직교정보**). **5-fold 랜덤스플릿(계절 골고루, 사용자 지시) 검증, 비대류일 무해.** `serve_solarwind_hybrid.py` 토글 `APPLY_TCOG`로 통합(`est_*_jeju_lh`, src 태그 `+tcog`), beta·지점=`lgbm_models/tcog_postproc.json`. cape/cinn/tcoh/gust/hpbl 미사용(3cmp-2: cape 83%·cinn 97% 9999 sentinel·tcoh 상수0).
- **3단계 점검·하이브리드 작업 종료**. 남은 것: 6단계 land_net_load에 채널분리(solar=PatchTST·wind=LGBM) 골격 이식(전국 D+12, land 재학습 필요 여부 EDA 후).

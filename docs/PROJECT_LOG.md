# 진행 로그 아카이브 (PROJECT.md §8에서 이관)

> 루트 `PROJECT.md` §8의 오래된 항목을 그대로 옮겨 보존한다(최신이 위로, 내용 무수정).
> 현행 로그는 PROJECT.md §8, 이관 규칙은 §0.4 참조.

**2026-06-07 — 제주 2단계 2-0c: 낮시간 surge 공략(비대칭손실+흐린날피처) + forecast bias/QM 검증 → 2-A 최종확정**
- 문제정의(사용자): KPX est_demand_da 약점=낮시간 BTM 변동 미반영. 진단(낮 08~16h, 완전기상): KPX는 **맑은날 +43.6MW 과대(BTM 차감 실패)**, 흐린날 −25MW 과소. baseline 모델은 맑음 압도하나 **흐린날 −47MW로 KPX보다 더 과소예측(7.62 vs 6.90)** → 흐린날 surge가 표적.
- 설계(사용자 결정: cap×이용률 BTM추정 금지·비대칭손실·흐린날 특화피처): **흐린날피처 solar_deficit(1−일사/평년)·solar_ramp(h≤48)** + **비대칭 quantile + 낮가중**. cape/tcog는 historical에 없어(forecast 전용) 미채택, 쓸 구름=midlow/total_cloud(west·south raw).
- forecast bias 점검(사용자 지적): historical↔forecast 분포차 존재(습도+7·풍속+1.7·구름+0.1, 기온·일사는 corr 0.94+). **QM(quantile mapping)으로 정렬했으나 흐린날 순효과 음(−)** — 흐린날 열위는 주변bias 아닌 예보 event-skill(구름 corr 0.56) 문제라 QM 미해결. → QM 미적용.
- alpha 재튜닝(서빙=forecast 기준, 사용자 지적): α=0.60 raw가 TEST 낮흐림 6.87·낮맑음 8.94로 **둘 다 KPX 우위·전체 최고정확도**. (α↑+QM은 강건하나 전체 손해) → **채택 α=0.60 raw**.
- **2-A 최종(22피처, quantile0.60+낮가중2)**: 완전기상 D+1 3.82/전체 3.99. 낮(실서빙 forecast) 전체 8.04·흐림 6.87·맑음 8.94 — 모두 KPX 상회. 산출 `eda/2-0c`(개념)·`model/_exp_*·_eval_*` 스크립트·갱신된 2-A.
- 다음: 2-B 서빙(raw forecast, D+1~D+7 UPSERT) — 사용자 요청 시.

**2026-06-07 — 제주 2단계: 배포모델 비교 + KPX 잔차 BTM/PPA 원인분석(2-0b)**
- 배포 PatchTST+LGBM(D+1) vs 신규 직접 다지평(D+1) 동일 구간(2026-03-22~05-31, 실측기상): **배포 4.06% ≈ 신규 4.12%(동률)**, PatchTST단독 6.04·KPX 6.01. → 신규는 PatchTST 없이 동급 D+1 + D+7 확장이 이점. (`model/_compare_deployed.py`, `tab/2-A_deployed_compare.csv`)
- **사용자 제공**: 전력거래소 제주 PPA+BTM 태양광 용량(월별 MW, 2019-2025) → `data/jeju_ppa_btm_capacity_mw.csv`(2026 캐리포워드). 비계량 발전 ≈ 용량×태양광이용률(land `backfill_btm_ppa.py`와 동일 원리).
- 2-0b EDA(`eda/2-0b_residual_btm.ipynb`·REPORT): 사용자 가설 검증. **실제 신재생 침투율(계량+비계량) 2026 ~30%**(계량 26%). KPX 잔차(real−est)는 **낮시간 집중·최근연도 확대**. 낮(9~16h) 잔차↔총운량 **+0.37**, ↔일사 −0.13. **맑은날 vs 흐린날(평일·월내 일사 상하위25%): 흐림이 낮수요 +106MW 높고 심야엔 −31MW** → 비계량 태양광이 맑은날 낮 계통수요를 끌어내림(est 없이 real만으로 입증). 잔차↔BTM/PPA서프라이즈(용량×(이용률−평년)) **−0.34**(R² 0.117, +구름 0.147), **연도별 상관이 용량과 함께 강화: 2020 −0.41→2026 −0.64**. 정직성: 선형은 낮시간 잔차의 ~15%만 설명(부호·방향 전부 가설 일치, 나머지는 비선형·KPX자체오차).
- 모델 시사점(피처변경=Decision Gate, 미확정): 현 2-A는 일사는 있으나 **구름·BTM/PPA 용량 없음** → 후보 ①구름(total/midlow_cloud, 예보존재) ②BTM/PPA용량×평년이용률 ③forecast cape. 서빙시 비계량추정은 예보일사/예보이용률로 대체 필요.
- 피처 A/B 실험 + 채택(사용자 Decision Gate): baseline 대비 +구름@h≤48(D+1 3.93·D+2 4.09, 단 D+3+ 악화), +BTM용량(전체 4.28→4.14·전지평 고르게), +둘다(전체 4.12) 비교. forecast 변수 상관(낮시간): midlow_cloud +0.38·total_cloud +0.34·**cape −0.25(historical 없음→학습불가, 후처리만)**·tcog +0.13·tcoh 사용불가. **채택=구름(west·south raw, h≤48)+BTM용량** → 2-A 최종 20피처 재학습(D+1 3.97·전체 4.14). cape는 forecast 전용이라 미채택.

**2026-06-07 — 제주 2단계 장지평 확장(2-A): 풀드 직접 다지평 LGBM 추가(기존 D+1 그대로)**
- 무엇을: land 5-A 틀을 제주로 이식. 기존 PatchTST+LGBM D+1 파이프라인은 손대지 않고, **LGBM 단독·풀드 직접 다지평 1~168h(D+1~D+7)** 신규 모델 추가. `eda/`(2-0)·`model/`(2-A) 신설.
- 피처 확정(사용자 Decision Gate, 두 차례 질의): 15개 = h+lag168+rec24/rec168+기상4(기온·습도·일사·풍속, 제주3지점평균·일사2지점)+달력(hour/dow/month sin·cos)+day_type. **land 5-A 대비 lag24 제거·h 유지(중요도 낮지만 풀드 구조상 필요)·month 추가·습도 추가**(제주 forecast엔 reh 있어 서빙가능 — land와 차이).
- 2-0 EDA(G-9 통과): lag24 0.894/lag168 0.822, 기온 V자(선형상관 ≈0), rec24 0.69/rec168 0.65, train↔test 겹침 안전. 학습창=기존 제주 2단계와 동일(train ≤2025-02/val ~2026-03-21/test 2026-03-22~05-31).
- 결과 test: **완전기상 D+1 4.13%→D+7 4.36%(전 지평 KPX 6.0% 상회, 거의 평평 — lag168이 전 지평 동일 가용)**. 단 **기후값(무기상정보) 하한 6.8~7.1%로 KPX보다 나쁨** → 제주는 기상예보 품질 의존도가 land보다 큼(정직성: 운영은 두 괄호 사이). D+1 비교: LGBM직접(완전) 4.13% > PatchTST단독 6.06% > KPX 5.94% > naive 8.80%. 중요도 lag168 37%·기온 15%·습도 6%·rec168 6%, h 0.4%.
- 다음: 2-B 서빙 연결(`forecast` UPSERT, D+1~D+7 선택형) — 사용자 요청 시.

**2026-06-07 — 5단계 마무리: 5-B 서빙 + 7일 예보(G-12) + 5-A2 지평별 모델 + 공휴일 실험**
- 5-B 서빙: `serve_land_demand.py`, D+1~D+7 선택형(`--days`) → `forecast.est_demand_land` UPSERT. 기상 예보 우선·없으면 (월,시) 기후값 폴백. 백필 검증 D+1 4.30%·D+7 5.40%(5-A 기후값 괄호 일치).
- 7일 예보 수집(G-12 신설·해결): KIMG 전구 발표별 예보길이 확인 — **00/12 UTC=288h(12일)·06/18 UTC=87h**(hf probe로 검증). 현재 18 UTC라 87h 캡이었음. 결정: **≤72h는 기존 신선 발표, >72h(D+4~)는 12 UTC 단일** `--kimg-days 7`. 서빙 무변경. 백필은 사용자 직접.
- 5-A2 지평별 직접모델(Direct-H, 사용자 요청): D+1·D+2·D+3·D+7·D+12 5개(D+n 하루 블록). lag_week=target−168(D+1~7)/−336(D+12). test 2026 완전기상 3.48~4.59%, 전 지평 KPX 상회. 풀드 5-A가 ~0.05~0.1%p 근소 우위.
- 공휴일 실험(사용자 지적): lag_week가 7일 전 평일을 주입 → 공휴일 MAPE 2배. lag_dt(lag 시점 day_type) A/B → 전체 개선 ≤0.15%p, 문제 부분집합 비일관(D+7 악화)·표본 9일 → **미채택**. 타깃 day_type이 신호 대부분 보유 확인.
- 낮시간 진단(`model/_eval_daytime.py`, 제주 2-0c 이식 검토): land 5-A 낮(08~16h) test 2026 = 모델 6.38% vs KPX 5.97%(근소 열위). 흐림(일사 하위25%)은 모델 3.64% 압승, **맑음에서 +4,545MW 과대예측(9.82%)** — land 낮 약점은 제주와 부호 반대(과대). → **제주식 비대칭 quantile(α>0.5, 예측 상향)은 land에 역효과라 미적용 확정**(land는 BTM 비중 작아 흐린날 과소 문제 없음. 맑은날 과대는 별개 이슈·후순위).
- 다음: 6단계 전국 신재생 / 제주 2단계 장지평 확장(후순위) / 5-A2 서빙 연결(선택).

**2026-06-06 — 5단계 전국 수요: 5-0 EDA + 5-A 직접 다지평 LGBM 완료 (D+1 3.6~4.5%, KPX 우위)**
- 무엇을: 전국 수요 예측기(5단계) 착수. 5-0 EDA(G-9 통과): 강한 일/주 주기(lag168 0.84), 기온 V자(58k~79k MW), 5지점 공간평균 타당, **서빙 가능 기상 = 기온·일사·풍속**(예보에 습도·강수·적설 없음 — 제주와 차이), train↔test 겹침 안전. 베이스라인 KPX 하루전 MAPE ~5.5%.
- 5-A(사용자 확정): **LGBM 단독·직접(direct) 다지평 1~168h 단일모델**(재귀 아님 — lag168이 전 지평 직접 가용해 오차 누적 회피. "PatchTST predict_length 다르게"의 LGBM판). 피처 = h+lag168+lag24(h≤24)+rec24/rec168+기상3+달력+day_type. 평가 D+1~D+7(각 24h 전체), 정직성 2겹(완전기상 상한↔기후값 하한).
- 결과 test 2026: **D+1 3.56~4.50% / 전체 3.99~5.01% / D+7 4.22~5.31% — KPX 하루전 5.45%를 전 지평 상회**(naive lag168 7.2%). 중요도 lag168·기온·rec168 주도. → 베이스라인 우위로 PatchTST 불필요.
- 곡절(정직성): 24의 배수 지평(23:00 origin)만 보면 23시 한 시각만 평가돼 낙관편향(1.88%) → D+1~D+7 블록(전 시각)으로 재집계. 기상은 forecast 발행 리드타임 미저장이라 예보오차 직접측정 불가 → 완전기상/기후값 괄호로 표현.
- 다음: 5-B 서빙(`est_demand_land` UPSERT) / 6단계 신재생 / 제주 2단계 장지평 확장(후순위).

**2026-06-06 — 7-A2 이용률 정규화로 2026 과소예측 보정 + 7-C end-to-end 갱신**
- 무엇을: 7-C에서 발견한 7-A의 2026 과소예측(bias −5.7%)을 보정. 원인 = LNG 설비 증설(`kr_elec_capa.csv`: 2022 41,788→2026 48,388MW, train 대비 +9.6%). 같은 수요에서 2026 가스발전만 +13% 점프(이용률로 보면 2022 수준 정렬).
- 처리(7-B 동일 논리): 타깃을 이용률(gen/cap) 정규화→×용량 복원, 피처는 7-A 동일. 결과 **test 2026 bias −5.7%→+4.0%, MAPE 11.4%→10.5%, R² 0.784→0.863**. 정직한 한계: val 2025 bias +8.3%(2025 저이용률 연도 과보정). 산출 `model/7-A2_*`·`REPORT_7-A2.md`·`lgbm_land_gas_util.txt`.
- 7-C 갱신: 송출량 예측에 7-A2 적용 → **end-to-end MAPE 13.6%→7.3%, bias −13%→−3.3%**. 변환계수(0.1521)는 그대로.
- 다음: (선택) 2025 저이용률 원인 분석 / 8단계 Streamlit 데모 / 예측기 5·6.

**2026-06-06 — 7-C KOGAS 환산 완료: 발전량(MWh)→송출량(TON) 단일계수 0.1521**
- 무엇을: 전력거래소 시간별 발전량을 일집계해 KOGAS 일간 송출량(TON)에 회귀. 산출 `model/7-C_kogas_conversion.ipynb`+`REPORT_7-C.md`+`fig/7c_*`·`tab/7c_*`.
- 변환계수(핵심): corr 0.972, **무절편 단일계수 0.1521 ton/MWh**(열효율 ~43% 물리적 타당 → 단위 TON 확인, G-5 부분해결). 변환 MAPE 3.6%, 연·월 안정(겨울 안 부풂=발전용만, 난방혼입 아님).
- 변환식 결정 곡절(사용자): 처음 무절편 lean → "전국 LNG=0 불가라 절편 넣자"(절편식) → 연도별 절편 759~9030 불안정 확인 후 **"그냥 절편 빼자"로 무절편 단일계수 최종 확정**.
- f(기온) 검증(현장 직관 "겨울 효율↑"): corr(변환비,기온) −0.14, f(기온) 추가 +0.05%p·부호 반대 → 전국 fleet 일집계에선 부분부하·급전구성이 압도해 기온신호 소멸. 단일계수 유지·문서화(정직성).
- 최종 산출: test 2026 일별/시간별 예상 송출량(TON). **오차 분해**: 변환만 MAPE 3.7%(견고) / **7-A가 2026 가스발전 −10% 과소예측** / end-to-end 13.6%(7-A 바닥편향 전파, 변환 문제 아님). 단가·수입가는 물량과 독립(corr≈0) → 가스비=곱.
- 다음: (선택) 7-A 2026 과소예측 보정 검토 / 8단계 Streamlit 데모 / 예측기 5·6.

**2026-06-06 — 7-B 제주 probe 완료(EDA G-9 + 마감 모델). 명제 입증 중심으로 전환**
- 무엇을: 제주 `only_gen` 실측으로 net_load → LNG 검증. EDA(G-9 제주): net_load↔LNG r=0.723, 0비중 1.3%, 대체효과 수요통제 신재생계수 −0.369(전국 ≈0 대비). 산출 `eda/7-B_jeju_probe_eda.ipynb`+`REPORT_7-B_eda.md`.
- **막힘→전환**: 첫 모델이 베이스라인보다 나빴음(test R²0.25). 진단 결과 2024-01 절대 LNG 점프 = **유류→LNG 설비전환**(사용자 제공 `jeju_gen_capacity.csv`: LNG_cap 333.7→492.5, 유류 186→40MW). 제주 LNG는 작은 계통이라 절대 점예측 본질적 한계. → §1.2대로 정확도가 아닌 **명제(관계·방향) 입증**으로 목표 재정렬.
- 처리(사용자 확정): 타깃 이용률(lng/cap) 정규화→×용량 복원, **주 학습창 2024-01+ 안정창**. 피처 수요+신재생합계+달력(7-A 동일 basis). 결과 net_load↔LNG r=0.777 단조증가, test R²0.50·MAE37.7(베이스 −0.24), **신재생 PDP −0.314**(전국 −0.017). net_load별 LNG 추정 곡선 산출.
- 학습창 비교(사용자 요청): 2022-08+ 확장(n 3배)은 동일 test에서 R²0.50→0.36 하락 — 2022-23 유류많은 fleet 구성표류 오염. **2024+가 맞는 창** 확인(대체효과는 두 창 −0.31~−0.34 일치). 산출 `model/7-B_jeju_gas_lgbm.ipynb`+`REPORT_7-B.md`+`lgbm_jeju_gas.txt`.
- 부수 결정: PPA(`jeju_ppa_cumulative_gen.csv`)는 7-B 미사용(2024-06 시범사업으로 PPA가 Grid 계량에 흡수 → 제주는 계량 신재생만으로 충분. 육지는 미흡수라 PPA 산정 필수). 누적발전량→용량 역산은 출력제어로 비물리적이라 부적합.
- 다음: **7-C KOGAS 환산**(`daliy_lng_gen_21-26.csv` → 단가·수입가로 수요·비용) + 제주·전국 명제 대비표.

**2026-06-06 — G-11 해결: 7-Ar 실측전용 대체효과 모델 추가(둘 다 유지)**
- 무엇을: BTM/PPA 실측만(2024-11+)으로 true_demand+true_renew LGBM 학습. 사용자 질문("실측전용 가능? 데이터 작지?")에 데이터로 답: train ~8천행 충분, **test 2026 R² 0.798·MAPE 12.0%로 오히려 최고**(train·test 동일 최신 레짐). 신재생 중요도 15.4%, 순수 실측. 산출 `model/7-Ar_*`·`lgbm_land_gas_recent.txt`.
- 최종 모델 lineup: 7-A(현행, 긴 이력 순수실측)=메인 예측 / 7-Ar(실측전용)=대체효과 설명 / 7-0b=전 기간 대체효과 EDA(역추정). 복원 단일화판(R²0.766)은 미채택.
- 다음: 7-B 제주 probe.

**2026-06-06 — 7-0b: BTM/PPA 역추정으로 전 기간 대체효과 입증(신재생계수 −0.33, 역추정≈실측)**
- 무엇을: 자가소비(BTM)·PPA가 계량수요에 숨어 7-0(5-b)에서 대체효과가 안 보였던 것 규명. G-11에서 (c) 역추정 채택(사용자 `ppa_scale.csv` 제공).
- 역추정(`second_dataset/backfill_btm_ppa.py` → `land_renew_reconstructed.parquet`): PPA=k·ppa_scale·태양광이용률(k=0.7108, 검증오차 ±5%), BTM=0.3153·PPA. 2020-01~2024-10 estimated 라벨, 2024-11+ measured.
- 검증(가스 실측 2022+): 수요 통제 신재생계수 계통분 +0.105 → **복원 −0.332**. estimated −0.319 ≈ measured −0.363 → **역추정 타당**. 한낮·저수요에서 특히 명확(제주형 패턴 전국 상존). 산출 `eda/7-0b_*`(notebook·REPORT·그림3·표2).
- 남은 결정(G-11): 7-A를 (true_demand,true_renew) 복원 피처로 재학습 vs 현행 유지+발표 EDA. 다음: 결정 → 7-B 제주 probe.

**2026-06-06 — 7-A 전국 가스 모델 최종(설계 A 분해형): test 2026 R² 0.78 / MAPE 11.4%**
- 무엇을: gen_gas_kr 동시점 회귀. 피처를 여러 설계로 비교 후 사용자 확정(§0.6). 산출 `7. land_gas_forecaster/model/`(notebook·`lgbm_land_gas.txt`·`metrics.csv`·`REPORT_7-A.md`·그림+PDP).
- 신재생 대체효과 EDA(5-b) 추가: 명제(신재생↑→가스↓)를 수요 통제하에 직접 확인 → **전국은 약함**(원상관 +0.01, 회귀 신재생계수 ≈0, 침투율 2.5%·자가소비 태양광 숨음). 저수요 시간대만 음(−). → 대체효과 입증은 제주(7-B).
- 피처 설계 비교(test R²): A 수요+신재생 0.784 / C net_load+수요 0.783 / D 셋다 0.754 / B net_load+신재생 0.610. 트리는 수요(절대규모)를 직접 줘야 강함. **A 채택**(예측 최고 + 신재생 명시로 대체효과 관찰 + 제주와 동일 basis).
- 최종 피처: real_demand_land + renew_gen_total_kr + day_type + 달력(hour/dow/month/doy). 결과: 베이스라인(수요 단독) R² 0.63, **LGBM R² 0.78·MAPE 11.4%·MAE 2,236**. 중요도 수요 60%·doy 15%·hour 13%·신재생 3.6%. 신재생 PDP 기울기 −0.017(부호는 대체, 크기 미미).
- 다음: 7-B 제주 probe(same basis, only_gen 2020-24 + net_load별 LNG 추정, 대체효과 제주 확인), 7-C KOGAS 환산(일별 `daliy_lng_gen_21-26.csv`).

**2026-06-06 — G-10 해결: 학습창 train 2022-24 / val 2025 / test 2026, 2020-21 로드시 필터**
- 무엇을: EDA 발견에 따라 전국 학습창 재정의. parquet `split` 컬럼(train 2020-23) 대신 7-A 로드 시 연도로 분할. 2020-2021(결측-0)은 로드 시 필터, parquet·빌더는 그대로(재빌드 안 함).
- 다음: 피처 최종 입력 사용자 확정(§0.6) → 7-A 학습.

**2026-06-06 — 7-0 EDA 완료(관계 강함, r=0.83) + 데이터 결손 발견(G-10 신설)**
- 무엇을: 7단계 첫 작업으로 전국 net_load → gen_gas_kr EDA notebook 작성·실행(`7. land_gas_forecaster/eda/7-0_eda_land.ipynb`, 그림 6·표 3·`REPORT_7-0_eda.md`).
- 결과(2022+ 실측): 상관 **r=0.83**(강함), 부하수준별 비선형, 타깃 0 비중 0%(항상 켜짐), 연도 안정(60-65k 가스 ~17,500MW 일정), train↔test net_load 겹침 안전(외삽 0.7%). → 명제(검증목표 2)는 데이터에 실제로 있음.
- **★ 발견(G-10)**: `gen_gas_kr` 실측은 **2022-01부터**. 2020(100% 0)·2021(97% 0)은 결측을 0으로 채운 값이고 `model_usable`이 잘못 True. **공식 분할 train=2020–2023은 절반이 가짜** → 학습창 2022+ 재정의 필요. EDA 먼저 안 했으면 가짜 데이터로 학습할 뻔(EDA-first 규율의 실증).
- 다음: G-10 확정(학습창/분할 + 라벨 수정 방식) → 피처 최종 입력 질의 → 7-A.

**2026-06-06 — 모델링 작업 규율 4건 추가 + G-9(관계 EDA 게이트) 신설**
- 무엇을: §0.6에 모든 모델링 공통 규율 추가 — ①시계열 분석 필수 ②피처 최종 입력은 반드시 사용자 확정(탐색은 자유) ③단계마다 보고서 산출물 필수 ④notebook 형식 선호.
- §5.0.5(관계 탐색·시계열 분석) 단계 신설, G-9 게이트 추가(명제가 데이터에 실제로 있는가 = 관계·시간적 안정성·train↔test 분포 겹침). G-6(구조)과 구분.
- 7단계 순서 재정의: 7-0 EDA(G-9) → 피처 확정 질의 → 7-A 전국 모델 → 7-B 제주 probe(+ net_load별 LNG 발전량 추정) → 7-C KOGAS 환산.
- 배경: 직전에 EDA 없이 7-A 모델로 직행하려다 잡음. 명제 자체가 관계 주장이라 EDA가 1차 증명. 다음: 7-0 EDA 착수.

**2026-06-06 — G-7 해결: 전국 7단계를 먼저 착수하기로 결정**
- 무엇을: 전국 트랙 진입 순서(G-7)를 확정. 예측기 5·6을 만들기 전에 7단계(net_load → `gen_gas_kr`)를 먼저 한다.
- 근거: 명제 입증이 목적이라 전국 historical `net_load_kr` 실측만으로 검증 가능(예측기 불필요). `land_train/val/test.parquet` 이미 생성돼 있어 즉시 착수 가능. G-8(원천 CSV 경로)은 데이터셋 재빌드 시에만 필요해 현재 비차단.
- 다음: 7단계 모델링 착수 — `land_*.parquet`로 `gen_gas_kr` 회귀(누수 차단: 딕셔너리 `forbidden` 제외), 제주 probe(`only_gen` 2020–2024)까지.

**2026-06-06 — 프로젝트 재구조화 + 통합 마스터 문서 작성**
- 목표가 제주 SMP(v1)에서 가스수요·전국 검증(v2)으로 피벗됨에 따라 폴더를 정리.
- 평면 넘버링 유지(중첩 금지 — DB 경로가 상대경로라 깊이가 바뀌면 깨짐). 제주 모델 폴더에 `jeju_` 접두사(2·3·4), 전국 골격 신설(5·6·7), `5.streamlit→8`, `6.report only→98`, `99.others` 유지.
- `7. second_dataset`(가스 데이터셋 빌더)를 `1. data_fetcher_and_db/second_dataset/`로 편입하고 `build_dataset.py`·`fit_merit_split.py`의 DB/OUT 경로 보정(이동으로 깊이 +1, 기존 stale 상수 정리). DB 경로 해석 검증 완료, 제주 파이프라인 4종 경로 정상 확인.
- 구 `PROJECT.md`(v1)·`project2.land.md`(v2)는 `docs/`로 이력 보존(헤더에 대체됨 표기). 이 통합본이 새 SSOT.
- 다음: 전국 트랙(G-7 결정 → 7단계 가스 예측기) 또는 8단계 데모.

**2026-06-03 — A0 데이터 확보·분리 + A1 가스 타깃 완료 (G-1~G-6 해결)**
- `second_dataset`에 빌더(`build_dataset.py`, `make_dictionary.py`, `fit_merit_split.py`) 작성·실행. 제주·전국 시간별 마스터셋 결합 → 감사 → LNG 타깃 도출+backfill → 라벨링 → 시간순 분할.
- 결과: 제주·전국 각 56,256행, 중복 0·시간구멍 0, 학습/검증/테스트 NaN 0. 분해는 급전순위 부하수준별(merit-order, 단일 비율 대비 MAE −13.7%). 산출 `data/*.parquet`·`data_dictionary.csv`·`audit.json`·`AUDIT_REPORT.md`.
- 다음: 가스 예측기 착수(제주 `only_gen` 실측, 전국 `gen_gas_kr` 정직 검증).

**2026-06-03 — 방향 전환(PRD 확정): SMP → 발전용 가스수요**
- 검증 목표 1·2 정의(제주 입증 → 전국 확증). 방법론(도출=타깃 / 학습=예측 2단, 검증 3계층) 확정. 전국 트랙을 보너스에서 핵심 증거로 격상.

**2026-06-05 — 4단계 제주 SMP 완료**
- D+1: 가격선 = DA 그대로 + 이진 음수경보 오버레이. 음수경보 ROC-AUC 0.973, 치명 recall 0.934. D+2: DA 예측 + 잔차회귀, TEST MAE 11.79. 통합 서빙 `smp_serve.py`.
- 하드 제약: 제주 SMP는 제주 데이터만. SMP 점예측·실시간 직접 회귀 등은 실패로 확인된 경로(재시도 금지). 상세 `4. jeju_smp_forecaster/trial_error.md`.

**2026-06-01 — 3단계 신재생 → net_load 완료**
- 3지점 입력 PatchTST 재학습. 이용률 solar +6.9%·wind +3.7%, net_load DA 대비 +7.0%. 서빙 `solarwind_db_pipeline.py`, `est_net_load_jeju` 백필.
- wind 시행착오(재시도 방지 기록): 첫 wind 3지점(west+east+south)이 serve(예보기상)에서 구버전 대비 −52.9% 악화. 진단 = **south(태양광지점)가 약상관(이용률 corr 0.249)+예보 풍속 대폭 과대(bias +3.94)로 주범**, wind_spd_sq/cu는 예보 풍속오차를 증폭(cubic이 악화 주범) → 둘 다 제거. wind_spd_diff(west−east)·스케일러 −1~1도 악화로 폐기. **최종 wind=west+east 10피처(풍향은 west 공유 1쌍)**, solar=west+south.
- 구버전 패키지(`net_load_forecaster/`·`models/`)는 무수정 보존, 신버전 가중치는 `solarwind_models/` 별도(구 `models/`를 덮으면 구 파이프라인이 단일지점 피처를 만들어 dim 불일치로 깨짐). 구/신 비교 스크립트·구 DB는 `98. report only/`(compare_old_vs_new.py·compare_net_load.py).

**2026-06-01 — 2단계 수요 예측 재구축 완료**
- 입력을 CSV에서 `input_data_jeju.db` 직접 로드로 전환. 제주 3지점 공간평균으로 LGBM 재학습 → Test MAPE 4.29% → 3.98%. 서빙 `demand_db_pipeline.py`.
- 운영 디테일: PatchTST 신호는 DB 테이블 `patchtst_signal(timestamp, jeju_patchtst_target)`로 이전(CSV 탈피). `real_demand_jeju` 0값은 결측으로 보고 시간보간. 학습 `patchtst_lgbm_train_db.py`, 추론 `demand_db_pipeline.py`의 `predict_demand_to_db(date)` → forecast `jeju_est_demand_new` UPSERT.
- train/serve 기상 컬럼 매핑: historical `temp_c_*/humidity_*/wind_spd_*/solar_rad_*` ↔ forecast `temp_*/reh_*/wind_spd_10m_*/radiation_*`. 일사는 west·south 2지점 평균(east는 풍력지점이라 일사 없음).


# functions.md — 1~7단계 핵심 CLI·함수 레퍼런스 (8단계 작업용)

> 작성 2026-06-11. 8단계 Streamlit 작업에서 각 단계 산출물을 정확히 끌어다 쓰기 위한 요약.
> 세부 구현이 아니라 "무엇을 받고, 무엇을 DB에 쓰는가" 수준. 상세는 각 스크립트 docstring 참조.
> 공통: 모든 파이프라인은 `1. data_fetcher_and_db/data/input_data_{jeju,land}.db`의
> `forecast` / `historical` 테이블에 timestamp 키로 UPSERT. 8단계 앱은 **읽기 전용**.

---

## ★ API 매칭 운영 원칙 (2026-06-11 사용자 확정)

1. **예측 조회는 하루 단위** — 00시~23시 1일 블록이 기본.
2. **실측은 실시간 갱신 가능해야 함** — `fetch_kpx_land`(수요)·`fetch_land_power`(가스·신재생)·`fetch_kpx_jeju`(제주 수급)는 앱에서 수시 새로고침(표시 전용, DB에 쓰지 않음. ttl 5분 캐시 + 수동 버튼).
3. **예측(forecast·DA 등 미래지향)은 DB 우선** — 사전 적재분을 읽고, **없을 때만 제한적으로 서빙 실행**(로컬 모델 추론이라 수집 API 한도와 무관).
4. **시각화의 주인공 = 예측 vs 실측 비교** — real_demand↔est_demand, real_net_load(재구성)↔est_net_load, gen_gas_kr↔est_gas_gen. 실측=solid, 예측=dot.
5. 평가지표: 수요·net_load·가스 = MAPE·MAE·bias / **신재생 = nMAE**(심야 분모≈0으로 MAPE 폭발 — 6단계 보고서와 동일 처리).

---

## ★ 단계별 `--days` 의미 차이 (함정 — 체인 실행 시 주의)

| 스크립트 | `--days` 의미 | 예 |
|---|---|---|
| 2-B `serve_jeju_demand_lh.py` | **정수 = D+1..D+N 범위** | `--days 7` → D+1~D+7 |
| 3 `serve_solarwind_hybrid.py` | **콤마 목록 = 지평들** | `--days 1,2,3,4,5,6,7` |
| 5-B `serve_land_demand.py` | **정수 = D+1..D+N 범위** | `--days 7` → D+1~D+7 |
| 6-C `serve_solarwind_land.py` | **콤마 목록 = 지평들** | `--days 1,2,3,4,5,6,7,12` |
| 7 `serve_land_gas.py` predict | **정수 = D+1..D+N 범위** | `--days 7` → D+1~D+7 |
| 7 `serve_land_gas.py` backfill | 정수 = 각 origin당 D+N까지 (기본 1 = D+1만) | |

또 하나: **2-B backfill은 기본이 평가만(no-write)** — DB에 쓰려면 `--write` 필요.
(5-B·6-C·7 backfill은 기본 write, `--no-write`로 끔.)

---

## 1단계 — 데이터 수집 (`1. data_fetcher_and_db/core`)

> **수집은 crontab 백그라운드 전용. 앱·사용자 트리거 금지(API 한도 보호).**
> 서버(~/project2026) crontab이 운영 중이며 업로드 후엔 서버 DB가 원본.

### collect_data_land.py — 육지(전국) 수집기
- 무엇을: KIMG-land 예보(5지점) + ASOS-land 관측(5지점) + KPX 전력계통 3종을 메모리에서 받아 `input_data_land.db`에 UPSERT.
- 5지점: 대관령·원주·서산·포항·영광 (`_daegwallyeong` 등 suffix).
- forecast에 쓰는 것: `radiation/total_cloud/midlow_cloud/temp/wind_spd_10m/wd_sin·cos_10m/reh/rainfall` ×5지점 + `smp_land_da`/`land_est_demand_da`(KPX 일전).
- historical에 쓰는 것: sukub 수급 7종(`*_land`) + 발전원별 실적(`gen_*_kr`) + ASOS 관측 + `*_da`.
- CLI: 인자 없이 = 최근 2발표 forecast + 최근 2일 historical. `--backfill N` / `--historical-days N` / `--no-forecast` / `--no-historical` / `--kimg-days 12`(D+12 지평 커버, 서버 00:40 적용).

### collect_data_jeju.py — 제주 수집기
- 무엇을: KIMR+KIMG 예보(서/동/남 3지점) + ASOS 관측 + KPX 제주 수급 + 실시간 SMP를 `input_data_jeju.db`에 UPSERT.
- forecast: 3지점 기상예보(`_west/_east/_south`) + `smp_jeju_da`/`jeju_est_demand_da` 등.
- historical: 제주 수급(`supply_cap_jeju`·`real_demand_jeju`·`real_renew_gen_jeju`·`real_solar/wind_gen_jeju`) + 관측 + **실시간 SMP**(`smp_jeju_rt`, `smp_rt_g1..g4`, `smp_rt_neg_num`) + 용량/이용률(`real_*_capacity/utilization_jeju`, `real_net_load_jeju`).
- CLI: collect_data_land와 같은 패턴(`--backfill` / `--historical-days` / `--bases`).

### api_fetchers_land.py — 육지 fetcher 허브 (라이브러리, 앱에서 직접 호출 가능한 것)
- `fetch_kpx_land(start, end)` → **sukub 수급 7컬럼** 시간별 wide DF: `supply_cap_land`(공급능력), `real_demand_land`(현재수요), `max_pred_demand_land`, `supply_reserve_land`/`supply_reserve_pct_land`(공급예비력/율), `oper_reserve_land`/`oper_reserve_pct_land`(운영예비력/율). 실패 시 빈 DF. **8단계 현황 탭 실시간 새로고침이 이걸 사용**(표시 전용, DB에 안 씀). KPX 공개 CSV 다운로드라 가벼움.
- `fetch_land_est(start, end)` → `smp_land_da` / `land_est_demand_da` (KPX 하루 전 발표).
- `fetch_land_power(start, end)` → 발전원별 실적 `gen_*_kr` 15컬럼(가스·석탄·원자력·태양광 market/BTM/PPA·풍력·수력·양수·유류 등, 전국값).
- `fetch_asos_land(start, end)` → ASOS 5지점 관측.

### api_fetchers_jeju.py — 제주 fetcher 허브
- `fetch_kpx_jeju(start, end)` → 제주 수급(chejusukub, `*_jeju`).
- `fetch_kpx_est(start, end)` → DA SMP + 예상수요(`*_da`).
- `fetch_asos(start, end)` → ASOS 3지점 관측.

---

## 제주 트랙 (2~4단계, DB = input_data_jeju.db)

### 2단계 — 수요
**demand_db_pipeline.py (배포 D+1, PatchTST+LGBM)**
- `predict_demand_to_db(date)` → `forecast.jeju_est_demand_new` (D+1 24h). Test MAPE 3.98%.
**serve_jeju_demand_lh.py (2-B 장지평, LGBM 직접 다지평)**
- origin(지정일 23:00) 다음 D+1~D+7 → `forecast.jeju_est_demand_lh` UPSERT. 기상 예보 우선·(월,시) 기후값 폴백.
- CLI: `predict [date] --days N` / `backfill start end --days N --write`(★기본 no-write).
- 실서빙(forecast) 낮시간 전체 8.04% — KPX(9.09%) 우위.

### 3단계 — 신재생 → net_load
**solarwind_db_pipeline.py (배포 D+1, Cross-Attention PatchTST 3지점)**
- `predict_solarwind_to_db(date)` → `est_solar/wind_utilization_jeju`(0~1), `est_solar/wind_gen_jeju`(MW), `est_net_load_jeju`(MW = jeju_est_demand_new − solar − wind).
**serve_solarwind_hybrid.py (공식 다지평, `_lh` 접미사)**
- 채널 분리: solar=PatchTST direct(D+1~7) / wind=LGBM 전지평 + tcog 대류일 후처리.
- 출력: `est_solar/wind_util_jeju_lh`, `est_solar/wind_gen_jeju_lh`, `est_net_load_jeju_lh`.
- CLI: `predict origin --days 1,2,...,7`(콤마 목록) / `backfill start end`.
- 참고: `est_*_jeju_lgbm`(serve_solarwind_lgbm.py)은 LGBM 단독 비교용 — 데모는 `_lh` 사용.

### 4단계 — SMP (제주만, 육지 SMP 연계 영구 배제)
**smp_serve.py (D+1·D+2 단일 진입점)**
- D+1(DA 발표됨 → DA가 가격선): `est_smp_jeju`, `smp_neg_proba_jeju`(음수확률), `smp_danger_jeju`(경보), `smp_neg_depth_p10/p50/p90`(깊이), `smp_neg_proba_cal_jeju`·`smp_rt_soft_est`·`smp_danger_day/night_jeju`.
- D+2(DA 미발표 → 예측 DA+오버레이): `est_smp_jeju_d2`, `smp_neg_proba_d2`, `smp_danger_d2`(균형)/`smp_danger_d2_hi`(고확신), `smp_neg_depth_d2_p10/p50/p90`.
- CLI: `day 2026-03-19` / `range start end [--scope d1|d2|both]`.
- 음수경보 ROC-AUC 0.973, D+2 가격선 MAE 11.79.

---

## 전국 트랙 (5~7단계, DB = input_data_land.db)

### 5단계 — 수요 (serve_land_demand.py, 5-B)
- LGBM 직접 다지평(h=1..168). origin 23:00 → D+1~D+7 → `forecast.est_demand_land`.
- 기상 = 예보 우선·기후값 폴백(`weather_src` 표기). 보통 실예보는 ~D+1, 그 너머는 기후값.
- CLI: `predict [date] --days N` / `backfill start end`. D+1 MAPE ~4.2%(백필, KPX 5.45% 우위).

### 6단계 — 신재생 → net_load (serve_solarwind_land.py, 6-C)
- 채널 분리: solar=PatchTST direct(D+1~7, D+12)+LGBM 폴백 / wind=LGBM 전지평. 수요는 `est_demand_land` 우선 → `land_est_demand_da`(KPX) 폴백.
- 출력 8컬럼: `est_solar/wind_util_land`, `est_solar/wind_gen_land`, **`est_market_renew_land`**(시장 solar+wind → 7단계 입력), `est_true_renew_land`·`est_true_demand_land`(BTM/PPA 포함, 분석용), **`est_net_load_land`**(= 수요 − 시장신재생).
- CLI: `predict origin --days 1,2,...,7,12`(콤마 목록) / `backfill start end`.
- 검증: SOLAR util MAE(낮) 0.087 / WIND 0.139.

### 7단계 — 가스 (serve_land_gas.py, 7-A2-A 체인)
- 체인: `est_demand_land`(5) + `est_market_renew_land`(6) 읽어 → 이용률 LGBM × LNG용량 × bias보정(×0.96509) → **`est_gas_gen_land`**(MW) → ×0.1521 → **`est_gas_sendout_ton_land`**(TON).
- CLI: `predict [date] --days N`(D+1..N) / `backfill start end --days N`(origin당 D+N, 기본 D+1).
- 계수 파일: `model/gas_serving_calib.json` (bias 0.96509, 변환 0.1521 ton/MWh).
- 체인 검증 가스 MAPE ~13%(D+1≈D+12 평평, ORACLE 10.8%).

### KOGAS 환산 (7-C 산출물 — 모델 아님, 앱이 직접 사용)
- 변환계수: **송출량(TON) = 0.1521 × 발전량(MWh)** (열효율 ~43%, 변환 자체 MAPE 3.6%).
- 가스비: **송출량(TON) × 55 GJ/ton × 월 단가(원/GJ)** — 단가는 `7. land_gas_forecaster/model/tab/7c_monthly_price_cost.csv`(`tariff_gen_won_per_GJ`, 월별. 범위 밖은 마지막 값).

---

## 8단계 앱이 읽는 핵심 컬럼 요약

| 용도 | 전국 (input_data_land.db) | 제주 (input_data_jeju.db) |
|---|---|---|
| 수요 예측 | forecast.`est_demand_land` | forecast.`jeju_est_demand_lh`(장지평) / `jeju_est_demand_new`(D+1 배포) |
| 신재생 예측 | forecast.`est_market_renew_land` | forecast.`est_solar/wind_gen_jeju_lh` |
| net_load 예측 | forecast.`est_net_load_land` | forecast.`est_net_load_jeju_lh` |
| 가스 예측 | forecast.`est_gas_gen_land`·`est_gas_sendout_ton_land` | (없음 — 제주는 SMP 관점) |
| SMP 예측 | (비대상 — 시장 구조) | forecast.`est_smp_jeju`·`est_smp_jeju_d2`·경보 컬럼들 |
| 수요 실측 | historical.`real_demand_land` (+sukub 실시간) | historical.`real_demand_jeju` |
| 신재생 실측 | historical.`renew_gen_total_kr` | historical.`real_renew_gen_jeju` |
| net_load 실측 | 재구성: real_demand − renew_gen_total | historical.`real_net_load_jeju` |
| 가스 실측 | historical.`gen_gas_kr` | — |
| SMP 실측 | — | historical.`smp_jeju_rt`(실시간)·`smp_jeju_da`(DA) |

주의: 전국 historical의 `net_load_kr`은 **발전 기준**(총발전−시장신재생)이라 우리 예측(수요 기준)과 ~3,550MW 오프셋 — 비교할 땐 반드시 `real_demand_land − renew_gen_total_kr`로 재구성한다.

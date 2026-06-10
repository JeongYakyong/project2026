# 6-C 요약 — 전국 신재생 통합 서빙 (serve_solarwind_land.py)

## 구조 (채널 분리, G-13)
- **SOLAR = PatchTST direct** (D+1~D+7, D+12 가중치, offset (n-1)×24). 입력결측/미학습 지평은 **LGBM(6-A) 폴백**.
- **WIND = LGBM 전 지평** (6-A). PatchTST 미사용(자기상관 붕괴·예보 풍속오차 증폭·true_renew 비중 작음).
- 대상일 기상 = forecast 우선 · 없으면 (월,시) 기후값 폴백. 수요 = est_demand_land(5단계) 우선 → land_est_demand_da(KPX) 폴백.

## 산출물 (forecast 테이블 UPSERT, _land 접미사)
- `est_solar_util_land`, `est_wind_util_land`
- `est_solar_gen_land`(시장), `est_wind_gen_land`
- **`est_market_renew_land`** = 시장 태양광+풍력 → **7-A** / **`est_net_load_land`** = 수요 − 시장신재생
- **`est_true_renew_land`** = +PPA/BTM(×total_solar_cap), **`est_true_demand_land`** = 수요+PPA/BTM → **7-Ar 대체효과**
- total_solar_cap = market_cap + k(1+r)·ppa_cap (k=0.7108·r=0.3152, 6-A2)

## 검증 (백필 D+1, forecast 기상)
- **SOLAR util MAE(낮, 2~5월) = 0.087** — PatchTST 정상 재현(LGBM 0.129 대비 우위). 월별 0.071~0.102.
- WIND util MAE = 0.139 (LGBM, 6-A 0.143과 일치).
- market_renew MAE 563MW(22%)·true_renew MAE 1,878MW(25%) [4월 D+1]. true_renew는 복원 근사 포함.

## API / CLI
- `predict_land_to_db(origin, horizons=(1..7,12))` / `backfill_land_to_db(start,end)`
- `python serve_solarwind_land.py predict 2026-05-01 --days 1,2,3,4,5,6,7,12`

## 한계·다음
- 수요는 현재 KPX(land_est_demand_da) 폴백 사용. 5단계 `serve_land_demand.py`로 est_demand_land 적재 시 자동 우선 사용(end-to-end).
- D+8~D+11은 PatchTST 미학습 → 요청 시 LGBM 폴백으로 서빙 가능.
- 6단계 완료. 다음: 8단계 Streamlit 데모(신재생→net_load→가스 차트 + brief_ai).

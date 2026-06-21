# 전국 수요 v4 구조 명세 (시각화용 단일 소스)

> 목적: 이 문서만 보고 구조 다이어그램을 그릴 수 있게 한다. 코드는 `model_lt.py`(forward),
> `calibrate_lt.py`(보정), `serve_chain_land_new.py`(production 서빙). 차원은 기본 하이퍼파라미터 기준.

## 한 줄 요약
**수요 = anchor(최근 같은요일 실측 레벨) + 모델이 학습한 잔차.** 잔차 모델은 과거수요+과거기상을
PatchTST 인코더로 표현하고, **미래 기상**이 과거 패치에 cross-attention 해 컨텍스트를 뽑은 뒤,
anchor·climatology를 헤드에 같이 넣어 잔차를 낸다. 그 위에 한낮 과대(BTM 태양광)를 지평별로 다르게 교정한다.
지평별(D+1~D+15) 15벌 — 구조는 15벌 모두 동일하고, **가중치·보정만 지평별 차등**:
**D1-6 = head 파인튜닝본·후처리 보정 없음 / D7-15 = 기존 가중치 + 후처리 보정**(G-24, 2026-06-21 → §9).

---

## 1. 입력 4블록 (한 샘플 = 한 지평 n 의 24h 예측)
| 블록 | 모양 | 정체 | 출처(서빙) |
|---|---|---|---|
| `past_numeric` | (336, 9) | 과거 336h 의 **공변량 9**(기상3 + 시간/달력6) | historical(관측 기상) |
| `past_y` | (336, 1) | 과거 336h **실측 수요** | historical |
| `future_numeric` | (24, 9) | 타깃 24h 의 **공변량 9**(미래 기상3 + 달력6) | forecast_horizon(예보 기상) + 달력 |
| `anchor`, `clim` | (24,), (24,) | 타깃 24h **레벨 기준 2종**(아래 4절) | historical 실측 lag |

- **공변량 9 = 기상 3** `[temp_c, humidity, solar_rad]`(4지점·2지점 평균, RobustScaler) **+ 시간/달력 6**
  `[Hour_sin, Hour_cos, Doy_sin, Doy_cos, is_weekend, is_holiday]`(비스케일).
- 기상 지점: 기온/습도=원주·서산·포항·영광(4), 일사=서산·영광(2). 미래 공휴일=`holidays.SouthKorea`.
- origin O = base 당일 23:00. 과거창 = O 직전 336h. 타깃창 = base+n일 00~23시.

## 2. Forward pass (잔차 모델, model_lt.PatchTST_Anchor)
차원: seq_len=336, patch_len=24, stride=12 → **patch 27개**. num_features=10(=공변량9+past_y).
d_model=256, heads=4, layers=3, d_ff=1024. ff=24×9=216.

```
(A) 과거 인코딩
  past_y ──RevIN(윈도우 평균·표준편차로 정규화)──▶ pyn(336,1)
  past_numeric(336,9) ⊕ pyn(336,1) = xp(336,10)
  xp ──패치화(len24·stride12=27패치, 각 24×10=240)──▶ (27,240)
     ──patch_embedding Linear(240→256) + 위치임베딩──▶ (27,256)
     ──TransformerEncoder(3층·4헤드·d_ff1024)──▶ eo(27,256)        # 과거 표현

(B) 미래 기상 cross-attention  (_PWA)
  Q = W_Q(future_numeric flat=216) → (1,256)        # 미래 공변량이 질의
  K = W_K(과거 기상 패치 xw: xp[:,:-1] 패치화 =(27,216)) → (27,256)
  attn = softmax(Q·Kᵀ/√256) → (1,27)
  ctx = attn · eo → (256,)                          # 미래기상과 닮은 과거패치를 가중 결합

(C) 잔차 헤드
  anc_z = (anchor−DMEAN)/DSTD ;  clim_z = (clim−DMEAN)/DSTD        # 수요스케일 정규화
  head_in   = [ ctx(256), ff(216), anc_z(24), clim_z(24) ] = 520
  bypass_in = [           ff(216), anc_z(24), clim_z(24) ] = 264
  resid = regressor(head_in: 520→256→LeakyReLU→Drop→24)
        + weather_bypass(bypass_in: 264→24)                       # 잔차(표준화 단위)

(D) 출력
  수요(24) = anchor + RESID_STD · resid           # 절대 수요(MW)
```
- 학습 타깃 = `y − anchor`(잔차), `RESID_STD`(지평별 학습셋 잔차 표준편차)로 표준화. 손실=SmoothL1.
- 핵심 아이디어: **레벨은 anchor가 모델 밖에서 공급**(장기 드리프트·태양광 성장은 최근 anchor/clim이 추적),
  모델은 작은 잔차만 학습 → 과적합·장기 열화 억제.

## 3. 지평별 15벌
구조 동일, **가중치는 D+1..D+15 각각**(`weights/best_lt_D{1..15}.pth`). 지평 n → offset=(n−1)×24h.
지평이 멀수록 anchor 의 lag 가 더 과거(아래)로 자동 이동.
- **D1-6 가중치 = head 파인튜닝본**(인코더·cross-attention 동결, residual head 만 신체제 2024-11~2025-11 재학습 → §9).
  D7-15 = 기존 v4(<2025 학습) 그대로. 차원·구조는 15벌 모두 동일.

## 4. 두 레벨 기준 (offline, 정직-lag = 참조가 origin 이전만)
둘 다 "타깃과 같은 (주말·공휴일) 상태인 same-DOW(168h 배수) 주"만 골라 평균. w0 = ⌈(offset+24)/168⌉.
- **anchor** = 가까운 **2주** 평균 → 날카로운 최근 레벨(저편향·고분산).
- **climatology(clim)** = 가까운 **13주** 평균 → 안정적이지만 여전히 최근(저분산). static 다년평균이 아님
  (다년평균은 BTM/PPA 태양광 성장 전 레벨이라 한낮 과대 → 최근창으로 해소).
- 모델이 anc_z·clim_z 를 헤드에서 받아 **지평별 수축 비중을 학습**(단기=anchor, 장기=clim 안정).

## 5. 후처리 보정층 (D7-15 만, 모델과 분리, calibrate_lt.py → calib_lt.json)
```
production 수요(D7-15) = 모델출력 × c[ 계절 , 시각 , 지평5구간 ]   # D1-6 은 무보정(파인튜닝본, §9)
```
- c = median(실측/예측), clamp 0.9~1.1. 키 = 계절(겨울/봄/여름/가을) × 시각(0~23) × 지평구간
  (중 D7-9 / 중장 D10-12 / 장 D13-15) — **초단 D1-3·단 D4-6 은 제외**(파인튜닝이 대체).
  = 최대 4×24×3=288셀 (현재 216 — 아카이브에 가을 미관측, 데이터 쌓이면 채워짐).
- `calibrate_lt.py` 는 `SKIP_GROUPS={'초단','단'}` 로 **D7-15 만 굽는다** → 재실행해도 D1-6 무보정 유지(안전).
- 용도: recent-clim 후 남는 장지평 한낮 과대(+7%)를 제거 → 지평별 bias ±0.4% 평평. (단기 한낮 과대는 §9 파인튜닝이 구조적으로 처리.)
- **별도층**: 재학습 없이 언제든 갱신(미보정 서빙결과 `est_horizon_land_raw`에서 재빌드). 없으면 무보정.

## 6. 서빙 파이프라인 (production)
```
forecast_horizon(예보 기상) ─┐
historical(과거 실측·수요)  ─┼▶ model_lt.predict_horizon (지평별 15벌 · D7-15 만 ×보정)
holidays.SouthKorea(미래)  ─┘        │
                                     ▼
        serve_chain_land_new.py (5수요 → 6신재생 → 7가스 한 패스)
                                     ▼
               est_horizon_land  (= 보정 수요 + 신재생 + net_load + 가스)
                                     ▼
                       streamlit · step7 소비
```
- 수요(est_demand_land)는 **가스 7단계의 입력 피처**이기도 함(수요 바뀌면 가스도 바뀜).
- 벤치: `serve_land_new.py`(기본 미보정) → `est_horizon_land_raw`(보정표 재생성·백테스트).

## 7. 학습 설정
- 데이터 historical 2020-01~. train < 2025-01-01 / val 2025. RobustScaler(EXOG, train fit).
- 지평별 독립 학습, val MAPE early stopping. 산출 = `best_lt_D{1..15}.pth` + `scaler_exog.pkl`
  + `metadata_lt.pkl`(HP·DMEAN/DSTD·RESID_STD). Colab GPU(`train_land_lt_colab.ipynb`).
- 이 기본 학습 위에 **D1-6 만 head 파인튜닝**(기본 가중치 보존, 신체제 재학습) → §9.

## 8. 다이어그램 권장 구성(박스·화살표 가이드)
- **좌측 입력 4박스**(past_numeric·past_y·future_numeric·anchor/clim) → 화살표로 모델 진입.
- **중앙 모델**: (A)인코더 스택 → (B)cross-attention(미래기상=Q, 과거패치=K, 인코더출력=V) → (C)헤드.
- **출력 합산 노드**: `anchor ⊕ RESID_STD·resid`.
- **우측 후처리**: `× calib[계절·시각·지평]`(D7-15 만) 박스 → est_horizon_land. D1-6 은 보정 건너뜀.
- **하단 띠(2구간)**: `D+1~6 = 파인튜닝본 head · 보정 없음` / `D+7~15 = 기존 head · 후처리 보정`.
- 색/강조: anchor·clim 경로(레벨)와 기상 경로(잔차)를 다른 색으로 구분하면 "레벨 분리" 의도가 보임.
- 실제 산출물 = `9. design/report/stage5/{5_model_v4.html(개요)·5_model_v4_tech.html(기술 상세)·5_anchor_clim.html(기준선 구성)}`.

> 핵심 수치 한눈: 입력 9공변량 + past_y / 패치 27 / d_model 256 / 헤드입력 520 / 출력 24h / 15벌(D1-6 파인튜닝본) / 보정 D7-15 만 ≤288셀(현재 216).

## 9. 지평별 파인튜닝 하이브리드 (G-24, 2026-06-21)
**문제**: BTM 태양광 폭증(2025~, 2026-03 용량 21GW)으로 한낮 계량수요를 과대예측(맑을수록 심함, solar 조건부).
레벨은 anchor/clim 이 잘 추적하나, residual head 가 BTM≈0(<2025) 시절 학습이라 한낮 봉우리를 얹는다.
후처리 보정표는 키가 (계절·시각·지평)뿐이라 **solar 조건부 spread 를 구조적으로 못 줄인다**(낮 range 보정≈raw, 흐린 날 오히려 악화).

**해법 — 지평별 차등**:
- **D1-6 = head 파인튜닝본.** 인코더·cross-attention 은 **동결**, residual head(`regressor`+`weather_bypass`, 약 5%)만
  신체제(2024-11~2025-11)로 재학습. scaler·DMEAN/DSTD·RESID_STD·HP 전부 보존. **후처리 보정 없음.**
- **D7-15 = 기존 v4 가중치 + 후처리 보정 유지.** (파인튜닝은 장지평에서 과적합이라 대체 불가.)

**학습 split**: train/val = historical(실측 기상), **격자 split p=1/6**(하루 단위·요일유형(평일/주말/공휴일)·계절 층화).
test = forecast_horizon(예보 기상, 186 base 2025-12-15~) 봉인 — 소스가 달라야 서빙 현실(예보오차)을 반영. train 은 2025-11-30 에서 끊어 test 와 무겹침.

**효과**(봉인 test): 전체 MAPE 3.95(기존 production 3.89 동급) · 단기 낮 solar spread 7.8→4.6.

**자산·코드**: `weights/best_lt_D{1..15}.pth`(D1-6=파인튜닝본·D7-15=기존), 원본 백업 `weights_v4_orig/`,
`calib_lt.json`(216셀, D7-15 만). 재현 = `finetune_lt.py` + `finetune_land_lt_colab.ipynb` + `eda_scaler/`(split).
서빙 경로 무변경(`serve_chain_land_new.py:LT_DIR`). 상세 = `weights/FINETUNE_NOTE.md`.

---

## 9. 지평별 하이브리드 (2026-06-21 production 갱신)
구조(1~8절)는 동일. **가중치·보정만 지평별로 차등** 배선했다. 배경·근거 = `eda_scaler/REPORT_demand_solar.md`,
폴더 메모 = `weights/FINETUNE_NOTE.md`.
- **원인**: BTM 태양광 폭증(2025~)으로 한낮 계량수요 과대(맑을수록 심함). residual head 가 <2025(BTM≈0) 학습이라 한낮 봉우리 stale.
  보정표는 (계절·시각·지평) 키라 **solar 조건부 spread 를 못 줄임**.
- **D1-6**: head 파인튜닝본(`finetune_lt.py`, 인코더 동결·head만, 2024-11~2025-11 신체제, 격자 split p=1/6) +
  **보정 없음**(calib_lt.json 초단·단 셀 제거 → 360→216). 낮 solar spread 7.8→4.6.
- **D7-15**: 기존 v4 가중치 + 보정 유지(ft 가 장지평 과적합이라 대체 불가, 보정 빼면 낮 +4.4% 복귀).
- 검증(forecast_horizon 186 base 봉인 test): 전체 MAPE 3.95(기존 3.89 동급)·낮 spread 10.3→8.9.
- 보정표 SSOT 갱신: `calibrate_lt.py` 를 **D7-15(중·중장·장)만 굽도록 수정 완료**(`SKIP_GROUPS={'초단','단'}`, 2026-06-21) → **재실행해도 D1-6 무보정 유지(안전)**. (초단·단 스킵은 주석으로 의도 보존.)

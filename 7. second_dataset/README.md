# 8. lng_dataset — A0/A1 데이터 확보·분리 패키지

PRD §5.0(데이터 단계) + §5.1(LNG 타깃 도출)의 산출물. **모델링(A2) 선행 게이트(G-6)**.

## 실행
```powershell
python "fit_merit_split.py"   # merit-order LNG/유류 분해함수 적합 + 백테스트 (먼저)
python "build_dataset.py"     # 결합·감사·타깃도출·split·parquet 출력
python "make_dictionary.py"   # data/data_dictionary.csv 생성
```
DB는 읽기 전용(`mode=ro`)으로만 연다. 모든 경로는 repo 루트 기준.

## 입력
- `1. data_fetcher_and_db/data/input_data_jeju.db`, `input_data_land.db` (historical/forecast)
- `7. data from csv/`: `only_gen`, `jeju_hvdc_hourly`, `oil_price_daily`, `gas_*`(KOGAS)

## 출력 (`data/`)
parquet 마스터·**full(전 구간 모델링용)**·split·서빙 + `kogas_monthly` + `data_dictionary.csv` + `audit.json`.
세부는 **`AUDIT_REPORT.md`** 참고.

`{jeju,land}_full.parquet` = 전 구간(2020~2026) 단일 모델링 데이터셋(누수컬럼 제외, 전 행 유지).
타깃 신뢰도는 `model_usable` 플래그로 구분: **제주는 실측 2020–24만 True**(2025~ derived/none=False),
**전국은 전 구간 True**(완전 실측). 즉 제주 타깃 불완전 vs 전국 완전의 비대칭이 행 단위로 드러난다.

## 핵심 규칙
- 정답(`lng_gen`/`gen_gas_kr`)은 피처 금지. 누수원(HVDC·유류·동시결정 발전·RT SMP) 제외.
- 분할은 시간순(랜덤 금지). 제주 `derived` 구간은 자기참조 → 정확도 제외(데모 표기).
- LNG/유류 분해는 **merit-order 부하수준별**(`merit_split_2024.json`, 급전순위 유류→LNG). 단일 비율 대비 MAE −14%.
- net_load는 `demand − renew_total`(G-1). DB `real_net_load_jeju`는 2025-12~만 존재해 미사용.

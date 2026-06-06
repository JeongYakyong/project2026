# -*- coding: utf-8 -*-
"""
데이터 딕셔너리 생성 (PRD §5.0-2: 정답/피처/금지 라벨링 + 누수 차단).
role 정의:
  key        결합 키
  target     검증 정답 (피처 절대 금지)
  feature    기본 모델 입력 (누수 없음, 서빙에서도 가용)
  feature_aux 선택 입력 (중복/외생, 누수는 아니나 기본 제외 권장)
  forbidden  금지 피처 (타깃 도출/co-determination/발행지연 누수원)
  meta       라벨/분할 등 메타
출력: data/data_dictionary.csv
"""
import os, pandas as pd

ROOT = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(ROOT, "data")

# region, column, role, source, note
ROWS = [
    # ---------------- 제주 ----------------
    ("jeju", "timestamp", "key", "DB.historical", "시간 키(KST, 시간별)"),
    ("jeju", "lng_gen", "target", "only_gen(실측)/merit도출", "LNG 발전량. 2020-24 실측, 2025 merit-order 도출. 피처 금지"),
    ("jeju", "target_source", "meta", "derived", "measured/derived/none"),
    ("jeju", "model_usable", "meta", "derived", "실측 타깃만 True(derived/none=False). 제주 타깃 불완전 플래그"),
    ("jeju", "split", "meta", "derived", "train/val/demo/unused"),
    ("jeju", "net_load", "feature", "도출 demand-renew", "잔여부하(=계통수요-신재생). 핵심 입력. G-1"),
    ("jeju", "temp_c_west", "feature", "DB.historical", "서/고산 기온"),
    ("jeju", "temp_c_east", "feature", "DB.historical", "동/성산 기온"),
    ("jeju", "temp_c_south", "feature", "DB.historical", "남/태양광지점 기온"),
    ("jeju", "day_type", "feature", "DB.historical", "weekday/weekend/holiday"),
    ("jeju", "hour", "feature", "calendar", "시"),
    ("jeju", "dow", "feature", "calendar", "요일0-6"),
    ("jeju", "month", "feature", "calendar", "월"),
    ("jeju", "doy", "feature", "calendar", "연중일"),
    ("jeju", "year", "feature", "calendar", "연도(추세)"),
    ("jeju", "hour_sin", "feature", "calendar", "시 주기 인코딩"),
    ("jeju", "hour_cos", "feature", "calendar", "시 주기 인코딩"),
    ("jeju", "month_sin", "feature", "calendar", "월 주기 인코딩"),
    ("jeju", "month_cos", "feature", "calendar", "월 주기 인코딩"),
    ("jeju", "doy_sin", "feature", "calendar", "계절 주기 인코딩"),
    ("jeju", "doy_cos", "feature", "calendar", "계절 주기 인코딩"),
    ("jeju", "Dubai", "feature_aux", "oil_price_daily", "외생 유가(서빙 가용). 기본 제외 권장"),
    ("jeju", "Brent", "feature_aux", "oil_price_daily", "외생 유가"),
    ("jeju", "WTI", "feature_aux", "oil_price_daily", "외생 유가"),
    ("jeju", "real_demand_jeju", "feature_aux", "DB.historical", "net_load 구성요소(중복). 누수 아님"),
    ("jeju", "real_renew_gen_jeju", "feature_aux", "DB.historical", "net_load 구성요소(중복)"),
    ("jeju", "real_solar_gen_jeju", "feature_aux", "DB.historical", "신재생 세부(중복)"),
    ("jeju", "real_wind_gen_jeju", "feature_aux", "DB.historical", "신재생 세부(중복)"),
    ("jeju", "real_net_load_jeju", "meta", "DB.historical", "DB원본 net_load(2025-12~만 존재). 도출 net_load 사용"),
    ("jeju", "HVDC_Total", "forbidden", "jeju_hvdc_hourly", "타깃 도출식 입력 → 누수. 서빙에도 없음"),
    ("jeju", "fuel_gen", "forbidden", "도출", "net_load-HVDC(=LNG+유류). 타깃 도출 중간값"),
    ("jeju", "lng_meas", "forbidden", "only_gen", "타깃 원천(=target). 피처 금지"),
    ("jeju", "oil_meas", "forbidden", "only_gen", "유류 발전(co-determination) → 누수"),
    ("jeju", "smp_jeju_rt", "forbidden", "DB.historical", "RT SMP 발행지연 누수"),
    ("jeju", "smp_rt_neg_num", "forbidden", "DB.historical", "RT SMP 파생 누수"),
    # ---------------- 전국 ----------------
    ("land", "timestamp", "key", "DB.historical", "시간 키"),
    ("land", "gen_gas_kr", "target", "DB.historical(실측)", "가스 발전량 실측. 검증목표2 정답. 피처 금지"),
    ("land", "target_source", "meta", "derived", "measured/none"),
    ("land", "model_usable", "meta", "derived", "실측 타깃만 True(전 구간 사실상 True). 제주와 대비되는 완전 타깃"),
    ("land", "split", "meta", "derived", "train/val/test/unused"),
    ("land", "net_load_kr", "feature", "DB.historical", "전국 잔여부하. 핵심 입력"),
    ("land", "temp_c_daegwallyeong", "feature", "DB.historical", "대관령 기온"),
    ("land", "temp_c_wonju", "feature", "DB.historical", "원주 기온"),
    ("land", "temp_c_seosan", "feature", "DB.historical", "서산 기온"),
    ("land", "temp_c_pohang", "feature", "DB.historical", "포항 기온"),
    ("land", "temp_c_yeonggwang", "feature", "DB.historical", "영광 기온"),
    ("land", "day_type", "feature", "DB.historical", "weekday/weekend/holiday"),
    ("land", "hour", "feature", "calendar", "시"),
    ("land", "dow", "feature", "calendar", "요일"),
    ("land", "month", "feature", "calendar", "월"),
    ("land", "doy", "feature", "calendar", "연중일"),
    ("land", "year", "feature", "calendar", "연도(추세)"),
    ("land", "hour_sin", "feature", "calendar", "주기 인코딩"),
    ("land", "hour_cos", "feature", "calendar", "주기 인코딩"),
    ("land", "month_sin", "feature", "calendar", "주기 인코딩"),
    ("land", "month_cos", "feature", "calendar", "주기 인코딩"),
    ("land", "doy_sin", "feature", "calendar", "주기 인코딩"),
    ("land", "doy_cos", "feature", "calendar", "주기 인코딩"),
    ("land", "renew_gen_total_kr", "feature_aux", "DB.historical", "net_load 구성요소(중복)"),
    ("land", "real_demand_land", "feature_aux", "DB.historical", "net_load 구성요소(중복)"),
    ("land", "gen_oil_kr", "forbidden", "DB.historical", "유류 발전 동시결정 → 누수"),
    ("land", "gen_coal_kr", "forbidden", "DB.historical", "석탄 발전 동시결정 → 누수"),
    ("land", "gen_nuclear_kr", "forbidden", "DB.historical", "원전 발전 동시결정 → 누수"),
    ("land", "gen_wind_kr", "forbidden", "DB.historical", "풍력 발전 동시결정(net_load에 반영됨)"),
    ("land", "smp_land_da", "feature_aux", "DB.historical", "DA SMP. 급전과 동시결정 우려 → 기본 제외"),
]

df = pd.DataFrame(ROWS, columns=["region", "column", "role", "source", "note"])
df.to_csv(os.path.join(OUT, "data_dictionary.csv"), index=False, encoding="utf-8-sig")
print("wrote data_dictionary.csv:", len(df), "rows")
print(df.groupby(["region", "role"]).size())

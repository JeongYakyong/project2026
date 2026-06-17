"""
collect_data_jeju_new.py -- (제주) forecast 기상 wide 라이브러리 (forecast_horizon 적재용).

역할별 재구성(2026-06-16).  육지(collect_data_land_new.build_forecast_wide)와 대칭인
제주판이다.  cron 한 줄 = 한 역할:
  ① 기상예보 → forecast_horizon   = collect_forecast_new.py (이 파일의 build_forecast_wide 사용)
  ② 실측      → historical        = collect_data_jeju.py (현행 유지)

KIMR + KIMG 병합은 검증된 collect_data_jeju 의 fetch/build_wide 를 **그대로 재사용**한다
(중복 코드 회피).  이 파일은 KPX(*_da) 호출과 DB 쓰기를 뺀 깨끗한 KMA 전용 forecast wide
라이브러리 표면만 제공한다.

병합 구조 (collect_data_jeju.build_wide 그대로)
  - 지점별 kimr_part.combine_first(kimg_part): KIMR 우선, KIMG 는 KIMR 이 못 채운 칸만.
  - radiation(일사)·cloud(구름)는 KIMR 에 없어 KIMG 단독 (전 지평).  일사는 3지점
    (radiation_west/east/south) -- 태양광 모델이 west+south 를 입력으로 쓴다.
  - temp/wind/gust/reh/rainfall 은 KIMR(D+1~D+5, 1h)이 채우고 D+6~ 는 KIMG(hf135 까지 1h,
    이후 3h)가 보충.  temp_skin/cape 등 KIMR 전용은 KIMG-only 구간에서 NaN.
  - 지평 깊이는 호출자가 forecast_days 로 결정(운영 기본 7일 = D+7).

라이브러리로 사용 (collect_forecast_new.py 가 호출)
    from collect_data_jeju_new import build_forecast_wide
    wide = build_forecast_wide(base=..., forecast_days=7)   # KIMR+KIMG 기상만, DB 안 씀
"""
from __future__ import annotations

from datetime import datetime

import pandas as pd

# 검증된 제주 fetch/pivot 로직을 그대로 재사용 (수정 없음).
import collect_data_jeju as cj
import postprocess as pp


# ── 기상 wide 라이브러리 (forecast_horizon 적재용; DB·KPX 쓰기 없음) ─────────
def build_forecast_wide(
    base: datetime | None = None,
    n_bases: int = 2,
    forecast_days: int | None = None,
) -> pd.DataFrame:
    """제주 KIMR+KIMG 병합 기상만 메모리 wide 로 반환.  KPX(*_da) 호출 없음, DB 쓰기 없음.

    collect_data_jeju.build() 에서 KPX(*_da) join 과 forecast 테이블 쓰기를 제거한 순수
    KMA 경로다 (= collect_forecast_runs 의 disable_kpx 패치판을 네이티브로 정리).
    collect_forecast_new.py 가 이 wide 에 base/horizon_d 태그를 붙여 forecast_horizon 에 적재.

    base/n_bases  : 발표 선택 (--base 단일 / 기본 최근 n_bases 발표).
    forecast_days : 수집 윈도우 길이(일).  None=기본(api_fetchers_jeju.FORECAST_DAYS).
                    7 = D+7 까지 (D+1~D+5 KIMR 1h, D+6~D+7 KIMG: hf135 까지 1h 이후 3h).
    """
    bases = cj._pick_bases(base, n_bases)
    with cj.forecast_days_override(forecast_days):
        # 윈도우는 반드시 override 안에서 계산한다 -- _window_for 가 FORECAST_DAYS
        # 글로벌을 읽으므로 밖에서 부르면 기본 2일로 잡혀 build_wide 가 D+2 까지로
        # 잘라버린다(KIMG 는 7일치를 받아도 결과가 48행이 되는 함정).
        window_start, window_end = cj._window_for(bases)
        # KIMR 순차(workers=1).  7일 윈도우는 ef=3,170,1(167스텝)을 한 요청에 통째로
        # 뽑아 요청이 무거운데, 지점 병렬(workers=3)로 겹치면 KMA 504(2025-12-28 실측).
        # 순차로 한 번에 하나씩 받아 서버 부하를 낮춘다.
        kimr_long = cj.fetch_kimr_long(bases, workers=1)
        # KIMG 지점 병렬 opt-in.  3 지점 전부 동시(동시성 3×6=18)는 KMA 504 로 hf 가
        # 빠져(2026-06-16 실측) 2 지점 동시(동시성 12)로 낮춘다 -- 1 point(=6)가 원래
        # 안전했던 기준선과의 절충.  여전히 빠지면 1(순차)로 더 내릴 것.
        kimg_long = cj.fetch_kimg_long(bases, point_workers=2)
    try:
        wide = cj.build_wide(kimr_long, kimg_long, window_start, window_end)
    except cj.NoUsableForecastRows:
        return pd.DataFrame()
    if wide.empty:
        return wide
    # postprocess: 범위 clip + day_type.  day_type 은 forecast_horizon 적재 시
    # _upsert_df 의 is_non_kma 필터가 떼므로 무해하지만 빌더 일관성 위해 적용.
    wide = pp.clip_ranges(wide)
    wide = pp.add_day_type(wide)
    return wide

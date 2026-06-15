"""
collect_data_land_new.py -- 육지(본토) **실측(historical) 단일목적 수집기** + 기상 wide 라이브러리.

역할별 재구성(2026-06-15).  기존 collect_data_land.py 는 forecast(KIMG 기상 + KPX *_da)
와 historical(KPX 수급/발전/DA + ASOS 관측)을 한 덩어리에 담아 --no-forecast/--no-historical
로 분기했다.  이 혼재가 서버 cron 분리·재시도·부분 적재 사고의 원인이라, 수집을 역할별
단일 진입점으로 쪼갠다 (PROJECT.md / 메모리 next-session-api-cleanup):

  ① 기상예보 → forecast_horizon   = collect_forecast_new.py  (KMA 기상 전용)
  ② 실측      → historical        = **이 파일**            (KPX 수급/발전/DA + ASOS)
  ③ 서빙 체인 → est_horizon_land  = serve_chain_land_new.py

전국(육지) 서빙은 레거시 `forecast` 테이블을 더는 쓰지 않는다 — 기상 입력은 forecast_horizon,
예측 출력은 est_horizon_land 로 이전(사용자 결정 2026-06-15).  그래서 이 수집기는 `forecast`
테이블에 아무것도 쓰지 않으며, KIMG 기상은 메모리 wide(build_forecast_wide)로만 노출해
collect_forecast_new.py 가 forecast_horizon 적재에 쓴다.  (KPX *_da 는 historical 에만 적재.)

검증된 fetch/pivot/historical 로직은 기존 collect_data_land.py 를 **그대로 import 재사용**한다
(700줄 중복 회피).  이 파일은 깔끔한 단일목적 CLI 표면만 제공한다.

사용
    python core/collect_data_land_new.py                          # 최근 2일치 historical (default)
    python core/collect_data_land_new.py --historical-days 7      # 최근 7일치
    python core/collect_data_land_new.py --start 2026-04-01 --end 2026-04-30   # 기간 지정
    python core/collect_data_land_new.py --no-save                # dry-run (DB 안 씀)

라이브러리로 사용 (collect_forecast_new.py 가 호출)
    from collect_data_land_new import build_forecast_wide
    wide = build_forecast_wide(base=..., forecast_days=16)   # KIMG-land 기상만, DB 안 씀
"""
from __future__ import annotations

import argparse
import time
from datetime import datetime
from pathlib import Path

import pandas as pd

# 검증된 육지 fetch/pivot/historical 로직을 그대로 재사용 (수정 없음).
import collect_data_land as cl
import postprocess as pp

DEFAULT_DB = cl.DEFAULT_DB


# ── 기상 wide 라이브러리 (forecast_horizon 적재용; DB·KPX 쓰기 없음) ─────────
def build_forecast_wide(
    base: datetime | None = None,
    n_bases: int = 2,
    forecast_days: int | None = None,
) -> pd.DataFrame:
    """KIMG-land 5 지점 기상만 메모리 wide 로 반환.  KPX(*_da) 호출 없음, DB 쓰기 없음.

    기존 build_forecast 에서 `_join_da`(KPX day-ahead)와 `forecast` 테이블 쓰기를 제거한
    순수 KIMG 경로다 (= collect_forecast_runs 의 disable_kpx 패치판을 네이티브로 정리).
    collect_forecast_new.py 가 이 wide 에 base/horizon_d 태그를 붙여 forecast_horizon 에 적재.

    base/n_bases  : 발표 선택 (--base 단일 / 기본 최근 n_bases 발표).
    forecast_days : 수집 윈도우 길이(일).  None=기본(_common.FORECAST_DAYS).  16 = D+15.5 까지.
    """
    bases = cl._pick_bases(base, n_bases)
    with cl.ckl.forecast_days_override(forecast_days):
        kimg_long = cl.fetch_kimg_land_long(bases)
    if kimg_long.empty:
        return pd.DataFrame()
    wide = cl.kimg_land_long_to_wide(kimg_long)
    if wide.empty:
        return wide
    # postprocess: 범위 clip + day_type (forecast_horizon 적재 시 day_type 은
    # _upsert_df 의 is_non_kma 필터가 떼므로 무해하지만, 빌더 일관성 위해 적용).
    wide = pp.clip_ranges(wide)
    wide = pp.add_day_type(wide)
    return wide


# ── CLI: 실측(historical) 전용 ─────────────────────────────────────────────
def main() -> None:
    p = argparse.ArgumentParser(
        description=(
            "육지(본토) 실측(historical) 단일목적 수집기 -> input_data_land.db.historical. "
            "KPX 육지 수급(sukub)/발전실적(gen_*_kr)/익일(*_da) + ASOS-land 5 지점 관측. "
            "forecast/forecast_horizon 은 건드리지 않는다(기상은 collect_forecast_new.py)."
        ),
    )
    p.add_argument("--start", default=None, help="historical start YYYY-MM-DD")
    p.add_argument("--end", default=None, help="historical end YYYY-MM-DD")
    p.add_argument(
        "--historical-days", type=int, default=2,
        help="historical window length in days (default 2; ignored if --start/--end)",
    )
    p.add_argument(
        "--db", type=Path, default=DEFAULT_DB,
        help=f"SQLite path (default {DEFAULT_DB})",
    )
    p.add_argument("--no-save", action="store_true", help="dry-run (don't write DB)")
    args = p.parse_args()

    t0 = time.time()
    print("=== historical 수집 (KPX 육지 + ASOS-land) ===")
    cl.build_historical(
        n_days_back=args.historical_days,
        start_date=args.start, end_date=args.end,
        save=not args.no_save, db_path=args.db,
    )
    print(f"\n[collect_data_land_new] done in {time.time() - t0:.1f}s")


if __name__ == "__main__":
    main()

#!/usr/bin/env bash
# ① 기상예보(KMA) 수집 wrapper **v2** — 신 KIM 소스(R030 1h + NE57 3h) -> forecast_horizon.
# 2026-07-04 KIM 개편 대응 (new_kma REPORT_03 로드맵).  구 wrapper(run_collect_forecast.sh)는
# 롤백 경로로 보존 -- 컷오버는 crontab 라인 교체로만 한다.
# ★cron 에서는 반드시 --production 을 붙인다 (없으면 격리 DB data/v2_*.db 에 쌓임).
# 예: 30 1 * * *  .../run_collect_forecast_v2.sh --backfill 3 --production
#     30 2 * * *  .../run_collect_forecast_v2.sh --backfill 3 --region jeju --production
set -u
REPO="$(cd "$(dirname "$0")/.." && pwd)"
PY="$REPO/.venv/bin/python"
LOG_DIR="$REPO/deploy/logs"
LOCK="/tmp/project2026_collect_forecast_v2.lock"

mkdir -p "$LOG_DIR"
cd "$REPO/1. data_fetcher_and_db"
exec flock -n "$LOCK" "$PY" core/collect_forecast_v2.py "$@" \
    >> "$LOG_DIR/collect_forecast_v2_$(date +%Y%m).log" 2>&1

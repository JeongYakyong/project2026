#!/usr/bin/env bash
# 지평별 누적(forecast_horizon) 수집 wrapper — crontab 에서 호출 (crontab.example 참고).
# 12 UTC 발표를 (base, timestamp) 키로 KMA 기상 예보 전용 테이블에 적재. 기존 수집과 독립.
# 추가 인자는 그대로 collect_forecast_runs.py 에 전달된다.
set -u
REPO="$(cd "$(dirname "$0")/.." && pwd)"
PY="$REPO/.venv/bin/python"
LOG_DIR="$REPO/deploy/logs"
LOCK="/tmp/project2026_collect_runs.lock"

mkdir -p "$LOG_DIR"
cd "$REPO/1. data_fetcher_and_db"
exec flock -n "$LOCK" "$PY" core/collect_forecast_runs.py "$@" \
    >> "$LOG_DIR/collect_runs_$(date +%Y%m).log" 2>&1

#!/usr/bin/env bash
# ① 기상예보(KMA) 수집 wrapper — 12 UTC 발표를 (base,timestamp) 키로 forecast_horizon 에 적재.
# 역할별 재구성(2026-06-15): 육지는 collect_forecast_new.py 가 clean wide(KPX 호출 없음)로 받는다.
# 기본 --region land (전국 우선).  제주 forecast_horizon 은 현행 run_collect_runs.sh --region jeju 유지.
# 추가 인자는 그대로 collect_forecast_new.py 에 전달된다 (예: --backfill 30, --region both).
set -u
REPO="$(cd "$(dirname "$0")/.." && pwd)"
PY="$REPO/.venv/bin/python"
LOG_DIR="$REPO/deploy/logs"
LOCK="/tmp/project2026_collect_forecast.lock"

mkdir -p "$LOG_DIR"
cd "$REPO/1. data_fetcher_and_db"
exec flock -n "$LOCK" "$PY" core/collect_forecast_new.py "$@" \
    >> "$LOG_DIR/collect_forecast_$(date +%Y%m).log" 2>&1

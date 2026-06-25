#!/usr/bin/env bash
# ② 실측(historical) 수집 wrapper — 육지 KPX 수급/발전/DA + ASOS-land → historical.
# 역할별 재구성(2026-06-15): collect_data_land.py(forecast+historical 혼재)를 대신해
# 실측만 단일목적으로 수집한다.  기상예보는 run_collect_forecast.sh, 서빙은 run_serve_chain_land.sh.
# 추가 인자는 그대로 collect_data_land_new.py 에 전달된다 (예: --historical-days 7).
set -u
REPO="$(cd "$(dirname "$0")/.." && pwd)"
PY="$REPO/.venv/bin/python"
LOG_DIR="$REPO/deploy/logs"
LOCK="/tmp/project2026_collect_land_new.lock"

mkdir -p "$LOG_DIR"
cd "$REPO/1. data_fetcher_and_db"
exec flock -n "$LOCK" "$PY" core/collect_data_land_new.py "$@" \
    >> "$LOG_DIR/collect_land_new_$(date +%Y%m).log" 2>&1

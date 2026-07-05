#!/usr/bin/env bash
# L010(국지 1.3km, D+2 1h) 아카이브 수집 wrapper — forecast_horizon_l010 (서빙 미연결).
# EDA 로 가치 확인 전까지 "수집만" (사용자 결정 2026-07-04).
# ★cron 에서는 --production 을 붙여 본 DB 의 별도 테이블에 쌓는다.
# 예: 50 5 * * *  .../run_collect_l010.sh --backfill 2 --region both --production
set -u
REPO="$(cd "$(dirname "$0")/.." && pwd)"
PY="$REPO/.venv/bin/python"
LOG_DIR="$REPO/deploy/logs"
LOCK="/tmp/project2026_collect_l010.lock"

mkdir -p "$LOG_DIR"
cd "$REPO/1. data_fetcher_and_db"
exec flock -n "$LOCK" "$PY" core/collect_l010_archive.py "$@" \
    >> "$LOG_DIR/collect_l010_$(date +%Y%m).log" 2>&1

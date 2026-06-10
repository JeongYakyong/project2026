#!/usr/bin/env bash
# 육지(전국) 수집 wrapper — crontab 에서 호출 (crontab.example / DEPLOY.md 참고).
# 추가 인자는 그대로 collect_data_land.py 에 전달된다.
# (00시대 실행은 `--bases 1 --kimg-days 7` 로 12 UTC 발표 7일 예보 수집 — G-12)
set -u
REPO="$(cd "$(dirname "$0")/.." && pwd)"
PY="$REPO/.venv/bin/python"
LOG_DIR="$REPO/deploy/logs"
LOCK="/tmp/project2026_collect_land.lock"

mkdir -p "$LOG_DIR"
cd "$REPO/1. data_fetcher_and_db"
exec flock -n "$LOCK" "$PY" core/collect_data_land.py "$@" \
    >> "$LOG_DIR/collect_land_$(date +%Y%m).log" 2>&1

#!/usr/bin/env bash
# 제주 수집 wrapper — crontab 에서 호출 (crontab.example / DEPLOY.md 참고).
# 레포가 어디에 clone 돼 있든 동작하도록 스크립트 자신의 위치 기준으로 경로를 푼다.
# 추가 인자는 그대로 collect_data_jeju.py 에 전달된다.
set -u
REPO="$(cd "$(dirname "$0")/.." && pwd)"
PY="$REPO/.venv/bin/python"
LOG_DIR="$REPO/deploy/logs"
LOCK="/tmp/project2026_collect_jeju.lock"

mkdir -p "$LOG_DIR"
cd "$REPO/1. data_fetcher_and_db"
exec flock -n "$LOCK" "$PY" core/collect_data_jeju.py "$@" \
    >> "$LOG_DIR/collect_jeju_$(date +%Y%m).log" 2>&1

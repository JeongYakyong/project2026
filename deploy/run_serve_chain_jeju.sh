#!/usr/bin/env bash
# ③ 서빙 체인 운영 러너 wrapper — 제주 2→3 최신 base → est_horizon_jeju.
# forecast_horizon(기상) 입력으로 수요·신재생→net_load 예측을 est_horizon_jeju(예측 아카이브)에
# 적재.  API 호출 없음(로컬 추론) — 반드시 실측·forecast_horizon 수집 완료 후 실행.  legacy
# forecast 테이블은 건드리지 않는다.  추가 인자는 그대로 serve_chain_jeju_new.py 에 전달된다
# (예: --backfill 7, --base 2026-06-16).
set -u
REPO="$(cd "$(dirname "$0")/.." && pwd)"
PY="$REPO/.venv/bin/python"
LOG_DIR="$REPO/deploy/logs"
LOCK="/tmp/project2026_serve_chain_jeju.lock"

mkdir -p "$LOG_DIR"
cd "$REPO"
exec flock -n "$LOCK" "$PY" "3. jeju_solarwind_forecaster/serve_chain_jeju_new.py" "$@" \
    >> "$LOG_DIR/serve_chain_jeju_$(date +%Y%m).log" 2>&1

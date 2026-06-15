#!/usr/bin/env bash
# ③ 서빙 체인 운영 러너 wrapper — 전국 5→6→7 최신 base → est_horizon_land.
# 역할별 재구성(2026-06-15): forecast_horizon(기상) 입력으로 수요·신재생·가스(보정·블렌딩) 예측을
# est_horizon_land(예측 아카이브)에 적재.  API 호출 없음(로컬 추론) — 반드시 ①·② 완료 후 실행.
# 추가 인자는 그대로 serve_chain_land_new.py 에 전달된다 (예: --backfill 3, --base 2026-06-14).
set -u
REPO="$(cd "$(dirname "$0")/.." && pwd)"
PY="$REPO/.venv/bin/python"
LOG_DIR="$REPO/deploy/logs"
LOCK="/tmp/project2026_serve_chain_land.lock"

mkdir -p "$LOG_DIR"
cd "$REPO"
exec flock -n "$LOCK" "$PY" "7. land_gas_forecaster/serve_chain_land_new.py" "$@" \
    >> "$LOG_DIR/serve_chain_land_$(date +%Y%m).log" 2>&1

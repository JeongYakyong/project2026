#!/usr/bin/env bash
# 서빙: 전국 일단위 도시가스 송출량(추정) — forecast_horizon(기온) → est_horizon_citygas.
# forecast_horizon(육지 기상예보)만 의존한다(수요·신재생·가스발전 체인 est_horizon_land 와 무관).
# API 호출 없음(로컬 추론) — ① 육지 기상예보 수집(forecast_horizon) 완료 후 실행하면 된다.
# 인자 없으면 최신 base 1건 서빙. 추가 인자는 그대로 serve_citygas_daily.py 에 전달
# (예: --backfill 3, --base 2026-01-07, --days 10).
set -u
REPO="$(cd "$(dirname "$0")/.." && pwd)"
PY="$REPO/.venv/bin/python"
LOG_DIR="$REPO/deploy/logs"
LOCK="/tmp/project2026_serve_citygas.lock"

mkdir -p "$LOG_DIR"
cd "$REPO"
exec flock -n "$LOCK" "$PY" "10. citygas_forecaster/serve_citygas_daily.py" "$@" \
    >> "$LOG_DIR/serve_citygas_$(date +%Y%m).log" 2>&1

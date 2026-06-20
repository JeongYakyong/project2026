#!/usr/bin/env bash
# ④ 제주 SMP 서빙 wrapper — est_horizon_jeju → est_smp_horizon_jeju (D+1·D+2 핵심3컬럼).
# 서빙 체인(③ run_serve_chain_jeju)이 est_horizon_jeju 를 채운 뒤 실행해야 한다(입력 의존).
# 미래 DA(historical.smp_jeju_da)는 ② run_collect_jeju 가 공급.  API 호출 없음(로컬 추론).
# forecast 테이블은 폐기됨(2026-06-20) — 건드리지 않는다.  추가 인자는 serve_smp_horizon_jeju.py 로
# 그대로 전달(예: --backfill 7, --base 2026-06-16).
set -u
REPO="$(cd "$(dirname "$0")/.." && pwd)"
PY="$REPO/.venv/bin/python"
LOG_DIR="$REPO/deploy/logs"
LOCK="/tmp/project2026_serve_smp_jeju.lock"

mkdir -p "$LOG_DIR"
cd "$REPO"
exec flock -n "$LOCK" "$PY" "4. jeju_smp_forecaster/serve_smp_horizon_jeju.py" "$@" \
    >> "$LOG_DIR/serve_smp_jeju_$(date +%Y%m).log" 2>&1

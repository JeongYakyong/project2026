#!/usr/bin/env bash
# 매일 자동 — 전국 지평 밴드(6구간) 종합 AI 브리핑 생성·저장(ai_briefings.db).
# 밴드(disjoint): D+1 · D+2 · D+3 · 단지평(D+4~5) · 중지평(D+6~10) · 장지평(D+11~15).
# DB(est_horizon_land 등)만 읽고 Gemini 만 호출한다 — KPX/KMA 수집은 트리거하지 않는다(한도 보호).
# ③ 서빙 체인(06:00)·④ 도시가스(06:50) 뒤에 둬 최신 base 예측 위에서 생성한다.
# 인자 없으면 오늘 기준 6밴드. 추가 인자는 gen_briefs_land.py 에 전달(예: --date 2026-06-25).
set -u
REPO="$(cd "$(dirname "$0")/.." && pwd)"
PY="$REPO/.venv/bin/python"
LOG_DIR="$REPO/deploy/logs"
LOCK="/tmp/project2026_gen_briefs.lock"

mkdir -p "$LOG_DIR"
cd "$REPO"
exec flock -n "$LOCK" "$PY" "8. streamlit/gen_briefs_land.py" "$@" \
    >> "$LOG_DIR/gen_briefs_$(date +%Y%m).log" 2>&1

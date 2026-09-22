#!/usr/bin/env bash
# ⑥ 외부 전송 API(serve_api) 상시 기동 가드 — 예측 시계열 + AI 브리핑을 HTTP 로 외부에 노출.
#   목적(루브릭 'AI 활용 확산성'): 다른 시스템이 우리 결과를 가져다 쓰게 함. /forecast·/brief·/bundle·/docs.
#   DB(est_horizon_land·ai_briefings.db)만 읽는다 — KPX/KMA 수집은 절대 트리거하지 않는다(한도 보호).
#
#   ★ 상시 데몬이라 "한 번 돌고 끝나는" 다른 wrapper 와 다르다 → 여러 번 돌려도 안전한 가드:
#     · 이미 떠 있으면(포트 응답) 아무것도 안 하고 즉시 종료
#     · 꺼져 있으면 백그라운드로 띄운다(setsid 로 세션 분리 → 이 스크립트가 끝나도 데몬은 계속 산다)
#   → 최초 1회 손으로 실행해 띄우고, crontab 에 같은 줄을 주기(예: */5)로 걸어두면
#     서버 재부팅·크래시 때 자동으로 되살아난다(매우 안정적 운영).
#
#   종료(수동):  pkill -f 'uvicorn serve_api:app'
#   포트 변경:   SERVE_API_PORT=9000 deploy/run_serve_api.sh   (기본 8800)
set -u
REPO="$(cd "$(dirname "$0")/.." && pwd)"
PY="$REPO/.venv/bin/python"
APP_DIR="$REPO/8. streamlit"
LOG_DIR="$REPO/deploy/logs"
LOG="$LOG_DIR/serve_api_$(date +%Y%m).log"
LOCK="/tmp/project2026_serve_api.lock"
HOST="${SERVE_API_HOST:-127.0.0.1}"   # 기본 내부 전용 — 이 서버는 Caddy 가 80/443→localhost 로 노출(DEPLOY §9). 직접 노출하려면 0.0.0.0.
PORT="${SERVE_API_PORT:-8800}"        # streamlit(8502)과 분리

mkdir -p "$LOG_DIR"

# 이미 떠 있으면(127.0.0.1:PORT TCP 응답) 그대로 둔다(중복 기동 안 함, curl 없이 bash /dev/tcp 로 점검)
if (exec 3<>"/dev/tcp/127.0.0.1/${PORT}") 2>/dev/null; then
    exec 3>&- 3<&-
    exit 0
fi

# 동시 기동 방지(가드가 겹쳐도 한 번만 띄움). fd 9 를 스크립트 종료까지 잠근다.
exec 9>"$LOCK"
flock -n 9 || exit 0

cd "$APP_DIR" || { echo "$(date '+%F %T') cd 실패: $APP_DIR" >> "$LOG"; exit 1; }

# setsid = wrapper 가 끝나도 데몬 유지(nohup 효과). 9>&- 로 lock fd 는 자식에 물려주지 않는다.
setsid "$PY" -m uvicorn serve_api:app --host "$HOST" --port "$PORT" >> "$LOG" 2>&1 9>&- &
echo "$(date '+%F %T') serve_api 기동(pid $!) → http://${HOST}:${PORT}  (docs: /docs)" >> "$LOG"

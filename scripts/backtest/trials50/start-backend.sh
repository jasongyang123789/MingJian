#!/bin/bash
# trials50 (FBOOK) rerun backend: scratch uvicorn on 127.0.0.1:$BACKTEST_PORT
# (default 8024), own DB $BACKTEST_RUN_DIR/trials50-fbook.db.
# Never touches :8000/3000 (standing deployment) or any other DB.
# Env: BACKTEST_PORT (default 8024), BACKTEST_RUN_DIR (default
# ~/.cache/mingjian-backtest/trials50-fbook), BACKTEST_LOCAL_ENV (optional
# file holding PLANAGENT_LOCAL_PROXY_SECRET=...), PLANAGENT_LOCAL_PROXY_SECRET
# (optional; otherwise a random secret is generated once and stored at
# $BACKTEST_RUN_DIR/.proxy-secret, mode 600, for the runners to read).
set -u
HARNESS_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$HARNESS_DIR/../../.." && pwd)"
PORT="${BACKTEST_PORT:-8024}"
RUN_DIR="${BACKTEST_RUN_DIR:-$HOME/.cache/mingjian-backtest/trials50-fbook}"
mkdir -p "$RUN_DIR"
DB="$RUN_DIR/trials50-fbook.db"
LOG="$RUN_DIR/server-$PORT.log"
if curl -s -m 10 --noproxy '*' "http://127.0.0.1:$PORT/health" | grep -q '"status":"ok"'; then
  echo "backend already up on :$PORT"; exit 0
fi
if [ -n "${PLANAGENT_LOCAL_PROXY_SECRET:-}" ]; then
  SECRET="$PLANAGENT_LOCAL_PROXY_SECRET"
elif [ -n "${BACKTEST_LOCAL_ENV:-}" ] && [ -f "$BACKTEST_LOCAL_ENV" ]; then
  SECRET=$(python3 -c "
for l in open('$BACKTEST_LOCAL_ENV'):
    if l.startswith('PLANAGENT_LOCAL_PROXY_SECRET='):
        print(l.strip().split('=',1)[1]); break
")
elif [ -f "$RUN_DIR/.proxy-secret" ]; then
  SECRET=$(cat "$RUN_DIR/.proxy-secret")
else
  SECRET=$(python3 -c 'import secrets; print(secrets.token_hex(32))')
fi
printf '%s' "$SECRET" > "$RUN_DIR/.proxy-secret"
chmod 600 "$RUN_DIR/.proxy-secret"
export PLANAGENT_DATABASE_URL="sqlite+aiosqlite:///$DB"
export PLANAGENT_EVENT_BUS_BACKEND=memory
export PLANAGENT_LOCAL_PROXY_SECRET="$SECRET"
cd "$REPO_ROOT" || exit 1
nohup "$REPO_ROOT/.venv/bin/python" -m uvicorn planagent.main:app \
  --host 127.0.0.1 --port "$PORT" >>"$LOG" 2>&1 &
echo "backend starting (pid $!), log: $LOG"
for _ in $(seq 1 60); do
  if curl -s -m 5 --noproxy '*' "http://127.0.0.1:$PORT/health" | grep -q '"status":"ok"'; then
    echo "backend up on :$PORT"; exit 0
  fi
  sleep 2
done
echo "backend did NOT come up; see $LOG"; exit 1

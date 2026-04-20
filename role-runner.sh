#!/bin/bash
# ============================================================
# Role Runner — Process Supervisor
# Runs multiple Hermes worker processes per container
# ============================================================

set -e

ROLE_LIST="${HERMES_ROLES:-}"
PAPERCLIP_URL="${PAPERCLIP_API_URL:-http://paperclip:3100/api}"
MINIMAX_KEY="${MINIMAX_API_KEY:-}"
NIM_KEY="${NVIDIA_NIM_KEY:-}"
NIM_BASE_URL="${NVIDIA_NIM_BASE_URL:-https://integrate.api.nvidia.com/v1}"

# Parse comma-separated roles
IFS=',' read -ra ROLES <<< "$ROLE_LIST"

echo "╔════════════════════════════════════════════════════════╗"
echo "║  Hermes Role Runner — $(printf '%-28s' "${#ROLES[@]} roles") ║"
echo "╚════════════════════════════════════════════════════════╝"
echo ""

# Wait for Paperclip
echo "[Bootstrap] Waiting for Paperclip at $PAPERCLIP_URL..."
for i in $(seq 1 30); do
  if curl -sf "$PAPERCLIP_URL/health" > /dev/null 2>&1; then
    echo "  ✓ Paperclip is ready"
    break
  fi
  echo "  Waiting... ($i/30)"
  sleep 2
done

# Export API keys as env for hermes
if [ -n "$MINIMAX_KEY" ]; then
  export MINIMAX_API_KEY="$MINIMAX_KEY"
fi
if [ -n "$NIM_KEY" ]; then
  export NVIDIA_NIM_KEY="$NIM_KEY"
fi
if [ -n "$NIM_BASE_URL" ]; then
  export NVIDIA_NIM_BASE_URL="$NIM_BASE_URL"
fi

# Source hermes venv if available (for local dev)
if [ -f /root/.hermes/hermes-agent/venv/bin/activate ]; then
  source /root/.hermes/hermes-agent/venv/bin/activate
fi

# Start each role as a background process
for ROLE in "${ROLES[@]}"; do
  ROLE=$(echo "$ROLE" | tr -d '[:space:]')
  [ -z "$ROLE" ] && continue

  CONFIG_FILE="/etc/hermes/workers/${ROLE}/config.yaml"
  SESSION_DIR="/var/hermes/sessions/${ROLE}"

  mkdir -p "$SESSION_DIR"

  echo "[Start] $ROLE"
  echo "  Config: $CONFIG_FILE"
  echo "  Session: $SESSION_DIR"

  # Start hermes in background with per-role log
  hermes chat \
    --config "$CONFIG_FILE" \
    --session-id "$ROLE" \
    --adapter paperclip \
    --heartbeat \
    >> "/app/logs/${ROLE}.log" 2>&1 &

  echo "  PID: $!"
  sleep 0.5
done

echo ""
echo "[Runner] All ${#ROLES[@]} roles started"
echo ""
echo "[Runner] Logging to /app/logs/"
ls -la /app/logs/ 2>/dev/null | grep -v "^total" | head -20

echo ""
echo "[Runner] Spawning log tailer..."
# Tail all logs in background
tail -f /app/logs/*.log &
TAIL_PID=$!

# Monitor all roles
MONITOR_INTERVAL=60
echo "[Runner] Monitoring every ${MONITOR_INTERVAL}s..."
while true; do
  sleep "$MONITOR_INTERVAL"

  for ROLE in "${ROLES[@]}"; do
    ROLE=$(echo "$ROLE" | tr -d '[:space:]')
    [ -z "$ROLE" ] && continue

    LOG_FILE="/app/logs/${ROLE}.log"

    # Check if process is still running
    # Look for hermes process associated with this role in process list
    if ! pgrep -f "hermes.*${ROLE}" > /dev/null 2>&1; then
      echo "[!] $ROLE died — restarting..."

      hermes chat \
        --config "/etc/hermes/workers/${ROLE}/config.yaml" \
        --session-id "$ROLE" \
        --adapter paperclip \
        --heartbeat \
        >> "$LOG_FILE" 2>&1 &

      echo "  Restarted $ROLE (PID: $!)"
    fi
  done
done &
MONITOR_PID=$!

# Cleanup on exit
trap "kill $TAIL_PID $MONITOR_PID 2>/dev/null; exit" SIGINT SIGTERM

wait

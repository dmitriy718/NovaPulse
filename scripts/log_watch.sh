#!/usr/bin/env bash
set -euo pipefail

BASE="$(cd "$(dirname "$0")/.." && pwd)"
LOG="$BASE/logs/errors.log"
STATE="$BASE/.log_watch.offset"
OUT="$BASE/logs/error_watch.log"
SECRETS_DIR="$BASE/.secrets"

rotate_if_large() {
  local path="$1"
  local max_bytes="${2:-200000000}" # ~200MB
  if [ -f "$path" ]; then
    local sz
    sz=$(wc -c < "$path" | tr -d ' ' || echo 0)
    if [ "${sz:-0}" -gt "$max_bytes" ] 2>/dev/null; then
      mv "$path" "${path}.$(date +%Y%m%d_%H%M%S)" 2>/dev/null || true
      : > "$path"
    fi
  fi
}

TOKEN="${TELEGRAM_BOT_TOKEN:-}"
CHAT_ID="${TELEGRAM_CHAT_ID:-}"
if [ -z "$TOKEN" ] && [ -f "$SECRETS_DIR/telegram_token" ]; then
  TOKEN=$(cat "$SECRETS_DIR/telegram_token" | tr -d '[:space:]')
fi
if [ -z "$CHAT_ID" ] && [ -f "$SECRETS_DIR/telegram_chat_id" ]; then
  CHAT_ID=$(cat "$SECRETS_DIR/telegram_chat_id" | tr -d '[:space:]')
fi

if [ ! -f "$LOG" ]; then
  exit 0
fi

curr_size=$(wc -c < "$LOG" | tr -d ' ')
last_size=0
if [ -f "$STATE" ]; then
  last_size=$(cat "$STATE" || echo 0)
fi

# Log rotation or truncation handling
if [ "$curr_size" -lt "$last_size" ]; then
  last_size=0
fi

if [ "$curr_size" -gt "$last_size" ]; then
  new=$(tail -c +$((last_size + 1)) "$LOG")
  if echo "$new" | grep -E -i "error|exception|traceback|pair scan failed|strategy error|background task" >/dev/null; then
    rotate_if_large "$OUT"
    clean=$(echo "$new" | sed -r 's/\x1B\[[0-9;]*[A-Za-z]//g' | sed -e $'s/\r//g')
    {
      echo "---- $(date -Is) ----"
      echo "$clean"
    } >> "$OUT"
    if [ -n "$TOKEN" ] && [ -n "$CHAT_ID" ]; then
      msg=$(printf "[%s] Error log update %s\n\n%s" "$(hostname)" "$(date -Is)" "$clean")
      msg=$(printf '%s' "$msg" | head -c 3800)
      curl -s -X POST "https://api.telegram.org/bot${TOKEN}/sendMessage" \
        --data-urlencode "chat_id=${CHAT_ID}" \
        --data-urlencode "text=${msg}" >/dev/null || true
    fi
  fi
fi

echo "$curr_size" > "$STATE"

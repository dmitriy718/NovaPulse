#!/usr/bin/env bash
set -euo pipefail

BASE="$(cd "$(dirname "$0")/.." && pwd)"
SECRETS="$BASE/.secrets"
STATE="$BASE/.health_check.state"
OUT="$BASE/logs/health_check.log"

mkdir -p "$BASE/logs" >/dev/null 2>&1 || true

BANKROLL="${INITIAL_BANKROLL:-}"
if [ -z "$BANKROLL" ] && [ -f "$BASE/.env" ]; then
  # Under pipefail, a "no match" grep would abort the script unless we swallow the non-zero exit.
  BANKROLL="$(
    (grep -E '^INITIAL_BANKROLL=' "$BASE/.env" || true) \
      | tail -n 1 \
      | cut -d'=' -f2- \
      | tr -d '[:space:]'
  )"
fi
if [ -z "$BANKROLL" ]; then
  BANKROLL="10000"
fi

TOKEN="${TELEGRAM_BOT_TOKEN:-}"
CHAT_ID="${TELEGRAM_CHAT_ID:-}"
if [ -z "$TOKEN" ] && [ -f "$SECRETS/telegram_token" ]; then
  TOKEN=$(tr -d '[:space:]' < "$SECRETS/telegram_token")
fi
if [ -z "$CHAT_ID" ] && [ -f "$SECRETS/telegram_chat_id" ]; then
  CHAT_ID=$(tr -d '[:space:]' < "$SECRETS/telegram_chat_id")
fi
can_notify="1"
if [ -z "$TOKEN" ] || [ -z "$CHAT_ID" ]; then
  can_notify="0"
fi

now_epoch=$(date +%s)
# Prefer a compose-resolved container id (avoids collisions when multiple projects exist).
container_name="$(cd "$BASE" && docker compose ps -q trading-bot 2>/dev/null | head -n 1 || true)"
if [ -z "${container_name:-}" ]; then
  container_name="novapulse"
fi
container_running="0"
container_health="none"
uptime_s="0"
pid=""

if command -v docker >/dev/null 2>&1; then
  # "healthy|unhealthy|starting" (or "none" if no healthcheck)
  running_flag="$(docker inspect -f '{{.State.Running}}' "${container_name}" 2>/dev/null || echo false)"
  if [ "${running_flag}" = "true" ]; then
    container_running="1"
    container_health="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "${container_name}" 2>/dev/null || echo none)"
    started_at="$(docker inspect -f '{{.State.StartedAt}}' "${container_name}" 2>/dev/null || true)"
    if [ -n "${started_at:-}" ]; then
      start_epoch=$(date -d "${started_at}" +%s 2>/dev/null || echo 0)
      if [ "$start_epoch" -gt 0 ] 2>/dev/null; then
        uptime_s=$((now_epoch - start_epoch))
      fi
    fi
  fi
fi

if [ "$container_running" != "1" ]; then
  pid="$({ pgrep -fa "venv/bin/python.*main\\.py" 2>/dev/null | awk 'NR==1{print $1}'; } || true)"
  if [ -n "${pid:-}" ] && [ -f "/proc/${pid}/stat" ]; then
    uptime_s=$(/usr/bin/python3 - <<'PY' 2>/dev/null || echo 0
import os
pid = int(os.environ.get("PID") or 0)
with open("/proc/uptime", "r") as f:
    uptime_sys = float(f.read().split()[0])
with open(f"/proc/{pid}/stat", "r") as f:
    fields = f.read().split()
start_ticks = int(fields[21])
hz = os.sysconf(os.sysconf_names["SC_CLK_TCK"])
print(max(uptime_sys - (start_ticks / hz), 0.0))
PY
PID="${pid}")
  fi
fi

status="DOWN"
status_emoji="🔴"
if [ "$container_running" = "1" ] || [ -n "${pid:-}" ]; then
  status="RUNNING"
  status_emoji="✅"
  if [ "$container_running" = "1" ] && [ "${container_health}" != "healthy" ] && [ "${container_health}" != "none" ]; then
    status_emoji="🟠"
  fi
fi

restart_attempted="0"
restart_note=""
if [ "$status" = "DOWN" ]; then
  restart_attempted="1"
  restart_note=" (restart attempted)"
  # Prefer docker compose if a compose file exists and docker is available.
  if command -v docker >/dev/null 2>&1 && [ -f "$BASE/docker-compose.yml" ]; then
    (cd "$BASE" && docker compose up -d >/dev/null 2>&1) || true
  else
    # Host-mode restart (venv). The main process has an instance lock to prevent duplicates.
    if [ -x "$BASE/venv/bin/python" ] && [ -f "$BASE/main.py" ]; then
      (cd "$BASE" && nohup "$BASE/venv/bin/python" "$BASE/main.py" >> "$BASE/logs/bot_output.log" 2>&1 &) || true
    fi
  fi
fi

format_duration() {
  local s="${1:-0}"
  local total=${s%.*}
  if [ -z "$total" ]; then total=0; fi
  local h=$((total / 3600))
  local m=$(((total % 3600) / 60))
  local sec=$((total % 60))
  printf "%02d:%02d:%02d" "$h" "$m" "$sec"
}

get_db_stats_host() {
  (
    cd "$BASE" && INITIAL_BANKROLL="$BANKROLL" PYTHONPATH="$BASE" /usr/bin/python3 - <<'PY'
from pathlib import Path
import os
import sqlite3
from src.core.config import ConfigManager
from src.core.multi_engine import resolve_db_path, resolve_trading_accounts

cfg = ConfigManager().config
base = os.getenv("DB_PATH") or cfg.app.db_path or "data/trading.db"
accounts = resolve_trading_accounts(cfg.exchange.name, getattr(cfg.app, "trading_accounts", ""))
if not accounts:
    accounts = [{"account_id": getattr(cfg.app, "account_id", "default"), "exchange": (cfg.exchange.name or "kraken")}]
multi = len(accounts) > 1
paths = []
for spec in accounts:
    ex = str(spec.get("exchange") or cfg.exchange.name or "kraken").strip().lower()
    account_id = str(spec.get("account_id") or "default").strip().lower()
    resolved = resolve_db_path(base, ex, multi=multi, account_id=account_id)
    p = Path(resolved)
    if not p.is_absolute():
        p = (Path.cwd() / p).resolve()
    if str(p) not in paths:
        paths.append(str(p))

initial_bankroll = float(os.environ.get("INITIAL_BANKROLL", "10000") or 10000)
total = max_id = open_positions = 0
win_rate = 0.0
drawdown_pnl = 0.0
drawdown_pct = 0.0
streak_label = "N/A"
closed_rows = []

for db in paths:
    if not os.path.exists(db):
        continue
    conn = sqlite3.connect(db, timeout=5)
    cur = conn.cursor()
    cur.execute("select count(*) from trades")
    total += int(cur.fetchone()[0] or 0)
    cur.execute("select max(id) from trades")
    max_id = max(max_id, int(cur.fetchone()[0] or 0))
    cur.execute("select count(*) from trades where status='open'")
    open_positions += int(cur.fetchone()[0] or 0)
    cur.execute("select coalesce(exit_time, entry_time, ''), pnl from trades where status='closed'")
    for ts, pnl in cur.fetchall():
        closed_rows.append((str(ts or ""), float(pnl or 0.0)))
    conn.close()

closed_rows.sort(key=lambda r: r[0])
if closed_rows:
    wins = sum(1 for _, p in closed_rows if p > 0)
    win_rate = wins / max(len(closed_rows), 1)
    cum = 0.0
    peak = float(initial_bankroll)
    streak = 0
    streak_type = ''
    last = None
    for _, p in closed_rows:
        pnl_val = float(p or 0.0)
        cum += pnl_val
        equity = initial_bankroll + cum
        if equity > peak:
            peak = equity
        win = pnl_val > 0
        if last is None:
            streak = 1
            streak_type = 'W' if win else 'L'
        elif win == last:
            streak += 1
        else:
            streak = 1
            streak_type = 'W' if win else 'L'
        last = win
    equity_now = initial_bankroll + cum
    drawdown_pnl = max(0.0, peak - equity_now)
    drawdown_pct = (drawdown_pnl / peak * 100.0) if peak > 0 else 0.0
    if streak_type:
        streak_label = f"{streak_type}{streak}"

print(f"{total} {max_id} {open_positions} {win_rate} {drawdown_pnl} {drawdown_pct} {streak_label} {len(paths)}")
PY
  ) 2>/dev/null || true
}

get_db_stats_container() {
  INITIAL_BANKROLL="$BANKROLL" docker exec -i "${container_name}" python - <<'PY' 2>/dev/null || true
import os, sqlite3
from pathlib import Path

def resolve_runtime_db_paths():
    try:
        from src.core.config import ConfigManager
        from src.core.multi_engine import resolve_db_path, resolve_trading_accounts

        cfg = ConfigManager().config
        base = os.getenv("DB_PATH") or cfg.app.db_path or "data/trading.db"
        accounts = resolve_trading_accounts(cfg.exchange.name, getattr(cfg.app, "trading_accounts", ""))
        if not accounts:
            accounts = [{"account_id": getattr(cfg.app, "account_id", "default"), "exchange": (cfg.exchange.name or "kraken")}]
        multi = len(accounts) > 1
        paths = []
        for spec in accounts:
            ex = str(spec.get("exchange") or cfg.exchange.name or "kraken").strip().lower()
            account_id = str(spec.get("account_id") or "default").strip().lower()
            resolved = resolve_db_path(base, ex, multi=multi, account_id=account_id)
            p = Path(resolved)
            if not p.is_absolute():
                p = (Path("/app") / p).resolve()
            if str(p) not in paths:
                paths.append(str(p))
        return paths
    except Exception:
        return ["/app/data/trading.db"]

db_paths = resolve_runtime_db_paths()
initial_bankroll_raw = (os.environ.get("INITIAL_BANKROLL") or "").strip()
initial_bankroll = 0.0
if initial_bankroll_raw:
    try:
        initial_bankroll = float(initial_bankroll_raw)
    except Exception:
        initial_bankroll = 0.0
if initial_bankroll <= 0:
    # Prefer the running config inside the container.
    try:
        import yaml
        cfg_path = "/app/config/config.yaml"
        if os.path.exists(cfg_path):
            cfg = yaml.safe_load(open(cfg_path, "r")) or {}
            initial_bankroll = float(((cfg.get("risk") or {}).get("initial_bankroll")) or 0.0)
    except Exception:
        pass
if initial_bankroll <= 0:
    initial_bankroll = 10000.0

total = max_id = open_positions = 0
win_rate = 0.0
drawdown_pnl = 0.0
drawdown_pct = 0.0
streak_label = "N/A"
closed_rows = []

for db in db_paths:
    if not os.path.exists(db):
        continue
    conn = sqlite3.connect(db, timeout=5)
    cur = conn.cursor()
    cur.execute("select count(*) from trades")
    total += int(cur.fetchone()[0] or 0)
    cur.execute("select max(id) from trades")
    max_id = max(max_id, int(cur.fetchone()[0] or 0))
    cur.execute("select count(*) from trades where status='open'")
    open_positions += int(cur.fetchone()[0] or 0)
    cur.execute("select coalesce(exit_time, entry_time, ''), pnl from trades where status='closed'")
    for ts, pnl in cur.fetchall():
        closed_rows.append((str(ts or ""), float(pnl or 0.0)))
    conn.close()

closed_rows.sort(key=lambda r: r[0])
if closed_rows:
    wins = sum(1 for _, p in closed_rows if p > 0)
    win_rate = wins / max(len(closed_rows), 1)
    cum = 0.0
    peak = float(initial_bankroll)
    streak = 0
    streak_type = ''
    last = None
    for _, p in closed_rows:
        pnl_val = float(p or 0.0)
        cum += pnl_val
        equity = initial_bankroll + cum
        if equity > peak:
            peak = equity
        win = pnl_val > 0
        if last is None:
            streak = 1
            streak_type = 'W' if win else 'L'
        elif win == last:
            streak += 1
        else:
            streak = 1
            streak_type = 'W' if win else 'L'
        last = win
    equity_now = initial_bankroll + cum
    drawdown_pnl = max(0.0, peak - equity_now)
    drawdown_pct = (drawdown_pnl / peak * 100.0) if peak > 0 else 0.0
    if streak_type:
        streak_label = f"{streak_type}{streak}"

print(f"{total} {max_id} {open_positions} {win_rate} {drawdown_pnl} {drawdown_pct} {streak_label} {len(db_paths)}")
PY
}

stats="0 0 0 0.0 0.0 0.0 N/A 0"
if [ "$container_running" = "1" ]; then
  stats="$(get_db_stats_container)"
else
  stats="$(get_db_stats_host)"
fi
if [ -z "${stats:-}" ]; then
  stats="0 0 0 0.0 0.0 0.0 N/A 0"
fi

read -r total_trades max_id open_positions win_rate drawdown_pnl drawdown_pct streak_label db_count <<<"$stats" || true
total_trades="${total_trades:-0}"
max_id="${max_id:-0}"
open_positions="${open_positions:-0}"
win_rate="${win_rate:-0.0}"
drawdown_pnl="${drawdown_pnl:-0.0}"
drawdown_pct="${drawdown_pct:-0.0}"
streak_label="${streak_label:-N/A}"
db_count="${db_count:-0}"

last_id=0
if [ -f "$STATE" ]; then
  last_id=$(cat "$STATE" 2>/dev/null || echo 0)
fi
new_trades=0
if [ "$max_id" -ge "$last_id" ] 2>/dev/null; then
  new_trades=$((max_id - last_id))
fi

uptime_fmt="$(format_duration "${uptime_s}")"
now_iso=$(date -Is)
win_rate_pct="$(awk -v v="${win_rate}" 'BEGIN { printf "%.1f%%", (v + 0.0) * 100.0 }')"
drawdown_line="$(printf '$%.2f (%.2f%%)' "${drawdown_pnl}" "${drawdown_pct}")"

host_label="${HOSTNAME:-$(hostname)}"
container_line=""
if [ "$container_running" = "1" ]; then
  clabel="${container_name}"
  if [ "${#clabel}" -gt 20 ] 2>/dev/null; then
    clabel="${clabel:0:12}"
  fi
  container_line=$(printf "\n*Container:* %s (%s)" "${clabel}" "${container_health}")
fi

msg=$(printf "✨ *All Systems Check* ✨\n\n*Host:* %s\n*Status:* %s %s%s%s\n*Uptime:* %s\n*DBs:* %s\n*Open Positions:* %s\n*Win Rate:* %s\n*Drawdown:* %s\n*Streak:* %s\n*Total Trades:* %s\n*New Trades:* %s\n*Time:* %s" \
  "${host_label}" "${status_emoji}" "${status}" "${restart_note}" "${container_line}" "${uptime_fmt}" "${db_count}" "${open_positions}" "${win_rate_pct}" "${drawdown_line}" "${streak_label}" "${total_trades}" "${new_trades}" "${now_iso}")

{
  echo "---- $(date -Is) ----"
  echo "$msg"
} >> "$OUT"

if [ "${can_notify}" = "1" ]; then
  curl -s -X POST "https://api.telegram.org/bot${TOKEN}/sendMessage" \
    --data-urlencode "chat_id=${CHAT_ID}" \
    --data-urlencode "parse_mode=Markdown" \
    --data-urlencode "text=${msg}" >/dev/null || true
fi

echo "$max_id" > "$STATE"

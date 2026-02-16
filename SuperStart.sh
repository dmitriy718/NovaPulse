#!/bin/bash
set -euo pipefail

# ==============================================================================
# NovaPulse v3 — Docker-First Deployment & Operations
# ==============================================================================
#
# Usage:
#   ./SuperStart.sh              Build & start the trading bot
#   ./SuperStart.sh --stress     Launch 5-minute quick stress test
#   ./SuperStart.sh --stress72   Launch full 72-hour stress monitor
#   ./SuperStart.sh --stop       Stop all containers
#   ./SuperStart.sh --logs       Follow live logs
#   ./SuperStart.sh --status     Show container status + health
#   ./SuperStart.sh --rebuild    Force rebuild image from scratch
#   ./SuperStart.sh --shell      Open a shell inside the running container
#
# Environment:
#   FAST_SETUP=1   Skip git pull
# ==============================================================================

BOLD='\033[1m'
GREEN='\033[0;32m'
CYAN='\033[0;36m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
DIM='\033[2m'
NC='\033[0m'

BASE="$(cd "$(dirname "$0")" && pwd)"
cd "$BASE"

ts() { echo -n "[$(date +%H:%M:%S)] "; }

banner() {
  echo -e "${CYAN}${BOLD}"
  echo "    ╔══════════════════════════════════════════════╗"
  echo "    ║         NovaPulse v3.0.0 — Docker Deploy     ║"
  echo "    ║       AI Crypto Trading Bot Operations        ║"
  echo "    ╚══════════════════════════════════════════════╝"
  echo -e "${NC}"
}

# ---------- Helpers ----------

check_docker() {
  if ! command -v docker &>/dev/null; then
    echo -e "$(ts)${RED}Docker not found. Install: https://docs.docker.com/engine/install/${NC}"
    exit 1
  fi
  if ! docker info &>/dev/null; then
    echo -e "$(ts)${RED}Docker daemon not running. Start it first.${NC}"
    exit 1
  fi
  if ! docker compose version &>/dev/null; then
    echo -e "$(ts)${RED}Docker Compose plugin not found. Install: https://docs.docker.com/compose/install/${NC}"
    exit 1
  fi
}

ensure_env() {
  if [ ! -f ".env" ]; then
    echo -e "$(ts)${YELLOW}No .env found. Creating from .env.example...${NC}"
    if [ -f ".env.example" ]; then
      cp .env.example .env
      echo -e "$(ts)${GREEN}✓ .env created. Edit it with your API keys before going live.${NC}"
    else
      echo -e "$(ts)${RED}No .env.example found either. Cannot continue.${NC}"
      exit 1
    fi
  fi
}

ensure_dirs() {
  mkdir -p data logs models config .secrets
}

# ---------- Commands ----------

cmd_start() {
  banner
  check_docker

  # 0. Code update
  echo -e "\n$(ts)${BOLD}[1/4] Code Update${NC}"
  if [ "${FAST_SETUP:-}" != "1" ]; then
    echo -e "  $(ts)${DIM}Pulling latest from origin...${NC}"
    git pull origin main 2>/dev/null || echo -e "  $(ts)${YELLOW}Git pull skipped (not a git repo or no remote).${NC}"
    echo -e "  $(ts)${GREEN}✓ Repository up to date.${NC}"
  else
    echo -e "  $(ts)${YELLOW}FAST_SETUP=1: skipping git pull.${NC}"
  fi

  # 1. Prerequisites
  echo -e "\n$(ts)${BOLD}[2/4] Prerequisites${NC}"
  ensure_env
  ensure_dirs
  echo -e "  $(ts)${GREEN}✓ .env present, directories ready.${NC}"

  # 2. Build & Start
  echo -e "\n$(ts)${BOLD}[3/4] Building & Starting Containers${NC}"
  echo -e "  $(ts)${DIM}Running docker compose up --build -d ...${NC}"
  docker compose up --build -d
  echo -e "  $(ts)${GREEN}✓ Containers started.${NC}"

  # 3. Health check
  echo -e "\n$(ts)${BOLD}[4/4] Health Check${NC}"
  echo -e "  $(ts)${DIM}Waiting for bot to become healthy (up to 120s)...${NC}"

  healthy=0
  for i in $(seq 1 24); do
    sleep 5
    health="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}starting{{end}}' novapulse 2>/dev/null || echo starting)"
    if [ "$health" = "healthy" ]; then
      healthy=1
      break
    fi
    echo -e "  $(ts)${DIM}  ...status: ${health} (${i}/24)${NC}"
  done

  if [ "$healthy" = "1" ]; then
    echo -e "  $(ts)${GREEN}✓ Bot is healthy and trading!${NC}"
  else
    echo -e "  $(ts)${YELLOW}⚠ Bot started but health check not yet passing. Check logs:${NC}"
    echo -e "  $(ts)${DIM}  docker compose logs -f trading-bot${NC}"
  fi

  # Dashboard info
  HOST_PORT="$(grep -E '^HOST_PORT=' .env 2>/dev/null | cut -d= -f2 | tr -d '[:space:]' || echo '127.0.0.1:8090')"
  echo -e "\n$(ts)${CYAN}${BOLD}DEPLOYMENT COMPLETE${NC}"
  echo -e "  Dashboard: http://${HOST_PORT}"
  echo -e "  Logs:      docker compose logs -f trading-bot"
  echo -e "  Stress:    ./SuperStart.sh --stress"
  echo -e "  Stop:      ./SuperStart.sh --stop"
}

cmd_rebuild() {
  banner
  check_docker
  ensure_env
  ensure_dirs

  echo -e "$(ts)${BOLD}Force rebuilding image from scratch...${NC}"
  docker compose build --no-cache
  docker compose up -d
  echo -e "$(ts)${GREEN}✓ Rebuilt and restarted.${NC}"
}

cmd_stop() {
  check_docker
  echo -e "$(ts)${BOLD}Stopping NovaPulse containers...${NC}"
  docker compose down
  echo -e "$(ts)${GREEN}✓ All containers stopped.${NC}"
}

cmd_logs() {
  check_docker
  docker compose logs -f trading-bot
}

cmd_status() {
  check_docker
  echo -e "${BOLD}Container Status:${NC}"
  docker compose ps
  echo ""

  health="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}N/A{{end}}' novapulse 2>/dev/null || echo 'not running')"
  started="$(docker inspect -f '{{.State.StartedAt}}' novapulse 2>/dev/null || echo 'N/A')"
  echo -e "  Health:     ${health}"
  echo -e "  Started at: ${started}"

  # Try to hit the health endpoint
  HOST_PORT="$(grep -E '^HOST_PORT=' .env 2>/dev/null | cut -d= -f2 | tr -d '[:space:]' || echo '127.0.0.1:8090')"
  if curl -fsS "http://${HOST_PORT}/api/v1/health" &>/dev/null; then
    echo -e "  API:        ${GREEN}responding${NC}"
  else
    echo -e "  API:        ${RED}not responding${NC}"
  fi
}

cmd_stress() {
  local hours="${1:-0.083}"
  local interval="${2:-1}"

  check_docker
  ensure_env

  echo -e "$(ts)${BOLD}Launching Stress Monitor (${hours}h, every ${interval}m)${NC}"

  # Read API key from .env for auth
  API_KEY="$(grep -E '^DASHBOARD_READ_KEY=' .env 2>/dev/null | cut -d= -f2 | tr -d '[:space:]' || true)"

  # Read dashboard port from .env
  DASH_PORT="$(grep -E '^DASHBOARD_PORT=' .env 2>/dev/null | cut -d= -f2 | tr -d '[:space:]' || echo '8080')"

  # Run stress test inside a container on the same Docker network.
  # Uses the service name "trading-bot" as hostname so it reaches the bot container.
  docker compose run --rm \
    --no-deps \
    -e PYTHONPATH=/app \
    -e DASHBOARD_URL="http://trading-bot:${DASH_PORT}" \
    trading-bot \
    python stress_test.py --hours "$hours" --interval "$interval" --api-key "${API_KEY:-}"
}

cmd_shell() {
  check_docker
  echo -e "$(ts)${DIM}Opening shell in novapulse container...${NC}"
  docker compose exec trading-bot /bin/bash || docker compose exec trading-bot /bin/sh
}

# ---------- Main ----------

case "${1:-}" in
  --stop)
    cmd_stop
    ;;
  --logs)
    cmd_logs
    ;;
  --status)
    cmd_status
    ;;
  --stress)
    # Quick 5-minute stress test
    cmd_stress 0.083 1
    ;;
  --stress72)
    # Full 72-hour stress monitor
    cmd_stress 72 5
    ;;
  --rebuild)
    cmd_rebuild
    ;;
  --shell)
    cmd_shell
    ;;
  --help|-h)
    banner
    echo "Usage: ./SuperStart.sh [COMMAND]"
    echo ""
    echo "Commands:"
    echo "  (none)       Build & start the trading bot (default)"
    echo "  --stress     Quick 5-minute stress test"
    echo "  --stress72   Full 72-hour stress monitor"
    echo "  --stop       Stop all containers"
    echo "  --logs       Follow live logs"
    echo "  --status     Show container health & status"
    echo "  --rebuild    Force rebuild image (no cache)"
    echo "  --shell      Open shell in running container"
    echo "  --help       Show this help"
    echo ""
    echo "Environment:"
    echo "  FAST_SETUP=1  Skip git pull on start"
    ;;
  *)
    cmd_start
    ;;
esac

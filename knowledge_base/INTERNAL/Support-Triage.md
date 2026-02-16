# Support Triage (Internal)

Last updated: 2026-02-13

## What To Collect First

1. Client report time range in UTC.
1. Domain affected: `nova.horizonsvc.com` (Nova Horizon) or `agent.horizonsvc.com` (Agent).
1. Exact error: `401`, `502`, `OFFLINE`, `STALE FEED`, or “no trades”.
1. Whether the client pressed Pause, Resume, or Kill.

## Quick Checks

1. Service status:
```bash
docker ps --format "table {{.Names}}\t{{.Status}}"
```

2. Caddy logs:
```bash
docker logs --tail 200 caddy
```

3. Market state (authenticated):
```bash
PASS="$(cat /home/ops/agent-stack/.nova_pass)"
curl -u "nova:$PASS" -sS https://nova.horizonsvc.com/api/state
```

4. Agent health:
```bash
curl -sS https://agent.horizonsvc.com/health
```

## Common Root Causes

1. Wrong or rotated Basic Auth credentials.
1. Market upstream WebSocket reconnect loops (feed stale).
1. Guardrails preventing trades: max spread, daily loss, pause, kill.
1. Caddy upstream resolution errors (rare, usually during container recreation).

## Ticket Response Templates

If 401:

1. Confirm the client is using the latest credentials.
1. If needed, rotate and reissue credentials.

If stale feed:

1. Confirm `feed_stale` and timestamps in `/api/state`.
1. Ask client to wait for automatic reconnect, or schedule a restart during a safe window.

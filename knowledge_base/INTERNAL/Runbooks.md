# Runbooks (Internal)

Last updated: 2026-02-13

## 1) Nova Horizon Shows OFFLINE

Symptoms:

1. Nova Horizon UI status shows `OFFLINE`.
1. `/api/state` fails or returns non-200.

Steps:

1. Verify Caddy is running: `docker ps | rg caddy`.
1. Verify market is running and healthy: `docker ps | rg market`.
1. Check Caddy logs for upstream errors:
`docker logs --tail 200 caddy`.
1. Check market logs:
`docker logs --tail 200 market`.
1. Check local endpoint inside container:
`docker exec market python -c 'import urllib.request; print(urllib.request.urlopen(\"http://127.0.0.1:9000/api/health\").read().decode())'`

Likely causes:

1. Market container restarted and is still in startup grace.
1. Basic Auth password mismatch (401 from `nova.horizonsvc.com`).

## 2) Nova Horizon Returns 401 Unauthorized

Meaning:

1. Basic Auth rejected.

Steps:

1. On the server, retrieve the current password:
`cat /home/ops/agent-stack/.nova_pass`
1. Validate:
`curl -u "nova:<PASSWORD>" -sS https://nova.horizonsvc.com/api/health`

## 3) Agent `/chat` Returns 401

Meaning:

1. Basic Auth required and rejected.

Steps:

1. On the server:
`cat /home/ops/agent-stack/.agent_chat_pass`
1. Validate:
`curl -u "agent:<PASSWORD>" -sS https://agent.horizonsvc.com/chat -H \"Content-Type: application/json\" -d '{\"query\":\"ping\"}'`

## 4) Trading Is Not Happening

Check in `/api/state`:

1. `trading_enabled` should be `true`.
1. `kill_switch` should be `false`.
1. `paused` should be `false`.
1. `feed_stale` should be `false` for the active exchange.

Steps:

1. Look for `guardrail` events in `docker logs market`.
1. Check staleness:
`curl -u "nova:<PASSWORD>" https://nova.horizonsvc.com/api/state`
1. Confirm exchange connectivity events in logs:
`coinbase_connected`, `kraken_connected`, or errors.

Common reasons:

1. Feed stale (WebSocket reconnecting).
1. Spread too wide (`MAX_SPREAD_BPS`).
1. Daily loss limit hit (`MAX_DAILY_LOSS_USD`).

## 5) Emergency Stop

Immediate action:

1. Trigger kill:
`curl -u "nova:<PASSWORD>" -X POST https://nova.horizonsvc.com/api/kill`

Verify:

1. `kill_switch: true` in `/api/state`.

Recovery:

1. Resume:
`curl -u "nova:<PASSWORD>" -X POST https://nova.horizonsvc.com/api/resume`

## 6) Safe Restart

```bash
cd /home/ops/agent-stack\nsudo systemctl start agent-stack.service\n# or:\ndocker compose up -d --remove-orphans\n```

Then validate:

1. `https://agent.horizonsvc.com/health`
1. `https://nova.horizonsvc.com/api/health` (with Basic Auth)

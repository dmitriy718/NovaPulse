# Nova Horizon Handoff (2026-02-14)

**Project:** Nova Horizon (public v2.0.0; internal v1.0.0)

**Droplet:** DigitalOcean `165.245.143.68`
- SSH user: `ops`
- Stack directory: `/home/ops/agent-stack`
- Docker compose project: `agent-stack`
- Containers: `caddy`, `agent-api`, `market`, `qdrant`

## How To SSH Next Time
- SSH key path (local): `~/.ssh/horizon`
- Command:
  - `ssh -i ~/.ssh/horizon ops@165.245.143.68`

## Domains / Entry Points
- Agent web UI (chat): `https://agent.horizonsvc.com/chat`
  - Note: `agent.horizon.com` does not resolve (DNS failure).
- Nova dashboard: `https://nova.horizonsvc.com`

## Auth / Credentials
- Both `nova.horizonsvc.com` and the agent chat UI are protected with Caddy Basic Auth.
- Username: `nova_admin`
- Password locations (do not paste into tickets/Slack):
  - Local repo: `admininfo.txt`
  - Droplet: `/home/ops/agent-stack/.nova_pass` and `/home/ops/agent-stack/.agent_chat_pass`

## Current State (Where We Left Off)
- The agent chat blank/white page issue was traced to routing behavior on `GET /chat`.
- Caddy has been updated so `GET /chat` serves the static agent web UI from `/home/ops/agent-stack/agent_ui`.
- `POST /chat` is proxied to `agent-api:8000`.
  - Request payload expected by the API: `{"query":"..."}` (not `{"message":"..."}`).
- `GET /health` is now public (no Basic Auth) and returns JSON like:
  - `{"status":"ok","agent":"HorizonOperator"}`

## What To Verify Next
- In an incognito browser session:
  1. Visit `https://agent.horizonsvc.com/chat` and log in.
  2. If still white page, open DevTools and check whether `/app.js` and `/styles.css` return `200` (not `401/404`).
  3. Confirm sending a message returns an answer (network call should be `POST /chat` with JSON body `{query: ...}` and a `200` response).

## Key Server Files
- Caddy config: `/home/ops/agent-stack/Caddyfile`
- Agent UI assets: `/home/ops/agent-stack/agent_ui/index.html`, `/home/ops/agent-stack/agent_ui/app.js`, `/home/ops/agent-stack/agent_ui/styles.css`
- Compose file: `/home/ops/agent-stack/docker-compose.yml`


# Operations (Internal)

Last updated: 2026-02-13

This section is for support/dev on-call tasks: restart services, check health, read logs, and validate the current trading state.

## Host Basics

1. Hostname: `horizon`
1. Provider: DigitalOcean droplet
1. OS: Ubuntu 22.04

## Where The Stack Lives

1. Compose directory: `/home/ops/agent-stack`
1. Compose file: `/home/ops/agent-stack/docker-compose.yml`
1. Caddyfile: `/home/ops/agent-stack/Caddyfile`
1. Data directory: `/home/ops/agent-stack/data`

## Service Management

The stack is managed by a systemd oneshot unit that runs `docker compose up -d`:

1. Unit: `agent-stack.service`
1. Location: `/etc/systemd/system/agent-stack.service`

Common commands:

```bash
sudo systemctl status agent-stack.service --no-pager -l
sudo systemctl start agent-stack.service
sudo systemctl stop agent-stack.service
```

If you need to manage compose directly:

```bash
cd /home/ops/agent-stack
docker compose ps
docker compose up -d --remove-orphans
docker compose down
```

## Health Checks

1. Agent:
```bash
curl -sS https://agent.horizonsvc.com/health
```

2. Nova Horizon API (requires Basic Auth):
```bash
curl -u "nova:<PASSWORD>" -sS https://nova.horizonsvc.com/api/health
curl -u "nova:<PASSWORD>" -sS https://nova.horizonsvc.com/api/state
```

3. Market container local API:
```bash
docker exec market python -c 'import urllib.request; print(urllib.request.urlopen(\"http://127.0.0.1:9000/api/health\").read().decode())'
```

## Logs

```bash
docker logs --tail 200 agent-api
docker logs --tail 200 market
docker logs --tail 200 caddy
docker logs --tail 200 qdrant
```

## Credentials (Where Stored)

Credentials are stored on the server as files readable only by `ops`.

1. Nova Horizon dashboard/API Basic Auth password:
`/home/ops/agent-stack/.nova_pass`

2. Agent `/chat` Basic Auth password:
`/home/ops/agent-stack/.agent_chat_pass`

Do not paste these into tickets or chat logs.

## Emergency Controls

The market engine supports these operator actions:

1. Pause trading:
`POST /api/pause`

2. Resume trading:
`POST /api/resume`

3. Kill switch:
`POST /api/kill`

Internally they map to files under `/data`:

1. `/data/PAUSE`
1. `/data/EMERGENCY_STOP`

## Backups

1. Backup script: `/home/ops/agent-stack/ops/backup.sh`
1. Backup output directory: `/home/ops/agent-stack/backups`
1. Cron: `/etc/cron.d/agent-stack-backup` (runs daily at 03:15 UTC)

Manual run:

```bash
sudo -u ops /home/ops/agent-stack/ops/backup.sh
ls -la /home/ops/agent-stack/backups
```

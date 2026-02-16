# Architecture (Internal)

Last updated: 2026-02-13

## High-Level Overview

The production system is a single Docker Compose stack (`agent-stack`) running on a DigitalOcean droplet. It exposes two public HTTPS domains via Caddy:

1. `agent.horizonsvc.com`: HorizonOperator agent API (`/health` public, `/chat` protected).
1. `nova.horizonsvc.com`: Nova Horizon dashboard + API (`/` static UI, `/api/*` protected).

## Components

1. Reverse proxy and TLS: Caddy (`caddy` container).
1. Agent API: FastAPI service (`agent-api` container).
1. Market engine + Nova Horizon API: Python asyncio service (`market` container).
1. Vector DB: Qdrant (`qdrant` container, internal-only).

## Network Model

1. Public ingress: ports `80` and `443` on the droplet.
1. Only Caddy binds host ports.
1. Market and agent services are only reachable to Caddy and internally via Docker networks.
1. Qdrant is internal-only (not published to the host).

## Public Surface Area

1. `GET https://agent.horizonsvc.com/health`
1. `POST https://agent.horizonsvc.com/chat` (Basic Auth required)
1. `GET https://nova.horizonsvc.com/` (Basic Auth required)
1. `GET https://nova.horizonsvc.com/api/state` (Basic Auth required)
1. `POST https://nova.horizonsvc.com/api/pause` (Basic Auth required)
1. `POST https://nova.horizonsvc.com/api/resume` (Basic Auth required)
1. `POST https://nova.horizonsvc.com/api/kill` (Basic Auth required)

## Data Flow Summary

1. Caddy terminates TLS and routes requests by host.
1. Market engine connects to exchanges via REST/WebSockets, computes signals, and (optionally) places orders.
1. Market engine writes NDJSON (and optional Parquet rollups) to disk under `/home/ops/agent-stack/data` (bind-mounted into the container at `/data`).
1. Nova Horizon dashboard is static HTML/JS served by Caddy, calling `/api/*` to read state and send control actions.
1. Agent API calls an LLM upstream and returns an operator-grade response.

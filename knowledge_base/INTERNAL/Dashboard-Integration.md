# Horizon Dashboard Integration

**Version:** 5.0.0
**Last Updated:** 2026-02-28

---

## Overview

NovaPulse bot instances are connected to the **horizonsvc.com** web dashboard ("Nova by Horizon"), a Next.js + Fastify SaaS application that gives each customer a rich, real-time view of their bot's performance, positions, trades, strategies, and AI reasoning. The horizonsvc.com API acts as an authenticated proxy — it stores each user's bot connection info (URL + API key) and forwards requests from the frontend to the user's NovaPulse bot.

```
Customer Browser
      |
      v
horizonsvc.com (Next.js 15 frontend)
      |  Firebase Auth (Bearer token)
      v
Fastify API (port 4000) — /bot/* proxy routes
      |  X-API-Key header
      v
Caddy Reverse Proxy (nova.horizonsvc.com, HTTPS)
      |
      v
NovaPulse Bot Container (trading-bot:8080)
```

---

## Architecture

### Components

| Component | Location | Technology | Purpose |
|-----------|----------|-----------|---------|
| Web Frontend | VPS 74.208.153.193 `/opt/horizonalerts/apps/web/` | Next.js 15, Tailwind | Customer dashboard UI |
| API Server | VPS 74.208.153.193 `/opt/horizonalerts/services/api/` | Fastify, TypeScript | Auth, billing, bot proxy |
| PostgreSQL | Docker on same VPS | PostgreSQL 16 | Users, entitlements, bot_connections |
| Caddy Proxy | OPS 165.245.143.68 `/home/ops/agent-stack/` | Caddy v2 | HTTPS termination for `nova.horizonsvc.com` |
| NovaPulse Bot | OPS 165.245.143.68 `/home/ops/novatrader/` | Python, Docker | Trading engine + API |

### Network Flow

1. Customer opens `https://horizonsvc.com/dashboard`
2. Next.js frontend authenticates via Firebase Auth and gets an ID token
3. Frontend calls `GET /bot/performance` with `Authorization: Bearer <firebase_token>`
4. Fastify API verifies the Firebase token → extracts `uid`
5. API queries `bot_connections` table for the user's bot URL + API key
6. API proxies the request to the bot (e.g., `https://nova.horizonsvc.com/api/v1/performance`) with the `X-API-Key` header
7. Caddy terminates HTTPS and forwards to `trading-bot:8080` on the Docker network
8. NovaPulse bot validates the API key and returns data
9. Fastify forwards the response back to the frontend

### Docker Network Topology (OPS Server)

```
novatrader_trading-net (bridge network)
    |
    +-- trading-bot (NovaPulse container, port 8080 internal)
    |       Mapped: 127.0.0.1:8090 → 8080 (localhost only)
    |
    +-- elasticsearch (port 9200 internal)
            Mapped: 127.0.0.1:9200 → 9200 (localhost only)

agent-stack (separate compose project)
    |
    +-- caddy (ports 80, 443 public)
    |       Network: novatrader_trading-net (external)
    |       Routes nova.horizonsvc.com → trading-bot:8080
    |
    +-- agent-api (internal)
    +-- qdrant (internal)
```

Key detail: The Caddy container joins `novatrader_trading-net` as an external network, allowing it to reach `trading-bot:8080` by Docker DNS name. Port 8080 is **not** exposed to the public internet — all external access goes through Caddy on ports 80/443.

---

## Database: `bot_connections` Table

**Migration:** `services/api/db/migrations/004_bot_connections.sql`

```sql
CREATE TABLE IF NOT EXISTS bot_connections (
  id SERIAL PRIMARY KEY,
  uid TEXT NOT NULL REFERENCES users(uid),
  bot_url TEXT NOT NULL,
  api_key TEXT NOT NULL,
  hosting_type TEXT NOT NULL DEFAULT 'managed',
  label TEXT DEFAULT 'My Bot',
  status TEXT DEFAULT 'active',
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now(),
  UNIQUE(uid)
);
```

| Column | Type | Description |
|--------|------|-------------|
| `uid` | TEXT | Firebase UID, foreign key to `users(uid)` |
| `bot_url` | TEXT | Full URL to the bot (e.g., `https://nova.horizonsvc.com`) |
| `api_key` | TEXT | NovaPulse read key or admin key |
| `hosting_type` | TEXT | `managed` (Horizon-hosted) or `self-hosted` |
| `label` | TEXT | User-friendly name |
| `status` | TEXT | `active` or `disconnected` |

One connection per user (`UNIQUE(uid)`). Upsert pattern via `ON CONFLICT (uid) DO UPDATE`.

---

## API: Bot Proxy Routes

**File:** `services/api/src/routes/bot.ts`
**Prefix:** `/bot`
**Auth:** All routes use `server.requireAuth` (Firebase token verification)

### Proxy Endpoints

| API Route | Proxies To | Allowed QS Params |
|-----------|-----------|-------------------|
| `GET /bot/status` | `/api/v1/status` | — |
| `GET /bot/performance` | `/api/v1/performance` | — |
| `GET /bot/positions` | `/api/v1/positions` | — |
| `GET /bot/trades` | `/api/v1/trades` | `limit`, `offset` |
| `GET /bot/strategies` | `/api/v1/strategy-performance` | — |
| `GET /bot/risk` | `/api/v1/risk` | — |
| `GET /bot/thoughts` | `/api/v1/thoughts` | `limit` |

Proxy behavior:
- Lookup: `uid` → `bot_connections` → `bot_url` + `api_key`
- No connection → 404 `{"error": "no_bot_connected"}`
- Bot unreachable → 502 `{"error": "bot_unreachable"}`
- Query string allowlisting prevents parameter injection
- 10-second timeout per proxy request (`AbortSignal.timeout(10_000)`)
- Redirect following disabled (`redirect: "error"`) to prevent SSRF via redirect

### Connection Management Endpoints

| Method | Route | Description |
|--------|-------|-------------|
| `GET /bot/connection` | Returns connection info (no raw `api_key` in response) |
| `PUT /bot/connection` | Upsert connection with validation |
| `DELETE /bot/connection` | Soft-delete (sets `status = 'disconnected'`) |

#### PUT /bot/connection — Validation Flow

1. Parse request body with Zod schema (url, api_key, hosting_type, label)
2. **SSRF check**: `isAllowedBotUrl()` blocks private IPs, localhost, link-local, RFC 1918 ranges, and does DNS resolution check to prevent DNS rebinding
3. **Connectivity test**: `proxyToBot(bot_url, api_key, "/api/v1/status")` — must return 200
4. If validation passes: upsert into `bot_connections`
5. Return connection info (without raw api_key)

---

## SSRF Protection

The `isAllowedBotUrl()` function in `bot.ts` provides layered SSRF protection:

1. **URL parsing**: Rejects malformed URLs
2. **IP string check**: Blocks `localhost`, `127.0.0.1`, `::1`, `0.0.0.0`, `169.254.*`, `10.*`, `172.16-31.*`, `192.168.*`, `fc*`, `fd*`, `fe80*`
3. **DNS resolution check**: Resolves the hostname and checks all returned addresses against the same blocklist (prevents DNS rebinding attacks where `attacker.com` resolves to `127.0.0.1`)
4. **Redirect blocking**: `redirect: "error"` on fetch prevents chained redirects to internal services

---

## Frontend Integration

### Dashboard (`apps/web/app/dashboard/page.tsx`)

The dashboard is a single-page React component with five tabs:

| Tab | Data Source | Poll Interval |
|-----|-----------|---------------|
| **Overview** | `/bot/performance`, `/bot/status` | 5 seconds |
| **Positions** | `/bot/positions` | 5 seconds |
| **Trades** | `/bot/trades?limit=100` | 15 seconds |
| **Strategies** | `/bot/strategies` | 15 seconds |
| **AI Feed** | `/bot/thoughts` | 15 seconds |

**Polling strategy:**
- Two polling loops: fast (5s) for performance/positions/status, slow (15s) for trades/strategies/risk/thoughts
- Exponential backoff on errors: `baseMs * 2^failCount`, max 60s
- Fail count resets on successful fetch

**Not-connected state:** If `GET /bot/connection` returns 404, the dashboard shows an inline setup wizard with hosting type selection (Managed vs Self-hosted) and connection form.

**Gamification layer:** The dashboard includes ranks, XP, achievements, and win streaks derived from trade data. This is computed client-side from the performance and trades responses.

### Settings (`apps/web/app/settings/page.tsx`)

The "Trading Bot" tab provides:
- **Connected state**: Status dot, masked bot URL, hosting type badge, "Open Dashboard" link, disconnect button
- **Not connected**: Guided 2-step wizard (choose hosting type → enter credentials)
- Connection test results with contextual error messages (unreachable, auth failed, etc.)

---

## Caddy Configuration

**File:** `/home/ops/agent-stack/Caddyfile`

```
nova.horizonsvc.com {
    encode zstd gzip
    header {
        Strict-Transport-Security "max-age=31536000; includeSubDomains; preload"
        X-Content-Type-Options "nosniff"
        X-Frame-Options "DENY"
        Referrer-Policy "no-referrer"
        -Server
    }
    reverse_proxy trading-bot:8080
}
```

Caddy handles:
- Automatic HTTPS via Let's Encrypt (ACME)
- HTTP → HTTPS redirect
- Response compression (zstd, gzip)
- Security headers (HSTS, no-sniff, no-frame, no-referrer)
- Server header removal

DNS: `nova.horizonsvc.com` → `165.245.143.68` (A record)

---

## Provisioning a Managed Customer

When a new managed customer subscribes:

1. Their NovaPulse bot is already running at `https://nova.horizonsvc.com` (shared instance) or a dedicated instance
2. The read API key is emailed to them along with the bot URL
3. Customer logs into `horizonsvc.com/dashboard`
4. Dashboard prompts them to connect → they enter the bot URL and API key
5. The Fastify API validates the connection and stores it in `bot_connections`
6. Dashboard starts showing live data

For **self-hosted** customers:
1. They run NovaPulse on their own server
2. They enter their bot's public URL (e.g., `http://their-ip:8080`) and API key
3. SSRF validation ensures the URL doesn't point to internal networks
4. Same flow from step 5 above

---

## Troubleshooting

### "Bot unreachable" on connection test

1. Verify the bot is running: `curl https://nova.horizonsvc.com/api/v1/health`
2. Check Caddy logs: `docker logs caddy --tail 50`
3. Check Docker network: `docker exec caddy curl -s http://trading-bot:8080/api/v1/health`
4. Verify DNS: `dig +short nova.horizonsvc.com` should return `165.245.143.68`

### "Authentication failed" on connection test

1. Verify the API key: `curl -H "X-API-Key: <key>" https://nova.horizonsvc.com/api/v1/status`
2. Check that the key matches `DASHBOARD_READ_KEY` or `DASHBOARD_ADMIN_KEY` in the bot's `.secrets/env`

### Dashboard shows stale data

1. Check the bot's health: `curl https://nova.horizonsvc.com/api/v1/health`
2. If unhealthy, check bot logs: `docker logs novatrader-trading-bot-1 --tail 50`
3. Check Fastify API: `curl -s http://localhost:4000/health` on the horizonsvc VPS

### Dashboard shows "Not connected" despite saved connection

1. Check `bot_connections` table: `SELECT * FROM bot_connections WHERE uid = '<uid>';`
2. Verify `status = 'active'` (not `disconnected`)
3. Test the stored URL manually

---

## Security Considerations

1. **API keys in transit**: Bot API keys travel from Fastify → Caddy → NovaPulse, always over HTTPS (Caddy terminates TLS)
2. **API keys at rest**: Stored as plaintext in `bot_connections.api_key` in PostgreSQL. The PostgreSQL instance is not exposed to the internet (Docker internal networking only). Future improvement: encrypt at rest with an application-level key.
3. **No key exposure**: The `GET /bot/connection` endpoint never returns the raw `api_key` to the frontend
4. **SSRF protection**: Private IP blocking + DNS rebinding prevention on user-supplied bot URLs
5. **Auth chain**: Firebase token → Fastify `requireAuth` → user `uid` → `bot_connections` lookup → per-user bot key. No cross-user data leakage.
6. **Rate limiting**: Fastify rate limiter (120 req/min) applies to all bot proxy routes

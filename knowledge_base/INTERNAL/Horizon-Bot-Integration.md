# Bot Integration

This document describes how HorizonAlerts connects to and proxies requests to NovaPulse trading bot instances.

---

## Overview

HorizonAlerts acts as a secure proxy between the customer dashboard and their NovaPulse bot. Each user has one bot connection (stored in `bot_connections`), and the API server forwards authenticated requests to the bot's API.

```
[Dashboard] --auth--> [HorizonAlerts API] --proxy--> [NovaPulse Bot]
                         |                               |
                    Firebase auth            X-API-Key header
                    SSRF protection          10s timeout
                    Query sanitization       No redirects
```

---

## Bot Connection Model

Each connection is stored in the `bot_connections` table:

```typescript
interface BotConnection {
  id: number;
  uid: string;           // User's Firebase UID
  bot_url: string;       // Full URL to NovaPulse API (e.g., https://server:8080)
  api_key: string;       // NovaPulse dashboard API key
  hosting_type: string;  // 'managed' or 'self-hosted'
  label: string;         // User-defined label (default: "My Bot")
  status: string;        // 'active' or 'disconnected'
  created_at: string;
  updated_at: string;
}
```

**Constraints**:
- UNIQUE(uid) -- One connection per user
- Upsert semantics on PUT (ON CONFLICT DO UPDATE)
- DELETE sets status to 'disconnected' rather than removing the row

---

## Connection Lifecycle

### 1. Create/Update Connection

**Endpoint**: `PUT /bot/connection`

**Validation steps**:

1. **Zod schema validation**: bot_url (valid URL), api_key (non-empty), hosting_type (enum), label (max 100 chars)

2. **SSRF protection** (`isAllowedBotUrl`):
   ```typescript
   async function isAllowedBotUrl(rawUrl: string): Promise<boolean> {
     const u = new URL(rawUrl);
     // Only http/https protocols
     if (u.protocol !== "http:" && u.protocol !== "https:") return false;
     // Quick string check for private IPs
     if (isPrivateIp(hostname)) return false;
     // DNS resolution check (anti-rebinding)
     const addresses = await dns.lookup(hostname, { all: true });
     for (const { address } of addresses) {
       if (isPrivateIp(address)) return false;
     }
     return true;
   }
   ```

3. **Connection test**: Fetches `/api/v1/status` from the bot using the provided URL and API key. Must return HTTP 200.

4. **Database upsert**: Inserts or updates the connection record.

### 2. Disconnect

**Endpoint**: `DELETE /bot/connection`

Sets `status = 'disconnected'` and `updated_at = now()`. The connection record is preserved for potential reconnection.

### 3. Get Connection

**Endpoint**: `GET /bot/connection`

Returns the active connection for the authenticated user (where `status = 'active'`). API key is NOT returned in the response.

---

## SSRF Protection

Server-Side Request Forgery (SSRF) protection prevents users from using the bot proxy to access internal network resources.

### Blocked IP Ranges

```typescript
function isPrivateIp(ip: string): boolean {
  // Loopback
  if (ip === "localhost" || ip === "127.0.0.1" || ip === "::1" || ip === "0.0.0.0" || ip === "::") return true;
  // Link-local
  if (ip.startsWith("169.254.")) return true;
  // Private ranges
  if (ip.startsWith("10.")) return true;
  if (/^172\.(1[6-9]|2\d|3[01])\./.test(ip)) return true;
  if (ip.startsWith("192.168.")) return true;
  // IPv6 private
  if (ip.startsWith("fc") || ip.startsWith("fd") || ip.startsWith("fe80")) return true;
  return false;
}
```

### Protocol Restrictions

Only `http:` and `https:` protocols are allowed. Blocked protocols include:
- `file://` -- Local filesystem access
- `ftp://` -- FTP protocol
- `data:` -- Data URIs
- `javascript:` -- Script execution

### DNS Rebinding Prevention

After the hostname string check, the system performs DNS resolution and checks ALL resolved IP addresses against the private IP blocklist. This prevents an attacker from:
1. Registering a domain that resolves to `127.0.0.1`
2. Using that domain as a bot URL
3. Having the proxy make requests to localhost

### Redirect Prevention

All `fetch()` calls to the bot use `redirect: "error"`, which prevents the bot from redirecting the proxy to an internal address.

---

## Proxy Architecture

### Proxy Endpoints

The following endpoints are proxied from HorizonAlerts to NovaPulse:

| HorizonAlerts Route | NovaPulse Route | Allowed Query Params |
|---|---|---|
| `GET /bot/status` | `/api/v1/status` | None |
| `GET /bot/performance` | `/api/v1/performance` | None |
| `GET /bot/positions` | `/api/v1/positions` | None |
| `GET /bot/trades` | `/api/v1/trades` | `limit`, `offset` |
| `GET /bot/strategies` | `/api/v1/strategies` | None |
| `GET /bot/risk` | `/api/v1/risk` | None |
| `GET /bot/thoughts` | `/api/v1/thoughts` | `limit` |
| `GET /bot/trades/csv` | `/api/v1/export/trades.csv` | `limit` |

### Proxy Request Flow

```typescript
async function proxyToBot(
  botUrl: string,
  apiKey: string,
  path: string,
  queryString?: string
): Promise<{ status: number; data: unknown }> {
  const url = queryString
    ? `${botUrl}${path}?${queryString}`
    : `${botUrl}${path}`;

  const res = await fetch(url, {
    headers: { "X-API-Key": apiKey, Accept: "application/json" },
    signal: AbortSignal.timeout(10_000),  // 10 second timeout
    redirect: "error",                     // SSRF protection
  });

  const data = await res.json().catch(() => null);
  return { status: res.status, data };
}
```

**Key security measures**:
- **Authentication**: X-API-Key header sent to bot
- **Timeout**: 10-second AbortSignal timeout prevents hanging connections
- **No redirects**: `redirect: "error"` prevents SSRF via redirect
- **Query sanitization**: Only allowlisted query parameters are forwarded
- **JSON parsing**: Gracefully handles non-JSON responses

### Query Parameter Sanitization

Only explicitly allowlisted query parameters are forwarded to the bot:

```typescript
if (ep.allowedQs && typeof request.query === "object") {
  const raw = request.query as Record<string, string>;
  const safe = Object.fromEntries(
    Object.entries(raw).filter(([k]) => ep.allowedQs!.includes(k))
  );
  qs = new URLSearchParams(safe).toString();
}
```

Any query parameters not in the allowlist are silently dropped.

### CSV Export Proxy

The CSV export endpoint has a dedicated handler because it returns `text/csv` instead of JSON:

```typescript
const res = await fetch(url, {
  headers: { "X-API-Key": conn.api_key, Accept: "text/csv" },
  signal: AbortSignal.timeout(10_000),
  redirect: "error",
});
const csv = await res.text();
return reply
  .header("Content-Type", "text/csv")
  .header("Content-Disposition", "attachment; filename=trades.csv")
  .send(csv);
```

---

## Bot Monitor Service

The `bot-monitor.ts` service runs inside the API process and periodically polls active bot connections for risk data.

### Monitoring Loop

- **Interval**: 60 seconds
- **Startup**: Initial check after 5 seconds delay
- **Concurrency**: Processes up to 10 bot connections concurrently per batch

### What It Monitors

For each active bot connection:

1. **Fetch risk data**: `GET /api/v1/risk` from the bot
2. **Daily loss**: Compares daily P&L against configured daily loss limit
3. **Max exposure**: Compares total exposure against configured max exposure
4. **Consecutive losses**: Compares consecutive loss count against limit
5. **Risk of ruin**: Compares risk of ruin metric against threshold
6. **Anomalies**: `GET /api/v1/anomalies` -- checks for active anomaly events
7. **Macro events**: `GET /api/v1/events` -- checks for upcoming macro events

### Alert Deduplication

The monitor maintains an in-memory `alertHistory` map with key format `${uid}:${alertType}`:
- Cooldown: 4 hours between same-tier alerts
- Escalation: Immediate on tier upgrade (warn25 -> warn10 -> triggered)
- Persistence: On startup, loads recent entries from `email_log` table

### Scheduled Reports

The monitor also handles scheduled report delivery at the top of each hour (minute <= 1):
- **Daily summary**: 00:00 UTC daily
- **Weekly digest**: 00:00 UTC on Sundays
- **Monthly report**: 00:00 UTC on the 1st of each month

Report history is tracked in-memory per user to prevent duplicate sends within the same period.

---

## Error Handling

### Proxy Errors

| Scenario | Response |
|---|---|
| No bot connection | 404 `{ "error": "no_bot_connected" }` |
| Bot unreachable (network error) | 502 `{ "error": "bot_unreachable" }` |
| Bot returns non-200 | Forward the bot's status code and response |
| Bot request timeout (10s) | 502 `{ "error": "bot_unreachable" }` |

### Connection Errors

| Scenario | Response |
|---|---|
| Invalid bot URL format | 400 `{ "error": "invalid_request" }` |
| Private/internal URL (SSRF) | 422 `{ "error": "invalid_bot_url" }` |
| Bot returns non-200 on test | 422 `{ "error": "bot_connection_failed" }` |
| Bot unreachable on test | 422 `{ "error": "bot_unreachable" }` |
| DNS resolution fails | 422 `{ "error": "invalid_bot_url" }` |

---

## NovaPulse API Compatibility

The proxy assumes the NovaPulse bot exposes the following API endpoints:

| Endpoint | Method | Description |
|---|---|---|
| `/api/v1/status` | GET | Bot status, uptime, version |
| `/api/v1/performance` | GET | P&L, win rate, trade counts |
| `/api/v1/positions` | GET | Open positions |
| `/api/v1/trades` | GET | Trade history (supports limit/offset) |
| `/api/v1/strategies` | GET | Strategy performance breakdown |
| `/api/v1/risk` | GET | Risk metrics (bankroll, drawdown, exposure) |
| `/api/v1/thoughts` | GET | AI thought log (supports limit) |
| `/api/v1/export/trades.csv` | GET | CSV trade export |
| `/api/v1/anomalies` | GET | Active anomaly events (bot monitor) |
| `/api/v1/events` | GET | Upcoming macro events (bot monitor) |

All NovaPulse endpoints are authenticated via X-API-Key header. The NovaPulse dashboard runs on port 8080 by default (mapped to 8090 on the host in Docker).

---

*Last updated: March 2026*

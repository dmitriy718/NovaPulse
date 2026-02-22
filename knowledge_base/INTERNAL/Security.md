# NovaPulse Security

**Version:** 4.0.0
**Last Updated:** 2026-02-22

---

## Authentication Model

NovaPulse uses a layered authentication model with multiple credential types:

### API Key Authentication (Primary)

| Key Type | Env Variable | Access Level | Description |
|----------|-------------|-------------|-------------|
| Admin Key | `DASHBOARD_ADMIN_KEY` | Full | Control endpoints + all read endpoints |
| Read Key | `DASHBOARD_READ_KEY` | Read-only | Data endpoints only |
| Tenant API Key | DB-managed | Tenant-scoped | Read + optional control per tenant |

**Request format:** Pass the key in the `X-API-Key` header:
```
X-API-Key: your_api_key_here
```

**Legacy aliases:** `DASHBOARD_SECRET_KEY` maps to `DASHBOARD_ADMIN_KEY`, `DASHBOARD_READONLY_KEY` maps to `DASHBOARD_READ_KEY` for backward compatibility.

### Session-Based Web Authentication

For the web dashboard UI:

| Component | Env Variable | Description |
|-----------|-------------|-------------|
| Username | `DASHBOARD_ADMIN_USERNAME` | Login username (default: "admin") |
| Password | `DASHBOARD_ADMIN_PASSWORD` | Plaintext password (paper mode only) |
| Password Hash | `DASHBOARD_ADMIN_PASSWORD_HASH` | Bcrypt hash (required in live mode) |
| Session Secret | `DASHBOARD_SESSION_SECRET` | Signs session cookies |
| Session TTL | `DASHBOARD_SESSION_TTL_SECONDS` | Cookie lifetime (default: 43200 = 12h) |
| Session Cookie | `np_session` | Cookie name |
| CSRF Cookie | `np_csrf` | CSRF protection cookie |

**Generate a bcrypt hash:**
```bash
python -c "import bcrypt; print(bcrypt.hashpw(b'your_password', bcrypt.gensalt()).decode())"
```

### Live Mode Requirements

In live mode (`TRADING_MODE=live`), the dashboard server enforces:

1. `DASHBOARD_ADMIN_KEY` **must** be explicitly set (no auto-generated ephemeral keys)
2. `DASHBOARD_SESSION_SECRET` **must** be explicitly set
3. `DASHBOARD_ADMIN_PASSWORD_HASH` **must** be set (plaintext password alone is rejected)

If any of these are missing, the bot will fail to start with a `RuntimeError`.

In paper mode, ephemeral keys are auto-generated and logged as warnings.

---

## Endpoint Authentication Matrix

| Endpoint | Admin Key | Read Key | Tenant Key | Session | No Auth |
|----------|-----------|----------|------------|---------|---------|
| GET /api/v1/health | - | - | - | - | Yes |
| GET /api/v1/status | Yes | Yes | Yes | Yes | No |
| GET /api/v1/trades | Yes | Yes | Yes | Yes | No |
| GET /api/v1/positions | Yes | Yes | Yes | Yes | No |
| GET /api/v1/performance | Yes | Yes | Yes | Yes | No |
| GET /api/v1/strategies | Yes | Yes | Yes | Yes | No |
| GET /api/v1/risk | Yes | Yes | Yes | Yes | No |
| GET /api/v1/thoughts | Yes | Yes | Yes | Yes | No |
| GET /api/v1/scanner | Yes | Yes | Yes | Yes | No |
| POST /api/v1/control/* | Yes | No | Conditional* | No | No |
| POST /api/v1/signal | - | - | - | - | Webhook secret |
| POST /api/v1/billing/* | - | - | - | - | Stripe signature |
| POST /api/v1/login | - | - | - | - | Credentials |
| WS /ws/live | Yes | Yes | Yes | - | Query param |

*Tenant keys can access control endpoints only if `dashboard.allow_tenant_keys_for_control: true`.

---

## Rate Limiting

### API Rate Limiting

When `dashboard.rate_limit_enabled: true` (default):

| Parameter | Default | Env Override |
|-----------|---------|-------------|
| Requests per minute | 240 | `DASHBOARD_RATE_LIMIT_RPM` |
| Burst allowance | 60 | `DASHBOARD_RATE_LIMIT_BURST` |

Rate limiting is applied per IP address. Exceeding the limit returns HTTP 429.

### Exchange Rate Limiting

Kraken REST client uses a semaphore-based rate limiter:
- Default: 15 requests per second (`exchange.rate_limit_per_second`)
- On 429 response: automatic backoff using `RateLimitError.retry_after`
- Exponential backoff on retries: `retry_base_delay * 2^attempt`

---

## Brute-Force Protection

### Login Endpoint

The `/api/v1/login` endpoint implements brute-force protection:

- Rate limited by the global API rate limiter
- Failed login attempts are logged with IP address
- Password comparison uses constant-time comparison (bcrypt)
- Session cookies are signed with `DASHBOARD_SESSION_SECRET`
- CSRF tokens are validated on state-changing requests

### WebSocket Authentication

WebSocket connections at `/ws/live` authenticate via query parameter:
```
ws://host:port/ws/live?key=your_api_key
```

The key is validated against the admin key, read key, and tenant API keys.

---

## Multi-Tenant Isolation

### Database Isolation

All data tables include a `tenant_id` column. Queries are scoped by tenant:

```sql
-- Every query includes tenant_id filter
SELECT * FROM trades WHERE tenant_id = ? AND status = 'open';
```

Tables with tenant_id:
- `trades`
- `thought_log`
- `metrics`
- `ml_features`
- `order_book_snapshots`
- `daily_summary`
- `tenant_api_keys`
- `stripe_webhook_events`
- `signal_webhook_events`
- `backtest_runs`

### Tenant API Key Resolution

The `resolve_tenant_id()` method in `DashboardServer` enforces:

1. **Admin/read keys** can target any tenant explicitly via `X-Tenant-ID` header
2. **Tenant API keys** are pinned to a specific tenant via hashed lookup in `tenant_api_keys` table
3. If a tenant key tries to access a different tenant, HTTP 403 is returned
4. Inactive tenants (not "active" or "trialing") are denied access with HTTP 403
5. If no valid key mapping exists, the default tenant is used (fail-safe)

### Tenant API Key Storage

Tenant keys are stored as SHA-256 hashes in the `tenant_api_keys` table:

```sql
CREATE TABLE IF NOT EXISTS tenant_api_keys (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id TEXT NOT NULL,
    key_hash TEXT NOT NULL UNIQUE,
    label TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);
```

Keys are never stored in plaintext. Lookup is done by hashing the provided key and comparing against stored hashes.

---

## Sensitive Data Handling

### Log Scrubbing

The structured logging system (`src/core/logger.py`) automatically masks sensitive data:

**Key-based masking:** Any log field containing these substrings is masked:
- `api_key`, `api_secret`, `password`, `token`, `secret`
- Masking format: `first4****last4`

**Pattern-based scrubbing:**
- Telegram bot tokens in URLs and exception strings are redacted
- Pattern: `bot<digits>:<token>` is replaced with `bot<digits>:<redacted>`

### Environment Variable Security

- API keys and secrets are loaded from `.env` or environment variables, never from config.yaml
- The `.env` file should have restrictive permissions: `chmod 600 .env`
- Docker secrets mounting: `.secrets/` is mounted read-only
- `op://` prefixed values (1Password references) are recognized and skipped

### Config File Security

- `config/config.yaml` is mounted read-only in Docker (`:ro`)
- No secrets should be stored in config.yaml
- The auto-tuner writes to config.yaml (strategy weights only) using atomic file replace

---

## Signal Webhook Security

For inbound trading signals from external providers:

| Protection | Details |
|------------|---------|
| Authentication | `SIGNAL_WEBHOOK_SECRET` header validation |
| Source filtering | `webhooks.allowed_sources` whitelist |
| Timestamp validation | Max skew: `max_timestamp_skew_seconds` (default 300s) |
| Idempotency | `signal_webhook_events` table prevents replay |

---

## Stripe Webhook Security

For billing webhooks:

| Protection | Details |
|------------|---------|
| Signature verification | `STRIPE_WEBHOOK_SECRET` (whsec_...) |
| Idempotency | `stripe_webhook_events` table prevents replay |
| Event validation | Stripe SDK signature verification |

---

## Network Security

### Container Network

- The `trading-net` bridge network isolates bot containers
- Dashboard binds to `127.0.0.1` by default (not exposed to public)
- ES binds to `127.0.0.1:9200` (not exposed to public)

### Recommended Production Setup

```
Internet
    |
    +-- Reverse Proxy (nginx/Caddy)
    |     - HTTPS termination (Let's Encrypt)
    |     - IP allowlisting (optional)
    |     - Additional rate limiting
    |
    +-- Host port 8090 (localhost only)
    |
    +-- Container port 8080
    |
    +-- NovaPulse Dashboard
```

### Exchange API Security

- Kraken: HMAC-SHA512 signed requests with nonce-based replay prevention
- Coinbase: JWT (ES256) signed requests with per-request token generation
- Both: HTTPS-only communication
- Connection pooling via httpx with keepalive limits

---

## Security Checklist

### Before Going Live

- [ ] `DASHBOARD_ADMIN_KEY` is a strong random value (not a dictionary word)
- [ ] `DASHBOARD_SESSION_SECRET` is a strong random value
- [ ] `DASHBOARD_ADMIN_PASSWORD_HASH` is a bcrypt hash (not plaintext)
- [ ] Exchange API keys have minimum required permissions
- [ ] `.env` file has restrictive permissions (600)
- [ ] Host port binds to `127.0.0.1` (not `0.0.0.0`)
- [ ] Reverse proxy with HTTPS is in place (if exposed to internet)
- [ ] No secrets in config.yaml or git history
- [ ] Docker image does not contain .env or secrets
- [ ] `require_api_key_for_reads: true` in config

### Regular Audit

- [ ] Review API access logs for unauthorized attempts
- [ ] Rotate exchange API keys quarterly
- [ ] Rotate dashboard admin key when team members change
- [ ] Verify tenant API keys are still needed
- [ ] Check for exposed ports: `ss -tlnp | grep -E "8080|8090|9200"`

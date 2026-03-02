# Security

This document covers the security architecture of HorizonAlerts, including all defensive measures implemented across the platform.

---

## Security Layers Overview

```
[Internet]
  |
  v
[Nginx] -- HTTPS enforcement, HSTS, CSP, X-Frame-Options, X-Content-Type-Options
  |
  v
[Fastify API] -- CORS, Rate limiting, Auth, Input validation, SSRF protection
  |
  v
[PostgreSQL] -- Parameterized queries, connection pooling
  |
  v
[External Services] -- HMAC tokens, signature verification, TLS
```

---

## Transport Security

### HTTPS Enforcement

All HTTP traffic is redirected to HTTPS:
```nginx
server {
  listen 80;
  return 301 https://$host$request_uri;
}
```

### HSTS

Strict Transport Security with a 2-year max-age:
```
Strict-Transport-Security: max-age=63072000; includeSubDomains; preload
```

This tells browsers to always use HTTPS for this domain, even if the user types `http://`.

### TLS

SSL certificates from Let's Encrypt. HTTP/2 is enabled for improved performance.

---

## Content Security Policy (CSP)

The CSP is set via Nginx and controls what resources the browser can load:

```
default-src 'self';

script-src 'self' 'unsafe-inline' 'unsafe-eval'
  https://s3.tradingview.com
  https://*.firebaseio.com
  https://*.googleapis.com
  https://apis.google.com
  https://app.posthog.com
  https://us.i.posthog.com;

style-src 'self' 'unsafe-inline';

img-src 'self' https: data:;

connect-src 'self'
  https://*.firebaseio.com
  https://*.googleapis.com
  https://identitytoolkit.googleapis.com
  https://securetoken.googleapis.com
  https://app.posthog.com
  https://us.i.posthog.com;

font-src 'self' https:;

frame-ancestors 'none';
```

### CSP Rationale

| Directive | Why |
|---|---|
| `'unsafe-inline'` (scripts) | Required by Next.js for inline scripts |
| `'unsafe-eval'` (scripts) | Required by TradingView widget |
| Firebase domains | Client-side Firebase Auth SDK |
| PostHog domains | Product analytics |
| `frame-ancestors 'none'` | Prevents clickjacking (same as X-Frame-Options: DENY) |

---

## Additional Security Headers

```nginx
add_header X-Content-Type-Options "nosniff" always;
add_header X-Frame-Options "DENY" always;
add_header Referrer-Policy "no-referrer-when-downgrade" always;
```

| Header | Purpose |
|---|---|
| X-Content-Type-Options: nosniff | Prevents MIME type sniffing |
| X-Frame-Options: DENY | Prevents embedding in iframes (redundant with CSP frame-ancestors) |
| Referrer-Policy | Controls referrer info sent with requests |

---

## CORS

Configured in `services/api/src/server.ts`:

```typescript
await server.register(cors, {
  origin: (origin, callback) => {
    if (!origin || allowedOrigins.includes(origin)) {
      callback(null, true);
    } else {
      callback(new Error("Not allowed by CORS"), false);
    }
  },
  credentials: true,
});
```

**Allowed origins**: Controlled by `CORS_ORIGINS` env var (default: `https://horizonsvc.com,http://localhost:3000`).

Requests without an `Origin` header (server-to-server, curl) are allowed.

---

## Rate Limiting

### Global Rate Limit

```typescript
await server.register(rateLimit, {
  max: 120,
  timeWindow: "1 minute",
  allowList: ["127.0.0.1"]
});
```

### Per-Endpoint Rate Limits

| Endpoint | Limit | Window |
|---|---|---|
| POST /auth/login-attempt | 5 | 15 minutes |
| GET /auth/lock-status | 10 | 1 minute |
| POST /newsletter/subscribe | 3 | 1 minute |
| POST /help/public/contact | 5 | 1 hour (custom in-memory) |

### Contact Form Rate Limiter

The public contact form uses a custom in-memory rate limiter (not @fastify/rate-limit) to handle IP-based limiting:

```typescript
const contactRateMap = new Map<string, number[]>();
const RATE_WINDOW = 60 * 60 * 1000; // 1 hour
const RATE_MAX = 5;
```

Stale entries are cleaned every 10 minutes via `setInterval().unref()` to prevent memory leaks without blocking process exit.

---

## Authentication Security

### Firebase Token Verification

- Firebase ID tokens are verified server-side using Firebase Admin SDK
- When Firebase IS configured, there is NO JWT fallback -- this prevents token confusion
- Token contains `uid`, `email`, and `email_verified` claims
- Every authenticated request re-verifies the token (no session cookies)

### JWT Signing Key

- Minimum 12 characters enforced in production
- Default dev value (`"dev-secret-change-local-only"`) causes a startup error in production
- Used for both JWT fallback (dev) and HMAC unsubscribe token signing

### Account Lockout

- 3 failed login attempts in 30 minutes triggers a 30-minute lock
- Warning email at 2 failed attempts
- Lock notification email at 3+ attempts
- Lock status endpoint does not reveal whether an email exists in the system

### Email Verification

- Required for dashboard access, checkout, and scanner
- Dashboard layout enforces with a blocking modal
- API endpoints check `email_verified` flag on the decoded token

---

## SSRF Protection

The bot proxy implements multiple SSRF defenses:

### Protocol Restriction

Only `http:` and `https:` protocols are allowed. Blocks: `file://`, `ftp://`, `data:`, `javascript:`.

### Private IP Blocking

```typescript
function isPrivateIp(ip: string): boolean {
  if (ip === "localhost" || ip === "127.0.0.1" || ip === "::1") return true;
  if (ip.startsWith("169.254.")) return true;  // Link-local
  if (ip.startsWith("10.")) return true;         // Class A private
  if (/^172\.(1[6-9]|2\d|3[01])\./.test(ip)) return true;  // Class B private
  if (ip.startsWith("192.168.")) return true;    // Class C private
  if (ip.startsWith("fc") || ip.startsWith("fd") || ip.startsWith("fe80")) return true;  // IPv6
  return false;
}
```

### DNS Rebinding Prevention

After hostname string check, all DNS-resolved IPs are checked:
```typescript
const addresses = await dns.lookup(hostname, { all: true });
for (const { address } of addresses) {
  if (isPrivateIp(address)) return false;
}
```

### Redirect Prevention

```typescript
const res = await fetch(url, {
  redirect: "error",  // Never follow redirects
});
```

### Query Parameter Sanitization

Only allowlisted query parameters are forwarded to the bot.

---

## Input Validation

All user inputs are validated using Zod schemas:

| Endpoint | Validated Fields |
|---|---|
| POST /auth/register | firstName, lastName, age (>=18), zipCode (>=5), email |
| PUT /bot/connection | bot_url (valid URL), api_key (non-empty), hosting_type (enum), label (max 100) |
| POST /me/tickets | department (enum), subject (1-200), message (1-5000), priority (enum) |
| POST /me/tickets/:id/reply | message (1-5000) |
| PUT /me/preferences | Strict schema matching notification structure |
| PUT /me/profile | firstName (1-50), lastName (1-50) |
| POST /newsletter/subscribe | email (valid), lists (enum array, min 1), source (max 100) |
| POST /help/public/contact | name (1-100), email (max 254), subject (1-200), message (1-5000) |

### Zod Error Handling

Invalid inputs return structured error details:
```json
{
  "error": "invalid_request",
  "details": {
    "fieldErrors": {
      "email": ["Invalid email"]
    }
  }
}
```

---

## SQL Injection Prevention

All database queries use parameterized queries via the `pg` library:

```typescript
await query(
  "SELECT * FROM users WHERE uid = $1",
  [uid]
);
```

No raw string interpolation is used in SQL queries.

---

## XSS Prevention

### Server-Side

HTML output in the unsubscribe page uses `escapeHtmlSimple()`:
```typescript
function escapeHtmlSimple(s: string): string {
  return s.replace(/&/g, "&amp;")
          .replace(/</g, "&lt;")
          .replace(/>/g, "&gt;")
          .replace(/"/g, "&quot;");
}
```

Email templates use the same `escapeHtml()` function for any user-provided content.

### Client-Side

React's JSX automatically escapes values inserted into templates. The `dangerouslySetInnerHTML` is only used for JSON-LD structured data (server-controlled content).

---

## HMAC Tokens (Unsubscribe)

Unsubscribe links use HMAC-SHA256 signed tokens:

```
Token format: base64url(JSON payload) . base64url(HMAC signature)
Payload: { uid, category, exp }
Secret: JWT_SIGNING_KEY
Expiry: 90 days
Comparison: crypto.timingSafeEqual (with length pre-check)
```

### Timing-Safe Comparison

```typescript
const sigBuf = Buffer.from(sig, "base64url");
const expectedBuf = Buffer.from(expected, "base64url");
if (sigBuf.length !== expectedBuf.length) return null;  // Length pre-check
if (!crypto.timingSafeEqual(sigBuf, expectedBuf)) return null;
```

The length pre-check prevents `timingSafeEqual` from throwing on mismatched buffer lengths while also not leaking timing information (length comparison is constant-time for equal-length strings, and early-exit for different lengths does not reveal the expected length since the expected length is always the same -- 32 bytes of HMAC-SHA256).

---

## Stripe Webhook Security

```typescript
event = stripe.webhooks.constructEvent(
  rawBody.toString("utf8"),  // Raw body preserved by custom parser
  signature,                  // stripe-signature header
  webhookSecret               // STRIPE_WEBHOOK_SECRET
);
```

The raw body is captured as a Buffer by a custom content type parser registered before route handlers. This ensures the body is not modified by JSON parsing before signature verification.

---

## Security Email Notifications

Security notifications cannot be disabled:
- `account_security.password_changed`
- `account_security.failed_login`
- `account_security.account_locked`
- `account_security.personal_info_changed`

Enforcement:
1. `sendEmail()` checks `SECURITY_KEYS` set and bypasses preference check
2. `PUT /me/preferences` rejects requests that try to disable security keys (400 error)
3. `GET /unsubscribe` rejects `account_security` category with error page
4. `isPreferenceEnabled()` always returns true for security keys, even with global unsubscribe

---

## Trust Proxy

```typescript
const server = Fastify({ logger: true, trustProxy: true });
```

`trustProxy: true` tells Fastify to use `X-Forwarded-For` and `X-Forwarded-Proto` headers from Nginx. This is required for:
- Correct client IP in rate limiting
- HTTPS detection for cookie/redirect logic
- IP logging in login attempts

---

## Recommendations for Future Hardening

1. **CSP nonces**: Replace `'unsafe-inline'` with nonce-based CSP for scripts
2. **Subresource Integrity**: Add SRI hashes for third-party scripts
3. **Rate limiting persistence**: Store rate limit state in Redis (currently in-memory)
4. **API key encryption at rest**: Encrypt bot API keys in the database
5. **Audit logging**: Comprehensive audit log for all admin/security actions
6. **WAF**: Consider adding a Web Application Firewall
7. **Dependency scanning**: Automated `npm audit` in CI/CD

---

*Last updated: March 2026*

# API Reference

Complete reference for the HorizonAlerts Fastify API server. The API runs on port 4000 and is proxied via Nginx at `/api/`.

---

## Authentication

All authenticated endpoints require a Firebase ID token in the Authorization header:

```
Authorization: Bearer <firebase_id_token>
```

The `requireAuth` decorator verifies the token and populates `request.user` with:
```typescript
{
  uid: string;
  email: string;
  email_verified: boolean;
}
```

If Firebase is not configured (dev mode), JWT tokens signed with `JWT_SIGNING_KEY` are accepted instead.

---

## Rate Limits

- **Global**: 120 requests per minute per IP
- **Login attempts**: 5 per 15 minutes (POST /auth/login-attempt)
- **Lock status**: 10 per minute (GET /auth/lock-status)
- **Newsletter subscribe**: 3 per minute (POST /newsletter/subscribe)
- **Contact form**: 5 per hour per IP (POST /help/public/contact)

Localhost (127.0.0.1) is excluded from global rate limits.

---

## Health

### GET /health
Returns API health status.

**Auth**: None

**Response** (200):
```json
{ "ok": true, "service": "api", "uptime": 12345.678 }
```

### GET /health/ready
Checks database connectivity.

**Auth**: None

**Response** (200):
```json
{ "ok": true, "db": "up" }
```

**Response** (503):
```json
{ "ok": false, "db": "down" }
```

---

## Authentication Routes

### POST /auth/register
Register a new user. Requires Firebase auth. Saves profile to DB, generates verification email.

**Auth**: Required

**Body**:
```json
{
  "firstName": "string (required)",
  "lastName": "string (required)",
  "age": "number (min 18)",
  "zipCode": "string (min 5 chars)",
  "streetAddress": "string (optional)",
  "city": "string (optional)",
  "state": "string (optional)",
  "email": "string (email format)",
  "preferences": "object (optional)"
}
```

**Security**: Token email must match body email (case-insensitive). Returns 403 on mismatch.

**Response** (200):
```json
{ "success": true }
```

### POST /auth/login-attempt
Track login attempts for lockout logic.

**Auth**: None (rate limited to 5/15min)

**Body**:
```json
{
  "email": "string (email format)",
  "success": "boolean"
}
```

**Response** (200):
```json
{ "status": "ok" }
```
or (on lockout):
```json
{ "status": "locked", "locked_until": "ISO8601" }
```

**Side effects**:
- On 2 failures in 30min: sends warning email
- On 3+ failures: locks account for 30 minutes, sends lock notification

### GET /auth/lock-status
Check if an account is locked.

**Auth**: None (rate limited to 10/min)

**Query**: `?email=user@example.com`

**Response** (200):
```json
{ "locked": false }
```
or:
```json
{
  "locked": true,
  "locked_until": "ISO8601",
  "minutes_remaining": 15
}
```

### POST /auth/welcome
Send welcome email after email verification.

**Auth**: Required

**Response** (200):
```json
{ "success": true }
```

---

## User Profile Routes

### GET /me/profile
Get user profile data.

**Auth**: Required

**Response** (200):
```json
{
  "uid": "string",
  "email": "string",
  "firstName": "string",
  "lastName": "string",
  "age": 25,
  "zipCode": "12345",
  "isPremium": false,
  "createdAt": "ISO8601"
}
```

### PUT /me/profile
Update user display name.

**Auth**: Required

**Body**:
```json
{
  "firstName": "string (optional, 1-50 chars)",
  "lastName": "string (optional, 1-50 chars)"
}
```

**Response** (200):
```json
{
  "firstName": "string",
  "lastName": "string",
  "email": "string"
}
```

**Side effects**: Sends personalInfoChanged security email with changed fields, IP address, and timestamp.

---

## Entitlement Routes

### GET /me/entitlement
Get the user's current subscription entitlement.

**Auth**: Required

**Response** (200):
```json
{
  "plan": "free" | "pro",
  "verifiedEmail": true,
  "currentPeriodEnd": "ISO8601" | null,
  "caps": {
    "alertsPerDay": 5 | 9999,
    "customization": false | true
  }
}
```

---

## Notification Preference Routes

### GET /me/preferences
Get merged notification preferences (stored values + defaults).

**Auth**: Required

**Response** (200):
```json
{
  "notifications": {
    "account_security": {
      "password_changed": { "email": true },
      "failed_login": { "email": true },
      "account_locked": { "email": true },
      "personal_info_changed": { "email": true }
    },
    "trading_alerts": {
      "daily_loss_limit": { "email": true },
      "max_exposure": { "email": true },
      "risk_of_ruin": { "email": true },
      "consecutive_losses": { "email": true },
      "anomaly_circuit_breaker": { "email": true },
      "macro_event_blackout": { "email": true },
      "trade_executed": { "email": false },
      "trade_closed": { "email": false }
    },
    "performance_reports": {
      "daily_summary": { "email": true },
      "weekly_digest": { "email": true },
      "monthly_report": { "email": true },
      "milestone_achievements": { "email": true }
    },
    "marketing": {
      "newsletter": { "email": true },
      "feature_announcements": { "email": true },
      "inactivity_reminders": { "email": true }
    }
  },
  "global_unsubscribe": false,
  "timezone": "America/New_York"
}
```

### PUT /me/preferences
Update notification preferences. Deep merges with existing values.

**Auth**: Required

**Body**: Partial version of the preferences object (only include fields to change).

**Restrictions**: Cannot set any `account_security.*` to `{ "email": false }`. Returns 400 with `error: "security_prefs_locked"`.

**Response** (200): Full merged preferences object.

---

## Support Ticket Routes

### GET /me/tickets
List user's support tickets.

**Auth**: Required

**Response** (200):
```json
[
  {
    "id": 1,
    "department": "tech_support",
    "subject": "Bot connection issue",
    "status": "open",
    "priority": "normal",
    "replyCount": 2,
    "createdAt": "ISO8601",
    "updatedAt": "ISO8601"
  }
]
```

### GET /me/tickets/:id
Get ticket with all replies.

**Auth**: Required

**Response** (200):
```json
{
  "id": 1,
  "department": "tech_support",
  "subject": "Bot connection issue",
  "message": "Full ticket body...",
  "status": "open",
  "priority": "normal",
  "createdAt": "ISO8601",
  "updatedAt": "ISO8601",
  "replies": [
    {
      "id": 1,
      "authorType": "user",
      "authorName": "John",
      "message": "Reply text...",
      "createdAt": "ISO8601"
    }
  ]
}
```

### POST /me/tickets
Create a new support ticket.

**Auth**: Required

**Body**:
```json
{
  "department": "billing" | "tech_support" | "customer_service" | "referrals" | "partnership",
  "subject": "string (1-200 chars)",
  "message": "string (1-5000 chars)",
  "priority": "low" | "normal" | "high" | "urgent" (default: "normal")
}
```

**Response** (200):
```json
{ "success": true, "ticketId": 1 }
```

### POST /me/tickets/:id/reply
Reply to a support ticket.

**Auth**: Required

**Body**:
```json
{ "message": "string (1-5000 chars)" }
```

**Restrictions**: Cannot reply to closed tickets (returns 400).

**Response** (200):
```json
{ "success": true }
```

---

## Bot Proxy Routes

All bot proxy routes require authentication and an active bot connection.

### GET /bot/status
Proxies to bot's `/api/v1/status`.

### GET /bot/performance
Proxies to bot's `/api/v1/performance`.

### GET /bot/positions
Proxies to bot's `/api/v1/positions`.

### GET /bot/trades
Proxies to bot's `/api/v1/trades`. Allowed query params: `limit`, `offset`.

### GET /bot/strategies
Proxies to bot's `/api/v1/strategies`.

### GET /bot/risk
Proxies to bot's `/api/v1/risk`.

### GET /bot/thoughts
Proxies to bot's `/api/v1/thoughts`. Allowed query params: `limit`.

### GET /bot/trades/csv
Proxies to bot's `/api/v1/export/trades.csv`. Returns CSV with `Content-Disposition: attachment`.

**Error responses**:
- 404: `{ "error": "no_bot_connected" }` -- No active bot connection
- 502: `{ "error": "bot_unreachable" }` -- Could not reach the bot

---

## Bot Connection Routes

### GET /bot/connection
Get current bot connection info.

**Auth**: Required

**Response** (200):
```json
{
  "id": 1,
  "bot_url": "https://server.com:8080",
  "hosting_type": "managed",
  "label": "My Bot",
  "status": "active",
  "created_at": "ISO8601",
  "updated_at": "ISO8601"
}
```

### PUT /bot/connection
Create or update bot connection.

**Auth**: Required

**Body**:
```json
{
  "bot_url": "https://server.com:8080",
  "api_key": "your-api-key",
  "hosting_type": "managed" | "self-hosted",
  "label": "My Bot (max 100 chars)"
}
```

**Validation**:
1. SSRF check on bot_url (blocks private IPs, DNS rebinding)
2. Connection test: fetches `/api/v1/status` from the bot
3. Must return 200 to succeed

**Response** (200):
```json
{
  "ok": true,
  "connection": {
    "id": 1,
    "bot_url": "https://server.com:8080",
    "hosting_type": "managed",
    "label": "My Bot",
    "status": "active"
  }
}
```

### DELETE /bot/connection
Disconnect bot (sets status to 'disconnected').

**Auth**: Required

**Response** (200):
```json
{ "ok": true }
```

---

## Billing Routes

### POST /billing/checkout-session
Create a Stripe Checkout session for Pro subscription.

**Auth**: Required (email must be verified)

**Response** (200):
```json
{ "url": "https://checkout.stripe.com/..." }
```

**Errors**:
- 403: `{ "error": "email_not_verified" }` -- Email not verified
- 409: `{ "error": "already_subscribed" }` -- Already has active subscription

### POST /billing/portal-session
Create a Stripe Customer Portal session.

**Auth**: Required (email must be verified)

**Response** (200):
```json
{ "url": "https://billing.stripe.com/..." }
```

---

## Stripe Webhook

### POST /auth/callback/stripe
Stripe webhook endpoint.

**Auth**: Stripe signature verification (not Firebase)

**Events handled**:
- `customer.subscription.created` -- Upsert entitlement
- `customer.subscription.updated` -- Upsert entitlement
- `customer.subscription.deleted` -- Mark as canceled

**Response** (200):
```json
{ "received": true }
```

---

## Public Feed Routes

### GET /public-feed
Get latest public signals (delayed, educational).

**Auth**: None

**Response** (200):
```json
{
  "data": [...],
  "disclaimer": "Educational only..."
}
```

### GET /public-feed/candidates
Get candidate lists by class scope.

**Auth**: None

**Response** (200):
```json
{
  "day": [...],
  "swing": [...],
  "invest": [...]
}
```

---

## Scanner Routes

### GET /scanner
Get live scanner signals (Pro only).

**Auth**: Required (verified email + active Pro subscription)

**Response** (200):
```json
{ "data": [...] }
```

### POST /scanner/run
Queue a manual scan.

**Auth**: Required (verified email)

**Body**:
```json
{
  "classScope": "day" | "swing" | "invest",
  "markets": ["us", "ca", "crypto"]
}
```

---

## Newsletter Routes

### POST /newsletter/subscribe
Subscribe to newsletter lists.

**Auth**: None (rate limited to 3/min)

**Body**:
```json
{
  "email": "string (email format)",
  "lists": ["stock_alerts", "weekly_newsletter", "product_updates"],
  "source": "string (optional, max 100 chars)"
}
```

---

## Unsubscribe Routes

### GET /unsubscribe
Process unsubscribe via HMAC-signed token.

**Auth**: None (token-based)

**Query**: `?token=<hmac_signed_token>`

**Response**: HTML page confirming unsubscription or showing error.

---

## Help Routes

### POST /help/public/contact
Public contact form submission.

**Auth**: None (rate limited to 5/hour per IP)

**Body**:
```json
{
  "name": "string (1-100 chars)",
  "email": "string (email, max 254 chars)",
  "subject": "string (1-200 chars)",
  "message": "string (1-5000 chars)"
}
```

### POST /help/ticket
Authenticated ticket submission.

**Auth**: Required

**Body**:
```json
{
  "topic": "string (1-100 chars)",
  "subject": "string (1-200 chars)",
  "message": "string (1-5000 chars)"
}
```

---

*Last updated: March 2026*

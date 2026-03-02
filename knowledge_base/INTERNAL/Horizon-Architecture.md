# Architecture

This document describes the system architecture of HorizonAlerts, the customer-facing platform for Nova|Pulse by Horizon Services.

---

## System Overview

HorizonAlerts is a multi-service application with the following high-level architecture:

```
[Browser] --> [Nginx (SSL)] --> [Next.js Web App :3000]
                            --> [Fastify API :4000] --> [PostgreSQL :5432]
                                                   --> [Redis :6379]
                                                   --> [NovaPulse Bot :8080] (per user)

[Signal Engine] --> [PostgreSQL]
[Automation]    --> [PostgreSQL]
```

### Request Flow

1. User visits horizonsvc.com
2. Nginx terminates SSL and routes:
   - `/api/*` requests to the Fastify API on port 4000 (stripping `/api/` prefix)
   - All other requests to the Next.js web app on port 3000
3. The Fastify API handles authentication, business logic, and proxies bot requests
4. Bot proxy requests are forwarded to the user's NovaPulse bot instance

---

## Services

### 1. Web App (`apps/web/`)

**Technology**: Next.js 15 with App Router, React 19, Tailwind CSS

**Purpose**: Marketing website + customer dashboard

**Pages**:
| Route | Type | Description |
|---|---|---|
| `/` | Public | Landing page with hero, features, testimonials |
| `/pricing` | Public | Plan comparison with hosting toggle, FAQ |
| `/academy` | Public | Educational articles (MDX content) |
| `/academy/[slug]` | Public | Individual academy article |
| `/blog` | Public | Blog listing |
| `/blog/[slug]` | Public | Individual blog post |
| `/about` | Public | About page |
| `/contact` | Public | Contact form |
| `/trust-safety` | Public | Trust and safety information |
| `/privacy` | Public | Privacy policy |
| `/terms` | Public | Terms of service |
| `/cookies` | Public | Cookie policy |
| `/dmarc` | Public | Email security (DMARC) information |
| `/auth` | Public | Login/signup page |
| `/login` | Public | Login redirect |
| `/signup` | Public | Signup redirect |
| `/onboarding` | Auth | Onboarding wizard |
| `/dashboard` | Auth | Main customer dashboard |
| `/settings` | Auth | Account settings, bot connection, notifications, support |
| `/support` | Public/Auth | Support contact form |

**Key Components**:
- `Navbar` -- Navigation bar with auth-aware links
- `AuthProvider` -- React context wrapping Firebase auth state
- `CookieBanner` -- GDPR cookie consent banner
- `NewsletterPopup` -- Email newsletter subscription popup
- `FooterNewsletter` -- Newsletter form in footer
- `OnboardingWizard` -- Multi-step registration form
- `TradingChart` -- Equity/performance chart visualization
- `MiniChart` -- Small sparkline charts for signals
- `ShareButton` -- Social sharing component for stats
- `SignalCard` -- Signal display card
- `ScanCarousel` -- Scanner signal carousel on dashboard
- `TransparencyLogger` -- Development debugging overlay
- `DisclaimerBar` -- Legal disclaimer in footer
- `Analytics` -- PostHog analytics integration
- `BillingButtons` -- Stripe checkout/portal buttons

**Client-Side Libraries**:
- `lib/api.ts` -- API base URL resolution (client: `/api`, server: internal URL)
- `lib/firebase.ts` -- Firebase client SDK initialization
- `lib/gamification.ts` -- Levels, XP, ranks, achievements, win streaks
- `lib/academy.ts` -- Academy content loading

### 2. API Server (`services/api/`)

**Technology**: Fastify 4, TypeScript, PostgreSQL (pg), Zod

**Purpose**: RESTful API for all backend operations

**Architecture**:
- `server.ts` -- Server factory with CORS, rate limiting, JWT, auth decorator
- `db.ts` -- PostgreSQL connection pool (max 20, idle 30s, connect 5s timeout)
- `env.ts` -- Environment validation with Zod
- `auth/firebase.ts` -- Firebase Admin SDK initialization and token verification
- `routes/` -- Route handlers organized by domain
- `services/` -- Business logic services (email, bot-monitor, unsubscribe, preferences)

**Authentication Decorator**:
The `requireAuth` Fastify decorator:
1. Extracts Bearer token from Authorization header
2. If Firebase is configured: verifies via Firebase Admin SDK (no JWT fallback)
3. If Firebase is not configured: falls back to local JWT verification
4. Sets `request.user = { uid, email, email_verified }`

**Raw Body Parsing**:
A custom content type parser captures the raw request body as a Buffer for Stripe webhook signature verification, while also parsing JSON normally.

### 3. Signal Engine (`services/signal-engine/`)

**Technology**: TypeScript

**Purpose**: Continuous market scanning and signal detection

**Detectors**:
- `vault.ts` -- Accumulation/vault pattern detection
- `divergence.ts` -- Price/indicator divergence detection
- `vice.ts` -- Squeeze and compression pattern detection

Detectors write to the `signals`, `signal_votes`, and `signals_live` tables.

### 4. Automation (`services/automation/`)

**Technology**: TypeScript

**Purpose**: Batch jobs for content management

**Scripts**:
- `seed_candidates.ts` -- Generate candidate lists
- `audit_fix.ts` -- Audit and fix data integrity
- `backfill.ts` -- Backfill historical data
- `remediate.ts` -- Data remediation jobs

---

## Data Flow

### User Registration Flow

```
Browser -> POST /auth/register (with Firebase token)
  -> Validate Zod schema
  -> Security check: token email == body email
  -> INSERT INTO users (upsert)
  -> Firebase Admin: generateEmailVerificationLink
  -> Send verification email via SMTP
  -> Return { success: true }
```

### Bot Proxy Flow

```
Browser -> GET /api/bot/status (with Firebase token)
  -> requireAuth: verify Firebase token
  -> SELECT bot_connection WHERE uid = user.uid AND status = 'active'
  -> fetch(bot_url + "/api/v1/status", { headers: { X-API-Key: api_key } })
  -> Return proxied response
```

### Stripe Subscription Flow

```
Browser -> POST /api/billing/checkout-session (with Firebase token)
  -> Verify email_verified
  -> Check no existing active subscription
  -> Create Stripe Checkout Session
  -> Return { url: checkout_url }

Stripe -> POST /auth/callback/stripe (webhook)
  -> Verify Stripe signature
  -> Extract uid from subscription metadata (or fallback: customer email lookup)
  -> UPSERT stripe_entitlements
```

### Email Notification Flow

```
Bot Monitor (60s loop):
  -> SELECT active bot_connections JOIN users
  -> For each connection:
    -> fetch(bot_url + "/api/v1/risk")
    -> Check thresholds (daily loss, exposure, consecutive losses, etc.)
    -> Determine alert tier (warn25, warn10, triggered)
    -> Check dedup (alertHistory map + 4hr cooldown)
    -> Check user preference (mergePreferences + isPreferenceEnabled)
    -> If should send: sendEmail() with template
    -> Record alert in alertHistory

  -> Check report schedules:
    -> Daily summary at 00:00 UTC
    -> Weekly digest on Sunday 00:00 UTC
    -> Monthly report on 1st 00:00 UTC
```

---

## Database

PostgreSQL 15 with the following key characteristics:
- Connection pool: max 20 connections, 30s idle timeout, 5s connection timeout
- pgcrypto extension for UUID generation
- 8 migration files managing schema evolution
- JSONB used for preferences and signal features

See [Database Schema](Database-Schema.md) for full table definitions.

---

## Caching

Redis 7 is provisioned in docker-compose but currently used primarily for:
- Rate limiting state (via @fastify/rate-limit)
- Potential session caching (future)

---

## External Services

| Service | Purpose | Configuration |
|---|---|---|
| Firebase Auth | User authentication | Service account JSON or Base64 env var |
| Stripe | Payments | Secret key, webhook secret, price ID |
| SMTP (SiteProtect) | Email delivery | 4 mailbox configs (support, alerts, marketing, security) |
| PostHog | Product analytics | API key + host |
| Polygon.io | Stock market data (NovaPulse) | API key |

---

## Error Handling

- API errors return JSON with `{ error: "error_code" }` and appropriate HTTP status codes
- Zod validation errors include `{ error: "invalid_request", details: { fieldErrors } }`
- Bot proxy errors return 502 with `{ error: "bot_unreachable" }`
- Database errors are caught and logged; 500 returned to client
- Email sending failures are logged but do not block API responses
- Unhandled errors are caught by Fastify's error handler

---

## Observability

- Fastify built-in request/response logging (pino)
- Console logging for email send/skip events
- Bot monitor logs for each check cycle
- PostHog for frontend analytics
- Docker health checks on all services

---

*Last updated: March 2026*

# Database Schema

HorizonAlerts uses PostgreSQL 15 with the `pgcrypto` extension for UUID generation. The schema is managed through sequential SQL migration files.

---

## Connection Configuration

```typescript
const pool = new Pool({
  connectionString: process.env.DATABASE_URL,
  max: 20,                        // Maximum connections in pool
  idleTimeoutMillis: 30_000,      // Close idle connections after 30s
  connectionTimeoutMillis: 5_000, // Fail connection attempt after 5s
});
```

Default connection string: `postgres://postgres:postgres@localhost:5432/horizonalerts`

---

## Tables

### users

Primary user accounts table. Created by migration `002_users.sql`, extended by `003_preferences.sql` and `006_login_security.sql`.

```sql
CREATE TABLE users (
  uid             TEXT PRIMARY KEY,           -- Firebase UID
  email           TEXT NOT NULL UNIQUE,
  first_name      TEXT,
  last_name       TEXT,
  age             INT,
  zip_code        TEXT,
  street_address  TEXT,
  city            TEXT,
  state           TEXT,
  is_premium      BOOLEAN DEFAULT false,
  preferences     JSONB DEFAULT '{}'::jsonb,  -- Notification preferences (added by 003)
  locked_until    TIMESTAMPTZ,                -- Account lock expiry (added by 006)
  failed_login_count INT DEFAULT 0,           -- Recent failed attempts (added by 006)
  created_at      TIMESTAMPTZ DEFAULT now(),
  updated_at      TIMESTAMPTZ DEFAULT now()
);
```

**Notes**:
- `uid` is the Firebase UID, used as the primary key across all user-related tables
- `preferences` stores notification preferences as JSONB, merged with defaults at read time
- `locked_until` is set when 3+ failed login attempts occur in 30 minutes
- `is_premium` is a legacy field; actual subscription status is in `stripe_entitlements`

### stripe_entitlements

Subscription status synced from Stripe webhooks.

```sql
CREATE TABLE stripe_entitlements (
  uid                 TEXT PRIMARY KEY,      -- FK to users.uid
  plan                TEXT NOT NULL,         -- 'free', 'pro', 'elite'
  status              TEXT NOT NULL,         -- 'active', 'canceled', 'past_due', etc.
  current_period_end  TIMESTAMPTZ,           -- Subscription period end
  seats               INT NOT NULL DEFAULT 1,
  updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

**Notes**:
- Updated by Stripe webhook handler on subscription events
- `status` maps directly to Stripe subscription statuses
- `plan` is extracted from the price metadata or defaults to 'pro'
- `uid` is resolved from subscription metadata or by customer email lookup

### bot_connections

User bot connection configurations.

```sql
CREATE TABLE bot_connections (
  id            SERIAL PRIMARY KEY,
  uid           TEXT NOT NULL REFERENCES users(uid),  -- One connection per user
  bot_url       TEXT NOT NULL,                        -- NovaPulse API URL
  api_key       TEXT NOT NULL,                        -- Bot dashboard API key
  hosting_type  TEXT NOT NULL DEFAULT 'managed',      -- 'managed' or 'self-hosted'
  label         TEXT DEFAULT 'My Bot',
  status        TEXT DEFAULT 'active',                -- 'active' or 'disconnected'
  created_at    TIMESTAMPTZ DEFAULT now(),
  updated_at    TIMESTAMPTZ DEFAULT now(),
  UNIQUE(uid)                                         -- One active connection per user
);

CREATE INDEX idx_bot_connections_status ON bot_connections(status);
```

**Notes**:
- UNIQUE constraint on `uid` ensures one bot per user
- Upsert on PUT /bot/connection uses ON CONFLICT (uid) DO UPDATE
- DELETE sets `status = 'disconnected'` rather than removing the row
- `api_key` is the bot's read or admin API key, sent as X-API-Key header

### login_attempts

Login attempt tracking for security/lockout.

```sql
CREATE TABLE login_attempts (
  id          BIGSERIAL PRIMARY KEY,
  email       TEXT NOT NULL,
  ip_address  TEXT NOT NULL,
  user_agent  TEXT,
  success     BOOLEAN DEFAULT false,
  created_at  TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_login_attempts_email_created ON login_attempts (email, created_at DESC);
```

**Notes**:
- Populated by POST /auth/login-attempt
- Used to count recent failures (last 30 minutes) for lockout decisions
- IP address extracted from X-Forwarded-For header or direct connection

### support_tickets

User support tickets with department routing and priority.

```sql
CREATE TABLE support_tickets (
  id          BIGSERIAL PRIMARY KEY,
  uid         TEXT NOT NULL REFERENCES users(uid) ON DELETE CASCADE,
  department  TEXT NOT NULL CHECK (department IN (
    'billing', 'tech_support', 'customer_service', 'referrals', 'partnership'
  )),
  subject     TEXT NOT NULL,
  message     TEXT NOT NULL,
  status      TEXT NOT NULL DEFAULT 'open' CHECK (status IN (
    'open', 'in_progress', 'resolved', 'closed'
  )),
  priority    TEXT NOT NULL DEFAULT 'normal' CHECK (priority IN (
    'low', 'normal', 'high', 'urgent'
  )),
  created_at  TIMESTAMPTZ DEFAULT now(),
  updated_at  TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_tickets_uid ON support_tickets(uid);
```

### ticket_replies

Replies on support tickets from users or staff.

```sql
CREATE TABLE ticket_replies (
  id          BIGSERIAL PRIMARY KEY,
  ticket_id   BIGINT NOT NULL REFERENCES support_tickets(id) ON DELETE CASCADE,
  author_type TEXT NOT NULL CHECK (author_type IN ('user', 'staff')),
  author_name TEXT,
  message     TEXT NOT NULL,
  created_at  TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_ticket_replies_ticket ON ticket_replies(ticket_id);
```

### newsletter_subscribers

Newsletter subscription tracking.

```sql
CREATE TABLE newsletter_subscribers (
  id          BIGSERIAL PRIMARY KEY,
  email       TEXT NOT NULL,
  list_name   TEXT NOT NULL CHECK (list_name IN (
    'stock_alerts', 'weekly_newsletter', 'product_updates'
  )),
  source      TEXT DEFAULT 'website',
  status      TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'unsubscribed')),
  created_at  TIMESTAMPTZ DEFAULT now(),
  updated_at  TIMESTAMPTZ DEFAULT now(),
  UNIQUE (email, list_name)
);

CREATE INDEX idx_newsletter_email ON newsletter_subscribers(email);
CREATE INDEX idx_newsletter_list ON newsletter_subscribers(list_name);
```

**Notes**:
- UNIQUE constraint on (email, list_name) prevents duplicate subscriptions
- Re-subscription (same email + list) updates status to 'active' via ON CONFLICT DO UPDATE

### signals

Signal detection records from the signal engine.

```sql
CREATE TABLE signals (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  symbol          TEXT NOT NULL,
  venue           TEXT NOT NULL,
  asset_type      TEXT NOT NULL,
  pattern         TEXT NOT NULL,
  features        JSONB NOT NULL DEFAULT '{}'::jsonb,
  entry           NUMERIC NOT NULL,
  sl              NUMERIC NOT NULL,
  tp1             NUMERIC,
  tp2             NUMERIC,
  tp3             NUMERIC,
  confidence      INT NOT NULL,
  bar_time        TIMESTAMPTZ NOT NULL,
  seen_time       TIMESTAMPTZ NOT NULL,
  interval        TEXT NOT NULL,
  data_latency_ms INT NOT NULL,
  vendor          TEXT NOT NULL,
  class_scope     TEXT NOT NULL,
  options_meta    JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

### signal_votes

Individual detector votes on signals.

```sql
CREATE TABLE signal_votes (
  id          BIGSERIAL PRIMARY KEY,
  signal_id   UUID REFERENCES signals(id),
  detector    TEXT NOT NULL,
  score       NUMERIC NOT NULL,
  details     JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

### signals_live

Active signal tracking with deduplication.

```sql
CREATE TABLE signals_live (
  signal_id   UUID PRIMARY KEY REFERENCES signals(id),
  status      TEXT NOT NULL,
  first_seen  TIMESTAMPTZ NOT NULL,
  last_seen   TIMESTAMPTZ NOT NULL,
  dedupe_hash TEXT NOT NULL UNIQUE
);
```

### public_feed

Published signal feed with configurable delay.

```sql
CREATE TABLE public_feed (
  id              BIGSERIAL PRIMARY KEY,
  signal_id       UUID REFERENCES signals(id),
  published_at    TIMESTAMPTZ NOT NULL,
  delay_minutes   INT NOT NULL DEFAULT 15
);
```

### email_log

Email send tracking for audit and deduplication.

```sql
CREATE TABLE email_log (
  id        BIGSERIAL PRIMARY KEY,
  uid       TEXT NOT NULL,
  template  TEXT NOT NULL,          -- Template name or 'custom', appended ':skipped' if preference-blocked
  subject   TEXT NOT NULL,
  sent_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  to_addr   TEXT NOT NULL
);
```

**Notes**:
- Used by bot-monitor to reload alert dedup history after process restart
- Template field includes ':skipped' suffix when email was blocked by preference check

### help_tickets

Legacy help ticket table (from initial migration).

```sql
CREATE TABLE help_tickets (
  id          BIGSERIAL PRIMARY KEY,
  uid         TEXT NOT NULL,
  email       TEXT NOT NULL,
  subject     TEXT NOT NULL,
  message     TEXT NOT NULL,
  status      TEXT NOT NULL,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

**Notes**: This is the older ticket system used by POST /help/ticket. The newer support_tickets table (migration 007) is used by the Settings > Support tab.

### portfolio_events

User portfolio interaction tracking.

```sql
CREATE TABLE portfolio_events (
  id          BIGSERIAL PRIMARY KEY,
  uid         TEXT NOT NULL,
  alert_id    UUID NOT NULL,
  symbol      TEXT NOT NULL,
  action      TEXT NOT NULL,
  price       NUMERIC NOT NULL,
  decided_at  TIMESTAMPTZ NOT NULL,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

---

## Migration Files

Migrations are located in `services/api/db/migrations/` and must be run in order:

| File | Description |
|---|---|
| `001_init.sql` | Core tables: signals, signal_votes, signals_live, public_feed, email_log, stripe_entitlements, help_tickets, portfolio_events |
| `002_users.sql` | Users table with profile fields |
| `003_preferences.sql` | Adds `preferences` JSONB column to users |
| `004_bot_connections.sql` | Bot connections table with UNIQUE(uid) |
| `005_fk_cascade.sql` | Adds foreign key cascades |
| `006_login_security.sql` | Login attempts table + locked_until/failed_login_count on users |
| `007_support_tickets.sql` | Support tickets + ticket_replies tables |
| `008_newsletter.sql` | Newsletter subscribers table |

**Important**: Migrations are idempotent (use `CREATE TABLE IF NOT EXISTS`, `ADD COLUMN IF NOT EXISTS`). They can be safely re-run.

---

## JSONB Preferences Structure

The `users.preferences` column stores notification preferences. The application merges stored values with defaults at read time, so newly added preference keys are automatically available with their default values.

See [Email System](Email-System.md) for the full default preferences structure.

---

## Indexes

| Table | Index | Columns |
|---|---|---|
| bot_connections | idx_bot_connections_status | status |
| login_attempts | idx_login_attempts_email_created | email, created_at DESC |
| support_tickets | idx_tickets_uid | uid |
| ticket_replies | idx_ticket_replies_ticket | ticket_id |
| newsletter_subscribers | idx_newsletter_email | email |
| newsletter_subscribers | idx_newsletter_list | list_name |

---

*Last updated: March 2026*

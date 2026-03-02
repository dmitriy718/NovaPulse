# Deployment

This document covers the deployment architecture for HorizonAlerts, including Docker Compose, Nginx reverse proxy, Ansible automation, and environment configuration.

---

## Infrastructure Overview

```
[Internet] --> [VPS] --> [Nginx :80/:443] --> [Next.js Web :3000]
                                          --> [Fastify API :4000]

Docker Compose Services:
  - postgres (PostgreSQL 15)
  - redis (Redis 7)
  - api (Fastify :4000)
  - web (Next.js :3000)
  - signal-engine (Signal detection)
  - automation (Batch jobs)

Volumes:
  - pgdata (PostgreSQL data)
  - ./content (Shared content directory, read-only)
  - Firebase service account files (read-only)
```

---

## Docker Compose (Production)

The production Docker Compose file is `docker-compose.prod.yml`.

### Services

#### PostgreSQL (`postgres`)

```yaml
image: postgres:15
environment:
  POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
  POSTGRES_USER: ${POSTGRES_USER}
  POSTGRES_DB: ${POSTGRES_DB}
volumes:
  - pgdata:/var/lib/postgresql/data
  - ./services/api/db/migrations/001_init.sql:/db/001_init.sql:ro
healthcheck:
  test: pg_isready -U ${POSTGRES_USER} -d ${POSTGRES_DB}
  interval: 10s
```

#### Redis (`redis`)

```yaml
image: redis:7
healthcheck:
  test: redis-cli ping
  interval: 10s
```

#### API (`api`)

```yaml
build:
  context: .
  dockerfile: services/api/Dockerfile
  target: prod
environment:
  PORT: 4000
  HOST: 0.0.0.0
  NODE_ENV: production
  DATABASE_URL: ${DATABASE_URL}
  # ... all SMTP, Stripe, Firebase vars
volumes:
  - ./content:/app/content
  - ./horizonsvcfirebase.json:/app/horizonsvcfirebase.json:ro
  - ./horizontalv2.json:/app/horizontalv2.json:ro
ports:
  - "4000:4000"
depends_on: [postgres, redis]
healthcheck:
  test: node http health check on localhost:4000
  interval: 10s
```

#### Web (`web`)

```yaml
build:
  context: .
  dockerfile: apps/web/Dockerfile
  target: prod
  args:
    # All NEXT_PUBLIC_* vars needed at build time
    NEXT_PUBLIC_API_BASE: ${NEXT_PUBLIC_API_BASE}
    NEXT_PUBLIC_FIREBASE_*: ${NEXT_PUBLIC_FIREBASE_*}
    NEXT_PUBLIC_POSTHOG_*: ${NEXT_PUBLIC_POSTHOG_*}
environment:
  PUBLIC_API_BASE: https://horizonsvc.com/api
  NEXT_PUBLIC_API_BASE: https://horizonsvc.com/api
  # ... same Firebase/PostHog vars at runtime
volumes:
  - ./content:/app/content
ports:
  - "3000:3000"
depends_on: [api]
```

**Important**: `NEXT_PUBLIC_*` variables must be provided both as build `args` (baked into the static build) AND as runtime `environment` (for server components).

#### Signal Engine (`signal-engine`)

```yaml
build:
  context: .
  dockerfile: services/signal-engine/Dockerfile
  target: prod
environment:
  DATABASE_URL: ${DATABASE_URL}
  REDIS_URL: ${REDIS_URL}
depends_on: [postgres, redis]
```

#### Automation (`automation`)

```yaml
build:
  context: .
  dockerfile: services/automation/Dockerfile
environment:
  DATABASE_URL: ${DATABASE_URL}
  OPENAI_API_KEY: ${OPENAI_API_KEY}
```

### Volumes

```yaml
volumes:
  pgdata:  # Persistent PostgreSQL data
```

The `content` directory is bind-mounted (not a Docker volume) to allow easy content updates without rebuilding.

---

## Nginx Configuration

### Location: `infra/ansible/roles/nginx/templates/nginx.conf.j2`

### HTTP to HTTPS Redirect

```nginx
server {
  listen 80;
  server_name horizonsvc.com www.horizonsvc.com;
  return 301 https://$host$request_uri;
}
```

### HTTPS Server

```nginx
server {
  listen 443 ssl http2;
  server_name horizonsvc.com www.horizonsvc.com;

  ssl_certificate /etc/letsencrypt/live/horizonsvc.com/fullchain.pem;
  ssl_certificate_key /etc/letsencrypt/live/horizonsvc.com/privkey.pem;
```

### Security Headers

```nginx
add_header Strict-Transport-Security "max-age=63072000; includeSubDomains; preload" always;
add_header X-Content-Type-Options "nosniff" always;
add_header X-Frame-Options "DENY" always;
add_header Referrer-Policy "no-referrer-when-downgrade" always;
add_header Content-Security-Policy "..." always;
```

### CSP Details

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

### Proxy Configuration

```nginx
# Next.js app
location / {
  proxy_pass http://127.0.0.1:3000;
  proxy_set_header Host $host;
  proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
  proxy_set_header X-Forwarded-Proto $scheme;
}

# Fastify API (strips /api/ prefix)
location /api/ {
  proxy_pass http://127.0.0.1:4000/;
  proxy_set_header Host $host;
  proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
  proxy_set_header X-Forwarded-Proto $scheme;
}
```

**Note**: The trailing slash in `proxy_pass http://127.0.0.1:4000/` causes Nginx to strip the `/api/` prefix. So `/api/health` is forwarded as `/health` to the API server.

### SSL Certificates

Let's Encrypt certificates are used. The `certbot` renewal should be configured as a cron job or systemd timer.

---

## Ansible

### Inventory

`infra/ansible/hosts.ini` defines target servers.

### Playbook

`infra/ansible/site.yml` is the main playbook that applies roles.

### Roles

#### Docker Role (`roles/docker/`)

Installs Docker and Docker Compose on the target server.

#### Nginx Role (`roles/nginx/`)

- Installs Nginx
- Templates the `nginx.conf.j2` configuration
- Handler to reload Nginx on config changes

---

## Environment Variables

### Complete List

The `.env.example` file documents all variables. Key groups:

**Database**:
```
DATABASE_URL=postgres://postgres:postgres@localhost:5432/horizonalerts
POSTGRES_PASSWORD=postgres
POSTGRES_USER=postgres
POSTGRES_DB=horizonalerts
REDIS_URL=redis://localhost:6379
```

**Authentication**:
```
JWT_SIGNING_KEY=<min 12 chars in production>
FIREBASE_SERVICE_ACCOUNT_PATH=./horizonsvcfirebase.json
NEXT_PUBLIC_FIREBASE_API_KEY=
NEXT_PUBLIC_FIREBASE_AUTH_DOMAIN=
NEXT_PUBLIC_FIREBASE_PROJECT_ID=
NEXT_PUBLIC_FIREBASE_APP_ID=
NEXT_PUBLIC_FIREBASE_MESSAGING_SENDER_ID=
NEXT_PUBLIC_FIREBASE_STORAGE_BUCKET=
```

**Stripe**:
```
STRIPE_SECRET_KEY=
STRIPE_WEBHOOK_SECRET=
STRIPE_PRICE_ID_PRO=
STRIPE_SUCCESS_URL=
STRIPE_CANCEL_URL=
STRIPE_PORTAL_RETURN_URL=
```

**Email (SMTP)**:
```
SMTP_HOST=smtp.siteprotect.com
SMTP_PORT=587
SMTP_SUPPORT_USER=
SMTP_SUPPORT_PASS=
SMTP_SUPPORT_FROM=Nova by Horizon <support@horizonsvc.com>
SMTP_ALERTS_USER=
SMTP_ALERTS_PASS=
SMTP_ALERTS_FROM=
SMTP_MARKETING_USER=
SMTP_MARKETING_PASS=
SMTP_MARKETING_FROM=
SMTP_SECURITY_USER=
SMTP_SECURITY_PASS=
SMTP_SECURITY_FROM=
```

**URLs**:
```
PUBLIC_SITE_URL=https://horizonsvc.com
PUBLIC_API_BASE=https://horizonsvc.com/api
NEXT_PUBLIC_API_BASE=https://horizonsvc.com/api
CORS_ORIGINS=https://horizonsvc.com,http://localhost:3000
```

**Analytics**:
```
NEXT_PUBLIC_POSTHOG_KEY=
NEXT_PUBLIC_POSTHOG_HOST=https://app.posthog.com
```

**Third Party**:
```
OPENAI_API_KEY=          # For automation scripts
SENDGRID_API_KEY=        # Legacy, not actively used
```

---

## Database Migrations

Migrations must be run manually in order:

```bash
psql $DATABASE_URL -f services/api/db/migrations/001_init.sql
psql $DATABASE_URL -f services/api/db/migrations/002_users.sql
psql $DATABASE_URL -f services/api/db/migrations/003_preferences.sql
psql $DATABASE_URL -f services/api/db/migrations/004_bot_connections.sql
psql $DATABASE_URL -f services/api/db/migrations/005_fk_cascade.sql
psql $DATABASE_URL -f services/api/db/migrations/006_login_security.sql
psql $DATABASE_URL -f services/api/db/migrations/007_support_tickets.sql
psql $DATABASE_URL -f services/api/db/migrations/008_newsletter.sql
```

All migrations use `CREATE TABLE IF NOT EXISTS` and `ADD COLUMN IF NOT EXISTS`, making them idempotent and safe to re-run.

---

## Health Checks

Docker Compose health checks ensure service availability:

| Service | Check | Interval |
|---|---|---|
| postgres | `pg_isready` | 10s |
| redis | `redis-cli ping` | 10s |
| api | HTTP GET localhost:4000/health | 10s |
| web | HTTP GET localhost:3000 | 15s |

Dependencies use `depends_on` (without `condition: service_healthy` in this config) for startup ordering.

---

## Deployment Process

### Initial Deployment

1. Provision VPS (manually or via Terraform)
2. Run Ansible playbook to install Docker and Nginx
3. Copy `.env` with production values to server
4. Copy Firebase service account JSON to server
5. Run `docker compose -f docker-compose.prod.yml up -d --build`
6. Run database migrations
7. Set up SSL with Let's Encrypt: `certbot --nginx -d horizonsvc.com -d www.horizonsvc.com`
8. Set up Stripe webhook endpoint: `https://horizonsvc.com/api/auth/callback/stripe`

### Updates

1. Pull latest code on server (or deploy via CI)
2. `docker compose -f docker-compose.prod.yml up -d --build`
3. Run any new migrations
4. Verify health checks pass

### Rollback

1. `docker compose -f docker-compose.prod.yml down`
2. Check out previous version
3. `docker compose -f docker-compose.prod.yml up -d --build`

---

## Testing

### Test Configuration

- **Test runner**: Vitest (`vitest.config.ts`)
- **E2E tests**: Playwright (`playwright.config.ts`)
- **Test directory**: `tests/`

### Running Tests

```bash
npm test          # Run Vitest unit tests
npm run test:e2e  # Run Playwright E2E tests
```

---

## Terraform

`infra/terraform/main.tf` contains IaC for VPS provisioning. This is optional and can be replaced with manual VPS creation.

---

## Monitoring Recommendations

Currently the application relies on Docker health checks and Fastify logging. Recommended additions:
- Uptime monitoring (e.g., UptimeRobot, Better Stack)
- Log aggregation (e.g., Loki, Datadog)
- Error tracking (e.g., Sentry)
- Database monitoring (pg_stat_statements)

---

*Last updated: March 2026*

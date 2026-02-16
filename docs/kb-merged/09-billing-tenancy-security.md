# Billing, Tenancy, and Security

## Tenancy (Support/Dev)

DB tables:

1. `tenants`
1. `tenant_api_keys`

Tenant statuses:

1. `active` and `trialing` should be allowed for non-admin access
1. others (for example `past_due`, `canceled`) should be denied for non-admin access

API tenant resolution rules:

1. Admin key (`DASHBOARD_SECRET_KEY`) can target any tenant explicitly.
1. Tenant API keys are pinned; they cannot claim a different tenant id.
1. If no valid mapping exists, requests must not be allowed to select arbitrary tenants.

Implementation:

1. `src/api/server.py` (`DashboardServer.resolve_tenant_id`)
1. `src/core/database.py` tenant/key lookups
1. `src/core/control_router.py` tenant mismatch protection

## Billing (Stripe)

Webhook endpoint:

1. `POST /api/v1/billing/webhook`

Expected behavior:

1. Verify webhook signature.
1. Update tenant status based on subscription lifecycle events.

## Control Auth (Local Bot)

Control endpoints require `X-API-Key`. Acceptable keys:

1. admin key (full access)
1. tenant API key (tenant-scoped)

## Frontend Key Handling

The UI requires a runtime key and does not ship a hardcoded key.

File:

1. `static/js/dashboard.js`

## Secrets Storage Rules

1. Never commit `.env`.
1. Never paste exchange keys into tickets or chat logs.
1. Rotate keys after any suspected exposure.

## Managed Stack Basic Auth (Environment-Specific)

Some deployments protect the dashboard and agent endpoints with reverse-proxy Basic Auth.

Example file locations (if your environment matches):

1. Nova password (plaintext): `/home/ops/agent-stack/.nova_pass`
1. Nova password hash (bcrypt): `/home/ops/agent-stack/.nova_hash`
1. Agent chat password (plaintext): `/home/ops/agent-stack/.agent_chat_pass`
1. Agent chat password hash (bcrypt): `/home/ops/agent-stack/.agent_chat_hash`

Rotation procedure (high level):

1. Generate a new password and write it to the relevant `*_pass` file (restrict perms).
1. Generate a new bcrypt hash (often via `caddy hash-password`).
1. Update the reverse proxy config (for example `Caddyfile`) to use the new hash.
1. Restart the proxy container.
1. Validate with `curl -u`.

Operational note:

1. Do not paste plaintext passwords or full hashes into tickets or chat logs.

## Network and Exposure

1. Keep local dashboards CORS-restricted.
1. If exposing publicly, add reverse proxy auth and consider IP allowlists.

## SSH and Operator Access (Support/Dev)

1. Restrict SSH to an operator allowlist.
1. Prefer key-based auth.
1. Treat "ops" host credentials as production secrets.

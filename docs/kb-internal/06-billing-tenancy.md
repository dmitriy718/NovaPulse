# Billing + Tenancy

Reference:
- `docs/BILLING.md`
- `src/billing/stripe_service.py`
- `src/core/database.py` (tenants + tenant_api_keys schema)

## Tenants

Tables:
- `tenants`: id, name, stripe customer/subscription IDs, status
- `tenant_api_keys`: api_key_hash -> tenant_id

Tenant statuses:
- `active` / `trialing`: allowed
- `past_due` / `canceled` / others: denied for non-admin API access

## Stripe webhooks

Endpoint:
- `POST /api/v1/billing/webhook`

Behavior:
- Verifies `Stripe-Signature`.
- Updates tenant status by subscription events.

## Tenant isolation model (current)

- DB queries are tenant-scoped in most read paths.
- API resolves tenant based on admin key or tenant API key mapping.
- Engine runtime is still effectively single-tenant (default tenant id) unless engineered otherwise.

## Support playbook

If a client says they are blocked:
1. `GET /api/v1/tenants/{tenant_id}` (admin only) to see status.
2. Verify webhook secrets and Stripe subscription status.
3. Confirm tenant API key mapping exists (hashed).


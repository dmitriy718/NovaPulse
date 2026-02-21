# Release Checklist

Pre-release:
- Verify Python version constraints and install docs are accurate.
- Run CI green on Python 3.11 and 3.12.
- Run `python scripts/live_preflight.py --strict` and require exit code `0`.
- Confirm dashboard control auth behavior:
  - Admin key works.
  - Tenant key cannot act as another tenant.
  - Inactive tenant is rejected.
- Smoke test:
  - Dashboard WS updates.
  - Scan loop active.
  - Position management loop active.
  - Close-all works in paper mode.
- If billing is enabled:
  - `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`, and at least one paid price id (`STRIPE_PRICE_ID_PRO` or `STRIPE_PRICE_ID_PREMIUM`, or legacy `STRIPE_PRICE_ID`) are present.
  - Stripe endpoint points to `POST /api/v1/billing/webhook`.
  - Stripe events include `checkout.session.completed`, `customer.subscription.updated`, `customer.subscription.deleted`, `invoice.paid`, `invoice.payment_failed`.
- If signal webhooks are enabled:
  - `SIGNAL_WEBHOOK_SECRET` is present.
  - `webhooks.allowed_sources` is non-empty.

Security:
- Confirm no hardcoded secrets in frontend.
- Ensure `DASHBOARD_ADMIN_KEY`, `DASHBOARD_SESSION_SECRET`, and `DASHBOARD_ADMIN_PASSWORD_HASH` are set in live mode.
- Ensure `dashboard.require_api_key_for_reads=true` in live mode.

Operational:
- Confirm log rotation and disk usage expectations.
- Confirm DB migrations run idempotently on startup.
- Confirm typed-safety policy is documented (current baseline: mypy is informational, not release-blocking).
- Confirm secrets policy is applied for this release:
  - single-vault model accepted
  - runtime service account is read-only
  - item-level ACLs are scoped to required runtime secrets only

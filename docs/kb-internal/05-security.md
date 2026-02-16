# Security Notes

## Dashboard control auth model

There are two auth patterns:
- Admin control key: `DASHBOARD_SECRET_KEY`
- Tenant API keys: mapped in DB (`tenant_api_keys`) and pinned to a tenant

Tenant rules (non-admin):
- Tenant keys cannot impersonate a different tenant via `X-Tenant-ID`.
- If tenant status is not `active` or `trialing`, API access is denied.

## Frontend key handling

The dashboard JS does not ship a default control key.
To enable control actions in a browser session, set:
- `localStorage.DASHBOARD_API_KEY = "<key>"`
or provide `window.DASHBOARD_API_KEY` at runtime.

## Secrets storage

Environment variables:
- Kraken/Coinbase API credentials
- Stripe secrets
- Dashboard secret key

Optional vault:
- `src/core/vault.py` provides an encrypted vault but is not fully wired into runtime config by default.

## Recommendations

- Never run live mode without `DASHBOARD_SECRET_KEY`.
- Restrict dashboard network access (reverse proxy auth, firewall).
- Rotate keys periodically and after any suspected exposure.


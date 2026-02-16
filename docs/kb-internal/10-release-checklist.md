# Release Checklist

Pre-release:
- Verify Python version constraints and install docs are accurate.
- Run CI green on Python 3.11 and 3.12.
- Confirm dashboard control auth behavior:
  - Admin key works.
  - Tenant key cannot act as another tenant.
  - Inactive tenant is rejected.
- Smoke test:
  - Dashboard WS updates
  - Scan loop active
  - Position management loop active
  - Close-all works in paper mode

Security:
- Confirm no hardcoded secrets in frontend.
- Ensure `DASHBOARD_SECRET_KEY` is required in live mode and set in deployment.

Operational:
- Confirm log rotation and disk usage expectations.
- Confirm DB migrations run idempotently on startup.


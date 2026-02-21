# Reboot Checkpoint (2026-02-21)

## Where We Left Off

- Branch: `main`
- Remote: `origin` -> `https://github.com/dmitriy718/NovaPulse.git`
- Stripe webhook endpoint configured: `https://nova.horizonsvc.com/api/v1/billing/webhook`
- 1Password confirmed fields now include:
  - `STRIPE_WEBHOOK_SECRET`
  - `STRIPE_PRICE_ID`
  - `STRIPE_WEBHOOK_ENDPOINT` (ops reference)
  - `CRYPTOPANIC_API_KEY`
- Vault model decision locked for release: **single vault + strict item-level ACLs**.

## Major Work Completed In This Commit

1. Billing tiers upgraded to support `free`, `pro`, `premium`.
2. Added multi-price Stripe support:
   - `STRIPE_PRICE_ID_PRO`
   - `STRIPE_PRICE_ID_PREMIUM`
   - legacy `STRIPE_PRICE_ID` fallback retained.
3. `POST /api/v1/billing/checkout` now accepts `plan` (`free|pro|premium`).
4. `free` plan path implemented (provisions tenant as `trialing` without Stripe checkout).
5. Preflight hardening:
   - signal webhook secret enforcement when enabled
   - billing runtime completeness checks for webhook secret + at least one paid price id
   - warning for missing `COINGECKO_API_KEY` when enrichment is enabled
6. Docs updated across README/runbooks/internal+merged KB to align with current auth and billing behavior.
7. Final testing doc updated with continuation pass and latest validation.

## Validation Snapshot

- `pytest -q` -> **136 passed**
- `scripts/walk_forward_gate.py` -> **PASS**
- targeted `ruff check` on changed billing/preflight/test files -> **passed**
- `mypy src tests` -> **289 errors in 37 files** (informational debt; not release-blocking policy)

## Next Steps After Reboot

1. In 1Password, set:
   - `STRIPE_PRICE_ID_PRO` (49.99 plan)
   - `STRIPE_PRICE_ID_PREMIUM` (79.99 plan)
2. Ensure runtime secret injection includes those values.
3. Run strict readiness check:
   - `python scripts/live_preflight.py --strict`
4. If clean, proceed to release start sequence from `LiveRunbook.md`.

## Resume Instruction

When back, ask Codex to: **"read `REBOOT_CHECKPOINT_2026-02-21.md` and continue"**.

# ==============================================================================
# NovaPulse — Secrets Template
#
# This file contains 1Password op:// references for all secrets.
# Run `./scripts/resolve_secrets.sh` to generate .env.secrets with real values.
#
# Values are resolved at deploy time — Docker never sees op:// or raw $.
# The generated .env.secrets is gitignored and loaded via env_file: in
# docker-compose.yml, bypassing Docker Compose's variable interpolation.
#
# For manual setup (no 1Password): copy this to .env.secrets and replace
# op:// references with actual values. No $$ escaping needed.
# ==============================================================================

# ---- Exchange API Keys ----
KRAKEN_API_KEY=op://dev/kraken/API_KEY
KRAKEN_API_SECRET=op://dev/kraken/API_SECRET
COINBASE_ORG_ID=op://dev/coinbase/ORG_ID
COINBASE_KEY_ID=op://dev/coinbase/KEY_ID
COINBASE_KEY_NAME=op://dev/coinbase/KEY_NAME
POLYGON_API_KEY=op://dev/polygon/API_KEY
ALPACA_API_KEY=op://dev/alpaca/API_KEY
ALPACA_API_SECRET=op://dev/alpaca/API_SECRET

# ---- Dashboard Auth ----
DASHBOARD_ADMIN_KEY=op://dev/dashboard/DASHBOARD_ADMIN_KEY
DASHBOARD_READ_KEY=op://dev/dashboard/DASHBOARD_READ_KEY
DASHBOARD_SESSION_SECRET=op://dev/dashboard/DASHBOARD_SESSION_SECRET
DASHBOARD_ADMIN_PASSWORD_HASH=op://dev/dashboard/DASHBOARD_ADMIN_PASSWORD_HASH

# ---- Telegram ----
TELEGRAM_BOT_TOKEN=op://dev/telegram/BOT_TOKEN
TELEGRAM_CHAT_ID=op://dev/telegram/CHAT_ID

# ---- External Services ----
COINGECKO_API_KEY=op://dev/coingecko/API_KEY
CRYPTOPANIC_API_KEY=op://dev/cryptopanic/API_KEY

# ---- Stripe (optional) ----
# STRIPE_SECRET_KEY=op://dev/stripe/SECRET_KEY
# STRIPE_WEBHOOK_SECRET=op://dev/stripe/WEBHOOK_SECRET

# ---- Vault ----
# VAULT_PASSWORD=op://dev/vault/PASSWORD

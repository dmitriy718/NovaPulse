# NovaPulse Credential Rotation

**Version:** 4.0.0
**Last Updated:** 2026-02-22

---

## Overview

This document describes zero-downtime credential rotation procedures for all external services used by NovaPulse. All credentials are stored in environment variables (`.env` file) or Docker secrets -- never in `config/config.yaml`.

---

## Kraken API Keys

### When to Rotate
- Quarterly (recommended)
- After team member departure
- If key exposure is suspected

### Procedure

1. **Generate new API key on Kraken:**
   - Log into Kraken at https://www.kraken.com/u/security/api
   - Create a new key with required permissions:
     - Query funds
     - Query open orders & trades
     - Query closed orders & trades
     - Create & modify orders
     - Cancel/close orders
   - Do NOT delete the old key yet

2. **Update credentials:**
   ```bash
   # Edit .env
   KRAKEN_API_KEY=new_key_here
   KRAKEN_API_SECRET=new_secret_here
   ```

3. **Restart the bot:**
   ```bash
   docker compose restart trading-bot
   ```

4. **Verify connectivity:**
   ```bash
   # Check logs for successful initialization
   docker logs novapulse --tail 50 | grep "Kraken REST client initialized"

   # Check status
   curl -s http://localhost:8090/api/v1/status -H "X-API-Key: $DASHBOARD_ADMIN_KEY"
   ```

5. **Delete old key on Kraken** after confirming the bot is working with the new key.

### Multi-Account Mode

For multi-account setups, keys follow the convention `{ACCOUNT_PREFIX}_{EXCHANGE}_API_KEY`:

```bash
MAIN_KRAKEN_API_KEY=new_key
MAIN_KRAKEN_API_SECRET=new_secret
SWING_KRAKEN_API_KEY=another_key
SWING_KRAKEN_API_SECRET=another_secret
```

---

## Coinbase API Keys

### Procedure

1. **Generate new CDP API key** at https://portal.cdp.coinbase.com/
   - Download the key file (contains key_name and private_key PEM)

2. **Update credentials:**
   ```bash
   COINBASE_API_KEY=organizations/xxx/apiKeys/yyy
   COINBASE_API_SECRET="-----BEGIN EC PRIVATE KEY-----\n...\n-----END EC PRIVATE KEY-----"
   ```

3. **Restart and verify** (same as Kraken steps 3-5).

---

## Dashboard Admin Key

### When to Rotate
- When a team member with access departs
- After suspected exposure
- Annually at minimum

### Procedure

1. **Generate a new key:**
   ```bash
   python -c "import secrets; print(secrets.token_urlsafe(32))"
   ```

2. **Update `.env`:**
   ```bash
   DASHBOARD_ADMIN_KEY=new_key_here
   ```

3. **Restart the bot:**
   ```bash
   docker compose restart trading-bot
   ```

4. **Update all clients** using the old key:
   - Monitoring scripts
   - CI/CD pipelines
   - Team members' local configs
   - Telegram/Discord/Slack bot integrations (if they call the API)

### Impact

- All existing API sessions using the old key will immediately stop working
- Web UI sessions (cookie-based) are not affected unless `DASHBOARD_SESSION_SECRET` also changes
- There is a brief downtime during container restart (~30 seconds)

---

## Dashboard Read Key

### Procedure

Same as admin key rotation:

```bash
# Generate new key
python -c "import secrets; print(secrets.token_urlsafe(32))"

# Update .env
DASHBOARD_READ_KEY=new_key_here

# Restart
docker compose restart trading-bot
```

Update any read-only monitoring clients.

---

## Dashboard Session Secret

### When to Rotate
- This invalidates ALL active web sessions
- Only rotate if you suspect the secret is compromised

### Procedure

1. **Generate new secret:**
   ```bash
   python -c "import secrets; print(secrets.token_urlsafe(48))"
   ```

2. **Update `.env`:**
   ```bash
   DASHBOARD_SESSION_SECRET=new_secret_here
   ```

3. **Restart:**
   ```bash
   docker compose restart trading-bot
   ```

4. **Impact:** All logged-in web users must re-authenticate.

---

## Dashboard Admin Password

### Procedure

1. **Generate new bcrypt hash:**
   ```bash
   python -c "import bcrypt; print(bcrypt.hashpw(b'new_password_here', bcrypt.gensalt()).decode())"
   ```

2. **Update `.env`:**
   ```bash
   DASHBOARD_ADMIN_PASSWORD_HASH=$2b$12$new_hash_here
   ```

3. **Restart:**
   ```bash
   docker compose restart trading-bot
   ```

---

## Telegram Bot Token

### When to Rotate
- If the token appears in logs (auto-scrubbed, but check)
- After suspected exposure

### Procedure

1. **Create new bot** via @BotFather on Telegram (or regenerate token for existing bot)
2. **Update `.env`:**
   ```bash
   TELEGRAM_BOT_TOKEN=new_token_here
   ```
3. **Restart:**
   ```bash
   docker compose restart trading-bot
   ```
4. **Important:** If you created a new bot, update chat commands with @BotFather

---

## Discord Bot Token

### Procedure

1. **Regenerate token** in Discord Developer Portal > Bot > Reset Token
2. **Update `.env`:**
   ```bash
   DISCORD_TOKEN=new_token_here
   ```
3. **Restart:**
   ```bash
   docker compose restart trading-bot
   ```

---

## Slack Bot Tokens

### Procedure

Slack uses multiple tokens:

1. **Regenerate tokens** in Slack app settings (https://api.slack.com/apps)
2. **Update `.env`:**
   ```bash
   SLACK_BOT_TOKEN=xoxb-new-token
   SLACK_SIGNING_SECRET=new_signing_secret
   SLACK_APP_TOKEN=xapp-new-token    # if using Socket Mode
   ```
3. **Restart:**
   ```bash
   docker compose restart trading-bot
   ```

---

## Stripe Credentials

### When to Rotate
- Stripe secret key rotation (e.g., switching from test to live)
- Webhook secret rotation

### Procedure

1. **Generate new webhook secret** in Stripe Dashboard > Webhooks > Signing secret
2. **Update `.env`:**
   ```bash
   STRIPE_SECRET_KEY=sk_live_new_key
   STRIPE_WEBHOOK_SECRET=whsec_new_secret
   ```
3. **Restart:**
   ```bash
   docker compose restart trading-bot
   ```
4. **Important:** The old webhook secret will immediately stop validating incoming webhooks. Update the Stripe webhook endpoint if needed.

---

## Elasticsearch API Key

### Procedure

1. **Create new API key** via Kibana or ES API:
   ```bash
   curl -X POST "localhost:9200/_security/api_key" -H "Content-Type: application/json" -d '{
     "name": "novapulse-bot",
     "role_descriptors": {
       "novapulse_writer": {
         "index": [{"names": ["novapulse-*"], "privileges": ["write", "create_index", "manage"]}]
       }
     }
   }'
   ```

2. **Update `.env`:**
   ```bash
   ES_API_KEY=new_base64_encoded_key
   ```

3. **Restart:**
   ```bash
   docker compose restart trading-bot
   ```

---

## Tenant API Keys

### Procedure

Tenant API keys are managed in the database, not in `.env`:

1. **Generate new key:**
   ```bash
   python -c "import secrets; print(secrets.token_urlsafe(32))"
   ```

2. **Insert hashed key into DB:**
   ```bash
   docker exec novapulse python -c "
   import asyncio, hashlib
   from src.core.database import DatabaseManager
   async def main():
       db = DatabaseManager('/app/data/trading.db')
       await db.initialize()
       key = 'the_new_key_value'
       key_hash = hashlib.sha256(key.encode()).hexdigest()
       async with db._timed_lock():
           await db._db.execute(
               'INSERT INTO tenant_api_keys (tenant_id, key_hash, label) VALUES (?, ?, ?)',
               ('tenant_id_here', key_hash, 'Rotated 2026-02-22')
           )
           await db._db.commit()
       print('Key inserted')
   asyncio.run(main())
   "
   ```

3. **Distribute new key** to the tenant.

4. **Delete old key** after confirming the tenant is using the new one:
   ```sql
   DELETE FROM tenant_api_keys WHERE id = <old_key_id>;
   ```

No restart is needed -- tenant key lookup is done on every request.

---

## External Data API Keys

### CoinGecko API Key

```bash
COINGECKO_API_KEY=new_key
docker compose restart trading-bot
```

### CryptoPanic API Key

```bash
CRYPTOPANIC_API_KEY=new_key
docker compose restart trading-bot
```

### Polygon API Key (Stocks)

```bash
POLYGON_API_KEY=new_key
docker compose restart trading-bot
```

### Alpaca API Keys (Stocks)

```bash
ALPACA_API_KEY=new_key
ALPACA_API_SECRET=new_secret
docker compose restart trading-bot
```

---

## Rotation Checklist

| Credential | Where Stored | Restart Required | Impact |
|------------|-------------|-----------------|--------|
| Kraken API Key | .env | Yes | Brief trading pause |
| Coinbase API Key | .env | Yes | Brief trading pause |
| Dashboard Admin Key | .env | Yes | All admin API sessions invalidated |
| Dashboard Read Key | .env | Yes | All read-only API sessions invalidated |
| Dashboard Session Secret | .env | Yes | All web sessions invalidated |
| Dashboard Password | .env | Yes | Must use new password to log in |
| Telegram Bot Token | .env | Yes | Telegram bot reconnects |
| Discord Bot Token | .env | Yes | Discord bot reconnects |
| Slack Bot Tokens | .env | Yes | Slack bot reconnects |
| Stripe Secret Key | .env | Yes | Billing operations use new key |
| Stripe Webhook Secret | .env | Yes | Old webhooks stop validating |
| ES API Key | .env | Yes | ES pipeline reconnects |
| Tenant API Key | Database | No | Immediate effect |
| CoinGecko/CryptoPanic | .env | Yes | Data collection reconnects |
| Alpaca/Polygon | .env | Yes | Stock operations reconnect |

---

## Emergency Key Revocation

If a credential is compromised and needs immediate revocation:

1. **Exchange API keys:** Disable on the exchange website immediately (do not wait for bot restart)
2. **Dashboard keys:** Change in `.env` and restart immediately
3. **Bot tokens:** Regenerate in the respective platform (Telegram @BotFather, Discord Dev Portal, Slack App Settings)
4. **Stripe:** Roll the secret key in Stripe Dashboard

In all cases, the bot will be temporarily unable to operate the affected component until the new credentials are in place and the container is restarted.

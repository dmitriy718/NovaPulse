# Security and Privacy

**Last updated:** 2026-02-22

Your security is a top priority for NovaPulse. This guide explains how your data, API keys, and access are protected.

---

## Exchange API Key Security

### How Your Keys Are Stored

- Your exchange API keys are stored **encrypted on our servers** using industry-standard encryption.
- Keys are never stored in plain text.
- Keys are never exposed in logs, dashboard views, or API responses.
- Only the NovaPulse trading engine has access to the decrypted keys at runtime.

### What NovaPulse Can Do With Your Keys

When you set up API keys with the recommended permissions, NovaPulse can:

- **View your balances** -- to calculate position sizes and exposure
- **Place orders** -- to execute trades (buy, sell, set stop losses)
- **Cancel orders** -- to manage and adjust existing orders
- **View order history** -- to track trade results

### What NovaPulse Cannot Do

With properly configured API keys (following the [Getting Started](Getting-Started.md) instructions):

- **Cannot withdraw funds** -- withdrawal permission is not enabled
- **Cannot transfer funds** between accounts
- **Cannot access other exchange features** (staking, lending, etc.)
- **Cannot change your exchange account settings**

> **Important:** When generating API keys, always ensure that withdrawal permissions are **disabled**. This is your primary protection -- even in the worst-case scenario, your funds cannot be moved off the exchange.

---

## Dashboard Authentication

### Login Security

- **Username and password** authentication for the web dashboard
- **Session-based login** with secure, signed session cookies
- Sessions expire after **12 hours** by default -- you will need to log in again
- In live mode, passwords are stored as **secure hashes** (never plain text)

### CSRF Protection

- The dashboard uses **CSRF (Cross-Site Request Forgery) tokens** to prevent unauthorized actions
- Every state-changing request (pause, resume, close all, kill) includes a CSRF token
- This prevents malicious websites from tricking your browser into executing commands

### API Key Authentication

For programmatic access (and for notification bots), NovaPulse uses API keys:

| Key Type | What It Can Do |
|----------|---------------|
| **Admin Key** | Full access: read data AND control the bot (pause, resume, close all) |
| **Read Key** | Read-only access: view data but cannot control the bot |
| **Tenant API Key** | Per-subscription access: read data, optionally control (based on plan) |

- API keys are passed via the `X-API-Key` header
- Admin keys are required for all control operations by default
- Keys are never logged or exposed in API responses

---

## Rate Limiting

NovaPulse protects against abuse and brute-force attacks with rate limiting:

- **Dashboard API:** 240 requests per minute per client (with burst allowance of 60)
- **Login endpoint:** Protected against brute-force attempts
- **Control endpoints:** Rate-limited to prevent rapid-fire commands

If you are rate-limited, you will receive a `429 Too Many Requests` response. Wait a moment and try again.

---

## Multi-Tenant Isolation

If you are using NovaPulse in a shared or multi-tenant environment:

- **Your data is isolated** from other tenants. You cannot see or access another tenant's trades, positions, or configuration.
- **Tenant API keys are pinned** to your specific tenant ID. A tenant key cannot access data from a different tenant.
- **Billing and subscription status** are tracked per tenant. An inactive subscription blocks access.

---

## What Data NovaPulse Collects

NovaPulse collects and stores the following data to operate the trading system:

| Data Type | Why It Is Collected | Retention |
|-----------|-------------------|-----------|
| **Trade records** | Track performance, calculate metrics, manage positions | Indefinite (your trading history) |
| **Market data** | Run trading strategies, calculate indicators | 90 days (candles), 30 days (order book) |
| **AI thought log** | Debugging, transparency, support troubleshooting | 200 most recent entries |
| **System logs** | Monitor health, diagnose issues, track errors | 72 hours |
| **Configuration** | Run the bot with your settings | Until you change it |
| **Session tokens** | Maintain your dashboard login | 12 hours |

### What NovaPulse Does NOT Collect

- Your exchange account password
- Your exchange withdrawal credentials
- Personal information beyond what is needed for account management
- Browsing history or activity outside the NovaPulse dashboard
- Data from other applications on your device

---

## How to Revoke Access

If you want to stop NovaPulse from accessing your exchange account:

### Immediate (Exchange-Side)

1. Log in to your exchange (Kraken or Coinbase).
2. Go to API settings.
3. **Delete or disable** the API key used by NovaPulse.
4. This takes effect immediately -- NovaPulse will no longer be able to view balances or place orders.

> **Important:** If you have open positions, use the **Close All** or **Kill** command before revoking API keys. Otherwise, your positions will remain open without NovaPulse managing them.

### NovaPulse-Side

1. Contact support to deactivate your NovaPulse account.
2. Your configuration and stored keys will be deleted.
3. Your trade history can be exported before deletion upon request.

---

## Security Best Practices

1. **Use strong, unique passwords** for both your exchange account and NovaPulse dashboard.
2. **Enable two-factor authentication (2FA)** on your exchange account.
3. **Never share your API keys** in chat messages, emails, or support tickets (support will never ask for your full secret key).
4. **Never enable withdrawal permissions** on API keys used by NovaPulse.
5. **Regularly review** your exchange API key list and remove any keys you no longer use.
6. **Use a password manager** to store your API keys and credentials securely.
7. **Log out of the dashboard** when using a shared or public computer.
8. **Monitor your exchange account** directly for any unexpected activity.

---

## Reporting Security Concerns

If you suspect any security issue -- unauthorized access, unexpected trades, or suspicious activity:

1. **Immediately press Kill** on the dashboard or send `/kill` via Telegram.
2. **Revoke your exchange API keys** directly on the exchange.
3. **Contact NovaPulse support immediately** with details of what you observed.
4. **Change your passwords** for both NovaPulse and your exchange account.

We take security reports seriously and will investigate promptly.

---

*For emergency controls, see [Controls](Controls-Pause-Resume-Kill.md).*
*For general support, see [Contact Support](Contact-Support.md).*

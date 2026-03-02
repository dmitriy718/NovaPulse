# Security and Privacy

**Last updated:** 2026-03-02

Your security is a top priority for Nova|Pulse by Horizon Services. This guide explains how your account, data, API keys, and access are protected across both the NovaPulse trading bot and the Horizon web platform.

---

## Account Security (Horizon Platform)

### Authentication

Nova by Horizon uses **Google Firebase Authentication** for all account management:

- Your password is never stored on our servers -- Firebase handles all credential storage and hashing
- Password hashing uses industry-standard bcrypt via Firebase
- Session tokens are Firebase ID tokens (JWT format) verified server-side on every request

### Sign-In Methods

Two sign-in methods are supported:
1. **Email and Password**: Create an account with your email and a strong password
2. **Google SSO**: Sign in with your Google account for one-click authentication

### Email Verification

Email verification is required before you can access the trading dashboard, subscribe to a plan, use the Pro scanner, or submit authenticated support tickets. Verification emails are sent from `support@horizonsvc.com`.

### Failed Login Detection

The system monitors failed login attempts and takes protective action:

| Failed Attempts (30 min) | Action |
|---|---|
| 1 | No action |
| 2 | Warning email sent to account owner |
| 3+ | Account temporarily locked for 30 minutes |

When locked, you receive an email notification from `security@horizonsvc.com`. The lock expires automatically -- you can try logging in again after 30 minutes.

### Security Notifications

When security-relevant events occur, you receive email notifications that **cannot be disabled**:
- **Password Changed**: Includes IP address and timestamp
- **Failed Login Warning**: After 2 failures, includes attempt count and IP
- **Account Locked**: Includes IP address and timestamp
- **Personal Info Changed**: When profile name is updated, includes changed fields and IP

---

## Exchange API Key Security

### Key Permissions

When you create API keys for your exchange, we recommend enabling only the minimum necessary permissions:
- **View** (balances, orders, trades) -- Required
- **Trade** (place and cancel orders) -- Required
- **Withdraw** -- **Never enable this.** Nova|Pulse does not need withdrawal access.

With these permissions, even if your API keys were compromised, an attacker could not withdraw funds from your exchange account.

### Key Storage

API keys are never stored in plain text:

- **Horizon-managed deployments:** Keys are stored in `.secrets/env`, a file volume-mounted into the Docker container. This file is not part of the codebase, not in version control, and not accessible via the API.
- **Self-hosted deployments:** You manage your own `.secrets/env` file. Follow the same practices: keep it outside version control, restrict file permissions, and never commit it to Git.
- **Horizon web platform:** Bot connection API keys (for dashboard proxy access) are stored in the `bot_connections` database table, transmitted only over TLS.

### SSRF Protection

When you connect a bot URL through the Horizon dashboard, the system prevents Server-Side Request Forgery (SSRF) attacks:
- Only HTTP and HTTPS protocols are allowed
- Private/internal IP addresses are blocked (127.0.0.1, 10.x.x.x, 172.16-31.x.x, 192.168.x.x, localhost)
- DNS resolution is checked to prevent DNS rebinding attacks
- Redirects are never followed on bot proxy requests

---

## Bot Dashboard Security

### API Key Authentication

The NovaPulse bot dashboard uses API key authentication:

| Key Type | Access Level |
|---|---|
| Admin Key | Full control + all read endpoints |
| Read Key | Data endpoints only |

Keys are sent in the `X-API-Key` header. They are stored in `.secrets/env` (never in the config file or version control).

### Login Protection

- Passwords are hashed with bcrypt (never stored in plain text)
- After 5 failed login attempts in 5 minutes, the account locks temporarily (brute-force protection)
- CSRF protection is enabled on all form submissions

### Dashboard Access

- The bot dashboard runs on port 8080 inside the container (mapped to 8090 on the host by default)
- For managed deployments, access is through a Caddy reverse proxy with HTTPS
- Rate limiting prevents API abuse

---

## Data Protection

### Data in Transit

- All traffic between your browser and both dashboards is encrypted via TLS 1.2+
- HTTPS is enforced site-wide with HTTP to HTTPS redirects
- HSTS (HTTP Strict Transport Security) is enabled with a 2-year max-age

### Content Security Policy

The Horizon platform enforces a strict Content Security Policy (CSP):
- Only resources from approved origins can be loaded
- `frame-ancestors 'none'` prevents the site from being embedded in iframes (clickjacking protection)
- Additional headers: X-Content-Type-Options: nosniff, X-Frame-Options: DENY

### Data at Rest

- **NovaPulse bot**: All trade data, logs, and metrics are stored in SQLite with WAL mode on the bot server
- **Horizon platform**: User accounts, subscriptions, and bot connections are stored in PostgreSQL
- Both systems use parameterized queries to prevent SQL injection

---

## API Security

### Horizon Platform API

- Firebase tokens are verified server-side on every authenticated request
- Global rate limit: 120 requests per minute per IP
- Per-endpoint rate limits for login attempts, newsletter subscriptions, and contact forms
- CORS restricts allowed origins to horizonsvc.com and localhost (development)
- All inputs are validated using Zod schemas

### NovaPulse Bot API

- X-API-Key header authentication on all endpoints
- CORS restricted to configured origins
- Rate limiting on sensitive endpoints

---

## Privacy Practices

### What Data We Collect

- **Account information**: Name, email, age, zip code (optional: address)
- **Authentication data**: Firebase UID, login timestamps, IP addresses (for security)
- **Subscription data**: Plan type, billing period (payment details handled entirely by Stripe)
- **Bot connection data**: Bot URL, API key (for dashboard proxy)
- **Trading data**: Proxied from your bot for dashboard display (not stored long-term on Horizon servers)
- **Email logs**: Template sent, timestamp, recipient (for deduplication and audit)

### What We Do NOT Collect

- Exchange credentials with withdrawal permissions
- Actual trade execution data on Horizon servers (this stays on your bot/exchange)
- Payment card numbers (handled entirely by Stripe)
- Browser fingerprints
- Location data beyond zip code

### Data Retention

- Account data is retained until account deletion
- Login attempts are retained for security review
- Email logs are retained for deduplication and audit
- Bot connection data is retained while the account is active
- Trade history on the bot is retained until stats are zeroed (user-initiated)

### Third-Party Services

| Service | Purpose |
|---|---|
| Firebase (Google) | Authentication and email verification |
| Stripe | Payment processing |
| PostHog | Product analytics (optional) |
| SMTP (SiteProtect) | Email delivery |

---

## Email Security

### Unsubscribe Token Security

Email unsubscribe links use HMAC-signed stateless tokens:
- Tokens are signed with HMAC-SHA256
- Tokens expire after 90 days
- Token verification uses timing-safe comparison to prevent timing attacks
- Security notification emails (password changes, failed logins, lockouts, profile changes) **cannot be unsubscribed** -- this is enforced at every level

### Email Sender Addresses

| Category | From Address |
|---|---|
| Support | support@horizonsvc.com |
| Trading Alerts | alerts@horizonsvc.com |
| Marketing | marketing@horizonsvc.com |
| Security | security@horizonsvc.com |

---

## Cookie Policy

The Horizon platform uses cookies for:
- Firebase authentication session management
- PostHog analytics (if enabled)
- Cookie consent preferences

A cookie banner is displayed to new visitors. The full cookie policy is available at [horizonsvc.com/cookies](https://horizonsvc.com/cookies).

---

## Legal Pages

- [Privacy Policy](https://horizonsvc.com/privacy)
- [Terms of Service](https://horizonsvc.com/terms)
- [Cookie Policy](https://horizonsvc.com/cookies)
- [Trust and Safety](https://horizonsvc.com/trust-safety)
- [Email Security (DMARC)](https://horizonsvc.com/dmarc)

---

## Best Practices for Users

1. **Never enable withdrawal permissions** on your exchange API keys
2. **Use a strong, unique password** for your Horizon account
3. **Enable 2FA on your exchange accounts** (Kraken, Coinbase, Alpaca)
4. **Use Google SSO** if you prefer not to manage another password
5. **Restrict API keys by IP** on your exchange if you have a static server IP
6. **Verify the URL** when logging in -- always use `horizonsvc.com` or your known bot URL
7. **Report suspicious activity** immediately to support@horizonsvc.com

---

*Nova|Pulse v5.0.0 by Horizon Services -- Your security is our foundation.*

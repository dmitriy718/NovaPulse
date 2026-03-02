# Notifications

Nova by Horizon sends email notifications for trading alerts, security events, performance reports, and marketing communications. You have granular control over which notifications you receive.

---

## Notification Categories

Notifications are organized into four categories, each with individual toggle-able subcategories.

### 1. Account Security (Cannot Be Disabled)

Security notifications are always sent regardless of preferences. These protect your account:

| Notification | Description |
|---|---|
| **Password Changed** | Sent when your password is changed |
| **Failed Login** | Warning after 2 failed login attempts in 30 minutes |
| **Account Locked** | Notification when your account is temporarily locked after 3+ failed login attempts |
| **Personal Info Changed** | Sent when your profile name is updated, includes IP address and timestamp |

These notifications cannot be disabled via preferences or global unsubscribe. This is enforced both on the API (400 error if attempted) and on the unsubscribe endpoint.

### 2. Trading Alerts

Real-time notifications about your bot's trading activity and risk thresholds:

| Notification | Default | Description |
|---|---|---|
| **Daily Loss Limit** | On | Tiered alerts (25%, 10%, triggered) when daily losses approach the configured limit |
| **Max Exposure** | On | Tiered alerts when total position exposure approaches the maximum |
| **Risk of Ruin** | On | Warning when the risk of ruin metric exceeds the threshold |
| **Consecutive Losses** | On | Alert when consecutive losing trades approach the pause threshold |
| **Anomaly Circuit Breaker** | On | Notification when the anomaly detector triggers a trading pause |
| **Macro Event Blackout** | On | Alert when FOMC, CPI, or NFP events trigger a trading blackout |
| **Trade Executed** | Off | Notification for every trade opened |
| **Trade Closed** | Off | Notification for every trade closed |

Note: Trade Executed and Trade Closed are disabled by default to avoid notification fatigue, since the bot may execute many trades per day.

### 3. Performance Reports

Scheduled summary reports delivered on a regular cadence:

| Report | Default | Frequency | Delivery Time |
|---|---|---|---|
| **Daily Summary** | On | Every day | 00:00 UTC |
| **Weekly Digest** | On | Every Sunday | 00:00 UTC |
| **Monthly Report** | On | 1st of each month | 00:00 UTC |
| **Milestone Achievements** | On | On achievement unlock | Immediate |

Reports include:
- P&L (dollar and percentage)
- Total trades and win rate
- Best/worst trade details
- Max drawdown
- Strategy breakdown (monthly)
- Sharpe ratio (monthly)
- Comparison to previous period (weekly)

### 4. Marketing

Promotional and engagement communications:

| Notification | Default | Description |
|---|---|---|
| **Newsletter** | On | Regular newsletter updates |
| **Feature Announcements** | On | New features and platform updates |
| **Inactivity Reminders** | On | Re-engagement emails if you have not logged in recently |

---

## Managing Preferences

### Via Dashboard Settings

1. Go to [horizonsvc.com/settings](https://horizonsvc.com/settings)
2. Click the **Notifications** tab
3. Toggle individual notification types on/off
4. Click **Save Preferences**

Changes take effect immediately. The next time a notification would be sent, the system checks your current preference and respects it.

### Global Unsubscribe

You can set a global unsubscribe flag that disables ALL non-security emails. This is available:
- In Settings > Notifications
- Via the unsubscribe link in any email (choosing "All Non-Security Emails")

When global unsubscribe is active:
- All trading alerts, performance reports, and marketing emails are suppressed
- Security notifications (password changed, failed login, account locked, personal info changed) continue to be sent
- You can re-enable notifications at any time in Settings

### Via Email Unsubscribe Links

Every non-security email contains an unsubscribe link in the footer. Clicking it:
1. Takes you to a branded unsubscribe confirmation page
2. Disables the entire notification category (e.g., all Trading Alerts, all Performance Reports, or all Marketing emails)
3. You can re-enable individual subcategories in Settings

The unsubscribe mechanism uses HMAC-signed stateless tokens:
- Tokens are valid for 90 days
- Each token is signed with the platform's JWT signing key
- Timing-safe comparison prevents token forgery
- The token contains the user ID and category to disable

---

## Alert Tiers

Trading alerts use a tiered system based on how close a metric is to its limit:

| Tier | Condition | Email Subject Prefix |
|---|---|---|
| **warn25** | Within 25% of limit | "Alert:" |
| **warn10** | Within 10% of limit | "Alert:" |
| **triggered** | Limit reached or exceeded | "FAILSAFE:" |

### Deduplication

To prevent notification fatigue:
- The same alert (same user + same alert type) is not re-sent within a 4-hour cooldown window
- Alerts escalate immediately (warn25 -> warn10 -> triggered) without waiting for cooldown
- De-escalation or repeated same-tier alerts respect the 4-hour cooldown
- Alert history survives process restarts by loading recent entries from the `email_log` database table

---

## Email Senders

Different notification categories are sent from different email addresses:

| Category | From Address |
|---|---|
| Support (verification, welcome, tickets) | support@horizonsvc.com |
| Trading Alerts | alerts@horizonsvc.com |
| Marketing | marketing@horizonsvc.com |
| Security | security@horizonsvc.com |

All emails include:
- Branded HTML templates with the Nova by Horizon design
- List-Unsubscribe header for one-click unsubscribe in email clients
- Footer with unsubscribe link (except security emails)
- Note that security notifications always state "You will still receive important security alerts related to your account."

---

## Email Templates

The platform uses a comprehensive template library for all email types:

**Account Lifecycle:**
- Email verification link
- Welcome email (after verification)
- Account deactivation notice

**Bot Setup:**
- Bot setup started
- Bot setup complete (with dashboard link)

**Trading Alerts:**
- Daily loss limit approaching/triggered
- Max exposure approaching/triggered
- Risk of ruin warning
- Consecutive losses alert
- Anomaly circuit breaker activated
- Macro event blackout notification
- Trade executed notification
- Trade closed notification

**Performance Reports:**
- Daily summary with P&L, trades, and metrics
- Weekly digest with week-over-week comparison
- Monthly report with Sharpe ratio and strategy breakdown

**Engagement:**
- Milestone achievement unlocked
- Newsletter
- Feature announcement
- Inactivity re-engagement

---

## Newsletter Subscription

The footer of the website and a popup include newsletter subscription forms. Newsletter subscriptions are separate from account notification preferences:

- Available lists: Stock Alerts, Weekly Newsletter, Product Updates
- Public endpoint (no authentication required)
- Rate limited to 3 subscriptions per minute per IP
- Stored in the `newsletter_subscribers` table
- Sources tracked (website footer, popup, etc.)

---

## Preference Storage

Preferences are stored as JSONB in the `users` table. The system uses a deep-merge approach:
1. Default preferences define all available toggles (all enabled except trade_executed and trade_closed)
2. User-stored preferences override specific values
3. On read, defaults are merged with stored values so new notification types are automatically enabled
4. The timezone field (default: America/New_York) can be used for scheduling reports in the user's local time

---

*Last updated: March 2026*

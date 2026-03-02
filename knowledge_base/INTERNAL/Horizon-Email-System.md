# Email System

This document covers the complete email infrastructure in HorizonAlerts, including SMTP configuration, the template system, preference checking, the unsubscribe mechanism, and the bot monitor.

---

## Architecture Overview

```
Email Trigger (API route / Bot Monitor / Scheduled Report)
  |
  v
sendEmail() in services/email.ts
  |
  v
[1] Resolve preference key from template name
[2] Check if security email (skip preference check)
[3] Check user preference (if applicable)
[4] Skip if preference disabled (log as :skipped)
[5] Build unsubscribe URL (HMAC-signed token)
[6] Render template to HTML
[7] Select SMTP transporter by email type
[8] Send via Nodemailer
[9] Log to email_log table
```

---

## SMTP Configuration

### Four Mailboxes

The system uses four separate SMTP accounts, one per email category:

| Type | From Address | Env Vars |
|---|---|---|
| `support` | support@horizonsvc.com | `SMTP_SUPPORT_USER`, `SMTP_SUPPORT_PASS`, `SMTP_SUPPORT_FROM` |
| `alerts` | alerts@horizonsvc.com | `SMTP_ALERTS_USER`, `SMTP_ALERTS_PASS`, `SMTP_ALERTS_FROM` |
| `marketing` | marketing@horizonsvc.com | `SMTP_MARKETING_USER`, `SMTP_MARKETING_PASS`, `SMTP_MARKETING_FROM` |
| `security` | security@horizonsvc.com | `SMTP_SECURITY_USER`, `SMTP_SECURITY_PASS`, `SMTP_SECURITY_FROM` |

### SMTP Server Configuration

| Variable | Default | Description |
|---|---|---|
| `SMTP_HOST` | smtp.siteprotect.com | SMTP server hostname |
| `SMTP_PORT` | 587 | SMTP port (STARTTLS) |

### Transporter Caching

SMTP transporters are created lazily and cached in a Map:
```typescript
const transporterCache = new Map<EmailType, ReturnType<typeof nodemailer.createTransport>>();
```

If credentials are missing for a type, `getTransporter()` returns null and the email is silently not sent.

---

## Email Templates

### Template Library

The template system is in `services/api/src/services/email-templates/`. Templates are organized by category:

| Category | Templates |
|---|---|
| Account Lifecycle | `verifyEmail`, `welcomeEmail`, `accountDeactivated` |
| Bot Setup | `botSetupStarted`, `botSetupComplete` |
| Security | `passwordChanged`, `failedLoginWarning`, `accountLocked`, `personalInfoChanged` |
| Trading Alerts | `dailyLossAlert`, `maxExposureAlert`, `riskOfRuinAlert`, `consecutiveLossAlert`, `anomalyAlert`, `macroEventAlert`, `tradeExecuted`, `tradeClosed` |
| Performance Reports | `dailySummary`, `weeklyDigest`, `monthlyReport`, `milestoneAchieved` |
| Marketing | `newsletter`, `featureAnnouncement`, `inactivityReengagement` |
| Legacy | `contact`, `ticket`, `security` (inline HTML) |

### Template Function Signature

Each template function returns an HTML string:
```typescript
function dailyLossAlert(data: any, unsub?: string): string {
  // Returns branded HTML email
}
```

The optional `unsub` parameter is the unsubscribe URL. It is included in all non-security emails.

### Base Layout

Templates share a common layout via `base-layout.ts` that provides:
- Branded header with Nova by Horizon logo
- Consistent color scheme (slate-950 background, cyan accents)
- Footer with unsubscribe link (when applicable)
- Legal disclaimer
- Mobile-responsive design

---

## sendEmail() Function

### Interface

```typescript
interface SendOptions {
  to: string;                     // Recipient email
  type: EmailType;                // 'support' | 'alerts' | 'marketing' | 'security'
  subject: string;                // Email subject line
  html?: string;                  // Custom HTML (used if no template)
  template?: TemplateName;        // Template to render
  data?: any;                     // Template data
  attachments?: any[];            // File attachments
  userId?: string;                // User UID for preference checking
  preferenceKey?: string;         // Override preference key
  skipPreferenceCheck?: boolean;  // Skip preference check (security emails)
}
```

### Processing Pipeline

1. **Get transporter**: Look up SMTP transporter for the email type. If missing credentials, return early.

2. **Resolve preference key**: Either use the explicit `preferenceKey` or auto-map from template name:
   ```typescript
   const map: Record<string, string> = {
     passwordChanged: "account_security.password_changed",
     dailyLoss: "trading_alerts.daily_loss_limit",
     newsletter: "marketing.newsletter",
     // ... etc
   };
   ```

3. **Check if security email**: Security emails bypass preference checks. Determined by:
   - `skipPreferenceCheck = true`
   - Preference key is in `SECURITY_KEYS` set

4. **Preference check**: For non-security emails with a userId and preference key:
   - Fetch user preferences from DB
   - Merge with defaults (`mergePreferences()`)
   - Check if the specific preference is enabled (`isPreferenceEnabled()`)
   - If disabled: log as `:skipped` in email_log and return

5. **Build unsubscribe URL**: For non-security emails with a userId:
   - Extract category from preference key (first segment)
   - Generate HMAC-signed token with 90-day expiry
   - Build full URL: `{BASE}/api/unsubscribe?token={token}`

6. **Render template**: Switch on template name, call the corresponding template function

7. **Set from address**: Based on email type

8. **Set headers**: Add `List-Unsubscribe` and `List-Unsubscribe-Post` headers for one-click unsubscribe

9. **Send via Nodemailer**: `transporter.sendMail({ from, to, subject, html, attachments, headers })`

10. **Log**: Insert into `email_log` table (non-critical, errors swallowed)

---

## Preference System

### Default Preferences

```typescript
export const DEFAULT_PREFERENCES: NotificationPreferences = {
  notifications: {
    account_security: {
      password_changed: { email: true },
      failed_login: { email: true },
      account_locked: { email: true },
      personal_info_changed: { email: true },
    },
    trading_alerts: {
      daily_loss_limit: { email: true },
      max_exposure: { email: true },
      risk_of_ruin: { email: true },
      consecutive_losses: { email: true },
      anomaly_circuit_breaker: { email: true },
      macro_event_blackout: { email: true },
      trade_executed: { email: false },      // High frequency, off by default
      trade_closed: { email: false },        // High frequency, off by default
    },
    performance_reports: {
      daily_summary: { email: true },
      weekly_digest: { email: true },
      monthly_report: { email: true },
      milestone_achievements: { email: true },
    },
    marketing: {
      newsletter: { email: true },
      feature_announcements: { email: true },
      inactivity_reminders: { email: true },
    },
  },
  global_unsubscribe: false,
  timezone: "America/New_York",
};
```

### Merge Logic

`mergePreferences(stored)` deep-merges the user's stored preferences with defaults:
- New keys added to defaults are automatically available with default values
- User-stored values override defaults
- Missing stored values fall back to defaults

### Preference Checking

```typescript
function isPreferenceEnabled(prefs: NotificationPreferences, preferenceKey: string): boolean {
  // Security notifications always enabled
  if (SECURITY_KEYS.has(preferenceKey)) return true;
  // Global unsubscribe blocks everything else
  if (prefs.global_unsubscribe) return false;
  // Check specific preference
  const [category, key] = preferenceKey.split(".");
  return prefs.notifications[category]?.[key]?.email !== false;
}
```

### Security Keys (Cannot Be Disabled)

```typescript
export const SECURITY_KEYS = new Set([
  "account_security.password_changed",
  "account_security.failed_login",
  "account_security.account_locked",
  "account_security.personal_info_changed",
]);
```

### Update Validation

The `PUT /me/preferences` endpoint:
1. Validates input against a strict Zod schema
2. Rejects attempts to disable security preferences (returns 400)
3. Deep-merges the update with existing preferences
4. Saves the merged result back to the users table

---

## Unsubscribe System

### Token Generation

```typescript
function generateUnsubscribeToken(uid: string, category: string): string {
  const payload = { uid, category, exp: now + 90_days };
  const data = Buffer.from(JSON.stringify(payload)).toString("base64url");
  const sig = crypto.createHmac("sha256", SECRET).update(data).digest("base64url");
  return `${data}.${sig}`;
}
```

### Token Verification

```typescript
function verifyUnsubscribeToken(token: string): UnsubscribePayload | null {
  const [data, sig] = token.split(".");
  const expected = crypto.createHmac("sha256", SECRET).update(data).digest("base64url");
  // Timing-safe comparison with length pre-check
  const sigBuf = Buffer.from(sig, "base64url");
  const expectedBuf = Buffer.from(expected, "base64url");
  if (sigBuf.length !== expectedBuf.length) return null;
  if (!crypto.timingSafeEqual(sigBuf, expectedBuf)) return null;
  // Parse and check expiry
  const payload = JSON.parse(Buffer.from(data, "base64url").toString("utf8"));
  if (payload.exp < now) return null;
  return payload;
}
```

### Unsubscribe Endpoint

`GET /unsubscribe?token=xxx` (public, no auth):
1. Verify HMAC token
2. Fetch user preferences
3. If category == "all": set `global_unsubscribe = true`
4. If category == "account_security": reject (cannot disable)
5. Otherwise: set all email toggles in the category to false
6. Save updated preferences
7. Return branded HTML confirmation page

### Email Headers

Every non-security email includes:
```
List-Unsubscribe: <unsubscribe_url>
List-Unsubscribe-Post: List-Unsubscribe=One-Click
```

These headers enable one-click unsubscribe in email clients that support RFC 8058.

---

## Bot Monitor

See [Bot Integration](Bot-Integration.md) for the full bot monitor documentation.

Summary:
- Runs every 60 seconds inside the API process
- Polls all active bot connections for risk data
- Sends tiered alerts (warn25, warn10, triggered) with 4-hour dedup
- Handles daily/weekly/monthly report scheduling
- Loads alert history from email_log on startup to survive restarts

---

## Email Log Table

```sql
CREATE TABLE email_log (
  id        BIGSERIAL PRIMARY KEY,
  uid       TEXT NOT NULL,           -- User UID or 'system'
  template  TEXT NOT NULL,           -- Template name; ':skipped' suffix if preference-blocked
  subject   TEXT NOT NULL,
  sent_at   TIMESTAMPTZ DEFAULT now(),
  to_addr   TEXT NOT NULL
);
```

Used for:
- Audit trail of all sent/skipped emails
- Bot monitor dedup history (loaded on startup)
- Debugging email delivery issues

---

## Environment Variables Summary

| Variable | Required | Description |
|---|---|---|
| `SMTP_HOST` | No (default: smtp.siteprotect.com) | SMTP server hostname |
| `SMTP_PORT` | No (default: 587) | SMTP port |
| `SMTP_SUPPORT_USER` | Yes | Support mailbox username |
| `SMTP_SUPPORT_PASS` | Yes | Support mailbox password |
| `SMTP_SUPPORT_FROM` | No | Support from address |
| `SMTP_ALERTS_USER` | Yes | Alerts mailbox username |
| `SMTP_ALERTS_PASS` | Yes | Alerts mailbox password |
| `SMTP_ALERTS_FROM` | No | Alerts from address |
| `SMTP_MARKETING_USER` | Yes | Marketing mailbox username |
| `SMTP_MARKETING_PASS` | Yes | Marketing mailbox password |
| `SMTP_MARKETING_FROM` | No | Marketing from address |
| `SMTP_SECURITY_USER` | Yes | Security mailbox username |
| `SMTP_SECURITY_PASS` | Yes | Security mailbox password |
| `SMTP_SECURITY_FROM` | No | Security from address |
| `JWT_SIGNING_KEY` | Yes | Used as HMAC secret for unsubscribe tokens |
| `PUBLIC_SITE_URL` | Yes | Base URL for unsubscribe links |

---

*Last updated: March 2026*

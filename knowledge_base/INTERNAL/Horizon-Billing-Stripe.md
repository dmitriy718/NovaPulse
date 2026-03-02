# Billing & Stripe Integration

This document covers the Stripe integration in HorizonAlerts, including the checkout flow, webhook handling, entitlement management, and customer portal.

---

## Overview

HorizonAlerts uses Stripe for subscription billing with the following components:
- **Stripe Checkout**: Hosted payment page for new subscriptions
- **Stripe Webhooks**: Server-side event handling for subscription lifecycle
- **Stripe Customer Portal**: Self-service subscription management
- **Entitlements Table**: Local database record of subscription status

---

## Configuration

### Environment Variables

| Variable | Description |
|---|---|
| `STRIPE_SECRET_KEY` | Stripe secret API key |
| `STRIPE_WEBHOOK_SECRET` | Webhook endpoint signing secret |
| `STRIPE_PRICE_ID_PRO` | Price ID for the Pro subscription plan |
| `STRIPE_SUCCESS_URL` | Redirect URL after successful checkout (default: `{siteUrl}/pricing?status=success`) |
| `STRIPE_CANCEL_URL` | Redirect URL after canceled checkout (default: `{siteUrl}/pricing?status=cancel`) |
| `STRIPE_PORTAL_RETURN_URL` | Return URL from Customer Portal (default: `{siteUrl}/settings`) |
| `PUBLIC_SITE_URL` | Base URL for building redirect URLs |

### Stripe API Version

The integration uses Stripe API version `2024-04-10`.

---

## Checkout Flow

### Creating a Checkout Session

**Endpoint**: `POST /billing/checkout-session`

**Prerequisites**:
1. User must be authenticated (Firebase token)
2. Email must be verified (`email_verified = true`)
3. User must NOT already have an active subscription

**Flow**:
```
1. Client sends POST /billing/checkout-session with Firebase token
2. API verifies: email_verified = true (else 403)
3. API checks: no existing active subscription (else 409)
4. API creates Stripe Checkout Session:
   - mode: "subscription"
   - line_items: [{ price: STRIPE_PRICE_ID_PRO, quantity: 1 }]
   - customer_email: user's email
   - success_url: STRIPE_SUCCESS_URL
   - cancel_url: STRIPE_CANCEL_URL
   - metadata: { uid: user's Firebase UID }
   - subscription_data: { metadata: { uid: user's Firebase UID } }
5. API returns { url: checkout_session_url }
6. Client redirects to Stripe Checkout
7. User completes payment on Stripe
8. Stripe redirects to success_url or cancel_url
```

**Key detail**: The `uid` is stored in BOTH `metadata` (session level) and `subscription_data.metadata` (subscription level). This ensures the webhook handler can find the UID when processing subscription events.

### Error Responses

| Code | Error | Condition |
|---|---|---|
| 403 | `email_not_verified` | User's email is not verified |
| 409 | `already_subscribed` | User already has an active Pro subscription |
| 500 | `stripe_not_configured` | STRIPE_SECRET_KEY or STRIPE_PRICE_ID_PRO missing |

---

## Webhook Handling

### Endpoint: POST /auth/callback/stripe

This endpoint receives Stripe webhook events. It is NOT protected by Firebase auth -- instead, it uses Stripe signature verification.

### Signature Verification

```typescript
const rawBody = request.rawBody as Buffer;
event = stripe.webhooks.constructEvent(
  rawBody.toString("utf8"),
  signature,
  webhookSecret
);
```

The raw body is captured by a custom content type parser that stores the original Buffer on `request.rawBody` while also parsing JSON normally.

### Handled Events

#### customer.subscription.created / customer.subscription.updated

1. Extract `uid` from `subscription.metadata.uid`
2. If uid is missing, fallback: look up customer by email, then find user by email
3. Extract `plan` from price metadata (default: "pro")
4. Upsert `stripe_entitlements`:
   ```sql
   INSERT INTO stripe_entitlements (uid, plan, status, current_period_end, updated_at)
   VALUES ($1, $2, $3, to_timestamp($4), now())
   ON CONFLICT (uid) DO UPDATE
   SET plan = excluded.plan,
       status = excluded.status,
       current_period_end = excluded.current_period_end,
       updated_at = now()
   ```

#### customer.subscription.deleted

1. Extract `uid` from subscription metadata (with same email fallback)
2. Update entitlement:
   ```sql
   UPDATE stripe_entitlements SET status = 'canceled', updated_at = now() WHERE uid = $1
   ```

### UID Resolution Fallback

When `subscription.metadata.uid` is missing (e.g., subscription created from Stripe dashboard):

```typescript
const customerId = typeof subscription.customer === "string"
  ? subscription.customer
  : subscription.customer?.id;

const customer = await stripe.customers.retrieve(customerId);
if (!customer.deleted && customer.email) {
  const userRows = await query(
    `SELECT uid FROM users WHERE email = $1 LIMIT 1`,
    [customer.email]
  );
  if (userRows.length) uid = userRows[0].uid;
}
```

If uid cannot be resolved, a warning is logged but the webhook returns 200 (to prevent Stripe from retrying).

---

## Customer Portal

### Creating a Portal Session

**Endpoint**: `POST /billing/portal-session`

**Prerequisites**:
1. User must be authenticated
2. Email must be verified

**Flow**:
```
1. Client sends POST /billing/portal-session with Firebase token
2. API looks up Stripe customer by email
3. If no customer exists, creates one with user's email and UID in metadata
4. Creates a Stripe Billing Portal session with return_url
5. Returns { url: portal_session_url }
6. Client redirects to Stripe Portal
7. User manages subscription (update payment, change plan, cancel)
8. Stripe redirects back to return_url
```

**Note**: Creating a Stripe customer object even when one does not exist ensures the portal is always accessible, even for users who have not subscribed yet (they can still view their billing info).

---

## Entitlement Checking

### Checking Subscription Status

The `GET /me/entitlement` endpoint returns the user's current plan and capabilities:

```typescript
const rows = await query(
  "SELECT plan, status, current_period_end FROM stripe_entitlements WHERE uid = $1",
  [uid]
);
const isPro = record?.plan === "pro" && record.status === "active";

return {
  plan: isPro ? "pro" : "free",
  verifiedEmail: true,
  currentPeriodEnd: record?.current_period_end || null,
  caps: {
    alertsPerDay: isPro ? 9999 : 5,
    customization: isPro,
  },
};
```

### Pro Feature Gating

Pro-only features check the `stripe_entitlements` table directly:

```typescript
// Scanner route
const entRows = await query(
  `SELECT status FROM stripe_entitlements WHERE uid = $1 AND status = 'active' LIMIT 1`,
  [uid]
);
if (!entRows.length) {
  return reply.code(403).send({
    error: "pro_required",
    message: "Live signals require a Pro subscription"
  });
}
```

### Duplicate Subscription Prevention

Before creating a checkout session, the API checks for existing active subscriptions:

```typescript
const existing = await query(
  `SELECT status FROM stripe_entitlements WHERE uid = $1 AND status = 'active' LIMIT 1`,
  [uid]
);
if (existing.length) {
  return reply.code(409).send({
    error: "already_subscribed",
    message: "You already have an active Pro subscription."
  });
}
```

---

## Frontend Integration

### Pricing Page

The pricing page (`apps/web/app/pricing/pricingClient.tsx`) handles:
- Hosting toggle (self-hosted vs Horizon-hosted)
- Three tier cards with dynamic pricing
- Success/cancel status messages from redirect query params
- Get Started button -> redirects to `/onboarding?plan=<tier>&hosting=<type>`

### Billing Buttons

The `BillingButtons` component provides:
- **Subscribe**: Creates a checkout session and redirects to Stripe
- **Manage Subscription**: Creates a portal session and redirects to Stripe Portal

### Settings Page

The Settings page displays:
- Current plan name
- Subscription status
- Current period end date
- Manage Subscription button (links to Stripe Portal)

---

## Stripe Subscription Statuses

| Status | Description | Platform Behavior |
|---|---|---|
| `active` | Subscription is paid and current | Full access to Pro features |
| `past_due` | Payment failed, retrying | Access continues during retry period |
| `canceled` | Subscription has been canceled | Reverts to free tier |
| `incomplete` | Initial payment pending | No Pro access |
| `incomplete_expired` | Initial payment failed | No Pro access |
| `trialing` | In trial period | Pro access (if applicable) |
| `unpaid` | All retry attempts failed | No Pro access |

---

## Testing Stripe Locally

For local development:

1. Use Stripe test mode keys
2. Install Stripe CLI: `brew install stripe/stripe-cli/stripe`
3. Forward webhooks: `stripe listen --forward-to localhost:4000/auth/callback/stripe`
4. Use test card numbers (e.g., 4242 4242 4242 4242)
5. The CLI will display the webhook signing secret to use in your `.env`

---

## Security Considerations

1. **Webhook signature verification**: All webhook events are verified using `stripe.webhooks.constructEvent` with the raw body and signature
2. **Raw body parsing**: Custom content type parser preserves the raw body for signature verification while parsing JSON normally
3. **No client-side secret key**: Only the publishable key is used client-side; the secret key is server-only
4. **Email verification required**: Checkout sessions cannot be created without a verified email
5. **UID in metadata**: The Firebase UID is stored in subscription metadata, ensuring correct entitlement mapping even when customer email changes

---

*Last updated: March 2026*

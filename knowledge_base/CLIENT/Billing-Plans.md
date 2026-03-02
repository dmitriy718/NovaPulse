# Billing and Plans

**Last updated:** 2026-03-02

Nova|Pulse by Horizon Services uses Stripe for all billing. This guide covers available plans, pricing, hosting options, how to subscribe, manage your subscription, and get a refund.

---

## Plans Overview

Every plan includes the full NovaPulse AI trading engine with all 12 strategies, the confluence engine, risk management, and the Smart Exit System. Plans differ in support level, customization options, hosting, and advanced features.

### Starter

**Self-Hosted: $49.99/mo | Horizon-Hosted: $99.99/mo**

- Full NovaPulse bot access
- All 12 AI trading strategies
- Multi-exchange support (Kraken, Coinbase, Alpaca)
- Crypto + US stock trading
- Real-time performance dashboard (bot + Horizon web)
- Multi-timeframe confluence engine
- Adaptive risk sizing and Smart Exit System
- Email support (< 24hr response time)

### Pro (Most Popular)

**Self-Hosted: $99.99/mo | Horizon-Hosted: $149.99/mo**

Everything in Starter, plus:
- Priority support (< 4hr response time)
- Custom strategy weight tuning
- Advanced risk configuration
- Telegram and Discord trade alerts
- Weekly performance report emails
- Strategy-level P&L attribution
- Custom confluence thresholds
- Regime-aware parameter adjustment
- Access to Pro Scanner (live trading signals feed)

### Elite

**Self-Hosted: $199.99/mo | Horizon-Hosted: $249.99/mo**

Everything in Pro, plus:
- Up to 3 bot instances
- Dedicated VPS resources
- Custom strategy development
- 1-on-1 onboarding call (60 minutes)
- SLA 99.9% uptime guarantee
- Direct Slack channel to the engineering team
- Priority feature requests
- Monthly strategy review sessions

---

## Self-Hosted vs Horizon-Hosted

### Self-Hosted

You run the NovaPulse Docker container on your own VPS or server.

**Pros:**
- Full control over your infrastructure
- API keys never leave your server
- Lower monthly cost
- Maximum privacy

**Requirements:**
- VPS with 2+ CPU cores, 4GB+ RAM
- Docker installed
- Ubuntu 22+ recommended
- You are responsible for updates and monitoring

### Horizon-Hosted

We provision and manage a dedicated bot instance on our infrastructure.

**Pros:**
- Zero server management
- 24/7 monitoring and automatic restarts
- Automatic software updates (always latest version)
- Live in under 5 minutes
- Guaranteed uptime

**What is included:**
- Dedicated instance (not shared)
- Monitoring and alerting
- Automatic recovery on crash
- Software updates pushed automatically

---

## What Is Included in Every Plan

Regardless of tier, you always get:

- **All twelve trading strategies** with confluence voting
- **Full risk management** (Kelly sizing, ATR stops, trailing, breakeven, daily loss limits, exposure caps)
- **Smart Exit System** with tiered partial closes
- **Bot dashboard** with real-time data, positions, P&L, thought feed
- **Horizon web dashboard** access at horizonsvc.com
- **Paper trading mode** for risk-free testing
- **Auto Strategy Tuner** (weekly strategy weight adjustment)
- **Session Analyzer** (per-hour confidence adjustment)
- **All circuit breakers** (consecutive loss, drawdown, stale data, WS disconnect)
- **Gamification** (levels, ranks, achievements, win streaks)

---

## How to Subscribe

### Step 1: Choose Your Plan

Visit [horizonsvc.com/pricing](https://horizonsvc.com/pricing) and:
1. Toggle between Self-Hosted and Horizon-Hosted pricing
2. Click the **Get Started** / **Go Pro** / **Go Elite** button on your chosen tier

### Step 2: Complete Onboarding

If you have not already registered:
1. Create your account (email/password or Google SSO)
2. Complete the onboarding wizard with your profile information
3. Verify your email address

### Step 3: Checkout

1. You are redirected to a Stripe Checkout session
2. Enter your payment details
3. Complete the purchase
4. You are redirected back to the pricing page with a success confirmation

### After Checkout

- Your subscription status is updated automatically via Stripe webhooks
- Pro features (scanner, custom configuration) become available immediately
- If you chose Horizon-hosted, your bot instance begins provisioning

---

## Managing Your Subscription

### View Subscription Status

Go to [horizonsvc.com/settings](https://horizonsvc.com/settings) to see:
- Your current plan (Free, Starter, Pro, or Elite)
- Subscription status (active, canceled, past_due)
- Current billing period end date

### Customer Portal

Click **Manage Subscription** in Settings to access the Stripe Customer Portal, where you can:
- Update your payment method
- View invoices and payment history
- Change your plan (upgrade/downgrade)
- Cancel your subscription

### Upgrading

You can upgrade your plan at any time. The price difference is prorated for the current billing period. New features become available immediately.

### Downgrading

Downgrade takes effect at the end of your current billing period. You retain access to higher-tier features until then.

### Canceling

1. Go to Settings > Manage Subscription
2. Click Cancel in the Stripe Customer Portal
3. Your subscription remains active until the current period ends
4. After cancellation, you revert to the free tier

---

## Refund Policy

We offer a **14-day money-back guarantee** on all plans, no questions asked.

- Email support@horizonsvc.com within 14 days of your subscription start date
- Provide your account email
- You will receive a full refund
- No reason required

---

## Free Tier

Users without an active subscription have access to:
- Limited public signal feed (delayed signals, educational only)
- Account settings and profile management
- Up to 5 alerts per day
- No bot connection or dashboard access
- No customization features
- No Pro scanner access

---

## Payment Methods

Stripe accepts all major credit and debit cards (Visa, Mastercard, American Express, Discover). Additional methods may be available depending on your region.

---

## Billing FAQ

**Q: Is there a free trial?**
A: No free trial, but there is a 14-day money-back guarantee on all plans.

**Q: When am I charged?**
A: On the day you subscribe, and then on the same date each month.

**Q: What happens if my payment fails?**
A: Stripe retries failed payments automatically. If payment continues to fail, your subscription status changes to `past_due`. You receive email notifications from Stripe.

**Q: Can I switch between self-hosted and Horizon-hosted?**
A: Yes, contact support to switch hosting options. We help migrate your bot configuration.

**Q: Can I switch between paper and live mode within my plan?**
A: Yes. Paper/live mode is a configuration choice, not a plan limitation. Both modes are supported on all plans.

**Q: Does the plan limit how much I can trade?**
A: Plans do not limit trade volume or bankroll size. The only limits are configuration parameters (max position size, max concurrent positions, etc.) which are adjustable.

**Q: Can I have multiple bots on one plan?**
A: Starter and Pro plans include one bot instance. Elite includes up to 3. For more, contact us about enterprise plans.

**Q: Are there any hidden fees?**
A: No. The subscription price covers everything. Exchange trading fees are charged by your exchange (Kraken, Coinbase, Alpaca), not by us.

---

## Enterprise / Custom Plans

For institutional users, trading desks, or high-volume accounts, contact [enterprise@horizonsvc.com](mailto:enterprise@horizonsvc.com) for:

- Custom infrastructure deployment
- Dedicated support engineer
- Custom strategy development
- Higher API rate limits
- SLA guarantees
- Multi-tenant management

---

*Nova|Pulse v5.0.0 by Horizon Services -- Choose the plan that matches your ambition.*

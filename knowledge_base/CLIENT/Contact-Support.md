# Contact and Support

**Last updated:** 2026-03-02

We are here to help. Whether you have a question about your dashboard, need help with settings, or are experiencing a problem, Horizon Services support is ready to assist through multiple channels.

---

## Support Channels

### 1. Horizon Support Page (Recommended)

Visit [horizonsvc.com/support](https://horizonsvc.com/support) to submit a support request.

**For registered users** (logged in):
- Select a topic category
- Provide a subject and detailed message
- Your request is linked to your account for faster resolution
- A confirmation email is sent to your account email

**For unregistered visitors** (not logged in):
- Enter your name and email address
- Provide a subject and message
- A confirmation email is sent to the provided address

### 2. Ticket System (Settings)

Registered users have access to a full ticket management system:

1. Go to [horizonsvc.com/settings](https://horizonsvc.com/settings)
2. Click the **Support** tab
3. Create a new ticket or view existing tickets

**Creating a Ticket:**
- **Department**: Billing, Tech Support, Customer Service, Referrals, or Partnership
- **Subject**: Brief summary of your issue (max 200 characters)
- **Message**: Detailed description (max 5,000 characters)
- **Priority**: Low, Normal, High, or Urgent

**Viewing Tickets:**
- See all your tickets with status (Open, In Progress, Resolved, Closed)
- Click a ticket to view the full conversation thread
- Reply to tickets with follow-up information

### 3. Email (All Plans)

Send an email directly to **support@horizonsvc.com**. Include:
- Your account email address
- A description of the issue
- Any relevant screenshots or error messages
- Your subscription plan

### 4. Telegram (Pro and Elite Plans)

Pro and Elite subscribers can receive support via Telegram. Your channel invite is included in your welcome email.

### 5. Slack (Elite Plan)

Elite members receive a direct Slack channel to the engineering team.

### 6. Contact Form

The contact page at [horizonsvc.com/contact](https://horizonsvc.com/contact) provides a general-purpose contact form for any inquiry.

---

## Response Times

Response times depend on your subscription tier:

| Plan | Email Support | Priority |
|---|---|---|
| Starter | < 24 hours | Standard |
| Pro | < 4 hours | Priority |
| Elite | < 1 hour | Highest Priority |

Elite members also receive:
- Direct Slack channel to the engineering team
- Monthly strategy review sessions
- Priority feature requests

---

## What to Include in Your Request

The more information you provide, the faster we can help.

### For Bot / Trading Issues

1. **Bot version** -- visible in the dashboard header (e.g., "v5.0.0")
2. **What happened** -- describe the issue clearly
3. **What you expected** -- what should have happened instead
4. **When it started** -- approximate date and time (UTC preferred)
5. **Thought feed messages** -- copy the relevant entries from the AI thought feed
6. **Error messages** -- any error text from the dashboard or logs
7. **Which exchange(s)** are affected and specific trading pairs
8. **Steps to reproduce** -- if you can reproduce the issue, describe how

### For Bot Connection Issues

- Your bot URL (masked for security -- just the hostname and port)
- Whether you are self-hosted or Horizon-hosted
- Error message shown in the Horizon dashboard
- Browser console errors (press F12, go to Console tab)

### For Dashboard / Platform Issues

- Screenshots of the issue
- Browser name and version
- Whether the issue occurs in incognito mode
- Steps to reproduce the problem

### For Billing Issues

- Your account email (the one used for Stripe)
- Stripe payment confirmation or invoice ID
- Expected vs actual subscription status

### For Configuration Questions

- What you want to achieve (e.g., "I want fewer but higher-quality trades")
- Your current settings (if known)
- Your plan tier

---

## Example Support Request

Here is an example of a well-written support request:

> Subject: Bot not placing trades for 3 hours
>
> Hi,
>
> My bot (v5.0.0, Kraken, Paper mode) has not placed any trades in the last 3 hours. The dashboard shows "OPERATIONAL" status and scan count is increasing normally.
>
> The thought feed shows repeated "No signal for BTC/USD" and "Confluence below threshold (1 < 2)" messages. I see that only the Keltner strategy is finding setups, but it needs at least 2 strategies to agree.
>
> Is this normal for current market conditions, or should I adjust my confluence threshold?
>
> Thanks

---

## Urgent Issues

For urgent issues that require immediate attention (bot trading incorrectly in live mode, suspected security breach, service outage):

1. **Use the dashboard Kill button** to immediately stop the bot
2. **Contact support with priority "Urgent"** via the ticket system
3. **Include "CRITICAL" in the email subject line** if emailing directly
4. **Use Telegram `/pause` or `/kill`** for immediate bot control

You can also:
- **Pause trading** via the dashboard or Telegram `/pause`
- **Close all positions** via the dashboard or Telegram `/close_all`
- **Kill the bot** via Telegram `/kill` or `docker stop`

See [Controls](Controls-Pause-Resume-Kill.md) for how to use these emergency controls.

---

## Self-Service Resources

Before contacting support, check these resources:

### Knowledge Base
- [Getting Started](Getting-Started.md) -- Account setup and onboarding
- [Horizon Dashboard](Horizon-Dashboard.md) -- How to use the web dashboard
- [Bot Dashboard Walkthrough](Nova-Dashboard-Walkthrough.md) -- Every panel of the bot dashboard
- [Troubleshooting](Troubleshooting.md) -- Common issues and fixes
- [FAQ](FAQ.md) -- Frequently asked questions

### Website Resources
- **Academy**: [horizonsvc.com/academy](https://horizonsvc.com/academy) -- Educational articles about trading strategies
- **Blog**: [horizonsvc.com/blog](https://horizonsvc.com/blog) -- Platform updates and market insights
- **Trust and Safety**: [horizonsvc.com/trust-safety](https://horizonsvc.com/trust-safety) -- Security practices and trust information

### Legal
- [Privacy Policy](https://horizonsvc.com/privacy)
- [Terms of Service](https://horizonsvc.com/terms)
- [Cookie Policy](https://horizonsvc.com/cookies)
- [Email Security (DMARC)](https://horizonsvc.com/dmarc)

---

## Business Hours

Our support team operates:
- **Monday through Friday:** 9:00 AM -- 6:00 PM Eastern (US)
- **Weekends and holidays:** Monitoring for urgent issues only

Pro and Elite support has extended hours with faster response times.

---

## Rate Limits on Support

To prevent abuse, the following rate limits are in place:
- **Contact form** (public): 5 submissions per hour per IP address
- **Support tickets** (authenticated): Subject to global API rate limits (120 requests/minute)
- **Ticket replies**: Subject to global API rate limits

---

## Escalation

If your issue is not resolved within the expected response time:

1. Reply to your existing ticket with additional context
2. Set the ticket priority to "High" or "Urgent" if the issue is critical
3. Email support@horizonsvc.com referencing your ticket number
4. For Elite members: use your dedicated Slack channel

---

## Feature Requests and Feedback

We welcome feedback on the platform:
- **Feature requests**: Submit via the support ticket system (department: "Customer Service")
- **Bug reports**: Via the support page or email
- **General feedback**: Email support@horizonsvc.com

Elite members have priority feature requests -- your suggestions are prioritized in the development roadmap.

---

## Community

Join the Nova|Pulse community:
- **Discord server** -- Connect with other traders using Nova|Pulse
- **Horizon blog** -- Trading insights and product updates at [horizonsvc.com/blog](https://horizonsvc.com/blog)

---

*Nova|Pulse v5.0.0 by Horizon Services -- We are here when you need us.*

# Troubleshooting

**Last updated:** 2026-03-02

This guide covers the most common issues you might encounter with Nova|Pulse and the Horizon platform, and how to resolve them. If your issue is not covered here, please [contact support](Contact-Support.md).

---

## Bot Is Not Placing Trades

This is the most common concern, especially for new users. There are many legitimate reasons the bot may not trade for a period.

### Check the Thought Feed

The thought feed (AI reasoning log on the dashboard) tells you exactly what the bot is seeing. Look for these messages:

| Message | Meaning | Action |
|---------|---------|--------|
| "Warming up..." | Bot is loading historical data | Wait 15 minutes for warmup to complete |
| "No signal for [pair]" | Strategies did not find a setup | Normal -- the bot is selective by design |
| "Confluence below threshold" | Strategies partially agree but not enough | Normal -- wait for stronger agreement |
| "Risk rejected: [reason]" | Signal passed confluence but failed risk check | Check the reason (daily loss, exposure cap, etc.) |
| "Paused" or "Auto-paused" | Trading is paused | Check the pause reason and resume if appropriate |
| "Priority schedule PAUSED" | Crypto paused during stock hours (or vice versa) | Normal -- automatic scheduling. Wait for the session change. |
| "Quiet hours" | Currently in a quiet hour | Normal -- no trades during configured quiet hours |
| "Cooldown active" | Post-loss cooldown | Wait for cooldown to expire (default 30 seconds) |

### Common Causes of Low Trade Frequency

1. **Low-volatility market**: When markets are range-bound, fewer signals meet confluence requirements
2. **High confluence threshold**: The default threshold (2) requires at least 2 strategies to agree
3. **Quiet hours**: Default quiet hours (3 AM UTC) suppress trading during low-liquidity periods
4. **Priority scheduling**: Crypto pauses during US market hours, stocks pause outside market hours
5. **Post-loss cooldowns**: After losses, brief cooldowns prevent re-entry

---

## Horizon Dashboard Issues

### "Bot Unreachable" or "No Bot Connected"

**Symptoms**: Dashboard shows a gray status indicator with "Unreachable" or a prompt to connect a bot.

**Solutions**:

1. **No bot connection configured**: Go to Settings > Bot Connection and enter your bot URL, API key, and hosting type

2. **Bot is not running**:
   - Self-hosted: Check that your Docker container is running (`docker ps`)
   - Horizon-hosted: Contact support -- your instance may need to be restarted

3. **Incorrect bot URL**: Verify the URL in Settings matches your bot's actual address. Include the protocol and port (e.g., `https://your-server.com:8080`). Remove trailing slashes

4. **Firewall blocking connections**: Ensure your bot's port (default 8080) is open to inbound connections from the internet

5. **API key mismatch**: Verify you are using the correct read key or admin key from your bot's `.secrets/env`

6. **SSL/TLS issues**: If your bot uses HTTPS, ensure the certificate is valid

### Dashboard Shows Stale Data

**Solutions**:
- Click the refresh button in the dashboard header
- Check that your bot is running and responsive
- Try logging out and back in to refresh your Firebase token
- Clear browser cache and reload the page

### Email Verification Modal Will Not Dismiss

**Solutions**:
- Wait a few seconds -- the system polls verification status every 3 seconds
- If it persists, try refreshing the page
- Click "Resend Verification Email" and use the new link
- Try logging out, clearing cookies, and logging back in

### Dashboard Loads but Shows No Data

**Solutions**:
- Verify your bot connection in Settings > Bot Connection
- Check that the bot is actually trading (it may be freshly started with no trade history)
- Ensure your bot has the API server running (port 8080 accessible)
- Check browser console for API errors (F12 > Console)

---

## Bot Dashboard Issues

### Dashboard Shows "CONNECTING..." or Does Not Load

**Solutions**:
1. Verify the bot container is healthy: `docker ps | grep novatrader`
2. Check container logs: `docker logs novatrader-trading-bot-1 --tail 50`
3. Verify port mapping (8090 host to 8080 container): `docker port novatrader-trading-bot-1`
4. Try accessing `/api/v1/health` directly in your browser
5. Check if another process is using port 8090

### "403 Forbidden" on Dashboard

**Solutions**:
- Verify your login credentials
- Check that the `DASHBOARD_ADMIN_KEY` or password hash in `.secrets/env` is correct
- Ensure bcrypt hashes are in `.secrets/env` (not `.env` -- Docker Compose mangles `$` characters)

---

## Bot Connection Issues

### "Could not reach your bot. Make sure the URL is correct and the bot is running."

**Solutions**:
- Verify the bot URL is accessible from the internet (not just your local network)
- Test the URL: open `https://your-bot-url:8080/api/v1/status` in a browser
- Check that the bot container is running: `docker ps | grep novatrader`
- Verify port forwarding if behind NAT
- Check firewall rules: `sudo ufw status` or cloud provider security groups

### "Authentication failed. Double-check your API key."

**Solutions**:
- The API key should be the read key or admin key from your NovaPulse `.secrets/env`
- API keys are case-sensitive -- copy-paste to avoid typos
- Make sure the key has not been rotated since you last configured it

### "Bot URL cannot point to internal network addresses"

**Solutions**:
- This is SSRF protection. Your bot URL must be a public IP or hostname
- Private IPs (10.x.x.x, 172.16-31.x.x, 192.168.x.x, localhost) are blocked
- Use your server's public IP or domain name instead

---

## Authentication Issues

### Cannot Log In to Horizon Dashboard

**Solutions**:
1. Check that you are using the correct email address
2. Try the "Forgot Password" link to reset your password
3. Check if your account is locked (after 3 failed attempts in 30 minutes)
4. Wait 30 minutes if locked, then try again
5. Clear browser cookies and try again
6. Try a different browser or incognito mode
7. Check that JavaScript is enabled in your browser

### Account Locked

**Solutions**:
- Account locks expire automatically after 30 minutes
- Check your email for the lock notification (it includes the IP that triggered it)
- If you did not make those login attempts, change your password immediately after the lock expires
- Contact support if you believe your account is compromised

### Google SSO Not Working

**Solutions**:
- Ensure third-party cookies are not blocked (required for Google sign-in)
- Try using a different browser
- Clear cookies for horizonsvc.com and google.com
- Try the email/password login as a fallback

### "Email not verified" Error When Subscribing

**Solutions**:
- You must verify your email before subscribing
- Check your inbox and spam folder for the verification email from support@horizonsvc.com
- Go to the dashboard -- the verification modal has a "Resend Verification Email" button

---

## Exchange Connection Issues

### Kraken "WS 1013" Errors

**Meaning**: Kraken WebSocket server sent a reconnect-requested close code. This is normal.

**Resolution**: The bot handles this automatically with retry backoff. No action needed.

### Coinbase "Invalid Pair" Messages

**Meaning**: Some pairs on Coinbase are not available for trading.

**Resolution**: The bot automatically excludes invalid pairs via the `_invalid_pairs` set. No action needed.

### "Exchange Auth Failed" Error

**Solutions**:
1. Re-check your exchange API keys
2. Ensure the keys have not been revoked or expired
3. Verify the correct permissions are enabled (View + Trade)
4. For Kraken: ensure both API Key and Private Key are provided
5. For Coinbase: ensure both API Key and API Secret are provided

---

## Billing Issues

### Subscription Not Activating After Payment

**Solutions**:
- Wait 1-2 minutes for the Stripe webhook to process
- Refresh the pricing page -- it should show "Subscription activated!"
- Check Settings for your subscription status
- If status still shows "free", contact support with your payment confirmation email

### "You already have an active subscription" Error

**Solutions**:
- Check Settings to verify your current subscription status
- If you recently canceled, your subscription may still be active until the end of the billing period
- Contact support to check your subscription record

### Payment Failed

**Solutions**:
- Stripe retries failed payments automatically
- Update your payment method in the Stripe Customer Portal (Settings > Manage Subscription)
- Check with your bank if the transaction is being blocked
- Try a different payment card

---

## Email Issues

### Not Receiving Emails from Horizon

**Solutions**:
1. Check your spam/junk folder
2. Add these sender addresses to your contacts:
   - support@horizonsvc.com
   - alerts@horizonsvc.com
   - security@horizonsvc.com
   - marketing@horizonsvc.com
3. Check your notification preferences in Settings > Notifications
4. Verify that Global Unsubscribe is not enabled
5. Some email providers delay delivery -- wait 5-10 minutes

### Getting Too Many Emails

**Solutions**:
- Go to Settings > Notifications to disable specific categories
- Turn off Trade Executed and Trade Closed notifications (high frequency)
- Use the unsubscribe link in any email to disable that category
- Enable Global Unsubscribe to stop all non-security emails

### Unsubscribe Link Not Working

**Solutions**:
- Unsubscribe tokens expire after 90 days -- request a fresh email and use its link
- Go to Settings > Notifications to manually disable categories instead
- Contact support if you cannot unsubscribe by any method

---

## Performance Issues

### Dashboard Loading Slowly

**Solutions**:
- Check your internet connection
- The Horizon dashboard proxies API calls to your bot -- slow bot response slows the dashboard
- For self-hosted: check your bot server's CPU and memory usage
- Try a different browser or disable browser extensions
- Clear browser cache

### High Memory Usage on Bot Server

**Solutions**:
- Check container memory: `docker stats novatrader-trading-bot-1`
- Consider reducing the number of trading pairs
- Reduce `lookback_bars` in config (default 120)
- Restart the container if memory usage is abnormally high

---

## Getting More Help

If none of the above solutions resolve your issue:

1. **Check the FAQ**: [FAQ](FAQ.md) for answers to common questions
2. **Submit a ticket**: [horizonsvc.com/support](https://horizonsvc.com/support)
3. **Email support**: support@horizonsvc.com
4. **Settings ticket system**: Settings > Support tab to create and track tickets

Pro and Elite members receive priority support with faster response times.

---

*Nova|Pulse v5.0.0 by Horizon Services -- Most issues have a simple solution.*

# Frequently Asked Questions

**Last updated:** 2026-02-22

---

## General

### What is NovaPulse?

NovaPulse is an AI-powered cryptocurrency trading bot that monitors the markets 24/7 and executes trades on your behalf. It uses nine independent trading strategies that must agree before any trade is placed, combined with institutional-grade risk management to protect your capital. You monitor and control it through a web dashboard and optionally through Telegram, Discord, or Slack.

---

### How does NovaPulse make trading decisions?

Every 60 seconds, NovaPulse scans each configured trading pair and runs all nine strategies:

1. Each strategy analyzes price action, momentum, volatility, and other indicators
2. Each strategy votes: BUY, SELL, or NO SIGNAL
3. If at least 3 strategies agree (confluence), a signal is generated
4. The AI evaluates the signal's confidence (minimum 65%)
5. Risk checks are applied (position limits, daily loss, exposure caps)
6. If everything passes, the trade is placed with automatic stop loss and take profit

The bot also considers the current market regime (trending vs. ranging, high vs. low volatility) and adjusts strategy weights accordingly. See [Trading Strategies](Trading-Strategies.md) for full details.

---

### What exchanges are supported?

NovaPulse currently supports:

- **Kraken** (recommended) -- Full support including WebSocket real-time data and REST API for orders
- **Coinbase** (Advanced Trade) -- Full REST API support

Multi-exchange support is available for subscribers on the Premium plan.

---

### Can I run NovaPulse on multiple exchanges simultaneously?

Yes, if you are on the Premium plan. NovaPulse can connect to both Kraken and Coinbase at the same time, with separate risk management and position tracking for each exchange.

---

## Safety and Risk

### Is my money safe?

NovaPulse implements 14 layers of protection (detailed in [Risk and Safety](Risk-Safety.md)), including:

- Automatic stop losses on every trade
- Trailing stops that lock in profits
- Daily loss limits that auto-pause the bot
- Maximum position sizes and exposure caps
- Circuit breakers for stale data and connection issues
- Exchange-native stop orders that survive bot outages

Additionally, your exchange API keys are configured **without withdrawal permissions**, so NovaPulse can trade but cannot move funds off the exchange.

That said, **no system can eliminate risk entirely**. Markets can be unpredictable, and losses are a normal part of trading.

---

### Can I lose money?

**Yes.** Trading cryptocurrency involves risk, and you can lose money. Even with NovaPulse's risk management:

- Individual trades can and will hit their stop losses
- Markets can experience sudden, extreme moves
- No trading system can guarantee profits

NovaPulse's risk management is designed to **limit the damage** from any individual loss and prevent catastrophic drawdowns. Think of it like wearing a seatbelt -- it greatly reduces the risk of serious harm, but it does not eliminate all risk.

**We strongly recommend:**
- Only trade with money you can afford to lose
- Start with paper trading to understand the bot's behavior
- Use Canary Mode when first going live
- Keep risk settings conservative (2% or less per trade)

---

### What happens if the bot crashes?

If NovaPulse's server crashes or restarts:

1. **Exchange-native stop orders** (if enabled) continue to protect your open positions on the exchange itself
2. When the bot comes back online, it re-detects open positions from the exchange
3. It resumes monitoring and managing those positions
4. The restart typically takes 1-2 minutes

Your positions are not abandoned during a crash -- the exchange's own stop-loss orders serve as a backup.

---

### How do I stop the bot in an emergency?

**From the dashboard:** Click the **Kill** button. This closes all positions and stops the bot.

**From Telegram:** Send `/kill` and confirm with "yes" when prompted.

**From Discord:** Send `/kill` in the authorized channel.

**From Slack:** Send `/trading-kill` in the authorized channel.

**If you cannot reach any of these:** Log in to your exchange directly and:
1. Close any open positions manually
2. Delete or disable the NovaPulse API key

See [Controls](Controls-Pause-Resume-Kill.md) for full details.

---

## Trading

### What is paper trading and should I start there?

Paper trading is simulated trading -- NovaPulse watches real markets and generates real signals, but no actual orders are placed. Profits and losses are tracked as if they were real.

**Yes, we strongly recommend starting with paper trading.** Run it for at least 1-2 weeks to:

- Understand how the bot makes decisions
- Get comfortable with the dashboard
- See how it handles different market conditions
- Verify your risk settings before committing real money

Paper mode works identically to live mode from the dashboard perspective -- the only difference is that no real money is at stake.

---

### How do I switch to live trading?

1. Run paper mode for at least 1-2 weeks and review results
2. Ensure your exchange API keys are configured
3. Review and set your risk settings (see [Configuration Guide](Configuration-Guide.md))
4. Consider starting with **Canary Mode** -- ultra-conservative live trading with very small positions
5. Contact support to switch your instance from paper to live (or canary) mode
6. Monitor the dashboard closely for the first few days

---

### How much money do I need to start?

There is no strict minimum, but we recommend at least **$500** for meaningful results. Here is why:

- With a $500 bankroll and 2% risk per trade, each trade risks about $10
- After exchange fees (~0.3-0.5% round trip), very small trades may struggle to be net profitable
- Having at least $500 allows for meaningful position sizes across multiple concurrent trades

That said, paper trading requires no capital at all, and canary mode can be used with as little as $100-200 for initial live testing.

---

### What pairs can I trade?

NovaPulse can trade any cryptocurrency pair available on your exchange. Common pairs include:

- **BTC/USD** -- Bitcoin
- **ETH/USD** -- Ethereum
- **SOL/USD** -- Solana
- **ADA/USD** -- Cardano
- **DOT/USD** -- Polkadot
- **LINK/USD** -- Chainlink
- **AVAX/USD** -- Avalanche
- **MATIC/USD** -- Polygon

The default configuration includes BTC/USD and ETH/USD. You can add or remove pairs through the settings panel or by contacting support.

---

### How often does the bot check the market?

By default, every **60 seconds**. Each scan analyzes all configured pairs across all nine strategies. Position monitoring (stop losses, trailing stops) runs more frequently -- approximately every **2 seconds**.

---

### Why did the bot skip a trading opportunity?

Common reasons:

1. **Not enough confluence:** Fewer than 3 strategies agreed (the minimum threshold)
2. **Confidence too low:** The signal was below the 0.65 minimum confidence
3. **Risk limits:** Maximum positions, daily loss limit, or exposure cap was already reached
4. **Cooldown active:** A recent trade or loss triggered a cooldown period
5. **Quiet hours:** The signal occurred during configured quiet hours
6. **Poor risk/reward:** The stop-loss and take-profit levels did not provide at least a 0.9:1 risk-reward ratio
7. **Spread too wide:** The bid-ask spread was too wide, indicating poor liquidity

The AI Thought Feed on the dashboard shows the reason when a signal is generated but not acted upon.

---

## Strategies and AI

### Can I customize which strategies are used?

Yes. You can enable or disable individual strategies from the settings panel. However, we recommend keeping all nine strategies enabled. The confluence system naturally filters out weak signals -- underperforming strategies simply get outvoted. Disabling a strategy might cause you to miss opportunities when that strategy happens to catch a move the others miss.

---

### What is confluence and why does it matter?

Confluence means multiple independent strategies agreeing on the same trade direction. NovaPulse requires at least 3 out of 9 strategies to agree before entering a trade.

**Why it matters:** Any single strategy can produce false signals. But when three or more strategies, each analyzing the market from a different angle, all see the same opportunity, the probability of a valid signal increases significantly. It is like getting multiple expert opinions before making an important decision.

---

### How do trailing stops work?

1. Every trade starts with a fixed stop loss (based on volatility)
2. When the trade is profitable by 1.5% or more, the trailing stop activates
3. As price continues moving in your favor, the stop follows behind by 0.5%
4. The stop never moves backward -- it only tightens as price improves
5. When price reverses, the trailing stop catches it and closes the trade with profit

**Example:** You buy at $100 with a stop at $97. Price rises to $105. The trailing stop activates and sets at $104.50. Price continues to $108, trailing stop moves to $107.50. Price then reverses and hits $107.50 -- the trade closes with a $7.50 profit instead of going all the way back to $97.

---

### What is the Sharpe ratio?

The Sharpe ratio measures **risk-adjusted return** -- how much return you get per unit of risk (volatility). It answers the question: "Am I being compensated enough for the risk I am taking?"

- **Below 0:** Losing money on a risk-adjusted basis
- **0 to 1.0:** Subpar
- **1.0 to 2.0:** Good
- **2.0 to 3.0:** Very good
- **Above 3.0:** Exceptional

A higher Sharpe ratio means more consistent, reliable returns. See [Understanding Metrics](Understanding-Metrics.md) for full details.

---

## Billing and Account

### How does billing work?

NovaPulse uses Stripe for secure payment processing. Your subscription is billed monthly, and you can manage it through the billing section of your dashboard. See [Billing and Plans](Billing-Plans.md) for full details on plan tiers and pricing.

---

### How do I cancel my subscription?

You can cancel at any time through the billing section of your dashboard, or by contacting support. Your service continues until the end of your current billing period. See [Billing and Plans](Billing-Plans.md) for the full cancellation policy.

---

## Support

### How do I get support?

- **Email support** for non-urgent questions and account management
- **Priority support** for urgent issues during trading hours

When contacting support, include:
1. Your dashboard status (screenshot if possible)
2. The time and timezone of the issue
3. What you observed and what you expected
4. Any error messages or codes

See [Contact Support](Contact-Support.md) for full details.

---

### Where can I learn more?

| Topic | Guide |
|-------|-------|
| First-time setup | [Getting Started](Getting-Started.md) |
| Dashboard features | [Dashboard Walkthrough](Nova-Dashboard-Walkthrough.md) |
| Controlling the bot | [Controls](Controls-Pause-Resume-Kill.md) |
| Understanding metrics | [Understanding Metrics](Understanding-Metrics.md) |
| How strategies work | [Trading Strategies](Trading-Strategies.md) |
| Risk and safety | [Risk and Safety](Risk-Safety.md) |
| Notifications | [Notifications](Notifications.md) |
| Settings | [Configuration Guide](Configuration-Guide.md) |
| Troubleshooting | [Troubleshooting](Troubleshooting.md) |
| Security | [Security and Privacy](Security-Privacy.md) |
| Billing | [Billing and Plans](Billing-Plans.md) |
| Support | [Contact Support](Contact-Support.md) |

---

*Still have questions? [Contact support](Contact-Support.md) -- we are here to help.*

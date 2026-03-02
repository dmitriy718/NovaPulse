# Frequently Asked Questions

**Last updated:** 2026-03-01

---

## General

### What is Nova|Pulse?

Nova|Pulse is an AI-powered automated trading bot that trades cryptocurrencies and US stocks on your behalf. It uses twelve independent trading strategies, confluence voting (requiring multiple strategies to agree before entering a trade), machine learning, and institutional-grade risk management. It runs 24/7 for crypto and during market hours for stocks.

### Who makes Nova|Pulse?

Nova|Pulse is built and operated by **Horizon Services**. The customer-facing platform is at [horizonsvc.com](https://horizonsvc.com).

### What exchanges does it support?

- **Kraken** (primary for crypto) -- WebSocket v2 + REST
- **Coinbase** (secondary for crypto) -- Advanced Trade REST + WebSocket
- **Alpaca** (for US stocks) -- REST API for orders
- **Polygon.io** (for stock market data) -- REST API

### Is Nova|Pulse suitable for beginners?

Yes. Nova|Pulse is designed to be hands-off once set up. The bot makes all trading decisions. You can monitor via the dashboard and control via Telegram. However, you should understand the basics of trading risk before using real money.

### Do I need to leave my computer on?

No. Nova|Pulse runs on a server (either managed by Horizon or self-hosted). It operates 24/7 regardless of whether your computer is on or the dashboard is open.

---

## Trading

### How does the bot decide when to trade?

The bot uses twelve different technical analysis strategies that each independently evaluate market conditions. When at least two strategies agree on a direction (this is called "confluence"), and the overall confidence score exceeds the minimum threshold, and all risk checks pass, a trade is placed. See [Trading Strategies](Trading-Strategies.md) for details.

### What pairs does it trade?

By default for crypto: BTC/USD, ETH/USD, SOL/USD, XRP/USD, ADA/USD, DOT/USD, AVAX/USD, LINK/USD. For stocks: a dynamic universe of up to 96 stocks. Both lists are configurable. See [Configuration Guide](Configuration-Guide.md).

### Does it trade both long and short?

**Crypto:** Yes. The bot can go long (betting price will rise) or short (betting price will fall) on crypto pairs, depending on what the strategies signal.

**Stocks:** Currently long-only. The stock swing strategy focuses on uptrend alignment.

### How often does it trade?

It depends on market conditions. In active markets with clear setups, you might see several trades per day. In quiet or choppy markets, the bot may go hours without trading. The bot is deliberately selective -- quality over quantity.

### Can I trade just crypto, or just stocks?

Yes. Each can be enabled or disabled independently in the configuration.

### What is "confluence" and why does it matter?

Confluence means multiple independent strategies agreeing on the same trade direction at the same time. Think of it like getting a second (and third) opinion. A single strategy can produce false signals, but when several different methods all point the same way, the probability of a valid setup is much higher. See [Trading Strategies](Trading-Strategies.md) for a full explanation.

### What is paper trading mode?

Paper mode simulates trades using real market data but does not place actual orders on your exchange. No real money is at risk. It is the default mode and we recommend using it until you are comfortable with the bot's behavior.

---

## Risk and Safety

### Can I lose money?

Yes. Trading involves risk, and losses are a normal part of any trading system. Nova|Pulse has extensive risk management to limit the size and frequency of losses, but it cannot eliminate them. No trading system can guarantee profits.

### What is the maximum I can lose on a single trade?

By default, 1% of your bankroll. On a $5,000 bankroll, that is $50. Every trade has a stop loss that enforces this limit. See [Risk and Safety](Risk-Safety.md).

### What if the bot has a bug or crashes?

- Exchange-native stop orders (if placed) remain active even if the bot crashes
- The bot includes a top-level supervisor that auto-restarts after crashes (up to 10 attempts)
- When restarting, it reconciles its position database with the exchange
- See [Risk and Safety](Risk-Safety.md) for the full safety architecture

### Can the bot withdraw money from my exchange?

**No**, as long as you did not enable the "Withdraw Funds" permission when creating your API keys. We explicitly recommend against enabling withdrawal permissions.

### What happens during extreme market events?

Multiple circuit breakers activate:
- Daily loss limit pauses trading
- Consecutive loss detection pauses trading
- Drawdown monitoring pauses trading
- Anomaly detection (if enabled) pauses trading
- Spread gates prevent trading when spreads are abnormally wide

### What is the daily loss limit?

By default, 5% of your bankroll per day. When reached, the bot stops opening new trades for the rest of the UTC day. Existing positions continue to be managed.

---

## Dashboard

### How do I access the dashboard?

Open the URL provided in your welcome email in any web browser. Log in with your credentials.

### Can I access it from my phone?

Yes. The dashboard is responsive and works on phones and tablets. For the best mobile experience, use the Horizon dashboard at [horizonsvc.com](https://horizonsvc.com).

### What does each metric mean?

See [Understanding Metrics](Understanding-Metrics.md) for plain-language explanations of every number on the dashboard.

### How do I pause or resume trading?

Click the Pause/Resume button on the dashboard header, or send `/pause` or `/resume` via Telegram. See [Controls](Controls-Pause-Resume-Kill.md).

### Can multiple people access the dashboard?

Yes. Multiple browser sessions can connect simultaneously and all see the same live data.

---

## AI and Machine Learning

### Does the AI guarantee better trades?

No. The AI improves trade quality over time as it learns from historical data, but it is one input among many. The core strategies and risk management work independently of the AI. See [AI and ML Features](AI-ML-Features.md).

### How long does the AI take to learn?

The TFLite model needs at least 500 trades before training begins. The continuous learner starts adjusting after each trade. The session analyzer needs 5 trades per hour. Full effectiveness typically takes a few weeks of trading.

### What are the v5.0 advanced features?

Ten optional features: event calendar, lead-lag intelligence, regime predictor, on-chain data, structural stops, liquidity sizing, anomaly detection, P&L attribution, ensemble ML, and Bayesian optimizer. All off by default. See [Advanced Features](Advanced-Features.md).

---

## Notifications

### How do I set up Telegram?

See the [Notifications guide](Notifications.md) for step-by-step instructions: create a bot via BotFather, get your chat ID, and configure the bot.

### Can I get notifications without giving the bot control?

Yes. You can receive notifications (trade alerts, check-ins) on all channels. Commands (pause, resume, close_all) require your chat/channel to be in the authorized list.

### Can I use Discord and Telegram at the same time?

Yes. Multiple notification channels can be active simultaneously.

---

## Billing and Plans

### What plans are available?

Nova|Pulse offers Pro and Premium plans. Pro includes core features and single-exchange trading. Premium adds multi-exchange, priority support, and advanced features. See [Billing and Plans](Billing-Plans.md).

### How do I cancel?

Contact support or manage your subscription through Stripe. See [Billing and Plans](Billing-Plans.md).

### Is there a free trial?

Check with Horizon Services for current promotions and trial availability.

---

## Technical

### What programming language is Nova|Pulse written in?

Python (asyncio), running on Python 3.11, 3.12, or 3.13.

### Can I run it on my own server?

Yes, if you have a self-hosted plan. Nova|Pulse runs as a Docker container. You need a server with Python 3.11+, Docker, and internet access to the exchange APIs.

### What database does it use?

SQLite in WAL (Write-Ahead Logging) mode. Separate database files per exchange engine. No external database server required.

### How much server resources does it need?

Minimal. A 1-CPU, 2GB RAM VPS can run Nova|Pulse comfortably. The bot is optimized for low resource usage.

### Can I view the source code?

Nova|Pulse is proprietary software. The source code is not publicly available.

---

## Multi-Exchange

### Does the bot trade the same pair on multiple exchanges?

The engines operate independently. If BTC/USD is configured on both Kraken and Coinbase, each engine evaluates it independently and may or may not trade it. The global risk aggregator prevents combined over-exposure.

### What happens if one exchange goes down?

The other engines continue operating normally. Each exchange has independent connectivity and error handling.

### Does the priority scheduler mean I am missing crypto trades during stock hours?

Yes, by design. The priority scheduler pauses crypto during stock hours (9:30 AM - 4:00 PM ET) to focus resources. This is a deliberate trade-off for systems running both crypto and stocks.

---

## Getting Help

### My question is not here. Who do I contact?

See [Contact Support](Contact-Support.md) for how to reach the Horizon Services team. Include your bot version, a description of the issue, and any relevant thought feed messages or error logs.

---

*Nova|Pulse v5.0.0 -- If you have a question, it probably has an answer here.*

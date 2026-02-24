# Multi-Exchange Trading

**Version:** 4.5.0
**Last updated:** 2026-02-24

NovaPulse is not limited to a single exchange or a single asset class. It can trade across Kraken, Coinbase, and the US stock market simultaneously -- all coordinated from one system, one dashboard, and one risk framework. This guide explains how multi-exchange trading works, why it matters, and what you should know as a subscriber.

---

## Why Trade on Multiple Exchanges?

Imagine a fisherman who only fishes in one pond. Some days that pond is full of fish; other days it is empty. Now imagine a fisherman with lines in three different bodies of water. Even when one is quiet, the others may be active.

That is the core idea behind multi-exchange trading:

- **Diversification:** Different exchanges list different assets and attract different types of traders. By watching all three, NovaPulse sees more opportunities.
- **Different asset classes:** Crypto and stocks behave differently. Crypto trades 24/7 with higher volatility; stocks follow structured market hours with more predictable patterns. Combining both gives NovaPulse access to a wider range of market conditions.
- **Reduced dependency:** If one exchange has downtime or connectivity issues, the others continue operating independently.
- **More data, better AI:** NovaPulse's machine learning models learn from trades across all exchanges. More data means faster learning and better signal quality over time.

---

## The Three Exchanges

### Kraken (Cryptocurrency)

Kraken is NovaPulse's primary crypto exchange and the recommended choice for cryptocurrency trading.

- **Data feed:** Real-time WebSocket (Kraken WS v2). Price updates arrive in milliseconds, giving NovaPulse the freshest possible view of the market.
- **Order execution:** REST API for placing and managing orders.
- **Pairs:** Configurable -- typically BTC/USD, ETH/USD, and other major crypto pairs.
- **Trading hours:** 24/7 (crypto never sleeps).

### Coinbase (Cryptocurrency)

Coinbase Advanced Trade is an alternative crypto exchange that NovaPulse supports alongside Kraken.

- **Data feed:** A combination of REST polling (for historical candles) and WebSocket (for live updates). This hybrid approach ensures reliable data even during brief connectivity hiccups.
- **Order execution:** REST API for placing and managing orders.
- **Pairs:** Configurable -- similar major crypto pairs as Kraken.
- **Trading hours:** 24/7.

### Alpaca (US Stocks)

Alpaca is NovaPulse's broker for US equity (stock) trading.

- **Data feed:** Polygon daily bars for market data. Polygon provides comprehensive stock market data covering thousands of US-listed equities.
- **Order execution:** Alpaca's trading API for buying and selling stocks.
- **Universe:** Up to 96 of the most liquid US stocks, automatically selected and refreshed every 60 minutes during market hours.
- **Trading hours:** US regular market hours only (9:30 AM to 4:00 PM Eastern Time, weekdays).

---

## How the Priority Scheduler Works

One of NovaPulse's most distinctive features is its **priority scheduler** -- an automatic system that coordinates trading across crypto and stock markets so they never compete for attention or resources.

Here is how it works:

```
Weekday Timeline (Eastern Time)
================================================================

12:00 AM  ----  Crypto engines ACTIVE (Kraken + Coinbase)
  |              Stocks engine PAUSED
  |
9:30 AM   ----  US market opens
  |              Crypto engines PAUSE automatically
  |              Stocks engine ACTIVATES
  |
4:00 PM   ----  US market closes
  |              Stocks engine PAUSES
  |              Crypto engines RESUME automatically
  |
11:59 PM  ----  (cycle repeats next weekday)

================================================================
Weekend:   Crypto engines ACTIVE 24/7, Stocks engine PAUSED
```

**Why does it work this way?**

- During US market hours, the stock market offers structured, high-quality trading opportunities. NovaPulse focuses on stocks during this window.
- Outside market hours (evenings, nights, weekends), the stock market is closed, so NovaPulse switches to crypto, which trades around the clock.
- This ensures NovaPulse is always doing something productive, no matter the time of day or day of the week.

**Is this automatic?** Yes, completely. You do not need to do anything. The scheduler monitors the clock and handles the transitions seamlessly. When it pauses a crypto engine, it does not close existing positions -- it simply stops scanning for new trades. Open positions continue to be managed (stop losses, trailing stops) regardless of whether the engine is paused.

---

## Separate Databases, Separate Tracking

Each exchange operates with its own independent database:

| Exchange | Database | What It Tracks |
|----------|----------|---------------|
| Kraken | `trading_kraken_default.db` | All Kraken trades, signals, metrics, P&L |
| Coinbase | `trading_coinbase_default.db` | All Coinbase trades, signals, metrics, P&L |
| Stocks | `trading_stocks_default.db` | All stock trades, signals, metrics, P&L |

**Why separate databases?**

- **Clean accounting:** You can see exactly how each exchange is performing independently.
- **Independent risk management:** Risk limits (daily loss, max positions, exposure) are tracked per exchange. A bad day on Kraken does not affect your stock trading limits.
- **Simpler troubleshooting:** If something looks off on one exchange, the data is cleanly isolated.

Even though the databases are separate, the dashboard combines them into one unified view, so you can see everything at a glance.

---

## The Unified Dashboard

Despite running multiple engines behind the scenes, your dashboard presents a single, unified view:

- **Portfolio summary:** Total P&L across all exchanges, combined win rate, overall equity curve.
- **Per-exchange breakdown:** Drill into Kraken, Coinbase, or Stocks individually to see exchange-specific performance.
- **Active positions:** All open trades from all exchanges in one list, clearly labeled by exchange.
- **Signal scanner:** Shows what each engine is analyzing, with exchange labels so you know which market generated each signal.
- **Thought feed:** The bot's reasoning from all engines, interleaved chronologically.

Think of it like a flight control center: multiple runways (exchanges), but one control tower (your dashboard) watching everything.

---

## How Data Flows Differently Per Exchange

Each exchange provides market data in a different way. NovaPulse adapts to each:

### Kraken: Real-Time WebSocket

```
Kraken Exchange
    |
    |  WebSocket v2 (persistent connection)
    |  Price updates in milliseconds
    v
NovaPulse Kraken Engine
    |
    |  REST API (order placement)
    v
Orders placed on Kraken
```

Kraken's WebSocket connection is a persistent, always-on data stream. NovaPulse receives price updates, order book changes, and trade notifications in near real-time. This is the fastest data path and is ideal for the short-term crypto strategies NovaPulse employs.

### Coinbase: Hybrid REST + WebSocket

```
Coinbase Exchange
    |
    |  REST polling (historical candles, ~60s intervals)
    |  + WebSocket (live price updates)
    v
NovaPulse Coinbase Engine
    |
    |  REST API (order placement)
    v
Orders placed on Coinbase
```

Coinbase uses a hybrid approach. Historical candle data is fetched via REST at regular intervals, while live price updates come through a WebSocket connection. This dual-path design provides reliability: if the WebSocket briefly disconnects, the REST polling ensures NovaPulse still has recent price data.

### Stocks: Polygon Data + Alpaca Execution

```
Polygon (Market Data)
    |
    |  Daily bars via REST API
    |  Universe scanning (volume, price filters)
    v
NovaPulse Stock Engine
    |
    |  REST API (order placement)
    v
Alpaca (Broker)
    Orders executed on US stock market
```

Stock trading uses a split architecture: Polygon provides the market data (daily price bars for the entire stock universe), while Alpaca handles order execution. This separation lets NovaPulse use Polygon's comprehensive data coverage while leveraging Alpaca's commission-free stock trading.

---

## Risk Management Across Exchanges

Each exchange has its own independent risk limits:

- **Daily loss limit:** Tracked per exchange. If Kraken hits its daily loss limit, it pauses. Coinbase and Stocks continue unaffected.
- **Max positions:** Each exchange has its own position cap.
- **Exposure cap:** The maximum percentage of each exchange's bankroll that can be deployed at once.
- **Circuit breakers:** Stale data, disconnects, and consecutive losses are monitored per exchange.

There is also a **global risk layer** that monitors your combined exposure across all exchanges. This prevents a scenario where each individual exchange is within its limits but your total exposure across all three is too high.

---

## Cross-Exchange ML Training

One of the most powerful benefits of multi-exchange trading is cross-exchange learning. NovaPulse's machine learning models can aggregate trade data from all three exchanges:

- The "leader" engine (typically Kraken) collects labeled training data from its own database plus the Coinbase and Stocks databases.
- When the model retrains (weekly by default), it learns from a larger, more diverse dataset.
- Patterns that work across multiple exchanges are given more weight, while exchange-specific noise is filtered out.

Think of it like a student who learns not just from one textbook but from three different textbooks on the same subject. The core concepts that appear in all three are reinforced; the quirks of any single book are naturally de-emphasized.

---

## Frequently Asked Questions

### Do I need accounts on all three exchanges?

No. NovaPulse is fully flexible:

- **Kraken only** -- Trade crypto on Kraken exclusively.
- **Kraken + Coinbase** -- Trade crypto on both exchanges.
- **Kraken + Stocks** -- Trade crypto and stocks.
- **All three** -- The full multi-exchange experience.

Your subscription determines which exchanges are available. Contact support to adjust your exchange configuration.

### Can I run just one exchange?

Absolutely. Many subscribers start with Kraken only and add additional exchanges later. NovaPulse works perfectly well with a single exchange -- the multi-exchange features simply add more breadth when you are ready.

### How is risk managed across exchanges?

Risk is managed at two levels:

1. **Per-exchange:** Each exchange has its own bankroll, daily loss limit, max positions, and exposure cap. They operate independently.
2. **Global:** A cross-exchange risk layer monitors your combined exposure to prevent overcommitment across all exchanges simultaneously.

This means a bad day on one exchange cannot cascade into losses on another. Each exchange stands on its own.

### Will adding more exchanges increase my risk?

Not inherently. Each exchange has its own independent risk limits. Adding an exchange gives NovaPulse more opportunities to find trades, but each trade is still subject to the same rigorous risk checks (position sizing, stop losses, daily loss limits, etc.). The global risk layer ensures your combined exposure stays within safe bounds.

### What happens if one exchange goes down?

The other exchanges continue operating normally. Each engine is independent. If Kraken has an outage, the Coinbase and Stocks engines are unaffected. NovaPulse will also pause the affected engine's trading (circuit breaker) and notify you, then resume automatically when the connection is restored.

### Can I see per-exchange performance separately?

Yes. While the dashboard shows a unified view by default, you can filter and drill into each exchange individually. Each exchange's database tracks its own complete history of trades, signals, and metrics.

### How does the priority scheduler affect my open positions?

When the scheduler pauses an engine (for example, pausing crypto during stock market hours), it only stops scanning for new trades. Existing positions continue to be actively managed -- stop losses are monitored, trailing stops are updated, and positions can be closed normally. No position is ever left unattended.

---

## Summary

| Feature | Kraken | Coinbase | Stocks (Alpaca) |
|---------|--------|----------|-----------------|
| **Asset type** | Cryptocurrency | Cryptocurrency | US equities |
| **Data feed** | Real-time WebSocket | REST + WebSocket | Polygon daily bars |
| **Trading hours** | 24/7 | 24/7 | 9:30 AM - 4:00 PM ET |
| **Order execution** | Kraken REST API | Coinbase REST API | Alpaca REST API |
| **Strategy type** | 9 crypto strategies | 9 crypto strategies | Swing trading |
| **Typical hold time** | Minutes to hours | Minutes to hours | Days |
| **Own database** | Yes | Yes | Yes |
| **Own risk limits** | Yes | Yes | Yes |
| **Paper mode** | Yes | Yes | Yes |

---

*For details on stock trading specifically, see [Stock Trading](Stock-Trading.md).*
*For AI and machine learning features, see [AI and ML Features](AI-ML-Features.md).*
*For risk protections, see [Risk and Safety](Risk-Safety.md).*
*Questions? See our [FAQ](FAQ.md) or [contact support](Contact-Support.md).*

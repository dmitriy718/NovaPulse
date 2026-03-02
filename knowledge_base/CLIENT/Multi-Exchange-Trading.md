# Multi-Exchange Trading

**Version:** 5.0.0
**Last updated:** 2026-03-01

Nova|Pulse is not limited to a single exchange or a single asset class. It can trade across Kraken, Coinbase, and the US stock market simultaneously -- all coordinated from one system, one dashboard, and one risk framework. This guide explains how multi-exchange trading works, why it matters, and what you should know as a subscriber.

---

## Why Trade on Multiple Exchanges?

### Diversification

Different exchanges offer different pairs, different liquidity, and different fee structures. By trading across multiple venues, you spread your exposure and reduce dependence on any single exchange.

### Access to More Markets

- **Kraken** excels at crypto-to-USD pairs with excellent API stability and deep order books
- **Coinbase** offers access to some pairs not available on Kraken
- **Alpaca/Polygon** opens the door to US equity swing trading -- an entirely different asset class with different rhythms

### Risk Isolation

If one exchange experiences an outage or degraded performance, the other engines continue operating independently. Your trading is not completely halted by a single point of failure.

---

## Supported Exchanges

### Kraken (Primary for Crypto)

| Feature | Details |
|---------|---------|
| **Connection** | WebSocket v2 (live data) + REST API (historical data, orders) |
| **Data** | Ticker, OHLC candles, order book, trade stream |
| **Order types** | Limit (with chase), Market (fallback) |
| **Default pairs** | BTC/USD, ETH/USD, SOL/USD, XRP/USD, ADA/USD, DOT/USD, AVAX/USD, LINK/USD |
| **Fees** | Maker 0.16%, Taker 0.26% |

### Coinbase (Secondary for Crypto)

| Feature | Details |
|---------|---------|
| **Connection** | WebSocket (live data) + REST (candle polling, orders) |
| **Data** | Ticker, candles (REST-polled every 60s), order book |
| **Order types** | Limit, Market |
| **Known exclusions** | USDC/USD, TRX/USD, XAUT/USD (permanently excluded, not tradeable pairs) |
| **Fees** | Varies by volume tier |

### Alpaca (Stocks)

| Feature | Details |
|---------|---------|
| **Connection** | REST API for orders and account info |
| **Market data** | Provided by Polygon.io (daily bars) |
| **Order types** | Market orders via Alpaca |
| **Default symbols** | 28 pinned stocks + up to 68 dynamic (96 total universe) |
| **Fees** | Commission-free (Alpaca's standard) |

---

## How Multi-Exchange Mode Works

### Engine Per Exchange

Each exchange runs its own independent engine instance:

- **Kraken engine** -- manages crypto trading on Kraken with its own database, strategies, and risk manager
- **Coinbase engine** -- manages crypto trading on Coinbase with its own database and risk manager
- **Stock engine** -- manages stock swing trading with Polygon data and Alpaca execution

### MultiEngineHub

The MultiEngineHub coordinates all engines:
- Aggregates portfolio data for the unified dashboard view
- Routes control commands (pause, resume, close_all) to all engines
- Manages the priority scheduler

### Unified Dashboard

Even with multiple engines running, you see a single dashboard:
- Portfolio totals are summed across all engines
- Positions show their exchange label (e.g., "BTC/USD (kraken:default)")
- The thought feed combines entries from all engines
- Control buttons affect all engines simultaneously

### Separate Databases

Each engine writes to its own SQLite database:
- `data/trading_kraken_default.db` -- Kraken crypto trades
- `data/trading_coinbase_default.db` -- Coinbase crypto trades
- `data/trading_stocks_default.db` -- Stock trades

This ensures isolation -- a database issue with one engine does not affect the others.

---

## Priority Scheduler

Nova|Pulse uses an intelligent priority scheduler to coordinate between crypto and stock trading:

### During US Market Hours (9:30 AM -- 4:00 PM Eastern, Weekdays)
- **Stock engine: ACTIVE** -- scanning and trading stocks
- **Crypto engines: PAUSED** -- no new crypto trades (existing positions still managed)

### Outside Market Hours
- **Crypto engines: ACTIVE** -- scanning and trading crypto
- **Stock engine: PAUSED** -- stocks cannot trade outside market hours anyway

### Why This Exists

Running all engines at full throttle simultaneously would:
- Spread API rate limits across too many requests
- Compete for the same risk budget
- Create unnecessary complexity during periods when one market is closed anyway

The scheduler ensures focused, efficient operation on the active market.

### What You See

The thought feed will log transitions:
```
Priority schedule PAUSED kraken engine | phase=equities_day_session
Priority schedule RESUMED kraken engine | phase=crypto_after_hours
```

These are normal operational messages, not errors.

---

## Cross-Engine Risk Management

### Global Risk Aggregator

The `GlobalRiskAggregator` tracks total exposure across all engines. Before any engine opens a new position, it checks:

1. **Local capacity** -- does this engine have room for more positions?
2. **Global capacity** -- does the total across all engines have room?

If either check fails, the trade is rejected. This prevents the combined portfolio from becoming over-exposed even if each individual engine looks fine in isolation.

### How It Works

Example with a $5,000 bankroll and 50% max exposure:
- Maximum total exposure across all engines: $2,500
- Kraken has $800 in positions, Coinbase has $600, Stocks has $400
- Total: $1,800 of $2,500 capacity used
- A new Kraken trade wanting $900 would be rejected (would bring total to $2,700)

### Correlation Awareness

The risk system also understands correlation groups:
- BTC/USD on Kraken and BTC/USD on Coinbase are the same asset
- If you are already long BTC on Kraken, opening long BTC on Coinbase counts against the same correlation group

---

## ML Training Across Exchanges

The machine learning system can aggregate training data from all exchange databases:

- The **leader engine** (typically the first configured exchange) runs ML training
- It reads trade data from all exchange databases
- The resulting model is shared across engines
- This gives the ML system a broader dataset to learn from

---

## Configuration

Multi-exchange mode is configured via the `trading_exchanges` or `trading_accounts` settings:

**Simple multi-exchange:**
```yaml
app:
  trading_exchanges: "kraken,coinbase"
```

**Multi-account (advanced):**
```yaml
app:
  trading_accounts: "main:kraken,main:coinbase,swing:kraken"
```

Your operator will set this up based on your subscription and exchange accounts.

---

## What to Expect

### Performance Differences

Each exchange may show different results because:
- Different liquidity affects execution quality
- Different pairs may be available
- Fee structures differ
- Coinbase uses REST-polled candles (60s intervals) vs. Kraken's WebSocket (real-time), which affects signal timing

### Independent but Coordinated

Each engine makes its own trading decisions independently (strategies, confluence, risk). The coordination happens at the risk level (global exposure) and scheduling level (priority scheduler). You will not see the same trade placed on both Kraken and Coinbase simultaneously -- they operate independently.

---

## Common Questions

**Q: Do I need accounts on all three exchanges?**
A: No. You can run with just one exchange. Multi-exchange is an option for those who want it.

**Q: Can I run crypto only or stocks only?**
A: Yes. Stocks can be disabled in the config. You can also run just Kraken, just Coinbase, or any combination.

**Q: Does multi-exchange cost more?**
A: Check your subscription plan. Some plans include multi-exchange; others may require an upgrade. See [Billing and Plans](Billing-Plans.md).

**Q: What happens if one exchange goes down?**
A: The other engines continue operating normally. The affected engine will reconnect automatically when the exchange recovers.

---

*Nova|Pulse v5.0.0 -- One bot, multiple markets, unified control.*

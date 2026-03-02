# Stock Trading

**Version:** 5.0.0
**Last updated:** 2026-03-01

Nova|Pulse is not just a crypto bot -- it also swing-trades US equities (stocks). This guide explains how the stock trading feature works, what makes it different from the crypto side, and what to expect as a subscriber.

---

## What Is Swing Trading?

Swing trading means holding positions for days rather than minutes. While the crypto side of Nova|Pulse makes short-term trades (holding for minutes to hours), the stock side looks for multi-day price swings:

- **Hold period:** 1 to 7 days (configurable)
- **Scanning frequency:** Every 2 minutes during market hours
- **Data source:** Daily bars from Polygon.io
- **Execution:** Market orders via Alpaca brokerage
- **Market hours:** 9:30 AM -- 4:00 PM Eastern, Monday through Friday

---

## How Stock Trading Works

### The Stock Universe

Nova|Pulse maintains a dynamic universe of up to 96 stocks to scan:

**Pinned Stocks (28):** Core stocks that are always scanned:
- Mega-cap tech: AAPL, MSFT, NVDA, TSLA, GOOG, AMZN, META
- Semiconductor: AMD, AVGO, INTC
- Finance: JPM, BAC, GS
- Consumer/Retail: NFLX, DIS, NKE
- Crypto-adjacent: MSTR, COIN, MARA, RIOT, CIFR
- High-beta: PLTR, SOFI, RIVN, LCID, NIO, SNAP

**Dynamic Stocks (up to 68):** Added by the universe scanner based on:
- Minimum average daily volume (300,000 shares)
- Price range ($3 to $2,000)
- Ranked by volume (most liquid first)
- Top movers overlay: 10 biggest gainers + 10 biggest losers are included for momentum/reversal plays

### Universe Refresh

The scanner refreshes every 60 minutes during market hours (plus 30 minutes before open):
1. Fetches grouped daily bars from Polygon.io
2. Filters by volume and price criteria
3. Ranks by trading volume
4. Merges with pinned stocks
5. Caps at 96 total symbols

This ensures the universe stays relevant as market conditions change throughout the day.

---

## The Stock Swing Strategy

The stock engine uses a simplified entry strategy compared to crypto's twelve-strategy confluence:

### Entry Criteria (All Must Be True)

1. **Price above EMA-20 above EMA-50** -- confirms the stock is in an uptrend
2. **RSI between 45 and 72** -- not overbought, not oversold, in the "sweet spot"
3. **Positive 5-day momentum** -- the stock has been gaining recently

When all three conditions align, the stock engine opens a long position.

### Why Simpler Than Crypto?

Stock swing trading uses daily bars (one candle per day), not 1-minute or 5-minute candles. With so much less data per unit of time, the signal-to-noise ratio is different. The strategy focuses on clear trend alignment rather than multi-strategy confluence, which requires higher-frequency data to be meaningful.

---

## Risk Management for Stocks

### Position Sizing

- Maximum position size: $500 per stock (default)
- Maximum open positions: 6 simultaneously
- No correlation group enforcement (stocks are inherently more diverse)

### Stop Loss and Take Profit

- Stop loss: 2% below entry (fixed percentage)
- Take profit: 4% above entry (fixed percentage)
- No smart exit tiers or trailing stops (the daily-bar timeframe makes these less practical)

### Fee Estimation

The engine accounts for estimated fees and slippage:
- Estimated fee: 0.05% per side (Alpaca is commission-free, but market impact exists)
- Estimated slippage: 0.02% per side
- Combined cost estimate: 0.14% round-trip

---

## Priority Scheduling

The priority scheduler coordinates stock and crypto trading:

- **9:30 AM -- 4:00 PM Eastern (weekdays):** Stock engine active, crypto engines paused
- **All other times:** Crypto engines active, stock engine paused

This happens automatically. During market hours, the stock engine scans every 2 minutes and places trades via Alpaca. Outside market hours, it goes dormant.

### Pre-Market

The universe scanner starts refreshing 30 minutes before market open (9:00 AM Eastern) to have fresh data ready when trading begins.

---

## What You See on the Dashboard

Stock positions appear in the positions table with a "(stocks:default)" suffix:

```
AAPL (stocks:default)  LONG  $182.45  $184.20  $500  +$4.80  ...
NVDA (stocks:default)  LONG  $825.30  $831.50  $500  +$3.75  ...
```

Stock-specific metrics in the scanner panel show:
- Universe size (e.g., "96 stocks")
- Which stocks are pinned vs. dynamic
- Last refresh time

---

## Required Accounts and API Keys

### Polygon.io (Market Data)

- **What it provides:** Daily price bars, grouped daily bars for universe scanning
- **Required tier:** Free tier works. The free tier provides grouped daily bars, which is sufficient for the universe scanner. Snapshot endpoints require a paid tier but are not required.
- **API key:** Set via config or `POLYGON_API_KEY` environment variable
- **Rate limit:** 5 requests per minute on free tier (the engine respects this)

### Alpaca (Brokerage)

- **What it provides:** Order execution, position management, account info
- **Account types:** Paper trading (recommended to start) or live trading
- **API keys:** API Key ID + Secret Key, set via config or environment variables
- **Commission:** Free (no per-trade fees)

---

## Paper Trading vs. Live Trading

**Paper mode (default):** The stock engine simulates trades using real market data but does not place actual orders on Alpaca. This is the recommended starting mode.

**Live mode:** Real orders are placed on your Alpaca account. Make sure:
- Your Alpaca account is funded
- You have switched from paper to live API keys
- You are comfortable with the bot's behavior in paper mode first

---

## Differences from Crypto Trading

| Aspect | Crypto | Stocks |
|--------|--------|--------|
| **Hold period** | Minutes to hours | 1-7 days |
| **Strategies** | 12 strategies with confluence | Single trend-alignment strategy |
| **Scan frequency** | Every 15 seconds | Every 2 minutes |
| **Data** | 1-min candles via WebSocket | Daily bars via REST |
| **Exit system** | Smart Exit with tiers + trailing | Fixed SL/TP percentages |
| **Market hours** | 24/7 | 9:30 AM - 4:00 PM ET, weekdays |
| **Max positions** | 10 | 6 |
| **Max position size** | $350 | $500 |
| **Exchanges** | Kraken, Coinbase | Alpaca |

---

## Configuration

Stock trading is configured under the `stocks:` section in config.yaml:

```yaml
stocks:
  enabled: true               # Master switch
  scan_interval_seconds: 120   # Scan every 2 minutes
  lookback_bars: 120           # 120 daily bars for indicators
  min_hold_days: 1             # Minimum 1 day hold
  max_hold_days: 7             # Maximum 7 day hold
  max_open_positions: 6
  max_position_usd: 500.0
  stop_loss_pct: 0.02          # 2% stop loss
  take_profit_pct: 0.04        # 4% take profit
  universe:
    enabled: true
    max_universe_size: 96
    min_avg_volume: 300000
    min_price: 3.0
    max_price: 2000.0
    refresh_interval_minutes: 60
```

---

## Common Questions

**Q: Can I trade stocks only, without crypto?**
A: Yes. Set `stocks.enabled: true` and do not configure any crypto exchanges. Or ask your operator.

**Q: Why are some stocks not in the universe?**
A: The scanner filters by volume and price. Stocks with very low daily volume or extreme prices are excluded. Pinned stocks are always included regardless.

**Q: Can I add specific stocks to always scan?**
A: Yes, via the `stocks.symbols` list in the config. All symbols in that list are treated as pinned.

**Q: Does the bot trade options?**
A: The config includes options support (`options_enabled`), but this feature is currently disabled by default and still in development. Stock trading is limited to shares for now.

**Q: What happens to stock positions over the weekend?**
A: They remain open. The stock engine does not trade on weekends, but existing positions are held. Stop losses are checked when the market reopens Monday.

**Q: Why only long positions for stocks?**
A: The current stock swing strategy focuses on uptrend alignment (price > EMA-20 > EMA-50). Shorting individual stocks involves additional broker requirements and risk, so the strategy is currently long-only.

---

*Nova|Pulse v5.0.0 -- Stocks by day, crypto by night.*

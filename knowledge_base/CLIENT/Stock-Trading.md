# Stock Trading

**Version:** 4.5.0
**Last updated:** 2026-02-24

NovaPulse is not just a crypto bot -- it also swing-trades US equities (stocks). This guide explains how the stock trading feature works, what makes it different from the crypto side, and what to expect as a subscriber.

---

## What Is Swing Trading?

Swing trading means holding positions for days, not minutes. Unlike NovaPulse's crypto strategies, which may open and close trades within hours, the stock engine looks for multi-day price movements and holds positions to capture those larger swings.

**Plain-language analogy:** Think of it as the difference between fishing with a quick-cast rod (crypto -- fast, frequent casts) and fishing with a deep-sea setup (stocks -- fewer casts, bigger catch per cast). Both are fishing, but the technique and patience required are different.

---

## How the Stock Universe Works

NovaPulse does not attempt to trade every stock on the market. Instead, it maintains a **dynamic universe** of up to 96 of the most liquid US stocks.

### The Selection Process

Every 60 minutes during market hours, NovaPulse runs a universe scan:

1. **Data collection:** Polygon provides daily price and volume data for thousands of US-listed stocks.
2. **Filtering:** Stocks are filtered by minimum price and minimum trading volume. This ensures NovaPulse only considers stocks that are liquid enough to trade without excessive slippage.
3. **Ranking:** Qualifying stocks are ranked by trading volume (most liquid first).
4. **Selection:** The top stocks are selected, up to a maximum of 96.

### Pinned Stocks

Four stocks are always included in the universe, regardless of the scan results:

| Stock | Why It Is Pinned |
|-------|-----------------|
| **AAPL** (Apple) | Highest-volume tech stock, extremely liquid |
| **MSFT** (Microsoft) | Major tech bellwether, deep order book |
| **NVDA** (NVIDIA) | AI/semiconductor leader, high volatility and volume |
| **TSLA** (Tesla) | Consistently among the highest-volume names on the market |

These four are pinned because they consistently meet all quality criteria and provide a stable foundation for the universe.

### Dynamic Stocks

The remaining 92 slots are filled dynamically based on the latest volume data. This means the universe adapts as market attention shifts. If a stock suddenly sees a surge in trading volume (perhaps due to earnings, news, or sector rotation), it may enter the universe. If volume dries up, it may be replaced.

**Refresh cycle:** Every 60 minutes during market hours (9:30 AM to 4:00 PM Eastern Time). Outside market hours, the universe holds steady until the next trading session.

---

## The Swing Trading Approach

NovaPulse's stock engine uses a different philosophy from its crypto strategies. Rather than running nine strategies and requiring confluence, the stock engine uses a focused set of technical signals specifically tuned for swing trading.

### Entry Signals

For NovaPulse to open a stock position, **all three** of the following conditions must be met simultaneously:

#### 1. Trend Alignment (EMA Stack)

The stock's price must be above its 20-day Exponential Moving Average (EMA20), and the EMA20 must be above the 50-day Exponential Moving Average (EMA50).

**What this means in plain language:** The stock is in an uptrend on both a short-term and medium-term basis. The price is not just rising -- it is rising in a structured, healthy way where the shorter-term average leads the longer-term average.

```
Price ---- above ----> EMA20 ---- above ----> EMA50
(current)              (short-term trend)      (medium-term trend)

All three aligned = healthy uptrend
```

#### 2. RSI Sweet Spot (45 to 72)

The Relative Strength Index (RSI) must be between 45 and 72.

**What this means in plain language:** RSI measures how "overbought" or "oversold" a stock is on a scale of 0 to 100. NovaPulse looks for the sweet spot:

- **Below 45:** The stock might be weakening -- too risky for a swing buy.
- **45 to 72:** The stock has momentum but is not overextended. This is the "Goldilocks zone" for swing entries.
- **Above 72:** The stock may be overbought and due for a pullback -- too late to enter.

#### 3. Positive 5-Day Momentum

The stock must show positive price momentum over the last 5 trading days.

**What this means in plain language:** Price has been moving upward recently. This confirms that the trend alignment (condition 1) is not stale -- there is fresh energy behind the move.

### Why All Three Must Agree

Requiring all three conditions to be met simultaneously is the stock engine's version of confluence. Each condition catches a different type of false signal:

- Trend alignment without momentum could be a stale, fading trend.
- Momentum without trend alignment could be a brief bounce in a downtrend.
- Good RSI without the other two could be a random fluctuation.

When all three agree, the probability of a genuine, tradeable swing setup increases substantially.

---

## Market Hours and the Priority Scheduler

Stock trading operates exclusively during **US regular market hours**: 9:30 AM to 4:00 PM Eastern Time, Monday through Friday (excluding market holidays).

NovaPulse's priority scheduler handles this automatically:

- **Market opens (9:30 AM ET):** The crypto engines pause scanning, and the stock engine activates.
- **Market closes (4:00 PM ET):** The stock engine pauses, and the crypto engines resume.
- **Weekends and holidays:** The stock engine remains paused; crypto engines run continuously.

This means you never need to manually switch between crypto and stock modes. NovaPulse handles it seamlessly.

**Important note about open stock positions:** When the market closes, any open stock positions remain open. They are not automatically closed at 4:00 PM. Swing trades are designed to be held for days, so positions carry overnight and through weekends as needed. NovaPulse will continue monitoring them when the market reopens.

---

## Data and Execution: Polygon + Alpaca

NovaPulse's stock trading uses two separate services:

### Polygon (Market Data)

Polygon provides the raw market data -- daily price bars for each stock in the universe. This includes open, high, low, close prices and trading volume for each day.

- **Data type:** Daily bars (one data point per trading day per stock).
- **Coverage:** Thousands of US-listed stocks.
- **Refresh:** Updated throughout the trading day as new bars form.

### Alpaca (Order Execution)

Alpaca is the broker that executes your stock trades. When NovaPulse decides to buy or sell a stock, the order is sent to Alpaca, which routes it to the stock market for execution.

- **Commission-free:** Alpaca does not charge trading commissions on US stocks.
- **Paper mode:** Alpaca provides a fully functional paper trading environment for testing.
- **Fractional shares:** Not currently used -- NovaPulse trades in whole shares.

**Why two services?** Splitting data and execution lets NovaPulse use the best tool for each job. Polygon excels at comprehensive market data; Alpaca excels at reliable, commission-free order execution.

---

## How Stock Trading Differs from Crypto

Understanding the key differences helps set expectations:

| Aspect | Crypto (Kraken/Coinbase) | Stocks (Alpaca) |
|--------|--------------------------|-----------------|
| **Trading hours** | 24/7 | 9:30 AM - 4:00 PM ET weekdays |
| **Hold time** | Minutes to hours | Days |
| **Strategies** | 9 strategies with confluence | Swing signals (EMA + RSI + momentum) |
| **Data frequency** | 1-minute candles, real-time | Daily bars |
| **Universe** | 5-15 configured pairs | Up to 96 dynamically selected stocks |
| **Volatility** | Higher (crypto swings can be large) | Lower (stocks tend to move more gradually) |
| **Scan interval** | Every 60 seconds | Every 120 seconds |
| **Signal approach** | Multi-strategy confluence | All-conditions-must-agree filter |

### Why the Different Approach?

Crypto and stocks are fundamentally different markets:

- **Crypto** moves fast and unpredictably. Nine strategies with a confluence requirement help filter the noise and find high-quality short-term opportunities in a chaotic environment.
- **Stocks** follow more structured patterns, with earnings cycles, sector rotations, and market hours creating more predictable behavior. A focused swing approach with clear technical criteria is well-suited to capture multi-day moves.

NovaPulse uses the right tool for each market rather than forcing one approach onto both.

---

## Paper Mode for Stocks

Just like the crypto side, NovaPulse supports **paper trading** for stocks. In paper mode:

- Real market data from Polygon is used -- you see actual stock prices and actual signals.
- Trades are simulated through Alpaca's paper trading environment -- no real money is at risk.
- All metrics (P&L, win rate, number of trades) are tracked as if they were real.
- The dashboard looks and works identically to live mode.

We recommend running stock trading in paper mode for at least one to two weeks before going live, especially if you are new to swing trading.

---

## Position Sizing for Stocks

The stock engine uses the same core risk principles as the crypto side:

- **Risk per trade:** A fixed percentage of your stock bankroll (default 2%).
- **Maximum position size:** Capped in dollar terms to prevent oversized bets.
- **Kelly Criterion:** Position size is calculated using the Kelly formula (at a conservative quarter-Kelly fraction), factoring in recent win rate and average win/loss ratio.

Because stock swing trades are held longer, position sizes tend to be moderate -- large enough to capture meaningful gains, but small enough that a losing trade does not significantly impact your account.

---

## What You See on the Dashboard

Stock trades appear on your dashboard alongside crypto trades, clearly labeled:

- **Position list:** Stock positions show the stock ticker (e.g., "AAPL"), entry price, current price, unrealized P&L, and holding period.
- **Signal scanner:** When the stock engine identifies potential swing setups, they appear in the scanner with a "stocks" label.
- **Performance metrics:** Stock P&L is tracked separately in the per-exchange breakdown and combined in the overall portfolio view.

---

## Frequently Asked Questions

**Do I need a separate Alpaca account?**
Yes. You need an Alpaca brokerage account (or Alpaca paper account for testing). NovaPulse uses your Alpaca API keys to place orders on your behalf. Signing up at Alpaca is free.

**Can I choose which stocks NovaPulse trades?**
The four pinned stocks (AAPL, MSFT, NVDA, TSLA) are always included. The remaining 92 are selected dynamically based on liquidity. You cannot manually add or remove individual stocks from the dynamic universe, but you can adjust the maximum universe size through configuration.

**What if a stock gaps down overnight?**
Swing trades carry overnight risk, which is inherent to the approach. NovaPulse accounts for this by using conservative position sizing and setting stop losses that accommodate normal overnight price movement. However, extreme overnight gaps (e.g., a company reporting terrible earnings after hours) can cause losses beyond the stop level. This is a known limitation of all swing trading systems.

**Why only 96 stocks?**
The universe size balances breadth with quality. Scanning too many stocks would dilute focus onto less-liquid names. 96 stocks provides excellent coverage of the most actively traded US equities while keeping the universe manageable and high-quality.

**Can I run stocks without crypto?**
NovaPulse is designed as a multi-engine system, but you can configure it to run only the stock engine. Contact support to adjust your configuration.

**What about dividends?**
Dividends from stocks held in your Alpaca account are handled by Alpaca according to their standard policies. NovaPulse does not factor dividend dates into its trading signals.

---

*For details on multi-exchange trading, see [Multi-Exchange Trading](Multi-Exchange-Trading.md).*
*For risk protections, see [Risk and Safety](Risk-Safety.md).*
*For AI features that enhance stock trading, see [AI and ML Features](AI-ML-Features.md).*
*Questions? See our [FAQ](FAQ.md) or [contact support](Contact-Support.md).*

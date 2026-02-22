# Configuration Guide

**Last updated:** 2026-02-22

NovaPulse comes pre-configured with sensible defaults, but you can customize many settings to match your trading style and risk tolerance. This guide explains what each setting does and when you might want to change it.

---

## How to Access Settings

You can view and adjust settings through:

1. **Dashboard Settings Panel** -- Click the gear icon on your dashboard. This is the easiest way for most users.
2. **Contact Support** -- For settings that require server-side changes, contact support and they will make the adjustment for you.

> **Important:** Some settings (particularly mode changes and exchange configuration) can only be modified by support for safety reasons. The dashboard will indicate which settings you can change yourself.

---

## Mode Selection

| Mode | Description | When to Use |
|------|-------------|-------------|
| **Paper** | Simulated trading. No real orders placed. Uses real market data. | Getting started, testing new settings, verifying behavior |
| **Live** | Real trading. Actual orders placed on your exchange. | When you are confident and ready to trade with real money |
| **Canary** | Ultra-conservative live trading. Tiny positions, limited pairs, high confidence threshold. | First time going live -- minimizes risk while verifying real execution |

### Paper Mode (Default)

- Trades are simulated internally
- No orders are sent to your exchange
- P&L tracking is identical to live mode
- All dashboard features work normally
- Perfect for learning and testing

### Canary Mode (Recommended for First Live Trading)

Canary mode is live trading with training wheels. It uses much tighter limits:

| Setting | Normal Live | Canary Mode |
|---------|------------|-------------|
| Trading pairs | All configured pairs | 1-2 pairs only |
| Max position size | $500 | $100 |
| Risk per trade | 2% | 0.5% |
| Min confidence | 0.65 | 0.68 |
| Min confluence | 3 | 3 |

**When to use Canary Mode:** When switching from paper to live for the first time. Run in canary mode for a few days to verify that real-money execution works correctly, that orders fill as expected, and that you are comfortable with the process. Then graduate to full live mode.

---

## Trading Pairs

You can configure which cryptocurrency pairs NovaPulse monitors and trades. Common pairs include:

| Pair | What It Is |
|------|-----------|
| BTC/USD | Bitcoin vs US Dollar |
| ETH/USD | Ethereum vs US Dollar |
| SOL/USD | Solana vs US Dollar |
| ADA/USD | Cardano vs US Dollar |
| DOT/USD | Polkadot vs US Dollar |
| LINK/USD | Chainlink vs US Dollar |
| AVAX/USD | Avalanche vs US Dollar |
| MATIC/USD | Polygon vs US Dollar |

**Considerations when choosing pairs:**
- More pairs = more opportunities, but also more complexity
- Major pairs (BTC/USD, ETH/USD) have the deepest liquidity and tightest spreads
- Smaller pairs may have wider spreads, which increases trading costs
- Each pair is scanned independently, so adding pairs does not slow down the bot

**How to change:** Adjust in the settings panel or contact support.

---

## Risk Settings

These are the most important settings to understand. They control how much capital is at risk.

### Risk Per Trade

**What it controls:** The maximum percentage of your bankroll that can be risked on a single trade.

**Default:** 2% (0.02)

**Range:** 0.1% to 10%

**Guidance:**
- 1-2%: Conservative (recommended for most users)
- 2-3%: Moderate
- 3-5%: Aggressive (higher potential returns, but higher drawdowns)
- Above 5%: Very aggressive -- not recommended for most users

**Example:** With a $10,000 bankroll and 2% risk per trade, the maximum you can lose on a single trade is $200.

---

### Max Position Size

**What it controls:** The maximum dollar amount that can be invested in a single trade.

**Default:** $500

**Guidance:** Set this based on your comfort level and bankroll. As a rule of thumb, it should not exceed 10% of your bankroll.

---

### Initial Bankroll

**What it controls:** The amount of capital NovaPulse considers as your trading bankroll. All percentage-based limits are calculated relative to this number.

**Default:** $10,000

**Important:** This should match the amount of capital you have allocated for trading on your exchange. If you have $5,000 set aside for trading, set the bankroll to $5,000.

---

### Max Daily Loss

**What it controls:** If total realized losses in a single day exceed this percentage of bankroll, the bot automatically pauses.

**Default:** 5%

**Guidance:**
- 3-5%: Standard range
- Setting this too tight (e.g., 1%) may cause frequent auto-pauses even during normal market activity
- Setting this too loose (e.g., 15%) reduces the protective benefit

---

### Max Total Exposure

**What it controls:** The maximum percentage of your bankroll that can be deployed in open positions at any time.

**Default:** 50%

**Example:** With a $10,000 bankroll and 50% max exposure, the bot will never have more than $5,000 in open positions combined.

---

### Max Concurrent Positions

**What it controls:** The maximum number of trades that can be open at the same time.

**Default:** 5

**Guidance:** Lower numbers are more conservative. With 5 max positions and $500 max per position, your worst-case open exposure is $2,500.

---

## Signal Settings

### Confidence Threshold

**What it controls:** The minimum signal strength required to enter a trade.

**Default:** 0.65 (65%)

**Guidance:**
- Higher threshold (0.70-0.80): Fewer trades, but potentially higher quality
- Lower threshold (0.55-0.65): More trades, but more marginal signals
- We recommend keeping this at 0.65 or higher

---

### Confluence Threshold

**What it controls:** The minimum number of strategies that must agree before a trade is taken.

**Default:** 3 (out of 9 strategies)

**Guidance:**
- 2: More trades, but lower agreement threshold -- more false signals
- 3: Balanced (recommended)
- 4-5: Very selective -- fewer trades but higher conviction
- Higher values mean fewer but potentially better trades

---

## Strategy Settings

### Enabling and Disabling Strategies

You can enable or disable individual strategies from the settings panel. Each strategy has an on/off toggle.

**Our recommendation:** Keep all strategies enabled. Weak strategies are naturally filtered out by the confluence system (they get outvoted), and you might miss opportunities if you disable a strategy that happens to catch a move the others miss.

**If you do want to disable a strategy:** Consider doing so based on performance data (check the Strategy Performance panel on the dashboard) rather than gut feeling.

### Single Strategy Mode

For advanced users or testing: you can configure NovaPulse to run only one specific strategy, bypassing the confluence requirement. This is primarily for testing purposes and is NOT recommended for live trading.

---

## Stop Loss and Take Profit Settings

### ATR Multipliers

**Stop Loss multiplier:** How many ATR units away the stop loss is placed. Default: 2.0x ATR.

**Take Profit multiplier:** How many ATR units away the take profit is placed. Default: 3.0x ATR.

**Guidance:** The defaults provide a 1.5:1 risk-reward ratio (TP is 1.5x further than SL). Widening stops (higher multiplier) means fewer stop-outs but larger losses when stops hit. Tightening stops means more stop-outs but smaller individual losses.

### Trailing Stop Settings

| Setting | Default | What It Controls |
|---------|---------|-----------------|
| Trailing activation | 1.5% profit | How much profit before trailing stop activates |
| Trailing step | 0.5% | How closely the stop follows the price |
| Breakeven activation | 1.0% profit | How much profit before stop moves to breakeven |

---

## Quiet Hours

You can configure hours during which NovaPulse will NOT open new trades. Existing positions are still managed normally.

**Default:** No quiet hours (24/7 trading)

**When to use:** If you notice that trading during certain hours consistently underperforms (e.g., very late-night hours with low liquidity), you can exclude those hours.

**Format:** UTC hours (0-23). For example, setting quiet hours to [2, 3, 4, 5] means no new trades between 2:00 and 5:59 UTC.

---

## Smart Exit System

**What it is:** An optional feature that takes partial profits at multiple price levels instead of one big exit.

**Default:** Disabled

**How it works when enabled:**
1. At 1x take profit distance: Close 50% of the position
2. At 1.5x take profit distance: Close 30% more
3. Remaining 20%: Managed by trailing stop

**When to enable:** If you find that many of your winning trades hit the take profit but then reverse before you can capture the full move. Smart exits sacrifice some upside for more reliable profit capture.

---

## Canary Mode Settings

These settings only apply when canary mode is enabled:

| Setting | Default | What It Controls |
|---------|---------|-----------------|
| Canary pairs | (none -- must be set) | Which pairs to trade in canary mode |
| Max pairs | 2 | Maximum number of pairs active in canary mode |
| Max position size | $100 | Maximum dollar amount per trade |
| Risk per trade | 0.5% | Maximum risk per trade |
| Min confidence | 0.68 | Higher confidence threshold for safety |
| Min confluence | 3 | Minimum strategy agreement |

---

## When to Change Settings (and When Not To)

**Good reasons to change settings:**
- Your bankroll has changed significantly (update initial bankroll)
- You want to trade additional pairs (add pairs)
- Your risk tolerance has changed (adjust risk per trade, max daily loss)
- Performance data suggests a setting change (e.g., raising confluence threshold after seeing too many false signals)
- You are graduating from paper to canary to live mode

**Bad reasons to change settings:**
- Reacting emotionally to a single losing trade (losses are normal)
- Trying to "recover" losses by increasing risk (this usually makes things worse)
- Changing settings too frequently without giving them time to show results
- Tweaking settings based on a few days of data (wait at least 2-4 weeks)

**A good rule of thumb:** Make one change at a time, document why you made it, and wait at least 2 weeks before evaluating the results.

---

## Default Settings Quick Reference

| Category | Setting | Default |
|----------|---------|---------|
| **Mode** | Trading mode | Paper |
| **Pairs** | Trading pairs | BTC/USD, ETH/USD |
| **Scanning** | Scan interval | 60 seconds |
| **Signal** | Min confidence | 0.65 |
| **Signal** | Min confluence | 3 strategies |
| **Risk** | Risk per trade | 2% |
| **Risk** | Max position size | $500 |
| **Risk** | Max daily loss | 5% |
| **Risk** | Max exposure | 50% |
| **Risk** | Max positions | 5 |
| **Risk** | Initial bankroll | $10,000 |
| **Stops** | Trailing activation | 1.5% profit |
| **Stops** | Breakeven activation | 1.0% profit |
| **Stops** | Trailing step | 0.5% |
| **Exits** | Smart exits | Disabled |
| **Safety** | Consecutive loss pause | 4 losses |
| **Safety** | Drawdown pause | 8% |
| **Safety** | Loss cooldown | 30 minutes |

---

*For detailed explanations of all metrics, see [Understanding Metrics](Understanding-Metrics.md).*
*For risk and safety features, see [Risk and Safety](Risk-Safety.md).*

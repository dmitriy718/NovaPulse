# Smart Exit System

**Version:** 4.5.0
**Last updated:** 2026-02-24

Getting into a trade at the right time is important. But getting out at the right time is just as important -- perhaps more so. A perfectly timed entry can still result in a loss if the exit is poorly managed. NovaPulse's Smart Exit System is designed to protect profits, limit losses, and adapt to changing market conditions as a trade progresses.

---

## Why Exits Matter as Much as Entries

Consider two traders who enter the same trade at the same time and price:

- **Trader A** sets a fixed take-profit and walks away. The price rises to within a hair of the target, then reverses all the way back. Trader A's winning trade turns into a loss.
- **Trader B** uses partial exits and trailing stops. When the price rises, Trader B locks in half the profit early. When the price reverses, the trailing stop catches the rest. Trader B walks away with a solid gain.

Same entry. Different exits. Completely different outcomes.

NovaPulse's Smart Exit System is designed to behave like Trader B -- taking profits along the way, tightening stops as conditions change, and never letting a good trade turn into a bad one.

---

## Multi-Tier Partial Closing

The core of the Smart Exit System is **multi-tier partial closing** -- instead of waiting for a single price target and closing the entire position at once, NovaPulse closes portions of the position at different profit levels.

### The Three Tiers

| Tier | Trigger | Action | Purpose |
|------|---------|--------|---------|
| **Tier 1** | Price reaches 1x the take-profit distance | Close 50% of the position | Lock in half the profit immediately |
| **Tier 2** | Price reaches 1.5x the take-profit distance | Close 30% of the position | Capture more of the extended move |
| **Tier 3** | Trailing stop catches remainder | Close the final 20% | Let the last piece ride as far as possible |

### Example: A BTC/USD Long Trade

Let us walk through a concrete example:

```
Entry price:              $64,000
Take-profit target:       $65,200 (1.875% above entry)
Stop loss:                $62,800 (1.875% below entry)
Position size:            0.10 BTC ($6,400)

The take-profit distance is $1,200 (from entry to TP target).
```

**Tier 1 triggers** when price reaches $65,200 (1x the TP distance):
```
Price hits $65,200
Action: Close 50% of position (0.05 BTC)
Profit locked in: 0.05 x $1,200 = $60
Remaining position: 0.05 BTC
```

**Tier 2 triggers** when price reaches $65,800 (1.5x the TP distance):
```
Price hits $65,800
Action: Close 30% of original position (0.03 BTC)
Profit locked in: 0.03 x $1,800 = $54
Remaining position: 0.02 BTC (final 20%)
```

**Tier 3** -- the final 20% rides with a trailing stop:
```
Price continues to $66,400, then reverses
Trailing stop catches at $66,100
Action: Close final 0.02 BTC
Profit locked in: 0.02 x $2,100 = $42

Total profit: $60 + $54 + $42 = $156
```

Compare this to a **flat exit** at the original $65,200 target:
```
Close entire 0.10 BTC at $65,200
Total profit: 0.10 x $1,200 = $120
```

In this example, the tiered approach captured $156 versus $120 -- a 30% improvement.

**But what if the price reverses after Tier 1?** Then you have already locked in $60 of profit on 50% of the position. The remaining 50% may be caught by the trailing stop at a lower level, or even at breakeven. Either way, you are better off than having held the entire position through the reversal.

---

## Dynamic Trailing Stops

Every trade in NovaPulse (whether or not Smart Exit is enabled) is protected by a **dynamic trailing stop**. This is a stop loss that moves in your favor as the price moves in your favor.

### How Trailing Stops Work

1. **Starting point:** When a trade is opened, a fixed stop loss is set based on the ATR (Average True Range) -- a measure of recent volatility. This initial stop accounts for normal market noise.

2. **Activation:** Once the trade is profitable by 1.5% (by default), the trailing stop activates.

3. **Trailing behavior:** From that point, the stop loss follows the price:
   - For long trades: the stop rises as price rises, but never falls.
   - For short trades: the stop falls as price falls, but never rises.
   - The trailing distance is 0.5% by default (the "step size").

4. **Acceleration:** As profits grow, the trailing stop tightens:
   - At 3%+ profit: the trailing distance narrows to 0.25% (half the normal step).
   - At 5%+ profit: the trailing distance narrows to 0.15% (locking in gains aggressively).

**Plain-language analogy:** Imagine climbing a mountain with a safety rope that a belayer pulls tighter as you ascend. Early in the climb (small profit), the rope has some slack -- you might fall a bit before it catches you. But the higher you go (bigger profit), the tighter the belayer pulls the rope. At the peak, the rope is so tight that any slip is caught almost immediately.

```
Example: Long trade from $100

Price: $100 -> $102 -> $104 -> $106 -> $108 -> $106 -> $104
Stop:  $97  -> $97  -> $101.4 -> $103.4 -> $107.5 -> $107.5 -> CLOSED
                       ^activated          ^tightened
                                                      Profit: $4
```

---

## Breakeven Activation

Once a trade reaches **1% profit** from the entry price, the stop loss is moved to the entry price. This is called "breakeven activation."

**What this means:** After the stop moves to breakeven, the trade can no longer result in a loss (ignoring fees). The worst outcome is exiting at the price you entered.

**Why it matters:** Many trades move into profit but then reverse. Breakeven activation ensures that once a trade has shown it can be profitable, you are protected from it turning into a loss.

### How It Fits with Trailing Stops

Breakeven activation kicks in before the trailing stop activates:

```
Profit level:    0%         1%              1.5%             3%+
                 |          |               |                |
Action:          Initial    Breakeven       Trailing stop    Accelerated
                 stop       activation      activates        trailing
                 loss       (stop → entry)  (stop follows    (tighter
                                            price)           step)
```

This creates a smooth progression: the initial stop protects against large losses, breakeven eliminates the possibility of a loss entirely, and the trailing stop then locks in ever-increasing profit.

---

## Time-Based Exit Tightening

Not all trades move quickly in your favor. Some trades enter and then just sit there -- price drifts sideways, neither hitting the take-profit target nor the stop loss. NovaPulse recognizes that a stagnant position is tying up capital and opportunity.

### How It Works

NovaPulse monitors how long a trade has been open and how much progress it has made toward its target:

| Condition | Action |
|-----------|--------|
| **30+ minutes open** and less than 0.5% profit | Take-profit target reduced to 60% of original distance |
| **60+ minutes open** and less than 1% profit | Take-profit target reduced to 40% of original distance |

### Example

```
Original trade:
  Entry: $64,000
  Take profit: $65,200 (TP distance = $1,200)

After 30 minutes with only 0.3% profit:
  Take profit tightened to 60%: $64,000 + ($1,200 x 0.6) = $64,720

After 60 minutes with only 0.8% profit:
  Take profit tightened to 40%: $64,000 + ($1,200 x 0.4) = $64,480
```

**Why this matters:** A trade that was expected to move quickly but has not is often a sign that the signal was weaker than anticipated. By reducing the target, NovaPulse takes what is available rather than holding indefinitely for a target that may never be reached. The freed-up capital can then be deployed on a fresh, stronger opportunity.

**Important:** Time-based tightening only affects the take-profit level. The stop loss and trailing stop continue operating normally. NovaPulse never widens risk -- it only narrows the profit target.

---

## Volatility-Regime-Aware Stops

NovaPulse continuously monitors the market's volatility regime (high, medium, or low) and adjusts trailing stop behavior accordingly.

### How It Works

| Volatility Regime | Trailing Step Adjustment | Why |
|-------------------|--------------------------|-----|
| **High volatility** | Step widened by 50% (e.g., 0.5% becomes 0.75%) | Volatile markets have larger natural swings. A tighter stop would get triggered by normal noise, closing profitable trades prematurely. |
| **Normal volatility** | Standard step (0.5%) | Default behavior. |
| **Low volatility** | Step narrowed by 30% (e.g., 0.5% becomes 0.35%) | Calm markets have smaller swings. A wider stop would give back too much profit unnecessarily. |

**Plain-language analogy:** Imagine you are walking a dog on a leash. In an open field (calm market), you keep the leash short -- there is no reason to give lots of slack. In a crowded, chaotic environment (volatile market), you let the leash out longer so the dog has room to navigate without constantly pulling you off balance. The leash length (trailing stop distance) adapts to the environment.

### How Regime Is Detected

NovaPulse classifies the current volatility regime using multiple indicators:

- ATR (Average True Range) relative to recent history
- Bollinger Band width
- Price range relative to its moving average

This classification happens on every scan cycle, so the regime label is always current. When a trade is opened, the current regime is stored with the trade's metadata. As the trailing stop is updated, this regime information adjusts the step size.

---

## Exchange-Native Stop Orders

All of the features described above -- trailing stops, breakeven, tiered exits -- are managed by NovaPulse's software. But what happens if NovaPulse itself has an issue? What if the server restarts, loses connectivity, or experiences an unexpected error?

This is where **exchange-native stop orders** come in.

### How It Works

When NovaPulse opens a live trade (not paper mode), it immediately places a **stop-loss order directly on the exchange**. This order lives on the exchange's own servers, completely independent of NovaPulse.

```
NovaPulse places trade (buy BTC at $64,000)
    |
    +--> Also places stop-loss order on exchange at $62,800
         (this order is on Kraken/Coinbase's servers, not ours)
    |
    +--> NovaPulse monitors and adjusts the stop as usual
         |
         +--> When trailing stop moves, exchange stop is updated too
```

**If NovaPulse goes offline:**
- The exchange's own stop order is already in place.
- If price hits the stop level, the exchange executes the stop automatically.
- Your position is protected regardless of what happens to NovaPulse.

**When NovaPulse comes back online:**
- It reconciles with the exchange to determine if the stop was triggered.
- If the position was closed by the exchange stop, NovaPulse records it and moves on.
- If the position is still open, NovaPulse resumes normal management.

### Stop Updates

As NovaPulse moves the trailing stop (or activates breakeven), it also updates the exchange-native stop order. The exchange stop is only updated when the stop price moves by more than 0.5%, to avoid excessive order cancellations.

When a trade is closed (for any reason), NovaPulse cancels the exchange-native stop order to keep things clean.

**This is your crash-proof safety net.** Even in the worst-case scenario -- complete server failure during a market crash -- your exchange's own stop order stands ready to protect your position.

---

## How It All Works Together

Here is the complete lifecycle of a trade's exit management:

```
Trade opened
    |
    v
Initial stop loss set (ATR-based, 2x ATR from entry)
Exchange-native stop placed on exchange
    |
    |-- Price reaches 1% profit -->  Breakeven activation
    |                                (stop moved to entry price)
    |                                Exchange stop updated
    |
    |-- Price reaches 1.5% profit -> Trailing stop activates
    |                                (stop follows price, 0.5% step)
    |                                Exchange stop updated
    |
    |-- [If Smart Exit enabled] ---> Tier 1 at 1x TP distance
    |   Price reaches 1x TP          Close 50% of position
    |
    |-- Price reaches 3%+ profit --> Trailing step accelerates
    |                                (0.25% step, tighter)
    |                                Exchange stop updated
    |
    |-- [If Smart Exit enabled] ---> Tier 2 at 1.5x TP distance
    |   Price reaches 1.5x TP        Close 30% of position
    |
    |-- Price reaches 5%+ profit --> Maximum acceleration
    |                                (0.15% step, very tight)
    |
    |-- 30 min with < 0.5% gain --> Time-based TP tightening (60%)
    |-- 60 min with < 1% gain ----> Time-based TP tightening (40%)
    |
    |-- Price reverses ------------> Trailing stop catches reversal
    |                                Final 20% closed (Tier 3)
    |                                Exchange stop cancelled
    |
    v
Trade closed. P&L recorded. ML model updated.
```

Each layer builds on the ones before it. Together, they create a comprehensive exit system that adapts to what the market is actually doing rather than relying on a single, rigid exit rule.

---

## Smart Exit: Enabled vs. Disabled

The multi-tier partial closing feature (Tiers 1, 2, and 3) is an optional enhancement that must be enabled in your configuration. It is **disabled by default**.

**When Smart Exit is disabled:**
- Trades use a single take-profit target (standard behavior).
- Trailing stops, breakeven activation, time-based tightening, volatility-aware stops, and exchange-native stops all still work.
- This is a simpler approach that works well for most market conditions.

**When Smart Exit is enabled:**
- Trades use the three-tier partial closing system described above.
- All other exit features (trailing stops, breakeven, etc.) still apply.
- This approach is more sophisticated and tends to capture more profit on extended moves, at the trade-off of slightly more complexity in position management.

If you are interested in enabling Smart Exit, contact support or see the [Configuration Guide](Configuration-Guide.md).

---

## Frequently Asked Questions

**Can I adjust the tier percentages?**
Yes. The default tiers (50% at 1x, 30% at 1.5x, 20% trailing) can be adjusted through the configuration. Contact support if you want to customize them.

**Does the trailing stop work in paper mode?**
Yes. All exit features -- trailing stops, breakeven, time-based tightening, and Smart Exit tiers -- work identically in paper mode and live mode. The only difference is that exchange-native stop orders are not placed in paper mode (since no real orders are on the exchange).

**What if the market gaps past my stop loss?**
In extreme cases (flash crashes, exchange outages), the market price may jump past your stop level without triggering it at the exact price. This is called "slippage" and is a limitation of all stop-loss systems, not specific to NovaPulse. Exchange-native stops help mitigate this (the exchange itself executes the stop), but they cannot eliminate gap risk entirely.

**Do time-based exit changes affect my stop loss?**
No. Time-based tightening only adjusts the take-profit level. Your stop loss and trailing stop continue operating at their current levels. NovaPulse never increases risk on an existing trade.

**How does the system handle the final 20% if Smart Exit is enabled?**
The final 20% of the position is managed entirely by the trailing stop. There is no fixed profit target for this last portion -- it rides until the trailing stop catches a reversal. This means the final piece has unlimited upside potential while still being protected by the trailing mechanism.

**What is the "hold duration optimization"?**
In addition to time-based TP tightening, NovaPulse tracks the average winning hold time for each strategy. If a trade has been open for more than twice the average winning duration for its strategy, the trailing stop is tightened to 50% of its current distance. This prevents "hope trades" -- positions that have overstayed their welcome and are unlikely to reach their target.

---

*For details on risk protections, see [Risk and Safety](Risk-Safety.md).*
*For how AI scores affect exit decisions, see [AI and ML Features](AI-ML-Features.md).*
*For dashboard controls, see [Controls: Pause, Resume, Kill](Controls-Pause-Resume-Kill.md).*
*Questions? See our [FAQ](FAQ.md) or [contact support](Contact-Support.md).*

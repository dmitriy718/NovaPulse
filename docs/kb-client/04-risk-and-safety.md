# Risk and Safety

## Core safety rules

- Start in paper mode until you trust behavior.
- Use conservative `risk.max_risk_per_trade` and `risk.max_position_usd`.
- Use `risk.max_daily_loss` to prevent runaway loss days.
- Use the spread filter (`trading.max_spread_pct`) to avoid illiquid fills.

## How sizing works (high level)

The bot uses risk controls that combine:
- fixed fractional sizing caps,
- Kelly-based sizing (conservative fraction),
- drawdown scaling,
- max exposure limits.

## Stops and trailing

Stops are managed continuously by the position management loop.
Trailing and breakeven activation depend on config thresholds.


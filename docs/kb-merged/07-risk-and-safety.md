# Risk and Safety

## Core Safety Rules (Client)

1. Start in paper mode.
1. Do not run live without understanding risk limits.
1. Pause trading when data is stale or when you are unsure.
1. Avoid changing multiple knobs at once.

## Risk Limits (What They Do)

Typical limits:

1. `risk.max_risk_per_trade` bounds per-trade risk.
1. `risk.max_daily_loss` blocks new entries after a daily drawdown threshold.
1. `risk.max_position_usd` caps exposure per position.

## Data Freshness (Stale Feed)

When market data is stale, the safe behavior is:

1. Do not enter new trades.
1. Prefer pausing trading until the feed is healthy again.

How to validate:

1. Check scanner staleness.
1. Check WS connected status.

## Operator Controls

Controls are intentional and should be used carefully:

1. Pause: blocks entries
1. Resume: re-enables entries
1. Close all: closes open positions
1. Kill: emergency stop

Local API:

1. `/api/v1/control/*`

Telegram:

1. `/pause`, `/resume`, `/close_all`, `/kill` (if enabled)

## Expected Results (Client)

Pause:

1. Status changes to `PAUSED`.

Resume:

1. Status changes back to `LIVE` if other guardrails are not triggered.

Kill:

1. Status changes to `STOPPED`.

Important note:

1. If the feed is stale, the system may remain in `STALE FEED` after resume. This is expected and safer than trading on bad data.

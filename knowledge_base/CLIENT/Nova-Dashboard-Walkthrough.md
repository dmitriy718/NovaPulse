# Nova Horizon Dashboard Walkthrough

Last updated: 2026-02-13

## Status Pill

Nova Horizon shows a status indicator that summarizes system state:

1. `LIVE`: trading engine is running and not blocked by safeguards.
1. `PAUSED`: trading is paused by an operator.
1. `STOPPED`: emergency stop is engaged.
1. `STALE FEED`: market data is stale, so the system is intentionally not trading.
1. `OFFLINE`: the dashboard cannot reach the API.

## Main Panels

Common fields:

1. Equity: current estimated total value (cash + positions).
1. Cash: available cash not currently held in positions.
1. Realized PnL: profit or loss from closed trades for the current day.
1. Unrealized PnL: profit or loss on currently open positions.
1. Exposure: total position notional value currently held.

## Positions Table

For each open position you may see:

1. Symbol
1. Quantity
1. Average cost
1. Current mid price
1. Position value
1. Position PnL
1. Signal indicator (BUY, SELL, HOLD) and confidence

## Recent Trades

Shows recent buy/sell actions and any realized PnL on sells.

## Feeds

Displays how recent the incoming market feeds are. If feeds become stale, the system will stop trading for safety.

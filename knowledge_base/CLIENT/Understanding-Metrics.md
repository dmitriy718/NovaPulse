# Understanding Metrics

Last updated: 2026-02-13

## Equity

Equity is an estimate of total account value:

1. Cash plus the current value of positions.

## Exposure

Exposure is the amount currently allocated into open positions (in USD notional terms).

## Realized vs Unrealized PnL

1. Realized PnL: gains or losses from trades that have been closed.
1. Unrealized PnL: gains or losses on positions still open.

## Signals

Signals indicate the system’s current bias for a symbol:

1. BUY means the model is biased toward entering or adding.
1. SELL means the model is biased toward reducing.
1. HOLD means no action is indicated.

Confidence is a relative score. Higher confidence does not guarantee a profitable outcome.

## Stale Feed and Safety Guards

If market data becomes stale, the system intentionally stops trading to avoid acting on bad information.


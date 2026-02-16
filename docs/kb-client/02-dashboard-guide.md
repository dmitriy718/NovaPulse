# Dashboard Guide

## What you see

- Status header: mode, uptime, scan count
- Portfolio: realized/unrealized PnL, equity, win rate, trades
- Thought log: bot reasoning and scan results
- Active positions: per-pair exposure and PnL
- Algo pulse: strategy performance indicators
- Ticker scanner: freshness and last price per pair
- Risk shield: risk of ruin, daily loss, exposure, drawdown factor
- Settings: weighted order book toggle

## Pause / Resume / Close All

These buttons are privileged actions.

To enable them in your browser session, set your API key in localStorage:

1. Open browser developer tools.
2. In the Console:
   - `localStorage.setItem('DASHBOARD_API_KEY', '<your key>')`
3. Refresh the page.

If you do not set this, the dashboard can still monitor but will block control actions.

## Weighted Order Book

When enabled, order book score can count as heavy confluence. This can increase trade frequency.

If you are seeing too many trades, turn this off or increase confluence thresholds in config.


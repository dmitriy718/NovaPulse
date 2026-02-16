# Configuration Guide

Primary file:
- `config/config.yaml`

Recommended client workflow:
1. Change only one thing at a time.
2. Run in paper mode after each change.
3. Watch the dashboard thought log for signal volume changes.

High-impact knobs:
- `trading.pairs`
- `trading.timeframes`
- `ai.confluence_threshold`
- `ai.min_confidence`
- `trading.max_spread_pct`
- `risk.max_risk_per_trade`
- `risk.max_daily_loss`

If you want fewer trades:
- Increase `ai.confluence_threshold`
- Increase `ai.min_confidence`
- Disable `ai.obi_counts_as_confluence`

If you want more trades:
- Reduce thresholds slightly, but monitor risk and drawdown.


# Trading Lifecycle (Signals -> Orders -> Positions)

## End-to-End Flow (Client)

1. Data arrives from the exchange.
1. Strategies evaluate markets and propose entries/exits.
1. Confluence merges multiple signals into a single decision.
1. Risk controls decide whether a trade is permitted and how large it can be.
1. Orders are executed (paper/live).
1. Open positions are monitored and managed.
1. Everything is logged and visible via the dashboard.

## Thought Log (How To Read It)

The thought log is meant to reduce support tickets by explaining:

1. Why a trade was entered or exited
1. Why a trade was skipped (stale feed, spread too wide, low confidence, risk stop)
1. Operational events (pause/resume, WS reconnects, errors)

## Support/Dev Code Map

Signal generation:

1. `src/strategies/*`
1. `src/ai/confluence.py`

Risk:

1. `src/execution/risk_manager.py`

Execution:

1. `src/execution/executor.py`

Market data:

1. `src/exchange/market_data.py`

Engine loops:

1. `src/core/engine.py`

## Paper vs Live Execution (Support/Dev)

1. Paper mode simulates fills and is the safe default for tuning.
1. Live mode must be treated as production and should require:
   - explicit enablement
   - valid exchange credentials
   - control key set


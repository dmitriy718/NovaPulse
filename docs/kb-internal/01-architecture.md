# Architecture

## High-level pipeline

Core trade pipeline:
1. Market data is ingested via WebSocket + REST warmup into `MarketDataCache`.
2. Strategies analyze OHLCV and emit `StrategySignal`s.
3. `ConfluenceDetector` aggregates signals (optionally multi-timeframe, order book gating, regime multipliers).
4. AI predictor gates signals (TFLite when available; otherwise heuristic).
5. `RiskManager` sizes and enforces limits (daily loss, RoR, cooldowns, exposure).
6. `TradeExecutor` places orders (paper or live) and manages positions (stops, trailing, breakeven).
7. Everything is persisted to SQLite (WAL) and surfaced via FastAPI + WebSocket dashboard.

Primary entry points and orchestrators:
- `main.py`: lifecycle owner (init, tasks, uvicorn server, shutdown).
- `src/core/engine.py`: orchestrates subsystems and runs background loops.

## Runtime loops

Engine loops (single-exchange mode):
- Scan loop: `BotEngine._main_scan_loop()` scans pairs (event-driven queue + timeout fallback).
- Position management loop: `BotEngine._position_management_loop()` checks stops/trailing on a short interval.
- WS loop: `BotEngine._ws_data_loop()` registers callbacks and connects WS client.
- Health monitor: `BotEngine._health_monitor()` detects WS death/stale data and triggers recovery.
- Cleanup: `BotEngine._cleanup_loop()` performs periodic DB cleanup.
- Retrainer: `AutoRetrainer.run()` retrains model periodically (trainer runs training in a subprocess).

Multi-exchange mode:
- `main.py` spins up multiple `BotEngine` instances and uses `src/core/multi_engine.py` to present a unified dashboard.

## Major modules

- Config:
  - `src/core/config.py`: Pydantic config models + env override overlay.
  - `config/config.yaml`: default config file.
- Data:
  - `src/exchange/market_data.py`: OHLCV ring buffers, tickers, order books, staleness checks.
  - `src/core/structures.py`: `RingBuffer` implementation.
- Exchange:
  - Kraken: `src/exchange/kraken_rest.py`, `src/exchange/kraken_ws.py`
  - Coinbase: `src/exchange/coinbase_rest.py`, `src/exchange/coinbase_ws.py`
- Strategies:
  - `src/strategies/*`: each returns a `StrategySignal`.
  - `src/utils/indicator_cache.py`: shared indicator cache per scan/timeframe.
  - `src/utils/indicators.py`: NumPy indicator primitives.
- AI:
  - `src/ai/confluence.py`: multi-strategy aggregation and gating.
  - `src/ai/predictor.py`: TFLite predictor + heuristic fallback + caching.
  - `src/ai/order_book.py`: microstructure analysis and scoring.
- Execution / Risk:
  - `src/execution/executor.py`: order placement, fills, slippage/fees, close logic, position management.
  - `src/execution/risk_manager.py`: sizing, cooldowns, daily loss, risk-of-ruin, trailing/breakeven.
- Persistence:
  - `src/core/database.py`: SQLite schema + async CRUD.
- API / Dashboard:
  - `src/api/server.py`: REST endpoints + WebSocket updates + control endpoints.
  - `static/`: HTML/CSS/JS dashboard client.

## Key invariants

- Never inject fake candles from ticker updates:
  - Ticker handler should update latest close in-place only.
- Never trade on stale data:
  - Confluence rejects stale pair data (`MarketDataCache.is_stale`).
- One open position per pair per tenant:
  - Enforced at execution layer (see `TradeExecutor`).
- Tenant safety:
  - API tenant resolution must not allow a user to act as a different tenant.


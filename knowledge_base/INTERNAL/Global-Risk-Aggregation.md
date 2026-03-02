# Cross-Engine Risk Aggregation

**Version:** 5.0.0
**Date:** 2026-02-27
**Source:** `src/execution/global_risk.py`
**Class:** `GlobalRiskAggregator`

---

## Overview

NovaPulse runs multiple engines concurrently (Kraken crypto, Coinbase crypto, Alpaca stocks) via MultiEngineHub. Each engine has its own RiskManager with local exposure caps, but the GlobalRiskAggregator enforces a single cross-engine total exposure ceiling to prevent the combined portfolio from becoming over-leveraged.

---

## Singleton Pattern

GlobalRiskAggregator uses the `__new__` singleton pattern. Every call to `GlobalRiskAggregator()` returns the same instance:

```python
class GlobalRiskAggregator:
    _instance: Optional[GlobalRiskAggregator] = None

    def __new__(cls) -> GlobalRiskAggregator:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self, max_total_exposure_usd: float = 0.0):
        if self._initialized:
            return
        self._initialized = True
        ...
```

This ensures all engines within the same process share a single aggregator. After first construction, `configure(max_total_exposure_usd)` can be called to update the cap without re-initializing the singleton.

---

## Thread Safety

All mutable state access is guarded by an `asyncio.Lock`:

```python
self._lock = asyncio.Lock()

async def register_exposure(self, engine_id: str, exposure_usd: float) -> None:
    async with self._lock:
        self._exposures[engine_id] = max(0.0, float(exposure_usd))
```

Since MultiEngineHub runs all engines on the same asyncio event loop, the `asyncio.Lock` provides correct mutual exclusion. If engines ever run on separate loops (separate threads), this would need to be replaced with a `threading.Lock`.

---

## Core API

### `register_exposure(engine_id, exposure_usd)`

Called by each engine's scan loop to report its current total open exposure in USD. The engine_id is typically a string like `"kraken:default"` or `"stocks:default"`.

```python
await aggregator.register_exposure(engine_id, total_exposure_usd)
```

### `get_remaining_capacity() -> float`

Returns the USD amount still available before hitting the global cap:

```python
remaining = await aggregator.get_remaining_capacity()
# Returns float('inf') if max_total_exposure_usd == 0 (no cap configured)
```

### `get_total_exposure() -> float`

Sum of all registered engine exposures.

### `unregister_engine(engine_id)`

Removes an engine from tracking on shutdown, freeing its capacity for others.

### `get_snapshot() -> Dict`

Non-async snapshot for dashboard/reporting. May be slightly stale since it does not acquire the lock:

```python
{
    "total_exposure_usd": 1500.0,
    "max_total_exposure_usd": 5000.0,
    "engines": {
        "kraken:default": 800.0,
        "coinbase:default": 400.0,
        "stocks:default": 300.0,
    }
}
```

---

## Wiring into RiskManager

The per-engine RiskManager checks the global aggregator inside `_get_remaining_capacity()`:

```python
def _get_remaining_capacity(self) -> float:
    # Local capacity check
    total_exposure = sum(pos["size_usd"] for pos in self._open_positions.values())
    max_total = self.current_bankroll * self.max_total_exposure_pct
    local_remaining = max(0, max_total - total_exposure)

    # Global cross-engine cap
    try:
        from src.execution.global_risk import GlobalRiskAggregator
        aggregator = GlobalRiskAggregator()
        if aggregator.max_total_exposure_usd > 0:
            global_total = sum(aggregator._exposures.values())
            global_remaining = max(0.0, aggregator.max_total_exposure_usd - global_total)
            return min(local_remaining, global_remaining)
    except Exception:
        pass

    return local_remaining
```

The import is done lazily to avoid circular imports. The aggregator's `_exposures` dict is read directly (not via the async API) since this runs in a synchronous context within `calculate_position_size()`. This is safe because dict reads are atomic under CPython's GIL, and the slight staleness is acceptable for sizing decisions.

---

## Engine Registration Flow

Each BotEngine (or StockSwingEngine) updates the aggregator during its scan loop:

1. Engine computes its total open exposure from `risk_manager._open_positions`.
2. Calls `await aggregator.register_exposure(engine_id, exposure_usd)`.
3. The aggregator stores the latest snapshot for that engine.
4. When the engine's RiskManager sizes a new position, `_get_remaining_capacity()` reads both local and global caps, returning the minimum.

---

## Configuration

The global cap is set from config YAML:

```yaml
global_risk:
  max_total_exposure_usd: 5000.0
```

If set to 0 or omitted, the global cap is effectively infinite (`get_remaining_capacity()` returns `float('inf')`), and only per-engine local limits apply.

The cap can be updated at runtime via `aggregator.configure(new_cap)` without restarting.

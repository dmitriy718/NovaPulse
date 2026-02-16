# ML + Backtesting

## Predictor

Module:
- `src/ai/predictor.py`

Modes:
- TFLite model (`models/trade_predictor.tflite`) when present and TensorFlow is installed.
- Heuristic fallback when model or TensorFlow is missing.

Normalization:
- Training writes `models/normalization.json`.
- Inference loads it when available.

## Trainer

Module:
- `src/ml/trainer.py`

Key behavior:
- Training runs in a subprocess (process pool) to avoid blocking the async event loop.
- Deploy uses atomic move with backup.

## Backtester

Module:
- `src/ml/backtester.py`

Modes:
- `simple`: lightweight, does not mirror full live gating.
- `parity`: reuses confluence + predictor gating + risk sizing (recommended for evaluation).

Runbook:
- Prefer parity mode for parameter tuning and strategy evaluation.


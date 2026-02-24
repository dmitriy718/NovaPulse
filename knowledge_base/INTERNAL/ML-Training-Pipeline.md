# NovaPulse ML Training Pipeline

**Version:** 4.5.0
**Last Updated:** 2026-02-24

---

## Overview

NovaPulse uses machine learning as a secondary filter on top of the strategy confluence system. The ML layer does not generate trade signals on its own -- it provides a confidence score that gates whether a confluence signal proceeds to execution. The pipeline consists of three components: a batch model trainer (Keras + TFLite), an online incremental learner (SGD), and a weekly strategy auto-tuner.

---

## ModelTrainer (Batch Training)

**File:** `src/ml/trainer.py` (~577 lines)
**Class:** `ModelTrainer`

### Architecture

The batch model is a Keras Sequential neural network:

```
Input (12 or 21 features)
  -> Dense(64, relu) -> BatchNormalization -> Dropout(0.3)
  -> Dense(32, relu) -> BatchNormalization -> Dropout(0.2)
  -> Dense(16, relu) -> BatchNormalization -> Dropout(0.1)
  -> Dense(1, sigmoid)
```

Output is a probability in [0, 1] representing the model's confidence that a trade will be profitable. The engine uses this as a multiplicative factor on the confluence score.

### Feature Set (12 Core Features)

| # | Feature | Computation | Range |
|---|---------|-------------|-------|
| 1 | `rsi` | RSI(14) | [0, 100] |
| 2 | `ema_ratio` | close / EMA(20) | ~[0.9, 1.1] |
| 3 | `bb_position` | (close - BB_lower) / (BB_upper - BB_lower) | [0, 1] |
| 4 | `adx` | ADX(14) | [0, 100] |
| 5 | `volume_ratio` | volume / SMA(volume, 20) | [0, inf) |
| 6 | `obi` | Order book imbalance (bid_vol - ask_vol) / total | [-1, 1] |
| 7 | `atr_pct` | ATR(14) / close | [0, inf) |
| 8 | `momentum` | (close - close[10]) / close[10] | (-inf, inf) |
| 9 | `trend_strength` | abs(EMA(20) - EMA(50)) / close | [0, inf) |
| 10 | `spread_pct` | (ask - bid) / mid_price | [0, inf) |
| 11 | `regime_trend` | Binary encoding: trending regime = 1 | {0, 1} |
| 12 | `regime_volatile` | Binary encoding: volatile regime = 1 | {0, 1} |

When Elasticsearch is available, `TrainingDataProvider` appends 9 additional features (see `Elasticsearch-Pipeline.md`), bringing the total to 21.

### Training Flow

```
1. Query ml_features table from SQLite
   -> SELECT features, label FROM ml_features WHERE tenant_id = ?
   -> label: 1 = profitable trade, 0 = losing trade

2. Parse JSON features into NumPy matrix
   -> Drop rows with NaN in critical columns (RSI, EMA ratio)
   -> Impute remaining NaN with column median

3. Fit StandardScaler on training split ONLY
   -> 80/20 train/validation split (stratified)
   -> Scaler is serialized alongside the model

4. Class weight balancing
   -> weights = {0: n_samples / (2 * n_neg), 1: n_samples / (2 * n_pos)}
   -> Handles imbalanced win/loss distributions

5. Train Keras model
   -> EarlyStopping(patience=10, monitor='val_loss')
   -> ReduceLROnPlateau(patience=5, factor=0.5)
   -> Max 100 epochs, batch_size=32

6. Evaluate on validation set
   -> If accuracy < 0.55 -> model is rejected, old model kept
   -> If accuracy >= 0.55 -> proceed to deployment

7. Convert to TFLite
   -> tf.lite.TFLiteConverter.from_keras_model()
   -> Quantization: dynamic range (default) or float16 (configurable)
   -> Output: models/{tenant_id}/signal_model.tflite

8. Atomic deployment
   -> Write to .tflite.tmp
   -> os.rename() to .tflite (atomic on POSIX)
   -> Hot-reload: engine picks up new model on next prediction call
```

### Accuracy Threshold

The minimum accuracy threshold of **0.55** is intentionally low. The model is not expected to be a standalone predictor -- it only needs to add marginal edge on top of the confluence system. A model that is 55% accurate at distinguishing profitable from unprofitable confluence signals provides meaningful value after thousands of trades.

If the training set has fewer than 50 samples, training is skipped entirely to avoid overfitting on noise.

### Scaler Normalization

The `StandardScaler` is fitted exclusively on the training split. The validation split and live inference use the training-fitted scaler. This prevents data leakage. The scaler is persisted as a pickle file alongside the TFLite model:

```
models/{tenant_id}/signal_model.tflite
models/{tenant_id}/scaler.pkl
```

### Config Keys

```yaml
ml:
  enabled: true
  retrain_interval_hours: 24           # how often auto_retrainer fires
  min_samples: 50                      # minimum ml_features rows to train
  accuracy_threshold: 0.55             # minimum val accuracy for deployment
  epochs: 100                          # max training epochs
  batch_size: 32
  dropout_rates: [0.3, 0.2, 0.1]      # per-layer dropout
  quantization: "dynamic"              # dynamic | float16
  use_es_features: true                # enrich with ES features if available
```

---

## ContinuousLearner (Online Training)

**File:** `src/ml/continuous_learner.py` (~216 lines)
**Class:** `ContinuousLearner`

### Purpose

The batch model retrains every 24 hours. Between retrains, the `ContinuousLearner` provides near-real-time adaptation using an SGDClassifier with `partial_fit()`. Every closed trade becomes a training sample that incrementally updates the online model.

### Architecture

```python
SGDClassifier(
    loss='log_loss',       # logistic regression
    learning_rate='adaptive',
    eta0=0.01,
    penalty='l2',
    alpha=0.0001,
    warm_start=True
)
```

The online model is lightweight -- it is a linear classifier, not a neural network. It captures recent distributional shifts (e.g., a sudden regime change) faster than the batch model can.

### Update Flow

```
Trade closes -> engine calls continuous_learner.update(features, label)
  -> scaler.partial_transform(features)    # uses batch model's scaler
  -> clf.partial_fit(features, label)      # incremental SGD step
  -> model saved to models/{tenant_id}/online_model.pkl
```

### Prediction Blending

When both the TFLite batch model and the online SGDClassifier are available, their predictions are blended:

```
blended_score = 0.60 * tflite_prediction + 0.40 * online_prediction
```

The 60/40 split favors the batch model because it is trained on more data with a more expressive architecture. The online model's 40% weight allows it to nudge the score based on very recent trade outcomes.

If only one model is available, that model's prediction is used at 100%. If neither is available (cold start), the ML confidence defaults to 1.0 (no filtering).

### Staleness Guard

The online model tracks the timestamp of its last `partial_fit()` call. If more than 48 hours have passed without an update (no trades closing), the online model's weight is decayed linearly toward 0 over the next 24 hours. This prevents a stale online model from dragging down predictions when market conditions have changed but no trades have closed to update it.

---

## StrategyTuner (Auto-Tuner)

**File:** `src/ml/strategy_tuner.py` (~230 lines)
**Class:** `StrategyTuner`

### Purpose

The auto-tuner adjusts strategy weights weekly based on realized performance. Strategies that perform well get more weight in the confluence score; strategies that underperform get less. This creates an adaptive feedback loop without manual intervention.

### Tuning Cycle

The tuner runs as a background task, firing once per week (default: Sunday 00:00 UTC).

```
1. Query closed trades from the past tuning_lookback_days (default: 30)
   -> Group by strategy name

2. For each strategy, compute:
   -> win_rate: wins / total
   -> avg_pnl_pct: mean P&L percentage
   -> sharpe: mean(pnl) / std(pnl) * sqrt(trades_per_year)
   -> trade_count: number of closed trades

3. Skip strategies with fewer than tuning_min_trades (default: 10)
   -> Insufficient data -- keep current weight unchanged

4. Compute raw score per strategy:
   -> raw_score = (win_rate * 0.4) + (norm_sharpe * 0.4) + (norm_avg_pnl * 0.2)

5. Normalize raw scores to sum to 1.0
   -> new_weight = raw_score / sum(all_raw_scores)

6. Clamp weights to [weight_floor, weight_ceiling]
   -> weight_floor: 0.05 (5%)
   -> weight_ceiling: 0.50 (50%)

7. Auto-disable: if Sharpe < -0.3 AND trade_count >= 30
   -> Strategy weight set to 0.0
   -> Strategy's enabled flag set to false
   -> Logged as WARNING: "Auto-disabled {strategy}: Sharpe={sharpe:.2f} over {n} trades"

8. Persist updated weights to config.yaml
   -> Atomic write: write to .tmp, rename to config.yaml
   -> Engine hot-reloads config on next scan cycle
```

### Weight Bounds

| Parameter | Default | Description |
|-----------|---------|-------------|
| `weight_floor` | 0.05 | No strategy can drop below 5% weight |
| `weight_ceiling` | 0.50 | No strategy can exceed 50% weight |
| `tuning_lookback_days` | 30 | Window of trades analyzed |
| `tuning_min_trades` | 10 | Minimum trades to adjust weight |
| `auto_disable_sharpe` | -0.3 | Sharpe threshold for auto-disable |
| `auto_disable_min_trades` | 30 | Minimum trades before auto-disable |

### Config Keys

```yaml
ml:
  strategy_tuner:
    enabled: true
    interval_hours: 168                  # 7 days
    lookback_days: 30
    min_trades: 10
    weight_floor: 0.05
    weight_ceiling: 0.50
    auto_disable_sharpe: -0.3
    auto_disable_min_trades: 30
    scoring_weights:
      win_rate: 0.4
      sharpe: 0.4
      avg_pnl: 0.2
```

---

## Cross-Exchange Training

In multi-engine deployments (Kraken + Coinbase + Stocks), one engine is designated as the **ML training leader**. The leader aggregates `ml_features` from all engine databases to train a single model with a larger and more diverse training set.

### Leader Election

The leader is the first engine in the `accounts` list in `config.yaml`. Other engines are followers.

```yaml
accounts: "main:kraken,swing:coinbase"
# "main:kraken" is the leader
```

### Aggregation Flow

```
Leader's auto_retrainer fires
  -> Reads own ml_features from trading_kraken_main.db
  -> Reads follower DB paths from config
  -> Opens read-only connections to:
     - trading_coinbase_swing.db
     - trading_stocks_default.db
  -> Concatenates all ml_features rows
  -> Trains unified model
  -> Deploys model to models/main/ (leader only)
  -> Followers load the leader's model via shared filesystem
```

Follower engines check `models/{leader_tenant_id}/signal_model.tflite` on each prediction call. If the file's mtime is newer than the last loaded version, the model is hot-reloaded.

### Caveats

- Stock features differ from crypto features (no order book imbalance, no spread_pct). Missing features are imputed with 0.0 during aggregation.
- The training set is imbalanced across exchanges (crypto generates more trades than stocks). Class weighting handles this.
- Each engine's `ContinuousLearner` runs independently -- online models are NOT shared across engines.

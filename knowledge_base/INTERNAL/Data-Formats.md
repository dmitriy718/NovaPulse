# Data Formats and Storage (Internal)

Last updated: 2026-02-13

## Storage Root

Host path:

1. `/home/ops/agent-stack/data`

Container path:

1. `/data`

## NDJSON

The system writes newline-delimited JSON for time-series artifacts. Typical files:

1. `/home/ops/agent-stack/data/sim/trades-YYYY-MM-DD.ndjson`
1. `/home/ops/agent-stack/data/sim/state.json`
1. `/home/ops/agent-stack/data/<exchange>/<symbol>/YYYY-MM-DD.ndjson`
1. `/home/ops/agent-stack/data/<exchange>/<kind>/<symbol>/YYYY-MM-DD.ndjson`

## Parquet Rollups

When enabled (`PARQUET_ROLLUP=1`), the market engine attempts to roll the prior day’s NDJSON into Parquet.

Typical outputs:

1. `...candles_60...YYYY-MM-DD.parquet`
1. `...trades...YYYY-MM-DD.parquet`
1. `/home/ops/agent-stack/data/sim/trades-YYYY-MM-DD.parquet`

## Backup Coverage

The default backup script archives:

1. `data/sim`
1. `data/features`
1. `ops_notes`
1. `docker-compose.yml`
1. `Caddyfile`
1. Docker volumes for Caddy and Qdrant


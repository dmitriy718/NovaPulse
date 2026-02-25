# HA-SentinelAI v1.0.0

Production-ready autonomous AI agent for monitoring and maintaining high-availability uptime across SaaS platforms, VPS infrastructure, and local/cloud services.

## Features

### Multi-Protocol Monitoring (8 Probe Types)
- **HTTP/HTTPS** — Full response validation (status codes, body matching, regex), response time thresholds, redirect following
- **TCP** — Port connectivity checks with latency measurement
- **DNS** — Resolution verification with expected value matching, custom nameserver support
- **SSL/TLS** — Certificate expiry monitoring with configurable warning/critical thresholds
- **ICMP** — Ping-based host reachability with packet loss and RTT tracking
- **Docker** — Container health status, restart count, running state monitoring
- **Process** — System process monitoring with CPU/memory stats
- **Custom** — Arbitrary script execution with structured JSON output support

### Incident Management
- Automatic incident detection with configurable failure thresholds
- Severity escalation: WARNING → CRITICAL → FATAL (time-based)
- Auto-resolution when services recover (configurable success threshold)
- Manual acknowledge and resolve via REST API
- Full incident history with duration tracking

### Auto-Remediation
- Service restarts (`systemctl restart`)
- Docker container restarts
- Arbitrary command execution
- HTTP webhook triggers for external automation
- SSH-based remote command execution
- Rate limiting (max actions per hour) and cooldown per target

### Notification Channels
- **Slack** — Rich attachments with severity color coding
- **Discord** — Embeds with severity-based colors
- **PagerDuty** — Events API v2 (trigger + auto-resolve)
- **Email** — SMTP with HTML formatting
- **Webhooks** — Generic HTTP with HMAC signature verification
- Per-incident cooldown to prevent alert fatigue

### Observability
- REST API with 12+ endpoints
- Real-time status page (auto-refresh, dark theme)
- Uptime SLA tracking (24h / 7d / 30d)
- Response time metrics (avg, p95, p99)
- Probe result history
- Bearer token authentication for protected endpoints

### Production-Ready
- Async architecture (asyncio + aiohttp) for high concurrency
- SQLite with WAL mode for reliable persistence
- Jittered check scheduling to prevent thundering herd
- Configurable retry logic with exponential backoff
- External heartbeat support (Healthchecks.io, BetterUptime, etc.)
- Automatic data retention cleanup
- Structured logging with file rotation
- Graceful shutdown with signal handling
- Docker + docker-compose support

## Quick Start

### 1. Install

```bash
pip install aiohttp pyyaml dnspython
```

### 2. Configure

Edit `ha_config.yaml` with your targets:

```yaml
targets:
  - name: My API
    id: my_api
    type: http
    endpoint: https://api.myapp.com/health
    interval_seconds: 30
    retries: 3
    expected_status_codes: [200]
    response_time_warn_ms: 500
    response_time_crit_ms: 2000
    consecutive_failures_warn: 2
    consecutive_failures_crit: 3

  - name: Database
    id: postgres
    type: tcp
    endpoint: db.myapp.com:5432
    interval_seconds: 15
```

### 3. Run

```bash
# Validate config
python3 -m ha_agent --validate

# Start agent
python3 -m ha_agent --config ha_config.yaml
```

### 4. Access Status Page

Open `http://localhost:8089` for the live status page.

## Configuration Reference

### Agent Settings

| Setting | Default | Description |
|---|---|---|
| `log_level` | `INFO` | Logging level (DEBUG, INFO, WARNING, ERROR) |
| `data_dir` | `./data/ha_sentinel` | Directory for SQLite DB and logs |
| `check_jitter_seconds` | `5` | Random jitter added to check schedules |
| `api.enabled` | `true` | Enable REST API / status page |
| `api.port` | `8089` | API server port |
| `api.secret` | `""` | Bearer token for protected endpoints |
| `notification_cooldown_seconds` | `300` | Min time between repeated alerts |
| `escalation_after_minutes` | `15` | Time before FATAL escalation |
| `remediation_enabled` | `true` | Global auto-remediation toggle |
| `max_remediation_per_hour` | `10` | Rate limit for remediation actions |

### Target Settings

| Setting | Default | Description |
|---|---|---|
| `type` | `http` | Probe type: http, tcp, dns, ssl, icmp, docker, process, custom |
| `interval_seconds` | `30` | Check interval |
| `timeout_seconds` | `10` | Probe timeout |
| `retries` | `2` | Number of retry attempts |
| `response_time_warn_ms` | `1000` | Response time warning threshold |
| `response_time_crit_ms` | `5000` | Response time critical threshold |
| `consecutive_failures_warn` | `2` | Failures before WARNING incident |
| `consecutive_failures_crit` | `3` | Failures before CRITICAL incident |

### Environment Variables

All settings can be overridden via environment variables with `HA_SENTINEL_` prefix:

```
HA_SENTINEL_CONFIG_PATH    — Config file path
HA_SENTINEL_LOG_LEVEL      — Log level
HA_SENTINEL_API_PORT       — API port
HA_SENTINEL_API_SECRET     — API bearer token
HA_SENTINEL_DATA_DIR       — Data directory
HA_SENTINEL_HEARTBEAT_URL  — External heartbeat URL
```

## REST API

| Method | Endpoint | Auth | Description |
|---|---|---|---|
| GET | `/` | No | Status page (HTML) |
| GET | `/health` | No | Health check |
| GET | `/api/v1/status` | No | Overall system status |
| GET | `/api/v1/targets` | Yes | List all targets with status |
| GET | `/api/v1/targets/{id}` | Yes | Target detail with uptime |
| GET | `/api/v1/targets/{id}/history` | Yes | Probe result history |
| GET | `/api/v1/incidents` | Yes | List incidents (filterable) |
| GET | `/api/v1/incidents/{id}` | Yes | Incident detail |
| POST | `/api/v1/incidents/{id}/acknowledge` | Yes | Acknowledge incident |
| POST | `/api/v1/incidents/{id}/resolve` | Yes | Resolve incident |
| GET | `/api/v1/uptime` | Yes | Uptime summaries |
| GET | `/api/v1/metrics` | Yes | Current metrics |

## Docker

```bash
# Build and run
docker-compose -f ha_agent/docker-compose.ha.yml up -d

# View logs
docker logs ha-sentinel-ai -f
```

## Running Tests

```bash
pip install pytest pytest-asyncio pytest-aiohttp
python3 -m pytest tests/test_ha_agent/ -v --noconftest --override-ini="asyncio_mode=auto"
```

## Architecture

```
ha_agent/
├── __init__.py          # Package version and name
├── __main__.py          # CLI entry point
├── agent.py             # Core autonomous agent engine
├── config.py            # YAML config loader with env overrides
├── models.py            # Data models (ProbeResult, Incident, etc.)
├── probes/              # Multi-protocol monitoring probes
│   ├── base.py          # Abstract base with retry logic
│   ├── http_probe.py    # HTTP/HTTPS probe
│   ├── tcp_probe.py     # TCP port probe
│   ├── dns_probe.py     # DNS resolution probe
│   ├── ssl_probe.py     # SSL certificate probe
│   ├── icmp_probe.py    # ICMP ping probe
│   ├── docker_probe.py  # Docker container probe
│   ├── process_probe.py # System process probe
│   └── custom_probe.py  # Custom script probe
├── incidents/           # Incident lifecycle management
│   ├── manager.py       # Detection, escalation, resolution
│   └── remediation.py   # Auto-remediation engine
├── notifications/       # Multi-channel alerting
│   ├── base.py          # Dispatcher with cooldown
│   ├── slack.py         # Slack webhook
│   ├── discord.py       # Discord webhook
│   ├── pagerduty.py     # PagerDuty Events API v2
│   ├── email_notifier.py# SMTP email
│   └── webhook.py       # Generic webhook with HMAC
├── storage/             # Persistent data layer
│   ├── database.py      # SQLite with WAL mode
│   └── metrics.py       # Aggregation and SLA calculation
├── api/                 # REST API and status page
│   └── server.py        # aiohttp server with auth
└── utils/               # Utilities
    └── logging_setup.py # Structured logging
```

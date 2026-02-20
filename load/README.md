# Load Tests (k6)

These scripts exercise NovaPulse API and dashboard websocket under concurrent load.

## Prerequisites

- Install `k6`: https://k6.io/docs/get-started/installation/
- Run NovaPulse locally (default `http://127.0.0.1:8080`)

## API + Dashboard endpoints

```bash
k6 run load/api_dashboard.js
```

With API key:

```bash
BASE_URL=http://127.0.0.1:8080 READ_KEY=your_read_key k6 run load/api_dashboard.js
```

## WebSocket fanout

```bash
k6 run load/ws_live.js
```

With API key:

```bash
BASE_URL=http://127.0.0.1:8080 READ_KEY=your_read_key k6 run load/ws_live.js
```

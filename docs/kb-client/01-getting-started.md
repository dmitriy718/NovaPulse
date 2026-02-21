# Getting Started

## Recommended setup

- Start in paper mode.
- Use Python 3.11 or 3.12.

## Install and run (local)

1. Copy env template:
- Copy `.env.example` to `.env` and fill values.

2. Create environment and install dependencies:
- `python3.11 -m venv venv`
- `source venv/bin/activate`
- `pip install -r requirements.txt`

3. Start the bot:
- `python main.py`

4. Open dashboard:
- `http://localhost:8080`

## Paper vs live mode

- Paper mode simulates orders/fills.
- Live mode places real orders on the exchange.

Live mode requirements:
- You must set `DASHBOARD_ADMIN_KEY` before starting in live mode.

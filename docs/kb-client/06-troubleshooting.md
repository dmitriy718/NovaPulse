# Troubleshooting

## Dashboard says RECONNECTING

Checklist:
- Ensure the bot is running.
- Check `GET /api/v1/status` returns data.
- Review logs in `logs/errors.log`.

## No trades

Common causes:
- Data stale (scanner shows stale pairs)
- Confluence too strict (thresholds too high)
- Spread filter too strict
- Trading paused

## Control buttons do nothing

You likely have not set a dashboard API key in your browser.
Set:
- `localStorage.DASHBOARD_API_KEY`

## Unsupported Python

If you try to run on Python 3.13, the app will refuse to start.
Use Python 3.11 or 3.12.


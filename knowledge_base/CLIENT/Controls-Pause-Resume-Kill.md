# Controls: Pause, Resume, Kill

Last updated: 2026-02-13

## Pause

Pause tells the system to stop placing new orders while still continuing to monitor and compute.

When to use:

1. You want to temporarily stop trading without a full emergency stop.
1. You are diagnosing suspicious behavior.

Expected result:

1. Status changes to `PAUSED`.

## Resume

Resume clears pause and kill flags and allows trading to continue (if other guardrails are not triggered).

When to use:

1. You have confirmed it is safe to resume trading.

Expected result:

1. Status changes back to `LIVE` or `STALE FEED` depending on market-data health.

## Kill (Emergency Stop)

Kill is an emergency stop. Use it when you need trading stopped immediately.

When to use:

1. You suspect credentials compromise.
1. You see unexpected order behavior.
1. You want to freeze trading until support reviews.

Expected result:

1. Status changes to `STOPPED`.

## Important Notes

1. If market feeds are stale, the system may still show `STALE FEED` even after resume. This is a safety feature.
1. Support can help confirm whether you are paused due to a safeguard or due to operator action.


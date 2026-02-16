# FAQ (Internal)

Last updated: 2026-02-13

## Why does `docker compose config` show secrets?

Because Compose renders the final environment values. Treat that command output as sensitive, and do not paste it into tickets.

## Why did Caddy reload require restart?

Because `admin off` disables the Caddy admin API, so `caddy reload` cannot push config to `:2019`. Use `docker restart caddy` after updating `Caddyfile`.

## Why is Qdrant empty?

Current agent code does not write anything into Qdrant yet. It is present as a future retrieval layer.

## Where are Nova credentials?

On the server:

1. `/home/ops/agent-stack/.nova_pass`

## Where are Agent chat credentials?

On the server:

1. `/home/ops/agent-stack/.agent_chat_pass`


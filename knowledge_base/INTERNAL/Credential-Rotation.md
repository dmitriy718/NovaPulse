# Credential Rotation (Internal)

Last updated: 2026-02-13

This document describes how to rotate Basic Auth credentials used by Caddy for:

1. Nova Horizon dashboard (`nova.horizonsvc.com`)
1. Agent chat (`agent.horizonsvc.com/chat`)

## Where Credentials Live

1. Nova password (plaintext): `/home/ops/agent-stack/.nova_pass`
1. Nova password hash (bcrypt): `/home/ops/agent-stack/.nova_hash`
1. Agent chat password (plaintext): `/home/ops/agent-stack/.agent_chat_pass`
1. Agent chat password hash (bcrypt): `/home/ops/agent-stack/.agent_chat_hash`

## Rotation Procedure

1. Generate a new password and save it into the appropriate `*_pass` file.
1. Generate a new bcrypt hash using Caddy.
1. Update `/home/ops/agent-stack/Caddyfile` to use the new hash.
1. Restart `caddy` container.
1. Validate the endpoints.

Example (Nova Horizon rotation):

```bash
cd /home/ops/agent-stack
umask 077

NEW_PASS="$(python3 - <<'PY'\nimport secrets\nprint(secrets.token_urlsafe(24))\nPY\n)"
printf "%s" "$NEW_PASS" > .nova_pass
chmod 600 .nova_pass

NEW_HASH="$(docker exec caddy caddy hash-password --plaintext "$NEW_PASS")"
printf "%s" "$NEW_HASH" > .nova_hash
chmod 600 .nova_hash

# Edit Caddyfile and replace the nova hash in basic_auth block
nano Caddyfile

docker restart caddy
```

Validation:

```bash
curl -u "nova:<NEW_PASS>" -sS https://nova.horizonsvc.com/api/health
```

## Notes

1. Caddy admin API is disabled (`admin off`), so config changes apply via `docker restart caddy`.
1. Do not paste passwords or full hashes into tickets or chat logs.

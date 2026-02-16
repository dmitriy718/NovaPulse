# Security (Internal)

Last updated: 2026-02-13

## Network

1. UFW default deny inbound.
1. Only ports `22`, `80`, `443` should be open.

Validate:

```bash
sudo ufw status verbose
sudo ss -tulpen
```

## SSH

1. `PasswordAuthentication` is disabled via cloud image config.
1. `PermitRootLogin` is set to `prohibit-password` (root key allowed, no passwords).

Validate:

```bash
sshd -T | rg -i \"permitrootlogin|passwordauthentication|kbdinteractiveauthentication|x11forwarding\"
```

## Secrets Storage Rules

1. Secrets must not be pasted into tickets, Slack, or public Git history.
1. File permissions for `/home/ops/agent-stack/.env` and credential files must be `600`.

Validate:

```bash
ls -l /home/ops/agent-stack/.env /home/ops/agent-stack/.nova_pass /home/ops/agent-stack/.agent_chat_pass
```

## Public API Exposure

1. `agent.horizonsvc.com/chat` must be protected (Basic Auth).
1. `nova.horizonsvc.com` must be protected (Basic Auth).

If abuse is suspected:

1. Rotate Basic Auth credentials (update Caddyfile hashes + password files).
1. Rotate upstream API keys (Anthropic, exchanges).
1. Review Caddy access logs/errors: `docker logs caddy`.


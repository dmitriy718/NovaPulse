"""Auto-remediation engine — execute recovery actions when incidents are detected."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from ha_agent.models import Incident, MonitorTarget

logger = logging.getLogger("ha_sentinel.remediation")


class RemediationEngine:
    """Executes predefined remediation actions when incidents occur.

    Supported action types:
      - restart_service: systemctl restart <service>
      - restart_docker: docker restart <container>
      - run_command: arbitrary shell command
      - http_webhook: POST to a URL to trigger external recovery
      - ssh_command: execute command on remote host via SSH
    """

    def __init__(self, enabled: bool = True, max_per_hour: int = 10) -> None:
        self._enabled = enabled
        self._max_per_hour = max_per_hour
        self._action_log: list[dict[str, Any]] = []
        self._cooldowns: dict[str, float] = {}

    def _rate_ok(self) -> bool:
        cutoff = time.time() - 3600
        recent = [a for a in self._action_log if a["timestamp"] > cutoff]
        return len(recent) < self._max_per_hour

    def _cooldown_ok(self, target_id: str, cooldown: int) -> bool:
        last = self._cooldowns.get(target_id, 0)
        return (time.time() - last) >= cooldown

    async def attempt_remediation(
        self, target: MonitorTarget, incident: Incident
    ) -> list[dict[str, Any]]:
        if not self._enabled or not target.remediation_enabled:
            return []

        if not target.remediation_actions:
            return []

        if not self._rate_ok():
            logger.warning("Remediation rate limit reached (%d/hr)", self._max_per_hour)
            return []

        if not self._cooldown_ok(target.id, target.remediation_cooldown_seconds):
            logger.info("Remediation cooldown active for %s", target.id)
            return []

        results = []
        for action in target.remediation_actions:
            action_type = action.get("type", "")
            try:
                result = await self._execute_action(action_type, action, target)
                result["timestamp"] = time.time()
                results.append(result)
                self._action_log.append(result)
                incident.remediation_attempts.append(result)

                logger.info(
                    "Remediation %s for %s: %s",
                    action_type, target.name,
                    "success" if result.get("success") else "failed",
                )
            except Exception as exc:
                err = {
                    "type": action_type,
                    "success": False,
                    "error": str(exc),
                    "timestamp": time.time(),
                }
                results.append(err)
                incident.remediation_attempts.append(err)
                logger.error("Remediation %s failed for %s: %s", action_type, target.name, exc)

        self._cooldowns[target.id] = time.time()
        return results

    async def _execute_action(
        self, action_type: str, action: dict[str, Any], target: MonitorTarget
    ) -> dict[str, Any]:
        timeout = action.get("timeout", 30)

        if action_type == "restart_service":
            return await self._restart_service(action["service"], timeout)
        elif action_type == "restart_docker":
            return await self._restart_docker(action["container"], timeout)
        elif action_type == "run_command":
            return await self._run_command(action["command"], timeout)
        elif action_type == "http_webhook":
            return await self._http_webhook(action, timeout)
        elif action_type == "ssh_command":
            return await self._ssh_command(action, timeout)
        else:
            return {"type": action_type, "success": False, "error": f"Unknown action type: {action_type}"}

    async def _restart_service(self, service: str, timeout: int) -> dict[str, Any]:
        proc = await asyncio.create_subprocess_exec(
            "systemctl", "restart", service,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        return {
            "type": "restart_service",
            "service": service,
            "success": proc.returncode == 0,
            "exit_code": proc.returncode,
            "stderr": stderr.decode()[:500] if stderr else "",
        }

    async def _restart_docker(self, container: str, timeout: int) -> dict[str, Any]:
        proc = await asyncio.create_subprocess_exec(
            "docker", "restart", container,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        return {
            "type": "restart_docker",
            "container": container,
            "success": proc.returncode == 0,
            "exit_code": proc.returncode,
            "output": stdout.decode()[:500] if stdout else "",
        }

    async def _run_command(self, command: str, timeout: int) -> dict[str, Any]:
        proc = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        return {
            "type": "run_command",
            "command": command[:200],
            "success": proc.returncode == 0,
            "exit_code": proc.returncode,
            "stdout": stdout.decode()[:500] if stdout else "",
            "stderr": stderr.decode()[:500] if stderr else "",
        }

    async def _http_webhook(self, action: dict[str, Any], timeout: int) -> dict[str, Any]:
        import aiohttp

        url = action["url"]
        method = action.get("method", "POST")
        headers = action.get("headers", {})
        body = action.get("body", "")

        async with aiohttp.ClientSession() as session:
            async with session.request(
                method, url, headers=headers, data=body,
                timeout=aiohttp.ClientTimeout(total=timeout),
            ) as resp:
                return {
                    "type": "http_webhook",
                    "url": url,
                    "success": 200 <= resp.status < 300,
                    "status_code": resp.status,
                }

    async def _ssh_command(self, action: dict[str, Any], timeout: int) -> dict[str, Any]:
        host = action["host"]
        user = action.get("user", "root")
        command = action["command"]
        key_file = action.get("key_file", "")

        ssh_args = ["ssh", "-o", "StrictHostKeyChecking=no", "-o", "ConnectTimeout=10"]
        if key_file:
            ssh_args.extend(["-i", key_file])
        ssh_args.extend([f"{user}@{host}", command])

        proc = await asyncio.create_subprocess_exec(
            *ssh_args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        return {
            "type": "ssh_command",
            "host": host,
            "command": command[:200],
            "success": proc.returncode == 0,
            "exit_code": proc.returncode,
            "stdout": stdout.decode()[:500] if stdout else "",
            "stderr": stderr.decode()[:500] if stderr else "",
        }

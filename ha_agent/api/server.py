"""Async REST API server built on aiohttp for status, metrics, and control."""

from __future__ import annotations

import json
import logging
import time
from typing import TYPE_CHECKING, Any

from aiohttp import web

if TYPE_CHECKING:
    from ha_agent.agent import SentinelAgent

logger = logging.getLogger("ha_sentinel.api")


class APIServer:
    def __init__(self, agent: SentinelAgent, host: str = "0.0.0.0", port: int = 8089, secret: str = "") -> None:
        self._agent = agent
        self._host = host
        self._port = port
        self._secret = secret
        self._app = web.Application(middlewares=[self._auth_middleware])
        self._setup_routes()
        self._runner: web.AppRunner | None = None

    def _setup_routes(self) -> None:
        self._app.router.add_get("/", self._handle_status_page)
        self._app.router.add_get("/health", self._handle_health)
        self._app.router.add_get("/api/v1/status", self._handle_status)
        self._app.router.add_get("/api/v1/targets", self._handle_targets)
        self._app.router.add_get("/api/v1/targets/{target_id}", self._handle_target_detail)
        self._app.router.add_get("/api/v1/targets/{target_id}/history", self._handle_target_history)
        self._app.router.add_get("/api/v1/incidents", self._handle_incidents)
        self._app.router.add_get("/api/v1/incidents/{incident_id}", self._handle_incident_detail)
        self._app.router.add_post("/api/v1/incidents/{incident_id}/acknowledge", self._handle_acknowledge)
        self._app.router.add_post("/api/v1/incidents/{incident_id}/resolve", self._handle_resolve)
        self._app.router.add_get("/api/v1/uptime", self._handle_uptime)
        self._app.router.add_get("/api/v1/metrics", self._handle_metrics)

    @web.middleware
    async def _auth_middleware(self, request: web.Request, handler: Any) -> web.Response:
        public_paths = {"/", "/health", "/api/v1/status"}
        if request.path in public_paths or not self._secret:
            return await handler(request)

        auth = request.headers.get("Authorization", "")
        if auth == f"Bearer {self._secret}" or request.query.get("token") == self._secret:
            return await handler(request)

        return web.json_response({"error": "Unauthorized"}, status=401)

    async def start(self) -> None:
        self._runner = web.AppRunner(self._app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, self._host, self._port)
        await site.start()
        logger.info("API server started on %s:%d", self._host, self._port)

    async def stop(self) -> None:
        if self._runner:
            await self._runner.cleanup()
            logger.info("API server stopped")

    async def _handle_health(self, request: web.Request) -> web.Response:
        return web.json_response({"status": "ok", "timestamp": time.time()})

    async def _handle_status(self, request: web.Request) -> web.Response:
        targets_data = []
        for target in self._agent.targets:
            state = self._agent.db.get_target_state(target.id)
            targets_data.append({
                "id": target.id,
                "name": target.name,
                "group": target.group,
                "status": state.get("current_status", "unknown"),
                "last_check_at": state.get("last_check_at", 0),
                "response_ms": state.get("last_response_ms", 0),
                "consecutive_failures": state.get("consecutive_failures", 0),
            })

        open_incidents = self._agent.incident_manager.get_active_incidents()
        overall = "operational"
        if any(t["status"] == "down" for t in targets_data):
            overall = "major_outage"
        elif any(t["status"] == "degraded" for t in targets_data):
            overall = "degraded"

        return web.json_response({
            "overall_status": overall,
            "targets": targets_data,
            "open_incidents": len(open_incidents),
            "timestamp": time.time(),
        })

    async def _handle_targets(self, request: web.Request) -> web.Response:
        targets = []
        for target in self._agent.targets:
            state = self._agent.db.get_target_state(target.id)
            uptime = self._agent.metrics.get_uptime_summary(target.id, hours=24)
            targets.append({
                "id": target.id,
                "name": target.name,
                "probe_type": target.probe_type.value,
                "endpoint": target.endpoint,
                "group": target.group,
                "tags": target.tags,
                "enabled": target.enabled,
                "status": state.get("current_status", "unknown"),
                "response_ms": state.get("last_response_ms", 0),
                "uptime_24h": uptime["uptime_pct"],
                "avg_response_24h": uptime["avg_response_ms"],
            })
        return web.json_response({"targets": targets})

    async def _handle_target_detail(self, request: web.Request) -> web.Response:
        target_id = request.match_info["target_id"]
        target = self._agent.get_target(target_id)
        if target is None:
            return web.json_response({"error": "Target not found"}, status=404)

        state = self._agent.db.get_target_state(target_id)
        uptime_24h = self._agent.metrics.get_uptime_summary(target_id, hours=24)
        uptime_7d = self._agent.metrics.get_uptime_summary(target_id, hours=168)
        uptime_30d = self._agent.metrics.get_uptime_summary(target_id, hours=720)

        return web.json_response({
            "target": {
                "id": target.id,
                "name": target.name,
                "probe_type": target.probe_type.value,
                "endpoint": target.endpoint,
                "group": target.group,
                "tags": target.tags,
                "interval_seconds": target.interval_seconds,
            },
            "current_state": state,
            "uptime": {
                "24h": uptime_24h,
                "7d": uptime_7d,
                "30d": uptime_30d,
            },
        })

    async def _handle_target_history(self, request: web.Request) -> web.Response:
        target_id = request.match_info["target_id"]
        limit = int(request.query.get("limit", "50"))
        results = self._agent.db.get_recent_results(target_id, limit=limit)
        return web.json_response({"target_id": target_id, "results": results})

    async def _handle_incidents(self, request: web.Request) -> web.Response:
        state = request.query.get("state")
        target_id = request.query.get("target_id")
        limit = int(request.query.get("limit", "50"))
        offset = int(request.query.get("offset", "0"))

        incidents = self._agent.db.get_incidents(
            limit=limit, offset=offset, target_id=target_id, state=state
        )

        return web.json_response({
            "incidents": [_serialize_incident(i) for i in incidents],
            "total": len(incidents),
        })

    async def _handle_incident_detail(self, request: web.Request) -> web.Response:
        incident_id = request.match_info["incident_id"]
        incident = self._agent.db.get_incident_by_id(incident_id)
        if incident is None:
            return web.json_response({"error": "Incident not found"}, status=404)
        return web.json_response({"incident": _serialize_incident(incident)})

    async def _handle_acknowledge(self, request: web.Request) -> web.Response:
        incident_id = request.match_info["incident_id"]
        success = self._agent.incident_manager.acknowledge_incident(incident_id)
        if success:
            return web.json_response({"status": "acknowledged"})
        return web.json_response({"error": "Incident not found or already resolved"}, status=404)

    async def _handle_resolve(self, request: web.Request) -> web.Response:
        incident_id = request.match_info["incident_id"]
        success = self._agent.incident_manager.resolve_incident(incident_id)
        if success:
            return web.json_response({"status": "resolved"})
        return web.json_response({"error": "Incident not found or already resolved"}, status=404)

    async def _handle_uptime(self, request: web.Request) -> web.Response:
        hours = int(request.query.get("hours", "24"))
        summaries = []
        for target in self._agent.targets:
            summary = self._agent.metrics.get_uptime_summary(target.id, hours=hours)
            summary["name"] = target.name
            summaries.append(summary)
        return web.json_response({"period_hours": hours, "targets": summaries})

    async def _handle_metrics(self, request: web.Request) -> web.Response:
        states = self._agent.db.get_all_target_states()
        active = self._agent.incident_manager.get_active_incidents()
        return web.json_response({
            "targets_monitored": len(self._agent.targets),
            "targets_up": sum(1 for s in states if s.get("current_status") == "up"),
            "targets_down": sum(1 for s in states if s.get("current_status") == "down"),
            "targets_degraded": sum(1 for s in states if s.get("current_status") == "degraded"),
            "active_incidents": len(active),
            "timestamp": time.time(),
        })

    async def _handle_status_page(self, request: web.Request) -> web.Response:
        return web.Response(
            text=self._render_status_page(),
            content_type="text/html",
        )

    def _render_status_page(self) -> str:
        targets_html = []
        overall_ok = True

        for target in self._agent.targets:
            state = self._agent.db.get_target_state(target.id)
            status = state.get("current_status", "unknown")
            response_ms = state.get("last_response_ms", 0)
            uptime = self._agent.metrics.get_uptime_summary(target.id, hours=24)

            if status == "up":
                badge_class = "badge-up"
                badge_text = "Operational"
            elif status == "degraded":
                badge_class = "badge-degraded"
                badge_text = "Degraded"
                overall_ok = False
            elif status == "down":
                badge_class = "badge-down"
                badge_text = "Down"
                overall_ok = False
            else:
                badge_class = "badge-unknown"
                badge_text = "Unknown"

            targets_html.append(f"""
            <div class="target-card">
                <div class="target-header">
                    <span class="target-name">{target.name}</span>
                    <span class="badge {badge_class}">{badge_text}</span>
                </div>
                <div class="target-details">
                    <span class="detail">{target.probe_type.value.upper()}</span>
                    <span class="detail">{response_ms:.0f}ms</span>
                    <span class="detail">{uptime['uptime_pct']:.2f}% uptime (24h)</span>
                </div>
            </div>
            """)

        overall_class = "status-operational" if overall_ok else "status-disrupted"
        overall_text = "All Systems Operational" if overall_ok else "Service Disruption Detected"

        open_incidents = self._agent.incident_manager.get_active_incidents()
        incidents_html = ""
        if open_incidents:
            items = []
            for inc in open_incidents[:10]:
                items.append(f"""
                <div class="incident-item">
                    <span class="incident-severity severity-{inc.severity.value}">{inc.severity.value.upper()}</span>
                    <span class="incident-title">{inc.title}</span>
                    <span class="incident-duration">{inc.duration_seconds:.0f}s</span>
                </div>
                """)
            incidents_html = f"""
            <div class="section">
                <h2>Active Incidents</h2>
                {''.join(items)}
            </div>
            """

        return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>HA-SentinelAI Status</title>
    <meta http-equiv="refresh" content="30">
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #0f1117; color: #e1e4e8; min-height: 100vh; }}
        .container {{ max-width: 900px; margin: 0 auto; padding: 2rem 1rem; }}
        .header {{ text-align: center; margin-bottom: 2rem; }}
        .header h1 {{ font-size: 1.5rem; font-weight: 600; color: #f0f6fc; margin-bottom: 0.5rem; }}
        .overall-status {{ padding: 1rem 2rem; border-radius: 12px; text-align: center; font-weight: 600; font-size: 1.1rem; margin-bottom: 2rem; }}
        .status-operational {{ background: linear-gradient(135deg, #0d3320, #1a4731); color: #3fb950; border: 1px solid #238636; }}
        .status-disrupted {{ background: linear-gradient(135deg, #3d1f00, #5a2d00); color: #f0883e; border: 1px solid #d18616; }}
        .section {{ margin-bottom: 2rem; }}
        .section h2 {{ font-size: 1.1rem; color: #8b949e; margin-bottom: 1rem; font-weight: 500; }}
        .target-card {{ background: #161b22; border: 1px solid #30363d; border-radius: 8px; padding: 1rem 1.25rem; margin-bottom: 0.5rem; transition: border-color 0.2s; }}
        .target-card:hover {{ border-color: #484f58; }}
        .target-header {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.5rem; }}
        .target-name {{ font-weight: 600; color: #f0f6fc; }}
        .badge {{ padding: 0.2rem 0.6rem; border-radius: 20px; font-size: 0.75rem; font-weight: 600; }}
        .badge-up {{ background: #0d3320; color: #3fb950; }}
        .badge-degraded {{ background: #3d1f00; color: #f0883e; }}
        .badge-down {{ background: #3d0d0d; color: #f85149; }}
        .badge-unknown {{ background: #1c1e24; color: #8b949e; }}
        .target-details {{ display: flex; gap: 1rem; }}
        .detail {{ font-size: 0.8rem; color: #8b949e; }}
        .incident-item {{ background: #161b22; border: 1px solid #30363d; border-radius: 8px; padding: 0.8rem 1rem; margin-bottom: 0.5rem; display: flex; align-items: center; gap: 0.8rem; }}
        .incident-severity {{ padding: 0.15rem 0.5rem; border-radius: 4px; font-size: 0.7rem; font-weight: 700; }}
        .severity-warning {{ background: #3d1f00; color: #f0883e; }}
        .severity-critical {{ background: #3d0d0d; color: #f85149; }}
        .severity-fatal {{ background: #5a0d0d; color: #ff6b6b; }}
        .severity-info {{ background: #0d1f3d; color: #58a6ff; }}
        .incident-title {{ flex: 1; color: #e1e4e8; }}
        .incident-duration {{ color: #8b949e; font-size: 0.8rem; }}
        .footer {{ text-align: center; color: #484f58; font-size: 0.8rem; margin-top: 3rem; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>HA-SentinelAI Status</h1>
        </div>
        <div class="overall-status {overall_class}">{overall_text}</div>
        {incidents_html}
        <div class="section">
            <h2>Monitored Services</h2>
            {''.join(targets_html)}
        </div>
        <div class="footer">
            Powered by HA-SentinelAI &mdash; Auto-refreshes every 30s
        </div>
    </div>
</body>
</html>"""


def _serialize_incident(incident: Any) -> dict:
    return {
        "id": incident.id,
        "target_id": incident.target_id,
        "target_name": incident.target_name,
        "severity": incident.severity.value,
        "state": incident.state.value,
        "title": incident.title,
        "description": incident.description,
        "started_at": incident.started_at,
        "resolved_at": incident.resolved_at,
        "acknowledged_at": incident.acknowledged_at,
        "acknowledged_by": incident.acknowledged_by,
        "duration_seconds": incident.duration_seconds,
        "remediation_attempts": incident.remediation_attempts,
        "notification_log": incident.notification_log,
    }

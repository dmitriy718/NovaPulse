"""Metrics collection and aggregation for uptime SLA reporting."""

from __future__ import annotations

import logging
import statistics
import time
from collections import defaultdict
from typing import Any

from ha_agent.models import ProbeResult, TargetStatus, UptimeRecord
from ha_agent.storage.database import Database

logger = logging.getLogger("ha_sentinel.metrics")


class MetricsCollector:
    """Collects probe results in memory and periodically flushes aggregated
    uptime records to the database."""

    AGGREGATION_INTERVAL = 300  # 5-minute buckets

    def __init__(self, db: Database) -> None:
        self._db = db
        self._buffers: dict[str, list[ProbeResult]] = defaultdict(list)
        self._last_flush: float = time.time()

    def record(self, result: ProbeResult) -> None:
        self._db.save_probe_result(result)
        self._buffers[result.target_id].append(result)

        if time.time() - self._last_flush >= self.AGGREGATION_INTERVAL:
            self.flush_all()

    def flush_all(self) -> None:
        now = time.time()
        for target_id, results in self._buffers.items():
            if not results:
                continue
            self._flush_target(target_id, results, now)
        self._buffers.clear()
        self._last_flush = now

    def _flush_target(
        self, target_id: str, results: list[ProbeResult], now: float
    ) -> None:
        if not results:
            return

        times = sorted(r.timestamp for r in results)
        period_start = times[0]
        period_end = times[-1]

        response_times = [r.response_time_ms for r in results if r.response_time_ms > 0]
        successful = sum(1 for r in results if r.is_healthy)

        p95 = _percentile(response_times, 0.95)
        p99 = _percentile(response_times, 0.99)
        avg_rt = statistics.mean(response_times) if response_times else 0

        record = UptimeRecord(
            target_id=target_id,
            period_start=period_start,
            period_end=period_end,
            total_checks=len(results),
            successful_checks=successful,
            avg_response_ms=avg_rt,
            p95_response_ms=p95,
            p99_response_ms=p99,
        )
        self._db.save_uptime_record(record)

    def get_uptime_summary(self, target_id: str, hours: int = 24) -> dict[str, Any]:
        since = time.time() - (hours * 3600)
        records = self._db.get_uptime_records(target_id, since=since)

        if not records:
            return {
                "target_id": target_id,
                "period_hours": hours,
                "uptime_pct": 100.0,
                "total_checks": 0,
                "avg_response_ms": 0,
                "p95_response_ms": 0,
                "p99_response_ms": 0,
                "incidents": 0,
            }

        total = sum(r["total_checks"] for r in records)
        success = sum(r["successful_checks"] for r in records)
        avg_rt = (
            statistics.mean(r["avg_response_ms"] for r in records if r["avg_response_ms"] > 0)
            if any(r["avg_response_ms"] > 0 for r in records)
            else 0
        )
        p95 = max((r["p95_response_ms"] for r in records), default=0)
        p99 = max((r["p99_response_ms"] for r in records), default=0)
        incidents = sum(r.get("incidents_count", 0) for r in records)

        return {
            "target_id": target_id,
            "period_hours": hours,
            "uptime_pct": (success / total * 100) if total else 100.0,
            "total_checks": total,
            "avg_response_ms": round(avg_rt, 2),
            "p95_response_ms": round(p95, 2),
            "p99_response_ms": round(p99, 2),
            "incidents": incidents,
        }


def _percentile(data: list[float], pct: float) -> float:
    if not data:
        return 0.0
    data_sorted = sorted(data)
    idx = int(len(data_sorted) * pct)
    idx = min(idx, len(data_sorted) - 1)
    return data_sorted[idx]

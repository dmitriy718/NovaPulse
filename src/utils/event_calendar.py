"""
Macro Event Calendar — Pauses trading around high-impact economic events.

Supports static FOMC/CPI/NFP schedules and optional Polygon earnings fetching.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from src.core.logger import get_logger

logger = get_logger("event_calendar")


class EventCalendar:
    """Calendar of macro events with configurable blackout windows."""

    def __init__(
        self,
        events_file: str = "data/events/macro_events.json",
        blackout_minutes: int = 30,
        fetch_earnings: bool = False,
        earnings_refresh_hours: int = 24,
    ):
        self._events_file = events_file
        self._default_blackout_minutes = max(1, blackout_minutes)
        self._fetch_earnings = fetch_earnings
        self._earnings_refresh_hours = max(1, earnings_refresh_hours)
        self._events: List[Dict] = []
        self._earnings_cache: List[Dict] = []
        self._earnings_cache_ts: float = 0.0
        self.load_events()

    def load_events(self) -> List[Dict]:
        """Load events from JSON file. Returns empty list on missing/invalid file."""
        self._events = []
        path = Path(self._events_file)
        if not path.exists():
            logger.warning("Events file not found, calendar empty", path=str(path))
            return self._events
        try:
            with open(path, "r") as f:
                data = json.load(f)
            events = data if isinstance(data, list) else data.get("events", [])
            for ev in events:
                if "datetime" not in ev and "date" not in ev:
                    continue
                self._events.append(ev)
            logger.info("Loaded macro events", count=len(self._events))
        except Exception as e:
            logger.warning("Failed to load events file", error=repr(e))
        return self._events

    def is_blackout(self, now: Optional[datetime] = None) -> Tuple[bool, Optional[str]]:
        """Check if current time falls within any event's blackout window.

        Returns (is_blackout, event_name_or_None).
        """
        if now is None:
            now = datetime.now(timezone.utc)
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)

        all_events = self._events + self._earnings_cache
        for ev in all_events:
            ev_dt = self._parse_event_time(ev)
            if ev_dt is None:
                continue
            before_min = int(ev.get("blackout_before_min", self._default_blackout_minutes))
            after_min = int(ev.get("blackout_after_min", self._default_blackout_minutes))
            window_start = ev_dt - timedelta(minutes=before_min)
            window_end = ev_dt + timedelta(minutes=after_min)
            if window_start <= now <= window_end:
                name = ev.get("name", ev.get("event", "Unknown Event"))
                return True, name
        return False, None

    def get_upcoming_events(self, hours_ahead: float = 24.0) -> List[Dict]:
        """Return events within the next `hours_ahead` hours."""
        now = datetime.now(timezone.utc)
        cutoff = now + timedelta(hours=hours_ahead)
        upcoming = []
        for ev in self._events + self._earnings_cache:
            ev_dt = self._parse_event_time(ev)
            if ev_dt is None:
                continue
            if now <= ev_dt <= cutoff:
                upcoming.append({
                    "name": ev.get("name", ev.get("event", "Unknown")),
                    "datetime": ev_dt.isoformat(),
                    "type": ev.get("type", "macro"),
                    "blackout_before_min": ev.get("blackout_before_min", self._default_blackout_minutes),
                    "blackout_after_min": ev.get("blackout_after_min", self._default_blackout_minutes),
                })
        upcoming.sort(key=lambda e: e["datetime"])
        return upcoming

    async def refresh_earnings(self, polygon_client=None, symbols: Optional[List[str]] = None) -> None:
        """Fetch upcoming earnings dates from Polygon (graceful on 403)."""
        if not self._fetch_earnings or polygon_client is None:
            return
        import time
        now = time.time()
        if (now - self._earnings_cache_ts) < self._earnings_refresh_hours * 3600:
            return
        try:
            import httpx
            today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            future = (datetime.now(timezone.utc) + timedelta(days=7)).strftime("%Y-%m-%d")
            # Attempt Polygon earnings endpoint (may 403 on free tier)
            api_key = getattr(polygon_client, "api_key", "") or ""
            if not api_key:
                return
            url = f"https://api.polygon.io/vX/reference/financials?filing_date.gte={today}&filing_date.lte={future}&apiKey={api_key}"
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(url)
                if resp.status_code == 403:
                    logger.debug("Polygon earnings endpoint requires paid tier")
                    self._earnings_cache_ts = now
                    return
                resp.raise_for_status()
                data = resp.json()
            results = data.get("results", [])
            earnings = []
            for r in results:
                ticker = r.get("tickers", [None])[0] if r.get("tickers") else None
                if symbols and ticker not in symbols:
                    continue
                filing_date = r.get("filing_date", "")
                if filing_date:
                    earnings.append({
                        "name": f"Earnings: {ticker}",
                        "datetime": f"{filing_date}T14:00:00Z",
                        "type": "earnings",
                        "blackout_before_min": 60,
                        "blackout_after_min": 30,
                    })
            self._earnings_cache = earnings
            self._earnings_cache_ts = now
            logger.info("Refreshed earnings calendar", count=len(earnings))
        except Exception as e:
            logger.warning("Earnings refresh failed (non-fatal)", error=repr(e))
            self._earnings_cache_ts = now  # Don't retry immediately

    def _parse_event_time(self, ev: Dict) -> Optional[datetime]:
        """Parse event datetime from various formats."""
        raw = ev.get("datetime") or ev.get("date")
        if raw is None:
            return None
        try:
            if isinstance(raw, datetime):
                dt = raw
            elif "T" in str(raw):
                dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
            else:
                dt = datetime.strptime(str(raw), "%Y-%m-%d").replace(hour=14, minute=30)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except Exception:
            return None

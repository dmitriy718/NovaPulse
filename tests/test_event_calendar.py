"""Tests for Feature 1: Macro Event Calendar with Auto-Pause."""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.utils.event_calendar import EventCalendar
from src.core.config import BotConfig, EventCalendarConfig


# ---------------------------------------------------------------------------
# Unit tests
# ---------------------------------------------------------------------------

class TestEventCalendarUnit:
    def _make_events_file(self, events, tmp_path):
        path = os.path.join(tmp_path, "events.json")
        with open(path, "w") as f:
            json.dump({"events": events}, f)
        return path

    def test_is_blackout_during_event(self, tmp_path):
        now = datetime(2026, 3, 18, 18, 10, tzinfo=timezone.utc)
        events = [{"name": "FOMC", "datetime": "2026-03-18T18:00:00Z", "blackout_before_min": 30, "blackout_after_min": 60}]
        path = self._make_events_file(events, tmp_path)
        cal = EventCalendar(events_file=path, blackout_minutes=30)
        is_bo, name = cal.is_blackout(now)
        assert is_bo is True
        assert name == "FOMC"

    def test_is_blackout_outside_event(self, tmp_path):
        now = datetime(2026, 3, 18, 20, 0, tzinfo=timezone.utc)
        events = [{"name": "FOMC", "datetime": "2026-03-18T18:00:00Z", "blackout_before_min": 30, "blackout_after_min": 60}]
        path = self._make_events_file(events, tmp_path)
        cal = EventCalendar(events_file=path)
        is_bo, name = cal.is_blackout(now)
        assert is_bo is False
        assert name is None

    def test_blackout_boundary_exact(self, tmp_path):
        events = [{"name": "CPI", "datetime": "2026-03-12T12:30:00Z", "blackout_before_min": 15, "blackout_after_min": 30}]
        path = self._make_events_file(events, tmp_path)
        cal = EventCalendar(events_file=path)
        # Exact start of blackout
        start = datetime(2026, 3, 12, 12, 15, tzinfo=timezone.utc)
        assert cal.is_blackout(start)[0] is True
        # Exact end of blackout
        end = datetime(2026, 3, 12, 13, 0, tzinfo=timezone.utc)
        assert cal.is_blackout(end)[0] is True
        # 1 second after
        after = datetime(2026, 3, 12, 13, 0, 1, tzinfo=timezone.utc)
        assert cal.is_blackout(after)[0] is False

    def test_get_upcoming_events_filters_past(self, tmp_path):
        past = (datetime.now(timezone.utc) - timedelta(hours=5)).isoformat()
        future = (datetime.now(timezone.utc) + timedelta(hours=5)).isoformat()
        events = [
            {"name": "Past Event", "datetime": past},
            {"name": "Future Event", "datetime": future},
        ]
        path = self._make_events_file(events, tmp_path)
        cal = EventCalendar(events_file=path)
        upcoming = cal.get_upcoming_events(hours_ahead=24)
        assert len(upcoming) == 1
        assert upcoming[0]["name"] == "Future Event"

    def test_load_events_from_json(self, tmp_path):
        events = [
            {"name": "A", "datetime": "2026-06-01T12:00:00Z"},
            {"name": "B", "datetime": "2026-06-02T12:00:00Z"},
        ]
        path = self._make_events_file(events, tmp_path)
        cal = EventCalendar(events_file=path)
        assert len(cal._events) == 2

    def test_load_events_missing_file_graceful(self):
        cal = EventCalendar(events_file="/nonexistent/path.json")
        assert len(cal._events) == 0
        is_bo, name = cal.is_blackout()
        assert is_bo is False

    def test_custom_blackout_minutes(self, tmp_path):
        now = datetime(2026, 3, 18, 17, 45, tzinfo=timezone.utc)
        events = [{"name": "FOMC", "datetime": "2026-03-18T18:00:00Z"}]
        path = self._make_events_file(events, tmp_path)
        # Default 30 min -> 17:30 should be in blackout
        cal = EventCalendar(events_file=path, blackout_minutes=30)
        assert cal.is_blackout(now)[0] is True
        # Custom 10 min -> 17:50 cutoff, 17:45 is outside
        cal2 = EventCalendar(events_file=path, blackout_minutes=10)
        assert cal2.is_blackout(now)[0] is False

    def test_multiple_events_same_day(self, tmp_path):
        events = [
            {"name": "CPI", "datetime": "2026-03-12T12:30:00Z", "blackout_before_min": 15, "blackout_after_min": 30},
            {"name": "FOMC", "datetime": "2026-03-12T18:00:00Z", "blackout_before_min": 30, "blackout_after_min": 60},
        ]
        path = self._make_events_file(events, tmp_path)
        cal = EventCalendar(events_file=path)
        # During CPI blackout
        assert cal.is_blackout(datetime(2026, 3, 12, 12, 20, tzinfo=timezone.utc))[0] is True
        # Between events
        assert cal.is_blackout(datetime(2026, 3, 12, 14, 0, tzinfo=timezone.utc))[0] is False
        # During FOMC blackout
        assert cal.is_blackout(datetime(2026, 3, 12, 18, 30, tzinfo=timezone.utc))[0] is True


# ---------------------------------------------------------------------------
# Integration tests
# ---------------------------------------------------------------------------

class TestEventCalendarIntegration:
    def _make_events_file(self, events, tmp_path):
        path = os.path.join(str(tmp_path), "events.json")
        with open(path, "w") as f:
            json.dump({"events": events}, f)
        return path

    @pytest.mark.asyncio
    async def test_executor_gate_blocks_during_blackout(self, tmp_path):
        from tests.conftest import make_executor, make_signal
        events = [{"name": "FOMC", "datetime": "2026-03-18T18:00:00Z", "blackout_before_min": 30, "blackout_after_min": 60}]
        path = self._make_events_file(events, tmp_path)
        cal = EventCalendar(events_file=path)
        executor, rm = make_executor()
        executor.set_event_calendar(cal)
        signal = make_signal()
        # Verify is_blackout returns True when called with a time inside the window
        cal_is_bo, _ = cal.is_blackout(datetime(2026, 3, 18, 18, 10, tzinfo=timezone.utc))
        assert cal_is_bo is True
        # Mock is_blackout on the calendar so the executor gate sees a blackout
        with patch.object(cal, "is_blackout", return_value=(True, "FOMC")):
            result = await executor._check_gates(signal, "buy", "keltner")
            assert result is False

    @pytest.mark.asyncio
    async def test_executor_gate_passes_outside_blackout(self, tmp_path):
        from tests.conftest import make_executor, make_signal
        events = [{"name": "FOMC", "datetime": "2026-03-18T18:00:00Z", "blackout_before_min": 30, "blackout_after_min": 60}]
        path = self._make_events_file(events, tmp_path)
        cal = EventCalendar(events_file=path)
        executor, rm = make_executor()
        executor.set_event_calendar(cal)
        signal = make_signal()
        # Outside blackout -- should pass (calendar doesn't block)
        result = await executor._check_gates(signal, "buy", "keltner")
        assert result is True

    def test_event_calendar_with_config_disabled(self):
        cfg = EventCalendarConfig(enabled=False)
        assert cfg.enabled is False
        assert cfg.blackout_minutes == 30

    def test_config_parses_event_calendar(self):
        cfg = BotConfig(event_calendar={"enabled": True, "blackout_minutes": 45})
        assert cfg.event_calendar.enabled is True
        assert cfg.event_calendar.blackout_minutes == 45

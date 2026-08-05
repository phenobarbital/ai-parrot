"""TASK-2140: Clock-event write surface — delete, location/cost-centre override, GPS."""
from __future__ import annotations

from datetime import UTC, datetime

import pytest
from parrot_tools.interfaces.workday.handlers.put_time_clock_events import (
    PutTimeClockEventsType,
)
from parrot_tools.interfaces.workday.models.clock_event import ClockEvent

_NOW = datetime(2026, 1, 1, tzinfo=UTC)


def _base_event(**overrides) -> ClockEvent:
    defaults = {
        "employee_id": "E1",
        "event_datetime": _NOW,
        "clock_event_type": "In",
    }
    defaults.update(overrides)
    return ClockEvent(**defaults)


class TestClockEventModel:
    def test_delete_requires_event_id(self):
        with pytest.raises(ValueError, match="time_clock_event_id"):
            _base_event(delete=True)

    def test_delete_with_event_id_is_valid(self):
        ev = _base_event(delete=True, time_clock_event_id="TCE-1")
        assert ev.delete is True
        assert ev.time_clock_event_id == "TCE-1"

    @pytest.mark.parametrize("lat,lon", [(91.0, 0.0), (0.0, 181.0), (-91.0, 0.0), (0.0, -181.0)])
    def test_gps_out_of_range_rejected(self, lat, lon):
        with pytest.raises(ValueError):
            _base_event(latitude=lat, longitude=lon)

    def test_gps_in_range_accepted(self):
        ev = _base_event(latitude=37.7749, longitude=-122.4194)
        assert ev.latitude == 37.7749
        assert ev.longitude == -122.4194

    def test_backwards_compatible_construction(self):
        """Pre-existing fields alone still construct a valid ClockEvent."""
        ev = ClockEvent(
            employee_id="E1",
            event_datetime=_NOW,
            clock_event_type="Out",
            position_id="P1",
            time_zone="America/New_York",
            time_entry_code="REG",
            auto_submit=True,
            comment="test",
        )
        assert ev.employee_id == "E1"
        assert ev.delete is False
        assert ev.location is None
        assert ev.cost_center is None
        assert ev.override_rate is None
        assert ev.latitude is None
        assert ev.longitude is None

    def test_new_fields_default_to_none_or_false(self):
        ev = _base_event()
        assert ev.delete is False
        assert ev.location is None
        assert ev.cost_center is None
        assert ev.override_rate is None
        assert ev.latitude is None
        assert ev.longitude is None


class TestPayloadEmission:
    def _build(self, events: list[ClockEvent]) -> dict:
        handler = PutTimeClockEventsType.__new__(PutTimeClockEventsType)
        return handler.build_request(events=events)

    def test_delete_flag_emitted(self):
        ev = _base_event(delete=True, time_clock_event_id="TCE-1")
        payload = self._build([ev])
        item = payload["Time_Clock_Event_Data"][0]
        assert item["Delete_Time_Clock_Event"] is True

    def test_delete_flag_omitted_when_false(self):
        ev = _base_event()
        payload = self._build([ev])
        item = payload["Time_Clock_Event_Data"][0]
        assert "Delete_Time_Clock_Event" not in item

    def test_location_and_cost_center_emitted(self):
        ev = _base_event(location="Warehouse B", cost_center="CC-100")
        payload = self._build([ev])
        item = payload["Time_Clock_Event_Data"][0]
        assert item["Location"] == "Warehouse B"
        assert item["Cost_Center"] == "CC-100"

    def test_location_and_cost_center_omitted_when_unset(self):
        ev = _base_event()
        payload = self._build([ev])
        item = payload["Time_Clock_Event_Data"][0]
        assert "Location" not in item
        assert "Cost_Center" not in item

    def test_override_rate_zero_is_sent(self):
        """Presence-based: 0 must be emitted, not skipped as falsy."""
        ev = _base_event(override_rate=0)
        payload = self._build([ev])
        item = payload["Time_Clock_Event_Data"][0]
        assert "Override_Rate" in item
        assert item["Override_Rate"] == 0

    def test_override_rate_positive_is_sent(self):
        ev = _base_event(override_rate=15.5)
        payload = self._build([ev])
        item = payload["Time_Clock_Event_Data"][0]
        assert item["Override_Rate"] == 15.5

    def test_override_rate_none_is_omitted(self):
        ev = _base_event()
        payload = self._build([ev])
        item = payload["Time_Clock_Event_Data"][0]
        assert "Override_Rate" not in item

    def test_gps_never_serialised(self):
        """lat/lon set → absent from the payload entirely."""
        ev = _base_event(latitude=37.7749, longitude=-122.4194)
        payload = self._build([ev])
        item = payload["Time_Clock_Event_Data"][0]
        assert "latitude" not in item
        assert "longitude" not in item
        assert "Latitude" not in item
        assert "Longitude" not in item
        # Full payload string never carries the values either.
        assert "37.7749" not in str(payload)
        assert "-122.4194" not in str(payload)

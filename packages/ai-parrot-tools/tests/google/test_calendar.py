"""Tests for GoogleCalendarToolkit (FEAT-453, Module 7).

FEAT-453 TASK-2393. All tests mock CalendarClient directly — no network,
no real aiogoogle discovery.
"""
from unittest.mock import AsyncMock

import pytest
from parrot_tools.google.calendar import GoogleCalendarToolkit


@pytest.fixture
def mock_calendar():
    """A fake CalendarClient — the object GoogleClient.get_calendar_client()
    would return once authenticated."""
    calendar = AsyncMock()
    calendar.insert_event = AsyncMock(
        return_value={
            "id": "evt1",
            "summary": "Modelo 303 Q1",
            "start": {"dateTime": "2026-04-01T09:00:00+02:00"},
            "end": {"dateTime": "2026-04-01T09:30:00+02:00"},
            "htmlLink": "https://calendar.google.com/evt1",
        }
    )
    calendar.list_events = AsyncMock(
        return_value={
            "items": [
                {
                    "id": "evt1",
                    "summary": "Modelo 303 Q1",
                    "start": {"dateTime": "2026-04-01T09:00:00+02:00"},
                    "end": {"dateTime": "2026-04-01T09:30:00+02:00"},
                }
            ]
        }
    )
    calendar.patch_event = AsyncMock(
        return_value={
            "id": "evt1",
            "summary": "Modelo 303 Q1 (rescheduled)",
            "start": {"dateTime": "2026-04-02T09:00:00+02:00"},
            "end": {"dateTime": "2026-04-02T09:30:00+02:00"},
        }
    )
    return calendar


@pytest.fixture
def mock_google_client(mock_calendar):
    client = AsyncMock()
    client.get_calendar_client = AsyncMock(return_value=mock_calendar)
    return client


@pytest.fixture
def toolkit(mock_google_client):
    return GoogleCalendarToolkit(google_client=mock_google_client)


class TestCalendar:
    async def test_create_event_body(self, toolkit, mock_calendar):
        result = await toolkit.create_event(
            summary="Modelo 303 Q1",
            start="2026-04-01T09:00:00+02:00",
            end="2026-04-01T09:30:00+02:00",
        )
        assert result["status"] == "success"
        args, _kwargs = mock_calendar.insert_event.call_args
        calendar_id, body = args
        assert calendar_id == "primary"
        assert body["summary"] == "Modelo 303 Q1"
        assert body["start"] == {"dateTime": "2026-04-01T09:00:00+02:00"}
        assert body["end"] == {"dateTime": "2026-04-01T09:30:00+02:00"}

    async def test_create_event_returns_structured_result(self, toolkit):
        result = await toolkit.create_event(
            summary="Modelo 303 Q1",
            start="2026-04-01T09:00:00+02:00",
            end="2026-04-01T09:30:00+02:00",
        )
        event = result["event"]
        assert event["id"] == "evt1"
        assert event["summary"] == "Modelo 303 Q1"
        assert event["start"] == "2026-04-01T09:00:00+02:00"

    async def test_create_event_with_description(self, toolkit, mock_calendar):
        await toolkit.create_event(
            summary="x",
            start="2026-04-01T09:00:00+02:00",
            end="2026-04-01T09:30:00+02:00",
            description="quarterly VAT return",
        )
        _args, _kwargs = mock_calendar.insert_event.call_args
        body = _args[1]
        assert body["description"] == "quarterly VAT return"

    async def test_list_events_range(self, toolkit, mock_calendar):
        result = await toolkit.list_events(
            time_min="2026-01-01T00:00:00Z", time_max="2026-04-01T00:00:00Z"
        )
        assert mock_calendar.list_events.called
        _args, kwargs = mock_calendar.list_events.call_args
        assert kwargs["timeMin"] == "2026-01-01T00:00:00Z"
        assert kwargs["timeMax"] == "2026-04-01T00:00:00Z"
        assert len(result["events"]) == 1

    async def test_update_event_partial_body(self, toolkit, mock_calendar):
        result = await toolkit.update_event(
            event_id="evt1", start="2026-04-02T09:00:00+02:00"
        )
        args, _kwargs = mock_calendar.patch_event.call_args
        calendar_id, event_id, body = args
        assert calendar_id == "primary"
        assert event_id == "evt1"
        # Only 'start' was supplied -> only 'start' appears in the patch body.
        assert body == {"start": {"dateTime": "2026-04-02T09:00:00+02:00"}}
        assert result["event"]["summary"] == "Modelo 303 Q1 (rescheduled)"

    async def test_naive_datetime_rejected_on_create(self, toolkit):
        with pytest.raises(ValueError, match="timezone"):
            await toolkit.create_event(
                summary="x", start="2026-04-01T09:00:00", end="2026-04-01T09:30:00"
            )

    async def test_naive_datetime_rejected_on_update(self, toolkit):
        with pytest.raises(ValueError, match="timezone"):
            await toolkit.update_event(event_id="evt1", start="2026-04-01T09:00:00")

    async def test_custom_calendar_id_override(self, toolkit, mock_calendar):
        await toolkit.create_event(
            summary="x",
            start="2026-04-01T09:00:00+02:00",
            end="2026-04-01T09:30:00+02:00",
            calendar_id="team@example.test",
        )
        args, _kwargs = mock_calendar.insert_event.call_args
        assert args[0] == "team@example.test"

    async def test_calendar_client_acquired_lazily_once(self, toolkit, mock_google_client):
        await toolkit.create_event(
            summary="a", start="2026-04-01T09:00:00+02:00", end="2026-04-01T09:30:00+02:00"
        )
        await toolkit.list_events(time_min="2026-01-01T00:00:00Z", time_max="2026-04-01T00:00:00Z")
        mock_google_client.get_calendar_client.assert_awaited_once()

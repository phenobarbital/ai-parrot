"""GoogleCalendarToolkit — Google Calendar v3 event tools (FEAT-453, Module 7).

Goal G6: Google Calendar event tools for the Spanish tax-calendar reminder
scheduler (TASK-2394). Built on :class:`~parrot.interfaces.google.CalendarClient`
(promoted from a bare config dict in this same task), which reuses
``GoogleClient.execute_api_call``'s existing aiogoogle auth/discovery
plumbing — **not** ``google-api-python-client``, which this repository does
not use for Google services (see this task's Completion Note for the
Codebase Contract correction).
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import TYPE_CHECKING, Any, Dict, Optional

from parrot.tools.toolkit import AbstractToolkit
from pydantic import BaseModel

if TYPE_CHECKING:
    from parrot.interfaces.google import CalendarClient, GoogleClient

logger = logging.getLogger(__name__)

#: Default Calendar id when the caller does not name one explicitly.
_DEFAULT_CALENDAR_ID = "primary"


class CalendarEvent(BaseModel):
    """Structured representation of a Calendar v3 event — never the raw API dict."""

    id: Optional[str] = None
    summary: str
    description: Optional[str] = None
    start: str
    end: str
    html_link: Optional[str] = None


def _require_tz_aware(value: str, field: str) -> datetime:
    """Parse *value* as an ISO-8601 datetime, requiring a timezone offset.

    Spanish filing deadlines are date-critical; a naive datetime silently
    drifts across DST/timezone boundaries.

    Raises:
        ValueError: If *value* does not parse, or parses without a
            timezone offset.
    """
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{field!r} is not a valid ISO-8601 datetime: {value!r}") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{field!r} must include a timezone offset (got {value!r}); " "naive datetimes are rejected")
    return parsed


def _event_from_api(raw: Dict[str, Any]) -> CalendarEvent:
    """Convert a raw Calendar v3 event resource into a :class:`CalendarEvent`."""
    start = raw.get("start", {}) or {}
    end = raw.get("end", {}) or {}
    return CalendarEvent(
        id=raw.get("id"),
        summary=raw.get("summary", ""),
        description=raw.get("description"),
        start=start.get("dateTime") or start.get("date") or "",
        end=end.get("dateTime") or end.get("date") or "",
        html_link=raw.get("htmlLink"),
    )


class GoogleCalendarToolkit(AbstractToolkit):
    """Google Calendar v3 event tools: ``create_event``, ``list_events``,
    ``update_event``.

    ``auto_open = True`` (FEAT-391): the live :class:`CalendarClient` is
    acquired lazily on first tool call via ``GoogleClient.get_calendar_client()``.
    """

    auto_open = True

    def __init__(
        self,
        google_client: GoogleClient,
        calendar_id: str = _DEFAULT_CALENDAR_ID,
        **kwargs: Any,
    ) -> None:
        """Initialize the toolkit.

        Args:
            google_client: An authenticated
                :class:`~parrot.interfaces.google.GoogleClient`.
            calendar_id: Default Calendar id for every tool call (default
                ``"primary"``); each method also accepts a per-call override.
            **kwargs: Forwarded to :class:`AbstractToolkit`.
        """
        super().__init__(**kwargs)
        self._google_client = google_client
        self.calendar_id = calendar_id
        self._calendar: Optional[CalendarClient] = None

    async def _open(self) -> None:
        """Acquire the live Calendar v3 client."""
        self._calendar = await self._google_client.get_calendar_client()

    async def _close(self) -> None:
        """Release the calendar client reference."""
        self._calendar = None
        await super()._close()

    async def create_event(
        self,
        summary: str,
        start: str,
        end: str,
        description: Optional[str] = None,
        calendar_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Create a Calendar v3 event.

        Args:
            summary: Event title.
            start: ISO-8601 start datetime — MUST include a timezone offset.
            end: ISO-8601 end datetime — MUST include a timezone offset.
            description: Optional event description.
            calendar_id: Calendar to insert into (defaults to
                ``self.calendar_id``).

        Returns:
            ``{"status": "success", "event": <CalendarEvent dict>}``.

        Raises:
            ValueError: If ``start``/``end`` is not a timezone-aware
                ISO-8601 datetime.
        """
        _require_tz_aware(start, "start")
        _require_tz_aware(end, "end")
        await self._ensure_open()

        body: Dict[str, Any] = {
            "summary": summary,
            "start": {"dateTime": start},
            "end": {"dateTime": end},
        }
        if description:
            body["description"] = description

        raw = await self._calendar.insert_event(calendar_id or self.calendar_id, body)
        return {"status": "success", "event": _event_from_api(raw).model_dump()}

    async def list_events(
        self,
        time_min: str,
        time_max: str,
        calendar_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """List events in ``[time_min, time_max)``.

        Args:
            time_min: Inclusive lower bound (ISO-8601, RFC3339).
            time_max: Exclusive upper bound (ISO-8601, RFC3339).
            calendar_id: Calendar to query (defaults to ``self.calendar_id``).

        Returns:
            ``{"status": "success", "events": [<CalendarEvent dict>, ...]}``.
        """
        await self._ensure_open()
        raw = await self._calendar.list_events(calendar_id or self.calendar_id, timeMin=time_min, timeMax=time_max)
        items = raw.get("items", []) if isinstance(raw, dict) else []
        return {
            "status": "success",
            "events": [_event_from_api(item).model_dump() for item in items],
        }

    async def update_event(
        self,
        event_id: str,
        summary: Optional[str] = None,
        start: Optional[str] = None,
        end: Optional[str] = None,
        description: Optional[str] = None,
        calendar_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Partially update an event — unset fields are left untouched
        (Calendar v3 PATCH semantics; never a full overwrite/PUT).

        Args:
            event_id: The event to update.
            summary: New title, if changing.
            start: New ISO-8601 start datetime (timezone-aware), if changing.
            end: New ISO-8601 end datetime (timezone-aware), if changing.
            description: New description, if changing.
            calendar_id: Calendar the event lives in (defaults to
                ``self.calendar_id``).

        Returns:
            ``{"status": "success", "event": <CalendarEvent dict>}``.

        Raises:
            ValueError: If a supplied ``start``/``end`` is not
                timezone-aware.
        """
        body: Dict[str, Any] = {}
        if summary is not None:
            body["summary"] = summary
        if start is not None:
            _require_tz_aware(start, "start")
            body["start"] = {"dateTime": start}
        if end is not None:
            _require_tz_aware(end, "end")
            body["end"] = {"dateTime": end}
        if description is not None:
            body["description"] = description

        await self._ensure_open()
        raw = await self._calendar.patch_event(calendar_id or self.calendar_id, event_id, body)
        return {"status": "success", "event": _event_from_api(raw).model_dump()}

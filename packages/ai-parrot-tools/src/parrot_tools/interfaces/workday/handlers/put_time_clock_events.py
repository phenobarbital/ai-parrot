"""PutTimeClockEventsType — handler for Put_Time_Clock_Events.

Builds the SOAP request body from a list of ClockEvent models, invokes
``self.service.call_operation(operation="Put_Time_Clock_Events", ...)``,
and parses the acknowledgment into a per-row ClockEventResult DataFrame.

SOAP body shapes (verified in timetracking_custom_44_2.wsdl + Workday WWS v46.1):
- Time_Clock_Event_Data repeats per event (maxOccurs unbounded).
- Clock_Event_Type_Reference  → {"ID": {"type": "Clock_Event_Type", "_value_1": "In|Break|Meal|Out"}}
- Time_Zone_Reference          → {"ID": {"type": "Time_Zone_ID", "_value_1": <tz>}}
- Employee_ID / Position_ID / Time_Clock_Event_ID / Time_Entry_Code → plain xsd:string.
- Time_Clock_Event_Date_Time   → xsd:dateTime (isoformat).

Acknowledgment:
- Put_Time_Clock_Events_Response → {"Response_Text": str} ONLY (no per-event WID, any version).
- Put is ATOMIC: a Validation_Fault/Processing_Fault marks ALL rows failed.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, List

import pandas as pd

from parrot_tools.interfaces.workday.handlers.base import WorkdayWriteTypeBase
from parrot_tools.interfaces.workday.models.clock_event import ClockEvent, ClockEventResult


def _isoformat_dt(dt: datetime) -> str:
    """Serialise a datetime as Workday-compatible xsd:dateTime string."""
    if dt.tzinfo is None:
        # Assume UTC when no timezone info present
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


class PutTimeClockEventsType(WorkdayWriteTypeBase):
    """Handler for ``Put_Time_Clock_Events`` (real-time clock-event submission).

    Args:
        service: ``WorkdayService`` instance (provides ``call_operation``).
        events: Validated ``list[ClockEvent]`` — set by the caller via ``execute``.
    """

    def _operation_name(self) -> str:
        return "Put_Time_Clock_Events"

    def build_request(self, events: List[ClockEvent], **kwargs) -> dict:  # type: ignore[override]
        """Build the Put_Time_Clock_Events SOAP body.

        Args:
            events: Pre-validated list of ClockEvent models.

        Returns:
            Dict with ``Time_Clock_Event_Data`` list ready for Zeep.
        """
        event_data = []
        for ev in events:
            item: dict[str, Any] = {
                "Time_Clock_Event_Date_Time": _isoformat_dt(ev.event_datetime),
                "Clock_Event_Type_Reference": {
                    "ID": {
                        "type": "Clock_Event_Type",
                        "_value_1": ev.clock_event_type,
                    }
                },
                "Auto_Submit": ev.auto_submit,
            }
            # Plain-string fields — only include when set
            if ev.time_clock_event_id:
                item["Time_Clock_Event_ID"] = ev.time_clock_event_id
            if ev.employee_id:
                item["Employee_ID"] = ev.employee_id
            if ev.position_id:
                item["Position_ID"] = ev.position_id
            if ev.time_zone:
                item["Time_Zone_Reference"] = {
                    "ID": {
                        "type": "Time_Zone_ID",
                        "_value_1": ev.time_zone,
                    }
                }
            if ev.time_entry_code:
                item["Time_Entry_Code"] = ev.time_entry_code
            if ev.comment:
                item["Comment"] = ev.comment
            event_data.append(item)

        return {"Time_Clock_Event_Data": event_data}

    def parse_ack(self, raw: Any) -> pd.DataFrame:  # type: ignore[override]
        """Parse Put_Time_Clock_Events_Response into a per-row status DataFrame.

        Put is atomic: a single Response_Text means ALL events succeeded.
        A Validation_Fault/Processing_Fault will have raised before this point
        (zeep raises on SOAP faults automatically), so arriving here means success.

        The event_id for each row is the CLIENT-assigned Time_Clock_Event_ID
        we sent (Workday returns no per-event WID in this operation).

        Args:
            raw: Raw Zeep response object (Put_Time_Clock_Events_Response).

        Returns:
            DataFrame with columns: submitted, event_id, error.
        """
        # Stored during build_request via execute; we re-read from last call
        return self._last_result

    async def execute(self, events: List[ClockEvent], **kwargs) -> pd.DataFrame:  # type: ignore[override]
        """Execute Put_Time_Clock_Events and return per-row status DataFrame.

        Overrides the base ``execute`` template to capture ``events`` so that
        ``parse_ack`` can echo back the per-event ``time_clock_event_id``.

        Args:
            events: Validated list of ClockEvent models.

        Returns:
            DataFrame with one row per input event: submitted, event_id, error.
        """
        import asyncio

        self._events = events
        operation = self._operation_name()
        request_body = self.build_request(events=events, **kwargs)

        for attempt in range(1, self.max_retries + 1):
            try:
                await self.service.call_operation(
                    operation=operation, **request_body
                )
                break
            except Exception as exc:
                # Check if it's a SOAP fault (Validation_Fault / Processing_Fault)
                exc_str = str(exc)
                is_fault = any(
                    kw in exc_str
                    for kw in ("Validation_Fault", "Processing_Fault", "SOAP", "Fault")
                )
                self._logger.warning(
                    "[%s] Write attempt %d/%d failed: %s",
                    operation,
                    attempt,
                    self.max_retries,
                    exc,
                )
                if is_fault or attempt == self.max_retries:
                    # Fault → atomic failure: mark ALL rows failed
                    self._logger.error(
                        "[%s] SOAP fault on attempt %d — marking all %d event(s) failed: %s",
                        operation,
                        attempt,
                        len(events),
                        exc,
                    )
                    results = [
                        ClockEventResult(
                            submitted=False,
                            event_id=ev.time_clock_event_id,
                            error=exc_str,
                        )
                        for ev in events
                    ]
                    return pd.DataFrame([r.model_dump() for r in results])
                await asyncio.sleep(self.retry_delay)

        # Success — echo back the client-assigned Time_Clock_Event_ID
        results = [
            ClockEventResult(
                submitted=True,
                event_id=ev.time_clock_event_id,
                error=None,
            )
            for ev in events
        ]
        return pd.DataFrame([r.model_dump() for r in results])

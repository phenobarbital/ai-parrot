"""ImportTimeClockEventsType — handler for Import_Time_Clock_Events.

Builds the SOAP request body from a list of ClockEvent models, invokes
``self.service.call_operation(operation="Import_Time_Clock_Events", ...)``,
and parses the Put_Import_Process_ResponseType into a per-row status DataFrame.

SOAP body shapes: same field types as Put (clock event data), plus optional
batch_id.

Acknowledgment (Import_Time_Clock_Events_Response → Put_Import_Process_ResponseType):
  { "Import_Process_Reference": <ref>, "Header_Instance_Reference": <ref> }
  This is an ASYNC background process — we surface the reference but do NOT poll
  for terminal status (Non-Goal per spec §1).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, List, Optional

import pandas as pd
from zeep.helpers import serialize_object

from parrot_tools.interfaces.workday.handlers.base import WorkdayWriteTypeBase
from parrot_tools.interfaces.workday.models.clock_event import ClockEvent, ClockEventResult


def _isoformat_dt(dt: datetime) -> str:
    """Serialise a datetime as Workday-compatible xsd:dateTime string."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


class ImportTimeClockEventsType(WorkdayWriteTypeBase):
    """Handler for ``Import_Time_Clock_Events`` (batch async import).

    The response carries a single ``Import_Process_Reference`` for the whole
    batch; this reference is echoed as ``event_id`` on every output row.
    No terminal-status polling is performed (Non-Goal).

    Args:
        service: ``WorkdayService`` instance.
    """

    def _operation_name(self) -> str:
        return "Import_Time_Clock_Events"

    def build_request(  # type: ignore[override]
        self,
        events: List[ClockEvent],
        batch_id: Optional[str] = None,
        **kwargs,
    ) -> dict:
        """Build the Import_Time_Clock_Events SOAP body.

        Args:
            events: Pre-validated list of ClockEvent models.
            batch_id: Optional batch identifier.

        Returns:
            Dict with Time_Clock_Event_Data list (and optional batch_id).
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

        body: dict[str, Any] = {"Time_Clock_Event_Data": event_data}
        if batch_id:
            body["Batch_ID"] = batch_id
        return body

    def parse_ack(self, raw: Any) -> pd.DataFrame:  # type: ignore[override]
        """Parse Put_Import_Process_ResponseType into a per-row status DataFrame.

        The single ``Import_Process_Reference`` is set as ``event_id`` on every
        row in the batch (all rows belong to the same async process).

        Args:
            raw: Raw Zeep response (Put_Import_Process_ResponseType).

        Returns:
            DataFrame with columns: submitted, event_id, error.
        """
        data = serialize_object(raw, target_cls=dict) if raw is not None else {}
        if isinstance(data, dict):
            import_ref = data.get("Import_Process_Reference")
            if import_ref is None:
                import_ref = data.get("import_process_reference")
        else:
            import_ref = None

        # Normalise the reference to a string
        if import_ref is not None and not isinstance(import_ref, str):
            import_ref = str(import_ref)

        events = getattr(self, "_events", [])
        results = [
            ClockEventResult(
                submitted=True,
                event_id=import_ref,
                error=None,
            )
            for _ in events
        ]
        return pd.DataFrame([r.model_dump() for r in results])

    async def execute(  # type: ignore[override]
        self,
        events: List[ClockEvent],
        batch_id: Optional[str] = None,
        **kwargs,
    ) -> pd.DataFrame:
        """Execute Import_Time_Clock_Events and return per-row status DataFrame.

        Args:
            events: Validated list of ClockEvent models.
            batch_id: Optional batch identifier.

        Returns:
            DataFrame with one row per input event: submitted, event_id, error.
            event_id = Import_Process_Reference (same for all rows, async).
        """
        import asyncio

        self._events = events
        operation = self._operation_name()
        request_body = self.build_request(events=events, batch_id=batch_id, **kwargs)

        raw = None
        for attempt in range(1, self.max_retries + 1):
            try:
                raw = await self.service.call_operation(
                    operation=operation, **request_body
                )
                break
            except Exception as exc:
                exc_str = str(exc)
                is_fault = any(
                    kw in exc_str
                    for kw in ("Validation_Fault", "Processing_Fault", "SOAP", "Fault")
                )
                self._logger.warning(
                    "[%s] Import attempt %d/%d failed: %s",
                    operation,
                    attempt,
                    self.max_retries,
                    exc,
                )
                if is_fault or attempt == self.max_retries:
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
                            event_id=None,
                            error=exc_str,
                        )
                        for _ in events
                    ]
                    return pd.DataFrame([r.model_dump() for r in results])
                await asyncio.sleep(self.retry_delay)

        return self.parse_ack(raw)

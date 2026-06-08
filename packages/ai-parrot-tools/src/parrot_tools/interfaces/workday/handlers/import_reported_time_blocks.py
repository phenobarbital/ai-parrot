"""ImportReportedTimeBlocksType — handler for Import_Reported_Time_Blocks.

Builds the SOAP request body from a list of ReportedTimeBlock models, invokes
``self.service.call_operation(operation="Import_Reported_Time_Blocks", ...)``,
and parses the Put_Import_Process_ResponseType into a per-row status DataFrame.

Acknowledgment shape (same as Import_Time_Clock_Events):
  { "Import_Process_Reference": <ref>, "Header_Instance_Reference": <ref> }
  Async background process — reference surfaced but NOT polled (Non-Goal).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, List

import pandas as pd
from zeep.helpers import serialize_object

from parrot_tools.interfaces.workday.handlers.base import WorkdayWriteTypeBase
from parrot_tools.interfaces.workday.models.clock_event import (
    ClockEventResult,
    ReportedTimeBlock,
)


def _isoformat_dt(dt: datetime) -> str:
    """Serialise a datetime as Workday-compatible xsd:dateTime string."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


class ImportReportedTimeBlocksType(WorkdayWriteTypeBase):
    """Handler for ``Import_Reported_Time_Blocks`` (batch async import).

    Args:
        service: ``WorkdayService`` instance.
    """

    def _operation_name(self) -> str:
        return "Import_Reported_Time_Blocks"

    def build_request(  # type: ignore[override]
        self,
        blocks: List[ReportedTimeBlock],
        **kwargs,
    ) -> dict:
        """Build the Import_Reported_Time_Blocks SOAP body.

        Args:
            blocks: Pre-validated list of ReportedTimeBlock models.

        Returns:
            Dict with Reported_Time_Block_Data list ready for Zeep.
        """
        block_data = []
        for blk in blocks:
            item: dict[str, Any] = {
                "Employee_ID": blk.employee_id,
                "Start_Date_Time": _isoformat_dt(blk.start_datetime),
            }
            if blk.position_id:
                item["Position_ID"] = blk.position_id
            if blk.end_datetime:
                item["End_Date_Time"] = blk.end_datetime
            if blk.time_entry_code:
                item["Time_Entry_Code"] = blk.time_entry_code
            if blk.reported_quantity is not None:
                item["Reported_Quantity"] = blk.reported_quantity
            if blk.comment:
                item["Comment"] = blk.comment
            block_data.append(item)

        return {"Reported_Time_Block_Data": block_data}

    def parse_ack(self, raw: Any) -> pd.DataFrame:  # type: ignore[override]
        """Parse Put_Import_Process_ResponseType into a per-row status DataFrame.

        The single ``Import_Process_Reference`` is echoed as ``event_id`` on
        every output row.

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

        if import_ref is not None and not isinstance(import_ref, str):
            import_ref = str(import_ref)

        blocks = getattr(self, "_blocks", [])
        results = [
            ClockEventResult(
                submitted=True,
                event_id=import_ref,
                error=None,
            )
            for _ in blocks
        ]
        return pd.DataFrame([r.model_dump() for r in results])

    async def execute(  # type: ignore[override]
        self,
        blocks: List[ReportedTimeBlock],
        **kwargs,
    ) -> pd.DataFrame:
        """Execute Import_Reported_Time_Blocks and return per-row status DataFrame.

        Args:
            blocks: Validated list of ReportedTimeBlock models.

        Returns:
            DataFrame with one row per input block: submitted, event_id, error.
            event_id = Import_Process_Reference (same for all rows, async).
        """
        import asyncio

        self._blocks = blocks
        operation = self._operation_name()
        request_body = self.build_request(blocks=blocks, **kwargs)

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
                        "[%s] SOAP fault on attempt %d — marking all %d block(s) failed: %s",
                        operation,
                        attempt,
                        len(blocks),
                        exc,
                    )
                    results = [
                        ClockEventResult(
                            submitted=False,
                            event_id=None,
                            error=exc_str,
                        )
                        for _ in blocks
                    ]
                    return pd.DataFrame([r.model_dump() for r in results])
                await asyncio.sleep(self.retry_delay)

        return self.parse_ack(raw)

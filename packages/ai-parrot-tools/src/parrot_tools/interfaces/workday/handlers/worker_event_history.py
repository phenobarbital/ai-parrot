"""Worker event history handler (FEAT-706, HR WSDL ``Get_Worker_Event_History``)."""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import date, datetime, time, timezone
from typing import Any

import pandas as pd
from zeep.exceptions import Fault

from ..models.worker_event import ResolvedWorkerReference, WorkerEvent
from ..utils.utils import ensure_list, extract_by_type, first
from .base import WorkdayTypeBase

logger = logging.getLogger(__name__)

WORKER_ID_TYPES: tuple[str, ...] = ("WID", "Employee_ID", "Contingent_Worker_ID")
SYSTEM_ID_WID: str = "WD-WID"
INVALID_ID_FAULT: str = "Invalid ID value"
_WID_RE = re.compile(r"^[0-9a-f]{32}$")


def candidate_worker_id_types(worker_id: str, worker_id_type: str | None = None) -> tuple[str, ...]:
    """Return the worker identifier types to try, in order.

    Args:
        worker_id: Worker identifier value.
        worker_id_type: Explicit Workday identifier type, if known.

    Returns:
        The ordered identifier types for the lookup.

    Raises:
        ValueError: If ``worker_id_type`` is not a supported identifier type.
    """
    if worker_id_type is not None:
        if worker_id_type not in WORKER_ID_TYPES:
            raise ValueError(f"Unsupported worker_id_type: {worker_id_type}")
        return (worker_id_type,)
    if _WID_RE.fullmatch(worker_id):
        return ("WID",)
    return ("Employee_ID", "Contingent_Worker_ID")


def build_event_history_worker_reference(ref: ResolvedWorkerReference) -> dict[str, Any]:
    """Build the ``Worker_Reference`` choice element for ``Worker_Event_History_Get``."""
    key = "Contingent_Worker_Reference" if ref.is_contingent else "Employee_Reference"
    return {key: {"Integration_ID_Reference": {"ID": {"_value_1": ref.wid, "System_ID": SYSTEM_ID_WID}}}}


def _as_date(value: date | str | None) -> date | None:
    """Normalise an ISO date string, date, or None to a date or None."""
    if value is None or isinstance(value, date):
        return value
    return date.fromisoformat(value)


def build_event_date_range(
    effective_from: date | str | None,
    effective_through: date | str | None,
    updated_from: date | str | None,
    updated_through: date | str | None,
) -> dict[str, datetime] | None:
    """Build ``Event_Date_Range_Data`` after validating date-pair constraints.

    Raises:
        ValueError: If a range pair is incomplete, inverted, or ends in the future.
    """
    effective_from_date = _as_date(effective_from)
    effective_through_date = _as_date(effective_through)
    updated_from_date = _as_date(updated_from)
    updated_through_date = _as_date(updated_through)

    if (effective_from_date is None) != (effective_through_date is None):
        raise ValueError("effective_from and effective_through must be provided together")
    if (updated_from_date is None) != (updated_through_date is None):
        raise ValueError("updated_from and updated_through must be provided together")
    if effective_from_date is not None and effective_from_date > effective_through_date:
        raise ValueError("effective_from must not be after effective_through")
    if updated_from_date is not None and updated_from_date > updated_through_date:
        raise ValueError("updated_from must not be after updated_through")
    if updated_through_date is not None and updated_through_date > date.today():
        raise ValueError("updated_through must not be in the future")

    result: dict[str, datetime] = {}
    if effective_from_date is not None:
        result["Effective_From"] = datetime.combine(effective_from_date, time.min)
        result["Effective_Through"] = datetime.combine(effective_through_date, time(23, 59, 59))
    if updated_from_date is not None:
        result["Updated_From"] = datetime.combine(updated_from_date, time.min)
        result["Updated_Through"] = datetime.combine(updated_through_date, time(23, 59, 59))
    return result or None


async def resolve_worker_reference(
    service: Any,
    worker_id: str,
    worker_id_type: str | None = None,
    max_retries: int = 3,
    retry_delay: float = 0.5,
) -> ResolvedWorkerReference:
    """Resolve any worker identifier to its WID-based reference.

    Raises:
        LookupError: If no candidate identifies a returned worker.
        ValueError: If an explicit worker identifier type is unsupported.
    """
    last_invalid: Exception | None = None
    for id_type in candidate_worker_id_types(worker_id, worker_id_type):
        invalid_for_candidate = False
        payload = {
            "Request_References": {"Worker_Reference": [{"ID": {"type": id_type, "_value_1": worker_id}}]},
            "Response_Group": {"Include_Reference": True, "Include_Personal_Information": True},
        }
        for attempt in range(1, max_retries + 1):
            try:
                raw = await service.call_operation(operation="Get_Workers", **payload)
                break
            except Fault as exc:
                if INVALID_ID_FAULT in str(exc):
                    last_invalid = exc
                    invalid_for_candidate = True
                    break
                if attempt == max_retries:
                    raise
                logger.warning(
                    "Get_Workers failed for %s as %s (attempt %s/%s): %s",
                    worker_id,
                    id_type,
                    attempt,
                    max_retries,
                    exc,
                )
                await asyncio.sleep(retry_delay)
            except Exception as exc:
                if attempt == max_retries:
                    raise
                logger.warning(
                    "Get_Workers failed for %s as %s (attempt %s/%s): %s",
                    worker_id,
                    id_type,
                    attempt,
                    max_retries,
                    exc,
                )
                await asyncio.sleep(retry_delay)
        else:
            continue

        if invalid_for_candidate:
            continue

        data = service.serialize_object(raw) if raw else {}
        workers = [
            worker
            for response_data in ensure_list(data.get("Response_Data"))
            for worker in ensure_list((response_data or {}).get("Worker"))
        ]
        worker = first(workers)
        if not worker:
            raise LookupError(f"No worker found for {worker_id}")

        worker_reference = first(worker.get("Worker_Reference"))
        identifiers = worker_reference.get("ID", [])
        legal_name = (
            worker.get("Worker_Data", {})
            .get("Personal_Data", {})
            .get("Name_Data", {})
            .get("Legal_Name_Data", {})
            .get("Name_Detail_Data", {})
        )
        wid = extract_by_type(identifiers, "WID")
        if not wid:
            raise LookupError(f"No WID returned for {worker_id}")
        return ResolvedWorkerReference(
            wid=wid,
            employee_id=extract_by_type(identifiers, "Employee_ID"),
            contingent_worker_id=extract_by_type(identifiers, "Contingent_Worker_ID"),
            formatted_name=legal_name.get("Formatted_Name"),
        )

    message = f"No worker found for {worker_id}"
    if last_invalid is not None:
        raise LookupError(message) from last_invalid
    raise LookupError(message)


def _completed_sort_key(value: datetime | None) -> datetime:
    """Return a comparable UTC-naive timestamp for an event completion time."""
    if value is None:
        return datetime.min
    if value.tzinfo is not None:
        return value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


class WorkerEventHistoryType(WorkdayTypeBase):
    """Handler for ``get_worker_event_history`` (HR WSDL, ``Get_Worker_Event_History``)."""

    def _get_default_payload(self) -> dict[str, Any]:
        """Return the unpaged operation's empty default payload."""
        return {}

    async def execute(
        self,
        worker_id: str,
        worker_id_type: str | None = None,
        effective_from: date | str | None = None,
        effective_through: date | str | None = None,
        updated_from: date | str | None = None,
        updated_through: date | str | None = None,
        **kwargs: Any,
    ) -> pd.DataFrame:
        """Return one row per worker event, sorted by effective and completion dates."""
        date_range = build_event_date_range(effective_from, effective_through, updated_from, updated_through)
        ref = await resolve_worker_reference(
            self.service,
            worker_id,
            worker_id_type,
            self.max_retries,
            self.retry_delay,
        )
        request: dict[str, Any] = {"Worker_Reference": build_event_history_worker_reference(ref)}
        if date_range:
            request["Event_Date_Range_Data"] = date_range
        self._logger.info("Get_Worker_Event_History for %s (%s)", ref.wid, ref.formatted_name)
        raw = await self.service.call_operation(operation="Get_Worker_Event_History", **request)
        data = self.service.serialize_object(raw) if raw else {}
        events: list[WorkerEvent] = []
        for history in ensure_list(data.get("Worker_Event_History_Data")):
            for event in ensure_list((history or {}).get("Event_Data")):
                event_type_reference = first(event.get("Event_Type_Reference"))
                events.append(
                    WorkerEvent(
                        worker_wid=ref.wid,
                        event_id=event.get("Event_ID", ""),
                        event_type=event_type_reference.get("Event_Type_Name"),
                        description=event.get("Description"),
                        effective_date=event.get("Effective_Date"),
                        completed_at=event.get("Completed_DateTime"),
                    )
                )
        events.sort(key=lambda event: (event.effective_date or date.min, _completed_sort_key(event.completed_at)))
        self.parsed = events
        columns = list(WorkerEvent.model_fields)
        return pd.DataFrame([event.model_dump() for event in events], columns=columns)

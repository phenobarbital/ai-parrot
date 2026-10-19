"""Worker job-changes handler (FEAT-706): as-of snapshots diffed per job event."""

from __future__ import annotations

import asyncio
from datetime import date, timedelta
from typing import Any

import pandas as pd
from zeep.exceptions import Fault

from ..models.worker_event import (
    COMPENSATION_EVENT_TYPES,
    JOB_CHANGE_EVENT_TYPES,
    FieldChange,
    JobChange,
    JobSnapshot,
    WorkerEvent,
)
from ..parsers.worker_parsers import (
    parse_business_site,
    parse_compensation_data,
    parse_employment_data,
    parse_management_chain_data,
    parse_worker_organization_data,
    parse_worker_status,
)
from ..utils.utils import ensure_list
from .base import WorkdayTypeBase
from .worker_event_history import (
    INVALID_ID_FAULT,
    build_event_date_range,
    build_event_history_worker_reference,
    resolve_worker_reference,
)

SNAPSHOT_RESPONSE_GROUP: dict[str, bool] = {
    "Include_Reference": True,
    "Include_Employment_Information": True,
    "Include_Organizations": True,
    "Include_Management_Chain_Data": True,
}


def parse_job_snapshot(worker: dict[str, Any], as_of: date, include_compensation: bool = False) -> JobSnapshot | None:
    """Compose existing worker parsers into one snapshot.

    Args:
        worker: Serialized ``Get_Workers`` Worker element.
        as_of: Effective date represented by the snapshot.
        include_compensation: Whether to compose compensation parser data.

    Returns:
        A snapshot, or ``None`` when the worker has no job data at ``as_of``.
    """
    worker_data = (worker or {}).get("Worker_Data") or {}
    if not ensure_list((worker_data.get("Employment_Data") or {}).get("Worker_Job_Data")):
        return None

    employment = parse_employment_data(worker_data)
    business_site = parse_business_site(worker_data)
    organization = parse_worker_organization_data(worker_data)
    management = parse_management_chain_data(worker_data)
    status = parse_worker_status(worker_data)
    values: dict[str, Any] = {
        "as_of": as_of,
        **{
            key: employment.get(key)
            for key in (
                "position_id",
                "position_title",
                "business_title",
                "job_profile_id",
                "job_profile_name",
                "job_family",
                "management_level",
                "job_category",
                "worker_type",
                "position_time_type",
                "pay_rate_type",
                "scheduled_weekly_hours",
                "full_time_equivalent_percentage",
            )
        },
        "position_effective_date": (
            str(employment["position_effective_date"])
            if employment.get("position_effective_date") is not None
            else None
        ),
        "location_name": business_site.get("business_site_name"),
        "location_id": business_site.get("business_site_location_id"),
        **{
            key: organization.get(key)
            for key in (
                "supervisory_organization_id",
                "supervisory_organization_name",
                "cost_center_id",
                "cost_center_name",
                "cost_center_hierarchy_name",
                "company_id",
                "company_name",
                "pay_group_id",
                "pay_group_name",
                "primary_organization_name",
            )
        },
        "direct_manager_id": management.get("direct_manager_id"),
        "direct_manager_name": management.get("direct_manager_name"),
        "active": status.get("active"),
        "hire_date": str(status["hire_date"]) if status.get("hire_date") is not None else None,
    }
    if include_compensation:
        compensation = parse_compensation_data(worker_data)
        salary_rows = compensation.get("salary_and_hourly") or []
        paid_row = next((row for row in salary_rows if row.get("amount") is not None), None)
        guidelines = compensation.get("compensation_guidelines") or {}
        values.update(
            wage=compensation.get("wage"),
            pay_currency=paid_row.get("currency") if paid_row else None,
            pay_frequency=paid_row.get("frequency") if paid_row else None,
            compensation_package=guidelines.get("package"),
            compensation_grade=guidelines.get("grade"),
            compensation_grade_profile=guidelines.get("profile"),
            compensation_effective_date=compensation.get("compensation_effective_date"),
            compensation_elements=[
                {
                    "plan": row.get("plan"),
                    "element": row.get("element"),
                    "amount": float(row["amount"]) if row.get("amount") is not None else None,
                    "currency": row.get("currency"),
                    "frequency": row.get("frequency"),
                }
                for row in salary_rows
            ],
        )
    return JobSnapshot(**values)


def diff_snapshots(before: JobSnapshot | None, after: JobSnapshot) -> list[FieldChange]:
    """Return changed snapshot fields, excluding metadata fields.

    Args:
        before: Snapshot from the preceding date, if one exists.
        after: Snapshot at the event's effective date.

    Returns:
        Typed changes, or an empty list for a hire.
    """
    if before is None:
        return []
    return [
        FieldChange(field=name, before=getattr(before, name), after=getattr(after, name))
        for name in JobSnapshot.model_fields
        if name not in JobSnapshot.DIFF_EXCLUDE and getattr(before, name) != getattr(after, name)
    ]


def group_job_events(events: list[WorkerEvent], event_types: tuple[str, ...]) -> dict[date, list[WorkerEvent]]:
    """Filter and group events by ascending effective date.

    Args:
        events: Event history rows to filter.
        event_types: Exact event type names to retain.

    Returns:
        Event groups keyed by ascending effective date.
    """
    grouped: dict[date, list[WorkerEvent]] = {}
    for event in events:
        if event.event_type not in event_types or event.effective_date is None:
            continue
        grouped.setdefault(event.effective_date, []).append(event)
    return {event_date: grouped[event_date] for event_date in sorted(grouped)}


class WorkerJobChangesType(WorkdayTypeBase):
    """Handle ``get_worker_job_changes`` through event history and as-of snapshots."""

    snapshot_concurrency: int = 4

    def _get_default_payload(self) -> dict[str, Any]:
        """Return this handler's empty default payload."""
        return {}

    async def _snapshot(
        self,
        wid: str,
        as_of: date,
        include_compensation: bool = False,
        memo: dict[date, Any] | None = None,
        sem: asyncio.Semaphore | None = None,
    ) -> JobSnapshot | None:
        """Fetch one WID snapshot once per as-of date within an execution."""
        memo = memo if memo is not None else {}
        if as_of in memo:
            value = memo[as_of]
            return await value if isinstance(value, asyncio.Future) else value
        semaphore = sem or asyncio.Semaphore(self.snapshot_concurrency)

        async def fetch() -> JobSnapshot | None:
            response_group = dict(SNAPSHOT_RESPONSE_GROUP)
            if include_compensation:
                response_group["Include_Compensation"] = True
            payload = {
                "Request_References": {"Worker_Reference": [{"ID": {"type": "WID", "_value_1": wid}}]},
                "Response_Filter": {"As_Of_Effective_Date": as_of.isoformat()},
                "Response_Group": response_group,
            }
            try:
                async with semaphore:
                    raw = await self.service.call_operation(operation="Get_Workers", **payload)
            except Fault as exc:
                if INVALID_ID_FAULT in str(exc):
                    return None
                raise
            data = self.service.serialize_object(raw) if raw else {}
            workers = [
                worker
                for response_data in ensure_list(data.get("Response_Data"))
                for worker in ensure_list((response_data or {}).get("Worker"))
            ]
            return parse_job_snapshot(workers[0], as_of, include_compensation) if workers else None

        task = asyncio.create_task(fetch())
        memo[as_of] = task
        return await task

    async def _fetch_events(self, ref: Any, effective_from: Any, effective_through: Any) -> list[WorkerEvent]:
        """Fetch and flatten one raw Worker Event History response."""
        date_range = build_event_date_range(effective_from, effective_through, None, None)
        request: dict[str, Any] = {"Worker_Reference": build_event_history_worker_reference(ref)}
        if date_range:
            request["Event_Date_Range_Data"] = date_range
        raw = await self.service.call_operation(operation="Get_Worker_Event_History", **request)
        data = self.service.serialize_object(raw) if raw else {}
        events: list[WorkerEvent] = []
        for history in ensure_list(data.get("Worker_Event_History_Data")):
            for event in ensure_list((history or {}).get("Event_Data")):
                event_type_reference = ensure_list(event.get("Event_Type_Reference"))
                event_type = event_type_reference[0].get("Event_Type_Name") if event_type_reference else None
                events.append(
                    WorkerEvent(
                        worker_wid=ref.wid,
                        event_id=event.get("Event_ID", ""),
                        event_type=event_type,
                        description=event.get("Description"),
                        effective_date=event.get("Effective_Date"),
                        completed_at=event.get("Completed_DateTime"),
                    )
                )
        return events

    async def execute(
        self,
        worker_id: str,
        worker_id_type: str | None = None,
        effective_from: date | str | None = None,
        effective_through: date | str | None = None,
        event_types: tuple[str, ...] | None = None,
        include_unchanged: bool = False,
        include_compensation: bool = False,
        **kwargs: Any,
    ) -> pd.DataFrame:
        """Return one change row per effective date in ascending order."""
        if event_types is None:
            event_types = JOB_CHANGE_EVENT_TYPES + (COMPENSATION_EVENT_TYPES if include_compensation else ())
        ref = await resolve_worker_reference(
            self.service, worker_id, worker_id_type, self.max_retries, self.retry_delay
        )
        groups = group_job_events(await self._fetch_events(ref, effective_from, effective_through), tuple(event_types))
        memo: dict[date, Any] = {}
        semaphore = asyncio.Semaphore(self.snapshot_concurrency)
        snapshot_pairs = await asyncio.gather(
            *(
                asyncio.gather(
                    self._snapshot(ref.wid, event_date - timedelta(days=1), include_compensation, memo, semaphore),
                    self._snapshot(ref.wid, event_date, include_compensation, memo, semaphore),
                )
                for event_date in groups
            )
        )
        rows: list[JobChange] = []
        for (event_date, events), (before, after) in zip(groups.items(), snapshot_pairs, strict=True):
            if after is None:
                self._logger.warning("No worker snapshot available for %s as of %s", ref.wid, event_date)
                continue
            changes = diff_snapshots(before, after)
            kind = "hire" if before is None else "no_change" if not changes else "change"
            if kind == "no_change" and not include_unchanged:
                continue
            rows.append(
                JobChange(
                    worker_wid=ref.wid,
                    effective_date=event_date,
                    kind=kind,
                    event_ids=[event.event_id for event in events],
                    event_types=[event.event_type for event in events if event.event_type is not None],
                    descriptions=[event.description for event in events if event.description is not None],
                    before=before,
                    after=after,
                    changes=changes,
                    includes_compensation=include_compensation,
                )
            )
        self.parsed = rows
        return pd.DataFrame([row.model_dump() for row in rows], columns=list(JobChange.model_fields))

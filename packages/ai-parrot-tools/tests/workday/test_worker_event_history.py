"""FEAT-706 — worker event-history handler (fake service, no live tenant)."""

from datetime import date, datetime, timedelta

import pytest
from zeep.exceptions import Fault

from parrot_tools.interfaces.workday.handlers.worker_event_history import (
    WorkerEventHistoryType,
    build_event_date_range,
    build_event_history_worker_reference,
    candidate_worker_id_types,
    resolve_worker_reference,
)
from parrot_tools.interfaces.workday.models.worker_event import ResolvedWorkerReference, WorkerEvent

WID = "0123456789abcdef0123456789abcdef"


def _ref(**ids):
    return {
        "ID": [{"type": identifier_type, "_value_1": value} for identifier_type, value in ids.items()],
        "Descriptor": None,
    }


WORKER_RESPONSE = {
    "Response_Data": {
        "Worker": {
            "Worker_Reference": _ref(WID=WID, Employee_ID="100001"),
            "Worker_Data": {
                "Personal_Data": {
                    "Name_Data": {"Legal_Name_Data": {"Name_Detail_Data": {"Formatted_Name": "Jane Doe"}}}
                }
            },
        }
    }
}

EVENT_HISTORY_RESPONSE = {
    "Worker_Event_History_Data": {
        "Event_Data": [
            {
                "Event_ID": "EV-1",
                "Event_Type_Reference": {"Event_Type_Name": "Change Job"},
                "Description": "Job change",
                "Completed_DateTime": datetime(2026, 6, 9, 9),
                "Effective_Date": date(2026, 6, 8),
            },
            {
                "Event_ID": "EV-2",
                "Event_Type_Reference": {"Event_Type_Name": "Hire"},
                "Description": "Hire",
                "Completed_DateTime": datetime(2022, 9, 27, 9),
                "Effective_Date": date(2022, 9, 26),
            },
            {
                "Event_ID": "EV-3",
                "Event_Type_Reference": {"Event_Type_Name": "Enter Time"},
                "Description": "Time",
                "Completed_DateTime": datetime(2026, 5, 1, 9),
                "Effective_Date": date(2026, 5, 1),
            },
            {
                "Event_ID": "EV-4",
                "Event_Type_Reference": {"Event_Type_Name": "Change Job"},
                "Description": "Another job change",
                "Completed_DateTime": datetime(2026, 6, 8, 10),
                "Effective_Date": date(2026, 6, 8),
            },
            {
                "Event_ID": "EV-5",
                "Event_Type_Reference": {"Event_Type_Name": "Change Organization Assignments for Worker"},
                "Description": "Organization",
                "Completed_DateTime": datetime(2026, 5, 1, 8),
                "Effective_Date": date(2026, 5, 1),
            },
            {
                "Event_ID": "EV-6",
                "Event_Type_Reference": {"Event_Type_Name": "Edit Position"},
                "Description": "Position",
                "Completed_DateTime": datetime(2026, 7, 1, 9),
                "Effective_Date": date(2026, 7, 1),
            },
        ]
    }
}


class _FakeService:
    def __init__(self, responses_by_operation=None, faults_by_id_type=None):
        self.responses_by_operation = responses_by_operation or {}
        self.faults_by_id_type = {key: list(value) for key, value in (faults_by_id_type or {}).items()}
        self.calls = []

    async def call_operation(self, operation, **kwargs):
        self.calls.append((operation, kwargs))
        if operation == "Get_Workers":
            id_type = kwargs["Request_References"]["Worker_Reference"][0]["ID"]["type"]
            outcomes = self.faults_by_id_type.get(id_type, [])
            if outcomes:
                outcome = outcomes.pop(0)
                if isinstance(outcome, Exception):
                    raise outcome
                return outcome
        return self.responses_by_operation.get(operation, WORKER_RESPONSE)

    def serialize_object(self, obj):
        return obj


def _invalid(id_type):
    return Fault(f"Invalid ID value for type {id_type}")


def test_candidate_worker_id_types():
    assert candidate_worker_id_types(WID) == ("WID",)
    assert candidate_worker_id_types("835104") == ("Employee_ID", "Contingent_Worker_ID")
    assert candidate_worker_id_types("835104", "Contingent_Worker_ID") == ("Contingent_Worker_ID",)
    with pytest.raises(ValueError):
        candidate_worker_id_types("835104", "Unknown")


def test_build_event_history_worker_reference_employee():
    ref = ResolvedWorkerReference(wid=WID, employee_id="100001")
    assert build_event_history_worker_reference(ref) == {
        "Employee_Reference": {"Integration_ID_Reference": {"ID": {"_value_1": WID, "System_ID": "WD-WID"}}}
    }


def test_build_event_history_worker_reference_contingent():
    ref = ResolvedWorkerReference(wid=WID, contingent_worker_id="CW-1")
    assert build_event_history_worker_reference(ref) == {
        "Contingent_Worker_Reference": {"Integration_ID_Reference": {"ID": {"_value_1": WID, "System_ID": "WD-WID"}}}
    }


def test_build_event_date_range_pairs():
    with pytest.raises(ValueError):
        build_event_date_range(date(2026, 1, 1), None, None, None)
    with pytest.raises(ValueError):
        build_event_date_range(date(2026, 2, 1), date(2026, 1, 1), None, None)
    with pytest.raises(ValueError):
        build_event_date_range(None, None, None, date.today() + timedelta(days=1))
    result = build_event_date_range("2026-01-01", "2026-01-02", "2026-02-01", "2026-02-02")
    assert result == {
        "Effective_From": datetime(2026, 1, 1),
        "Effective_Through": datetime(2026, 1, 2, 23, 59, 59),
        "Updated_From": datetime(2026, 2, 1),
        "Updated_Through": datetime(2026, 2, 2, 23, 59, 59),
    }


@pytest.mark.asyncio
async def test_resolve_worker_reference_by_wid():
    service = _FakeService()
    resolved = await resolve_worker_reference(service, WID)
    assert resolved == ResolvedWorkerReference(wid=WID, employee_id="100001", formatted_name="Jane Doe")
    assert service.calls[0][1]["Request_References"]["Worker_Reference"][0]["ID"]["type"] == "WID"


@pytest.mark.asyncio
async def test_resolve_worker_reference_by_employee_id():
    service = _FakeService()
    resolved = await resolve_worker_reference(service, "100001", "Employee_ID")
    assert resolved.wid == WID
    assert resolved.employee_id == "100001"
    assert resolved.formatted_name == "Jane Doe"
    assert service.calls[0][1]["Request_References"]["Worker_Reference"][0]["ID"]["type"] == "Employee_ID"


@pytest.mark.asyncio
async def test_resolve_worker_reference_contingent_fallback():
    contingent_response = {
        "Response_Data": {
            "Worker": {
                "Worker_Reference": _ref(WID=WID, Contingent_Worker_ID="CW-1"),
                "Worker_Data": {
                    "Personal_Data": {
                        "Name_Data": {"Legal_Name_Data": {"Name_Detail_Data": {"Formatted_Name": "Jane Doe"}}}
                    }
                },
            }
        }
    }
    service = _FakeService(
        faults_by_id_type={"Employee_ID": [_invalid("Employee_ID")], "Contingent_Worker_ID": [contingent_response]}
    )
    resolved = await resolve_worker_reference(service, "CW-1")
    assert resolved.contingent_worker_id == "CW-1"
    assert [call[1]["Request_References"]["Worker_Reference"][0]["ID"]["type"] for call in service.calls] == [
        "Employee_ID",
        "Contingent_Worker_ID",
    ]


@pytest.mark.asyncio
async def test_resolve_worker_reference_not_found():
    service = _FakeService(responses_by_operation={"Get_Workers": {"Response_Data": {"Worker": []}}})
    with pytest.raises(LookupError):
        await resolve_worker_reference(service, "missing", "Employee_ID")

    rejected = _FakeService(
        faults_by_id_type={
            "Employee_ID": [_invalid("Employee_ID")],
            "Contingent_Worker_ID": [_invalid("Contingent_Worker_ID")],
        }
    )
    with pytest.raises(LookupError):
        await resolve_worker_reference(rejected, "missing")


@pytest.mark.asyncio
async def test_event_history_execute_rows_sorted():
    handler = WorkerEventHistoryType(_FakeService({"Get_Worker_Event_History": EVENT_HISTORY_RESPONSE}), retry_delay=0)
    frame = await handler.execute("100001")
    assert list(frame.columns) == list(WorkerEvent.model_fields)
    assert list(frame["event_id"]) == ["EV-2", "EV-5", "EV-3", "EV-4", "EV-1", "EV-6"]
    assert isinstance(handler.parsed, list)
    assert all(isinstance(event, WorkerEvent) for event in handler.parsed)


@pytest.mark.asyncio
async def test_event_history_passes_date_range():
    service = _FakeService({"Get_Worker_Event_History": EVENT_HISTORY_RESPONSE})
    handler = WorkerEventHistoryType(service, retry_delay=0)
    await handler.execute("100001", effective_from="2026-01-01", effective_through="2026-01-31")
    event_call = next(call for call in service.calls if call[0] == "Get_Worker_Event_History")
    assert event_call[1]["Event_Date_Range_Data"] == {
        "Effective_From": datetime(2026, 1, 1),
        "Effective_Through": datetime(2026, 1, 31, 23, 59, 59),
    }


@pytest.mark.asyncio
async def test_date_range_error_makes_no_call():
    service = _FakeService()
    handler = WorkerEventHistoryType(service, retry_delay=0)
    with pytest.raises(ValueError):
        await handler.execute("100001", effective_from="2026-01-01")
    assert service.calls == []

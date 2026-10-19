"""FEAT-706 worker job-changes handler tests using a fake Workday service."""
from datetime import date

import pytest

from parrot_tools.interfaces.workday.handlers.worker_job_changes import (
    SNAPSHOT_RESPONSE_GROUP,
    WorkerJobChangesType,
    diff_snapshots,
    group_job_events,
    parse_job_snapshot,
)
from parrot_tools.interfaces.workday.models.worker_event import JobSnapshot, WorkerEvent

WID = "0123456789abcdef0123456789abcdef"


def _id(identifier_type: str, value: str) -> dict[str, str]:
    """Build a serialized Workday ID node."""
    return {"type": identifier_type, "_value_1": value}


def _worker(position_id: str = "MEX559647", title: str = "Payroll Coordinator", wage: float = 20.0) -> dict:
    """Build the compact serialized worker response used by the snapshots."""
    return {
        "Worker_Data": {
            "Employment_Data": {
                "Worker_Job_Data": [{
                    "Position_Data": {
                        "Position_Reference": {"ID": [_id("Position_ID", position_id)]},
                        "Position_Title": title,
                        "Business_Title": title,
                        "Effective_Date": "2026-06-08",
                        "Job_Profile_Summary_Data": {
                            "Job_Profile_Reference": {"ID": [_id("Job_Profile_ID", "PROFILE-1")]},
                            "Job_Profile_Name": title,
                        },
                    }
                }],
                "Worker_Status_Data": {"Active": True, "Hire_Date": "2022-09-26"},
            },
            "Organization_Data": [],
            "Management_Chain_Data": {},
            "Compensation_Data": {
                "Compensation_Effective_Date": "2026-05-25",
                "Salary_and_Hourly_Data": [{
                    "Amount": str(wage),
                    "Compensation_Plan_Reference": {"ID": [_id("Compensation_Plan_ID", "BASE")]},
                    "Compensation_Element_Reference": {"ID": [_id("Compensation_Element_ID", "SALARY")]},
                    "Currency_Reference": {"ID": [_id("Currency_ID", "USD")]},
                    "Frequency_Reference": {"ID": [_id("Frequency_ID", "Monthly")]},
                    "Assignment_Effective_Date": "2026-05-25",
                }],
                "Compensation_Guidelines_Data": [{
                    "Compensation_Package_Reference": {"ID": [_id("Compensation_Package_ID", "PKG")]},
                    "Compensation_Grade_Reference": {"ID": [_id("Compensation_Grade_ID", "G1")]},
                    "Compensation_Grade_Profile_Reference": {
                        "ID": [_id("Compensation_Grade_Profile_ID", "P1")]
                    },
                }],
            },
        }
    }


REFERENCE_RESPONSE = {
    "Response_Data": {"Worker": [{"Worker_Reference": {"ID": [_id("WID", WID)]}, "Worker_Data": {}}]}
}
EVENT_HISTORY_RESPONSE = {
    "Worker_Event_History_Data": {"Event_Data": [
        {"Event_ID": "hire", "Event_Type_Reference": {"Event_Type_Name": "Hire"}, "Effective_Date": "2022-09-26"},
        {"Event_ID": "pay", "Event_Type_Reference": {"Event_Type_Name": "Propose Compensation Change"}, "Effective_Date": "2026-05-25"},
        {"Event_ID": "job", "Event_Type_Reference": {"Event_Type_Name": "Change Job"}, "Effective_Date": "2026-06-08"},
        {"Event_ID": "org", "Event_Type_Reference": {"Event_Type_Name": "Change Organization Assignments for Worker"}, "Effective_Date": "2026-06-08"},
        {"Event_ID": "edit", "Event_Type_Reference": {"Event_Type_Name": "Edit Position"}, "Effective_Date": "2026-07-06"},
        {"Event_ID": "noise", "Event_Type_Reference": {"Event_Type_Name": "Enter Time"}, "Effective_Date": "2026-07-06"},
    ]}
}
SNAPSHOTS = {
    "2022-09-25": {"Response_Data": {"Worker": []}},
    "2022-09-26": {"Response_Data": {"Worker": [_worker()]}},
    "2026-05-24": {"Response_Data": {"Worker": [_worker(wage=20.0)]}},
    "2026-05-25": {"Response_Data": {"Worker": [_worker(wage=22.0)]}},
    "2026-06-07": {"Response_Data": {"Worker": [_worker()]}},
    "2026-06-08": {"Response_Data": {"Worker": [_worker("P104998", "Payroll Specialist")]}},
    "2026-07-05": {"Response_Data": {"Worker": [_worker("P104998", "Payroll Specialist")]}},
    "2026-07-06": {"Response_Data": {"Worker": [_worker("P104998", "Payroll Specialist")]}},
}


class _FakeService:
    """Minimal fake service recording each SOAP operation and payload."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    async def call_operation(self, operation: str, **kwargs: dict) -> dict:
        """Return fixture data for the requested operation."""
        self.calls.append((operation, kwargs))
        if operation == "Get_Worker_Event_History":
            return EVENT_HISTORY_RESPONSE
        if "Response_Filter" not in kwargs:
            return REFERENCE_RESPONSE
        return SNAPSHOTS[kwargs["Response_Filter"]["As_Of_Effective_Date"]]

    @staticmethod
    def serialize_object(value: dict) -> dict:
        """Mirror zeep serialization for already-serialized fixture dictionaries."""
        return value


def test_parse_job_snapshot_fields() -> None:
    """Job data is composed from existing worker parser values."""
    snapshot = parse_job_snapshot(_worker(), date(2026, 6, 8))
    assert snapshot is not None
    assert (snapshot.position_id, snapshot.position_title, snapshot.hire_date) == (
        "MEX559647", "Payroll Coordinator", "2022-09-26"
    )
    assert snapshot.wage is None


def test_parse_job_snapshot_prehire_returns_none() -> None:
    """An empty Worker_Job_Data is a pre-hire snapshot."""
    assert parse_job_snapshot({"Worker_Data": {"Employment_Data": {}}}, date(2022, 9, 25)) is None


def test_parse_job_snapshot_compensation_opt_in() -> None:
    """Compensation is parsed only when explicitly requested."""
    snapshot = parse_job_snapshot(_worker(wage=22.0), date(2026, 5, 25), include_compensation=True)
    assert snapshot is not None
    assert (snapshot.wage, snapshot.pay_currency, snapshot.pay_frequency) == (22.0, "USD", "Monthly")
    assert snapshot.compensation_elements == [{"plan": "BASE", "element": "SALARY", "amount": 22.0, "currency": "USD", "frequency": "Monthly"}]


@pytest.mark.asyncio
async def test_snapshot_response_group_compensation_flag() -> None:
    """Snapshot SOAP response group requests compensation only for an opted-in call."""
    service = _FakeService()
    handler = WorkerJobChangesType(service)
    await handler._snapshot(WID, date(2026, 5, 25), memo={})
    await handler._snapshot(WID, date(2026, 5, 24), include_compensation=True, memo={})
    groups = [kwargs["Response_Group"] for operation, kwargs in service.calls if operation == "Get_Workers"]
    assert groups[0] == SNAPSHOT_RESPONSE_GROUP
    assert groups[1] == {**SNAPSHOT_RESPONSE_GROUP, "Include_Compensation": True}


def test_diff_snapshots() -> None:
    """Diffs exclude the as-of metadata and retain changed values."""
    before = JobSnapshot(as_of=date(2026, 6, 7), position_id="old")
    after = JobSnapshot(as_of=date(2026, 6, 8), position_id="new")
    changes = diff_snapshots(before, after)
    assert len(changes) == 1
    assert changes[0].model_dump() == {"field": "position_id", "before": "old", "after": "new"}


def test_group_job_events_filters_and_groups() -> None:
    """Only requested typed events with effective dates are grouped in date order."""
    events = [
        WorkerEvent(worker_wid=WID, event_id="two", event_type="Change Job", effective_date=date(2026, 6, 8)),
        WorkerEvent(worker_wid=WID, event_id="one", event_type="Hire", effective_date=date(2022, 9, 26)),
        WorkerEvent(worker_wid=WID, event_id="skip", event_type="Enter Time", effective_date=date(2026, 6, 8)),
    ]
    grouped = group_job_events(events, ("Hire", "Change Job"))
    assert list(grouped) == [date(2022, 9, 26), date(2026, 6, 8)]
    assert [event.event_id for event in grouped[date(2026, 6, 8)]] == ["two"]


@pytest.mark.asyncio
async def test_job_changes_execute_before_after() -> None:
    """A position change retains typed before/after snapshots and changed fields."""
    result = await WorkerJobChangesType(_FakeService()).execute(WID)
    row = result[result["effective_date"] == date(2026, 6, 8)].iloc[0]
    assert row["kind"] == "change"
    assert row["before"]["position_id"] == "MEX559647"
    assert row["after"]["position_id"] == "P104998"
    assert {change["field"] for change in row["changes"]} >= {
        "position_id", "position_title", "business_title", "job_profile_name"
    }


@pytest.mark.asyncio
async def test_job_changes_compensation_diff() -> None:
    """Opting in includes compensation events and their wage change."""
    result = await WorkerJobChangesType(_FakeService()).execute(WID, include_compensation=True)
    row = result[result["effective_date"] == date(2026, 5, 25)].iloc[0]
    assert row["kind"] == "change"
    assert any(change["field"] == "wage" for change in row["changes"])
    assert bool(row["includes_compensation"]) is True


@pytest.mark.asyncio
async def test_job_changes_include_unchanged() -> None:
    """No-change event dates are returned only when requested."""
    handler = WorkerJobChangesType(_FakeService())
    assert date(2026, 7, 6) not in set((await handler.execute(WID))["effective_date"])
    result = await handler.execute(WID, include_unchanged=True)
    assert result[result["effective_date"] == date(2026, 7, 6)].iloc[0]["kind"] == "no_change"


@pytest.mark.asyncio
async def test_job_changes_snapshot_memoised() -> None:
    """Adjacent event dates share the same snapshot call within one execution."""
    service = _FakeService()
    await WorkerJobChangesType(service).execute(WID)
    snapshots = [kwargs for operation, kwargs in service.calls if operation == "Get_Workers" and "Response_Filter" in kwargs]
    assert len(snapshots) == len({kwargs["Response_Filter"]["As_Of_Effective_Date"] for kwargs in snapshots})


@pytest.mark.asyncio
async def test_job_changes_end_to_end_fixture() -> None:
    """The fixture yields a hire row and the documented June position transition."""
    result = await WorkerJobChangesType(_FakeService()).execute(WID)
    hire = result[result["effective_date"] == date(2022, 9, 26)].iloc[0]
    assert hire["kind"] == "hire" and hire["before"] is None and hire["changes"] == []
    june = result[result["effective_date"] == date(2026, 6, 8)].iloc[0]
    assert june["event_ids"] == ["job", "org"]
    assert not {"cost_center_id", "company_id", "pay_group_id"} & {change["field"] for change in june["changes"]}

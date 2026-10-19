"""FEAT-706 — worker-history toolkit tools (stubbed composable)."""

import json
from datetime import date, datetime

import pytest

from parrot_tools.interfaces.workday.models.worker_event import FieldChange, JobChange, JobSnapshot, WorkerEvent
from parrot_tools.workday.tool import WorkdayToolkit


class _FakeComposable:
    def __init__(self, models):
        self.models = models
        self.calls = []
        self.requested_ops = []

    async def fetch_models(self, operation_type, **params):
        self.calls.append((operation_type, params))
        return self.models


def _toolkit(monkeypatch, fake):
    tk = WorkdayToolkit()
    tk._initialized = True

    async def fake_get_composable(self, operation_type):
        fake.requested_ops.append(operation_type)
        return fake

    monkeypatch.setattr(WorkdayToolkit, "_get_composable", fake_get_composable)
    return tk


def test_tools_are_exposed():
    names = {tool.name for tool in WorkdayToolkit().get_tools()}
    assert {"wd_get_worker_event_history", "wd_get_worker_job_changes"} <= names


@pytest.mark.asyncio
async def test_wd_get_worker_event_history_delegates(monkeypatch):
    event = WorkerEvent(
        worker_wid="worker-wid",
        event_id="event-1",
        event_type="Hire",
        description="Hired",
        effective_date=date(2026, 10, 1),
        completed_at=datetime(2026, 10, 2, 9, 30),
    )
    fake = _FakeComposable([event])
    toolkit = _toolkit(monkeypatch, fake)

    result = await toolkit.wd_get_worker_event_history(
        "worker-1",
        worker_id_type="Employee_ID",
        effective_from="2026-01-01",
        effective_through="2026-10-01",
        updated_from="2026-01-02",
        updated_through="2026-10-02",
    )

    assert fake.requested_ops == ["get_worker_event_history"]
    assert fake.calls == [
        (
            "get_worker_event_history",
            {
                "worker_id": "worker-1",
                "worker_id_type": "Employee_ID",
                "effective_from": "2026-01-01",
                "effective_through": "2026-10-01",
                "updated_from": "2026-01-02",
                "updated_through": "2026-10-02",
            },
        )
    ]
    assert result[0]["effective_date"] == "2026-10-01"
    assert result[0]["completed_at"] == "2026-10-02T09:30:00"
    json.dumps(result)


@pytest.mark.asyncio
async def test_wd_get_worker_job_changes_delegates(monkeypatch):
    snapshot = JobSnapshot(as_of=date(2026, 10, 1), position_id="position-1", wage=42.5)
    change = JobChange(
        worker_wid="worker-wid",
        effective_date=date(2026, 10, 1),
        kind="change",
        event_ids=["event-1"],
        event_types=["Change Job"],
        descriptions=["Changed job"],
        after=snapshot,
        changes=[FieldChange(field="position_id", before="position-0", after="position-1")],
        includes_compensation=True,
    )
    fake = _FakeComposable([change])
    toolkit = _toolkit(monkeypatch, fake)

    result = await toolkit.wd_get_worker_job_changes(
        "worker-1",
        worker_id_type="WID",
        effective_from="2026-01-01",
        effective_through="2026-10-01",
        include_unchanged=True,
        include_compensation=True,
    )

    assert fake.requested_ops == ["get_worker_job_changes"]
    assert fake.calls == [
        (
            "get_worker_job_changes",
            {
                "worker_id": "worker-1",
                "worker_id_type": "WID",
                "effective_from": "2026-01-01",
                "effective_through": "2026-10-01",
                "include_unchanged": True,
                "include_compensation": True,
            },
        )
    ]
    assert result[0]["effective_date"] == "2026-10-01"
    assert result[0]["after"]["as_of"] == "2026-10-01"
    assert result[0]["changes"][0] == {
        "field": "position_id",
        "before": "position-0",
        "after": "position-1",
    }
    json.dumps(result)

"""Get_Workers single-worker lookup: Worker_Reference ID-type resolution."""
import logging

import pytest
from zeep.exceptions import Fault

from parrot_tools.interfaces.workday.handlers.workers import WorkerType

RAW = {"Response_Data": {"Worker": []}}


class _FakeService:
    def __init__(self, outcomes):
        self._logger = logging.getLogger("test.workday.worker_id_type")
        self.outcomes = {k: list(v) for k, v in outcomes.items()}
        self.calls = []

    async def call_operation(self, operation, **payload):
        id_type = payload["Request_References"]["Worker_Reference"][0]["ID"]["type"]
        self.calls.append(id_type)
        outcome = self.outcomes[id_type].pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def _invalid(id_type):
    return Fault(f"Validation error occurred. Invalid ID value.  'X' is not a valid ID value for type = '{id_type}'")


def _handler(service):
    return WorkerType(service, max_retries=3, retry_delay=0)


@pytest.mark.asyncio
async def test_alphanumeric_employee_id_uses_employee_id_first():
    service = _FakeService({"Employee_ID": [RAW]})

    assert await _handler(service)._fetch_single_worker("T0000005001147", ["Employee_ID", "Contingent_Worker_ID"]) is RAW
    assert service.calls == ["Employee_ID"]


@pytest.mark.asyncio
async def test_falls_back_to_contingent_without_retrying_invalid_id():
    service = _FakeService({"Employee_ID": [_invalid("Employee_ID")], "Contingent_Worker_ID": [RAW]})

    assert await _handler(service)._fetch_single_worker("TD0ATVE10", ["Employee_ID", "Contingent_Worker_ID"]) is RAW
    assert service.calls == ["Employee_ID", "Contingent_Worker_ID"]


@pytest.mark.asyncio
async def test_raises_when_no_id_type_matches():
    service = _FakeService(
        {"Employee_ID": [_invalid("Employee_ID")], "Contingent_Worker_ID": [_invalid("Contingent_Worker_ID")]}
    )

    with pytest.raises(Fault, match="Contingent_Worker_ID"):
        await _handler(service)._fetch_single_worker("NOPE", ["Employee_ID", "Contingent_Worker_ID"])
    assert service.calls == ["Employee_ID", "Contingent_Worker_ID"]


@pytest.mark.asyncio
async def test_transient_errors_are_retried():
    service = _FakeService({"Employee_ID": [ConnectionError("reset"), RAW]})

    assert await _handler(service)._fetch_single_worker("889", ["Employee_ID"]) is RAW
    assert service.calls == ["Employee_ID", "Employee_ID"]


@pytest.mark.asyncio
async def test_transient_errors_exhaust_retries():
    service = _FakeService({"Employee_ID": [ConnectionError("reset")] * 3})

    with pytest.raises(ConnectionError):
        await _handler(service)._fetch_single_worker("889", ["Employee_ID", "Contingent_Worker_ID"])
    assert service.calls == ["Employee_ID"] * 3


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kwargs,expected",
    [
        ({}, ["Employee_ID", "Contingent_Worker_ID"]),
        ({"worker_id_type": "Contingent_Worker_ID"}, ["Contingent_Worker_ID"]),
    ],
)
async def test_execute_passes_id_types(monkeypatch, kwargs, expected):
    handler = _handler(_FakeService({}))
    seen = {}

    async def fake_fetch(worker_id, id_types):
        seen["args"] = (worker_id, id_types)
        raise RuntimeError("stop")

    monkeypatch.setattr(handler, "_fetch_single_worker", fake_fetch)

    with pytest.raises(RuntimeError, match="stop"):
        await handler.execute(worker_id="T0000005001147", **kwargs)
    assert seen["args"] == ("T0000005001147", expected)

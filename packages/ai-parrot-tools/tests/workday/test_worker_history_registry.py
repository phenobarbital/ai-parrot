"""FEAT-706 — routing, registry and fetch_models round-trip for the worker-history operations."""
from datetime import date
import logging

import pandas as pd
import pytest

from parrot.conf import WORKDAY_WSDL_HUMAN_RESOURCES
from parrot_tools.interfaces.workday import service as service_mod
from parrot_tools.interfaces.workday.config import WorkdayConfig, get_wsdl_path
from parrot_tools.interfaces.workday.handlers import WorkerEventHistoryType, WorkerJobChangesType
from parrot_tools.interfaces.workday.models.worker_event import FieldChange, JobChange, JobSnapshot, WorkerEvent
from parrot_tools.interfaces.workday.service import WorkdayService

KEYS = ("get_worker_event_history", "get_worker_job_changes")


def test_routing_to_hr_wsdl():
    for key in KEYS:
        assert get_wsdl_path(key) == WORKDAY_WSDL_HUMAN_RESOURCES


def test_model_map():
    assert service_mod._OPERATION_MODEL_MAP["get_worker_event_history"] is WorkerEvent
    assert service_mod._OPERATION_MODEL_MAP["get_worker_job_changes"] is JobChange


def test_type_handlers_registered():
    # WorkdayService(config=WorkdayConfig(client_id="cid", client_secret="secret",
    #   token_url="https://example.invalid/token", refresh_token="r", tenant="t",
    #   workday_url="https://example.invalid"), operation_type="get_worker_event_history");
    #   assert isinstance(svc._type_handlers[KEYS[0]], WorkerEventHistoryType) and [KEYS[1]] → WorkerJobChangesType.
    #   Do not call start() (it loads the WSDL).
    config = WorkdayConfig(
        client_id="cid",
        client_secret="secret",
        token_url="https://example.invalid/token",
        refresh_token="r",
        tenant="t",
        workday_url="https://example.invalid"
    )
    
    # Test with get_worker_event_history
    svc1 = WorkdayService(config=config, operation_type="get_worker_event_history")
    assert isinstance(svc1._type_handlers[KEYS[0]], WorkerEventHistoryType)
    
    # Test with get_worker_job_changes
    svc2 = WorkdayService(config=config, operation_type="get_worker_job_changes")
    assert isinstance(svc2._type_handlers[KEYS[1]], WorkerJobChangesType)


@pytest.mark.asyncio
async def test_fetch_models_roundtrip(monkeypatch):
    # svc = WorkdayService.__new__(WorkdayService); set svc._logger (pattern test_fetch_models_rehydrate.py:58-59);
    #   build a JobChange(kind="change", before=JobSnapshot(...), after=JobSnapshot(...), changes=[FieldChange(...)]);
    #   fake fetch returns pd.DataFrame([jc.model_dump()]); models = await svc.fetch_models("get_worker_job_changes");
    #   assert models == [jc] (nested before/after/changes intact).
    
    # Create a JobChange with nested data
    before_snapshot = JobSnapshot(
        as_of=date(2023, 1, 1),
        position_id="P1",
        position_title="Developer"
    )
    
    after_snapshot = JobSnapshot(
        as_of=date(2023, 2, 1),
        position_id="P2",
        position_title="Senior Developer"
    )
    
    field_change = FieldChange(
        field="position_title",
        before="Developer",
        after="Senior Developer"
    )
    
    jc = JobChange(
        worker_wid="W123",
        effective_date=date(2023, 2, 1),
        kind="change",
        event_ids=["E1"],
        event_types=["Change Job"],
        descriptions=["Promotion"],
        before=before_snapshot,
        after=after_snapshot,
        changes=[field_change]
    )
    
    # Mock the fetch method to return our test data
    async def mock_fetch(operation_type, **params):
        return pd.DataFrame([jc.model_dump()])
    
    # Set up the service with minimal config
    config = WorkdayConfig(
        client_id="cid",
        client_secret="secret",
        token_url="https://example.invalid/token",
        refresh_token="r",
        tenant="t",
        workday_url="https://example.invalid"
    )
    svc = WorkdayService(config=config, operation_type="get_worker_job_changes")
    svc._logger = logging.getLogger("test")
    
    monkeypatch.setattr(svc, "fetch", mock_fetch)
    
    # Test the round-trip
    models = await svc.fetch_models("get_worker_job_changes")
    assert len(models) == 1
    assert isinstance(models[0], JobChange)
    assert models[0].worker_wid == jc.worker_wid
    assert models[0].effective_date == jc.effective_date
    assert models[0].kind == jc.kind
    
    # Check nested data integrity
    assert models[0].before is not None
    assert models[0].before.position_id == "P1"
    assert models[0].after.position_id == "P2"
    assert len(models[0].changes) == 1
    assert models[0].changes[0].field == "position_title"
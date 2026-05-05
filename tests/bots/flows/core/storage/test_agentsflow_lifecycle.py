"""Lifecycle tests for AgentsFlow constructor wiring (FEAT-147 TASK-1018).

Mirrors test_agentcrew_lifecycle.py but targets parrot.bots.flow.fsm.AgentsFlow.
"""
import pytest
from unittest.mock import MagicMock

from parrot.bots.flows.core.storage.backends import ResultStorage


class _RecordingStorage(ResultStorage):
    """ResultStorage that records calls for assertions."""

    def __init__(self) -> None:
        self.saves: list = []
        self.closed: int = 0

    async def save(self, collection: str, document: dict) -> None:
        self.saves.append((collection, document))

    async def close(self) -> None:
        self.closed += 1


# ──────────────────────────────────────────────────────────────────────────────
# Tests against parrot.bots.flow.fsm.AgentsFlow
# ──────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_agentsflow_persist_false_opens_no_connection(monkeypatch):
    """AgentsFlow(persist_results=False) must never call get_result_storage."""
    from parrot.bots.flow.fsm import AgentsFlow

    factory = MagicMock(side_effect=AssertionError("must not be called"))
    monkeypatch.setattr(
        "parrot.bots.flows.core.storage.persistence.get_result_storage",
        factory,
    )
    flow = AgentsFlow(name="X", persist_results=False)
    await flow._save_result(MagicMock(to_dict=lambda: {}), "run_flow")
    factory.assert_not_called()


@pytest.mark.asyncio
async def test_agentsflow_explicit_storage_instance_is_used():
    """AgentsFlow(result_storage=<instance>) uses that instance directly."""
    from parrot.bots.flow.fsm import AgentsFlow

    storage = _RecordingStorage()
    flow = AgentsFlow(name="X", result_storage=storage)
    await flow._save_result(MagicMock(to_dict=lambda: {"a": 1}), "run_flow")
    assert len(storage.saves) == 1


@pytest.mark.asyncio
async def test_agentsflow_aclose_releases_storage():
    """async with AgentsFlow(...) as flow: releases storage on exit."""
    from parrot.bots.flow.fsm import AgentsFlow

    storage = _RecordingStorage()
    async with AgentsFlow(name="X", result_storage=storage) as flow:
        await flow._save_result(MagicMock(to_dict=lambda: {}), "run_flow")
    assert storage.closed == 1


@pytest.mark.asyncio
async def test_agentsflow_constructor_sets_mixin_attrs():
    """All four mixin attributes are initialised on AgentsFlow."""
    from parrot.bots.flow.fsm import AgentsFlow

    flow = AgentsFlow(name="Y", persist_results=False)
    assert flow._persist_results is False
    assert flow._result_storage_arg is None
    assert flow._result_storage is None
    assert isinstance(flow._persist_tasks, set)


@pytest.mark.asyncio
async def test_agentsflow_constructor_persist_true_default():
    """AgentsFlow defaults to persist_results=True."""
    from parrot.bots.flow.fsm import AgentsFlow

    flow = AgentsFlow(name="Z")
    assert flow._persist_results is True
    assert flow._result_storage_arg is None
    assert flow._result_storage is None
    assert isinstance(flow._persist_tasks, set)

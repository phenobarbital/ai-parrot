"""Lifecycle tests for AgentCrew constructor wiring (FEAT-147 TASK-1018).

Covers both the orchestration.crew.AgentCrew and the flows.crew.AgentCrew
(the two duplicate copies that must stay in lockstep).
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
# Tests against parrot.bots.orchestration.crew.AgentCrew
# ──────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_orchestration_persist_false_opens_no_connection(monkeypatch):
    """AgentCrew(persist_results=False) must never call get_result_storage."""
    from parrot.bots.orchestration.crew import AgentCrew

    factory = MagicMock(side_effect=AssertionError("must not be called"))
    monkeypatch.setattr(
        "parrot.bots.flows.core.storage.persistence.get_result_storage",
        factory,
    )
    crew = AgentCrew(name="X", persist_results=False)
    await crew._save_result(MagicMock(to_dict=lambda: {}), "run_flow")
    factory.assert_not_called()


@pytest.mark.asyncio
async def test_orchestration_explicit_storage_instance_is_used():
    """AgentCrew(result_storage=<instance>) uses that instance directly."""
    from parrot.bots.orchestration.crew import AgentCrew

    storage = _RecordingStorage()
    crew = AgentCrew(name="X", result_storage=storage)
    await crew._save_result(MagicMock(to_dict=lambda: {"a": 1}), "run_flow")
    assert len(storage.saves) == 1


@pytest.mark.asyncio
async def test_orchestration_aclose_releases_storage():
    """async with AgentCrew(...) as crew: releases storage on exit."""
    from parrot.bots.orchestration.crew import AgentCrew

    storage = _RecordingStorage()
    async with AgentCrew(name="X", result_storage=storage) as crew:
        await crew._save_result(MagicMock(to_dict=lambda: {}), "run_flow")
    assert storage.closed == 1


@pytest.mark.asyncio
async def test_orchestration_constructor_sets_mixin_attrs():
    """All four mixin attributes are initialised on the crew."""
    from parrot.bots.orchestration.crew import AgentCrew

    crew = AgentCrew(name="Y", persist_results=False)
    assert crew._persist_results is False
    assert crew._result_storage_arg is None
    assert crew._result_storage is None
    assert isinstance(crew._persist_tasks, set)


# ──────────────────────────────────────────────────────────────────────────────
# Tests against parrot.bots.flows.crew.AgentCrew (duplicate copy)
# ──────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_flows_persist_false_opens_no_connection(monkeypatch):
    """flows.crew.AgentCrew(persist_results=False) must never call factory."""
    from parrot.bots.flows.crew.crew import AgentCrew

    factory = MagicMock(side_effect=AssertionError("must not be called"))
    monkeypatch.setattr(
        "parrot.bots.flows.core.storage.persistence.get_result_storage",
        factory,
    )
    crew = AgentCrew(name="X", persist_results=False)
    await crew._save_result(MagicMock(to_dict=lambda: {}), "run_flow")
    factory.assert_not_called()


@pytest.mark.asyncio
async def test_flows_explicit_storage_instance_is_used():
    """flows.crew.AgentCrew(result_storage=<instance>) uses that instance."""
    from parrot.bots.flows.crew.crew import AgentCrew

    storage = _RecordingStorage()
    crew = AgentCrew(name="X", result_storage=storage)
    await crew._save_result(MagicMock(to_dict=lambda: {"a": 1}), "run_flow")
    assert len(storage.saves) == 1


@pytest.mark.asyncio
async def test_flows_aclose_releases_storage():
    """async with flows.crew.AgentCrew(...) as crew: releases storage."""
    from parrot.bots.flows.crew.crew import AgentCrew

    storage = _RecordingStorage()
    async with AgentCrew(name="X", result_storage=storage) as crew:
        await crew._save_result(MagicMock(to_dict=lambda: {}), "run_flow")
    assert storage.closed == 1


@pytest.mark.asyncio
async def test_flows_constructor_sets_mixin_attrs():
    """All four mixin attributes are initialised on the flows.crew.AgentCrew."""
    from parrot.bots.flows.crew.crew import AgentCrew

    crew = AgentCrew(name="Z", persist_results=True)
    assert crew._persist_results is True
    assert crew._result_storage_arg is None
    assert crew._result_storage is None
    assert isinstance(crew._persist_tasks, set)

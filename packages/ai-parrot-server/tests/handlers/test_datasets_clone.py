"""Tests for per-user DatasetManager source cloning."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from parrot.handlers.datasets import _clone_agent_dm, _clone_source
from parrot.tools.dataset_manager import DatasetEntry, DatasetManager
from parrot.tools.dataset_manager.sources.table import TableSource


def test_clone_agent_dm_copies_source() -> None:
    """Each cloned manager owns distinct source and mutable filter objects."""
    source = TableSource(
        table="sales.orders",
        driver="pg",
        permanent_filter={"tenant_id": "corp"},
    )
    agent_dm = DatasetManager()
    agent_dm._datasets["orders"] = DatasetEntry(name="orders", source=source)
    agent = SimpleNamespace(_dataset_manager=agent_dm)
    logger = MagicMock()

    first = _clone_agent_dm(agent, logger)
    second = _clone_agent_dm(agent, logger)

    assert first is not None and second is not None
    first_source = first._datasets["orders"].source
    second_source = second._datasets["orders"].source
    assert first_source is not source
    assert second_source is not source
    assert first_source is not second_source
    assert first_source._permanent_filter is not source._permanent_filter
    assert second_source._permanent_filter is not source._permanent_filter
    assert first_source._permanent_filter is not second_source._permanent_filter

    first_source._permanent_filter["region"] = ["northeast"]
    assert source._permanent_filter == {"tenant_id": "corp"}
    assert second_source._permanent_filter == {"tenant_id": "corp"}
    assert _clone_source(None) is None

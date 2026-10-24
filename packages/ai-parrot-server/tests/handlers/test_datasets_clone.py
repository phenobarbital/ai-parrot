"""Tests for _clone_agent_dm's source isolation (issue:90cf04ce8edd)."""

from __future__ import annotations

import logging

import pandas as pd
import pytest

from parrot.handlers.datasets import _clone_agent_dm
from parrot.tools.dataset_manager import DatasetEntry, DatasetManager
from parrot.tools.dataset_manager.sources.table import TableSource


class _Agent:
    """Minimal stand-in for the agent object ``_clone_agent_dm`` reads."""

    def __init__(self, dm: DatasetManager) -> None:
        self._dataset_manager = dm


def _agent_with(entry: DatasetEntry) -> _Agent:
    """Build an agent whose DatasetManager holds exactly ``entry``."""
    dm = DatasetManager()
    dm._datasets[entry.name] = entry
    return _Agent(dm)


@pytest.fixture
def logger() -> logging.Logger:
    """Real logger — the function only calls .warning/.debug on it."""
    return logging.getLogger("test_datasets_clone")


def test_clone_agent_dm_does_not_share_source(logger: logging.Logger) -> None:
    """Each user's entry gets its own DataSource object, not the agent's."""
    entry = DatasetEntry(name="orders", source=TableSource(table="sales.orders", driver="pg"))
    agent = _agent_with(entry)

    user_dm = _clone_agent_dm(agent, logger)

    assert user_dm is not None
    cloned = user_dm._datasets["orders"]
    assert cloned.source is not entry.source


def test_clone_agent_dm_isolates_mutation(logger: logging.Logger) -> None:
    """Writing through the clone's source must not reach the agent's source.

    Uses ``_permanent_filter`` because that is the dict the RLS injectors write
    *into* — a plain shallow copy would still share it.
    """
    entry = DatasetEntry(name="orders", source=TableSource(table="sales.orders", driver="pg"))
    agent = _agent_with(entry)

    user_dm = _clone_agent_dm(agent, logger)
    assert user_dm is not None
    user_dm._datasets["orders"].source._permanent_filter["region"] = ["northeast"]

    assert "region" not in entry.source._permanent_filter


def test_clone_agent_dm_two_users_do_not_see_each_other(logger: logging.Logger) -> None:
    """The cross-subject case: two clones of one agent catalog stay separate."""
    entry = DatasetEntry(name="orders", source=TableSource(table="sales.orders", driver="pg"))
    agent = _agent_with(entry)

    alice = _clone_agent_dm(agent, logger)
    bob = _clone_agent_dm(agent, logger)
    assert alice is not None and bob is not None

    alice._datasets["orders"].source._permanent_filter["region"] = ["northeast"]

    assert "region" not in bob._datasets["orders"].source._permanent_filter
    assert "region" not in entry.source._permanent_filter


def test_clone_agent_dm_copies_dataframe_without_source(logger: logging.Logger) -> None:
    """A df-backed entry still clones; its source is an InMemorySource, also isolated."""
    entry = DatasetEntry(name="rows", df=pd.DataFrame({"id": [1, 2]}))
    agent = _agent_with(entry)

    user_dm = _clone_agent_dm(agent, logger)

    assert user_dm is not None
    cloned = user_dm._datasets["rows"]
    assert cloned.source is not entry.source
    pd.testing.assert_frame_equal(cloned.df, entry.df)


def test_clone_agent_dm_skips_uncopyable_source(
    logger: logging.Logger, caplog: pytest.LogCaptureFixture
) -> None:
    """A source that cannot be copied is skipped and logged, never shared."""

    class _Uncopyable(TableSource):
        def __copy__(self):  # noqa: ANN204 - test double
            raise RuntimeError("cannot copy this source")

    entry = DatasetEntry(name="bad", source=_Uncopyable(table="sales.orders", driver="pg"))
    agent = _agent_with(entry)

    with caplog.at_level(logging.WARNING, logger="test_datasets_clone"):
        user_dm = _clone_agent_dm(agent, logger)

    # The entry is absent rather than present-and-shared.
    assert user_dm is None or "bad" not in user_dm._datasets
    assert "Failed to clone dataset" in caplog.text

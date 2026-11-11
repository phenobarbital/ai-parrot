"""Session isolation of self-governed dataset entries (FEAT-880, M3)."""

from __future__ import annotations

import pandas as pd
import pytest

from parrot.handlers.user_objects import UserObjectsHandler
from parrot.tools.dataset_manager import DatasetEntry, DatasetManager
from parrot.tools.dataset_manager.sources.base import DataSource


class _GovSource(DataSource):
    """Self-governed double with a stable owner id."""

    def __init__(self, owner: str = "owner-a") -> None:
        self._owner = owner

    @property
    def self_governed(self) -> bool:
        return True

    def current_owner(self) -> str | None:
        return self._owner

    async def fetch(self, **params) -> pd.DataFrame:
        return pd.DataFrame({"v": [1]})

    async def prefetch_schema(self):
        return {"v": "int64"}

    def describe(self) -> str:
        return "gov"

    def cache_key(self) -> str:
        return "gov"


class _Agent:
    name = "agent"

    def __init__(self) -> None:
        self.entry = DatasetEntry(
            name="gov",
            description="governed",
            source=_GovSource(),
            metadata={"k": "v"},
            usage_guidance={"do": ["x"]},
            cache_ttl=42,
            protected=True,
        )
        self.plain = DatasetEntry(name="plain", df=pd.DataFrame({"a": [1]}))
        self._dataset_manager = DatasetManager()
        self._dataset_manager._datasets["gov"] = self.entry
        self._dataset_manager._datasets["plain"] = self.plain


@pytest.mark.asyncio
async def test_configure_dataset_manager_isolates_self_governed_entries() -> None:
    agent = _Agent()
    agent.entry._df = pd.DataFrame({"v": [9]})  # simulates rows fetched for another subject
    h = UserObjectsHandler()
    a, b = await h.configure_dataset_manager({}, agent), await h.configure_dataset_manager({}, agent)

    ea, eb = a._datasets["gov"], b._datasets["gov"]
    assert ea is not eb and ea is not agent.entry
    assert ea.source is not agent.entry.source
    assert ea._df is None and eb._df is None
    assert not ea.loaded
    assert ea.description == "governed" and ea.cache_ttl == 42 and ea.protected
    ea.metadata["k"] = "changed"
    ea.usage_guidance["do"].append("y")
    assert eb.metadata["k"] == "v" and eb.usage_guidance["do"] == ["x"]
    assert agent.entry.metadata["k"] == "v"
    # ordinary entries keep sharing
    assert a._datasets["plain"] is agent.plain


@pytest.mark.asyncio
async def test_configure_dataset_manager_preserves_existing_session() -> None:
    agent = _Agent()
    h = UserObjectsHandler()
    session: dict = {}
    first = await h.configure_dataset_manager(session, agent)
    assert await h.configure_dataset_manager(session, agent) is first


@pytest.mark.asyncio
async def test_chat_session_governed_dataset_isolation() -> None:
    agent = _Agent()
    h = UserObjectsHandler()
    a = await h.configure_dataset_manager({}, agent)
    b = await h.configure_dataset_manager({}, agent)
    a._datasets["gov"]._df = pd.DataFrame({"v": ["A-rows"]})

    assert b._datasets["gov"]._df is None
    assert not b._datasets["gov"].loaded
    assert agent.entry._df is None
    # B's fetch/eviction does not alter A.
    b._datasets["gov"]._df = pd.DataFrame({"v": ["B-rows"]})
    b._datasets["gov"]._df = None
    assert a._datasets["gov"]._df["v"].tolist() == ["A-rows"]

"""FEAT-880: DatasetManager support for self-governed data sources."""
from __future__ import annotations

import pandas as pd
import pytest

from parrot.tools.dataset_manager.sources.base import DataSource
from parrot.tools.dataset_manager.sources import (
    CompositeDataSource,
    InMemorySource,
    QuerySlugSource,
    SQLQuerySource,
    TableSource,
)


class _GovernedSource(DataSource):
    """Minimal self-governed source: records fetch params, one frame per call."""

    def __init__(self, owner: str | None = "subject-a") -> None:
        super().__init__()
        self.name = "governed"
        self.owner = owner
        self.calls: list[dict] = []

    @property
    def self_governed(self) -> bool:
        return True

    @property
    def has_builtin_cache(self) -> bool:
        return True

    @property
    def cache_key(self) -> str:
        return "governed:test"

    def current_owner(self) -> str | None:
        return self.owner

    def describe(self) -> str:
        return "governed test source"

    async def fetch(self, **params) -> pd.DataFrame:
        self.calls.append(dict(params))
        return pd.DataFrame({"n": [len(self.calls)]})


_EXISTING_SOURCE_CLASSES = [
    InMemorySource,
    QuerySlugSource,
    SQLQuerySource,
    TableSource,
    CompositeDataSource,
]


def test_datasource_self_governed_default_false() -> None:
    """Every existing source reports self_governed == False."""
    source = InMemorySource(df=pd.DataFrame({"a": [1]}), name="mem")
    assert source.self_governed is False
    # Class-level check: no existing source overrides the base default, so every
    # instance inherits False without needing network access or credentials.
    for cls in _EXISTING_SOURCE_CLASSES:
        assert cls.self_governed is DataSource.self_governed, cls.__name__


@pytest.mark.parametrize("cls", _EXISTING_SOURCE_CLASSES, ids=lambda c: c.__name__)
def test_existing_sources_inherit_base_hooks(cls: type[DataSource]) -> None:
    """No existing source overrides either hook."""
    assert cls.self_governed is DataSource.self_governed
    assert cls.current_owner is DataSource.current_owner


def test_datasource_current_owner_default_none() -> None:
    """Every existing source returns None from current_owner()."""
    assert InMemorySource(df=pd.DataFrame({"a": [1]}), name="mem").current_owner() is None


def test_governed_double_contract() -> None:
    """The shared double declares both hooks."""
    source = _GovernedSource()
    assert source.self_governed is True
    assert source.current_owner() == "subject-a"

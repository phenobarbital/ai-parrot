"""Unit tests for parrot.stores.parents.factory.

Tests cover:
- Empty config returns None.
- Valid ``in_table`` config returns an ``InTableParentSearcher``.
- ``in_table`` with ``store=None`` raises ``ConfigError``.
- Missing ``type`` key raises ``ConfigError``.
- Unknown ``type`` value raises ``ConfigError``.
- Empty config short-circuits without consulting the registry (store=None ok).
"""

from __future__ import annotations

import pytest

from parrot.exceptions import ConfigError
from parrot.stores.parents.factory import create_parent_searcher


class FakeStore:
    """Stand-in for AbstractStore — minimal shape, no DB."""

    pass


@pytest.fixture()
def fake_store() -> FakeStore:
    """Provide a minimal stub store for factory tests."""
    return FakeStore()


def test_empty_config_returns_none(fake_store: FakeStore) -> None:
    """An empty config dict must return None (no parent searcher)."""
    assert create_parent_searcher({}, store=fake_store) is None


def test_empty_config_short_circuits_store_check() -> None:
    """Empty config must return None even when store=None (guard precedes registry)."""
    assert create_parent_searcher({}, store=None) is None


def test_in_table_returns_instance(fake_store: FakeStore) -> None:
    """in_table config must return an InTableParentSearcher with .store set."""
    s = create_parent_searcher({"type": "in_table"}, store=fake_store)
    from parrot.stores.parents.in_table import InTableParentSearcher

    assert isinstance(s, InTableParentSearcher)
    assert s.store is fake_store


def test_in_table_with_expand_to_parent_returns_instance(fake_store: FakeStore) -> None:
    """expand_to_parent key in config is ignored by the factory (consumed by manager)."""
    s = create_parent_searcher(
        {"type": "in_table", "expand_to_parent": True}, store=fake_store
    )
    from parrot.stores.parents.in_table import InTableParentSearcher

    assert isinstance(s, InTableParentSearcher)


def test_in_table_requires_store() -> None:
    """in_table with store=None must raise ConfigError matching 'requires store'."""
    with pytest.raises(ConfigError, match="requires store"):
        create_parent_searcher({"type": "in_table"}, store=None)


def test_missing_type_raises(fake_store: FakeStore) -> None:
    """Config without 'type' key must raise ConfigError matching 'missing type'."""
    with pytest.raises(ConfigError, match="missing 'type'"):
        create_parent_searcher({"expand_to_parent": True}, store=fake_store)


def test_unknown_type_raises(fake_store: FakeStore) -> None:
    """Unknown type must raise ConfigError matching 'unknown parent searcher type'."""
    with pytest.raises(ConfigError, match="unknown parent searcher type"):
        create_parent_searcher({"type": "magic"}, store=fake_store)


def test_config_dict_not_mutated(fake_store: FakeStore) -> None:
    """create_parent_searcher must not mutate the caller's config dict."""
    original = {"type": "in_table"}
    _ = create_parent_searcher(original, store=fake_store)
    assert original == {"type": "in_table"}

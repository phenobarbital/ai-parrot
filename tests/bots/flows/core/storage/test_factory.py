"""Unit tests for get_result_storage factory."""
import pytest
from unittest.mock import patch

from parrot.bots.flows.core.storage.backends import (
    ResultStorage,
    get_result_storage,
)


class _Fake(ResultStorage):
    """Minimal concrete subclass for testing."""

    async def save(self, collection: str, document: dict) -> None:
        pass

    async def close(self) -> None:
        pass


def test_factory_passes_instance_through():
    """An existing ResultStorage instance is returned as-is."""
    f = _Fake()
    assert get_result_storage(f) is f


def test_factory_unknown_name_raises():
    """An unrecognised backend name raises ValueError."""
    with pytest.raises(ValueError, match="Unknown ResultStorage backend"):
        get_result_storage("snowflake")


def test_factory_uses_env_var(monkeypatch):
    """When name_or_instance is None, the CREW_RESULT_STORAGE env var is consulted."""
    monkeypatch.setattr(
        "parrot.bots.flows.core.storage.backends.factory.CREW_RESULT_STORAGE",
        "redis",
    )
    with patch(
        "parrot.bots.flows.core.storage.backends.factory._import_class"
    ) as imp:
        imp.return_value = _Fake
        instance = get_result_storage(None)
        imp.assert_called_once()
    assert isinstance(instance, _Fake)


def test_factory_defaults_to_documentdb(monkeypatch):
    """When name_or_instance=None and no env var, falls back to 'documentdb'."""
    monkeypatch.setattr(
        "parrot.bots.flows.core.storage.backends.factory.CREW_RESULT_STORAGE",
        "",
    )
    with patch(
        "parrot.bots.flows.core.storage.backends.factory._import_class"
    ) as imp:
        imp.return_value = _Fake
        get_result_storage(None)
        called_path = imp.call_args.args[0]
        assert "documentdb" in called_path


def test_factory_resolves_string_name(monkeypatch):
    """Explicit string name is resolved to the correct backend class."""
    with patch(
        "parrot.bots.flows.core.storage.backends.factory._import_class"
    ) as imp:
        imp.return_value = _Fake
        instance = get_result_storage("redis")
        called_path = imp.call_args.args[0]
        assert "redis" in called_path
    assert isinstance(instance, _Fake)

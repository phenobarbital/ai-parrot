"""DocumentDb forwards a bounded connect timeout to the asyncdb driver."""
from typing import Any, Optional

import pytest

from parrot.interfaces import documentdb as documentdb_module
from parrot.interfaces.documentdb import DocumentDb


def _patch_timeout(monkeypatch: pytest.MonkeyPatch, value: Optional[int]) -> None:
    """Make ``config.getint('DOCUMENTDB_TIMEOUT', ...)`` return ``value`` (or its fallback)."""
    original = documentdb_module.config.getint

    def fake_getint(key: str, *args: Any, **kwargs: Any) -> Any:
        if key == "DOCUMENTDB_TIMEOUT":
            return kwargs.get("fallback") if value is None else value
        return original(key, *args, **kwargs)

    monkeypatch.setattr(documentdb_module.config, "getint", fake_getint)


def test_default_timeout_is_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    """Without DOCUMENTDB_TIMEOUT the driver gets 30s, not asyncdb's 600s."""
    _patch_timeout(monkeypatch, None)
    driver = DocumentDb()._get_connection()
    assert driver._timeout == 30


def test_timeout_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    """DOCUMENTDB_TIMEOUT overrides the default."""
    _patch_timeout(monkeypatch, 7)
    driver = DocumentDb()._get_connection()
    assert driver._timeout == 7

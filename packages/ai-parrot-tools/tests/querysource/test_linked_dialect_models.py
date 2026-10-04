"""FEAT-598 TASK-3782 — model additions, variable rejection, and lazy QuerySource accessors."""

from __future__ import annotations

from types import ModuleType

import pytest

from parrot_tools.querysource import _qs
from parrot_tools.querysource.dialect import reject_variable_values
from parrot_tools.querysource.errors import InvalidConditionsError
from parrot_tools.querysource.models import PlaceholderInfo, SlugDetail


def test_placeholder_info_defaults_backward_compatible() -> None:
    """New describe metadata defaults without changing existing construction."""
    info = PlaceholderInfo(name="firstdate", type="date")
    assert info.required is False and info.accepts_keywords is False


def test_slug_detail_variables_supported_default() -> None:
    """Slug details preserve variable support unless the describe path says otherwise."""
    detail = SlugDetail(
        slug="sales",
        program_slug="retail",
        provider="postgres",
        is_multiquery=False,
        is_cached=False,
        cache_timeout=0,
    )
    assert detail.variables_supported is True


def test_reject_variable_values() -> None:
    """A top-level deployment variable is rejected."""
    with pytest.raises(InvalidConditionsError, match="firstdate"):
        reject_variable_values({"firstdate": "@today"})


def test_reject_variable_values_nested_filter() -> None:
    """Nested filter and IN-list deployment variables are reported together."""
    with pytest.raises(InvalidConditionsError) as exc_info:
        reject_variable_values({"filter": {"opened": [">=", "@x"], "store": [1, "@store"]}})

    message = str(exc_info.value)
    assert "filter.opened[1]" in message
    assert "filter.store[1]" in message


def test_reject_variable_values_accepts_keywords_and_literals() -> None:
    """Closed UDF keywords and literal values remain valid."""
    reject_variable_values({"firstdate": "YESTERDAY", "lastdate": "TODAY", "store": [1, 2], "filter": {"a": "x"}})


def test_qs_accessors_are_lazy(monkeypatch: pytest.MonkeyPatch) -> None:
    """Module accessors delegate their imports through the lazy loading seam."""
    paths: list[str] = []

    def fake_load(module_path: str) -> ModuleType:
        paths.append(module_path)
        return ModuleType(module_path)

    monkeypatch.setattr(_qs, "_load", fake_load)

    assert _qs.get_describe().__name__ == "querysource.queries.describe"
    assert _qs.get_tenants().__name__ == "querysource.tenants"
    assert paths == ["querysource.queries.describe", "querysource.tenants"]


@pytest.mark.asyncio
async def test_get_definition_repository_uses_lazy_connection(monkeypatch: pytest.MonkeyPatch) -> None:
    """The repository accessor awaits the connection-owned QuerySource method."""
    expected = object()
    paths: list[str] = []

    class FakeConnection:
        """Minimal connection replacement for the lazy accessor seam."""

        async def get_definition_repository(self) -> object:
            return expected

    def fake_load(module_path: str) -> ModuleType:
        paths.append(module_path)
        module = ModuleType(module_path)
        module.Connection = FakeConnection
        return module

    monkeypatch.setattr(_qs, "_load", fake_load)

    assert await _qs.get_definition_repository() is expected
    assert paths == ["querysource.interfaces.connections"]

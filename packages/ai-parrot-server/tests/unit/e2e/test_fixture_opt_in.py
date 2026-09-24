"""Unit coverage for the suite-local FEAT-581 E2E opt-in hook."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


class _E2EItem:
    """Minimal pytest-item collaborator exposing the marker queried by the hook."""

    def get_closest_marker(self, name: str) -> object | None:
        """Return a truthy marker only for the existing ``e2e`` marker.

        Args:
            name: Marker pytest asks this item to resolve.

        Returns:
            A marker sentinel for ``e2e`` and ``None`` otherwise.
        """
        return object() if name == "e2e" else None


def _suite_conftest():
    """Load the E2E suite conftest without relying on a package import.

    Returns:
        The loaded suite conftest module.
    """
    path = Path(__file__).resolve().parents[2] / "e2e" / "conftest.py"
    spec = importlib.util.spec_from_file_location("feat_581_e2e_conftest", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_e2e_opt_in_skips_before_fixture_setup(monkeypatch: pytest.MonkeyPatch) -> None:
    """An absent opt-in makes the suite hook skip before any fixture can spawn."""
    module = _suite_conftest()
    monkeypatch.delenv("PARROT_TEST_E2E", raising=False)

    with pytest.raises(pytest.skip.Exception):
        module.pytest_runtest_setup(_E2EItem())


def test_e2e_opt_in_allows_fixture_setup(monkeypatch: pytest.MonkeyPatch) -> None:
    """The exact explicit value ``1`` permits normal fixture setup."""
    module = _suite_conftest()
    monkeypatch.setenv("PARROT_TEST_E2E", "1")

    module.pytest_runtest_setup(_E2EItem())

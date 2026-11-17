"""Regression tests for client cost computation without observability bootstrap."""

from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock

import pytest

from parrot.clients import base as client_base
from parrot.observability.cost import get_shared_cost_calculator, set_shared_cost_calculator


@pytest.fixture(autouse=True)
def restore_shared_calculator() -> Any:
    """Restore the process-wide calculator after each test."""
    previous = get_shared_cost_calculator()
    set_shared_cost_calculator(None)
    yield
    set_shared_cost_calculator(previous)


def _client() -> SimpleNamespace:
    """Return the minimum client-shaped object needed by the cost helper."""
    return SimpleNamespace(logger=Mock())


def test_compute_call_cost_builds_calculator_without_bootstrap() -> None:
    """Bundled pricing is used when no observability bootstrap installed a calculator."""
    cost = client_base.AbstractClient._compute_call_cost(
        _client(),
        "google",
        "gemini-3-flash-preview",
        100,
        50,
    )

    assert isinstance(cost, float)
    assert cost > 0


def test_compute_call_cost_returns_none_when_calculator_creation_fails(monkeypatch: Any) -> None:
    """Calculator construction failures remain isolated from the client call path."""

    def raise_on_build() -> Any:
        raise RuntimeError("pricing unavailable")

    monkeypatch.setattr(client_base, "ensure_shared_cost_calculator", raise_on_build)

    assert (
        client_base.AbstractClient._compute_call_cost(
            _client(),
            "google",
            "gemini-3-flash-preview",
            100,
            50,
        )
        is None
    )


def test_compute_call_cost_reuses_installed_calculator(monkeypatch: Any) -> None:
    """An already-installed calculator is used without invoking the lazy builder."""
    calculator = Mock()
    calculator.cost_usd.return_value = 0.25
    set_shared_cost_calculator(calculator)
    builder = Mock(side_effect=AssertionError("unexpected calculator construction"))
    monkeypatch.setattr(client_base, "ensure_shared_cost_calculator", builder)

    cost = client_base.AbstractClient._compute_call_cost(
        _client(),
        "google",
        "gemini-3-flash-preview",
        100,
        50,
    )

    assert cost == 0.25
    builder.assert_not_called()
    calculator.cost_usd.assert_called_once()

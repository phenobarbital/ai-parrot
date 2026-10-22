"""FEAT-710 TASK-4547 — shared CostCalculator + resolve_event_cost."""

from __future__ import annotations

from typing import Any

from parrot.core.events.lifecycle.events import AfterClientCallEvent
from parrot.observability.cost import (
    ensure_shared_cost_calculator,
    get_shared_cost_calculator,
    resolve_event_cost,
    set_shared_cost_calculator,
)


def test_event_cost_wins_without_recompute() -> None:
    """An origin-computed cost must bypass every calculator."""

    class _Spy:
        calls = 0

        def cost_usd(self, **_: Any) -> float:
            _Spy.calls += 1
            return 9.9

    set_shared_cost_calculator(_Spy())
    try:
        assert resolve_event_cost(AfterClientCallEvent(trace_context=None, cost_usd=0.5), None) == 0.5
        assert _Spy.calls == 0
    finally:
        set_shared_cost_calculator(None)


def test_missing_cost_uses_shared_then_fallback() -> None:
    """A missing origin cost uses shared then fallback calculators and never raises."""

    class _Calculator:
        def __init__(self, value: float) -> None:
            self.value = value

        def cost_usd(self, **_: Any) -> float:
            return self.value

    class _RaisingCalculator:
        def cost_usd(self, **_: Any) -> float:
            raise RuntimeError("pricing unavailable")

    event = AfterClientCallEvent(
        trace_context=None,
        client_name="OpenAIClient",
        model="gpt-4o-mini",
        input_tokens=100,
        output_tokens=50,
    )
    shared = _Calculator(0.25)
    fallback = _Calculator(0.75)

    set_shared_cost_calculator(shared)
    try:
        assert resolve_event_cost(event, fallback) == 0.25
    finally:
        set_shared_cost_calculator(None)

    assert resolve_event_cost(event, fallback) == 0.75
    assert resolve_event_cost(event, _RaisingCalculator()) is None


def test_holder_roundtrip() -> None:
    """The holder returns the exact installed calculator instance."""
    calculator = object()
    set_shared_cost_calculator(calculator)
    try:
        assert get_shared_cost_calculator() is calculator
    finally:
        set_shared_cost_calculator(None)
    assert get_shared_cost_calculator() is None


def test_ensure_shared_cost_calculator_honors_pricing_path(monkeypatch: Any) -> None:
    """Lazy construction forwards PARROT_PRICING_PATH from navconfig once."""
    import navconfig
    from parrot.observability.cost import calculator as calculator_module

    created: list[str | None] = []

    class _Calculator:
        def __init__(self, *, override_path: str | None = None) -> None:
            created.append(override_path)

    monkeypatch.setattr(
        navconfig.config, "get", lambda key, fallback=None: "/tmp/pricing" if key == "PARROT_PRICING_PATH" else fallback
    )
    monkeypatch.setattr(calculator_module, "CostCalculator", _Calculator)
    set_shared_cost_calculator(None)
    try:
        first = ensure_shared_cost_calculator()
        second = ensure_shared_cost_calculator()
        assert first is second
        assert created == ["/tmp/pricing"]
    finally:
        set_shared_cost_calculator(None)

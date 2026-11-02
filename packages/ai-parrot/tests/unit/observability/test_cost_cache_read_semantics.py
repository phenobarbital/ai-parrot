"""Cache-read tokens must not be subtracted twice for providers whose input excludes them (issue:19673bf4da06)."""

from __future__ import annotations

import pytest

from parrot.core.events.lifecycle import TraceContext
from parrot.core.events.lifecycle.events.client import AfterClientCallEvent
from parrot.observability.cost import resolve_event_cost
from parrot.observability.cost.calculator import CostCalculator, _select_entry


def _event(client_name: str, model: str, input_tokens: int, cache_read: int) -> AfterClientCallEvent:
    return AfterClientCallEvent(
        trace_context=TraceContext.new_root(),
        client_name=client_name,
        model=model,
        duration_ms=1.0,
        input_tokens=input_tokens,
        output_tokens=0,
        cache_read_tokens=cache_read,
    )


def _price(calc: CostCalculator, provider: str, model: str) -> dict:
    return _select_entry(calc._pricing[provider][model], None)


def test_anthropic_cache_reads_larger_than_input_are_priced_additively() -> None:
    """Claude input excludes cache reads, so input and cache reads are both billed in full."""
    calc = CostCalculator()
    model = next(iter(calc._pricing["anthropic"]))
    price = _price(calc, "anthropic", model)

    cost = resolve_event_cost(_event("claude-code", model, input_tokens=100, cache_read=10_000), calc)

    expected = (100 * price["input_per_1m"] + 10_000 * price.get("cached_input_per_1m", price["input_per_1m"])) / 1e6
    assert cost == pytest.approx(round(expected, 6))
    assert cost > 0


def test_openai_cache_reads_stay_included_in_input() -> None:
    """OpenAI/Codex input already includes cached tokens, so the cached part is subtracted from it."""
    calc = CostCalculator()
    model = next(iter(calc._pricing["openai"]))
    price = _price(calc, "openai", model)

    cost = resolve_event_cost(_event("openai", model, input_tokens=1_000, cache_read=400), calc)

    cached_per_1m = price.get("cached_input_per_1m", price["input_per_1m"])
    expected = (600 * price["input_per_1m"] + 400 * cached_per_1m) / 1e6
    assert cost == pytest.approx(round(expected, 6))

"""FEAT-783 TASK-4987 — cache-creation tier, dated pricing, and revisions."""

from datetime import date
from pathlib import Path

import pytest

from parrot.observability.cost.calculator import CostCalculator, _reset_pricing_cache_for_tests

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "pricing_revisions"


@pytest.fixture(autouse=True)
def _fresh_cache() -> None:
    """Isolate module-level pricing state for every revisioning assertion."""
    _reset_pricing_cache_for_tests()
    yield
    _reset_pricing_cache_for_tests()


def test_cache_creation_tier_is_additive() -> None:
    """Cache creation is charged in addition to regular input tokens."""
    calculator = CostCalculator(override_path=str(FIXTURES / "rev_a"))

    base = calculator.cost_usd(
        provider="anthropic",
        model="claude-revision-test",
        input_tokens=1_000,
        output_tokens=0,
    )
    priced = calculator.cost_usd(
        provider="anthropic",
        model="claude-revision-test",
        input_tokens=1_000,
        output_tokens=0,
        cache_creation_tokens=500,
    )

    assert base == pytest.approx(0.002)
    assert priced == pytest.approx(0.003)


def test_valid_from_selects_window() -> None:
    """Dated entries select the latest pricing window at or before the date."""
    calculator = CostCalculator(override_path=str(FIXTURES / "rev_b"))

    early = calculator.cost_usd(
        provider="anthropic",
        model="claude-revision-test",
        input_tokens=1_000,
        output_tokens=0,
        at=date(2026, 5, 31),
    )
    late = calculator.cost_usd(
        provider="anthropic",
        model="claude-revision-test",
        input_tokens=1_000,
        output_tokens=0,
        at=date(2026, 6, 1),
    )

    assert early == pytest.approx(0.003)
    assert late == pytest.approx(0.007)


def test_revision_changes_with_file_content() -> None:
    """A different provider file content yields a different pricing revision."""
    revision_a = (
        CostCalculator(override_path=str(FIXTURES / "rev_a"))
        .price_call(
            provider="anthropic",
            model="claude-revision-test",
            input_tokens=1,
            output_tokens=1,
        )
        .price_revision
    )
    _reset_pricing_cache_for_tests()
    revision_b = (
        CostCalculator(override_path=str(FIXTURES / "rev_b"))
        .price_call(
            provider="anthropic",
            model="claude-revision-test",
            input_tokens=1,
            output_tokens=1,
        )
        .price_revision
    )

    assert revision_a is not None
    assert revision_b is not None
    assert revision_a != revision_b


def test_unpriced_pair_still_none() -> None:
    """An unknown provider/model pair remains explicitly unpriced."""
    calculator = CostCalculator(override_path=str(FIXTURES / "rev_a"))

    result = calculator.price_call(
        provider="anthropic",
        model="not-priced",
        input_tokens=1,
        output_tokens=1,
    )

    assert result.priced is False
    assert (
        calculator.cost_usd(
            provider="anthropic",
            model="not-priced",
            input_tokens=1,
            output_tokens=1,
        )
        is None
    )


@pytest.mark.asyncio
async def test_priced_event_and_record_carry_revision() -> None:
    """The origin stamps revision fields and the recorder preserves them."""
    from navigator_eventbus.lifecycle.trace import TraceContext

    from parrot.clients.base import AbstractClient
    from parrot.observability.cost import set_shared_cost_calculator
    from parrot.observability.recorders.subscriber import UsageRecordingSubscriber

    class Events:
        """Capture an emitted client event."""

        def __init__(self) -> None:
            self.emitted = []

        async def emit(self, event: object) -> None:
            self.emitted.append(event)

    class Client:
        """Minimal client double exposing the cost emission helpers."""

        _emit_after_call = AbstractClient._emit_after_call
        _compute_call_cost = AbstractClient._compute_call_cost
        _price_revision_fields = AbstractClient._price_revision_fields

        def __init__(self) -> None:
            import logging

            self.events = Events()
            self.logger = logging.getLogger("test")

        async def _forward_to_global_awaited(self, event: object) -> None:
            return None

    class Recorder:
        """Capture a usage record."""

        name = "capture"

        def __init__(self) -> None:
            self.records = []

        async def record(self, record: object) -> None:
            self.records.append(record)

        async def aclose(self) -> None:
            return None

    calculator = CostCalculator(override_path=str(FIXTURES / "rev_b"))
    recorder = Recorder()
    client = Client()
    set_shared_cost_calculator(calculator)
    try:
        await client._emit_after_call(
            TraceContext.new_root(),
            client_name="anthropic",
            model="claude-revision-test",
            duration_ms=1.0,
            input_tokens=1,
            output_tokens=1,
        )
        event = client.events.emitted[0]
        await UsageRecordingSubscriber(recorders=[recorder], cost_calculator=calculator)._on_client_after(event)
    finally:
        set_shared_cost_calculator(None)

    assert event.price_revision is not None
    assert event.price_valid_from == "2026-06-01"
    assert recorder.records[0].price_revision == event.price_revision
    assert recorder.records[0].price_valid_from == event.price_valid_from

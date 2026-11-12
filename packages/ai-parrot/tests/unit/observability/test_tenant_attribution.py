"""Unit tests for tenant attribution on OpenTelemetry signals."""

from __future__ import annotations

import asyncio
from typing import Any, Callable

import pytest
from navigator_eventbus.lifecycle.trace import TraceContext

from parrot.clients.base import AbstractClient
from parrot.core.events.lifecycle.events import (
    AfterClientCallEvent,
    AfterInvokeEvent,
    AfterToolCallEvent,
    BeforeClientCallEvent,
    BeforeInvokeEvent,
    ClientCallFailedEvent,
    ClientRoundEvent,
    InvokeFailedEvent,
    ToolCallFailedEvent,
)
from parrot.observability.attributes import (
    TENANT_ATTR,
    build_after_client_attrs,
    build_after_invoke_attrs,
    build_before_client_attrs,
    build_before_invoke_attrs,
    build_client_failed_attrs,
    build_invoke_failed_attrs,
)
from parrot.observability.context import current_tenant
from parrot.observability.subscribers.metrics import MetricsSubscriber


class _Instrument:
    """Capture metric attributes without exporting a data point."""

    def __init__(self) -> None:
        self.attributes: list[dict[str, object]] = []

    def add(self, value: object, *, attributes: dict[str, object]) -> None:
        """Capture counter attributes."""
        self.attributes.append(attributes)

    def record(self, value: object, *, attributes: dict[str, object]) -> None:
        """Capture histogram attributes."""
        self.attributes.append(attributes)


def _make_stub_client() -> AbstractClient:
    """Return a concrete client that exposes lifecycle emit helpers."""

    class _StubClient(AbstractClient):
        """No-I/O client used to inspect emitted lifecycle events."""

        client_name = "stub"

        def __init__(self) -> None:
            super().__init__(debug=False)

        async def ask(self, prompt: str, model: str = "stub-model", **kwargs: object) -> object:
            raise NotImplementedError

        async def ask_stream(self, prompt: str, **kwargs: object) -> Any:
            raise NotImplementedError
            yield

        async def get_client(self) -> None:
            return None

        async def _ensure_client(self) -> None:
            return None

        async def invoke(self, *args: object, **kwargs: object) -> object:
            raise NotImplementedError

        async def resume(self, *args: object, **kwargs: object) -> object:
            raise NotImplementedError

    return _StubClient()


def _events(tenant: str | None = "acme") -> list[object]:
    """Build representative lifecycle events carrying a tenant value."""
    trace_context = TraceContext.new_root()
    return [
        BeforeClientCallEvent(trace_context=trace_context, client_name="openai", model="gpt-4o", tenant=tenant),
        AfterClientCallEvent(
            trace_context=trace_context, client_name="openai", model="gpt-4o", duration_ms=1.0, tenant=tenant
        ),
        ClientCallFailedEvent(
            trace_context=trace_context,
            client_name="openai",
            model="gpt-4o",
            error_type="TimeoutError",
            error_message="timed out",
            tenant=tenant,
        ),
        ClientRoundEvent(trace_context=trace_context, client_name="openai", model="gpt-4o", tenant=tenant),
        AfterInvokeEvent(trace_context=trace_context, agent_name="bot", method="ask", duration_ms=1.0, tenant=tenant),
        InvokeFailedEvent(
            trace_context=trace_context,
            agent_name="bot",
            method="ask",
            error_type="TimeoutError",
            error_message="timed out",
            tenant=tenant,
        ),
    ]


@pytest.mark.asyncio
async def test_before_and_round_events_capture_bound_tenant() -> None:
    """Client events snapshot a bound tenant before asynchronous dispatch."""
    client = _make_stub_client()
    captured: list[object] = []

    async def capture(event: object) -> None:
        """Store a delivered event."""
        captured.append(event)

    client.events.subscribe(BeforeClientCallEvent, capture)
    client.events.subscribe(ClientRoundEvent, capture)
    token = current_tenant.set("acme")
    try:
        trace_context = client._emit_before_call(client_name="stub", model="stub-model")
        client._emit_round_event(
            trace_context,
            client_name="stub",
            model="stub-model",
            round_number=1,
            usage=None,
            raw_usage=None,
            tool_calls=(),
            duration_ms=1.0,
        )
        await asyncio.sleep(0)
    finally:
        current_tenant.reset(token)

    assert [event.tenant for event in captured] == ["acme", "acme"]


@pytest.mark.asyncio
async def test_before_and_round_events_tenant_none_when_unbound() -> None:
    """Client events preserve the unbound tenant value as None."""
    client = _make_stub_client()
    captured: list[object] = []

    async def capture(event: object) -> None:
        """Store a delivered event."""
        captured.append(event)

    client.events.subscribe(BeforeClientCallEvent, capture)
    client.events.subscribe(ClientRoundEvent, capture)
    trace_context = client._emit_before_call(client_name="stub", model="stub-model")
    client._emit_round_event(
        trace_context,
        client_name="stub",
        model="stub-model",
        round_number=1,
        usage=None,
        raw_usage=None,
        tool_calls=(),
        duration_ms=1.0,
    )
    await asyncio.sleep(0)

    assert [event.tenant for event in captured] == [None, None]


@pytest.mark.parametrize(
    ("builder", "index"),
    [
        (build_before_client_attrs, 0),
        (build_after_client_attrs, 1),
        (build_client_failed_attrs, 2),
        (build_after_invoke_attrs, 4),
        (build_invoke_failed_attrs, 5),
    ],
)
def test_span_builders_set_tenant_or_unknown(builder: Callable[[Any], dict[str, Any]], index: int) -> None:
    """Every tenant-aware span builder emits a concrete tenant label."""
    assert builder(_events("acme")[index])[TENANT_ATTR] == "acme"
    assert builder(_events(None)[index])[TENANT_ATTR] == "unknown"


def test_before_invoke_attrs_have_no_tenant_key() -> None:
    """BeforeInvokeEvent remains outside tenant attribution scope."""
    attrs = build_before_invoke_attrs(
        BeforeInvokeEvent(trace_context=TraceContext.new_root(), agent_name="bot", method="ask")
    )
    assert TENANT_ATTR not in attrs


@pytest.mark.asyncio
async def test_client_metrics_carry_tenant_label() -> None:
    """All client metric handlers label their LLM telemetry by tenant."""
    subscriber = MetricsSubscriber()
    request, duration, tokens, rounds, round_tokens, errors = (_Instrument() for _ in range(6))
    subscriber._client_request_count = request
    subscriber._client_op_duration = duration
    subscriber._client_token_usage = tokens
    subscriber._client_rounds = rounds
    subscriber._client_round_token_usage = round_tokens
    subscriber._client_error_count = errors
    events = _events()
    await subscriber._on_client_before(events[0])
    await subscriber._on_client_after(events[1])
    await subscriber._on_client_round(events[3])
    await subscriber._on_client_fail(events[2])
    assert all(
        attrs[TENANT_ATTR] == "acme"
        for instrument in (request, duration, tokens, rounds, round_tokens, errors)
        for attrs in instrument.attributes
    )


@pytest.mark.asyncio
async def test_invoke_metrics_carry_tenant_label() -> None:
    """Invoke duration and failure metrics label their telemetry by tenant."""
    subscriber = MetricsSubscriber()
    duration, failures = _Instrument(), _Instrument()
    subscriber._invoke_duration = duration
    subscriber._invoke_failure_count = failures
    events = _events()
    await subscriber._on_invoke_after(events[4])
    await subscriber._on_invoke_fail(events[5])
    assert [attrs[TENANT_ATTR] for attrs in duration.attributes + failures.attributes] == ["acme", "acme"]


@pytest.mark.asyncio
async def test_tool_metrics_have_no_tenant_label() -> None:
    """Tool metrics remain outside the tenant-attribution scope."""
    subscriber = MetricsSubscriber()
    duration, failures = _Instrument(), _Instrument()
    subscriber._tool_exec_duration = duration
    subscriber._tool_failure_count = failures
    trace_context = TraceContext.new_root()
    await subscriber._on_tool_after(
        AfterToolCallEvent(trace_context=trace_context, tool_name="search", duration_ms=1.0)
    )
    await subscriber._on_tool_fail(
        ToolCallFailedEvent(
            trace_context=trace_context,
            tool_name="search",
            duration_ms=1.0,
            error_type="TimeoutError",
            error_message="timed out",
        )
    )
    assert all(TENANT_ATTR not in attrs for attrs in duration.attributes + failures.attributes)

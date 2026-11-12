"""HOTFIX-otel-attribution-6 — LLM-call telemetry carries agent and tenant, end to end.

Real ``AbstractClient._emit_*`` helpers -> global lifecycle registry ->
``MetricsSubscriber`` / ``GenAIOpenTelemetrySubscriber`` -> in-memory OTel
readers. Hermetic: no network, no provider SDK.

The agents whose ``ask`` body is heavy (BaseBot, PandasAgent,
DatabaseAgent) run a stub body under the SAME ``with_call_identity`` wrapper the
class uses (the class's own ``ask`` is asserted to be that wrapper); VoiceBot's
real ``ask`` runs, with its context builders stubbed.
"""

from __future__ import annotations

import asyncio
from typing import Any, AsyncIterator, List

import pytest
from navigator_eventbus.lifecycle.global_registry import scope
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from parrot.bots.base import BaseBot, with_call_identity
from parrot.bots.data import PandasAgent
from parrot.bots.database.agent import DatabaseAgent
from parrot.bots.voice import VoiceBot
from parrot.clients.base import AbstractClient
from parrot.models.voice import LiveVoiceResponse
from parrot.observability.subscribers.metrics import MetricsSubscriber
from parrot.observability.subscribers.trace import GenAIOpenTelemetrySubscriber

_AGENT_ATTR = "parrot.agent.name"
_TENANT_ATTR = "parrot.tenant"


class _EmittingClient(AbstractClient):
    """Stub client whose ``ask`` fires the real before/after lifecycle helpers."""

    client_type = "stub"
    supported_models = ["stub"]

    def __init__(self, **kwargs: Any) -> None:
        kwargs.setdefault("model", "stub")
        super().__init__(**kwargs)

    async def get_client(self) -> "_EmittingClient":
        return self

    async def _ensure_client(self) -> "_EmittingClient":
        return self

    async def _emit_cycle(self) -> None:
        tc = self._emit_before_call(client_name="stub", model="stub")
        # The before-event is forwarded fire-and-forget while the after-event is awaited; a real
        # provider call takes long enough for the span to open first, so model that latency.
        await asyncio.sleep(0.05)
        await self._emit_after_call(
            tc, client_name="stub", model="stub", duration_ms=5.0, input_tokens=3, output_tokens=2
        )

    async def ask(self, prompt: str = "", **kwargs: Any) -> str:
        await self._emit_cycle()
        return "ok"

    async def ask_stream(self, prompt: str, **kwargs: Any):
        yield "ok"

    async def resume(self, session_id: str, user_input: str, state: Any):
        raise NotImplementedError

    async def invoke(self, prompt: str, **kwargs: Any):
        raise NotImplementedError


class _EmittingVoiceClient(_EmittingClient):
    """Voice variant: ``ask`` is an async iterator, as ``VoiceBot.ask`` expects."""

    async def ask(self, question: str = "", **kwargs: Any) -> AsyncIterator[LiveVoiceResponse]:  # type: ignore[override]
        await self._emit_cycle()
        yield LiveVoiceResponse(text="ok", is_complete=True)

    async def __aenter__(self) -> "_EmittingVoiceClient":
        return self

    async def __aexit__(self, *exc: Any) -> None:
        return None


@pytest.fixture
def otel():
    """In-memory readers with both subscribers registered on a scoped registry."""
    reader = InMemoryMetricReader()
    mp = MeterProvider(resource=Resource.create({"service.name": "parrot-test"}), metric_readers=[reader])
    exporter = InMemorySpanExporter()
    tp = TracerProvider(resource=Resource.create({"service.name": "parrot-test"}))
    tp.add_span_processor(SimpleSpanProcessor(exporter))
    with scope() as registry:
        MetricsSubscriber(meter_provider=mp, service_name="parrot-test").register(registry)
        GenAIOpenTelemetrySubscriber(service_name="parrot-test", tracer_provider=tp).register(registry)
        yield reader, exporter


def _data_points(reader: InMemoryMetricReader) -> List[Any]:
    data = reader.get_metrics_data()
    if data is None:
        return []
    return [
        dp
        for rm in data.resource_metrics
        for sm in rm.scope_metrics
        for metric in sm.metrics
        for dp in metric.data.data_points
    ]


async def _drain(reader: InMemoryMetricReader, exporter: InMemorySpanExporter) -> None:
    """Yield to the loop until the fire-and-forget dispatch produced data."""
    for _ in range(200):
        if _data_points(reader) and exporter.get_finished_spans():
            return
        await asyncio.sleep(0.01)


def _stub_body(client: _EmittingClient):
    async def body(self: Any, question: str, ctx: Any = None, **kwargs: Any) -> str:
        return await client.ask(question)

    return body


async def _run_agent(kind: str, tenant: str | None, monkeypatch: pytest.MonkeyPatch) -> str:
    client = _EmittingClient()
    kwargs = {"tenant": tenant} if tenant else {}
    if kind == "voice":
        voice = object.__new__(VoiceBot)
        voice.name = "voice-agent"
        monkeypatch.setattr(VoiceBot, "memory_key_id", "voice-agent")  # read-only property
        voice.conversation_memory = None
        voice._llm = _EmittingVoiceClient()

        async def _vector(*a: Any, **k: Any):
            return "", {}

        async def _user(*a: Any, **k: Any):
            return ""

        async def _kb(*a: Any, **k: Any):
            return "", {}

        async def _prompt(*a: Any, **k: Any):
            return "system"

        voice._build_vector_context = _vector
        voice._build_user_context = _user
        voice._build_kb_context = _kb
        voice.create_system_prompt = _prompt
        async for _ in voice.ask("hello", **kwargs):
            pass
        return voice.name

    cls = {"basic": BaseBot, "pandas": PandasAgent, "database": DatabaseAgent}[kind]
    if kind != "basic":  # BaseBot.ask binds inline, so it has no decorator to assert
        assert hasattr(cls.__dict__["ask"], "__wrapped__"), f"{cls.__name__}.ask must use with_call_identity"
    monkeypatch.setattr(cls, "ask", with_call_identity(_stub_body(client)))
    agent = object.__new__(cls)
    agent.name = f"{kind}-agent"
    await agent.ask("hello", **kwargs)
    return agent.name


@pytest.mark.asyncio
@pytest.mark.parametrize("agent_kind", ["basic", "pandas", "database", "voice"])
async def test_llm_call_metrics_and_span_carry_agent_and_tenant(agent_kind: str, otel, monkeypatch) -> None:
    reader, exporter = otel
    name = await _run_agent(agent_kind, "acme", monkeypatch)
    await _drain(reader, exporter)

    points = _data_points(reader)
    assert points, "no metric data points were recorded"
    for dp in points:
        assert dp.attributes.get(_AGENT_ATTR) == name
        assert dp.attributes.get(_TENANT_ATTR) == "acme"

    spans = exporter.get_finished_spans()
    assert spans, "no client span was exported"
    for span in spans:
        assert span.attributes.get(_AGENT_ATTR) == name
        assert span.attributes.get(_TENANT_ATTR) == "acme"


@pytest.mark.asyncio
async def test_missing_tenant_is_unknown_sentinel(otel, monkeypatch) -> None:
    reader, exporter = otel
    await _run_agent("basic", None, monkeypatch)
    await _drain(reader, exporter)

    points = _data_points(reader)
    assert points
    assert all(dp.attributes.get(_TENANT_ATTR) == "unknown" for dp in points)
    assert all(span.attributes.get(_TENANT_ATTR) == "unknown" for span in exporter.get_finished_spans())

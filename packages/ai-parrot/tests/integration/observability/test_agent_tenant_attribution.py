"""HOTFIX-otel-attribution-6 — LLM-call telemetry carries agent and tenant, end to end.

Real ``AbstractClient._emit_*`` helpers -> global lifecycle registry ->
``MetricsSubscriber`` / ``GenAIOpenTelemetrySubscriber`` -> in-memory OTel
readers. Hermetic: no network, no provider SDK.

Every agent runs its REAL ``ask`` body, so the test proves the identity each
body binds reaches the client call it makes: BaseBot (binds inline) and
PandasAgent (``with_call_identity``) with tools, history and vector context
off; DatabaseAgent (``with_call_identity``) over an in-memory toolkit; VoiceBot
with its context builders stubbed. Only the LLM client is a stub.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any, AsyncIterator, List, Optional

import pytest
from navigator_eventbus.lifecycle.global_registry import scope
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from parrot.bots.base import BaseBot
from parrot.bots.data import PandasAgent
from parrot.bots.database.agent import DatabaseAgent
from parrot.bots.database.models import QueryExecutionResponse, TableMetadata
from parrot.bots.database.toolkits.base import DatabaseToolkit
from parrot.bots.voice import VoiceBot
from parrot.clients.base import AbstractClient
from parrot.models import AIMessage
from parrot.models.responses import CompletionUsage
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

    async def ask(self, prompt: str = "", **kwargs: Any) -> AIMessage:
        await self._emit_cycle()
        return AIMessage(
            input=prompt,
            output="ok",
            response="ok",
            model="stub",
            provider="stub",
            usage=CompletionUsage(),
            turn_id=str(uuid.uuid4()),
        )

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


class _InMemoryToolkit(DatabaseToolkit):
    """DatabaseToolkit with no connection: no schema matches, every query returns no rows."""

    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None

    async def search_schema(
        self, search_term: str, schema_name: Optional[str] = None, limit: int = 10
    ) -> List[TableMetadata]:
        return []

    async def execute_query(self, query: str, limit: int = 1000, timeout: int = 30) -> QueryExecutionResponse:
        return QueryExecutionResponse(success=True, data=[], row_count=0, execution_time_ms=0.0, schema_used="public")


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


async def _run_agent(kind: str, tenant: str | None, monkeypatch: pytest.MonkeyPatch) -> str:
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

    if kind == "basic":
        bot = BaseBot(
            name="basic-agent", llm=_EmittingClient(), memory_type="memory", injection_detection=False, model="stub"
        )
        await bot.configure()
        await bot.ask("hello", use_conversation_history=False, use_tools=False, use_vector_context=False, **kwargs)
        return bot.name

    if kind == "pandas":
        agent = PandasAgent(name="pandas-agent", llm=_EmittingClient(), injection_detection=False)
        await agent.ask("hello", use_tools=False, return_structured=False, use_conversation_history=False, **kwargs)
        return agent.name

    assert kind == "database", kind
    toolkit = _InMemoryToolkit(
        dsn="postgresql://stub:stub@localhost:5432/stub",
        allowed_schemas=["public"],
        primary_schema="public",
        database_type="postgresql",
    )
    agent = DatabaseAgent(name="database-agent", toolkits=[toolkit])
    await agent.configure()
    agent._llm = _EmittingClient()  # configure() resolves its own client; swap in the stub afterwards
    await agent.ask("list tables", **kwargs)
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

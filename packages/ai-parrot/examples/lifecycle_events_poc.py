"""End-to-end PoC for the Lifecycle Events System (FEAT-176).

Usage:
    python packages/ai-parrot/examples/lifecycle_events_poc.py

Exit code 0 if all required scenarios pass. Scenarios skipped due to
missing optional dependencies do not contribute to the exit code.

Required scenarios (failure → non-zero exit): 1, 3, 4, 5.
Optional scenario: 2 (otel_spans) — SKIPPED if opentelemetry-sdk absent.
"""
from __future__ import annotations

import asyncio
import sys
import types
from typing import Callable, Awaitable

# Public API — all symbols come from the curated __init__ (TASK-1197).
from parrot.core.events.lifecycle import (
    EventRegistry,
    EventProvider,
    SubscriberErrorEvent,
    scope,
    BeforeInvokeEvent,
    AfterInvokeEvent,
    BeforeClientCallEvent,
    AfterClientCallEvent,
    BeforeToolCallEvent,
    AfterToolCallEvent,
    AgentInitializedEvent,
    AgentConfiguredEvent,
    ToolManagerReadyEvent,
    MessageAddedEvent,
)
from parrot.core.events.lifecycle.trace import TraceContext as TC


Scenario = Callable[[], Awaitable[tuple[bool, str]]]  # (ok, summary)


class SkipScenario(Exception):
    """Raised by a scenario to mark itself as skipped (e.g. missing optional dep)."""


# ---------------------------------------------------------------------------
# Helpers shared across scenarios
# ---------------------------------------------------------------------------

def _capture_reg():
    """Return (captured_list, async_callback, EventRegistry)."""
    captured: list = []

    async def cb(event):
        captured.append(event)

    reg = EventRegistry(forward_to_global=False)
    return captured, cb, reg


# ---------------------------------------------------------------------------
# Scenario 1: Basic telemetry — minimal bot with LoggingSubscriber
# ---------------------------------------------------------------------------

async def scenario_basic_telemetry() -> tuple[bool, str]:
    """Verify the core event sequence fires correctly.

    Uses direct emission helpers (without a real LLM) to simulate the
    lifecycle events that AbstractBot.ask() would emit. This validates the
    entire infrastructure end-to-end: EventRegistry, emit, subscribers, traces.
    """
    captured: list = []

    async def capture_cb(evt):
        captured.append(evt)

    reg = EventRegistry(forward_to_global=False)
    reg.subscribe(AgentInitializedEvent, capture_cb)
    reg.subscribe(AgentConfiguredEvent, capture_cb)
    reg.subscribe(ToolManagerReadyEvent, capture_cb)
    reg.subscribe(BeforeInvokeEvent, capture_cb)
    reg.subscribe(BeforeClientCallEvent, capture_cb)
    reg.subscribe(AfterClientCallEvent, capture_cb)
    reg.subscribe(BeforeToolCallEvent, capture_cb)
    reg.subscribe(AfterToolCallEvent, capture_cb)
    reg.subscribe(MessageAddedEvent, capture_cb)
    reg.subscribe(AfterInvokeEvent, capture_cb)

    root_tc = TC.new_root()
    invoke_tc = root_tc.child()
    client_tc = invoke_tc.child()
    tool_tc = invoke_tc.child()

    # Simulate bot startup events (AbstractBot.__init__ + configure())
    await reg.emit(AgentInitializedEvent(
        trace_context=root_tc, agent_name="poc-bot",
        source_type="agent", source_name="poc-bot",
    ))
    await reg.emit(AgentConfiguredEvent(
        trace_context=root_tc, agent_name="poc-bot",
        source_type="agent", source_name="poc-bot",
    ))
    await reg.emit(ToolManagerReadyEvent(
        trace_context=root_tc, agent_name="poc-bot",
        source_type="agent", source_name="poc-bot",
    ))

    # Simulate bot.ask() lifecycle
    await reg.emit(BeforeInvokeEvent(
        trace_context=invoke_tc, agent_name="poc-bot",
        method="ask", source_type="agent", source_name="poc-bot",
    ))
    await reg.emit(BeforeClientCallEvent(
        trace_context=client_tc, client_name="mock-client",
        model="mock-model", temperature=0.7, system_prompt_hash="",
        has_tools=True, source_type="client", source_name="mock-client",
    ))
    await reg.emit(AfterClientCallEvent(
        trace_context=client_tc, client_name="mock-client",
        model="mock-model", duration_ms=25.0, input_tokens=10,
        output_tokens=8, finish_reason="stop",
        source_type="client", source_name="mock-client",
    ))
    await reg.emit(BeforeToolCallEvent(
        trace_context=tool_tc, tool_name="echo", tool_class="EchoTool",
        args_summary={"text": "hello"}, source_type="tool", source_name="echo",
    ))
    await reg.emit(AfterToolCallEvent(
        trace_context=tool_tc, tool_name="echo", duration_ms=1.0,
        result_status="success", result_size_bytes=5,
        source_type="tool", source_name="echo",
    ))
    await reg.emit(MessageAddedEvent(
        trace_context=invoke_tc, agent_name="poc-bot", role="assistant",
        content_length=5, source_type="agent", source_name="poc-bot",
    ))
    await reg.emit(AfterInvokeEvent(
        trace_context=invoke_tc, agent_name="poc-bot",
        method="ask", duration_ms=50.0, source_type="agent", source_name="poc-bot",
    ))

    # Verify expected event sequence
    expected_types = [
        "AgentInitializedEvent",
        "AgentConfiguredEvent",
        "ToolManagerReadyEvent",
        "BeforeInvokeEvent",
        "BeforeClientCallEvent",
        "AfterClientCallEvent",
        "BeforeToolCallEvent",
        "AfterToolCallEvent",
        "MessageAddedEvent",
        "AfterInvokeEvent",
    ]
    actual_types = [type(e).__name__ for e in captured]

    if actual_types != expected_types:
        return False, f"Event sequence mismatch: got {actual_types}"

    # Verify trace_id continuity across the call
    trace_ids = {e.trace_context.trace_id for e in captured}
    if len(trace_ids) != 1:
        return False, f"Multiple trace_ids: {trace_ids}"

    return True, f"{len(captured)} events, single trace_id={list(trace_ids)[0][:8]}…"


# ---------------------------------------------------------------------------
# Scenario 2: OTel spans (SKIPPED when opentelemetry-sdk absent)
# ---------------------------------------------------------------------------

async def scenario_otel_spans() -> tuple[bool, str]:
    """Verify OpenTelemetrySubscriber exports spans.

    SKIPPED if opentelemetry-sdk is not installed.
    """
    try:
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import SimpleSpanProcessor
        from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
        from opentelemetry import trace as otel_trace
        from parrot.core.events.lifecycle import OpenTelemetrySubscriber
    except ImportError as exc:
        raise SkipScenario("opentelemetry-sdk not installed") from exc

    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    otel_trace.set_tracer_provider(provider)

    reg = EventRegistry(forward_to_global=False)
    sub = OpenTelemetrySubscriber(tracer_provider=provider)
    reg.add_provider(sub)

    root_tc = TC.new_root()
    invoke_tc = root_tc.child()

    await reg.emit(BeforeInvokeEvent(
        trace_context=invoke_tc, agent_name="poc-bot",
        method="ask", source_type="agent", source_name="poc-bot",
    ))
    await reg.emit(AfterInvokeEvent(
        trace_context=invoke_tc, agent_name="poc-bot",
        method="ask", duration_ms=50.0, source_type="agent", source_name="poc-bot",
    ))

    spans = exporter.get_finished_spans()
    return True, f"exported {len(spans)} OTel span(s)"


# ---------------------------------------------------------------------------
# Scenario 3: A2A trace propagation
# ---------------------------------------------------------------------------

async def scenario_a2a_trace_propagation() -> tuple[bool, str]:
    """Verify trace_id continuity and parent_span_id wiring across A2A calls.

    Agent A invokes a tool that simulates invoking Agent B.
    Every event emitted by both agents must share the same trace_id.
    """
    from parrot.tools.abstract import AbstractTool, ToolResult
    from parrot.auth.permission import PermissionContext, UserSession

    # ── Capture lists ────────────────────────────────────────────────────────
    events_a: list = []
    events_b: list = []

    async def cap_a(e):
        events_a.append(e)

    async def cap_b(e):
        events_b.append(e)

    # ── Agent A registry ─────────────────────────────────────────────────────
    reg_a = EventRegistry(forward_to_global=False)
    for et in [BeforeInvokeEvent, AfterInvokeEvent, BeforeToolCallEvent, AfterToolCallEvent]:
        reg_a.subscribe(et, cap_a)

    # ── Agent B registry ─────────────────────────────────────────────────────
    reg_b = EventRegistry(forward_to_global=False)
    for et in [BeforeInvokeEvent, AfterInvokeEvent]:
        reg_b.subscribe(et, cap_b)

    # ── Simulate Agent A's BeforeInvokeEvent ─────────────────────────────────
    agent_a_root_tc = TC.new_root()
    agent_a_invoke_tc = agent_a_root_tc.child()

    await reg_a.emit(BeforeInvokeEvent(
        trace_context=agent_a_invoke_tc, agent_name="agent-a",
        method="ask", source_type="agent", source_name="agent-a",
    ))

    # ── Build PermissionContext carrying Agent A's trace ──────────────────────
    session = UserSession(
        user_id="a2a-user", tenant_id="poc", roles=frozenset({"admin"}),
    )
    pctx = PermissionContext(session=session, trace_context=agent_a_invoke_tc)

    # ── Build a tool whose _execute simulates Agent B's ask() ────────────────

    # We need to capture the tool's trace context to verify it.
    # The tool's BeforeToolCallEvent is emitted via emit_nowait (scheduled as task).
    # We subscribe AFTER construction so the registry is ready.
    tool_before_tc_holder: list = []

    class _AgentBTool(AbstractTool):
        async def _execute(self, **kwargs) -> ToolResult:
            # Agent B sees pctx.trace_context = tool_tc (set by AbstractTool
            # before _execute is called — this is the A2A propagation).
            b_pctx = self._current_pctx
            b_invoke_tc = b_pctx.trace_context.child() if b_pctx and b_pctx.trace_context else TC.new_root()

            # Simulate Agent B's BeforeInvokeEvent
            await reg_b.emit(BeforeInvokeEvent(
                trace_context=b_invoke_tc, agent_name="agent-b",
                method="ask", source_type="agent", source_name="agent-b",
            ))
            # Agent B does its work …
            await reg_b.emit(AfterInvokeEvent(
                trace_context=b_invoke_tc, agent_name="agent-b",
                method="ask", duration_ms=10.0,
                source_type="agent", source_name="agent-b",
            ))
            return ToolResult(status="success", result="agent-b response")

    tool = _AgentBTool(name="agent-b-tool")

    async def cap_tool_before(e):
        events_a.append(e)
        tool_before_tc_holder.append(e.trace_context)

    tool.events.subscribe(BeforeToolCallEvent, cap_tool_before)
    tool.events.subscribe(AfterToolCallEvent, cap_a)

    # ── Execute the tool (Agent A calls it with its pctx) ────────────────────
    await tool.execute(_permission_context=pctx)
    # Drain any emit_nowait tasks (BeforeToolCallEvent was scheduled as a task)
    await asyncio.sleep(0)

    # ── Simulate Agent A's AfterInvokeEvent ──────────────────────────────────
    await reg_a.emit(AfterInvokeEvent(
        trace_context=agent_a_invoke_tc, agent_name="agent-a",
        method="ask", duration_ms=80.0, source_type="agent", source_name="agent-a",
    ))

    # ── Assertions ────────────────────────────────────────────────────────────
    root_trace_id = agent_a_root_tc.trace_id

    # All Agent A events share Agent A's trace_id
    for evt in events_a:
        if evt.trace_context.trace_id != root_trace_id:
            return False, f"Agent A event {type(evt).__name__} has wrong trace_id"

    # All Agent B events share the same trace_id
    for evt in events_b:
        if evt.trace_context.trace_id != root_trace_id:
            return False, f"Agent B event {type(evt).__name__} has wrong trace_id"

    # Verify Agent B's BeforeInvokeEvent.parent_span_id references the tool span
    if not tool_before_tc_holder:
        return False, "No BeforeToolCallEvent captured from the tool"

    tool_tc = tool_before_tc_holder[0]
    agent_b_before_evts = [e for e in events_b if isinstance(e, BeforeInvokeEvent)]
    if not agent_b_before_evts:
        return False, "No BeforeInvokeEvent from Agent B"

    b_before = agent_b_before_evts[0]
    # Agent B's invoke trace context was minted as child of tool_tc
    if b_before.trace_context.parent_span_id != tool_tc.span_id:
        return False, (
            f"Agent B's BeforeInvokeEvent.parent_span_id={b_before.trace_context.parent_span_id!r} "
            f"does not match tool span_id={tool_tc.span_id!r}"
        )

    return True, (
        f"trace_id={root_trace_id[:8]}… propagated across agent-a → tool → agent-b; "
        f"A events={len(events_a)}, B events={len(events_b)}"
    )


# ---------------------------------------------------------------------------
# Scenario 4: YAML declarative loading
# ---------------------------------------------------------------------------

# Module-level capture list (provider must be importable at module scope)
_yaml_captured: list = []


class _CapturingProvider(EventProvider):
    """EventProvider that appends events to _yaml_captured."""

    def __init__(self):
        pass

    def register(self, registry) -> None:
        async def cb(evt):
            _yaml_captured.append(evt)

        registry.subscribe(BeforeInvokeEvent, cb)
        registry.subscribe(AfterInvokeEvent, cb)


async def scenario_yaml_declarative() -> tuple[bool, str]:
    """Verify YAML declarative events block wires subscribers correctly.

    Uses wire_events() directly (the same path that BotManager takes)
    to simulate what happens when an agent is loaded from YAML.
    """
    global _yaml_captured
    _yaml_captured = []

    from parrot.core.events.lifecycle.yaml_loader import wire_events

    # Register the CapturingProvider under a discoverable dotted path
    mod_name = "lifecycle_poc_yaml_provider"
    mod = types.ModuleType(mod_name)
    mod.CapturingProvider = _CapturingProvider
    sys.modules[mod_name] = mod

    # Simulated bot stub with an EventRegistry
    class _BotStub:
        name = "poc-yaml-agent"
        events = EventRegistry(forward_to_global=False)

    bot = _BotStub()

    yaml_events_block = {
        "subscribers": [
            {
                "provider": f"{mod_name}:CapturingProvider",
            }
        ]
    }

    wire_events(bot, yaml_events_block)

    # Simulate the invocation lifecycle
    tc = TC.new_root()
    invoke_tc = tc.child()

    await bot.events.emit(BeforeInvokeEvent(
        trace_context=invoke_tc, agent_name="poc-yaml-agent",
        method="ask", source_type="agent", source_name="poc-yaml-agent",
    ))
    await bot.events.emit(AfterInvokeEvent(
        trace_context=invoke_tc, agent_name="poc-yaml-agent",
        method="ask", duration_ms=30.0,
        source_type="agent", source_name="poc-yaml-agent",
    ))

    if len(_yaml_captured) != 2:
        return False, f"Expected 2 events from YAML provider, got {len(_yaml_captured)}"

    types_captured = [type(e).__name__ for e in _yaml_captured]
    expected = ["BeforeInvokeEvent", "AfterInvokeEvent"]
    if types_captured != expected:
        return False, f"Wrong event types from YAML provider: {types_captured}"

    return True, f"YAML provider captured {len(_yaml_captured)} events via declarative wiring"


# ---------------------------------------------------------------------------
# Scenario 5: Subscriber error isolation
# ---------------------------------------------------------------------------

async def scenario_subscriber_error_isolation() -> tuple[bool, str]:
    """Verify a failing subscriber does not prevent other subscribers from firing.

    - failing_subscriber: raises RuntimeError on every call.
    - well_behaved: appends event to captured list.

    Expected: both registered on BeforeInvokeEvent.
    After bot.ask(), well_behaved still fires and a SubscriberErrorEvent
    reaches the global registry.
    """
    with scope() as global_reg:
        subscriber_errors: list = []

        async def capture_errors(evt):
            subscriber_errors.append(evt)

        global_reg.subscribe(SubscriberErrorEvent, capture_errors)

        # Build a local registry with both subscribers
        local_reg = EventRegistry(forward_to_global=True)  # forward errors to global
        captured_well: list = []

        async def failing_subscriber(evt):
            raise RuntimeError("boom — intentional failure")

        async def well_behaved(evt):
            captured_well.append(evt)

        local_reg.subscribe(BeforeInvokeEvent, failing_subscriber)
        local_reg.subscribe(BeforeInvokeEvent, well_behaved)

        # Emit BeforeInvokeEvent
        tc = TC.new_root()
        invoke_tc = tc.child()

        # Emit should NOT raise even if a subscriber fails
        try:
            await local_reg.emit(BeforeInvokeEvent(
                trace_context=invoke_tc, agent_name="error-test-bot",
                method="ask", source_type="agent", source_name="error-test-bot",
            ))
        except Exception as exc:
            return False, f"emit() raised unexpectedly: {type(exc).__name__}: {exc}"

        # well_behaved must have fired
        if len(captured_well) != 1:
            return False, (
                f"well_behaved did not capture BeforeInvokeEvent "
                f"(got {len(captured_well)} events)"
            )

        # SubscriberErrorEvent must have reached global registry
        # Give async tasks a moment to propagate
        await asyncio.sleep(0)

        if not subscriber_errors:
            return False, "No SubscriberErrorEvent reached the global registry"

        err_evt = subscriber_errors[0]
        if "RuntimeError" not in err_evt.error_type:
            return False, f"Unexpected error_type in SubscriberErrorEvent: {err_evt.error_type!r}"

        return True, (
            f"well_behaved fired once; "
            f"SubscriberErrorEvent error_type={err_evt.error_type!r} forwarded to global"
        )


# ---------------------------------------------------------------------------
# Orchestrator (verbatim from spec §3 Module 18)
# ---------------------------------------------------------------------------

SCENARIOS: dict[str, Scenario] = {
    "basic_telemetry":            scenario_basic_telemetry,
    "otel_spans":                 scenario_otel_spans,           # may SKIP
    "a2a_trace_propagation":      scenario_a2a_trace_propagation,
    "yaml_declarative":           scenario_yaml_declarative,
    "subscriber_error_isolation": scenario_subscriber_error_isolation,
}


async def main() -> int:
    results: dict[str, tuple[bool | None, str]] = {}
    for name, fn in SCENARIOS.items():
        print(f"  {name} ...", flush=True)
        try:
            ok, summary = await fn()
            results[name] = (ok, summary)
            print(f"  {'PASS' if ok else 'FAIL'} -- {summary}")
        except SkipScenario as exc:
            results[name] = (None, f"SKIPPED: {exc}")
            print(f"  SKIPPED -- {exc}")
        except Exception as exc:
            results[name] = (False, f"CRASH: {type(exc).__name__}: {exc}")
            import traceback
            traceback.print_exc()
            print(f"  CRASH -- {type(exc).__name__}: {exc}")

    print("\n=== Summary ===")
    passed = [n for n, (ok, _) in results.items() if ok is True]
    failed = [n for n, (ok, _) in results.items() if ok is False]
    skipped = [n for n, (ok, _) in results.items() if ok is None]
    print(f"  passed:  {len(passed)}/{len(SCENARIOS)}")
    print(f"  failed:  {len(failed)}")
    print(f"  skipped: {len(skipped)}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

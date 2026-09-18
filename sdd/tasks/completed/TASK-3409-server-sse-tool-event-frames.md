# TASK-3409: Server SSE `tool_event` frames scoped per request

**Feature**: FEAT-573 — Agent Terminal Workspace for `parrot agent`
**Spec**: `sdd/specs/new-ui-cli-agents.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3402
**Assigned-to**: unassigned

---

## Context

Implements spec §3 **Module 10 (Server SSE tool-event frames)**. Today
`StreamHandler.stream_sse` (`packages/ai-parrot-server/src/parrot/handlers/stream.py:64-110`)
writes only text frames (`{"content": ...}`), one final `{"type": "ai_message", ...}` frame and
`[DONE]`. Tool activity is therefore invisible to a streaming client until the final message.
The lifecycle event system already emits `BeforeToolCallEvent` / `AfterToolCallEvent` /
`ToolCallFailedEvent` from `AbstractTool.execute()` and forwards them to the **global** registry.
This task subscribes to those events for the duration of one streamed turn, **scoped to the
request** through the `turn_scope` ContextVar (TASK-3402), and emits them as
`{"type": "tool_event", ...}` frames between text deltas. Scoping is what makes this safe on a
multi-tenant server: two concurrent SSE requests must never see each other's tool events (AC17).

---

## Scope

- In `stream_sse`: mint a `turn_id`; subscribe the three tool events on `get_global_registry()`
  with `where=in_turn_scope(turn_id)`; callbacks only `put_nowait` a ready-made frame dict onto
  an `asyncio.Queue`; run `bot.ask_stream(...)` inside `with turn_scope(turn_id):`; drain the
  queue before/after every text frame and once more after the stream ends; `finally`
  unsubscribe all three subscriptions.
- Frame grammar (each `data: <json>\n\n`), exactly:
  - `{"content": "<delta>"}` — unchanged
  - `{"type": "tool_event", "data": {"event": "started"|"finished"|"failed", "call_id": <span_id>, "tool_name": str, "turn_id": str, "seq": int, "at": iso8601, + started: "args_summary": {...} | finished: "duration_ms": float, "result_status": str, "result_size_bytes": int | failed: "duration_ms": float, "error_type": str, "error_message": str}}` — **new**
  - `{"type": "ai_message", "data": <AIMessage.to_dict()>}` — unchanged
  - `[DONE]` — unchanged; `error: Internal streaming error` — unchanged
- Write `tests/handlers/test_stream_tool_events.py` with a fake bot that executes a fake
  `AbstractTool` between two deltas, plus a two-request concurrency test.

**NOT in scope**: `stream_ndjson`, `stream_chunked`, `stream_websocket` (unchanged); the CLI-side
parser (TASK-3408); AgentTalk's chunked transport (`handlers/agent.py`); any authentication
change; live tool events for the daemon (Q10, deferred).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/handlers/stream.py` | MODIFY | imports + `stream_sse` body: scoped subscription, queue drain, `tool_event` frames |
| `packages/ai-parrot-server/tests/handlers/test_stream_tool_events.py` | CREATE | frame-order test with a fake tool; concurrency/no-leak test (AC17) |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase.
> The implementing agent MUST use these exact imports, class names, and method signatures.
> **DO NOT** invent, guess, or assume any import, attribute, or method not listed here.
> If you need something not listed, VERIFY it exists first with `grep` or `read`.

### Verified Imports
```python
from typing import Any, Dict, Optional, Set                    # verified: packages/ai-parrot-server/src/parrot/handlers/stream.py:1
import asyncio                                                 # verified: stream.py:2
import logging                                                 # verified: stream.py:3
from aiohttp import web                                        # verified: stream.py:4
from datamodel.parsers.json import json_encoder, json_decoder  # verified: stream.py:5
from navigator.views import BaseHandler                        # verified: stream.py:6
from parrot.bots import AbstractBot                            # verified: stream.py:7
from parrot.models.responses import AIMessage                  # verified: stream.py:8
import uuid                                                    # stdlib — ADD
from parrot.core.events.lifecycle import (                     # verified: packages/ai-parrot/src/parrot/core/events/lifecycle/__init__.py:21-22 (registry), :39-41 (tool events)
    get_global_registry, BeforeToolCallEvent, AfterToolCallEvent, ToolCallFailedEvent)
from parrot.core.events.lifecycle.turn_scope import turn_scope, in_turn_scope   # provided by TASK-3402 (packages/ai-parrot/src/parrot/core/events/lifecycle/turn_scope.py)
# tests only:
import pytest                                                  # test dep
from aiohttp.test_utils import TestClient, TestServer          # aiohttp
from parrot.tools.abstract import AbstractTool, ToolResult     # verified: packages/ai-parrot/tests/unit/tools/test_tool_lifecycle.py:17 uses exactly this import
from parrot.handlers.stream import StreamHandler               # the module under test
```

### Existing Signatures to Use
```python
# packages/ai-parrot-server/src/parrot/handlers/stream.py
class StreamHandler(BaseHandler):                                                   # line 13
    def __init__(self, *args, **kwargs)                                             # line 16 (self.active_connections: Set[web.WebSocketResponse])
    def _get_botmanager(self, request) -> Any                                       # request.app['bot_manager']   # line ~38
    async def _get_bot(self, request: web.Request) -> AbstractBot                   # bot_manager.get_bot(request.match_info['bot_id']); 404 when None
    def _extract_stream_params(self, payload, *extra_ignored_keys) -> (prompt, kwargs)   # line 57 ('prompt' key; rest → ask_stream kwargs)
    async def stream_sse(self, request: web.Request) -> web.StreamResponse          # line 64
        #   data = await request.json(); prompt, ask_kwargs = self._extract_stream_params(data); bot = await self._get_bot(request)   # 69-71
        #   response = web.StreamResponse(status=200, reason='OK', headers={... 'Content-Type': 'text/event-stream' ...})              # 72-82
        #   await response.prepare(request)                                                                                          # 83
        #   try: ai_message = None; async for chunk in bot.ask_stream(prompt, **ask_kwargs): ...                                     # 84-92
        #       sse_data = f"data: {json_encoder({'content': chunk})}\n\n"; await response.write(...); await response.drain()          # 90-92
        #   if ai_message is not None: meta_event = f"data: {json_encoder({'type': 'ai_message', 'data': ai_message.to_dict()})}\n\n"  # 94-95
        #   await response.write(b"data: [DONE]\n\n")                                                                                # 97
        #   except asyncio.CancelledError ... except Exception ... await response.write(b"error: Internal streaming error\n\n")        # 99-107
        #   finally: await response.write_eof()                                                                                      # 109-110
    def configure_routes(self, app: web.Application)                                # line 446; add_post('/bots/{bot_id}/stream/sse', self.stream_sse)  # line 467

# packages/ai-parrot/src/parrot/core/events/lifecycle/events/tool.py
class BeforeToolCallEvent(LifecycleEvent): tool_name: str; tool_class: str; args_summary: dict         # line 12
class AfterToolCallEvent(LifecycleEvent):  tool_name: str; duration_ms: float; result_status: str; result_size_bytes: int   # line 30
class ToolCallFailedEvent(LifecycleEvent): tool_name: str; duration_ms: float; error_type: str; error_message: str          # line 74
# every LifecycleEvent has .trace_context (TraceContext: trace_id, span_id, parent_span_id) and .timestamp (datetime, UTC)

# navigator_eventbus.lifecycle.registry.EventRegistry (0.3.0, installed)
#   def subscribe(self, event_type, callback, *, where=None, forward_to_bus=False) -> str   # returns subscription_id
#   def unsubscribe(self, subscription_id: str) -> bool
#   emit_nowait() and the global forwarder schedule emit() with loop.create_task → contextvars copied

# packages/ai-parrot/src/parrot/tools/abstract.py
#   AbstractTool.__init__(self, name: Optional[str] = None, description: Optional[str] = None, ...)   # line 335
#   async def execute(self, *args, **kwargs) -> ToolResult                                            # line 872
#   tool_tc = pctx.trace_context.child() if pctx else TraceContext.new_root()                         # lines 938-939 (same tool_tc for Before/After/Failed → call_id = span_id)
#   self.events.emit_nowait(BeforeToolCallEvent(...))  # 946 ; await self.events.emit(AfterToolCallEvent(...))  # 1130 ; ToolCallFailedEvent  # 1172

# packages/ai-parrot/src/parrot/core/events/lifecycle/turn_scope.py  (TASK-3402 — fixed by spec §3 M3)
TURN_SCOPE: ContextVar[Optional[str]]
@contextlib.contextmanager
def turn_scope(turn_id: str) -> Iterator[None]
def in_turn_scope(turn_id: str) -> Callable[[LifecycleEvent], bool]

# test fake-tool pattern (packages/ai-parrot/tests/unit/tools/test_tool_lifecycle.py:29-40, :72)
class _OkTool(AbstractTool):
    async def _execute(self, **kwargs) -> ToolResult: return ToolResult(status="success", result="ok")
tool = _OkTool(name="ok-tool"); await tool.execute()
```

### Does NOT Exist
- ~~`{"type": "tool_event", ...}` frames~~ — do not exist yet; **this task adds them**.
- ~~`request.app['bot_manager'].get_bot` returning a `_ServerBotProxy`~~ — on the server the bot is a real `AbstractBot` (or the test fake); `ask_stream` yields `str` and a final `AIMessage`.
- ~~`bot.events.subscribe(BeforeToolCallEvent, ...)` receiving tool events~~ — tool events are emitted on the **tool's** registry and forwarded to the **global** one; subscribe on `get_global_registry()`.
- ~~filtering by `event.trace_context.trace_id == <request trace>`~~ — unreliable (tools mint `new_root()` when no `PermissionContext` carries a trace, `tools/abstract.py:938-939`); use `in_turn_scope(turn_id)`.
- ~~`EventRegistry.subscribe(forward_to_global=...)`~~ — no such parameter (the doc's claim is stale); the real keyword-only params are `where` and `forward_to_bus`.
- ~~awaiting `response.write` inside a subscriber callback~~ — callbacks run on the emitter's task; they must only enqueue.
- ~~a fixture-provided aiohttp app in `tests/handlers/conftest.py`~~ — that conftest only has `recipients_csv`/`recipients_xlsx`/`frozen_now` (CommCenter); build the app locally in the test module.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-server/src/parrot/handlers/stream.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-server/tests/handlers/test_stream_tool_events.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-server/src/parrot/handlers/stream.py#StreamHandler",
    "sym:packages/ai-parrot-server/src/parrot/handlers/stream.py#StreamHandler.stream_sse",
    "sym:packages/ai-parrot/src/parrot/core/events/lifecycle/events/tool.py#BeforeToolCallEvent",
    "sym:packages/ai-parrot/src/parrot/core/events/lifecycle/events/tool.py#AfterToolCallEvent",
    "sym:packages/ai-parrot/src/parrot/core/events/lifecycle/events/tool.py#ToolCallFailedEvent",
    "sym:packages/ai-parrot/src/parrot/tools/abstract.py#AbstractTool.execute"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Subscribe **before** calling `bot.ask_stream` and unsubscribe in `finally` — otherwise a slow
  tool that finishes after the client disconnects leaks a subscription forever.
- Callbacks are `async def` (the registry requires an async subscriber) but must only
  `queue.put_nowait(frame)`; never touch `response` from a callback.
- Draining: call a small `_drain(queue, response)` helper (a) right before writing each text
  frame, (b) after the `async for` completes, (c) once more after a short `await asyncio.sleep(0)`
  so an `AfterToolCallEvent` scheduled by `emit_nowait` on the same tick is not lost.
- `call_id` is `event.trace_context.span_id`; `seq` is a per-turn counter incremented in the
  callback; `at` is `event.timestamp.isoformat()`.
- Existing frames and their order for text-only bots are byte-identical to today (regression
  guard: a bot with no tools produces exactly the same output as before).
- Cross-package: run tests inside the worktree with
  `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-server/src`; never `uv sync` there.
- Google docstrings, `logger` (module-level) for debug lines, `black` 120 cols, `ruff` clean.

### References in Codebase
- `packages/ai-parrot/tests/unit/tools/test_tool_lifecycle.py` — how a fake `AbstractTool` emits lifecycle events in tests.
- `packages/ai-parrot/tests/unit/events/lifecycle/test_registry.py` — registry subscribe/dispatch patterns.
- `packages/ai-parrot-server/tests/handlers/test_openai_compat.py` — local `web.Application` + handler test style in this package.

---

## Implementation Blueprint

> **CRITICAL — Executor-ready starting point.** Write each block below to its declared
> path nearly verbatim, then complete every `# FILL IN:` marker. Never change a signature,
> class name, or file path the blueprint fixes.

### Steps (in order)
1. Add the `uuid` and lifecycle imports below `from parrot.models.responses import AIMessage` — *why*: the handler now subscribes to lifecycle events.
2. Add module-level `_tool_event_frame(event, *, turn_id, seq) -> Dict[str, Any]` and `async def _drain(queue, response)` above `class StreamHandler` — *why*: keeps `stream_sse` short and the frame shape testable in isolation.
3. Replace the `try:` block of `stream_sse` (lines 84-97) with the scoped version below — *why*: subscription, scope and drain must bracket the whole `ask_stream` loop.
4. Leave headers, `except` and `finally` (lines 72-83, 99-110) untouched — *why*: zero behaviour change for text-only bots.
5. Write the tests; run them with the cross-package `PYTHONPATH`.

### `packages/ai-parrot-server/src/parrot/handlers/stream.py` (MODIFY — imports + helpers)
```python
# occurrences: 1 (verified: grep -c 'from parrot.models.responses import AIMessage' packages/ai-parrot-server/src/parrot/handlers/stream.py)
# AFTER — insert below `from parrot.models.responses import AIMessage` (verified: stream.py:8)
import uuid
from parrot.core.events.lifecycle import (
    AfterToolCallEvent,
    BeforeToolCallEvent,
    ToolCallFailedEvent,
    get_global_registry,
)
from parrot.core.events.lifecycle.turn_scope import in_turn_scope, turn_scope  # provided by TASK-3402

# occurrences: 1 (verified: grep -c '^class StreamHandler(BaseHandler):' stream.py)
# BEFORE — insert above `class StreamHandler(BaseHandler):` (verified: stream.py:13)
def _tool_event_frame(event: Any, *, turn_id: str, seq: int) -> Dict[str, Any]:
    """Build the ``tool_event`` SSE frame body for one lifecycle tool event.

    Args:
        event: ``BeforeToolCallEvent`` | ``AfterToolCallEvent`` | ``ToolCallFailedEvent``.
        turn_id: The streamed turn this event belongs to.
        seq: Monotonic per-turn sequence number.

    Returns:
        ``{"type": "tool_event", "data": {...}}`` per spec §3 Module 10.
    """
    data: Dict[str, Any] = {
        "call_id": event.trace_context.span_id,
        "tool_name": event.tool_name,
        "turn_id": turn_id,
        "seq": seq,
        "at": event.timestamp.isoformat(),
    }
    if isinstance(event, BeforeToolCallEvent):
        data.update(event="started", args_summary=dict(event.args_summary or {}))
    elif isinstance(event, AfterToolCallEvent):
        data.update(event="finished", duration_ms=event.duration_ms,
                    result_status=event.result_status, result_size_bytes=event.result_size_bytes)
    else:
        data.update(event="failed", duration_ms=event.duration_ms,
                    error_type=event.error_type, error_message=event.error_message)
    return {"type": "tool_event", "data": data}


async def _drain(queue: "asyncio.Queue[Dict[str, Any]]", response: web.StreamResponse) -> None:
    """Write every queued tool_event frame to ``response`` (non-blocking on an empty queue)."""
    while not queue.empty():
        frame = queue.get_nowait()
        await response.write(f"data: {json_encoder(frame)}\n\n".encode("utf-8"))
        await response.drain()
```
**Why this shape**: the frame keys are the contract TASK-3408's parser reads (`event`, `call_id`, `tool_name`,
`args_summary` / `duration_ms` …); `call_id = span_id` is stable across the three emits of one tool execution
because `AbstractTool.execute` reuses `tool_tc` (`tools/abstract.py:938-1172`).

### `packages/ai-parrot-server/src/parrot/handlers/stream.py` (MODIFY — `stream_sse` try-block)
```python
# occurrences: 1 (verified: grep -c 'ai_message = None' stream.py — the only one is inside stream_sse at line 85)
# REPLACE from `        try:` (stream.py:84) through `            await response.drain()` after `[DONE]` (stream.py:98)
        turn_id = str(uuid.uuid4())
        queue: "asyncio.Queue[Dict[str, Any]]" = asyncio.Queue()
        seq = {"n": 0}
        registry = get_global_registry()

        async def _enqueue(event: Any) -> None:
            seq["n"] += 1
            queue.put_nowait(_tool_event_frame(event, turn_id=turn_id, seq=seq["n"]))

        predicate = in_turn_scope(turn_id)
        sub_ids = [
            registry.subscribe(BeforeToolCallEvent, _enqueue, where=predicate),
            registry.subscribe(AfterToolCallEvent, _enqueue, where=predicate),
            registry.subscribe(ToolCallFailedEvent, _enqueue, where=predicate),
        ]
        try:
            ai_message = None
            with turn_scope(turn_id):
                async for chunk in bot.ask_stream(prompt, **ask_kwargs):
                    if isinstance(chunk, AIMessage):
                        ai_message = chunk
                        continue
                    await _drain(queue, response)
                    sse_data = f"data: {json_encoder({'content': chunk})}\n\n"
                    await response.write(sse_data.encode('utf-8'))
                    await response.drain()
                await asyncio.sleep(0)   # let emit_nowait tasks scheduled on this tick land
                await _drain(queue, response)

            if ai_message is not None:
                meta_event = f"data: {json_encoder({'type': 'ai_message', 'data': ai_message.to_dict()})}\n\n"
                await response.write(meta_event.encode('utf-8'))
                await response.drain()
            await response.write(b"data: [DONE]\n\n")
            await response.drain()
            # FILL IN: nothing else here — keep the existing except/finally clauses (stream.py:99-110) unchanged
```
**Why**: subscribing on the global registry with `where=in_turn_scope(turn_id)` is the only correct correlation
(spec §2 item 4); because `emit_nowait`/global forwarding use `loop.create_task`, the predicate sees this
request's `TURN_SCOPE` and rejects every other request's events (AC17). Draining before each text frame keeps
`started` frames ahead of the text the model produces after the tool.

### `packages/ai-parrot-server/src/parrot/handlers/stream.py` (MODIFY — `finally`)
```python
# occurrences: 1 (verified: grep -c 'await response.write_eof()' stream.py — inside stream_sse only? if >1, quote the preceding `except Exception as e:` + `logger.error("SSE stream error` lines to disambiguate)
# REPLACE `            await response.write_eof()` in stream_sse's finally (verified: stream.py:110)
            for sid in sub_ids:
                registry.unsubscribe(sid)
            await response.write_eof()
```
**Why**: unsubscribe must run on every exit path (normal, cancelled, failed) — a leaked subscription would keep
enqueuing into a dead queue for the process lifetime.

### `packages/ai-parrot-server/tests/handlers/test_stream_tool_events.py` (CREATE)
```python
"""SSE tool_event frames are emitted per request and never leak across requests (FEAT-573 TASK-3409)."""
from __future__ import annotations

import asyncio
import json
from typing import Any, AsyncIterator, List

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from parrot.handlers.stream import StreamHandler
from parrot.models.responses import AIMessage
from parrot.tools.abstract import AbstractTool, ToolResult


class _OkTool(AbstractTool):
    async def _execute(self, **kwargs) -> ToolResult:
        await asyncio.sleep(0.01)
        return ToolResult(status="success", result="ok")


class _FakeBot:
    """ask_stream: delta, tool execution (emits Before/After), delta, final AIMessage."""
    def __init__(self, name: str) -> None:
        self.name = name

    async def ask_stream(self, prompt: str, **kwargs: Any) -> AsyncIterator[Any]:
        yield "Hel"
        await _OkTool(name=f"tool-{self.name}").execute()
        yield "lo"
        # FILL IN: build a minimal AIMessage(input=prompt, output="Hello", model="m", provider="p", usage=CompletionUsage()) — bounded by responses.py:75 required fields


class _BotManager:
    def __init__(self, bots: dict[str, _FakeBot]) -> None:
        self._bots = bots

    async def get_bot(self, bot_id: str) -> Any:
        return self._bots.get(bot_id)


def _parse_frames(body: str) -> List[Any]:
    """Return the decoded `data:` payloads in order ('[DONE]' kept as a string)."""
    out: List[Any] = []
    for block in body.split("\n\n"):
        if block.startswith("data: "):
            payload = block[6:]
            out.append(payload if payload == "[DONE]" else json.loads(payload))
    return out


@pytest.fixture
async def client():
    app = web.Application()
    app["bot_manager"] = _BotManager({"a": _FakeBot("a"), "b": _FakeBot("b")})
    handler = StreamHandler()
    handler.configure_routes(app)   # verified: stream.py:446 registers POST /bots/{bot_id}/stream/sse
    async with TestClient(TestServer(app)) as c:
        yield c


class TestToolEventFrames:
    async def test_frame_order_with_tool(self, client):
        resp = await client.post("/bots/a/stream/sse", json={"prompt": "hi"})
        frames = _parse_frames(await resp.text())
        # FILL IN: assert frames == [{"content":"Hel"}, started, finished, {"content":"lo"}, ai_message, "[DONE]"] by type/event,
        #          started.data.call_id == finished.data.call_id, tool_name == "tool-a" — bounded by spec §3 M10 grammar / AC6

    async def test_two_concurrent_requests_do_not_leak(self, client):
        ra, rb = await asyncio.gather(
            client.post("/bots/a/stream/sse", json={"prompt": "hi"}),
            client.post("/bots/b/stream/sse", json={"prompt": "hi"}),
        )
        # FILL IN: every tool_event in ra's frames has tool_name "tool-a" and in rb's "tool-b"; each has exactly one started+finished — bounded by AC17

    async def test_text_only_bot_unchanged(self, client):
        # FILL IN: a bot whose ask_stream yields only strings + AIMessage produces no tool_event frames and the legacy frame sequence — bounded by "existing frames unchanged"
        ...
```
**Why**: the fake tool is a real `AbstractTool` subclass, so the events are produced by the genuine emit path
(`tools/abstract.py:946/1130`) inside the request's task — the exact mechanism the ContextVar predicate relies on.

### FILL IN checklist
- [ ] `stream.py::stream_sse` — keep `except`/`finally` unchanged apart from the unsubscribe loop; bounded by "existing frames unchanged"
- [ ] `stream.py::_drain` — decide whether to also drain inside the `except Exception` path before `error:` (recommended: no); bounded by zero behaviour change for text-only bots
- [ ] `test_stream_tool_events.py::_FakeBot.ask_stream` — minimal valid `AIMessage`; bounded by `responses.py:75-115` required fields (`input`, `output`, `model`, `provider`, `usage`)
- [ ] `test_stream_tool_events.py` — assertion bodies per spec §4 row `test_stream_sse_emits_tool_event_frames` and AC17

---

## Acceptance Criteria

- [ ] With a tool-using bot, `POST /bots/{id}/stream/sse` emits `tool_event` `started` and `finished` frames before the text the model produces after the tool, and before `ai_message` (spec AC6/AC7)
- [ ] Two concurrent SSE requests never receive each other's `tool_event` frames (spec AC17)
- [ ] For a text-only bot the frame sequence is byte-identical to today: `content`* → `ai_message` → `[DONE]`
- [ ] Every subscription is removed on normal, cancelled and failed exits (`registry.unsubscribe` called for all three ids)
- [ ] Frame keys match spec §3 Module 10 exactly (`event`, `call_id`, `tool_name`, `turn_id`, `seq`, `at`, plus per-kind fields)
- [ ] All tests pass: `pytest packages/ai-parrot-server/tests/handlers/test_stream_tool_events.py -v`
- [ ] Existing stream/a2ui tests green: `pytest packages/ai-parrot-server/tests/handlers/test_agent_a2ui_stream.py -v`
- [ ] `ruff check packages/ai-parrot-server/src/parrot/handlers/stream.py` clean

---

## Validation Commands

- `pytest packages/ai-parrot-server/tests/handlers/test_stream_tool_events.py -q`
- `pytest packages/ai-parrot-server/tests/handlers/test_agent_a2ui_stream.py -q`

---

## Test Specification

```python
# packages/ai-parrot-server/tests/handlers/test_stream_tool_events.py — see blueprint; minimum set:
# TestToolEventFrames.test_frame_order_with_tool          → started/finished between deltas, shared call_id
# TestToolEventFrames.test_two_concurrent_requests_do_not_leak → AC17 (turn_scope isolation)
# TestToolEventFrames.test_text_only_bot_unchanged        → legacy grammar regression guard
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify `Depends-on` tasks are in `tasks/completed/`
3. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source)
   - Confirm every class/method in "Existing Signatures" still has the listed attributes
   - If anything has changed, update the contract FIRST, then implement
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
4. **Update status** in `sdd/tasks/index/new-ui-cli-agents.json` → `"in-progress"` with your session ID
5. **Implement** — start from the Implementation Blueprint blocks, complete every
   `# FILL IN:` marker, and never change a signature or path the blueprint fixes
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-3409-server-sse-tool-event-frames.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-coder native `sonnet` seat (attempt f831350e038c4c2aa136c46ef3f93d0d)
**Date**: 2026-09-18
**Notes**: `StreamHandler.stream_sse` mints a `turn_id`, subscribes
Before/After/Failed tool-call events on `get_global_registry()` scoped via
`in_turn_scope(turn_id)`, runs `bot.ask_stream` inside `turn_scope`, drains
a per-request queue into `tool_event` SSE frames before each text frame and
once more at stream end, unsubscribing in `finally` on every exit path.
Applied the `unscoped-removal-reuses-full-uninstall-helper` feedback
pattern directly: read `EventRegistry.emit`/`emit_nowait`/
`_forward_to_global_safely` source before trusting the blueprint's assumed
frame order, which surfaced a real fire-and-forget forwarding-task race in
the test fixture's timing (not production code) — fixed with a realistic
inter-token latency, verified stable across 5 runs.

Merge clean (`coder_merge` outcome=merged, 0 residual lint). Orchestrator
ran `pytest test_stream_tool_events.py`: 3 passed. Confirmed 2 pre-existing
failures in `test_agent_a2ui_stream.py` are unrelated (target `agent.py`,
a different, explicitly out-of-scope file — string-literal assertions,
untouched by this diff).

**Feedback recorded**: none new — both historical patterns checked;
`unisolated-real-home-in-tests` correctly judged not applicable (no
PARROT_HOME code here), `unscoped-removal-reuses-full-uninstall-helper`
was applicable and correctly applied (see above).
**Deviations from spec**: test-fixture-only timing adjustment (documented
above); production `stream.py` matches the blueprint verbatim.

# TASK-3404: `TurnRunner` — the single execution boundary (`parrot/cli/session.py`)

**Feature**: FEAT-573 — Agent Terminal Workspace for `parrot agent`
**Spec**: `sdd/specs/new-ui-cli-agents.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-3401, TASK-3402, TASK-3403
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 5. Today `AgentREPL.send()` / `send_stream()` (`repl.py:200`, `:228`)
talk to the bot directly and the renderer writes as chunks arrive. The Textual
workspace (TASK-3412) and the inline REPL (TASK-3407) must both consume the same
turn lifecycle, so this task creates the **one place** that calls
`bot.ask()` / `bot.ask_stream()` and turns their yields into the `TurnEvent`
stream defined by TASK-3403 (spec G3, AC5).

It also owns the three cross-cutting behaviours the presenters must not
re-implement: cancellation (spec G9, AC18), live tool progress via the lifecycle
registry scoped to the active turn (spec G4, AC6), and conversation resume from
bot-owned memory (spec G5, AC9).

---

## Scope

- Implement `packages/ai-parrot/src/parrot/cli/session.py` with
  `TurnInProgressError`, `_ResumedResponse` and `TurnRunner` exactly per the spec
  §3 Module 5 Interface Skeleton.
- `run_turn(query)` yields `TurnStarted`, then `TextDelta` / `ToolStarted` /
  `ToolFinished` / `ToolFailed`, then exactly one terminal event
  (`TurnCompleted` | `TurnFailed` | `TurnCancelled`); it never re-raises to the
  presenter.
- Tool events: subscribe `BeforeToolCallEvent`, `AfterToolCallEvent`,
  `ToolCallFailedEvent` on **`get_global_registry()`** with
  `where=in_turn_scope(turn_id)`; `call_id = event.trace_context.span_id`.
- Cancellation: `cancel()` cancels the active task; inside `run_turn`,
  `asyncio.CancelledError` → `aclose()` the iterator → yield `TurnCancelled`.
- `load_history(session_id)` via `bot.get_conversation_history(user_id, session_id)`;
  `reset_session()`; `add_post_turn_hook()`; `history` list; `save_session_pointer`
  after each completed turn.
- Unit tests in `packages/ai-parrot/tests/cli/test_session.py`.

**NOT in scope**: any rendering (TASK-3405/3407/3410-3412), `REPLConfig` changes
(TASK-3407 — this task only *reads* `config.session_id`, `config.user_id`,
`config.permission_context`, `config.streaming`, `config.agent_name`), slash
commands (TASK-3406), backend proxies (TASK-3408/3415), `conftest.py` edits
(TASK-3416).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/cli/session.py` | CREATE | `TurnRunner`, `TurnInProgressError`, `_ResumedResponse` |
| `packages/ai-parrot/tests/cli/test_session.py` | CREATE | Unit tests (fake bot, lifecycle `scope()`, fake tool) |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: Use these exact imports, names and signatures. Anything not listed
> must be verified with `grep`/`read` before use.

### Verified Imports
```python
from parrot.models.outputs import OutputMode                                   # verified: repl.py:24 (TERMINAL = "terminal", models/outputs.py:29)
from parrot.cli.commands import ConversationTurn                               # verified: commands.py:38 (dataclass: query, response, timestamp)
from parrot.core.events.lifecycle import (                                     # verified: core/events/lifecycle/__init__.py:21-22, :39-41
    get_global_registry, BeforeToolCallEvent, AfterToolCallEvent, ToolCallFailedEvent, scope)
from parrot.core.events.lifecycle.turn_scope import turn_scope, in_turn_scope  # provided by TASK-3402 (core/events/lifecycle/turn_scope.py)
from parrot.cli.events import (                                                # provided by TASK-3403 (cli/events.py)
    TurnEvent, TurnStarted, TextDelta, ToolStarted, ToolFinished, ToolFailed,
    TurnCompleted, TurnFailed, TurnCancelled, BackendCapabilities, PostTurnHook, summarize_message_text)
from parrot.cli.modes import save_session_pointer                              # provided by TASK-3401 (cli/modes.py)
from parrot.memory.abstract import ConversationHistory                         # verified: memory/abstract.py:274
from parrot.models.basic import ToolCall                                       # verified: models/basic.py:23
# tests only:
from parrot.tools.abstract import AbstractTool, ToolResult                     # verified: tests/unit/tools/test_tool_lifecycle.py:16
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/bots/abstract.py
async def ask(self, question: str, session_id: Optional[str] = None, user_id: Optional[str] = None, ...,
              output_mode: OutputMode = OutputMode.DEFAULT, ..., **kwargs) -> AIMessage          # line 4533
async def ask_stream(self, question: str, session_id=None, user_id=None, ...) -> AsyncIterator[Union[str, AIMessage]]   # line 4588
async def get_conversation_history(self, user_id: str, session_id: str, chatbot_id: Optional[str] = None) -> Optional[ConversationHistory]   # line 2360
# BaseBot.ask_stream accepts permission_context (bots/base.py:1747) and **kwargs; yields str deltas then one AIMessage (base.py:2004, :2127)

# packages/ai-parrot/src/parrot/cli/repl.py — kwargs the REPL passes today; TurnRunner passes the SAME set
self.bot.ask(question=query, session_id=self.config.session_id, user_id=self.config.user_id,
             output_mode=OutputMode.TERMINAL, permission_context=self.config.permission_context)         # lines 212-218
self.bot.ask_stream(question=query, session_id=..., user_id=..., output_mode=OutputMode.TERMINAL,
                    permission_context=...)                                                               # lines 249-255
# chunk handling to preserve: str → text; hasattr(chunk, "text") → chunk.text; hasattr(chunk, "content") → chunk.content;
# hasattr(chunk, "output") → final message                                                                # lines 256-269

# packages/ai-parrot/src/parrot/cli/commands.py
@dataclass class ConversationTurn: query: str; response: Any; timestamp: datetime = field(default_factory=datetime.now)   # line 38

# packages/ai-parrot/src/parrot/memory/abstract.py
@dataclass class ConversationTurn:  # line 102 — fields used for resume:
    user_message: str            # line 107
    assistant_response: str      # line 108
    timestamp: datetime          # line 111
    tool_invocations: List[ToolInvocation]   # line 119 (ToolInvocation has .name/.arguments/.result/.error — verify with grep before mapping)
    error: Optional[str]         # line 121
@dataclass class ConversationHistory: session_id: str; user_id: str; turns: List[ConversationTurn]   # lines 274-280

# packages/ai-parrot/src/parrot/models/basic.py
class ToolCall(BaseModel): id: str; name: str; arguments: Dict[str, Any]; result: Optional[Any] = None; error: Optional[str] = None; execution_time: Optional[float] = None   # line 23

# packages/ai-parrot/src/parrot/core/events/lifecycle/events/tool.py
class BeforeToolCallEvent(LifecycleEvent): tool_name: str; tool_class: str; args_summary: dict     # line 12
class AfterToolCallEvent(LifecycleEvent): tool_name: str; duration_ms: float; result_status: str; result_size_bytes: int   # line 30
class ToolCallFailedEvent(LifecycleEvent): tool_name: str; duration_ms: float; error_type: str; error_message: str          # line 74
# every event: .trace_context (TraceContext with .span_id) and .timestamp

# navigator_eventbus.lifecycle.registry.EventRegistry (0.3.0)
def subscribe(self, event_type, callback, *, where=None, forward_to_bus=False) -> str
def unsubscribe(self, subscription_id: str) -> bool
# callbacks are `async def cb(event) -> None`

# tests/cli/conftest.py fixtures usable here: mock_agent (AsyncMock; ask_stream yields str chunks of
# "Test streaming response" in 10-char pieces; ask returns a MagicMock with .output/.tool_calls/.usage), repl_config
```

### Does NOT Exist
- ~~`bot.events.subscribe(BeforeToolCallEvent, …)` receiving tool events~~ — tool events are emitted on the **tool's** registry and forwarded to the **global** registry (`tools/abstract.py:946`, `:1130`, `:1172`). Subscribe on `get_global_registry()`.
- ~~filtering tool events by `trace_context.trace_id`~~ — unreliable (`tools/abstract.py:938-939` mints `new_root()` when no `PermissionContext`); use `in_turn_scope(turn_id)`.
- ~~`EventRegistry.subscribe(..., forward_to_global=...)`~~ — no such parameter.
- ~~`AbstractBot.ask_stream` yielding tool events~~ — it yields `str` and a final `AIMessage` only.
- ~~`ConversationMemory.list_sessions()`~~ — not verified; `last` resolution is TASK-3406's job via the pointer file.
- ~~`parrot.cli.session` / `TurnRunner`~~ — created by THIS task.
- ~~`REPLConfig.ui_mode` / `resume_session_id`~~ — added by TASK-3407; do not read them here.
- `getattr(bot, "capabilities", None)` on an `AsyncMock` bot returns a Mock — **`isinstance(..., BackendCapabilities)` check is mandatory**, else fall back to standalone defaults.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/cli/session.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/cli/test_session.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/bots/abstract.py#AbstractBot.ask",
    "sym:packages/ai-parrot/src/parrot/bots/abstract.py#AbstractBot.ask_stream",
    "sym:packages/ai-parrot/src/parrot/bots/abstract.py#AbstractBot.get_conversation_history",
    "sym:packages/ai-parrot/src/parrot/cli/commands.py#ConversationTurn",
    "sym:packages/ai-parrot/src/parrot/memory/abstract.py#ConversationHistory",
    "sym:packages/ai-parrot/src/parrot/memory/abstract.py#ConversationTurn",
    "sym:packages/ai-parrot/src/parrot/models/basic.py#ToolCall",
    "sym:packages/ai-parrot/src/parrot/core/events/lifecycle/events/tool.py#BeforeToolCallEvent",
    "sym:packages/ai-parrot/src/parrot/core/events/lifecycle/events/tool.py#AfterToolCallEvent",
    "sym:packages/ai-parrot/src/parrot/core/events/lifecycle/events/tool.py#ToolCallFailedEvent"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- **Only this module calls the bot** (AC5). Pass exactly the kwargs `repl.py:212-218` / `:249-255` pass today; omit `user_id` from the call when it is `None`.
- Event order per turn: `TurnStarted` (seq 0) → any number of `TextDelta`/`Tool*` → exactly one terminal event. `seq` is monotonic from 0.
- Subscribe **before** the bot call and unsubscribe in `finally`; callbacks only enqueue onto an `asyncio.Queue` — never render, never await the presenter.
- Post-turn hooks run only after `TurnCompleted`; a `ConversationTurn` is appended only for completed turns (AC18).
- Never mutate logging handler levels (AC14) — `_mute_stream_loggers` is deleted by TASK-3407, not replaced here.
- Async-first; `self.logger = logging.getLogger(__name__)`; Google docstrings; Pydantic models come from TASK-3403 — do not redefine them.
- Inside a worktree run tests with `PYTHONPATH=packages/ai-parrot/src pytest …`; never `uv sync` there.

### References in Codebase
- `packages/ai-parrot/src/parrot/cli/repl.py:228-294` — current stream loop (chunk shapes, `_StreamedResponse` fallback).
- `packages/ai-parrot/tests/unit/tools/test_tool_lifecycle.py:19-40` — minimal `AbstractTool` subclass + `_capture()` pattern for tests.
- `packages/ai-parrot/tests/unit/events/lifecycle/test_registry.py` — registry test style.
- `packages/ai-parrot/docs/lifecycle_events.md` §3 — registry API (ignore its `forward_to_global` claim).

---

## Implementation Blueprint

### Steps (in order)
1. Create `session.py` with the block below — *why*: the skeleton names are fixed by spec §3 M5 and consumed by TASK-3406/3407/3412.
2. Implement `_TurnState` bookkeeping (`turn_id`, `seq`, `partial`, `queue`, `subscriptions`) inside `run_turn` — *why*: the generator must yield tool events interleaved with deltas, so tool callbacks enqueue and the loop drains between yields.
3. Implement the delta loop from `repl.py:256-269` chunk rules, wrapped in `turn_scope(turn_id)` — *why*: the ContextVar must be set in the task that awaits the bot so tool emits inherit it.
4. Implement cancellation: `cancel()` calls `task.cancel()` on the awaiting task recorded in `run_turn`; catch `asyncio.CancelledError` around the loop, `await stream.aclose()`, yield `TurnCancelled` — *why*: AC18 requires the partial answer kept and no history append.
5. Implement `load_history` mapping memory turns → CLI turns via `_ResumedResponse` — *why*: `ResponseRenderer.render_history` (TASK-3405) and `/export` read `.query`/`.response.output`/`.tool_calls`.
6. Write tests — *why*: §4 rows `test_turn_event_seq_monotonic_and_terminal_once` … `test_runner_post_turn_hook_after_completed_only`.

### `packages/ai-parrot/src/parrot/cli/session.py` (CREATE)
```python
"""Turn execution boundary for the ``parrot agent`` presenters (FEAT-573, spec §3 M5).

Only this module calls ``bot.ask`` / ``bot.ask_stream``. Both the inline REPL and
the Textual workspace consume the ``TurnEvent`` stream produced here.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any, AsyncIterator, List, Optional
from uuid import uuid4

from parrot.cli.commands import ConversationTurn                               # verified: commands.py:38
from parrot.cli.events import (                                                # provided by TASK-3403
    BackendCapabilities, PostTurnHook, TextDelta, ToolFailed, ToolFinished, ToolStarted,
    TurnCancelled, TurnCompleted, TurnEvent, TurnFailed, TurnStarted, summarize_message_text)
from parrot.cli.modes import save_session_pointer                              # provided by TASK-3401
from parrot.core.events.lifecycle import (                                     # verified: lifecycle/__init__.py:21-22, :39-41
    AfterToolCallEvent, BeforeToolCallEvent, ToolCallFailedEvent, get_global_registry)
from parrot.core.events.lifecycle.turn_scope import in_turn_scope, turn_scope  # provided by TASK-3402
from parrot.models.basic import ToolCall                                       # verified: models/basic.py:23
from parrot.models.outputs import OutputMode                                   # verified: repl.py:24


class TurnInProgressError(RuntimeError):
    """Raised by :meth:`TurnRunner.run_turn` while another turn is active (one turn per session)."""


class _ResumedResponse:
    """AIMessage-compatible view of a stored memory turn (``output``/``response``/``tool_calls``/``usage``)."""

    def __init__(self, output: str, tool_calls: List[ToolCall], error: Optional[str] = None) -> None:
        self.output = output
        self.response = output
        self.tool_calls = tool_calls
        self.usage = None
        self.error = error


class TurnRunner:
    """Run conversation turns against a bot-like backend and yield ``TurnEvent``s.

    Identity kwargs are exactly those ``AgentREPL`` passes today (repl.py:212-218, :249-255):
    ``session_id``, ``user_id``, ``output_mode=OutputMode.TERMINAL``, ``permission_context``.
    ``user_id=None`` is omitted from the call.
    """

    def __init__(self, bot: Any, config: Any, *, capabilities: Optional[BackendCapabilities] = None) -> None:
        self.bot = bot
        self.config = config
        self.history: List[ConversationTurn] = []
        self.logger = logging.getLogger(__name__)
        self._hooks: List[PostTurnHook] = []
        self._active_task: Optional[asyncio.Task] = None
        self._capabilities = capabilities or self._default_capabilities(bot)

    @staticmethod
    def _default_capabilities(bot: Any) -> BackendCapabilities:
        """``bot.capabilities`` when it IS a BackendCapabilities (AsyncMock attrs are not), else standalone defaults."""
        caps = getattr(bot, "capabilities", None)
        if isinstance(caps, BackendCapabilities):
            return caps
        return BackendCapabilities(streaming=True, live_tool_events=True, usage=True,
                                   resume=callable(getattr(bot, "get_conversation_history", None)))

    @property
    def capabilities(self) -> BackendCapabilities:
        return self._capabilities

    @property
    def is_active(self) -> bool:
        return self._active_task is not None and not self._active_task.done()
```
**Why this shape**: module/class names and every public signature come from spec §3 M5 and are consumed by TASK-3406 (`ctx.runner`), TASK-3407 and TASK-3412 — not renegotiable. `_default_capabilities` guards against `AsyncMock` (the `mock_agent` fixture) so `getattr` never yields a truthy Mock.

### `packages/ai-parrot/src/parrot/cli/session.py` (CREATE — second half, same file)
```python
    def _identity_kwargs(self) -> dict[str, Any]:
        """The exact kwargs AgentREPL passes today (repl.py:212-218); ``user_id`` omitted when None."""
        kwargs: dict[str, Any] = {
            "session_id": self.config.session_id,
            "output_mode": OutputMode.TERMINAL,
            "permission_context": self.config.permission_context,
        }
        if self.config.user_id is not None:
            kwargs["user_id"] = self.config.user_id
        return kwargs

    async def run_turn(self, query: str) -> AsyncIterator[TurnEvent]:
        """Yield TurnStarted, then TextDelta/Tool* events, then exactly one terminal event."""
        if self.is_active:
            raise TurnInProgressError("a turn is already running")
        turn_id = str(uuid4())
        seq = 0
        queue: "asyncio.Queue[TurnEvent]" = asyncio.Queue()
        registry = get_global_registry()
        sub_ids: List[str] = []
        partial = ""
        message: Any = None
        self._active_task = asyncio.current_task()
        yield TurnStarted(kind="started", turn_id=turn_id, seq=seq, query=query, streaming=self.config.streaming)
        try:
            if self.capabilities.live_tool_events:
                # FILL IN: three subscribe() calls with where=in_turn_scope(turn_id); callbacks build
                # ToolStarted/ToolFinished/ToolFailed (call_id=event.trace_context.span_id, seq assigned at
                # drain time) and queue.put_nowait them — bounded by spec §2 Data Models + AC6
                pass
            with turn_scope(turn_id):
                if self.config.streaming:
                    stream = self.bot.ask_stream(question=query, **self._identity_kwargs())
                    try:
                        async for chunk in stream:
                            # FILL IN: drain `queue` first (yield each with next seq); then apply repl.py:256-269
                            # chunk rules: str→text; .text; .content; .output→message and break — bounded by AC5/AC8
                            pass
                    except asyncio.CancelledError:
                        await stream.aclose()
                        raise
                else:
                    message = await self.bot.ask(question=query, **self._identity_kwargs())
                    partial = summarize_message_text(message)
            # FILL IN: drain remaining queue, then yield TurnCompleted(text=partial, message=message or
            # _ResumedResponse(partial, [])) ; append ConversationTurn(query, response, datetime.now());
            # save_session_pointer(self.config.agent_name, self.config.session_id); await hooks — bounded by AC18/AC9
        except asyncio.CancelledError:
            yield TurnCancelled(kind="cancelled", turn_id=turn_id, seq=seq + 1, partial_text=partial)
        except Exception as exc:  # noqa: BLE001 — presenters must never see a raw exception (AC19)
            self.logger.exception("turn %s failed", turn_id)
            yield TurnFailed(kind="failed", turn_id=turn_id, seq=seq + 1, error_type=type(exc).__name__,
                             error_message=str(exc), partial_text=partial)
        finally:
            for sid in sub_ids:
                registry.unsubscribe(sid)
            self._active_task = None

    def cancel(self) -> bool:
        """Cancel the active turn's task; True if one was active."""
        if not self.is_active:
            return False
        self._active_task.cancel()  # type: ignore[union-attr]
        return True

    async def load_history(self, session_id: str) -> List[ConversationTurn]:
        """Resume: map ``bot.get_conversation_history(user_id, session_id)`` turns to CLI turns."""
        if not self.capabilities.resume:
            return []
        history = await self.bot.get_conversation_history(self.config.user_id or "cli-user", session_id)
        if history is None:
            return []
        # FILL IN: for each memory turn build ConversationTurn(query=t.user_message,
        # response=_ResumedResponse(t.assistant_response, [ToolCall(...) from t.tool_invocations], t.error),
        # timestamp=t.timestamp); set self.config.session_id = session_id; replace self.history — bounded by AC9
        return self.history

    def reset_session(self) -> str:
        """New session id (``/clear`` semantics, commands.py:228-230); clears history."""
        self.config.session_id = str(uuid4())
        self.history.clear()
        return self.config.session_id

    def add_post_turn_hook(self, hook: PostTurnHook) -> None:
        """Register a coroutine awaited after each COMPLETED turn."""
        self._hooks.append(hook)
```
**Why**: the `seq` counter and the queue drain make tool events observable *between* deltas without a second task; `asyncio.current_task()` is what `cancel()` cancels; `aclose()` before re-raising closes the bot's generator so `BaseBot.ask_stream`'s `finally` (base.py) runs. `TurnCancelled` and `TurnFailed` bypass history and hooks by construction. Split across two blocks only to respect the 80-line cap — it is ONE file.

### `packages/ai-parrot/tests/cli/test_session.py` (CREATE)
```python
"""Unit tests for parrot.cli.session.TurnRunner (FEAT-573 TASK-3404, spec §4)."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any, List

import pytest

from parrot.cli.events import (TurnCancelled, TurnCompleted, TurnEventKind, TurnFailed,  # provided by TASK-3403
                               ToolFinished, ToolStarted)
from parrot.cli.session import TurnInProgressError, TurnRunner
from parrot.core.events.lifecycle import scope                                    # verified: lifecycle/__init__.py:22
from parrot.models.outputs import OutputMode                                      # verified: repl.py:24
from parrot.tools.abstract import AbstractTool, ToolResult                        # verified: tests/unit/tools/test_tool_lifecycle.py:16


class _OkTool(AbstractTool):
    """Emits Before/After lifecycle events when executed (pattern: tests/unit/tools/test_tool_lifecycle.py:19)."""

    async def _execute(self, **kwargs) -> ToolResult:
        return ToolResult(status="success", result="ok")


def _config(**over: Any) -> SimpleNamespace:
    base = dict(agent_name="t", streaming=True, session_id="s-1", user_id="u", permission_context=None)
    base.update(over)
    return SimpleNamespace(**base)


class _FakeBot:
    def __init__(self, deltas: List[str], final: Any = None, tool: AbstractTool | None = None, fail_after: int | None = None):
        self.deltas, self.final, self.tool, self.fail_after = deltas, final, tool, fail_after
        self.calls: List[dict] = []
        self.closed = False

    async def ask_stream(self, question: str, **kwargs):
        self.calls.append(kwargs)
        try:
            for i, d in enumerate(self.deltas):
                if self.fail_after is not None and i == self.fail_after:
                    raise RuntimeError("boom")
                if self.tool is not None and i == 1:
                    await self.tool.execute()  # emits inside the caller's task → inside turn_scope
                yield d
                await asyncio.sleep(0)
            if self.final is not None:
                yield self.final
        finally:
            self.closed = True

    async def ask(self, question: str, **kwargs):
        self.calls.append(kwargs)
        return self.final


@pytest.fixture
def lifecycle_scope():
    with scope() as reg:
        yield reg


async def _collect(runner: TurnRunner, query: str):
    return [e async for e in runner.run_turn(query)]


@pytest.mark.asyncio
async def test_turn_event_seq_monotonic_and_terminal_once(lifecycle_scope):
    final = SimpleNamespace(output="abc", response="abc", tool_calls=[], usage=None)
    runner = TurnRunner(_FakeBot(["a", "b", "c"], final), _config())
    events = await _collect(runner, "hi")
    # FILL IN: assert kinds == [STARTED, DELTA, DELTA, DELTA, COMPLETED]; seq == 0..4; history len 1 — AC5
    assert isinstance(events[-1], TurnCompleted)


@pytest.mark.asyncio
async def test_runner_live_tool_events_scoped(lifecycle_scope, tmp_path, monkeypatch):
    monkeypatch.setenv("PARROT_HOME", str(tmp_path))
    runner = TurnRunner(_FakeBot(["a", "b"], None, tool=_OkTool()), _config())
    events = await _collect(runner, "hi")
    # FILL IN: exactly one ToolStarted and one ToolFinished, equal call_id, both before TurnCompleted — AC6
    # FILL IN: second test body: a tool executed OUTSIDE run_turn (no scope) yields no Tool* events


# FILL IN (one test each, spec §4): test_runner_batch_mode_uses_ask (kwargs == session_id/output_mode=TERMINAL/
# permission_context, no user_id when None) · test_runner_cancel_yields_cancelled_and_closes_stream (slow bot, cancel
# from another task → TurnCancelled(partial), bot.closed, history unchanged, hooks not run) ·
# test_runner_failure_preserves_partial · test_runner_rejects_second_turn (TurnInProgressError) ·
# test_runner_load_history_maps_memory_turns · test_runner_post_turn_hook_after_completed_only
```
**Why**: `scope()` isolates the global registry so the test never sees another test's tool events; `_OkTool.execute()` awaited inside `ask_stream` runs in the runner's task, so `TURN_SCOPE` is set when the tool emits — this is the property spec §2 item 4 relies on. `PARROT_HOME` is redirected because a completed turn writes the session pointer (TASK-3401).

### FILL IN checklist
- [ ] `session.py::TurnRunner.run_turn` — subscription callbacks and queue drain; bounded by spec §2 Data Models (call_id = span_id, seq monotonic) and AC6.
- [ ] `session.py::TurnRunner.run_turn` — chunk rules copied from `repl.py:256-269`; bounded by AC5/AC8.
- [ ] `session.py::TurnRunner.run_turn` — completion tail (TurnCompleted, history append, pointer save, hooks); bounded by AC9/AC18.
- [ ] `session.py::TurnRunner.load_history` — memory→CLI turn mapping incl. `tool_invocations`→`ToolCall`; bounded by AC9 (verify `ToolInvocation` field names with grep first).
- [ ] `test_session.py` — the eight test bodies listed; bounded by spec §4 rows.

---

## Acceptance Criteria

- [ ] `from parrot.cli.session import TurnRunner, TurnInProgressError` works.
- [ ] Event stream shape and `seq` monotonic (spec AC5).
- [ ] Live tool events arrive between deltas with equal `call_id`; out-of-scope emits are ignored (spec AC6).
- [ ] `cancel()` → `TurnCancelled(partial_text)`, iterator closed, no history append, no hooks (spec AC18).
- [ ] Mid-stream exception → `TurnFailed(partial_text)`; nothing escapes (spec AC19).
- [ ] `load_history` maps memory turns and updates `config.session_id` (spec AC9).
- [ ] `grep -n "handler.setLevel" packages/ai-parrot/src/parrot/cli/session.py` is empty (spec AC14).
- [ ] All tests pass; `ruff check packages/ai-parrot/src/parrot/cli/session.py` clean.

## Validation Commands

- `pytest packages/ai-parrot/tests/cli/test_session.py -q`

---

## Test Specification

See the CREATE block for `test_session.py`; required test names (spec §4):
`test_turn_event_seq_monotonic_and_terminal_once`, `test_runner_batch_mode_uses_ask`,
`test_runner_live_tool_events_scoped`, `test_runner_cancel_yields_cancelled_and_closes_stream`,
`test_runner_failure_preserves_partial`, `test_runner_rejects_second_turn`,
`test_runner_load_history_maps_memory_turns`, `test_runner_post_turn_hook_after_completed_only`.

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
4. **Update status** in the per-spec index → `"in-progress"` with your session ID
5. **Implement** — start from the Implementation Blueprint blocks, complete every
   `# FILL IN:` marker, and never change a signature or path the blueprint fixes
6. **Verify** all acceptance criteria are met
7. **Move this file** to `tasks/completed/TASK-3404-turn-runner-session.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none | describe if any

# TASK-3403: Presentation-neutral turn event model (`parrot/cli/events.py`)

**Feature**: FEAT-573 — Agent Terminal Workspace for `parrot agent`
**Spec**: `sdd/specs/new-ui-cli-agents.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 **Module 4** and §2 Data Models. Today `AgentREPL.send_stream` consumes raw
`str` chunks plus a final `AIMessage` directly (`repl.py:256-271`) and the renderer owns
the terminal; there is no typed description of "what happened during a turn". Both
presenters (inline `AgentREPL`, Textual `AgentWorkspaceApp`) must consume ONE event stream
produced by `TurnRunner` (G3, spec AC5), and the server proxy must be able to yield the
same tool events it parses from SSE frames (TASK-3408/3409).

This task defines that vocabulary: the `TurnEvent` family, `BackendCapabilities` (what a
backend can do: streaming, live tool events, usage, resume) and the `PostTurnHook` alias.
It is a pure Pydantic module with no I/O — a root of the graph consumed by
TASK-3404/3405/3406/3408/3410.

---

## Scope

- Create `parrot/cli/events.py` with exactly the models in spec §2 Data Models:
  `TurnEventKind`, `TurnEvent` (base: `kind`, `turn_id`, `seq`, `at`), `TurnStarted`,
  `TextDelta`, `ToolStarted`, `ToolFinished`, `ToolFailed`, `TurnCompleted`, `TurnFailed`,
  `TurnCancelled`, `BackendCapabilities`; plus `PostTurnHook` and `summarize_message_text()`.
- Each concrete event fixes its own `kind` via a default so producers cannot mislabel it.
- Unit tests: kinds are fixed per class, `seq`/`at` defaults, `TurnCompleted.message`
  accepts arbitrary objects (MagicMock / `_StreamedResponse`-like), `summarize_message_text`
  mirrors the renderer's fallback order, `BackendCapabilities` defaults.

**NOT in scope**: producing events (TASK-3404), rendering them (TASK-3405, TASK-3410),
parsing SSE frames into them (TASK-3408), the `CommandContext` protocol (TASK-3406).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/cli/events.py` | CREATE | `TurnEvent` family, `BackendCapabilities`, `PostTurnHook`, `summarize_message_text` |
| `packages/ai-parrot/tests/cli/test_events.py` | CREATE | Model behaviour tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase.
> The implementing agent MUST use these exact imports, class names, and method signatures.
> **DO NOT** invent, guess, or assume any import, attribute, or method not listed here.
> If you need something not listed, VERIFY it exists first with `grep` or `read`.

### Verified Imports
```python
from pydantic import BaseModel, ConfigDict, Field     # verified: BaseModel/Field parrot/cli/repl.py:18; ConfigDict parrot/models/responses.py (AIMessage.model_config = ConfigDict(arbitrary_types_allowed=True), :186)
from parrot.cli.commands import ConversationTurn      # verified: packages/ai-parrot/src/parrot/cli/commands.py:38 (also imported at repl.py:22)
from datetime import datetime                         # stdlib (pattern: commands.py:14)
from enum import Enum                                 # stdlib
import json                                           # stdlib (pattern: commands.py:11)
from typing import TYPE_CHECKING, Any, Awaitable, Callable   # stdlib
import pytest                                         # verified: packages/ai-parrot/tests/cli/test_integration.py:14
from unittest.mock import MagicMock                   # verified: packages/ai-parrot/tests/cli/test_integration.py:12
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/cli/commands.py
@dataclass
class ConversationTurn:                                  # line 38
    query: str                                           # line 47
    response: Any                                        # line 48  (AIMessage or a duck-typed proxy)
    timestamp: datetime = field(default_factory=datetime.now)   # line 49
    def to_dict(self) -> Dict[str, Any]:                 # line 51  (uses response.output or response.response)

# packages/ai-parrot/src/parrot/cli/renderer.py — fallback order to mirror in summarize_message_text
def render(self, response: AIMessage) -> None:           # line 89
    output = response.output                             # line 98
    if output is None: output = response.response or ""  # lines 99-100
    if isinstance(output, str) and output.strip(): ...   # line 103
    elif isinstance(output, (dict, list)): json.dumps(output, indent=2, default=str)   # lines 105-107
    elif output is not None: str(output)                 # lines 111-112

# packages/ai-parrot/src/parrot/cli/repl.py
class _StreamedResponse:                                 # line 305  (duck type: .output, .response, .tool_calls=[], .usage=None)

# packages/ai-parrot/src/parrot/models/responses.py
class AIMessage(BaseModel):                              # line 75
    output: Any ; response: Optional[str]                # lines 78-79
    usage: CompletionUsage                               # line 101
    tool_calls: List[ToolCall]                           # line 115
    model_config = ConfigDict(arbitrary_types_allowed=True)   # line 186

# packages/ai-parrot/src/parrot/core/events/lifecycle/events/tool.py — field names the Tool* events mirror
class BeforeToolCallEvent(LifecycleEvent): tool_name: str; tool_class: str; args_summary: dict      # line 12
class AfterToolCallEvent(LifecycleEvent):  tool_name; duration_ms; result_status; result_size_bytes # line 30
class ToolCallFailedEvent(LifecycleEvent): tool_name; duration_ms; error_type; error_message       # line 74
```

### Does NOT Exist
- ~~`parrot.cli.events`~~ — created by this task.
- ~~`parrot.models.responses.StreamChunk` as the CLI event type~~ — it exists (`responses.py:53`, fields `content/is_complete/chunk_id/turn_id`) but is a client-level chunk model; do NOT reuse or subclass it. The CLI event family is new and richer.
- ~~`TurnEvent` / `ToolStarted` / `BackendCapabilities` anywhere in `parrot/`~~ — new names; nothing else defines them.
- ~~`parrot.cli.session.TurnRunner`, `parrot.cli.commands.CommandContext`~~ — created by TASK-3404 / TASK-3406; reference them only under `TYPE_CHECKING` (for the `PostTurnHook` alias) as a string forward reference.
- ~~`AIMessage.text` / `.content_text`~~ — the text accessor is `to_text()` (`responses.py:205`) and `.content` is an alias of `.output`; `summarize_message_text` must follow the renderer's `output`→`response` order, not call `to_text()` (duck-typed proxies lack it).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/cli/events.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/cli/test_events.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/cli/commands.py#ConversationTurn",
    "sym:packages/ai-parrot/src/parrot/cli/renderer.py#ResponseRenderer.render",
    "sym:packages/ai-parrot/src/parrot/models/responses.py#AIMessage",
    "sym:packages/ai-parrot/src/parrot/core/events/lifecycle/events/tool.py#BeforeToolCallEvent",
    "sym:packages/ai-parrot/src/parrot/core/events/lifecycle/events/tool.py#AfterToolCallEvent",
    "sym:packages/ai-parrot/src/parrot/core/events/lifecycle/events/tool.py#ToolCallFailedEvent"
  ]
}
```

---

## Implementation Notes

### Pattern to Follow
```python
# responses.py:186 — allow arbitrary payloads on a Pydantic v2 model
model_config = ConfigDict(arbitrary_types_allowed=True)
```

### Key Constraints
- Field names and types are fixed by spec §2 Data Models; consumers in five other tasks
  use them verbatim. `kind` on each concrete class is a `Literal`-style fixed default
  (`kind: TurnEventKind = TurnEventKind.DELTA`), never a required argument.
- `seq` is an `int >= 0` (`Field(ge=0)`); the producer (TASK-3404) guarantees monotonicity — do not enforce ordering here.
- `TurnCompleted.message: Any` requires `arbitrary_types_allowed=True` (AIMessage, `_StreamedResponse`, `_ServerResponse`, MagicMock in tests).
- `summarize_message_text()` must never raise on a duck-typed object missing `output`/`response`
  (use `getattr(..., None)`); dict/list outputs are `json.dumps(indent=2, default=str)` like `renderer.py:105-107`.
- `PostTurnHook` is `Callable[["CommandContext", ConversationTurn], Awaitable[None]]` with
  `CommandContext` imported under `TYPE_CHECKING` from `parrot.cli.commands` — that name is
  added by TASK-3406; until then the string annotation is unresolved at runtime, which is fine
  because `from __future__ import annotations` keeps it lazy.
- Inside a worktree run tests with `PYTHONPATH=packages/ai-parrot/src pytest ...`; never `uv sync` there.

### References in Codebase
- `packages/ai-parrot/src/parrot/cli/renderer.py:89-122` — text fallback order.
- `packages/ai-parrot/src/parrot/cli/commands.py:38-67` — `ConversationTurn`.
- `packages/ai-parrot/src/parrot/core/events/lifecycle/events/tool.py` — source field names for `Tool*` events.
- `sdd/specs/new-ui-cli-agents.spec.md` §2 Data Models, §3 Module 4, AC5, AC8.

---

## Implementation Blueprint

> **CRITICAL — Executor-ready starting point.** Write each block below to its declared
> path nearly verbatim, then complete every `# FILL IN:` marker.

### Steps (in order)
1. Write the enum, base class and nine concrete events with fixed `kind` defaults — *why*: a producer can only mislabel an event by fighting the type system.
2. Add `BackendCapabilities`, `PostTurnHook`, `summarize_message_text` — *why*: `TurnRunner`, the server proxy and the renderer all need one definition of "backend can/can't" and one text-extraction rule (AC8: never invent text or usage).
3. Write the tests, using `MagicMock` payloads as `tests/cli/conftest.py::_make_ai_message` does — *why*: the CLI test-suite convention is duck-typed message mocks; the models must accept them.

### `packages/ai-parrot/src/parrot/cli/events.py` (CREATE)
```python
"""Presentation-neutral turn lifecycle events for the Parrot agent CLI (FEAT-573 M4).

One ``TurnRunner`` (parrot/cli/session.py) produces these; the inline REPL and the Textual
workspace consume them. Nothing here performs I/O.
"""
from __future__ import annotations

import json
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING, Any, Awaitable, Callable

from pydantic import BaseModel, ConfigDict, Field  # verified: parrot/cli/repl.py:18, parrot/models/responses.py:186

from parrot.cli.commands import ConversationTurn  # verified: parrot/cli/commands.py:38

if TYPE_CHECKING:  # added by TASK-3406
    from parrot.cli.commands import CommandContext

#: Awaited after each COMPLETED turn, before control returns to the presenter.
PostTurnHook = Callable[["CommandContext", ConversationTurn], Awaitable[None]]


class TurnEventKind(str, Enum):
    """Discriminator for :class:`TurnEvent` subclasses."""

    STARTED = "started"
    DELTA = "delta"
    TOOL_STARTED = "tool_started"
    TOOL_FINISHED = "tool_finished"
    TOOL_FAILED = "tool_failed"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TurnEvent(BaseModel):
    """Base event: ``seq`` is monotonic per turn (starts at 0), ``at`` is wall-clock."""

    model_config = ConfigDict(arbitrary_types_allowed=True)
    kind: TurnEventKind
    turn_id: str
    seq: int = Field(ge=0)
    at: datetime = Field(default_factory=datetime.now)


class TurnStarted(TurnEvent):
    kind: TurnEventKind = TurnEventKind.STARTED
    query: str
    streaming: bool


class TextDelta(TurnEvent):
    kind: TurnEventKind = TurnEventKind.DELTA
    text: str


class ToolStarted(TurnEvent):
    """``call_id`` is the lifecycle event's ``trace_context.span_id``; ``args_summary`` is already truncated."""
    kind: TurnEventKind = TurnEventKind.TOOL_STARTED
    call_id: str
    tool_name: str
    args_summary: dict[str, Any] = Field(default_factory=dict)
```

**Part 2 of the same file** — continue appending to `packages/ai-parrot/src/parrot/cli/events.py` (split only to respect the 80-line block cap):
```python
class ToolFinished(TurnEvent):
    kind: TurnEventKind = TurnEventKind.TOOL_FINISHED
    call_id: str
    tool_name: str
    duration_ms: float
    result_status: str
    result_size_bytes: int


class ToolFailed(TurnEvent):
    kind: TurnEventKind = TurnEventKind.TOOL_FAILED
    call_id: str
    tool_name: str
    duration_ms: float
    error_type: str
    error_message: str


class TurnCompleted(TurnEvent):
    """``message`` is the AIMessage or backend response object (duck-typed: .output/.response/.tool_calls/.usage)."""
    kind: TurnEventKind = TurnEventKind.COMPLETED
    text: str
    message: Any


class TurnFailed(TurnEvent):
    kind: TurnEventKind = TurnEventKind.FAILED
    error_type: str
    error_message: str
    partial_text: str = ""


class TurnCancelled(TurnEvent):
    kind: TurnEventKind = TurnEventKind.CANCELLED
    partial_text: str = ""


class BackendCapabilities(BaseModel):
    """What a bot-like backend can do; read by ``TurnRunner`` via ``getattr(bot, 'capabilities', None)``."""

    streaming: bool = True
    live_tool_events: bool = False
    usage: bool = False
    resume: bool = False


def summarize_message_text(message: Any) -> str:
    """``output`` if str, else ``response``, else ``json.dumps(output)`` — mirrors renderer.py:98-112. Never raises."""
    # FILL IN: output = getattr(message, "output", None); fall back to getattr(message, "response", None) or "";
    # str → as-is; dict/list → json.dumps(indent=2, default=str) (TypeError/ValueError → str(output));
    # other non-None → str(output) — bounded by renderer.py:98-112 and AC8 (never fabricate text).
    raise NotImplementedError
```
**Why this shape**: the class-level `kind` defaults make each subclass self-describing so a
`match event.kind` in presenters is exhaustive over `TurnEventKind`. The two blocks are
under 80 lines combined only because the models are declarative; keep it that way — no
methods beyond `summarize_message_text`.

### `packages/ai-parrot/tests/cli/test_events.py` (CREATE)
```python
"""Unit tests for parrot.cli.events (FEAT-573 TASK-3403)."""
from __future__ import annotations

from unittest.mock import MagicMock  # verified: tests/cli/test_integration.py:12

import pytest  # verified: tests/cli/test_integration.py:14

from parrot.cli.events import (
    BackendCapabilities, TextDelta, ToolFailed, ToolFinished, ToolStarted, TurnCancelled,
    TurnCompleted, TurnEventKind, TurnFailed, TurnStarted, summarize_message_text,
)


@pytest.mark.parametrize(
    ("cls", "kwargs", "kind"),
    [
        (TurnStarted, {"query": "hi", "streaming": True}, TurnEventKind.STARTED),
        (TextDelta, {"text": "he"}, TurnEventKind.DELTA),
        (ToolStarted, {"call_id": "s1", "tool_name": "t"}, TurnEventKind.TOOL_STARTED),
        (ToolFinished, {"call_id": "s1", "tool_name": "t", "duration_ms": 1.0, "result_status": "success", "result_size_bytes": 2}, TurnEventKind.TOOL_FINISHED),
        (ToolFailed, {"call_id": "s1", "tool_name": "t", "duration_ms": 1.0, "error_type": "E", "error_message": "m"}, TurnEventKind.TOOL_FAILED),
        (TurnCompleted, {"text": "x", "message": MagicMock()}, TurnEventKind.COMPLETED),
        (TurnFailed, {"error_type": "E", "error_message": "m"}, TurnEventKind.FAILED),
        (TurnCancelled, {}, TurnEventKind.CANCELLED),
    ],
)
def test_each_event_has_fixed_kind_and_defaults(cls, kwargs, kind) -> None:
    ev = cls(turn_id="t", seq=0, **kwargs)
    assert ev.kind is kind and ev.turn_id == "t" and ev.seq == 0 and ev.at is not None


def test_seq_must_be_non_negative() -> None:
    with pytest.raises(ValueError):
        TextDelta(turn_id="t", seq=-1, text="x")


def test_turn_completed_accepts_duck_typed_message() -> None:
    msg = MagicMock(); msg.output = "answer"; msg.response = None
    ev = TurnCompleted(turn_id="t", seq=3, text="answer", message=msg)
    assert ev.message is msg


def test_summarize_message_text_fallback_order() -> None:
    m1 = MagicMock(); m1.output = "plain"; assert summarize_message_text(m1) == "plain"
    m2 = MagicMock(); m2.output = None; m2.response = "resp"; assert summarize_message_text(m2) == "resp"
    m3 = MagicMock(); m3.output = {"a": 1}; assert '"a": 1' in summarize_message_text(m3)
    assert summarize_message_text(object()) == ""
    # FILL IN: list output and a non-JSON-serialisable object → str() — bounded by renderer.py:105-112.


def test_backend_capabilities_defaults() -> None:
    caps = BackendCapabilities()
    assert (caps.streaming, caps.live_tool_events, caps.usage, caps.resume) == (True, False, False, False)
```
**Why**: rows map to spec §4 (`test_turn_event_seq_monotonic_and_terminal_once` is the
producer's test in TASK-3404; here we pin the model surface it relies on). The duck-typed
`MagicMock` payloads mirror `tests/cli/conftest.py::_make_ai_message`.

### FILL IN checklist
- [ ] `events.py::summarize_message_text` — fallback order; bounded by `renderer.py:98-112`, AC8.
- [ ] `test_events.py::test_summarize_message_text_fallback_order` — list and non-serialisable cases.

---

## Acceptance Criteria

- [ ] `from parrot.cli.events import TurnEventKind, TurnEvent, TurnStarted, TextDelta, ToolStarted, ToolFinished, ToolFailed, TurnCompleted, TurnFailed, TurnCancelled, BackendCapabilities, PostTurnHook, summarize_message_text` works, and `import parrot.cli.events` does not import `textual`, `parrot.cli.session` or `parrot.cli.repl` at runtime.
- [ ] Every concrete event class has a fixed `kind` matching spec §2 Data Models; `seq < 0` is rejected.
- [ ] `TurnCompleted(message=<any object>)` validates (spec §2: AIMessage or backend response object).
- [ ] `summarize_message_text` follows `renderer.py:98-112` and never raises on a duck-typed object (spec AC8).
- [ ] `BackendCapabilities()` defaults are `streaming=True, live_tool_events=False, usage=False, resume=False`.
- [ ] All tests pass: `pytest packages/ai-parrot/tests/cli/test_events.py -v`
- [ ] `ruff check` and `mypy` clean on `events.py`.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/cli/test_events.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/cli/test_events.py — see blueprint
def test_each_event_has_fixed_kind_and_defaults(cls, kwargs, kind): ...
def test_seq_must_be_non_negative(): ...
def test_turn_completed_accepts_duck_typed_message(): ...
def test_summarize_message_text_fallback_order(): ...
def test_backend_capabilities_defaults(): ...
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
4. **Update status** in `tasks/.index.json` → `"in-progress"` with your session ID
5. **Implement** — start from the Implementation Blueprint blocks, complete every
   `# FILL IN:` marker, and never change a signature or path the blueprint fixes
6. **Verify** all acceptance criteria are met
7. **Move this file** to `tasks/completed/TASK-3403-turn-event-model.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any

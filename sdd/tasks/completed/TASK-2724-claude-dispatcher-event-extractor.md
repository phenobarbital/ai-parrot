# TASK-2724: Claude dispatcher — block extractor + tool-use correlation

**Feature**: FEAT-496 — Dev-Loop Dispatch Event Legibility
**Spec**: `sdd/specs/dev-loop-dispatch-event-legibility.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-2723
**Assigned-to**: unassigned

---

## Context

Spec §1 root causes 1–3, §2 "Layer 3", §3 Module 3.

This is the task that fixes the exact output the user reported. `claude-code`
is the default dev-loop backend, and its `_publish_message_event`
(`claude.py:1116`) reduces every SDK message to its **class name**:

```
dispatch.message     message_class=SystemMessage
{"message_class": "SystemMessage"}

dispatch.tool_result message_class=UserMessage
{"message_class": "UserMessage", "tools": ["toolu_01DJTbBETmR3cVWEy8t9BxLu"]}
```

Three separate defects live in that one method:

1. `SystemMessage` (which carries the session's resolved `model`, `cwd`,
   `tools`, `mcp_servers`, `slash_commands`, `session_id`) and the terminal
   `ResultMessage` (`subtype`, `num_turns`, `duration_ms`, `total_cost_usd`)
   are both flattened to a class name.
2. A `ToolResultBlock`'s `tool_use_id` is written into `payload["tools"]`
   (`claude.py:1149-1152`) — that is the opaque `toolu_01…` string. The tool
   *name* was known one message earlier and is discarded.
3. The key is `payload["tools"]` (a list), but
   `action_from_dispatch_event` (`session_state.py:1337-1338`) reads
   `payload["tool_name"]` — so `DispatchToolUse.tool_name` has been the empty
   string for every Claude dispatch ever run, and the console's `briefOf`
   falls through to its `keys[0]=value` last resort.

---

## Scope

- Rewrite `ClaudeCodeDispatcher._publish_message_event` (`claude.py:1116`) to
  extract per-block detail instead of a class name.
- Emit `tool_name` (singular, the key `session_state` actually reads) plus
  `tool_input` for `ToolUseBlock`; keep `tools` as-is for backward
  compatibility with anything already reading it.
- Add a **per-dispatch** `tool_use_id → tool_name` correlation map so a
  `ToolResultBlock` reports the originating tool's name, plus `is_error` and
  a clamped result snippet.
- Enrich `SystemMessage` and `ResultMessage` payloads.
- Route `ClaudeCodeDispatcher._publish_event` (`claude.py:1077`) through
  `normalize_payload`.
- Accept `labels: Optional[DispatchLabels] = None` on
  `ClaudeCodeDispatcher.dispatch` (`claude.py:170`) and bind/reset it
  alongside the existing `_SESSION_HOST_CTX` token.
- Extend the dispatcher's tests.

**NOT in scope**: other dispatchers; `session_state.py`; `agent_pool.py`;
console HTML.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/claude.py` | MODIFY | extractor, correlation map, `labels` kwarg, `_publish_event` wiring |
| `packages/ai-parrot/tests/flows/dev_loop/test_claude_dispatcher_events.py` | CREATE | new event-legibility tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# verified: dispatchers/claude.py:50 — claude.py ALREADY imports from _shared
from parrot.flows.dev_loop.dispatchers._shared import _SESSION_HOST_CTX
# add (created by TASK-2722 / TASK-2723, same module):
from parrot.flows.dev_loop.dispatchers._shared import (
    bind_labels, normalize_payload, summarize_tool_input,
    TEXT_MAX_CHARS,
)
from parrot.flows.dev_loop.models import DispatchLabels
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/claude.py
class ClaudeCodeDispatcher:                                   # line 94
    async def dispatch(self, *, brief, profile, output_model,
                       run_id, node_id, cwd,
                       session_host=None) -> T:               # line 170
        stream_key = f"flow:{run_id}:dispatch:{node_id}"      # line 204
        _host_token = _SESSION_HOST_CTX.set(session_host)     # line 211
        # ... _SESSION_HOST_CTX.reset(_host_token)            # lines 231, 456
        # dispatch.queued  {"profile": ..., "dispatcher": "claude-code"}  # 218-229
        # dispatch.started {"cwd": cwd, "subagent": profile.subagent}     # 252-257
        # per-message:  await self._publish_message_event(...)            # line 271
        # dispatch.failed on TimeoutError                                 # 273-280

    async def _publish_event(self, stream_key: str, *, kind: str,
                             run_id: str, node_id: str,
                             payload: Dict[str, Any]) -> None:# line 1077
        event = DispatchEvent(kind=kind, ts=time.time(), run_id=run_id,
                              node_id=node_id, payload=payload)  # ~line 1085
        _apply_to_session_host(event)                         # ~line 1097

    async def _publish_message_event(self, stream_key, message,
                                     run_id, node_id) -> None:# line 1116
        kind = "dispatch.message"                             # line 1135
        payload = {"message_class": type(message).__name__}   # lines 1136-1138
        # for block in content:  cls_name = type(block).__name__          # 1141-1142
        #   "ToolUseBlock"    -> kind = "dispatch.tool_use"               # 1145-1148
        #                        name = getattr(block, "name", None)
        #   "ToolResultBlock" -> kind = "dispatch.tool_result"            # 1149-1152
        #                        name = block.tool_use_id  ← THE BUG
        #   "TextBlock"       -> text_snippet = raw[:200]                 # 1153-1156
        # payload["tools"] = tool_names                                   # 1156-1157
        # payload["text"]  = text_snippet                                 # 1158-1159
        # if message.is_error: payload["is_error"]/"api_error_status"/
        #                      "result_text"                              # 1160-1164

    @staticmethod
    def _extract_result_error(messages) -> Optional[Dict[str, Any]]:  # line ~775
    @staticmethod
    def _extract_result_usage(messages) -> Optional[Dict[str, Any]]:  # line ~825
        # duck-types: usage / total_cost_usd / num_turns / duration_ms
```

### Does NOT Exist

- ~~an eager `claude_agent_sdk` import in this module~~ — the dispatcher
  **duck-types** every SDK object (see the comment at `claude.py:1011-1013`
  and `_extract_result_error`'s reverse-scan on `hasattr(msg, "is_error")`).
  Do **not** add an SDK import; keep using `type(block).__name__` string
  comparison and `getattr(..., default)`.
- ~~`ToolResultBlock.name`~~ — it has `tool_use_id`, `content` and
  `is_error`; the current code's `getattr(block, "name", None)` fallback at
  `claude.py:1151` never fires.
- ~~a `self._tool_names` instance dict~~ — must NOT be instance state; one
  dispatcher instance is shared across concurrent seats (the documented
  reason `session_host` is a ContextVar, `_shared.py:30-46`).
- ~~`DispatchEvent.labels`~~ — labels live inside `payload`.
- ~~a new `dispatch.*` kind for thinking blocks~~ — `ThinkingBlock` maps to
  `dispatch.message`, same as `TextBlock`.

---

## Implementation Notes

### The correlation map must be per-dispatch

Bind it in `dispatch()` next to the existing tokens, and read it in
`_publish_message_event`:

```python
_TOOL_NAMES_CTX: "contextvars.ContextVar[Optional[Dict[str, str]]]" = (
    contextvars.ContextVar("dev_loop_claude_tool_names", default=None)
)

# in dispatch(), beside _SESSION_HOST_CTX.set(...):
_tools_token = _TOOL_NAMES_CTX.set({})
_labels_token = bind_labels(labels)
# ... and reset BOTH on every path that resets _host_token (lines 231, 456)
```

A plain `dict` on `self` would cross-contaminate concurrent pool seats and
mislabel tool results — this is the single most important correctness
constraint in the task.

### Extractor sketch

```python
for block in content:
    cls_name = type(block).__name__
    if cls_name == "ToolUseBlock":
        kind = "dispatch.tool_use"
        name = getattr(block, "name", "") or ""
        tool_id = getattr(block, "id", "") or ""
        if name:
            payload["tool_name"] = name                    # ← the key session_state reads
            tool_names.append(name)
            if tool_id:
                (_TOOL_NAMES_CTX.get() or {})[tool_id] = name
            payload["tool_input"] = summarize_tool_input(
                name, getattr(block, "input", None))
    elif cls_name == "ToolResultBlock":
        kind = "dispatch.tool_result"
        tool_id = getattr(block, "tool_use_id", "") or ""
        name = (_TOOL_NAMES_CTX.get() or {}).get(tool_id, "")
        payload["tool_use_id"] = tool_id
        if name:
            payload["tool_name"] = name
            tool_names.append(name)
        if getattr(block, "is_error", False):
            payload["is_error"] = True
        payload["result_snippet"] = _snippet(getattr(block, "content", None))
    elif cls_name in ("TextBlock", "ThinkingBlock") and not text_snippet:
        text_snippet = (getattr(block, "text", "") or "")[:TEXT_MAX_CHARS]
```

`SystemMessage` enrichment (duck-typed, all `getattr` with defaults):
`subtype`, `model`, `cwd`, `session_id`, `len(tools)`, `len(mcp_servers)`.

`ResultMessage` enrichment on the **success** path too, not only on error:
`subtype`, `num_turns`, `duration_ms`, `total_cost_usd`. Reuse the duck-typing
style of `_extract_result_usage`.

### Key Constraints

- **Backward compatible**: keep emitting `tools` (the list) alongside the new
  `tool_name`. Existing tests that assert on `tools` must keep passing.
- **Unknown `tool_use_id`** (result arriving with no recorded use — possible
  on a resumed session) must degrade to a summary without a name, never crash.
- `text` clamped to `TEXT_MAX_CHARS`; `result_snippet` clamped likewise.
- Every `getattr` needs a default — the SDK is never imported, objects are
  duck-typed, and tests pass in hand-rolled doubles.
- Telemetry must never break a dispatch: the extractor body is wrapped so a
  malformed block degrades the payload instead of raising.

### References in Codebase

- `packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/claude.py:825-880` — `_extract_result_usage`, the duck-typing style to copy.
- `packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/llm.py:445-510` — the target payload shape (`tool_name` + args + result).
- `packages/ai-parrot/tests/flows/dev_loop/test_dual_publish.py:179-218` — how dispatch events are asserted today.

---

## Acceptance Criteria

- [ ] A `ToolUseBlock` named `"Read"` produces `payload["tool_name"] == "Read"` and a non-empty `payload["tool_input"]`.
- [ ] A `ToolResultBlock` whose `tool_use_id` matches an earlier `ToolUseBlock` reports that block's tool **name**; no payload contains a bare `toolu_…` value under `tool_name`.
- [ ] An unpaired `tool_use_id` degrades gracefully (no exception, summary still present).
- [ ] Two concurrent dispatches on the **same** dispatcher instance never cross-resolve tool ids.
- [ ] A `SystemMessage` payload carries `subtype`, `model` and `cwd` (when the message has them) and a summary that is not just the class name.
- [ ] A terminal `ResultMessage` carries `num_turns` and `duration_ms` on the **success** path.
- [ ] No payload published by this dispatcher has `message_class` as its only informative key.
- [ ] `ClaudeCodeDispatcher.dispatch` accepts `labels=` and binds/resets it on every exit path (success, timeout, validation error, exception).
- [ ] All tests pass: `pytest packages/ai-parrot/tests/flows/dev_loop/ -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/claude.py`

---

## Test Specification

```python
# packages/ai-parrot/tests/flows/dev_loop/test_claude_dispatcher_events.py
import asyncio
import pytest

from parrot.flows.dev_loop.dispatchers.claude import ClaudeCodeDispatcher


class ToolUseBlock:
    def __init__(self, name, id_, input_):
        self.name, self.id, self.input = name, id_, input_

class ToolResultBlock:
    def __init__(self, tool_use_id, content="ok", is_error=False):
        self.tool_use_id, self.content, self.is_error = tool_use_id, content, is_error

class TextBlock:
    def __init__(self, text): self.text = text

class AssistantMessage:
    def __init__(self, content): self.content = content

class UserMessage:
    def __init__(self, content): self.content = content

class SystemMessage:
    subtype = "init"; model = "claude-opus-5"; cwd = "/wt/feat-496"
    session_id = "s1"; tools = ["Read", "Bash"]; mcp_servers = []
    content = None


@pytest.fixture
def captured(monkeypatch):
    """Capture every (kind, payload) the dispatcher publishes."""
    events = []
    async def fake_publish(self, stream_key, *, kind, run_id, node_id, payload):
        events.append((kind, payload))
    monkeypatch.setattr(ClaudeCodeDispatcher, "_publish_event", fake_publish)
    return events


class TestClaudeEventExtraction:
    async def test_tool_use_emits_tool_name(self, captured):
        d = ClaudeCodeDispatcher()
        await d._publish_message_event(
            "k", AssistantMessage([ToolUseBlock("Read", "toolu_x", {"file_path": "a/foo.py"})]),
            "run-1", "development.w1")
        kind, p = captured[-1]
        assert kind == "dispatch.tool_use"
        assert p["tool_name"] == "Read"
        assert "foo.py" in p["tool_input"]

    async def test_tool_result_resolves_originating_name(self, captured):
        """The reported bug: toolu_01DJ... instead of a tool name."""
        d = ClaudeCodeDispatcher()
        await d._publish_message_event(
            "k", AssistantMessage([ToolUseBlock("Read", "toolu_x", {})]),
            "run-1", "development.w1")
        await d._publish_message_event(
            "k", UserMessage([ToolResultBlock("toolu_x")]), "run-1", "development.w1")
        kind, p = captured[-1]
        assert kind == "dispatch.tool_result"
        assert p["tool_name"] == "Read"
        assert not str(p.get("tool_name", "")).startswith("toolu_")

    async def test_unknown_tool_use_id_degrades(self, captured):
        d = ClaudeCodeDispatcher()
        await d._publish_message_event(
            "k", UserMessage([ToolResultBlock("toolu_missing")]), "run-1", "n")
        _, p = captured[-1]
        assert p["summary"]

    async def test_system_message_is_enriched(self, captured):
        d = ClaudeCodeDispatcher()
        await d._publish_message_event("k", SystemMessage(), "run-1", "n")
        _, p = captured[-1]
        assert p["model"] == "claude-opus-5"
        assert p["cwd"] == "/wt/feat-496"
        assert set(p) != {"message_class"}

    async def test_no_payload_is_only_a_class_name(self, captured):
        """FEAT-496 AC1, asserted over a realistic message sequence."""
        d = ClaudeCodeDispatcher()
        for msg in [SystemMessage(),
                    AssistantMessage([TextBlock("working")]),
                    AssistantMessage([ToolUseBlock("Bash", "t1", {"command": "pytest"})]),
                    UserMessage([ToolResultBlock("t1")])]:
            await d._publish_message_event("k", msg, "run-1", "n")
        for _kind, p in captured:
            assert set(p) - {"message_class"}, f"uninformative payload: {p}"
            assert p["summary"]

    async def test_correlation_map_is_per_dispatch(self):
        """Concurrent seats on ONE dispatcher instance must not cross-resolve."""
        # bind two separate tool maps in two tasks; assert isolation
        ...
```

---

## Agent Instructions

1. **Read the spec** — §1 root causes 1-3, §2 "Layer 3", §3 Module 3, §7 "Concurrency".
2. **Check dependencies** — TASK-2723 must be in `sdd/tasks/completed/`.
3. **Verify the Codebase Contract** — re-read `claude.py:1116-1175` and `:170-235` before editing; this file churns.
4. **Update status** in the per-spec index → `"in-progress"`.
5. **Implement**. Keep the SDK un-imported — duck-type everything.
6. **Verify** all acceptance criteria, especially the concurrency one.
7. **Move this file** to `sdd/tasks/completed/`.
8. **Update index** → `"done"`.
9. **Fill in the Completion Note** below.

---

## Completion Note

**Completed by**: sdd-worker (Claude)
**Date**: 2026-09-02
**Notes**: Rewrote `_publish_message_event` to walk content blocks via a new
`_extract_message_blocks` static method: `ToolUseBlock` → `tool_name` +
`tool_input` digest (plus recording `tool_use_id -> tool_name` into a
per-dispatch `_TOOL_NAMES_CTX` correlation map, mirroring `_SESSION_HOST_CTX`
exactly — bound/reset alongside it in `dispatch()`, on both the pre-semaphore
`except` path and the `finally`); `ToolResultBlock` resolves through that
map, plus `is_error` and a clamped `result_snippet` via a new `_snippet`
helper. `SystemMessage`/`ResultMessage` enrichment (`subtype`, `model`, `cwd`,
`session_id`, `tool_count`, `mcp_server_count`, `num_turns`, `duration_ms`,
`total_cost_usd`) now runs unconditionally via duck-typed `getattr` — no SDK
import added. `_publish_event` now routes every payload through
`normalize_payload`. `dispatch()` accepts `labels: Optional[DispatchLabels]
= None`. Kept emitting the legacy `tools` list alongside the new `tool_name`
for backward compatibility. 7 new tests pass (including a per-dispatch
correlation-isolation test using two concurrent seats with the SAME
`tool_use_id` to prove no cross-talk); full `dev_loop` suite green (98 total
claude/dual_publish tests plus the same 3 pre-existing unrelated failures in
`test_recovery_lifecycle.py`).

**Deviations from spec**: none

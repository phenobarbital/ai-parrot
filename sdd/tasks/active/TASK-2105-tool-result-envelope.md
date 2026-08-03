# TASK-2105: Correct tool execution timing, argument parsing and result envelope

**Feature**: FEAT-408 — Nova Sonic Protocol Fidelity
**Spec**: `sdd/specs/nova-sonic-protocol-fidelity.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-2104
**Assigned-to**: unassigned

---

## Context

Implements spec Module 6 (gaps 2, 3, 4). With TASK-2104 declaring
`toolConfiguration`, Nova will start emitting `toolUse` — and the existing
handling is wrong in three independent ways:

1. **Timing** — parrot executes on the `toolUse` frame. The sample waits for
   `contentEnd` with `type == "TOOL"` (`nova_sonic_tool_use.py:649-652`).
2. **Arguments** — `toolUse.content` is a **JSON string**; the sample does
   `json.loads(tool_content.get("content"))` (`:103-104`). Parrot passes it
   straight to `_execute_tool(name, input)` as if it were a kwargs dict.
3. **Result envelope** — the result requires **three** frames
   (`:261-285`, `:381-390`, `:719-721`):
   `contentStart{type:"TOOL", role:"TOOL", interactive:false,
   toolResultInputConfiguration:{toolUseId, type:"TEXT", textInputConfiguration}}`
   → `toolResult{promptName, contentName, content}` → `contentEnd`.
   Parrot sends a single `toolResult` and puts `toolUseId` in it where
   `contentName` belongs.

---

## Scope

- On `toolUse`: stash the call into `_TurnState.pending_tool` /
  `pending_tool_raw_input` (fields declared by TASK-2102). **Do not execute.**
- On `contentEnd` with `type == "TOOL"`: parse the stashed content with
  `json.loads` into a kwargs dict, execute via `self._execute_tool(name, args)`,
  then send the three-frame envelope through a new
  `_send_tool_result(stream, prompt_name, tool_use_id, result)`.
- Malformed or non-object `content` → report a tool error (populate
  `LiveToolCall.error`) and still send a well-formed result envelope. Never crash
  the turn.
- Preserve the existing `LiveToolCall` bookkeeping: `execution_time_ms`,
  `usage.tool_calls_executed`, `usage.tool_execution_time_ms`, the immediate
  per-call `LiveVoiceResponse`, and the accumulated `tool_calls` on the terminal
  frame.
- Tests for all three defects, each as a named regression.

**NOT in scope**: declaring `toolConfiguration` (TASK-2104); changing
`_execute_tool`'s signature; parallel/concurrent tool execution (the sample runs
tools as background tasks — parrot stays sequential for now; note it in the
Completion Note as a possible follow-up).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/clients/nova/audio.py` | MODIFY | Timing, parsing, `_send_tool_result()` |
| `packages/ai-parrot/tests/clients/test_nova_tool_result.py` | CREATE | Regression tests for gaps 2/3/4 |

---

## Codebase Contract (Anti-Hallucination)

> Line numbers verified on branch `fix/nova-sonic-bidirectional-sdk` @ `89204b9f0`.
> TASK-2102 restructured the receive loop — **re-read before editing.**

### Verified Imports

```python
from parrot.clients.nova import NovaClient        # verified: clients/nova/__init__.py:10
from parrot.clients.live import LiveToolCall      # verified: clients/live.py:128
# already imported at the top of nova/audio.py — do not re-add:
#   json, uuid, time
#   from ..live import LiveCompletionUsage, LiveToolCall, LiveVoiceResponse, VoiceTurnMetadata
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/clients/live.py
@dataclass
class LiveToolCall:                               # line 128
    id: str
    name: str
    arguments: Dict[str, Any]
    result: Optional[Any] = None
    error: Optional[str] = None
    execution_time_ms: float = 0.0
    def to_dict(self) -> Dict[str, Any]: ...

# packages/ai-parrot/src/parrot/clients/nova/audio.py — the code to RESTRUCTURE
tool_use = event.get("toolUse")                    # line 522
if tool_use:
    tool_name = tool_use.get("toolName")
    tool_input = tool_use.get("content", {})       # ← a JSON STRING, not a dict
    tool_use_id = tool_use.get("toolUseId", str(uuid.uuid4()))   # line 526
    tc = LiveToolCall(id=tool_use_id, name=tool_name, arguments=tool_input)
    start = time.monotonic()
    try:
        result = await self._execute_tool(tool_name, tool_input)  # line 531 — too early
        tc.result = result
    except Exception as exc:
        tc.error = str(exc); result = str(exc)
    tc.execution_time_ms = (time.monotonic() - start) * 1000
    tool_calls_list.append(tc)
    usage.tool_calls_executed += 1
    usage.tool_execution_time_ms += tc.execution_time_ms
    await self._send_event(stream, {"event": {"toolResult": {   # ← wrong envelope
        "promptName": prompt_name,
        "toolUseId": tool_use_id,                  # ← should be contentName
        "content": str(result),
    }}})
    yield LiveVoiceResponse(text="", tool_calls=[tc], is_complete=False, ...)

async def _send_event(self, stream, event: Dict[str, Any]) -> None: ...   # line 234

# Declared by TASK-2102, to be used here:
@dataclass
class _TurnState:
    pending_tool: Optional[LiveToolCall] = None
    pending_tool_raw_input: Optional[str] = None
```

### Frame shapes `_iter_events()` yields (already envelope-unwrapped)

```python
{"toolUse": {"toolName": "get_weather", "toolUseId": "tu_1",
             "content": '{"location": "Miami"}'}}     # content is a JSON STRING
{"contentEnd": {"type": "TOOL"}}                      # ← execute HERE
```

### Does NOT Exist

- ~~`toolResult.toolUseId`~~ — the `toolResult` frame takes `promptName`,
  `contentName`, `content`. `toolUseId` belongs in the **`contentStart`**'s
  `toolResultInputConfiguration`. This inversion is the bug.
- ~~a single-frame tool result~~ — three frames are required, in order.
- ~~`toolUse.content` as a dict~~ — it is a JSON string.
- ~~`toolUse.input` / `toolUse.arguments` / `toolUse.name`~~ — the keys are
  `content`, `toolUseId`, `toolName`.
- ~~`self._execute_tool(name, json_string)`~~ — it expects parsed kwargs.
  Verify its real signature before calling.
- ~~`event["event"]["toolUse"]`~~ — `_iter_events()` already unwraps.

---

## Implementation Notes

### Pattern to Follow

```python
    async def _send_tool_result(
        self, stream: Any, prompt_name: str, tool_use_id: str, result: Any
    ) -> None:
        """Send a tool result as the three-frame sequence Nova requires.

        contentStart(TOOL) -> toolResult -> contentEnd. ``toolUseId`` is carried
        on the contentStart's ``toolResultInputConfiguration``; the toolResult
        frame itself is keyed by ``contentName``.
        """
        content_name = str(uuid.uuid4())
        await self._send_event(stream, {"event": {"contentStart": {
            "promptName": prompt_name,
            "contentName": content_name,
            "interactive": False,
            "type": "TOOL",
            "role": "TOOL",
            "toolResultInputConfiguration": {
                "toolUseId": tool_use_id,
                "type": "TEXT",
                "textInputConfiguration": {"mediaType": "text/plain"},
            },
        }}})
        content = result if isinstance(result, str) else json.dumps(result)
        await self._send_event(stream, {"event": {"toolResult": {
            "promptName": prompt_name,
            "contentName": content_name,
            "content": content,
        }}})
        await self._send_event(stream, {"event": {"contentEnd": {
            "promptName": prompt_name,
            "contentName": content_name,
        }}})
```

Argument parsing must be defensive:

```python
def _parse_tool_arguments(raw: Any) -> Dict[str, Any]:
    """Parse a toolUse content payload into kwargs for _execute_tool().

    Nova sends this as a JSON string. Raises ValueError for anything that does
    not decode to a JSON object, so the caller can report a tool error.
    """
    if isinstance(raw, dict):
        return raw                       # tolerate an already-parsed payload
    parsed = json.loads(raw or "{}")     # ValueError on malformed input
    if not isinstance(parsed, dict):
        raise ValueError(f"tool arguments must be a JSON object, got {type(parsed).__name__}")
    return parsed
```

### Key Constraints

- The `contentEnd` handler must distinguish `type == "TOOL"` from ordinary
  `contentEnd` frames, which close text/audio content blocks and must be ignored
  here.
- Clear `pending_tool`/`pending_tool_raw_input` after handling, so a second tool
  call in the same turn cannot reuse stale state.
- A `contentEnd(TOOL)` with no pending tool must be ignored, not raise.
- Keep `usage.tool_calls_executed` / `tool_execution_time_ms` accounting and both
  `LiveVoiceResponse` emissions (immediate per-call, and accumulated on terminal)
  exactly as they are today — `test_nova.py::test_stream_voice_tool_use` asserts
  two frames carry `tool_calls`, and that must keep holding.
- **`test_nova.py::test_stream_voice_tool_use` will need updating**: it currently
  feeds `{"toolUse": {...}}` followed immediately by `{"completionEnd": {}}` and
  expects execution. Under the corrected timing it must feed a
  `{"contentEnd": {"type": "TOOL"}}` frame. Update it as part of this task.

### References in Codebase

- `nova_sonic_tool_use.py` (AWS sample): `:261-285` TOOL contentStart template,
  `:381-390` toolResult builder, `:644-652` receive-side timing, `:719-721` send
  order, `:103-104` content parsing.
- `packages/ai-parrot/tests/clients/test_nova.py::test_stream_voice_tool_use` —
  the existing test to update.

---

## Acceptance Criteria

- [ ] `_execute_tool` is **not** called on the `toolUse` frame.
- [ ] `_execute_tool` **is** called on `contentEnd` with `type == "TOOL"`.
- [ ] A JSON-string `content` is parsed into a dict and passed as the tool's
      arguments.
- [ ] The result is sent as exactly three frames in order: `contentStart`(TOOL) →
      `toolResult` → `contentEnd`.
- [ ] The `contentStart` carries `toolUseId` inside
      `toolResultInputConfiguration`; the `toolResult` carries `contentName` and
      **not** `toolUseId`.
- [ ] Malformed `content` yields a `LiveToolCall.error`, still sends a
      well-formed envelope, and the turn continues to `completionEnd`.
- [ ] `contentEnd(TOOL)` with no pending tool is ignored without raising.
- [ ] Ordinary (non-TOOL) `contentEnd` frames do not trigger execution.
- [ ] `usage.tool_calls_executed` and `tool_execution_time_ms` still accumulate;
      two frames still carry `tool_calls` (immediate + terminal).
- [ ] `test_nova.py::test_stream_voice_tool_use` updated to the corrected frame
      sequence and passing.
- [ ] All existing tests pass: `pytest packages/ai-parrot/tests/clients/ -k "nova or bedrock" -q`
- [ ] No AWS access required.

---

## Test Specification

```python
# packages/ai-parrot/tests/clients/test_nova_tool_result.py
import json
import pytest
from unittest.mock import AsyncMock, patch

from parrot.clients.nova import NovaClient

TOOL_USE = {"toolUse": {"toolName": "get_weather", "toolUseId": "tu_1",
                        "content": '{"location": "Miami"}'}}
TOOL_END = {"contentEnd": {"type": "TOOL"}}
TEXT_END = {"contentEnd": {"type": "TEXT"}}
END = {"completionEnd": {}}


async def _run(frames, execute=None):
    client = NovaClient(model="nova-2-sonic", region="us-east-1")
    sent = []

    async def capture(_stream, event):
        sent.append(event)

    async def iter_events(_stream):
        for f in frames:
            yield f

    async def audio():
        yield b"\x00\x01" * 8
        yield None

    execute = execute or AsyncMock(return_value="Sunny, 25C")
    with patch.object(client, "_open_stream", return_value=AsyncMock()), \
         patch.object(client, "_send_event", new=capture), \
         patch.object(client, "_iter_events", new=iter_events), \
         patch.object(client, "_close_stream", new=AsyncMock()), \
         patch.object(client, "_execute_tool", new=execute):
        out = [r async for r in client.stream_voice(audio())]
    return out, sent, execute


def _frames(sent, name):
    return [e["event"][name] for e in sent if name in e.get("event", {})]


class TestToolTiming:
    @pytest.mark.asyncio
    async def test_not_executed_on_tool_use_frame(self):
        _, _, execute = await _run([TOOL_USE])
        execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_executed_on_tool_content_end(self):
        _, _, execute = await _run([TOOL_USE, TOOL_END, END])
        execute.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_text_content_end_does_not_execute(self):
        _, _, execute = await _run([TOOL_USE, TEXT_END])
        execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_tool_content_end_without_pending_tool_is_ignored(self):
        out, _, execute = await _run([TOOL_END, END])
        execute.assert_not_called()
        assert out[-1].is_complete is True


class TestToolArguments:
    @pytest.mark.asyncio
    async def test_json_string_content_parsed_to_kwargs(self):
        _, _, execute = await _run([TOOL_USE, TOOL_END, END])
        name, args = execute.await_args[0]
        assert name == "get_weather"
        assert args == {"location": "Miami"}

    @pytest.mark.asyncio
    async def test_malformed_content_reported_as_tool_error(self):
        bad = {"toolUse": {"toolName": "get_weather", "toolUseId": "tu_1",
                           "content": "not json{"}}
        out, sent, execute = await _run([bad, TOOL_END, END])
        execute.assert_not_called()
        errored = [tc for r in out for tc in r.tool_calls if tc.error]
        assert errored, "expected a LiveToolCall with an error set"
        assert _frames(sent, "toolResult"), "must still send a result envelope"


class TestToolResultEnvelope:
    @pytest.mark.asyncio
    async def test_three_frames_in_order(self):
        _, sent, _ = await _run([TOOL_USE, TOOL_END, END])
        names = [n for e in sent for n in e.get("event", {})]
        i = names.index("toolResult")
        assert names[i - 1] == "contentStart"
        assert names[i + 1] == "contentEnd"

    @pytest.mark.asyncio
    async def test_tool_use_id_on_content_start_not_tool_result(self):
        _, sent, _ = await _run([TOOL_USE, TOOL_END, END])
        result = _frames(sent, "toolResult")[0]
        assert "toolUseId" not in result
        assert "contentName" in result
        tool_starts = [c for c in _frames(sent, "contentStart")
                       if c.get("type") == "TOOL"]
        assert tool_starts[0]["toolResultInputConfiguration"]["toolUseId"] == "tu_1"
        assert tool_starts[0]["role"] == "TOOL"
        assert tool_starts[0]["interactive"] is False

    @pytest.mark.asyncio
    async def test_content_name_matches_across_three_frames(self):
        _, sent, _ = await _run([TOOL_USE, TOOL_END, END])
        tool_start = [c for c in _frames(sent, "contentStart")
                      if c.get("type") == "TOOL"][0]
        result = _frames(sent, "toolResult")[0]
        assert result["contentName"] == tool_start["contentName"]
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify TASK-2104 is in `sdd/tasks/completed/`
   (without `toolConfiguration`, none of this is reachable in production)
3. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm `self._execute_tool`'s real signature before calling it
   - Confirm `_TurnState` has the two pending-tool fields (TASK-2102)
   - Re-locate the `toolUse` branch, which TASK-2102 restructured
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
4. **Update status** in `sdd/tasks/index/nova-sonic-protocol-fidelity.json` → `"in-progress"` with your session ID
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met — including the updated
   `test_nova.py::test_stream_voice_tool_use`
7. **Move this file** to `sdd/tasks/completed/TASK-2105-tool-result-envelope.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any

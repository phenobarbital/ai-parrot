# TASK-2148: Parallel Tool Execution

**Feature**: FEAT-416 — Voice Agent Framework
**Spec**: `sdd/specs/voice-agent-framework.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-2146
**Assigned-to**: unassigned

---

## Context

Both `GeminiLiveClient` and `NovaAudio` execute tool calls sequentially
during voice turns. Nova 2 Sonic supports parallel tool calling (multiple
`toolUse` events in one turn), but results must all be sent back before
the model resumes. Sequential execution adds unnecessary latency for
independent tools (e.g., 2 tools × 100ms = 200ms serial vs ~100ms
parallel).

This task adds `asyncio.TaskGroup`-based concurrent tool execution, gated
by a `parallel_tool_execution` config flag.

Implements spec §3 Module 4.

---

## Scope

- **Nova (`nova/audio.py`)**: In the `stream_voice()` event loop, collect
  all `toolUse` contentEnd events that arrive before the next non-tool
  event. When `parallel_tool_execution=True`, execute them concurrently
  with `asyncio.TaskGroup` and send all results. When `False`, keep
  current sequential behavior.
- **Gemini (`live.py`)**: In the tool-handling path of `stream_voice()`,
  collect multiple `function_call` parts from a single `model_turn` and
  execute concurrently when the flag is set.
  **Note**: verify whether Google SDK actually sends multiple
  `function_call` parts in one turn. If it does not, the parallel path
  is a no-op for Gemini (still correct — the TaskGroup just runs one
  task).
- Write tests proving parallel execution is faster than sequential for
  two independent tools.

**NOT in scope**: modifying ToolManager (parallel execution is at the
client level), modifying VoiceBot or VoiceConfig (done in other tasks).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/clients/nova/audio.py` | MODIFY | Parallel tool dispatch in stream_voice() |
| `parrot/clients/live.py` | MODIFY | Parallel tool dispatch in stream_voice() |
| `tests/clients/test_parallel_tool_execution.py` | CREATE | Timing-based parallel vs sequential tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from parrot.clients.nova.audio import NovaAudio       # verified: nova/audio.py:245
from parrot.clients.live import GeminiLiveClient       # verified: live.py:488
from parrot.clients.live import LiveToolCall            # verified: live.py:117
from parrot.clients.live import LiveVoiceResponse      # verified: live.py:156
```

### Existing Signatures to Use

```python
# parrot/clients/nova/audio.py:869 — current sequential tool execution
result = await self._execute_tool(pending.name, args)

# parrot/clients/nova/audio.py:563 — sends tool result back to Nova
async def _send_tool_result(
    self, stream: Any, prompt_name: str, tool_use_id: str, result: Any
) -> None: ...

# parrot/clients/base.py:1415 — the tool execution method
async def _execute_tool(
    self,
    tool_name: str,
    parameters: Dict[str, Any],
    tool_context: Optional[Dict[str, Any]] = None,
) -> Any: ...

# parrot/clients/live.py:373 — Gemini tool execution (LiveToolAdapter)
async def execute_tool(
    self,
    function_call: Any,
    context: Optional[Dict[str, Any]] = None,
) -> tuple[types.FunctionResponse, Optional[Dict[str, Any]]]: ...

# parrot/clients/nova/audio.py:127 — _TurnState dataclass
@dataclass
class _TurnState:
    role: Optional[str] = None
    generation_stage: Optional[str] = None
    pending_tool: Optional[LiveToolCall] = None
    pending_tool_raw_input: Optional[str] = None
```

### Does NOT Exist

- ~~`ToolManager.execute_tools_parallel()`~~ — no parallel method on ToolManager
- ~~`NovaAudio._execute_tools_batch()`~~ — no such method
- ~~`GeminiLiveClient._execute_tools_parallel()`~~ — no such method

---

## Implementation Notes

### Nova Pattern

The current flow at lines ~860-895:
1. Detect `contentEnd` with `type=TOOL` → `pending_tool` is fully assembled
2. Parse arguments, execute via `self._execute_tool()` sequentially
3. Send result via `_send_tool_result()`
4. Yield `LiveVoiceResponse` with tool call info

For parallel: accumulate `pending_tool` entries in a list until the next
non-tool event or completionEnd. Then dispatch all at once:

```python
if parallel_tool_execution and len(pending_tools) > 1:
    async with asyncio.TaskGroup() as tg:
        tasks = [
            tg.create_task(self._execute_tool(tool.name, tool.arguments))
            for tool in pending_tools
        ]
    # Send all results
    for tool, task in zip(pending_tools, tasks):
        tool.result = task.result()
        await self._send_tool_result(stream, prompt_name, tool.id, tool.result)
else:
    # Sequential (current behavior)
    ...
```

### Key Constraints

- The `parallel_tool_execution` flag comes through `**kwargs` (from
  VoiceConfig, wired in TASK-2151). Default `False` preserves current
  behavior.
- All tool results must be sent back **before** the model resumes — this
  is a Nova Sonic protocol requirement.
- If one tool raises, its error should be reported; other tools should
  still complete (use TaskGroup exception handling).

---

## Acceptance Criteria

- [ ] `parallel_tool_execution=True`: two 100ms tools complete in < 150ms wall-clock
- [ ] `parallel_tool_execution=False`: sequential behavior preserved
- [ ] Tool errors in parallel mode are reported per-tool (one failure doesn't kill others)
- [ ] All tool results sent back before model resumes
- [ ] All tests pass: `pytest tests/clients/test_parallel_tool_execution.py -v`

---

## Test Specification

```python
# tests/clients/test_parallel_tool_execution.py
import pytest
import asyncio
import time


class TestParallelToolExecution:
    @pytest.mark.asyncio
    async def test_parallel_faster_than_sequential(self):
        """Two 100ms tools execute in < 150ms with parallel=True."""
        # Mock two tools with 100ms sleep
        # Measure wall-clock with parallel_tool_execution=True
        # Assert < 150ms (not 200ms)

    @pytest.mark.asyncio
    async def test_sequential_default(self):
        """Two 100ms tools take ~200ms with parallel=False (default)."""
        # Same setup, parallel_tool_execution=False
        # Assert >= 180ms (sequential)

    @pytest.mark.asyncio
    async def test_parallel_error_isolation(self):
        """One failing tool doesn't prevent the other from completing."""
        # Mock: tool_a raises, tool_b succeeds
        # Assert tool_b result is sent, tool_a error is reported
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/voice-agent-framework.spec.md` §3 Module 4
2. **Check dependencies** — TASK-2146 done (for config flag)
3. **Read** `nova/audio.py` lines 860-895 to understand current tool flow
4. **Read** `live.py` tool handling in `stream_voice()` to understand Gemini flow
5. **Implement** parallel path gated on `parallel_tool_execution` kwarg
6. **Write tests** and verify timing assertions

---

## Completion Note

*(Agent fills this in when done)*

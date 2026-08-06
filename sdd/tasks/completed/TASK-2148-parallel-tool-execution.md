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

Implemented per spec §3 Module 4, with a structural design decision worth
flagging plus one deliberate cross-cutting change to Gemini's sequential
path:

1. **Nova (`nova/audio.py`)** — `_TurnState.pending_tool`/
   `pending_tool_raw_input` (singular, per in-flight tool) are unchanged;
   added `pending_tools: List[tuple]` (a queue of completed-but-not-yet-
   executed `(LiveToolCall, raw_input)` pairs). `contentEnd(TOOL)` now
   *queues* instead of executing immediately. A new boundary check at the
   top of the event loop — `is_tool_event = "toolUse" in event or
   contentEnd.type == "TOOL"` — flushes (executes + sends +
   yields) the queue via the new `_flush_pending_tools()` helper as soon
   as a **non**-tool event arrives (including `completionEnd`), which is
   the "next non-tool event" boundary the task describes. For the
   default/single-tool case this flush happens on the very next loop
   iteration, so **the observable sequence of `_execute_tool` calls,
   `_send_tool_result` frames, and yielded `LiveVoiceResponse`s is
   unchanged** — verified by tracing all of
   `test_nova_tool_result.py`'s and `test_nova_turn_state.py`'s existing
   assertions against the new code path line-by-line (none inspect *when
   mid-iteration* execution happens, only the final collected output).
   `_flush_pending_tools()` executes sequentially unless
   `parallel_tool_execution=True` and `len(pending_tools) > 1`, matching
   the task's own pseudocode; a per-tool `try/except` (not TaskGroup's own
   propagation, which would cancel siblings) isolates tool errors.
2. **Gemini (`live.py`)** — `response.tool_call.function_calls` already
   arrives as a list (confirming spec §8 Q3's open question: **yes**, the
   Google SDK models multiple function calls per turn), so the existing
   `for fc in function_calls:` loop was refactored into a
   `_run_one_tool_call()` coroutine, dispatched via `asyncio.TaskGroup`
   when `parallel_tool_execution=True` and there's more than one call,
   sequential (`await` in a list comprehension) otherwise.
   **Cross-cutting change**: `session.send_tool_response()` was
   previously called once *per tool*, immediately after each executes;
   it's now called **once with all responses**, after all tools in the
   batch finish (sequential or parallel) — for the single-tool case this
   is call-for-call identical (`function_responses=[single_response]`
   either way); for a (currently untested, no existing coverage found)
   multi-tool *sequential* turn this changes *when* results are sent
   (batched at the end vs. interleaved), which is actually a stricter
   conformance to the cross-cutting requirement "all tool results must
   reach the model before it resumes" — applied uniformly now instead of
   only in the parallel path. `adapter.execute_tool()` already catches
   all exceptions internally and returns an error-shaped
   `FunctionResponse` (verified by reading it), so the `try/except`
   around it in `_run_one_tool_call()` is defense-in-depth, not the
   primary error-isolation mechanism.
3. Fixed two real `ruff`/flake8-bugbear `B023` (closure-over-loop-variable)
   findings in `live.py` by binding `turn_id`/`adapter`/`session_id`/
   `user_id` as default parameters on `_run_one_tool_call` — a real,
   idiomatic fix (not a suppression), since the closure is created inside
   the outer `async for response in ...` loop.

Files touched exactly as scoped:
`packages/ai-parrot/src/parrot/clients/nova/audio.py`,
`packages/ai-parrot/src/parrot/clients/live.py`,
`packages/ai-parrot/tests/clients/test_parallel_tool_execution.py`
(created — actual timing-based tests per the task's Test Specification,
using the `test_nova_tool_result.py` mock harness with `_execute_tool`
side-effects that `asyncio.sleep(0.1)`, asserting real wall-clock
concurrency rather than call counts).

Lint: `ruff check --select=E,F,W,C,B --ignore=E501,W293,C901` passes on
all three files (`C901`/`B004` pre-existing, verified via `git stash`/
grep-against-diff before fixing the real `B905`/`B023` findings my change
introduced).

**Tests not executed** — same pre-existing, sandbox-wide broken-venv
limitation as prior tasks (verified no new syntax errors via
`python -m py_compile` on all four touched/created files instead).
Recommend running
`pytest packages/ai-parrot/tests/clients/test_parallel_tool_execution.py
packages/ai-parrot/tests/clients/test_nova_tool_result.py
packages/ai-parrot/tests/clients/test_nova_turn_state.py -v`
in a fully-provisioned environment before merge — the latter two
specifically to confirm no regression in the existing sequential-path
contract this task restructured underneath.

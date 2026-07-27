# TASK-1952: Wire the stage into `ToolManager.execute_tool()` + extend `AfterToolCallEvent`

**Feature**: FEAT-380 — Tool Result Compression Pipeline
**Spec**: `sdd/specs/tool-result-compression.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-1951
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 2 (integration half). This is the **only** place compression is
applied (G1): `ToolManager.execute_tool()` is the single choke point both
execution routes (`AbstractTool` and `ToolkitTool`) pass through, and the one
place where `tool_name`, the unserialized payload, `status` and `metadata` are
simultaneously available.

`manager.py` is the hot path of every agent in the framework. The edit must be
small, surgical, and behavior-preserving for every path that is not
compressing.

**Q1 is resolved and load-bearing**: the stage runs **after**
`_postprocess_result()` and `_run_result_hooks()`, which both keep observing
the ORIGINAL payload (so DataFrame auto-share keeps working unchanged). The
stage's output is what `execute_tool()` returns and what persists.

---

## Scope

- In `ToolManager.__init__`, lazily construct the compression stage
  (registry + budget router, both loaded once) and store it. Loading must not
  raise at import time; a manifest error surfaces at manager construction with
  the file path (per G: fail at startup, never at first tool call).
- In `execute_tool()`, at the verified fragment (manager.py:1490-1506): after
  `self._postprocess_result(...)` and `self._run_result_hooks(...)`, run the
  stage and return its output instead of the raw `out`.
- Merge the stage's compression metadata into the `ToolResult.metadata` /
  `meta` dict so the `_compressed` marker travels with the result into
  conversational memory.
- Pass `return_direct` from the tool instance (`getattr(tool, "return_direct",
  False)`) and `status` from the `ToolResult` (or `"success"` for the raw
  branch) into the stage.
- Extend `AfterToolCallEvent` (frozen dataclass → **new fields require
  defaults**) with: `compression_codec: str = ""`,
  `compression_level: str = ""`, `result_size_bytes_original: int = 0`,
  `compression_duration_ms: float = 0.0`, `compression_teed: bool = False`.
  Re-document `result_size_bytes` as the **post-compression** size.
- Populate the new fields wherever `AfterToolCallEvent` is emitted for a
  compressed call.
- Update `ToolManager.clone()`: the registry and stage config are shared **by
  reference**; per-session compression **metrics state is NOT cloned**. Extend
  the "Not cloned" docstring list (manager.py:1707-1712) accordingly.

**NOT in scope**:
- The `status == "error"` branch reorder and the tee → TASK-1953 (this task
  leaves `raise ValueError(result.error)` exactly where it is).
- `clients/live.py` → TASK-1956.
- `clients/google/client.py` → TASK-1961.
- The savings report → TASK-1957.
- The changelog entry for the `result_size_bytes` semantic change →
  TASK-1960 (this task only re-documents the field's docstring).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/tools/manager.py` | MODIFY | Stage construction in `__init__`; stage call in `execute_tool()`; `clone()` docstring + state list |
| `packages/ai-parrot/src/parrot/core/events/lifecycle/events/tool.py` | MODIFY | New `AfterToolCallEvent` fields (with defaults) + re-documented `result_size_bytes` |
| `packages/ai-parrot/tests/tools/compression/test_manager_integration.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: VERIFIED against HEAD `024c21d44` on 2026-07-27.
> **Path mapping**: `parrot/...` means `packages/ai-parrot/src/parrot/...`.
> A stale build copy exists at
> `packages/ai-parrot/build/lib.linux-x86_64-cpython-311/parrot/` — do NOT
> edit it and restrict every `grep` to `packages/ai-parrot/src/`.

### Verified Imports

```python
from parrot.tools.compression import CompressorRegistry
from parrot.tools.compression.budget import BudgetRouter
from parrot.tools.compression.stage import CompressionStage
from parrot.core.events.lifecycle.events import (
    BeforeToolCallEvent, AfterToolCallEvent, ToolCallFailedEvent,
)
# NOTE: `events` is a PACKAGE (core/events/lifecycle/events/), not events.py.
# Symbols live in events/tool.py and are re-exported by events/__init__.py.
# parrot/tools/abstract.py:22 already uses this exact import.
```

### Existing Signatures to Use

```python
# parrot/tools/manager.py:229
class ToolManager(MCPToolManagerMixin):
    self._result_hooks: List[Callable[[str, Any, Dict[str, Any]], None]] = []  # line 266
    self.auto_share_dataframes: bool = True                                     # line 272
    self.auto_push_to_pandas: bool = True                                       # line 273

async def execute_tool(                                                # line 1379
    self,
    tool_name: str,
    parameters: Dict[str, Any],
    permission_context: Optional["PermissionContext"] = None,
) -> Any: ...

def _postprocess_result(self, tool_name: str, out: Any, meta: Dict[str, Any]) -> None: ...  # line 1663
def clone(self, *, include_search_tool: bool = False) -> "ToolManager": ...                 # line 1697
def add_result_hook(self, fn: Callable[[str, Any, Dict[str, Any]], None]) -> None: ...      # line 1777
def _run_result_hooks(self, tool_name: str, result: Any, metadata: Dict[str, Any]) -> None: ...  # line 1781
```

**VERBATIM insertion point — `manager.py` lines 1490-1506:**

```python
result = await tool.execute(**exec_kwargs)

# Handle ToolResult objects
if isinstance(result, ToolResult):
    # Return forbidden results directly without post-processing
    if result.status == 'forbidden':
        return result                          # forbidden returns intact — leave alone
    if result.status == "error":
        raise ValueError(result.error)         # ← TASK-1953 reorders this, NOT you
    out = result.result
    meta = getattr(result, "metadata", {}) or {}
else:
    out = result
    meta = {}
self._postprocess_result(tool_name, out, meta)     # observes the ORIGINAL (Q1)
self._run_result_hooks(tool_name, out, meta)       # observes the ORIGINAL (Q1)
return out                                          # ← replace with the stage output
```

**`clone()` docstring — VERBATIM, manager.py:1707-1712, the list to extend:**

```
Not cloned (each user gets a fresh, independent copy):
    - ``_shared`` (dataframe registry)
    - ``_registered_agents`` (per-session agent bindings)
    - ``_result_hooks``
    - ``_wired_toolkits`` (auto-wire tracking)
    - MCP state initialised by ``_init_mcp``
```

**`AfterToolCallEvent` — VERBATIM, `parrot/core/events/lifecycle/events/tool.py`:**

```python
class BeforeToolCallEvent(LifecycleEvent):   # line 12
    tool_name: str = ""                      # line 24

class AfterToolCallEvent(LifecycleEvent):    # line 30
    tool_name: str = ""                      # line 42
    duration_ms: float = 0.0                 # line 43
    result_status: str = ""                  # line 44 — "success" | "partial"
    result_size_bytes: int = 0               # line 45 ← becomes POST-compression size

class ToolCallFailedEvent(LifecycleEvent):   # line 49
    tool_name: str = ""                      # line 61
    duration_ms: float = 0.0                 # line 62
```

`AfterToolCallEvent` is a `@dataclass(frozen=True)` over `navigator_eventbus`'s
`LifecycleEvent` — **every new field MUST have a default** or construction of
existing call sites breaks.

### Does NOT Exist

- ~~`ToolManager.add_result_hook` with a transforming return~~ — hooks return
  `None`. Do NOT repurpose `_result_hooks` as the compression chain; the
  acceptance criteria require that contract to stay untouched.
- ~~A second place in the codebase that truncates tool results~~ — only
  `parrot/clients/google/client.py` (`MAX_TOOL_RESULT_CHARS`, line 1197).
  `claude.py` / `groq.py` / `grok.py` have NO equivalent. After this task,
  `grep` must still find compression logic in exactly ONE place (G1).
- ~~`parrot/core/events/lifecycle/events.py` as a file~~ — `events` is a
  package; tool events live in `events/tool.py`.
- ~~A tee~~ — TASK-1953. The stage's tee callback stays `None` here.
- ~~`parrot/` at the repo root~~ — the package lives at
  `packages/ai-parrot/src/parrot/`.

---

## Implementation Notes

### Pattern to Follow

```python
# execute_tool(), replacing the final `return out` of the fragment above
self._postprocess_result(tool_name, out, meta)
self._run_result_hooks(tool_name, out, meta)

out, comp_meta = await self._compression_stage.run(
    tool_name, out,
    status=result.status if isinstance(result, ToolResult) else "success",
    metadata=meta,
    return_direct=getattr(tool, "return_direct", False),
)
meta.update(comp_meta)
return out
```

### Key Constraints

- **Do not change observable behavior for non-compressing paths.** The
  `forbidden` early return, the `error` raise, and the unknown-tool-type
  branch stay byte-identical.
- The stage must be constructed once per manager, not per call. Registry load
  happens at manager construction (or first use) — but a manifest error must
  surface with the file path, loudly, not be swallowed.
- `clone()`: share the registry/stage config by reference (schemas must stay
  identical across users); give the clone fresh metrics state so one user's
  circuit-breaker trip does not leak into another's session.
- Adding fields to a frozen dataclass without defaults is a runtime error at
  every existing construction site — defaults are mandatory, not stylistic.
- Keep `self.logger` usage consistent with the surrounding manager code.

### References in Codebase

- `parrot/tools/toolkit.py:390` `_post_execute()` — the transformer contract
  this stage call mirrors.
- `parrot/tools/abstract.py:22` — the verified events import line.

---

## Acceptance Criteria

- [ ] Compression applies on BOTH tool routes (`AbstractTool` and
      `ToolkitTool`) through this single call site (G1).
- [ ] `test_extraction_sees_original`: `_postprocess_result()` and result
      hooks receive the ORIGINAL payload; `execute_tool()` returns the
      compressed one (Q1).
- [ ] `test_after_tool_call_event_fields`: new fields populated;
      `result_size_bytes` is the post-compression size; the original is in
      `result_size_bytes_original`.
- [ ] `test_clone_does_not_share_metrics`: `clone()` shares the registry by
      reference, NOT metrics state; the docstring list is updated.
- [ ] `AfterToolCallEvent` constructs successfully with no new kwargs
      (defaults present) — existing call sites unbroken.
- [ ] `PARROT_COMPRESSION_DISABLED=1` → `execute_tool()` returns exactly what
      it returns today.
- [ ] `_result_hooks` signature and contract unchanged (`grep` proof).
- [ ] Existing manager tests still pass:
      `pytest packages/ai-parrot/tests/tools/ tests/manager/ -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/tools/manager.py packages/ai-parrot/src/parrot/core/events/lifecycle/events/tool.py`

---

## Test Specification

```python
# packages/ai-parrot/tests/tools/compression/test_manager_integration.py
import pytest
from parrot.core.events.lifecycle.events import AfterToolCallEvent


def test_after_tool_call_event_new_fields_have_defaults():
    """Frozen dataclass: existing construction sites must keep working."""
    evt = AfterToolCallEvent(tool_name="t", duration_ms=1.0,
                             result_status="success", result_size_bytes=10)
    assert evt.compression_codec == ""
    assert evt.result_size_bytes_original == 0
    assert evt.compression_duration_ms == 0.0
    assert evt.compression_teed is False


class TestStagePlacement:
    async def test_extraction_sees_original(self, tool_manager_with_compression):
        """Q1: hooks observe the ORIGINAL; the return value is compressed."""
        seen = []
        tool_manager_with_compression.add_result_hook(
            lambda name, result, meta: seen.append(result)
        )
        out = await tool_manager_with_compression.execute_tool("bulky_tool", {})
        assert seen and seen[0] is not out          # hook saw the pre-compression object
        assert out != seen[0]                        # and the caller got the compressed one

    async def test_both_tool_routes(self, tool_manager_with_compression):
        """G1: identical treatment for AbstractTool and ToolkitTool."""
        ...

    async def test_kill_switch_restores_behavior(self, tool_manager_with_compression,
                                                 monkeypatch):
        monkeypatch.setenv("PARROT_COMPRESSION_DISABLED", "1")
        out = await tool_manager_with_compression.execute_tool("bulky_tool", {})
        assert out == EXPECTED_UNCOMPRESSED


class TestClone:
    def test_clone_does_not_share_metrics(self, tool_manager_with_compression):
        clone = tool_manager_with_compression.clone()
        assert clone._compression_stage._registry is \
            tool_manager_with_compression._compression_stage._registry
        assert clone._compression_stage._router is not \
            tool_manager_with_compression._compression_stage._router


def test_result_hooks_contract_untouched():
    import inspect
    from parrot.tools.manager import ToolManager
    sig = inspect.signature(ToolManager.add_result_hook)
    assert list(sig.parameters) == ["self", "fn"]
```

---

## Agent Instructions

1. **Read the spec** (§2 overview + Q1, §3 Module 2, §6 integration points).
2. **Check dependencies** — TASK-1951 must be in `sdd/tasks/completed/`.
3. **Verify the Codebase Contract** — re-read `manager.py:1490-1506` and
   `events/tool.py:30-45` BEFORE editing; if the line anchors have drifted,
   update this contract first, then implement.
4. **Update status** in `sdd/tasks/index/tool-result-compression.json`.
5. **Implement** per scope. Leave the `status == "error"` branch alone.
6. **Verify** acceptance criteria — run the broader manager test suite, not
   just the compression tests. This is the framework hot path.
7. **Move this file** to `sdd/tasks/completed/`.
8. **Update index** → `"done"`.
9. **Fill in the Completion Note**.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none | describe if any

# TASK-2570: Adapters — `ToolManagerExecutor` and `ConversationMemorySurfaceStore`

**Feature**: FEAT-469 — A2UI Agent Functions Runtime (v1.0 RPC leg)
**Spec**: `sdd/specs/a2ui-agent-functions.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2569
**Assigned-to**: unassigned

---

## Context

Implements **spec §3 Module 3**. TASK-2569 left `A2UIRuntime` talking to three
`Protocol`s; this task supplies the two real implementations that bind them to
ai-parrot's tool and memory subsystems:

- `ToolManagerExecutor` — wraps `ToolManager.execute_tool(...)`, always passing
  `permission_context=` (spec **G7**: the user's `PermissionContext` is the
  *only* authorization barrier, since §8 resolved "all ToolManager tools are
  invocable").
- `ConversationMemorySurfaceStore` — implements **both** `SurfaceStateStore` and
  `PendingCallRegistry` over `ConversationHistory.metadata`, because there is no
  metadata API on `ConversationMemory` (see contract) and both pieces of state
  are session-scoped.

These live *inside* `runtime/` but must keep the **G8 one-way import rule**
intact by importing `parrot.tools` / `parrot.memory` **lazily, inside methods**.

---

## Scope

- Implement `ToolManagerExecutor` (`call`, `list_functions`).
- Implement `ConversationMemorySurfaceStore` (`get`/`put`/`delete` + `add`/`resolve`)
  over `metadata["a2ui_surfaces"]` and `metadata["a2ui_pending_calls"]`, with
  TTL expiry on pending calls.
- Extend the existing import-rule test to cover `runtime/`.
- Unit tests with a real `FileConversationMemory`.

**NOT in scope**: `export_functions` / UAX #31 sanitization (TASK-2571 — but see
the note below on where `list_functions` stops), any transport, `a2ui_hidden`
filtering at the catalog level (TASK-2571).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/outputs/a2ui/runtime/adapters.py` | CREATE | Both adapters |
| `packages/ai-parrot/tests/outputs/a2ui/adapters/test_import_rule.py` | MODIFY | Extend to `runtime/` |
| `packages/ai-parrot/tests/outputs/a2ui/runtime/test_adapters.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

> Verified on `dev` @ `ce716a032` (2026-08-29).

### Verified Imports (all LAZY — inside methods, never module level)
```python
# inside a method body:
from parrot.tools.manager import ToolManager          # tools/manager.py:233
from parrot.tools.abstract import ToolResult          # tools/abstract.py:200
from parrot.memory.abstract import (                  # memory/abstract.py
    ConversationMemory,     # 135
    ConversationHistory,    # 51
)
```
Module level is fine for these (no agent stack):
```python
from parrot.outputs.a2ui.runtime.models import (
    A2UICallContext, FunctionCallRecord, SurfaceState,
)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/tools/manager.py
class ToolManager(MCPToolManagerMixin):                                  # 233
    _tools: Dict[str, Union[ToolDefinition, AbstractTool]]               # 273
    def get_tool_schemas(self, provider_format: ToolFormat = ToolFormat.GENERIC) -> List[Dict[str, Any]]:  # 1121
    def get_tool(self, tool_name: str) -> Optional[Any]:                 # 1215
    def list_tools(self) -> List[str]:                                   # 1235
    def get_tools(self) -> Dict[str, Any]:                               # 1239
    async def execute_tool(self, tool_name: str, parameters: Dict[str, Any],
                           permission_context: Optional["PermissionContext"] = None) -> Any:  # 1519

# packages/ai-parrot/src/parrot/memory/abstract.py
@dataclass
class ConversationHistory:                       # 51
    session_id: str                              # 53
    user_id: str                                 # 54
    chatbot_id: Optional[str] = None             # 55
    turns: List[ConversationTurn] = ...          # 56
    created_at: datetime = ...                   # 57
    updated_at: datetime = ...                   # 58
    metadata: Dict[str, Any] = field(default_factory=dict)   # 59  <-- the store
    def add_turn(self, turn) -> None: ...        # 61

class ConversationMemory(ABC):                   # 135
    async def create_history(...)                # 146
    async def get_history(...)                   # 157
    async def update_history(self, history: ConversationHistory) -> None:  # 167
    async def add_turn(...)                      # 172
    async def clear_history(...)                 # 183
    async def list_sessions(...)                 # 193
    async def delete_history(...)                # 202
```

### Critical behaviours verified in `execute_tool` (manager.py:1519)
```python
if tool_name not in self._tools:
    return ToolResult(success=False, status='not_found',
                      error=f"Tool '{tool_name}' not found", result=None)   # ~1523-1528
```
- A **missing tool returns a `ToolResult`, it does not raise** — despite the
  docstring's `Raises: ValueError`. Do not wrap the miss in try/except and
  invent a different code; pass the `ToolResult` straight through so
  TASK-2569's mapping turns `not_found` into `INVALID_FUNCTION_CALL`.
- `ToolDefinition`-backed tools (the `@tool` decorator path) **do not support
  permission enforcement** — the code says so explicitly at ~1530-1535 and
  calls `tool.function(**parameters)` directly, ignoring `permission_context`.
  This is a real **security gap for G7**: a `@tool` function is invokable via
  `callAgentFunction` with no permission check. **Log a warning** when
  dispatching to a `ToolDefinition` and record the gap in the completion note
  so it can be escalated — do not silently pretend it is enforced, and do not
  try to fix `ToolManager` in this task (out of scope).
- `execute_tool` is typed `-> Any`, not `-> ToolResult`: a `ToolDefinition`
  path returns the function's **raw return value**. Normalize to a `ToolResult`
  in the adapter so TASK-2569 always sees a consistent shape.

### Does NOT Exist
- ~~`ConversationMemory.get_metadata()` / `.set_metadata()`~~ — **no metadata API exists**. Use `get_history()` → mutate `history.metadata` → `update_history(history)`.
- ~~`ToolManager.get_function_definitions()`~~ / ~~`.list_functions()`~~ — not real. Use `get_tool_schemas()` (1121), `list_tools()` (1235), or `get_tools()` (1239).
- ~~`AbstractTool.a2ui_requires_user_activation` / `.a2ui_hidden`~~ — **not yet**; TASK-2571 adds them. Read them defensively with `getattr(tool, "a2ui_hidden", False)`.
- ~~a `ttl`/`expire` argument on `update_history`~~ — the signature is `(self, history)` only.
- ~~an atomic metadata update~~ — see the concurrency note below.

---

## Implementation Notes

### `ToolManagerExecutor`
```python
class ToolManagerExecutor:
    """FunctionExecutor over a ToolManager (spec G1/G7)."""
    def __init__(self, tool_manager: "ToolManager") -> None: ...

    async def call(self, name, args, ctx) -> "ToolResult":
        # ALWAYS pass permission_context — G7. Never omit it, never pass None
        # when ctx.permission_context is set.
        raw = await self._tm.execute_tool(name, args, permission_context=ctx.permission_context)
        return self._normalize(raw)     # -> ToolResult (see contract: execute_tool returns Any)

    def list_functions(self) -> list["FunctionDefinition"]: ...
```
Emit the **audit log line** required by spec §7 "Superficie de ataque" on every
call: `agent_id`, `user_id`, `call`, resulting `status`. This is the only
forensic record that a renderer invoked a tool.

`list_functions()` here returns catalog-side `FunctionDefinition`s built from
the tool schemas. Keep it **mechanical** — the UAX #31 sanitization, collision
detection and `a2ui_hidden` filtering all belong to TASK-2571's
`export_functions()`. If that split proves awkward, put the shared derivation in
`export.py` (TASK-2571) and have this method delegate; do **not** duplicate the
logic in two places.

### `ConversationMemorySurfaceStore`
One class implementing both Protocols. Layout inside `ConversationHistory.metadata`:
```python
metadata["a2ui_surfaces"]      = {surface_id: SurfaceState.model_dump(mode="json")}
metadata["a2ui_pending_calls"] = {function_call_id: FunctionCallRecord.model_dump(mode="json")}
```
- `put`/`add` are **read-modify-write**: `get_history` → mutate → `update_history`.
- `resolve` must treat an entry whose `created_at + ttl_seconds` is in the past
  as **absent** (return `None`) and drop it. Sweep expired entries on every
  access — spec §7 says cleanup is lazy, there is no reaper.
- `delete` removes one surface; it must not clobber `a2ui_pending_calls`.
- Use `model_dump(mode="json")` / `model_validate` so `datetime` round-trips
  through Redis and file JSON.

### Concurrency (spec §7 "Concurrencia en memoria" — flagged as unverified)
Read-modify-write on `metadata` races when two dispatches share a `session_id`.
The spec says "with Redis, use whatever atomic operation `RedisConversation`
offers, or a per-`session_id` lock — **verify in implementation**". Do that
verification: inspect `parrot/memory/redis.py` for a compare-and-set or
pipeline/WATCH primitive. If none exists, implement an `asyncio.Lock` keyed by
`session_id` inside the adapter and **document the limitation** (a lock is
per-process and does not protect multi-worker deployments) in the completion
note. Do not silently ship the unlocked version.

### Preserving G8
`adapters.py` sits under `runtime/` and *does* touch `parrot.tools` /
`parrot.memory`. Keep every such import **inside a method body** (or under
`if TYPE_CHECKING:` for annotations). The extended import-rule test enforces
this — it is the mechanism, not a formality.

### References in Codebase
- `tests/outputs/a2ui/adapters/test_import_rule.py` — the existing test to extend; copy its detection approach.
- `tests/outputs/a2ui/recipes/test_import_rule.py` — a second precedent of the same pattern.
- `knowledge/ontology/tool_dispatcher.py:195-214` — house style for building a `PermissionContext` and threading it to tools.
- `memory/file.py` (`FileConversationMemory`) — the test-friendly memory backend.

---

## Acceptance Criteria

- [ ] `ToolManagerExecutor.call` passes `permission_context=ctx.permission_context` to `execute_tool` on **every** call (asserted with a mock).
- [ ] A raw (non-`ToolResult`) return from a `ToolDefinition` tool is normalized into a `ToolResult`.
- [ ] Dispatching to a `ToolDefinition` logs a warning noting permissions are not enforced on that path.
- [ ] An audit log line with `agent_id`, `user_id`, `call`, `status` is emitted per invocation.
- [ ] `ConversationMemorySurfaceStore` round-trips a `SurfaceState` by `surface_id` through a real `FileConversationMemory`.
- [ ] An expired pending call does not resolve and is dropped; a live one resolves and returns its record.
- [ ] `delete()` removes only the named surface and leaves `a2ui_pending_calls` intact.
- [ ] Import-rule test passes: `runtime/` (including `adapters.py`) imports no `parrot.bots` / `parrot.clients` at module level.
- [ ] The Redis concurrency question is resolved in code (atomic op or documented lock), not left open.
- [ ] Tests pass: `pytest packages/ai-parrot/tests/outputs/a2ui/runtime packages/ai-parrot/tests/outputs/a2ui/adapters -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/outputs/a2ui/runtime`

---

## Test Specification

```python
# packages/ai-parrot/tests/outputs/a2ui/runtime/test_adapters.py
import pytest
from unittest.mock import AsyncMock

from parrot.outputs.a2ui.runtime.adapters import (
    ConversationMemorySurfaceStore, ToolManagerExecutor,
)
from parrot.outputs.a2ui.runtime.models import A2UICallContext, SurfaceState


class TestToolManagerExecutor:
    async def test_passes_permission_context(self, a2ui_call_ctx):
        tm = AsyncMock()
        await ToolManagerExecutor(tm).call("get_weather", {"location": "Caracas"}, a2ui_call_ctx)
        _, kwargs = tm.execute_tool.call_args
        assert kwargs["permission_context"] is a2ui_call_ctx.permission_context

    async def test_normalizes_raw_return_to_tool_result(self, a2ui_call_ctx):
        tm = AsyncMock(); tm.execute_tool.return_value = "plain string"
        res = await ToolManagerExecutor(tm).call("t", {}, a2ui_call_ctx)
        assert res.success is True and res.result == "plain string"

    async def test_not_found_tool_result_passes_through(self, a2ui_call_ctx):
        """execute_tool RETURNS not_found, it does not raise."""
        ...


class TestConversationMemorySurfaceStore:
    async def test_surface_roundtrip(self, memory_store):
        st = SurfaceState(surface_id="s-1", catalog_id="c", data_model={"a": 1},
                          updated_at=datetime.now(timezone.utc))
        await memory_store.put("sess-1", st)
        assert (await memory_store.get("sess-1", "s-1")).data_model == {"a": 1}

    async def test_pending_call_ttl_expiry(self, memory_store):
        """A record past created_at + ttl_seconds must not resolve."""
        ...

    async def test_delete_surface_keeps_pending_calls(self, memory_store): ...


def test_runtime_import_rule():
    """G8 — extends tests/outputs/a2ui/adapters/test_import_rule.py."""
    ...
```

---

## Agent Instructions

1. **Read the spec** — §3 Module 3, §7 ("Superficie de ataque", "Concurrencia en memoria"), and G7/G8.
2. **Check dependencies** — TASK-2569 in `sdd/tasks/completed/`.
3. **Verify the Codebase Contract** — re-read `execute_tool` (manager.py:1519) and
   re-confirm both the `not_found` return and the `ToolDefinition` permission
   bypass; re-confirm `ConversationMemory` still has no metadata API.
4. **Update status** in the index → `"in-progress"`.
5. **Implement** per scope, keeping every tools/memory import lazy.
6. **Resolve the Redis concurrency question** — do not leave it open.
7. **Verify** every acceptance criterion.
8. **Move this file** to `sdd/tasks/completed/`.
9. **Update index** → `"done"`, and note the `ToolDefinition` permission gap in the Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Redis concurrency resolution**: (atomic primitive found / asyncio.Lock + limitation)
**ToolDefinition permission gap**: (confirmed / mitigated / escalated)

**Deviations from spec**: none | describe if any

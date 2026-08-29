# TASK-2569: Protocols and `A2UIRuntime.dispatch`

**Feature**: FEAT-469 — A2UI Agent Functions Runtime (v1.0 RPC leg)
**Spec**: `sdd/specs/a2ui-agent-functions.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-2568
**Assigned-to**: unassigned

---

## Context

Implements **spec §3 Module 2** — the heart of the feature. `A2UIRuntime` is
pure protocol: it takes a deserialized renderer→agent envelope plus an
`A2UICallContext`, and returns a `DispatchResult` of already-serialized
agent→renderer envelopes. It knows nothing about HTTP, A2A, aiohttp, bots or
tools — everything it needs arrives through three injected `Protocol`s
(`FunctionExecutor`, `SurfaceStateStore`, `PendingCallRegistry`), whose concrete
adapters land in TASK-2570.

This split is what makes the whole RPC leg testable with fakes and is the
**G8 invariant** the spec repeats three times. Every transport (TASK-2572 A2A,
TASK-2573 HTTP, TASK-2574 deep links) is a thin shell over this one method.

---

## Scope

- Define the three `Protocol`s in `runtime/__init__.py`.
- Implement `A2UIRuntime` in `runtime/dispatch.py` with:
  - `dispatch(envelope, ctx) -> DispatchResult`
  - `call_renderer(session_id, surface_id, call, args, *, catalog_id=None) -> tuple[str, dict]`
- Envelope validation (exactly one message key; `version == "v1.0"`).
- `callAgentFunction` → catalog resolution → `allowedCallers` check → executor → `ToolResult` mapping.
- `action` → size-cap check → surface persistence → structured user turn.
- `rendererFunctionResponse` / `error` → `PendingCallRegistry.resolve`.
- Lazy expiry sweep of pending calls on every `dispatch`.
- Full unit-test suite against fakes.

**NOT in scope**: the concrete adapters (TASK-2570), the catalog `export_functions`
(TASK-2571), any transport (TASK-2572/2573/2574), `_a2ui_surface_state` tool
plumbing (TASK-2575).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/outputs/a2ui/runtime/__init__.py` | MODIFY | Add the three `Protocol`s; re-export `A2UIRuntime` |
| `packages/ai-parrot/src/parrot/outputs/a2ui/runtime/dispatch.py` | CREATE | `A2UIRuntime` |
| `packages/ai-parrot/tests/outputs/a2ui/runtime/conftest.py` | CREATE | `fake_executor`, `fake_surfaces`, `fake_pending`, `a2ui_call_ctx` fixtures |
| `packages/ai-parrot/tests/outputs/a2ui/runtime/test_dispatch.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

> Verified on `dev` @ `ce716a032` (2026-08-29).

### Verified Imports
```python
from parrot.outputs.a2ui.models import (
    A2UIRendererMessage,       # renderer->agent envelope wrapper
    ActionMessage,             # models.py:585  (+ .data_model from TASK-2567)
    CallAgentFunction,         # models.py:610
    RendererFunctionResponse,  # models.py:627
    ErrorMessage,              # models.py:639
    AgentFunctionResponse,     # models.py:575
    CallRendererFunction,      # models.py:521
    FunctionCallError,         # models.py:~540
)
from parrot.outputs.a2ui.serialization import serialize, deserialize  # serialization.py:104, :155
from parrot.outputs.a2ui.catalog.base import DEFAULT_CATALOG_ID       # catalog/base.py:52
from parrot.outputs.a2ui.runtime.models import (                       # TASK-2568
    A2UICallContext, A2UIErrorCode, DispatchResult, FunctionCallRecord,
    SurfaceState, error_envelope,
)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/outputs/a2ui/models.py
class CallAgentFunction(A2UIMessageBase):        # 610
    surface_id: str = Field(alias="surfaceId")           # REQUIRED
    function_call_id: str = Field(alias="functionCallId")
    call_function: FunctionCall = Field(alias="callFunction")

class CallRendererFunction(A2UIMessageBase):     # 521
    function_call_id: str = Field(alias="functionCallId")
    call_function: FunctionCall = Field(alias="callFunction")
    # NOTE: for THIS message callFunction.catalogId is REQUIRED by the official
    # schema (stricter than the shared FunctionCall model); enforced by
    # jsonschema, NOT by pydantic. call_renderer() MUST always set catalogId.

class _FunctionResponseBase(A2UIMessageBase):    # 554
    function_call_id: str; value: Any = None; error: FunctionCallError | None = None
    # model_validator: exactly one of value/error, keyed off model_fields_set

class FunctionCallError(A2UIMessageBase):        # ~540
    code: str
    message: str

# packages/ai-parrot/src/parrot/outputs/a2ui/catalog/__init__.py
def resolve_catalog(component_catalog_id: str | None, surface_catalog_id: str | None) -> str:  # 219
def get_function(name: str) -> FunctionDefinition:   # 191  (raises if unknown)
def list_functions() -> list[FunctionDefinition]:    # 200
def validate_message(message) -> None:               # 334
def validate_envelope(...)                           # 378

# packages/ai-parrot/src/parrot/outputs/a2ui/catalog/base.py:246
class FunctionDefinition(BaseModel):
    name: str; catalog_id: str; args_schema: dict[str, Any]
    return_type: str = "any"
    allowed_callers: Literal["rendererOnly", "agentOnly", "rendererOrAgent"] = "rendererOnly"
    requires_user_activation: bool = False
```

### `ToolResult` — the mapping source (do NOT re-model it)
```python
# packages/ai-parrot/src/parrot/tools/abstract.py:200
class ToolResult(BaseModel):
    success: bool = True          # 202
    status: str = "success"       # 203
    result: Any                   # 204
    error: str | None = None      # 205
    metadata: dict = {}           # 206
    timestamp: str                # 207
    files / images / voice_text / display_data   # 210-219
```
`runtime/` must **not** import `ToolResult` at module level (G8). Type it under
`TYPE_CHECKING` and duck-type at runtime (`.success`, `.status`, `.result`, `.error`).

### The renderer→agent envelope shape (verified in `renderer_to_agent.json`)
```
minProperties: 2, maxProperties: 2
oneOf: [ {required:[action,version]}, {required:[callAgentFunction,version]},
         {required:[rendererFunctionResponse,version]}, {required:[error,version]} ]
```
⇒ exactly `version` + **one** message key. There are only **four** legal R→A
message keys — `createSurface`, `updateComponents`, `updateDataModel`,
`deleteSurface`, `callRendererFunction`, `agentFunctionResponse` are all A→R and
must be **rejected** if a renderer sends them.

### Does NOT Exist
- ~~`A2UIRuntime`~~ / ~~`FunctionExecutor`~~ / ~~`SurfaceStateStore`~~ / ~~`PendingCallRegistry`~~ — this task creates them.
- ~~a `sendDataModel` message~~ — it is a `createSurface` flag; the data arrives on `action.dataModel` (TASK-2567).
- ~~`ToolManager` / `ConversationMemory` in `runtime/`~~ — forbidden (G8); those are TASK-2570's adapters.
- ~~`catalog.get_function()` returning `None`~~ — verify its miss behaviour before relying on it (it is `get_function`, not `.get`); wrap in try/except rather than assuming a sentinel.

---

## Implementation Notes

### The three Protocols (spec §2 "New Public Interfaces" — verbatim)
```python
@runtime_checkable
class FunctionExecutor(Protocol):
    async def call(self, name: str, args: dict[str, Any], ctx: A2UICallContext) -> "ToolResult": ...
    def list_functions(self) -> list["FunctionDefinition"]: ...

@runtime_checkable
class SurfaceStateStore(Protocol):
    async def get(self, session_id: str, surface_id: str) -> SurfaceState | None: ...
    async def put(self, session_id: str, state: SurfaceState) -> None: ...
    async def delete(self, session_id: str, surface_id: str) -> None: ...

@runtime_checkable
class PendingCallRegistry(Protocol):
    async def add(self, session_id: str, record: FunctionCallRecord) -> None: ...
    async def resolve(self, session_id: str, function_call_id: str,
                      value: Any, error: dict | None) -> FunctionCallRecord | None: ...
```

### `dispatch` — required order of operations
1. **Normalize**: accept `dict` or `A2UIRendererMessage`; a `dict` goes through
   `deserialize()` (never `model_validate` directly — `serialization` owns
   legacy normalization and `version`).
2. **Envelope guard**: exactly one message key + `version == "v1.0"`.
   Two keys, zero keys, an A→R key, or a wrong version ⇒
   `error{INVALID_FUNCTION_CALL}` and **execute nothing**.
3. **Lazy expiry sweep** of pending calls for `ctx.session_id` (spec §7: TTL 900 s,
   cleaned opportunistically on each dispatch — there is no background reaper).
4. **Branch** on the message key.

### Branch — `callAgentFunction`
```
catalogId = resolve_catalog(callFunction.catalogId, surface's catalogId)
        -> explicit catalogId wins; else the surface default; else -> INVALID_FUNCTION_CALL
look the function up among executor.list_functions() (catalog-side FunctionDefinition)
        -> missing                         -> INVALID_FUNCTION_CALL
        -> allowed_callers == "rendererOnly" -> INVALID_FUNCTION_CALL  (renderer may not ask the AGENT to run a renderer-only fn)
        -> allowed_callers == "agentOnly"    -> INVALID_FUNCTION_CALL
        -> "rendererOrAgent"                 -> proceed
await executor.call(name, args, ctx)
```
`ToolResult` mapping (spec §2, exhaustive):

| Condition | Emitted A→R |
|---|---|
| `success is True` | `agentFunctionResponse{functionCallId, value}` |
| `status == "forbidden"` | `error{code: FORBIDDEN}` |
| `status == "not_found"` | `error{code: INVALID_FUNCTION_CALL}` |
| executor raised | `error{code: INTERNAL}` |

`value` is `ToolResult.result` serialized to JSON. If the result carries an
`a2ui_envelope`, **also** append the corresponding `updateComponents` /
`updateDataModel` envelope to `DispatchResult.messages` (spec §2 step 4).

Check `status` **before** `success` for the failure cases, and match on the exact
strings `'forbidden'` / `'not_found'` — those are what `AbstractTool.execute`
(`tools/abstract.py:797`) and `ToolManager.execute_tool` (`manager.py:1519`,
miss path at ~1540) actually set.

### Branch — `action`
1. If `action.data_model is not None` (TASK-2567's field) and its serialized
   size exceeds `A2UI_MAX_DATA_MODEL_BYTES` (**default 1 MiB**, env-overridable):
   emit `error{INTERNAL, "data model too large"}`, **keep the previous surface
   state**, and do not persist. (Spec §7 + AC-OQ5.)
2. Else if `data_model is not None`: `surfaces.put(session_id, SurfaceState(...))`
   and set `DispatchResult.surface_state`. Note `{}` **is** a real update —
   only `None` means "renderer sent none" (that is exactly why TASK-2567 used
   `| None` rather than `default_factory=dict`).
3. Build `DispatchResult.user_turn`:
   - `action.userMessage` present ⇒ a **visible user turn** carrying that text.
   - absent ⇒ a **system turn** (spec §8 resolved OQ).
   - The `dataModel` / `context` **never** goes into the visible text — it
     travels via `surface_state` → `_a2ui_surface_state` (TASK-2575).

### Branch — `rendererFunctionResponse` / `error`
`pending.resolve(session_id, functionCallId, value, error)`. An unknown or
already-expired id ⇒ `error{NOT_FOUND}`. A resolved record returns; a `None`
return means unknown.

### `call_renderer()`
- `functionCallId` = `secrets.token_urlsafe(16)` (spec §7 — same criterion as deep links).
- **Always** set `callFunction.catalogId` (defaulting to `self._catalog_id`):
  the official schema makes it REQUIRED on `callRendererFunction` even though
  pydantic does not (see contract above). Omitting it produces an envelope that
  passes our models and fails a conformant renderer.
- Register a `FunctionCallRecord` via `pending.add` **before** returning, so a
  fast response cannot race the registration.
- Return `(function_call_id, serialized_envelope)`.

### Key Constraints
- **G8**: no module-level `parrot.bots` / `parrot.clients` / `parrot.tools` / `parrot.memory` import. `TYPE_CHECKING` only.
- Never hand-write `"version"` — always `serialize()`.
- `error.message` is a **safe** string; the real cause goes to `self.logger.exception` (spec §7 "Errores sin fuga"). No tracebacks on the wire.
- async throughout; Pydantic v2; Google-style docstrings; `self.logger`.

### References in Codebase
- `outputs/a2ui/catalog/__init__.py:219` `resolve_catalog` — precedence helper to reuse, do not reimplement.
- `outputs/a2ui/deeplink.py` — `secrets.token_urlsafe` id-minting precedent.
- `outputs/a2ui/serialization.py:104/155` — the only sanctioned envelope in/out.

---

## Acceptance Criteria

- [ ] `A2UIRuntime(executor=..., surfaces=..., pending=...)` constructs with fakes satisfying the Protocols, with no agent stack imported.
- [ ] A two-key envelope, a zero-key envelope, an A→R key, or `version != "v1.0"` ⇒ `error{INVALID_FUNCTION_CALL}` and **the executor is never called**.
- [ ] `callAgentFunction` success ⇒ `agentFunctionResponse` echoing the same `functionCallId`.
- [ ] `forbidden` ⇒ `FORBIDDEN`; `not_found` ⇒ `INVALID_FUNCTION_CALL`; raised exception ⇒ `INTERNAL` with no traceback in `message`.
- [ ] `allowedCallers = "rendererOnly"` (and `"agentOnly"`) invoked renderer→agent ⇒ error, executor not called.
- [ ] Explicit `callFunction.catalogId` beats the surface default; neither present ⇒ error.
- [ ] `action` with `dataModel` ⇒ `surfaces.put` called and `DispatchResult.surface_state` set; without ⇒ store untouched.
- [ ] `action` with `dataModel` over 1 MiB ⇒ `error{INTERNAL}`, previous state preserved.
- [ ] `userMessage` present ⇒ visible user turn; absent ⇒ system turn; `dataModel` never in the turn text.
- [ ] `call_renderer()` returns a unique `functionCallId`, always sets `catalogId`, and registers the pending record before returning.
- [ ] `rendererFunctionResponse` with a known id resolves it; unknown/expired ⇒ `error{NOT_FOUND}`.
- [ ] Every emitted envelope validates against `agent_to_renderer.json`.
- [ ] Tests pass: `pytest packages/ai-parrot/tests/outputs/a2ui/runtime -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/outputs/a2ui/runtime`

---

## Test Specification

```python
# packages/ai-parrot/tests/outputs/a2ui/runtime/conftest.py
import pytest
from parrot.outputs.a2ui.runtime.models import A2UICallContext


class FakeExecutor:
    """Programmable: success / forbidden / not_found / raise."""
    def __init__(self, mode="success", functions=None):
        self.mode, self.calls, self._functions = mode, [], functions or []
    async def call(self, name, args, ctx):
        self.calls.append((name, args, ctx))
        if self.mode == "raise":
            raise RuntimeError("secret internal detail")
        from parrot.tools.abstract import ToolResult
        return {
            "success":   ToolResult(success=True, status="success", result={"ok": 1}),
            "forbidden": ToolResult(success=False, status="forbidden", result=None, error="denied"),
            "not_found": ToolResult(success=False, status="not_found", result=None, error="missing"),
        }[self.mode]
    def list_functions(self):
        return self._functions


@pytest.fixture
def a2ui_call_ctx():
    return A2UICallContext(agent_id="agent-1", user_id="u-1", session_id="s-1",
                           transport="http", permission_context=object())
```

```python
# packages/ai-parrot/tests/outputs/a2ui/runtime/test_dispatch.py
class TestEnvelopeGuards:
    async def test_rejects_multi_key_envelope(self, runtime, fake_executor, a2ui_call_ctx):
        res = await runtime.dispatch(
            {"version": "v1.0", "action": {...}, "callAgentFunction": {...}}, a2ui_call_ctx)
        assert res.messages[0]["error"]["code"] == "INVALID_FUNCTION_CALL"
        assert fake_executor.calls == []          # nothing executed

    async def test_rejects_agent_to_renderer_key(self, runtime, a2ui_call_ctx): ...
    async def test_rejects_wrong_version(self, runtime, a2ui_call_ctx): ...


class TestCallAgentFunction:
    async def test_success_echoes_function_call_id(self, runtime, a2ui_call_ctx): ...
    async def test_forbidden_maps_to_FORBIDDEN(self, runtime_forbidden, a2ui_call_ctx): ...
    async def test_not_found_maps_to_INVALID_FUNCTION_CALL(self, runtime_missing, a2ui_call_ctx): ...
    async def test_exception_maps_to_INTERNAL_without_traceback(self, runtime_raises, a2ui_call_ctx):
        res = await runtime_raises.dispatch(env, a2ui_call_ctx)
        msg = res.messages[0]["error"]["message"]
        assert "secret internal detail" not in msg and "Traceback" not in msg
    async def test_renderer_only_function_rejected(self, runtime, a2ui_call_ctx): ...
    async def test_catalog_resolution_precedence(self, runtime, a2ui_call_ctx): ...


class TestAction:
    async def test_persists_data_model_and_sets_user_turn(self, runtime, fake_surfaces, a2ui_call_ctx): ...
    async def test_without_data_model_does_not_touch_store(self, runtime, fake_surfaces, a2ui_call_ctx): ...
    async def test_oversized_data_model_errors_and_preserves_state(self, runtime, fake_surfaces, a2ui_call_ctx): ...
    async def test_user_message_absent_yields_system_turn(self, runtime, a2ui_call_ctx): ...
    async def test_data_model_never_leaks_into_turn_text(self, runtime, a2ui_call_ctx): ...


class TestRendererCalls:
    async def test_call_renderer_registers_pending_and_sets_catalog_id(self, runtime, fake_pending): ...
    async def test_response_resolves_pending(self, runtime, fake_pending, a2ui_call_ctx): ...
    async def test_unknown_function_call_id_is_not_found(self, runtime, a2ui_call_ctx): ...
```

---

## Agent Instructions

1. **Read the spec** — §2 (Overview flows + New Public Interfaces), §3 Module 2, §7.
2. **Check dependencies** — TASK-2568 in `sdd/tasks/completed/`.
3. **Verify the Codebase Contract** — re-check `resolve_catalog` (catalog/__init__.py:219),
   `FunctionDefinition.allowed_callers` (catalog/base.py:246), and the exact
   `status` strings set by `ToolManager.execute_tool` (manager.py:1519 and its
   ~1540 miss path). Update the contract first if anything drifted.
4. **Update status** in the index → `"in-progress"`.
5. **Implement** per scope; keep `runtime/` free of agent-stack imports.
6. **Verify** every acceptance criterion.
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

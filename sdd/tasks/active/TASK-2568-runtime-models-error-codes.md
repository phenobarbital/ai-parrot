# TASK-2568: Runtime models and A2UI error codes

**Feature**: FEAT-469 — A2UI Agent Functions Runtime (v1.0 RPC leg)
**Spec**: `sdd/specs/a2ui-agent-functions.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-2567
**Assigned-to**: unassigned

---

## Context

Implements **spec §3 Module 1**. Creates the new `parrot/outputs/a2ui/runtime/`
package and the pure-data types every other FEAT-469 task consumes:
`A2UICallContext` (what the transport hands the runtime), `FunctionCallRecord`
(an agent→renderer call awaiting correlation), `SurfaceState` (the last
`dataModel` seen for a surface), `DispatchResult` (what the runtime hands back),
and `A2UIErrorCode`.

This is the foundation of the **G8 one-way import rule**: `runtime/` is pure
protocol and must never import `parrot.bots` or `parrot.clients` at module
level. Getting the package boundary right here is what makes TASK-2569 and
TASK-2570 testable without booting an agent.

---

## Scope

- Create the `parrot/outputs/a2ui/runtime/` package.
- Implement `A2UICallContext`, `FunctionCallRecord`, `SurfaceState`,
  `DispatchResult` (all Pydantic v2) and the `A2UIErrorCode` str-enum.
- Implement the `error_envelope(code, message, *, function_call_id=None, surface_id=None)`
  helper that emits a schema-valid `{"version": "v1.0", "error": {...}}`.
- Unit-test the envelope shape against the vendored schemas.

**NOT in scope**: `dispatch()` (TASK-2569), the Protocol definitions
(TASK-2569), any adapter (TASK-2570).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/outputs/a2ui/runtime/__init__.py` | CREATE | Package init; re-export the models (Protocols land here in TASK-2569) |
| `packages/ai-parrot/src/parrot/outputs/a2ui/runtime/models.py` | CREATE | The five types + `error_envelope` |
| `packages/ai-parrot/tests/outputs/a2ui/runtime/__init__.py` | CREATE | Test package init |
| `packages/ai-parrot/tests/outputs/a2ui/runtime/test_models.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

> Verified on `dev` @ `ce716a032` (2026-08-29).

### Verified Imports
```python
from parrot.outputs.a2ui.catalog.base import DEFAULT_CATALOG_ID   # catalog/base.py:52 == "https://parrot.dev/catalogs/v1"
from parrot.outputs.a2ui.models import ErrorMessage                # models.py:639
from parrot.outputs.a2ui.serialization import serialize            # serialization.py:104
from pydantic import BaseModel, ConfigDict, Field
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/outputs/a2ui/models.py:639
class ErrorMessage(A2UIMessageBase):
    model_config = ConfigDict(populate_by_name=True, extra="allow")   # NOTE: "allow", unlike its siblings
    code: str
    message: str
    surface_id: ...        # alias "surfaceId"
    path: ...              # validation errors only
    function_call_id: ...  # alias "functionCallId", generic errors only

# packages/ai-parrot/src/parrot/outputs/a2ui/models.py:~633 — the schema's two error shapes
_VALIDATION_ERROR_CODES = frozenset({"VALIDATION_FAILED", "UNALLOWED_PARENT", "UNALLOWED_CHILD"})

# packages/ai-parrot/src/parrot/outputs/a2ui/catalog/__init__.py
def validate_message(message) -> None:   # line 334 — jsonschema validation
def validate_envelope(...)               # line 378
```

### The error-shape rule (verified in `renderer_to_agent.json`, and mirrored in `agent_to_renderer.json`)

`ErrorMessage` covers **two mutually exclusive shapes** — the docstring at
`models.py:639-658` states this and it is enforced by jsonschema, not by
pydantic (`extra="allow"`):

| Shape | Trigger | MUST carry | MUST NOT carry |
|---|---|---|---|
| **Validation** | `code` ∈ `{VALIDATION_FAILED, UNALLOWED_PARENT, UNALLOWED_CHILD}` | `surfaceId` **and** `path` | `functionCallId` |
| **Generic** | any other `code` | **exactly one** of `surfaceId` / `functionCallId` | — |

`error_envelope()` must therefore refuse to build an envelope that mixes these
(e.g. `UNALLOWED_PARENT` with a `functionCallId`, or a generic error with both
`surfaceId` and `functionCallId`). Raise `ValueError` — a malformed error
envelope is a bug in *our* code, not renderer input.

### Does NOT Exist
- ~~`parrot.outputs.a2ui.runtime`~~ — this task creates it.
- ~~`A2UIErrorCode` / `A2UICallContext` / `SurfaceState` / `DispatchResult` / `FunctionCallRecord`~~ — all new here.
- ~~`parrot.auth.permission` imported by `runtime/models.py`~~ — do NOT import it; `permission_context` is typed `Any` on purpose (G8).
- ~~`ConversationMemory` / `ToolManager` references in `runtime/`~~ — forbidden at module level (G8); they arrive only in TASK-2570's adapters.

---

## Implementation Notes

### The models (spec §2 "Data Models" — reproduce these field-for-field)
```python
class A2UICallContext(BaseModel):
    agent_id: str
    user_id: str | None = None
    session_id: str
    surface_id: str | None = None
    permission_context: Any = None      # parrot.auth.permission.PermissionContext — NOT re-modelled, NOT imported (G8)
    transport: Literal["http", "a2a", "deeplink"]
    streaming: bool = False

class FunctionCallRecord(BaseModel):
    function_call_id: str
    surface_id: str | None = None
    call: str
    catalog_id: str | None = None
    args: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    ttl_seconds: int = 900

class SurfaceState(BaseModel):
    surface_id: str
    catalog_id: str
    data_model: dict[str, Any]
    updated_at: datetime

class DispatchResult(BaseModel):
    messages: list[dict[str, Any]] = Field(default_factory=list)  # ALREADY serialized A->R envelopes
    user_turn: str | None = None
    surface_state: SurfaceState | None = None
```

### `A2UIErrorCode`
Spec §2 lists exactly: `INVALID_FUNCTION_CALL`, `UNALLOWED_PARENT`,
`UNALLOWED_CHILD`, `FORBIDDEN`, `NOT_FOUND`, `INTERNAL`, `TIMEOUT`.
Note that `FORBIDDEN`, `NOT_FOUND`, `INTERNAL` and `TIMEOUT` are
**parrot extensions** — the A2UI spec reserves no code list for generic errors,
so any string is legal there. Only the three validation codes are protocol-fixed
(and they match `_VALIDATION_ERROR_CODES` in `models.py`). Add a module docstring
saying which are ours and which are the protocol's, so nobody later "fixes" them
to match a spec that never defined them.

### `error_envelope`
Must build via the model + `serialize()` — **never hand-write `{"version": ...}`**
(spec §7: "el runtime nunca escribe `version` a mano"; `serialization` owns it).
`message` must be a **safe** string: no exception text, no traceback. The caller
logs the real cause with `logger.exception`.

### Key Constraints
- Pydantic v2, Google-style docstrings, strict type hints.
- `datetime` fields: use timezone-aware UTC (`datetime.now(timezone.utc)`).
- **G8**: no `parrot.bots` / `parrot.clients` / `parrot.tools` / `parrot.memory`
  imports at module level anywhere under `runtime/`.

### References in Codebase
- `outputs/a2ui/models.py:639` — `ErrorMessage`, the wire target.
- `outputs/a2ui/deeplink.py:53` — `ResumePayload`, a good local example of a Pydantic model with a `field_validator` guarding wire shape.
- `outputs/a2ui/catalog/base.py:246` — `FunctionDefinition`, the house style for a small wire-adjacent model.

---

## Acceptance Criteria

- [ ] `from parrot.outputs.a2ui.runtime.models import A2UICallContext, FunctionCallRecord, SurfaceState, DispatchResult, A2UIErrorCode, error_envelope` works.
- [ ] `error_envelope(A2UIErrorCode.INTERNAL, "boom", function_call_id="fc-1")` → `{"version": "v1.0", "error": {"code": "INTERNAL", "message": "boom", "functionCallId": "fc-1"}}`.
- [ ] `error_envelope` raises `ValueError` when given a validation code without `surface_id`+`path`, or a generic code with both/neither of `surface_id`/`function_call_id`.
- [ ] Every emitted envelope validates against the vendored `agent_to_renderer.json`.
- [ ] `A2UICallContext.permission_context` is typed `Any`; `runtime/models.py` imports nothing from `parrot.auth`.
- [ ] Tests pass: `pytest packages/ai-parrot/tests/outputs/a2ui/runtime -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/outputs/a2ui/runtime`

---

## Test Specification

```python
# packages/ai-parrot/tests/outputs/a2ui/runtime/test_models.py
import pytest

from parrot.outputs.a2ui.runtime.models import (
    A2UICallContext, A2UIErrorCode, DispatchResult, FunctionCallRecord,
    SurfaceState, error_envelope,
)


class TestErrorEnvelope:
    def test_generic_error_with_function_call_id(self):
        env = error_envelope(A2UIErrorCode.INTERNAL, "boom", function_call_id="fc-1")
        assert env == {"version": "v1.0",
                       "error": {"code": "INTERNAL", "message": "boom", "functionCallId": "fc-1"}}

    def test_generic_error_rejects_both_ids(self):
        with pytest.raises(ValueError):
            error_envelope(A2UIErrorCode.INTERNAL, "boom",
                           function_call_id="fc-1", surface_id="s-1")

    def test_generic_error_rejects_neither_id(self):
        with pytest.raises(ValueError):
            error_envelope(A2UIErrorCode.INTERNAL, "boom")

    def test_validation_code_requires_surface_and_path(self):
        with pytest.raises(ValueError):
            error_envelope(A2UIErrorCode.UNALLOWED_PARENT, "bad", function_call_id="fc-1")

    def test_never_hand_writes_version(self):
        assert error_envelope(A2UIErrorCode.NOT_FOUND, "x", function_call_id="f")["version"] == "v1.0"


class TestRuntimeModels:
    def test_call_context_permission_context_is_opaque(self):
        ctx = A2UICallContext(agent_id="a", session_id="s", transport="http",
                              permission_context=object())
        assert ctx.permission_context is not None

    def test_dispatch_result_defaults_empty(self):
        r = DispatchResult()
        assert r.messages == [] and r.user_turn is None and r.surface_state is None


def test_runtime_models_do_not_import_agent_stack():
    """G8: runtime/ is pure protocol."""
    import parrot.outputs.a2ui.runtime.models as m
    src = open(m.__file__).read()
    for banned in ("from parrot.bots", "from parrot.clients", "from parrot.auth"):
        assert banned not in src
```

---

## Agent Instructions

1. **Read the spec** — §2 "Data Models", §3 Module 1, §7 "Patterns to Follow".
2. **Check dependencies** — TASK-2567 must be in `sdd/tasks/completed/`.
3. **Verify the Codebase Contract** — confirm `ErrorMessage` (models.py:639) still
   has `extra="allow"` and that `_VALIDATION_ERROR_CODES` still holds those three codes.
4. **Update status** in `sdd/tasks/index/a2ui-agent-functions.json` → `"in-progress"`.
5. **Implement** per scope.
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

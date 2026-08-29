# TASK-2567: Wire-model support for `action.dataModel` + fix swapped response docstrings

**Feature**: FEAT-469 — A2UI Agent Functions Runtime (v1.0 RPC leg)
**Spec**: `sdd/specs/a2ui-agent-functions.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec goal **G3** requires the renderer to attach the surface's full `dataModel`
to every `action` (the `sendDataModel` flow). The spec's §6 Codebase Contract
assumed FEAT-469 would only *consume* `outputs/a2ui/models.py` — that assumption
is **wrong**, and this task is the correction (spec §6 "Contract Refresh —
FINDING 1").

`sendDataModel` today is only a **boolean flag on `createSurface`**
(`outputs/a2ui/models.py:467`) meaning "renderer, send the full data model back
with every message". But the receiving model, `ActionMessage`, is
`extra="forbid"` with no field to receive it — so a compliant renderer honouring
`sendDataModel: true` produces a payload that **ai-parrot rejects with a
pydantic `ValidationError`**. G3 cannot work until this is fixed, and every
downstream task (2569 dispatch, 2570 adapters, 2575 bot context) assumes the
field exists.

This task is deliberately **first, tiny, and surgical**: it is the only task in
FEAT-469 that touches `outputs/a2ui/models.py`, a file that in-flight **FEAT-473**
(`a2ui-v1-structured-outputs`) may also touch. Land it early and keep the diff
minimal so the overlap window is as short as possible.

It also fixes a docs defect shipped by FEAT-470 (spec §6 FINDING 2) — the two
function-response classes describe each other's pairing, which is precisely the
pairing this whole feature implements.

---

## Scope

- Add an explicit optional `data_model` field to `ActionMessage`
  (alias `dataModel`), keeping `extra="forbid"`.
- Fix the swapped docstrings on `AgentFunctionResponse` and
  `RendererFunctionResponse`.
- Add unit tests proving `action` accepts `dataModel`, that
  `callAgentFunction` still **rejects** it, and that round-tripping through
  `serialize`/`deserialize` preserves it.

**Design decision — explicit field, NOT `extra="allow"`.** Relaxing
`ActionMessage` to `extra="allow"` would also silently swallow renderer typos
(`datamodel`, `dataMdel`) and every future unknown key, turning a loud
`ValidationError` into a silent data loss. An explicit optional field keeps
`extra="forbid"` doing its job for everything else. This is mandated by the spec
(AC-F1) — do not substitute `extra="allow"`.

**NOT in scope**:
- Persisting or size-capping the data model — that is TASK-2570 (`SurfaceStateStore`)
  and the `A2UI_MAX_DATA_MODEL_BYTES` check in TASK-2569.
- Exposing it to tools as `_a2ui_surface_state` — TASK-2575.
- Any change to `CallAgentFunction` (the schema forbids `dataModel` there — see below).
- Any other change to `models.py`. Keep the diff minimal for FEAT-473 overlap.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/outputs/a2ui/models.py` | MODIFY | Add `ActionMessage.data_model`; fix two docstrings |
| `packages/ai-parrot/tests/outputs/a2ui/test_models.py` | MODIFY | Add the `dataModel` accept/reject tests |
| `packages/ai-parrot/tests/outputs/a2ui/test_serialization.py` | MODIFY | Add the round-trip test |

---

## Codebase Contract (Anti-Hallucination)

> Verified on `dev` @ `ce716a032` (2026-08-29), **after** FEAT-470 merged (PR #1263).

### Verified Imports
```python
from parrot.outputs.a2ui.models import (          # outputs/a2ui/models.py
    A2UIMessageBase,          # line 381
    A2UIRendererMessage,      # renderer->agent envelope wrapper
    ActionMessage,            # line 585
    CallAgentFunction,        # line 610
    AgentFunctionResponse,    # line 575
    RendererFunctionResponse, # line 627
    CreateSurface,            # line 445
)
from parrot.outputs.a2ui.serialization import serialize, deserialize  # serialization.py:104, :155
from pydantic import ConfigDict, Field
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/outputs/a2ui/models.py:585
class ActionMessage(A2UIMessageBase):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    name: str
    user_message: str | None = Field(default=None, alias="userMessage")
    surface_id: str = Field(alias="surfaceId")
    source_component_id: str = Field(alias="sourceComponentId")
    timestamp: str
    context: dict[str, Any]
    metadata: ComponentMetadata | None = None
    # <-- ADD `data_model` HERE

# packages/ai-parrot/src/parrot/outputs/a2ui/models.py:445  (the FLAG that drives this)
class CreateSurface(A2UIMessageBase):
    send_data_model: bool = Field(default=False, alias="sendDataModel")   # line 467
    data_model: dict[str, Any] = Field(default_factory=dict, alias="dataModel")  # line 469
    # ^^ copy this exact alias/type style for ActionMessage.data_model

# packages/ai-parrot/src/parrot/outputs/a2ui/models.py:610  (do NOT touch — schema forbids dataModel)
class CallAgentFunction(A2UIMessageBase):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")
    surface_id: str = Field(alias="surfaceId")
    function_call_id: str = Field(alias="functionCallId")
    call_function: FunctionCall = Field(alias="callFunction")

# packages/ai-parrot/src/parrot/outputs/a2ui/models.py:554
class _FunctionResponseBase(A2UIMessageBase):
    function_call_id: str = Field(alias="functionCallId")
    value: Any = None
    error: FunctionCallError | None = None
    @model_validator(mode="after")
    def _exactly_one(self) -> "_FunctionResponseBase": ...   # value XOR error
```

### The schema evidence (verified — this is WHY the change is legal)

Read from the vendored
`packages/ai-parrot/src/parrot/outputs/a2ui/catalog/basic/spec/renderer_to_agent.json`:

| Message | `additionalProperties` | ⇒ may carry `dataModel`? |
|---|---|---|
| `action` | **key absent** ⇒ defaults to `true` | **YES — legal** |
| `callAgentFunction` | **`false`** | **NO — illegal** |

The envelope is `minProperties: 2, maxProperties: 2` with
`oneOf: [action, callAgentFunction, rendererFunctionResponse, error]` (each
`required` alongside `version`), so `dataModel` can only ever live *inside* the
message object — never as a sibling of it. `$defs` is empty in this schema file.

`action.required` is exactly
`["name", "surfaceId", "sourceComponentId", "timestamp", "context"]` — so
`dataModel` must be **optional** (`default=None`), never required.

### Does NOT Exist
- ~~a `sendDataModel` *message*~~ — it is only a boolean field on `createSurface`. There is no `SendDataModel` class and you must not create one.
- ~~`ActionMessage.data_model`~~ — this task adds it.
- ~~`$defs` in `renderer_to_agent.json`~~ — the file has an empty `$defs`; don't try to `$ref` into it.
- ~~`CallAgentFunction.data_model`~~ — schema-forbidden. Do not add it.

---

## Implementation Notes

### The edit
```python
# in ActionMessage, mirroring CreateSurface's alias style at models.py:469
data_model: dict[str, Any] | None = Field(default=None, alias="dataModel")
```
Use `| None` with `default=None` (NOT `default_factory=dict`): the spec needs to
distinguish "renderer sent an empty data model" from "renderer sent none at
all", because only the former should overwrite stored surface state in TASK-2570.
`CreateSurface.data_model` uses `default_factory=dict` because there the surface
always has *some* initial model — the semantics genuinely differ. Document that
difference in the field's docstring entry.

Add the attribute to the class docstring's `Attributes:` block, matching the
existing Google-style formatting.

### The docstring fix (spec §6 FINDING 2)
Currently **both are backwards**:

| Line | Class | Says it answers | Should say |
|---|---|---|---|
| 575 | `AgentFunctionResponse` | `callRendererFunction` | **`callAgentFunction`** |
| 627 | `RendererFunctionResponse` | `callAgentFunction` | **`callRendererFunction`** |

The class *placement* and wire directions are already correct — 
`AgentFunctionResponse` sits in the agent→renderer block and answers the
renderer's `callAgentFunction`; `RendererFunctionResponse` sits in the
renderer→agent block and answers the agent's `callRendererFunction`. **Change
only the prose. Do not move, rename, or re-parent either class** — that would be
a wire-breaking change.

### Key Constraints
- Pydantic v2, Google-style docstrings.
- Do not touch `model_config` on any class.
- Keep the diff to these two concerns only (FEAT-473 shares this file).

### References in Codebase
- `outputs/a2ui/models.py:445-470` — `CreateSurface`, the alias/typing style to copy.
- `outputs/a2ui/serialization.py:104` `serialize` / `:155` `deserialize` — round-trip path.
- `outputs/a2ui/catalog/__init__.py:334` `validate_message` / `:378` `validate_envelope` — jsonschema conformance helpers to reuse in tests.

---

## Acceptance Criteria

- [ ] `ActionMessage` accepts `dataModel` by alias and `data_model` by field name; `extra="forbid"` is unchanged.
- [ ] `ActionMessage.data_model` defaults to `None` (absent), distinguishable from `{}` (explicitly empty).
- [ ] `CallAgentFunction` still rejects `dataModel` with a `ValidationError`.
- [ ] `AgentFunctionResponse` / `RendererFunctionResponse` docstrings name the correct counterpart call message.
- [ ] An `action` envelope carrying `dataModel` validates against the vendored `renderer_to_agent.json`.
- [ ] `serialize(deserialize(env)) == env` for an `action` envelope with `dataModel`.
- [ ] Tests pass: `pytest packages/ai-parrot/tests/outputs/a2ui/test_models.py packages/ai-parrot/tests/outputs/a2ui/test_serialization.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/outputs/a2ui/models.py`

---

## Test Specification

```python
# packages/ai-parrot/tests/outputs/a2ui/test_models.py
import pytest
from pydantic import ValidationError

from parrot.outputs.a2ui.models import ActionMessage, CallAgentFunction


def _action(**extra):
    base = {
        "name": "submit",
        "surfaceId": "s-1",
        "sourceComponentId": "btn-1",
        "timestamp": "2026-08-29T10:00:00Z",
        "context": {"k": "v"},
    }
    base.update(extra)
    return base


class TestActionDataModel:
    def test_action_accepts_data_model(self):
        msg = ActionMessage.model_validate(_action(dataModel={"count": 3}))
        assert msg.data_model == {"count": 3}

    def test_action_data_model_absent_is_none(self):
        """Absent must be None, NOT {} — TASK-2570 relies on the distinction."""
        assert ActionMessage.model_validate(_action()).data_model is None

    def test_action_empty_data_model_is_not_none(self):
        assert ActionMessage.model_validate(_action(dataModel={})).data_model == {}

    def test_action_still_forbids_unknown_keys(self):
        with pytest.raises(ValidationError):
            ActionMessage.model_validate(_action(datamodel={"typo": 1}))

    def test_call_agent_function_rejects_data_model(self):
        """renderer_to_agent.json sets additionalProperties:false here."""
        with pytest.raises(ValidationError):
            CallAgentFunction.model_validate({
                "surfaceId": "s-1",
                "functionCallId": "fc-1",
                "callFunction": {"call": "get_weather", "args": {}},
                "dataModel": {"nope": True},
            })


class TestFunctionResponseDocstrings:
    def test_agent_function_response_names_call_agent_function(self):
        from parrot.outputs.a2ui.models import AgentFunctionResponse
        assert "callAgentFunction" in AgentFunctionResponse.__doc__
        assert "callRendererFunction" not in AgentFunctionResponse.__doc__

    def test_renderer_function_response_names_call_renderer_function(self):
        from parrot.outputs.a2ui.models import RendererFunctionResponse
        assert "callRendererFunction" in RendererFunctionResponse.__doc__
        assert "callAgentFunction" not in RendererFunctionResponse.__doc__
```

```python
# packages/ai-parrot/tests/outputs/a2ui/test_serialization.py
def test_action_with_data_model_round_trips():
    from parrot.outputs.a2ui.serialization import serialize, deserialize
    env = {
        "version": "v1.0",
        "action": {
            "name": "submit", "surfaceId": "s-1", "sourceComponentId": "btn-1",
            "timestamp": "2026-08-29T10:00:00Z", "context": {},
            "dataModel": {"rows": [1, 2, 3]},
        },
    }
    assert serialize(deserialize(env)) == env
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** — especially §6 "Contract Refresh — 2026-08-29", FINDING 1 and FINDING 2.
2. **Check dependencies** — none. This is the first task of FEAT-469.
3. **Verify the Codebase Contract** before writing code: re-read `ActionMessage`
   (~line 585) and confirm it is still `extra="forbid"` with no `data_model`; re-read
   `renderer_to_agent.json` and re-confirm `action` has no `additionalProperties`
   key while `callAgentFunction` has `additionalProperties: false`. If FEAT-473
   has already changed `models.py`, update this contract FIRST, then implement.
4. **Update status** in `sdd/tasks/index/a2ui-agent-functions.json` → `"in-progress"`.
5. **Implement** exactly the two concerns in scope — nothing else in `models.py`.
6. **Verify** every acceptance criterion.
7. **Move this file** to `sdd/tasks/completed/`.
8. **Update index** → `"done"`.
9. **Fill in the Completion Note** below.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none | describe if any

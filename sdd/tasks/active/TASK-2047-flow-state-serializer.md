# TASK-2047: FlowStateSerializer — type registry + ormsgpack

**Feature**: FEAT-399 — AgentsFlow State Checkpointing (Two-Tier Persistence)
**Spec**: `sdd/specs/agentsflow-state-checkpointing.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2046
**Assigned-to**: unassigned

---

## Context

Spec §2/§3 Module 2. The hybrid serializer (resolved OQ1: **ormsgpack**, never
pickle): registered Pydantic models round-trip with type identity; everything
else degrades to a tagged repr and marks the checkpoint `lossy=True` instead of
failing the flow.

---

## Scope

- Add `ormsgpack>=1.5` to `pyproject.toml` (checkpointing dependency).
- Implement `serializer.py`:
  - `FlowStateSerializer` with a **type registry**: `register(model_cls)`
    maps a type tag (e.g. `"parrot.models.AIMessage"`) → class; encode as
    `{"__type__": tag, "data": model.model_dump()}`; decode reconstructs via
    `model_validate`.
  - Pre-register the known result types: `AIMessage` (from `parrot.models`)
    and reuse the coercion behavior of `_serialise_result_value` for plain
    values (spec §6 Integration Points).
  - `encode(obj) -> bytes` / `decode(data: bytes) -> Any` via ormsgpack with a
    `default=` hook; unregistered objects → `{"__repr__": repr(obj), "__type__": "lossy"}`
    and the serializer records `lossy=True` for the enclosing operation
    (expose e.g. `encode_with_meta() -> tuple[bytes, bool]`).
  - Structured error encoding: `Exception` → `{type, message, repr}` dict.
- Unit tests per spec §4 (registered round-trip, lossy degradation,
  structured errors).

**NOT in scope**: stores, checkpointer, any AgentsFlow change.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/flows/core/checkpoint/serializer.py` | CREATE | FlowStateSerializer |
| `packages/ai-parrot/src/parrot/bots/flows/core/checkpoint/__init__.py` | MODIFY | Re-export FlowStateSerializer |
| `pyproject.toml` | MODIFY | Add `ormsgpack>=1.5` |
| `packages/ai-parrot/tests/flows/checkpoint/test_serializer.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.models import AIMessage            # verified: parrot/models/__init__.py:15-16 (defined in models/responses.py)
from parrot.bots.flows.core.result import _serialise_result_value  # verified: imported by flow/flow.py:33
from parrot.bots.flows.core.checkpoint.model import FlowCheckpoint  # from TASK-2046
import ormsgpack                                # NEW dependency added by THIS task
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/bots/flows/core/result.py
def _serialise_result_value(...) -> ...:   # existing result-value coercion —
    ...                                     # read the actual signature before use;
                                            # fold its behavior into the registry fallback
```

### Does NOT Exist
- ~~`ormsgpack` in pyproject.toml today~~ — THIS task adds it; until then `import ormsgpack` fails.
- ~~`msgpack`~~ — resolved OQ1 chose ormsgpack; do NOT add or import `msgpack`.
- ~~pickle/cloudpickle paths~~ — forbidden by spec (never pickle).
- ~~A pre-existing type registry anywhere in `parrot/`~~ — this task introduces it.

---

## Implementation Notes

### Key Constraints
- ormsgpack serializes Pydantic models natively via
  `ormsgpack.packb(obj, option=ormsgpack.OPT_SERIALIZE_PYDANTIC)` — but for
  *registered* types we need the type tag for faithful **decode**, so wrap
  registered models in the `{"__type__": ...}` envelope BEFORE packb.
- Decode must never execute arbitrary code (no dynamic import of unregistered
  tags — unknown tag decodes to the raw envelope dict).
- `datetime`/`UUID` are handled natively by ormsgpack.
- Log at DEBUG on lossy degradation (include the offending type name).

### References in Codebase
- `parrot/bots/flows/core/result.py` — `_serialise_result_value` fallback behavior.
- Spec §7 Known Risks — lossy checkpoints, structured errors.

---

## Acceptance Criteria

- [ ] `test_serializer_registered_pydantic_roundtrip` — registered model survives encode/decode with type identity (`isinstance` preserved).
- [ ] `test_serializer_unregistered_degrades_lossy` — unknown object → tagged repr, lossy flag True, no exception.
- [ ] `test_serializer_errors_structured` — Exception → `{type, message, repr}`.
- [ ] `uv pip install -e .` resolves ormsgpack; `python -c "import ormsgpack"` works in the venv.
- [ ] All tests pass: `pytest packages/ai-parrot/tests/flows/checkpoint/test_serializer.py -v`
- [ ] `ruff check` clean on new files.

---

## Test Specification

```python
# packages/ai-parrot/tests/flows/checkpoint/test_serializer.py
from parrot.bots.flows.core.checkpoint import FlowStateSerializer

def test_registered_pydantic_roundtrip():
    s = FlowStateSerializer()
    msg = AIMessage(...)                      # minimal valid instance
    data, lossy = s.encode_with_meta({"n1": msg})
    assert not lossy
    out = s.decode(data)
    assert isinstance(out["n1"], AIMessage)

def test_unregistered_degrades_lossy():
    class Weird: ...
    s = FlowStateSerializer()
    data, lossy = s.encode_with_meta({"n1": Weird()})
    assert lossy
    assert "Weird" in str(s.decode(data)["n1"])

def test_exception_structured():
    ...  # ValueError("boom") → {"type": "ValueError", "message": "boom", ...}
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify `Depends-on` tasks are in `tasks/completed/`
3. **Verify the Codebase Contract** — confirm imports/signatures still exist; read `_serialise_result_value`'s real signature before folding it in
4. **Update status** in `sdd/tasks/index/agentsflow-state-checkpointing.json` → `"in-progress"`
5. **Implement**, then **verify** all acceptance criteria
6. **Move this file** to `sdd/tasks/completed/` and update index → `"done"`
7. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none

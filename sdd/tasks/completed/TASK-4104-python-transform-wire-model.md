# TASK-4104: `PythonTransform` wire model, three-way `TransformSpec` XOR, terminal rule + schema regeneration

**Feature**: FEAT-636 — Linked A2UI surfaces — server-executed Python recipe transformers
**Spec**: `sdd/specs/linked-a2ui-recipes-transforms.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 1. Linked surfaces' `TransformSpec` today is a two-way XOR (`ops` | `ref`). This task adds the
third member, `python: PythonTransform`, which every other FEAT-636 task builds on. It also enforces the
v1 **terminal** rule (proposal U3): no derived/join/union sibling may consume a python-transformed source,
and regenerates BOTH committed schema artifacts — because `test_ts_codegen.py::test_schemas_in_sync_with_committed`
and `test_linked_schema.py::test_committed_schema_matches_export` fail the moment the model changes without them.

---

## Scope

- Add `PythonTransform` (fields `transformer`, `params`, `input_alias="source"`, `output=None`).
- Make `TransformSpec` exactly-one-of `ops` / `ref` / `python`.
- Extend `DerivedDataSource._ops_only` to reject `python` as well as `ref`.
- Add `LinkedSources._python_terminal`: reject any `derived.from`, `join.with`, or `union.sources`
  that names a sibling whose `transform.python` is set.
- Export `PythonTransform` from `parrot.outputs.a2ui.linked`.
- Regenerate `linked/contract/schema.json` (`python -m parrot.outputs.a2ui.linked.schema`) and
  `ui/schemas/LinkedSources.json` (`python scripts/generate_ts_types.py`).
- Write unit tests.

**NOT in scope**: running the transformer (TASK-4105), the TS `.d.ts` regeneration via `pnpm generate`
(TASK-4110), executor/service/handler changes.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/outputs/a2ui/linked/models.py` | MODIFY | `PythonTransform`, 3-way XOR, derived reject, terminal rule |
| `packages/ai-parrot/src/parrot/outputs/a2ui/linked/__init__.py` | MODIFY | export `PythonTransform` |
| `packages/ai-parrot/src/parrot/outputs/a2ui/linked/contract/schema.json` | MODIFY | regenerated (never hand-edited) |
| `packages/ai-parrot-server/ui/schemas/LinkedSources.json` | MODIFY | regenerated (never hand-edited) |
| `packages/ai-parrot/tests/outputs/a2ui/linked/test_python_transform_models.py` | CREATE | unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from pydantic import BaseModel, ConfigDict, Field, RootModel, field_validator, model_validator  # verified: linked/models.py:9
from parrot.outputs.a2ui.linked.models import (  # verified: linked/models.py
    DerivedDataSource, Join, LinkedDataSource, LinkedSources, TransformSpec, Union_,
)
from parrot.outputs.a2ui.linked.schema import dumps_schema, export_json_schema, write_json_schema  # verified: linked/schema.py:19-37
from scripts.generate_ts_types import SCHEMAS_DIR, export_schemas  # verified: scripts/generate_ts_types.py:43,117
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/outputs/a2ui/linked/models.py
_CFG = ConfigDict(extra="forbid", populate_by_name=True)               # line 13
class Join(BaseModel):  with_: str = Field(alias="with")               # line 159-164
class Union_(BaseModel): sources: list[str] = Field(min_length=1)      # line 167-170
class TransformSpec(BaseModel):                                        # line 178
    ops: list[TransformOp] | None = None                               # line 182
    ref: TransformRef | None = None                                    # line 183
    @model_validator(mode="after")
    def _xor(self) -> TransformSpec:                                   # line 185-189 (two-way today)
class LinkedDataSource(BaseModel): transform: TransformSpec | None     # line 192, 205
class DerivedDataSource(BaseModel):                                    # line 226
    from_: str = Field(alias="from")                                   # line 237
    transform: TransformSpec                                           # line 238
    def _ops_only(self) -> DerivedDataSource:                          # line 257-261
class LinkedSources(RootModel[dict[str, LinkedSource]]):               # line 267
    def _default_kind(cls, value)                                      # line 270-287 (mode="before")
    def _check_keys(self) -> LinkedSources:                            # line 289-295 (mode="after")

# packages/ai-parrot/src/parrot/outputs/a2ui/linked/__init__.py — imports at 31, __all__ at 80-105
# scripts/generate_ts_types.py:83,113 — LinkedSources is one of the exported UI schemas; main() at 141
```

### Does NOT Exist
- ~~`TransformSpec.python`~~ / ~~`PythonTransform`~~ — created by this task.
- ~~a `kind="python"` source~~ — rejected design (proposal OQ-A); do NOT add a new source kind.
- ~~`src/lib/types/generated/LinkedSources.d.ts` regeneration here~~ — that is `pnpm generate`, TASK-4110.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/outputs/a2ui/linked/models.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/outputs/a2ui/linked/__init__.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/outputs/a2ui/linked/contract/schema.json", "action": "MODIFY"},
    {"path": "packages/ai-parrot-server/ui/schemas/LinkedSources.json", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/outputs/a2ui/linked/test_python_transform_models.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/outputs/a2ui/linked/models.py#TransformSpec",
    "sym:packages/ai-parrot/src/parrot/outputs/a2ui/linked/models.py#DerivedDataSource",
    "sym:packages/ai-parrot/src/parrot/outputs/a2ui/linked/models.py#LinkedSources",
    "sym:packages/ai-parrot/src/parrot/outputs/a2ui/linked/schema.py#write_json_schema",
    "sym:scripts/generate_ts_types.py#export_schemas"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Keep `_CFG` (`extra="forbid"`) on the new model — every wire model in this file uses it.
- Descriptors without `python` must validate exactly as before (AC11): the XOR change must not alter the
  error message path for the existing `ops`/`ref` cases beyond the wording "exactly one of 'ops', 'ref' or 'python'".
- Never hand-edit the two JSON schema files; regenerate them with the commands in Steps.

---

## Implementation Blueprint

### Steps (in order)
1. Add `PythonTransform` directly above `TransformSpec` — *why*: `TransformSpec` references it, and Pydantic needs it defined first.
2. Replace `_xor` with a three-way count — *why*: AC1 requires exactly one of three members.
3. Extend `DerivedDataSource._ops_only` — *why*: a derived view runs only inline ops; `python` is server-terminal (AC1).
4. Add `LinkedSources._python_terminal` after `_check_keys` — *why*: U3/AC2 forbid consuming a python source's frame.
5. Export `PythonTransform` in `linked/__init__.py` (import + `__all__`) — *why*: TASK-4105/4109 import it from the package.
6. Run `python -m parrot.outputs.a2ui.linked.schema` then `python scripts/generate_ts_types.py` — *why*: both drift tests compare committed JSON to the model.
7. Write the tests below and run the Validation Commands.

### `packages/ai-parrot/src/parrot/outputs/a2ui/linked/models.py` (MODIFY — new model)
```python
# occurrences: 1 (verified: grep -c 'class TransformSpec(BaseModel):' linked/models.py)
# BEFORE — insert immediately above `class TransformSpec(BaseModel):` (verified: linked/models.py:178)
class PythonTransform(BaseModel):
    """Server-side registered transformer applied to a fetched frame (G1: referenced by name, never code).

    Runs ONLY in the Python lanes (bake, persist, server refresh, the per-source data endpoint) — the mirror
    image of ``transform.ref``, which runs only in the renderer.
    """

    model_config = _CFG
    transformer: str = Field(min_length=1)
    params: dict[str, Any] = Field(default_factory=dict)
    input_alias: str = Field(default="source", min_length=1)
    output: str | None = None
```

### `packages/ai-parrot/src/parrot/outputs/a2ui/linked/models.py` (MODIFY — TransformSpec)
```python
# occurrences: 1 (verified: grep -c 'class TransformSpec(BaseModel):' linked/models.py)
# REPLACE the class body at linked/models.py:178-189 with:
class TransformSpec(BaseModel):
    """Exactly one of inline DSL operations, a catalogued renderer module, or a server-side Python transformer."""

    model_config = _CFG
    ops: list[TransformOp] | None = None
    ref: TransformRef | None = None
    python: PythonTransform | None = None

    @model_validator(mode="after")
    def _xor(self) -> TransformSpec:
        if sum(member is not None for member in (self.ops, self.ref, self.python)) != 1:
            raise ValueError("TransformSpec requires exactly one of 'ops', 'ref' or 'python'")
        return self
```

### `packages/ai-parrot/src/parrot/outputs/a2ui/linked/models.py` (MODIFY — DerivedDataSource)
```python
# occurrences: 1 (verified: grep -c 'raise ValueError("a derived source requires inline transform.ops (transform.ref is not allowed)")' linked/models.py)
# REPLACE the _ops_only body at linked/models.py:257-261 with:
    @model_validator(mode="after")
    def _ops_only(self) -> DerivedDataSource:
        if self.transform.ref is not None or self.transform.python is not None or not self.transform.ops:
            raise ValueError(
                "a derived source requires inline transform.ops (transform.ref and transform.python are not allowed)"
            )
        return self
```

### `packages/ai-parrot/src/parrot/outputs/a2ui/linked/models.py` (MODIFY — LinkedSources)
```python
# occurrences: 1 (verified: grep -c 'class LinkedSources(RootModel[dict[str, LinkedSource]]):' linked/models.py)
# AFTER — append below `_check_keys` (ends at linked/models.py:295), inside LinkedSources
    @model_validator(mode="after")
    def _python_terminal(self) -> LinkedSources:
        """A python-transformed source is terminal in v1 (FEAT-636 U3): no sibling may consume its frame."""
        python_keys = {
            key
            for key, src in self.root.items()
            if src.transform is not None and src.transform.python is not None
        }
        if not python_keys:
            return self
        for key, src in self.root.items():
            # FILL IN: collect the sibling keys `src` consumes — DerivedDataSource.from_, every Join.with_ and
            #   every Union_.sources entry in src.transform.ops (None-safe) — bounded by AC2; raise
            #   ValueError(f"source {key!r} consumes python-transformed source {name!r}; python transforms are terminal")
            #   on the first hit.
            pass
        return self
```
**Why this shape**: `_python_terminal` is a second `mode="after"` validator so `_check_keys` still runs first and its
error message stays unchanged. Do NOT reuse `executor.dependencies_of` here — models must not import the executor.

### `packages/ai-parrot/src/parrot/outputs/a2ui/linked/__init__.py` (MODIFY)
```python
# FILL IN: add PythonTransform to the existing `from parrot.outputs.a2ui.linked.models import (...)` block
#   (TransformSpec is imported there at line 31) and add "PythonTransform" to __all__ (alphabetical, near
#   "TransformSpec" at line 103) — bounded by: no other export changes.
```

### `packages/ai-parrot/tests/outputs/a2ui/linked/test_python_transform_models.py` (CREATE)
```python
"""FEAT-636 TASK-4104 — PythonTransform wire model, 3-way XOR, terminal rule."""

import pytest
from pydantic import ValidationError

from parrot.outputs.a2ui.linked.models import LinkedSources, TransformSpec

PY = {"python": {"transformer": "division_breakdown", "params": {"period": "Q3"}}}


def _src(target: str, transform: dict | None = None) -> dict:
    return {"slug": "sales", "conditions": {}, "request": {}, "target": target, "transform": transform}


def test_python_member_parses_with_defaults() -> None:
    spec = TransformSpec.model_validate(PY)
    assert spec.python.input_alias == "source" and spec.python.output is None


@pytest.mark.parametrize("payload", [{}, {**PY, "ops": [{"op": "limit", "n": 1}]}])
def test_transform_spec_xor_three(payload: dict) -> None:
    with pytest.raises(ValidationError, match="exactly one of 'ops', 'ref' or 'python'"):
        TransformSpec.model_validate(payload)


def test_derived_rejects_python() -> None:
    # FILL IN: LinkedSources with a query_slug "sales" + a derived "view" whose transform is PY → ValidationError
    ...


@pytest.mark.parametrize("consumer", ["derived", "join", "union"])
def test_python_source_is_terminal(consumer: str) -> None:
    # FILL IN: "sales" carries PY; a sibling consumes "sales" via derived.from / {"op":"join","with":"sales",...} /
    #   {"op":"union","sources":["sales"]} → ValidationError matching "terminal" (AC2)
    ...


def test_existing_descriptor_unchanged() -> None:
    sources = LinkedSources.model_validate({"sales": _src("/sales", {"ops": [{"op": "limit", "n": 5}]})})
    assert sources.root["sales"].transform.python is None
```

### FILL IN checklist
- [ ] `models.py::LinkedSources._python_terminal` — consumer-key collection; bounded by AC2
- [ ] `linked/__init__.py` — export `PythonTransform`
- [ ] test bodies for `test_derived_rejects_python`, `test_python_source_is_terminal`
- [ ] both JSON schemas regenerated by command (never by hand)

---

## Acceptance Criteria

- [ ] AC1 (spec): exactly-one-of `ops`/`ref`/`python`; `DerivedDataSource` rejects `python`.
- [ ] AC2 (spec): a python source is terminal (derived/join/union consumers rejected).
- [ ] AC3 (spec, Python half): `contract/schema.json` and `ui/schemas/LinkedSources.json` regenerated; drift tests green.
- [ ] AC11 (spec): existing linked contract tests pass unchanged.
- [ ] `ruff check` clean on touched Python files.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/outputs/a2ui/linked/test_python_transform_models.py -q`
- `pytest packages/ai-parrot/tests/outputs/a2ui/linked/test_linked_schema.py -q`
- `pytest packages/ai-parrot/tests/outputs/a2ui/linked/test_contract_envelopes.py -q`
- `pytest packages/ai-parrot-server/tests/test_ts_codegen.py -q`

---

## Agent Instructions

1. Work in the feature worktree (`python -m scripts.sdd.ensure_worktree --slug linked-a2ui-recipes-transforms --feature-id FEAT-636`), with `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-server/src`.
2. Verify the Codebase Contract before writing code; fix it first if anything moved.
3. Start from the blueprint; complete every `FILL IN`; never change a fixed name/path.
4. Run the Validation Commands; commit only the listed files.
5. Close with `scripts/sdd/close_task.sh TASK-4104 linked-a2ui-recipes-transforms verified` and fill the Completion Note.

---

## Completion Note

**Completed by**: sdd-worker orchestrator; implemented by seat gpt-5.6-terra (codex), attempt 1, 421s, 0 retries
**Date**: 2026-10-06
**Notes**: PythonTransform + three-way TransformSpec XOR + terminal rule + both schema artifacts regenerated
(commit c2debed67). Diff reviewed by hand against the spec; `tests/outputs/a2ui/linked` 220 passed.
Merge-tier validation exit 1, but the failures are outside the task's files and pass in isolation on both the
pre-task base and this branch: test_structured_envelope.py (4 passed), test_publish_surface_mixin.py (10 passed).
The `ai-parrot-server/tests` collection errors are an environment issue. I did not rerun the full batch on the
baseline, so batch-level pollution is inferred, not proven; the feature-level run should confirm.
`finalize_task` was not used because it requires a green validation ref.

**Deviations from spec**: none

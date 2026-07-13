# TASK-1720: A2UI envelope models + serialization layer

**Feature**: FEAT-273 — A2UI Protocol Integration — Rendering Core (parrot.outputs.a2ui)
**Spec**: sdd/specs/a2ui-implementation.spec.md
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Implements **Module 1** of the spec (§3, "Envelope models + serialization layer") — the foundational data contract every other FEAT-273 module builds on. A2UI v1.0 defines a six-message wire protocol; this task ships the complete message set as Pydantic v2 models plus a single serialization layer that is the SOLE owner of the `version` field and the JSONL emit format. Because A2UI v1.0 is a candidate spec with no other implementer (spec §7 risks), any future protocol fork must be absorbable in `serialization.py` alone — nothing else may read or write `version`.

---

## Scope

- Create the new package `packages/ai-parrot/src/parrot/outputs/a2ui/` (with `__init__.py`).
- Implement in `models.py` Pydantic v2 models for the complete A2UI v1.0 message set: `CreateSurface`, `UpdateComponents`, `UpdateDataModel`, `Action`, `ActionResponse`, `CallFunction` — exposed as a **discriminated union** on the message-type field (field names follow the A2UI v1.0 spec at https://a2ui.org/specification/v1.0-a2ui/).
- Implement `serialization.py` as the **single owner of the `version` field**: functions to serialize any message to a JSON dict / JSONL line (injecting `version`) and to deserialize incoming JSON/JSONL into the discriminated union (validating/stripping `version`). No model in `models.py` declares or defaults `version` itself.
- Implement **light binding-syntax validation** for data-model bindings inside component payloads: a regex-level check that binding expressions are well-formed (e.g. JSON Pointer-shaped paths). Explicitly NOT full JSON Pointer resolution — that lives in the bake pass (Module 6) in the visualizations satellite.
- Reject unknown message types on deserialization with a structured validation error.
- Write unit tests: round-trip for every message type, `version` single-owner invariant, unknown-type rejection, binding-syntax accept/reject cases.

**NOT in scope**:
- Component catalog, `ComponentDefinition`, allowlist validation (TASK-1721 / Module 2).
- Renderer registry / `AbstractA2UIRenderer` (TASK-1723 / Module 4).
- `RenderedArtifact`, baking, JSON Pointer *resolution* (Module 6 — requires `jsonpointer` dep which core must NOT gain).
- Message **dispatch** for `UpdateComponents`/`Action`/`ActionResponse`/`CallFunction` — schemas ship in v1, dispatch is FEAT-B (spec Non-Goals).
- `OutputMode.A2UI`, `AIMessage.a2ui_envelope` (Module 10).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/outputs/a2ui/__init__.py` | CREATE | Package init; re-export message models + serialization entry points |
| `packages/ai-parrot/src/parrot/outputs/a2ui/models.py` | CREATE | Complete v1.0 message set, discriminated union, binding-syntax regex validation |
| `packages/ai-parrot/src/parrot/outputs/a2ui/serialization.py` | CREATE | Sole owner of `version`; JSON/JSONL emit + parse |
| `packages/ai-parrot/tests/outputs/a2ui/__init__.py` | CREATE | Test package init |
| `packages/ai-parrot/tests/outputs/a2ui/test_models.py` | CREATE | Round-trip, discriminated-union, binding-syntax tests |
| `packages/ai-parrot/tests/outputs/a2ui/test_serialization.py` | CREATE | Version single-owner, JSONL emit, unknown-type rejection tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase.
> The implementing agent MUST use these exact imports, class names, and method signatures.
> **DO NOT** invent, guess, or assume any import, attribute, or method not listed here.
> If you need something not listed, VERIFY it exists first with `grep` or `read`.

### Verified Imports
```python
# Nothing existing needs to be imported into models.py/serialization.py beyond
# pydantic + stdlib. This module is greenfield BY DESIGN (spec G8 one-way rule).
# For reference only (do NOT import into a2ui code):
from parrot.models.outputs import OutputMode, StructuredOutputConfig  # models/outputs.py:36/:72
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/outputs/formats/__init__.py:1-2 — namespace-package
# boilerplate used across parrot.outputs subpackages (host side uses extend_path):
from pkgutil import extend_path
__path__ = extend_path(__path__, __name__)
```

### Does NOT Exist
- ~~`parrot.outputs.a2ui`~~ — this task creates it; `packages/ai-parrot/src/parrot/outputs/` today contains only `formats/`, `formatter.py`, `templates/`, `__init__.py`.
- ~~`RenderedArtifact` / `RenderedOutput` / `OutputArtifact`~~ — no reusable rendered-file model exists anywhere (Module 6 creates it).
- ~~Any A2UI models elsewhere in the repo~~ — the `STRUCTURED_*` renderers (`OutputMode.STRUCTURED_CHART/TABLE/MAP`, `models/outputs.py:67-69`) are precedent, not reusable A2UI models.

### Key Constraints (spec G1/G8)
- **Zero new core dependencies** — pydantic v2 and stdlib only. In particular NO `jsonpointer` (that dep belongs to `ai-parrot-visualizations[a2ui]`).
- **One-way import rule**: `parrot.outputs.a2ui` must NEVER import from `parrot.bots`, `parrot.clients`, agents, or DatasetManager.
- No `exec(`/`eval(` anywhere under `parrot/outputs/a2ui` (spec acceptance G1).

---

## Implementation Notes

### Pattern to Follow
Pydantic v2 discriminated union on a literal type field, e.g.:

```python
# Standard pydantic v2 pattern (illustrative — field names per A2UI v1.0 spec):
# each message: `<type_field>: Literal["createSurface"]` etc., then
# A2UIMessage = Annotated[Union[CreateSurface, ...], Field(discriminator="<type_field>")]
```

### Key Constraints
- Pydantic v2 idioms (`model_validate`, `model_dump`, `ConfigDict`) — no v1 `parse_obj`/`dict()`.
- `version` must not appear as a settable field on any model in `models.py`; `serialization.py` injects it on emit and validates it on parse. Enforce with a test.
- Binding-syntax validation: regex only (JSON Pointer *shape*, e.g. `^/[^\s]*` style paths inside binding expressions). Document in a docstring that full resolution is deferred to the bake pass.
- JSONL emit: one message per line, deterministic key ordering not required but each line must be a complete, parseable message.
- Google-style docstrings + strict type hints on every public symbol.
- Consult the A2UI v1.0 spec (https://a2ui.org/specification/v1.0-a2ui/) for exact wire field names — do not invent field names.

### References in Codebase
- `packages/ai-parrot/src/parrot/models/outputs.py` — house style for output-related Pydantic/dataclass models.
- `packages/ai-parrot/src/parrot/storage/models.py:275` (`Artifact`) — house style for Pydantic v2 models with optional refs.

---

## Acceptance Criteria

- [ ] All six v1.0 message types model correctly and round-trip: model → serialize → parse → identical model (spec G3).
- [ ] `version` is emitted by `serialization.py` and by nothing else; grep for `version` under `parrot/outputs/a2ui/` hits only `serialization.py` (+ tests).
- [ ] Unknown message type on parse → structured validation error (not a silent fallback).
- [ ] Binding-syntax validation accepts well-formed pointer-shaped bindings and rejects malformed ones; NO full JSON Pointer resolution imported or implemented.
- [ ] `grep -rn "exec(\|eval(" packages/ai-parrot/src/parrot/outputs/a2ui/` returns nothing.
- [ ] No new dependencies added to `packages/ai-parrot/pyproject.toml`.
- [ ] All tests pass: `pytest packages/ai-parrot/tests/outputs/a2ui/ -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/outputs/a2ui/`
- [ ] Imports work: `from parrot.outputs.a2ui.models import CreateSurface`

---

## Test Specification

> Minimal test scaffold. The agent must make these pass.
> Add more tests as needed.

```python
# packages/ai-parrot/tests/outputs/a2ui/test_models.py
import pytest


class TestMessageSet:
    @pytest.mark.parametrize("message_type", [
        "createSurface", "updateComponents", "updateDataModel",
        "action", "actionResponse", "callFunction",
    ])
    def test_message_set_roundtrip(self, message_type):
        """Every v1.0 message type serializes and deserializes to an identical model."""
        ...

    def test_discriminated_union_dispatch(self):
        """Parsing a dict routes to the correct concrete message class via the discriminator."""
        ...

    def test_binding_syntax_valid_pointer_accepted(self):
        """A well-formed pointer-shaped binding passes light syntax validation."""
        ...

    def test_binding_syntax_malformed_rejected(self):
        """A malformed binding expression raises a validation error."""
        ...


# packages/ai-parrot/tests/outputs/a2ui/test_serialization.py
class TestSerialization:
    def test_version_set_by_serialization_layer_only(self):
        """`version` appears in serialized output but is not a settable model field."""
        ...

    def test_jsonl_emit_one_message_per_line(self):
        """JSONL emit produces one complete parseable message per line."""
        ...

    def test_unknown_message_type_rejected(self):
        """Deserializing an unknown message type raises a structured validation error."""
        ...
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify `Depends-on` tasks are in `tasks/completed/`
3. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source)
   - Confirm every class/method in "Existing Signatures" still has the listed attributes
   - If anything has changed, update the contract FIRST, then implement
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
4. **Update status** in the per-spec index → `"in-progress"` with your session ID
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `tasks/completed/TASK-1720-a2ui-envelope-models.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: sdd-worker (Claude)
**Date**: 2026-07-11
**Notes**: Created `parrot.outputs.a2ui` package with `models.py` (complete v1.0
message set as a Pydantic v2 discriminated union on `messageType`: CreateSurface,
UpdateComponents, UpdateDataModel, Action, ActionResponse, CallFunction, plus the
`Component` adjacency node), `serialization.py` (sole owner of `version`; JSON/JSONL
serialize + deserialize via a `TypeAdapter`), and `__init__.py` re-exports.
Light binding-syntax validation implemented as a JSON-Pointer regex (`is_valid_pointer`)
plus recursive `{"$bind": "/pointer"}` scanning in `Component.properties`; full
pointer resolution deferred to the bake pass (Module 6). 18 unit tests pass; ruff
clean; no `exec(`/`eval(`; zero new core deps. `version` appears only in
`serialization.py` (models/__init__ references are docstrings only).

**Deviations from spec**: none. Wire field names (`messageType`, `surfaceId`,
`catalogId`, `dataModel`, etc.) follow A2UI v1.0 conventions cross-checked against
the sibling `infographic-theme-catalog-a2ui.spec.md` translation contract, since the
a2ui.org spec URL was not fetchable offline. Binding sigil chosen as `$bind` (a
mapping key) — documented in `models.BINDING_KEY` for downstream tasks.

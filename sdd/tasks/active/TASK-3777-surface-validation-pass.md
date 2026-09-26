# TASK-3777: validate_envelope surface-level pass + LLM-origin gate for linked sources

**Feature**: FEAT-598 — A2UI Linked Surfaces
**Spec**: `sdd/specs/a2ui-linked-surfaces.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3769, TASK-3770, TASK-3775
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 3. `validate_envelope` today only loops over components; it has no surface-level rule.
A linked surface carries its data-source descriptors at
`createSurface.metadata.extensions["parrot_data_sources"]` (G2). This task adds the **first
surface-level pass**: parse the descriptors, check their structural consistency, and gate their origin
(only TOOL-origin builders may emit a descriptor — G5, mirroring the D10b action gate and the
FEAT-473 inline-data gate). Every issue is appended to the same `issues` list so ALL problems are
reported together, exactly as today (AC2).

---

## Scope

- Add three error-code constants to `catalog/base.py`: `DATA_SOURCES_NOT_ALLOWED_FOR_LLM`,
  `DATA_SOURCE_INVALID`, `TRANSFORM_REF_UNKNOWN`.
- Import them in `catalog/__init__.py` and add `_validate_linked_sources(envelope, *, origin, issues)`.
- Call it from `validate_envelope` right before the final `if issues:` raise, only for `CreateSurface`
  envelopes (UpdateComponents has no surface metadata).
- Rules (all append issues, never raise):
  1. descriptor present + `origin is LLM` → `DATA_SOURCES_NOT_ALLOWED_FOR_LLM` (one issue, then stop
     checking this surface — an LLM envelope is rejected regardless of content).
  2. `LinkedSources.model_validate(...)` fails → one `DATA_SOURCE_INVALID` per pydantic error (message
     carries the error `loc`), then stop (nothing else is checkable).
  3. per source key `k`: `target` root key (first pointer segment) must exist in `dataModel` OR be the
     prefix of ≥ 1 component binding `{"path": ...}` → else `DATA_SOURCE_INVALID`.
  4. `locked ⊆ params` → else `DATA_SOURCE_INVALID` (the model may already enforce it — if TASK-3769's
     validator rejects it at parse time, rule 2 covers it; keep the explicit check anyway, it is cheap).
  5. every `join.with` / `union.sources` entry names ANOTHER key of the same surface → else
     `DATA_SOURCE_INVALID`.
  6. `kind == "query_slug"` (the Literal already enforces it; no extra code needed beyond rule 2).
  7. `conditions == derive_conditions(request, locked={n: conditions.get(n) for n in locked})` →
     else `DATA_SOURCE_INVALID` (S5 — `conditions` is a derived cache of `request`).
  8. `transform.ref` present → `load_manifest()`; manifest `None` OR `ref.name` not an entry →
     `TRANSFORM_REF_UNKNOWN`.
- Tests: `test_validate_linked.py`.

**NOT in scope**: the builder that emits descriptors (TASK-3778); executing sources (TASK-3780); the manifest
loader itself (TASK-3775); `integrity` equality between descriptor and manifest (renderer checks SRI at
load time, TASK-3794 — optional here: see FILL IN).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/outputs/a2ui/catalog/base.py` | MODIFY | 3 new error-code constants |
| `packages/ai-parrot/src/parrot/outputs/a2ui/catalog/__init__.py` | MODIFY | import codes; `_validate_linked_sources`; call before the aggregate raise |
| `packages/ai-parrot/tests/outputs/a2ui/linked/test_validate_linked.py` | CREATE | AC2 tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.outputs.a2ui.catalog import ProducerOrigin, validate_envelope        # catalog/__init__.py:499 (validate_envelope)
from parrot.outputs.a2ui.catalog.base import CatalogValidationError             # catalog/base.py:307 (.issues: list[dict])
from parrot.outputs.a2ui.models import CreateSurface, Component, SurfaceMetadata, Extensions   # models.py:446,341,378
# net-new — import LAZILY inside _validate_linked_sources (one-way import rule, spec §7 last gotcha):
from parrot.outputs.a2ui.linked.models import LinkedSources                     # TASK-3769
from parrot.outputs.a2ui.linked.conditions import derive_conditions             # TASK-3770
from parrot.outputs.a2ui.linked.manifest import load_manifest                   # TASK-3775 -> TransformManifest | None
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/outputs/a2ui/catalog/__init__.py
from parrot.outputs.a2ui.catalog.base import (   # L37-58 — tuple import; TOOL_ONLY_NOT_ALLOWED_FOR_LLM at L45
    ACTION_NOT_ALLOWED_FOR_LLM, CATALOG_UNRESOLVED, DANGLING_CHILD, DEFAULT_CATALOG_ID, DUPLICATE_ID,
    INLINE_DATA_NOT_ALLOWED_FOR_LLM, MISSING_ROOT, TOOL_ONLY_NOT_ALLOWED_FOR_LLM, UNALLOWED_CHILD, ...
)
def validate_envelope(envelope: CreateSurface | UpdateComponents, *, origin: ProducerOrigin = ProducerOrigin.TOOL,
                      surface_catalog_id: str | None = None) -> None:   # L499
    issues: list[dict[str, Any]] = []                                   # L553 — issues are DICTS {"code","message","path"}
    # D10b action gate L621-632; tool_only gate L634-644; inline-data gate L646-685
    if issues:                                                          # L717 — the single aggregate raise
        raise CatalogValidationError(summary, issues=issues, unknown_components=..., action_components=...)

# packages/ai-parrot/src/parrot/outputs/a2ui/catalog/base.py
TOOL_ONLY_NOT_ALLOWED_FOR_LLM = "TOOL_ONLY_NOT_ALLOWED_FOR_LLM"         # L86 (comment-documented constants L60-86)
class ProducerOrigin(str, Enum): TOOL = "tool"; LLM = "llm"             # L89-98

# packages/ai-parrot/src/parrot/outputs/a2ui/models.py
class CreateSurface(A2UIMessageBase):                                   # L446
    components: list[Component]; data_model: dict[str, Any]  (alias dataModel); metadata: SurfaceMetadata | None  # L468-470
class Extensions(RootModel[dict[str, Any]])                             # L341 — read the mapping via `.root`
SurfaceMetadata = ComponentMetadata  # {extensions: Extensions | None}  # L378
# Component props are pydantic extras: `comp.model_extra` (same idiom as the inline-data gate L647)
```

### Does NOT Exist
- ~~`ValidationIssue` (class)~~ — spec §3 M3 skeleton names it, but it does NOT exist: issues are plain
  dicts `{"code", "message", "path"}` (catalog/__init__.py:553, base.py:307 docstring). Type the
  parameter as `list[dict[str, Any]]`.
- ~~A surface-level rule loop in `validate_envelope`~~ — net-new (this task).
- ~~`DATA_SOURCES_NOT_ALLOWED_FOR_LLM`, `DATA_SOURCE_INVALID`, `TRANSFORM_REF_UNKNOWN`~~ — net-new.
- ~~Module-level `import parrot.outputs.a2ui.linked...` in `catalog/`~~ — forbidden; import inside the function.
- ~~`Extensions.get(...)`~~ — it is a RootModel; use `envelope.metadata.extensions.root.get(...)`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/outputs/a2ui/catalog/base.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/outputs/a2ui/catalog/__init__.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/outputs/a2ui/linked/test_validate_linked.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/outputs/a2ui/catalog/__init__.py#validate_envelope",
    "sym:packages/ai-parrot/src/parrot/outputs/a2ui/catalog/base.py#CatalogValidationError",
    "sym:packages/ai-parrot/src/parrot/outputs/a2ui/catalog/base.py#ProducerOrigin",
    "sym:packages/ai-parrot/src/parrot/outputs/a2ui/models.py#CreateSurface",
    "sym:packages/ai-parrot/src/parrot/outputs/a2ui/models.py#Extensions"
  ]
}
```

---

## Implementation Notes

### Pattern to Follow
The D10b gate (catalog/__init__.py:617-632) and the inline-data gate (L646-685): check `origin is
ProducerOrigin.LLM`, append a dict issue with `code`, `message`, `path`, continue. `path` for surface
issues: `f"parrot_data_sources.{key}"` (or `"parrot_data_sources"` for whole-surface issues).

### Key Constraints
- Never raise from `_validate_linked_sources` — only append (AC2 "reported together").
- Zero behaviour change for envelopes without the extension: return immediately when
  `metadata is None`, `extensions is None`, or the key is absent (AC11 — every existing golden and
  test stays green).
- An empty mapping (`parrot_data_sources: {}`) is treated as "no descriptor" (matches
  `has_data_sources` semantics in TASK-3769: non-empty mapping).
- The lazy import of `linked.manifest` must not fail if `STATIC_DIR` is unset: `load_manifest()` returns
  `None` in that case (per TASK-3775), which makes any `ref` `TRANSFORM_REF_UNKNOWN` — correct fail-closed.

### References in Codebase
- `catalog/__init__.py:617-685` — gate idioms; `catalog/__init__.py:717` — aggregate raise.

---

## Implementation Blueprint

### Steps (in order)
1. Add the three constants to `base.py` — *why*: codes are module constants, like every other code.
2. Import them in `catalog/__init__.py` inside the existing tuple import — *why*: same idiom as the
   other codes.
3. Add `_validate_linked_sources` as a private function ABOVE `validate_envelope` — *why*: keeps
   `validate_envelope` readable and makes the pass unit-testable.
4. Call it right before `    if issues:` — *why*: its issues join the single aggregate raise.
5. Write the tests — *why*: AC2.

### `packages/ai-parrot/src/parrot/outputs/a2ui/catalog/base.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'TOOL_ONLY_NOT_ALLOWED_FOR_LLM = "TOOL_ONLY_NOT_ALLOWED_FOR_LLM"' packages/ai-parrot/src/parrot/outputs/a2ui/catalog/base.py)
# AFTER — insert below `TOOL_ONLY_NOT_ALLOWED_FOR_LLM = "TOOL_ONLY_NOT_ALLOWED_FOR_LLM"` (verified: catalog/base.py:86)
#: An LLM-originated envelope carries ``metadata.extensions.parrot_data_sources`` (FEAT-598 G5 —
#: only deterministic TOOL-origin builders may emit linked data-source descriptors).
DATA_SOURCES_NOT_ALLOWED_FOR_LLM = "DATA_SOURCES_NOT_ALLOWED_FOR_LLM"
#: A linked data-source descriptor is malformed or inconsistent: model parse error, unbound
#: ``target``, ``locked`` ⊄ ``params``, a ``join.with``/``union.sources`` naming no sibling, or
#: ``conditions`` ≠ ``derive_conditions(request)`` (FEAT-598 M3/S5).
DATA_SOURCE_INVALID = "DATA_SOURCE_INVALID"
#: A ``transform.ref`` names no entry of the signed transforms manifest (or no valid manifest is
#: available) (FEAT-598 M9/S6).
TRANSFORM_REF_UNKNOWN = "TRANSFORM_REF_UNKNOWN"
```
**Why**: identical comment-then-constant layout as L60-86.

### `packages/ai-parrot/src/parrot/outputs/a2ui/catalog/__init__.py` (MODIFY) — import
```python
# occurrences: 1 (verified: grep -c '    TOOL_ONLY_NOT_ALLOWED_FOR_LLM,' packages/ai-parrot/src/parrot/outputs/a2ui/catalog/__init__.py)
# Inside `from parrot.outputs.a2ui.catalog.base import (` (L37): insert the two DATA_* names after
# `    DANGLING_CHILD,` (L40) and TRANSFORM_REF_UNKNOWN after `    TOOL_ONLY_NOT_ALLOWED_FOR_LLM,` (L45),
# keeping the tuple alphabetical:
    DANGLING_CHILD,
    DATA_SOURCE_INVALID,
    DATA_SOURCES_NOT_ALLOWED_FOR_LLM,
    ...
    TOOL_ONLY_NOT_ALLOWED_FOR_LLM,
    TRANSFORM_REF_UNKNOWN,
```

### `packages/ai-parrot/src/parrot/outputs/a2ui/catalog/__init__.py` (MODIFY) — the pass
```python
# occurrences: 1 (verified: grep -c 'def validate_envelope(' packages/ai-parrot/src/parrot/outputs/a2ui/catalog/__init__.py)
# BEFORE — insert immediately above `def validate_envelope(` (verified: catalog/__init__.py:499)
_DATA_SOURCES_KEY = "parrot_data_sources"


def _binding_paths(value: Any) -> list[str]:
    """Collect every ``{"path": "..."}`` binding pointer nested anywhere in a prop value."""
    # FILL IN: recursive walk over dict/list; a dict whose only/defining key is "path" with a str value
    #   is a binding; bounded by the v1.0 wire binding shape (models.py Binding / a2ui-types.ts Binding).
    raise NotImplementedError


def _validate_linked_sources(envelope: CreateSurface, *, origin: ProducerOrigin, issues: list[dict[str, Any]]) -> None:
    """Surface-level pass over ``metadata.extensions.parrot_data_sources`` (FEAT-598 M3).

    Appends issues (never raises): origin gate, model parse, target binding, ``locked ⊆ params``,
    sibling refs of join/union, ``conditions == derive_conditions(request, locked=…)`` (S5), and
    ``transform.ref ∈ manifest`` (S6).
    """
    meta = envelope.metadata
    raw = meta.extensions.root.get(_DATA_SOURCES_KEY) if meta is not None and meta.extensions is not None else None
    if not raw:
        return
    if origin is ProducerOrigin.LLM:
        issues.append({"code": DATA_SOURCES_NOT_ALLOWED_FOR_LLM, "path": _DATA_SOURCES_KEY,
                       "message": "LLM-produced envelopes may not carry linked data-source descriptors."})
        return

    from pydantic import ValidationError

    from parrot.outputs.a2ui.linked.conditions import derive_conditions
    from parrot.outputs.a2ui.linked.models import LinkedSources

    try:
        sources = LinkedSources.model_validate(raw).root
    except ValidationError as exc:
        for err in exc.errors():
            issues.append({"code": DATA_SOURCE_INVALID, "path": _DATA_SOURCES_KEY,
                           "message": f"{'.'.join(str(p) for p in err['loc'])}: {err['msg']}"})
        return

    bound_roots = {p.split("/")[1] for c in envelope.components for v in (c.model_extra or {}).values()
                   for p in _binding_paths(v) if p.startswith("/") and len(p.split("/")) > 1}
    manifest = None
    for key, src in sources.items():
        path = f"{_DATA_SOURCES_KEY}.{key}"
        # FILL IN rules 3-5 and 7 from Scope (target root in data_model or bound_roots; locked ⊆ params;
        #   join.with / union.sources ∈ sources.keys() - {key}; conditions == derive_conditions(
        #   src.request, locked={n: src.conditions.get(n) for n in src.locked})) — one DATA_SOURCE_INVALID
        #   each, message naming the offending value; bounded by AC2.
        if src.transform is not None and src.transform.ref is not None:
            if manifest is None:
                from parrot.outputs.a2ui.linked.manifest import load_manifest

                manifest = load_manifest() or False
            # FILL IN: TRANSFORM_REF_UNKNOWN when manifest is False or src.transform.ref.name not in its
            #   entries (use TASK-3775's TransformManifest attribute name); bounded by AC9 / S6.
```
**Why**: lazy imports keep the one-way rule (`linked` never imports `catalog`; `catalog` touches
`linked` only at call time). The locked values are read back from `conditions` because the descriptor
stores locked NAMES only — the forced value lives in `conditions` (it is the only place it exists).

### `packages/ai-parrot/src/parrot/outputs/a2ui/catalog/__init__.py` (MODIFY) — the call
```python
# occurrences: 1 (verified: grep -c '    if issues:' packages/ai-parrot/src/parrot/outputs/a2ui/catalog/__init__.py)
# BEFORE — insert immediately above `    if issues:` (verified: catalog/__init__.py:717)
    if isinstance(envelope, CreateSurface):
        _validate_linked_sources(envelope, origin=origin, issues=issues)

```
**Why**: surface issues join the one aggregate `CatalogValidationError` (AC2). Also add one bullet to
`validate_envelope`'s docstring "Checks:" list describing the surface pass.

### `packages/ai-parrot/tests/outputs/a2ui/linked/test_validate_linked.py` (CREATE)
```python
"""Surface-level linked-source validation (FEAT-598 M3, AC2)."""

import pytest

from parrot.outputs.a2ui.catalog import ProducerOrigin, validate_envelope
from parrot.outputs.a2ui.catalog.base import CatalogValidationError
from parrot.outputs.a2ui.models import CreateSurface


def _envelope(sources: dict, data_model: dict | None = None) -> CreateSurface:
    # FILL IN: a Chart root bound to {"path": "/activity/rows"}, metadata.extensions.parrot_data_sources=sources,
    #   using the `linked_source` fixture (tests/outputs/a2ui/linked/conftest.py, TASK-3769) dumped mode="json".
    raise NotImplementedError


def _codes(exc: CatalogValidationError) -> list[str]:
    return [i["code"] for i in exc.issues]


def test_validate_linked_tool_origin_ok(linked_source) -> None: ...          # FILL IN
def test_validate_linked_llm_origin_rejected(linked_source) -> None: ...     # FILL IN: DATA_SOURCES_NOT_ALLOWED_FOR_LLM
def test_validate_linked_target_unbound(linked_source) -> None: ...          # FILL IN
def test_validate_linked_locked_not_in_params(linked_source) -> None: ...    # FILL IN
def test_validate_linked_join_with_unknown_key(linked_source) -> None: ...   # FILL IN
def test_validate_linked_conditions_mismatch(linked_source) -> None: ...     # FILL IN (S5)
def test_validate_linked_ref_not_in_manifest(linked_source, monkeypatch) -> None: ...  # FILL IN: monkeypatch load_manifest -> None
def test_validate_linked_issues_reported_together(linked_source) -> None: ...  # FILL IN: ≥2 codes in ONE raise
def test_envelope_without_descriptor_unchanged() -> None: ...                # FILL IN: plain Chart envelope still validates
```

### FILL IN checklist
- [ ] `_binding_paths` — recursive walk
- [ ] rules 3, 4, 5, 7 in `_validate_linked_sources`; bounded by AC2 / S5
- [ ] rule 8 (manifest lookup); bounded by AC9 / S6 — optional: also flag `integrity` ≠ manifest entry as `TRANSFORM_REF_UNKNOWN`
- [ ] test bodies

---

## Acceptance Criteria

- [ ] `origin=TOOL` + valid descriptor passes; `origin=LLM` → `DATA_SOURCES_NOT_ALLOWED_FOR_LLM` (AC2)
- [ ] unbound target, `locked ⊄ params`, unknown join/union sibling, conditions mismatch → `DATA_SOURCE_INVALID`; unknown ref → `TRANSFORM_REF_UNKNOWN`; all in one raise (AC2)
- [ ] No module-level import of `parrot.outputs.a2ui.linked` in `catalog/`
- [ ] Existing a2ui tests unchanged and green (AC11): `pytest packages/ai-parrot/tests/outputs/a2ui/test_catalog.py -q`
- [ ] `ruff check` clean on both modified files

---

## Validation Commands

- `pytest packages/ai-parrot/tests/outputs/a2ui/linked/test_validate_linked.py -q`
- `pytest packages/ai-parrot/tests/outputs/a2ui/test_catalog.py -q`
- `pytest packages/ai-parrot/tests/outputs/a2ui/test_builders.py -q`

---

## Test Specification

As in the test block; each named test is a spec §4 row (`test_validate_linked_llm_origin_rejected`,
`test_validate_linked_target_unbound` / `_locked_not_in_params` / `_join_with_unknown_key` /
`_ref_not_in_manifest`, `test_validate_linked_conditions_mismatch`).

---

## Agent Instructions

1. Read spec §3 M3, §2 Data Models; read TASK-3769 models, TASK-3770 `derive_conditions`, TASK-3775 `load_manifest`.
2. Verify TASK-3769, TASK-3770, TASK-3775 are done.
3. Re-run the three `grep -c` anchors above; implement; fill every `# FILL IN:`.
4. Run the Validation Commands (worktree: `PYTHONPATH=packages/ai-parrot/src`).
5. Commit only the listed files; update the index; fill the Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: `ValidationIssue` does not exist — issues typed as `list[dict[str, Any]]` (decided at task time).

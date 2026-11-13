# TASK-5633: Procedure graph models and package exports

**Feature**: FEAT-891 — Procedural Graph Plane
**Spec**: `sdd/specs/procedural-graph-plane.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 1 and §2 "Data Models". Every other module of the feature imports these models.
The package `__init__.py` declares every public name of the whole package once (lazy exports),
so no later task edits it.

---

## Scope

- Create the package `parrot.knowledge.wiki.procedure` with `models.py` and a lazy `__init__.py`.
- Implement every model of spec §2 "Data Models" except `ProcedureSettings` (it belongs to
  `parrot/sdd/config.py`, TASK-5643).
- Add `uncovered_ok: list[str]` to `ProcedureManifest` (spec §3 Module 9).
- Add the constants `INDEX_SCHEMA_VERSION`, `PLANE_DIR`, `INDEX_FILE`, `EDGE_FIELDS` and the method
  `ProcedureSpec.edges()`.
- Create the test package `packages/ai-parrot/tests/knowledge/wiki/procedure/` and `test_models.py`.

**NOT in scope**: producers, validation, index, plane, resolver, operations (later tasks). Do not
create those modules; the lazy `__init__.py` only names them.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/procedure/__init__.py` | CREATE | PEP 562 lazy exports for the whole package |
| `packages/ai-parrot/src/parrot/knowledge/wiki/procedure/models.py` | CREATE | Pydantic models and constants |
| `packages/ai-parrot/tests/knowledge/wiki/procedure/__init__.py` | CREATE | Empty test package marker |
| `packages/ai-parrot/tests/knowledge/wiki/procedure/test_models.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `9a3a611b0c` (dev).

### Verified Imports
```python
from pydantic import BaseModel, ConfigDict, Field, model_validator   # pydantic v2, existing dependency
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/wiki/schema/__init__.py:8-41  (the lazy-export pattern to copy)
_EXPORTS: dict[str, str] = {"SchemaSourceConfig": "models", ...}   # public name -> submodule
__all__ = sorted(_EXPORTS)
def __getattr__(name: str) -> Any:
    try:
        module = importlib.import_module(f"{__name__}.{_EXPORTS[name]}")
    except KeyError as exc:
        raise AttributeError(name) from exc
    return getattr(module, name)
```

### Does NOT Exist
- ~~`parrot.knowledge.wiki.procedure`~~ — this task creates it.
- ~~`packages/ai-parrot/tests/knowledge/wiki/procedure/`~~ — this task creates it. Sibling test
  directories (`tests/knowledge/wiki/schema/`) are packages with an `__init__.py`.
- ~~`ProcedureSettings` in this package~~ — it is defined in `parrot/sdd/config.py` by TASK-5643.
- ~~`WikiPageCategory.PROCEDURE`~~ — no such enum member; the store's `category` is an open string.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/knowledge/wiki/procedure/__init__.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/src/parrot/knowledge/wiki/procedure/models.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/knowledge/wiki/procedure/__init__.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/knowledge/wiki/procedure/test_models.py", "action": "CREATE"}
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

- Conventions: `.claude/rules/codebase-conventions.md` (Pydantic v2, Google docstrings, type hints).
- In a worktree prefix tests with `PYTHONPATH=packages/ai-parrot/src`.
- Use `Field(default_factory=list)` / `Field(default_factory=dict)` for every list or dict default.
- `models.py` imports only `pathlib`, `typing` and `pydantic`. It must not import `parrot.sdd` or
  the wiki store.

---

## Implementation Blueprint

### Steps (in order)
1. Write `models.py` — *why*: every other task imports from it.
2. Write `__init__.py` with the full export table below — *why*: later tasks add modules, not
   exports, so two tasks never edit this file.
3. Write the tests and the empty test `__init__.py` — *why*: later test files live in this package.

### `packages/ai-parrot/src/parrot/knowledge/wiki/procedure/models.py` (CREATE)
```python
"""Procedure graph models (FEAT-891)."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

ProcedureMode = Literal["advisory", "mandatory", "constraint"]
ProcedureKind = Literal["command", "skill", "flow", "crew", "rule"]
ProcedureSource = Literal["authored", "learned"]
EdgeRel = Literal["requires", "next", "alternative_to", "escalates_to", "on_failure", "learned_from", "applies_to"]
ProbeCost = Literal["local", "remote"]
GuardKind = Literal["entry", "bypass"]

INDEX_SCHEMA_VERSION = 1
PLANE_DIR = Path(".parrot") / "procedure"
INDEX_FILE = "procedures.json"
#: ProcedureSpec field name -> edge relation.
EDGE_FIELDS: dict[str, str] = {
    "requires_procedures": "requires",
    "next": "next",
    "alternative_to": "alternative_to",
    "escalates_to": "escalates_to",
    "on_failure": "on_failure",
    "learned_from": "learned_from",
    "applies_to": "applies_to",
}


class ScopeArg(BaseModel):
    """Where a guard reads one scope value from a command line."""

    argv: int | None = None  # positional index after argv_prefix
    flag: str | None = None  # e.g. "--base"; alternatives separated by "|" ("--base|-B")

    @model_validator(mode="after")
    def _exactly_one(self) -> "ScopeArg":
        """Require exactly one of ``argv`` and ``flag``."""
        if (self.argv is None) == (self.flag is None):
            raise ValueError("ScopeArg needs exactly one of 'argv' and 'flag'")
        return self


# FILL IN: ProbeCheck, GuardSpec, ExecutorRef, ProcedureSpec, ProcedureManifest, ProbeResult,
# ResolvedProcedure, Resolution — copy every field, default and comment VERBATIM from spec §2
# "Data Models" (ProcedureSpec and ProcedureManifest keep model_config = ConfigDict(extra="forbid")).
# Add to ProcedureManifest:  uncovered_ok: list[str] = Field(default_factory=list)
# Add to ProcedureSpec the method below.


class ProcedureSpec(BaseModel):
    """One procedure node, independent of how the procedure is implemented."""

    model_config = ConfigDict(extra="forbid")

    def edges(self) -> list[tuple[str, str, str]]:
        """Return ``(src, dst, rel)`` for every id listed in an edge field.

        ``applies_to`` targets are entity type names and are returned as ``type:<Name>``.
        """
        out: list[tuple[str, str, str]] = []
        for field_name, rel in EDGE_FIELDS.items():
            for target in getattr(self, field_name):
                dst = f"type:{target}" if field_name == "applies_to" else target
                out.append((self.id, dst, rel))
        return out
```
**Why this shape**: the field list is fixed by spec §2, so it is copied, not redesigned. `edges()`
is the single place that maps fields to relations; the validator, the plane and the index all call
it. Define the classes in dependency order (`ProbeCheck`, `ScopeArg`, `GuardSpec`, `ExecutorRef`
before `ProcedureSpec`).

### `packages/ai-parrot/src/parrot/knowledge/wiki/procedure/__init__.py` (CREATE)
```python
"""Procedure plane — what to do next, as a wikitoolkit overlay plane (FEAT-891)."""

from __future__ import annotations

import importlib
from typing import Any

_EXPORTS: dict[str, str] = {
    **dict.fromkeys(
        ("ProbeCheck", "ScopeArg", "GuardSpec", "ExecutorRef", "ProcedureSpec", "ProcedureManifest", "ProbeResult",
         "ResolvedProcedure", "Resolution", "INDEX_SCHEMA_VERSION", "PLANE_DIR", "INDEX_FILE", "EDGE_FIELDS"),
        "models",
    ),
    **dict.fromkeys(("MANIFEST_DIR", "load_manifest", "manifest_specs", "skill_spec", "skill_specs"), "producers"),
    **dict.fromkeys(("GraphFinding", "validate_graph"), "validate"),
    **dict.fromkeys(("compile_index", "publish_index", "read_index", "is_stale"), "index"),
    "ProcedurePlane": "plane",
    **dict.fromkeys(("ProbeRunner", "resolve"), "resolver"),
    **dict.fromkeys(("ProcedureNextInput", "op_procedure_next", "procedure_plane_available"), "operations"),
}
__all__ = sorted(_EXPORTS)


def __getattr__(name: str) -> Any:
    """Resolve a public name from its submodule on first access."""
    try:
        module = importlib.import_module(f"{__name__}.{_EXPORTS[name]}")
    except KeyError as exc:
        raise AttributeError(name) from exc
    return getattr(module, name)
```
**Why**: same pattern as `wiki/schema/__init__.py`. Names whose module does not exist yet resolve
only when a later task has created that module; nothing here imports them eagerly.

### `packages/ai-parrot/tests/knowledge/wiki/procedure/test_models.py` (CREATE)
```python
"""Tests for the procedure graph models (FEAT-891)."""

import pytest
from pydantic import ValidationError

from parrot.knowledge.wiki.procedure.models import EDGE_FIELDS, ProcedureManifest, ProcedureSpec, ScopeArg


def _spec(**overrides):
    return ProcedureSpec(**{"id": "sdd:a", "title": "A", "kind": "command", **overrides})


def test_spec_edges() -> None:
    """Every edge field maps to its relation; applies_to targets get the type: prefix."""
    # FILL IN: build a spec with one target in each EDGE_FIELDS field and assert the exact tuple list.


def test_models_forbid_extra() -> None:
    """Unknown keys are rejected in ProcedureSpec and ProcedureManifest."""
    # FILL IN: pytest.raises(ValidationError) for an unknown key in each model.


def test_scope_arg_needs_exactly_one() -> None:
    """ScopeArg rejects neither and both of argv / flag."""
    # FILL IN


def test_lazy_exports_resolve_models() -> None:
    """The package resolves model names lazily and rejects unknown names."""
    # FILL IN: `from parrot.knowledge.wiki import procedure`; procedure.ProcedureSpec is ProcedureSpec;
    # getattr(procedure, "nope") raises AttributeError. Do NOT `import *` (later modules do not exist yet).
```

### FILL IN checklist
- [ ] `models.py` — the eight model classes, copied verbatim from spec §2; `uncovered_ok` on the manifest
- [ ] `test_models.py` — the four test bodies; bounded by the docstrings above

---

## Acceptance Criteria

- [ ] `from parrot.knowledge.wiki.procedure import ProcedureSpec, ProcedureManifest, Resolution` works.
- [ ] `ProcedureSpec` and `ProcedureManifest` reject unknown keys.
- [ ] `ProcedureSpec.edges()` returns one tuple per listed id with the relation from `EDGE_FIELDS`.
- [ ] `models.py` imports nothing from `parrot.sdd` or `parrot.knowledge.wiki.store`.
- [ ] `ruff check` passes on the new files.

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/wiki/procedure/test_models.py -q`

---

## Agent Instructions

1. Work in the feature worktree (`parrot sdd worktree ensure --slug procedural-graph-plane --feature-id FEAT-891`), never on `dev`.
2. Verify the Codebase Contract before writing code; if an entry is stale, fix it in this file first.
3. Implement only the files listed above; complete every `FILL IN`; never change a name the blueprint fixes.
4. Run `ruff check --fix` on the touched files and the Validation Commands.
5. Commit the code, then close with `parrot sdd task close TASK-5633 procedural-graph-plane verified` and fill in the Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

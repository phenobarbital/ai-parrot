# TASK-4464: Query & result contracts + error taxonomy (M2)

**Feature**: FEAT-704 — Semantic Layer — governed metric queries for agents (`ai-parrot-semantic`)
**Spec**: `sdd/specs/semantic-layer.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4463
**Assigned-to**: unassigned

---

## Context

Spec §2 Data Models and §3 Module 2: the pydantic request/response contracts every other module consumes (`SemanticQuery`, `CompiledQuery`, `GovernedQuery`, `SemanticQueryResult`, `ModelMember`) and the `SemanticError` hierarchy.

---

## Scope

- Implement `packages/ai-parrot-semantic/src/parrot/semantic/errors.py`: `SemanticError(code, details)` and the five subclasses.
- Implement `packages/ai-parrot-semantic/src/parrot/semantic/models.py`: `Grain`, `FilterOp`, `TimeDimension`, `FilterLeaf`, `FilterGroup`, `OrderBy`, `SemanticQuery` (+ `canonical_json`, `validate_against`), `CompiledQuery`, `GovernedQuery`, `SemanticQueryResult`, `ModelMember`, `Limits`.
- Model validators: `saved_query` XOR `metrics`; `offset > 0` requires `order_by`; `limit >= 1` when set; `extra="forbid"`.
- Write `test_models.py`.

**NOT in scope**: member-kind resolution against a real model (TASK-4467/4473 call `validate_against`); policy models (TASK-4465).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-semantic/src/parrot/semantic/errors.py` | CREATE | exception hierarchy |
| `packages/ai-parrot-semantic/src/parrot/semantic/models.py` | CREATE | pydantic contracts |
| `packages/ai-parrot-semantic/tests/test_models.py` | CREATE | validator tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase
> (re-verified on `dev` @ 754878f67, 2026-10-19). Use these exact imports, class names and
> method signatures. **DO NOT** invent, guess or assume anything not listed here — verify first.
> `grep` in this repo is aliased to `ugrep` by RTK: use `grep -F` for anchors with `(`, `[`, `{`.

### Verified Imports
```python
from pydantic import BaseModel, ConfigDict, Field, model_validator   # pydantic v2 (core dependency)
import json
```

### Existing Signatures to Use
```python
# packages/ai-parrot-semantic/src/parrot/semantic/__init__.py (TASK-4463)
__all__ = ["__version__"]
```

### Does NOT Exist
- ~~`Limits` in core~~ — defined here (`default: int = 1000`, `max: int = 10000`); TASK-4465's `ModelPolicy.limits` uses it.
- ~~`ModelMember.sensitive` driving masking~~ — masking is policy-driven (TASK-4471); `sensitive` is descriptive only.
- ~~pydantic `model_dump_json(sort_keys=...)`~~ — not a pydantic option; use `json.dumps(self.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-semantic/src/parrot/semantic/errors.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-semantic/src/parrot/semantic/models.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-semantic/tests/test_models.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

- Field lists are fixed verbatim by spec §2 Data Models — copy them; do not rename.
- `FilterGroup.items` is recursive: call `FilterGroup.model_rebuild()` after the class.

### Key Constraints
- Async-first; sync CPU-only work (sqlglot, sidemantic compile) runs under `asyncio.to_thread` at the call site.
- Pydantic v2 models; `logging.getLogger(__name__)` / `self.logger`, never `print`.
- Google-style docstrings, strict type hints, 120-column lines; `ruff check` clean (TID251 bans apply).
- Fail closed wherever governance is involved (spec §7 "Patterns to Follow").
- Worktree testing: prefix pytest with `PYTHONPATH=packages/ai-parrot-semantic/src:packages/ai-parrot/src` (add `:packages/ai-parrot-server/src` for server tests); never `uv sync` inside a worktree.

---

## Implementation Blueprint

> **Executor-ready starting point.** Write each block to its declared path nearly verbatim,
> then complete every `# FILL IN:` marker. Never change a signature, class name or path the
> blueprint fixes (they come from the spec §3 Interface Skeletons).

### Steps (in order)
1. Write `errors.py` — *why*: models raise `SemanticValidationError`.
2. Write `models.py` copying spec §2 field lists — *why*: the contracts are fixed by the spec.
3. Implement `canonical_json` and `validate_against` — *why*: cache keys (AC8) and mixed WHERE/HAVING rejection (spec §7).
4. Write the tests.

### `packages/ai-parrot-semantic/src/parrot/semantic/errors.py` (CREATE)
```python
"""Semantic-layer exception hierarchy (spec §3 Module 2)."""
from __future__ import annotations

from typing import Any


class SemanticError(Exception):
    """Base for all semantic-layer errors.

    Args:
        code: Stable machine-readable error code (e.g. ``"no_credentials"``).
        message: Human-readable message; NEVER contains SQL or subject values.
        details: Extra structured context (suggestions, audit_id, ...).
    """

    def __init__(self, code: str, message: str = "", *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message or code)
        self.code = code
        self.details: dict[str, Any] = details or {}


class SemanticValidationError(SemanticError):
    """Malformed or unsatisfiable SemanticQuery (unknown member, mixed filter group, missing grain, fan-out)."""


class SemanticPolicyError(SemanticError):
    """Invalid model/policy definition (unknown member, sidemantic `security:` block, bad RLS binding)."""


class SemanticAccessError(SemanticError):
    """Denied: no PermissionContext, evaluator unavailable, PBAC denial, member not granted, usage right, lineage."""


class SemanticExecutionError(SemanticError):
    """Database execution failed; ``details['audit_id']`` set; SQL never in the message."""


class SemanticResultError(SemanticError):
    """Result handle unknown, foreign, expired or stale (context/policy changed)."""
```

### `packages/ai-parrot-semantic/src/parrot/semantic/models.py` (CREATE)
```python
"""Pydantic request/response contracts (spec §2 Data Models)."""
from __future__ import annotations

import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .errors import SemanticValidationError

Grain = Literal["second", "minute", "hour", "day", "week", "month", "quarter", "year"]
FilterOp = Literal["equals", "not_equals", "in", "not_in", "contains", "gt", "gte", "lt", "lte",
                   "between", "is_set", "not_set", "in_date_range", "before_date", "after_date"]


class Limits(BaseModel):
    """Row limits from the policy file."""
    default: int = 1000
    max: int = 10000


class ModelMember(BaseModel):
    """One metric/dimension of a loaded model, as the catalog sees it."""
    name: str
    kind: Literal["metric", "dimension", "time_dimension", "entity"]
    description: str = ""
    grain: Grain | None = None
    sensitive: bool = False

# FILL IN: TimeDimension, FilterLeaf, FilterGroup (+ FilterGroup.model_rebuild()), OrderBy —
#          fields verbatim from spec §2 Data Models


class SemanticQuery(BaseModel):
    """Structured metric query; credential-like/unknown fields are rejected (extra=forbid)."""
    model_config = ConfigDict(extra="forbid")
    # FILL IN: fields verbatim from spec §2 (model, metrics, dimensions, time_dimensions, filters,
    #          order_by, limit, offset, timezone, saved_query)

    @model_validator(mode="after")
    def _check_shape(self) -> "SemanticQuery":
        # FILL IN: saved_query XOR metrics (exactly one present); offset>0 requires order_by; limit>=1 —
        #          raise ValueError (pydantic wraps it) — bounded by spec §3 M2 validators
        return self

    def canonical_json(self) -> str:
        """Sorted-key, whitespace-free JSON used in CompiledQuery.cache_key."""
        return json.dumps(self.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))

    def validate_against(self, member_kinds: dict[str, str], time_dimensions: set[str]) -> None:
        """Raise SemanticValidationError for unknown members, mixed filter groups, missing grains."""
        # FILL IN: unknown metric/dimension/order/filter member -> code "unknown_member";
        #          a FilterGroup whose leaves mix metric and dimension kinds -> "mixed_filter_group";
        #          a time_dimensions entry naming a time dimension with grain None -> "grain_required"
        raise NotImplementedError

# FILL IN: CompiledQuery(frozen), GovernedQuery(frozen), SemanticQueryResult — verbatim from spec §2
```
**Why**: the spec fixes every field; the validator split (shape in `model_validator`, model-dependent checks in `validate_against`) is spec §3 M2.

### FILL IN checklist
- [ ] Remaining model classes verbatim from spec §2.
- [ ] `_check_shape` rules — bounded by spec §3 M2.
- [ ] `validate_against` error codes — `unknown_member` / `mixed_filter_group` / `grain_required`.

---

## Acceptance Criteria

- [ ] `test_semantic_query_validators` and `test_canonical_json_stable` pass.
- [ ] `SemanticQuery(model='m', metrics=['x'], password='p')` raises `ValidationError` (extra=forbid).
- [ ] `CompiledQuery`/`GovernedQuery` are frozen (assignment raises).

---

## Validation Commands

> File-level pytest only — no directories, no package roots. Run with `PYTHONPATH=packages/ai-parrot-semantic/src:packages/ai-parrot/src` in a worktree.

- `pytest packages/ai-parrot-semantic/tests/test_models.py -q`

---

## Test Specification

```python
# packages/ai-parrot-semantic/tests/test_models.py
import pytest
from pydantic import ValidationError
from parrot.semantic.models import SemanticQuery, FilterGroup, FilterLeaf
from parrot.semantic.errors import SemanticValidationError


def test_semantic_query_validators():
    """saved_query XOR metrics; offset needs order_by; mixed filter group; grain required."""
    with pytest.raises(ValidationError):
        SemanticQuery(model="orders", metrics=["revenue"], saved_query="monthly")
    with pytest.raises(ValidationError):
        SemanticQuery(model="orders", metrics=["revenue"], offset=10)
    q = SemanticQuery(model="orders", metrics=["revenue"],
                      filters=FilterGroup(op="and", items=[FilterLeaf(member="revenue", op="gt", values=[1]),
                                                           FilterLeaf(member="region", op="equals", values=["n"])]))
    with pytest.raises(SemanticValidationError):
        q.validate_against({"revenue": "metric", "region": "dimension"}, set())
    # FILL IN: grain_required case


def test_canonical_json_stable():
    a = SemanticQuery(model="orders", metrics=["revenue"], dimensions=["region"])
    b = SemanticQuery(dimensions=["region"], metrics=["revenue"], model="orders")
    assert a.canonical_json() == b.canonical_json()
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `dev`
   (`python -m scripts.sdd.ensure_worktree --slug semantic-layer --feature-id FEAT-704 --spec sdd/specs/semantic-layer.spec.md --index sdd/tasks/index/semantic-layer.json`).
2. **Read the spec** (`sdd/specs/semantic-layer.spec.md`), especially the sections named in Context.
3. **Check dependencies** — every `Depends-on` task is `done` in `sdd/tasks/index/semantic-layer.json`.
4. **Verify the Codebase Contract** before writing code; fix a stale entry in this file first.
5. **Implement** exactly the files above, following the blueprint; touch nothing else.
6. **Validate**: `ruff check --fix <files>`, then the Validation Commands.
7. **Commit** only the listed files: `feat(semantic-layer): TASK-4464 — Query & result contracts + error taxonomy (M2)`.
8. **Close** with `scripts/sdd/close_task.sh TASK-4464 semantic-layer verified` and fill in the Completion Note.

---

## Completion Note


- Task: TASK-4464
- Feature: semantic-layer
- Implementation SHA: 6de327d670649e4f233da5b3b67bf41c2e7d3172
- Closed at (UTC): 2026-10-19T12:38:35+00:00
- Fix commits: none

| Metric | Value |
|---|---|
| validation_refs | 1 |
| fix_commits | 0 |
| seat_summary | Seat: gpt-5.6-terra · Backend: codex · Model: gpt-5.6-terra · Attempts: 1 · Duration: 77.7s · Tokens: n/a |

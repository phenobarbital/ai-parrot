# TASK-4465: Model policy side-file (M3)

**Feature**: FEAT-704 — Semantic Layer — governed metric queries for agents (`ai-parrot-semantic`)
**Spec**: `sdd/specs/semantic-layer.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4464
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 3 + §8 Q4: parse `<model>.policy.yaml` into `ModelPolicy` — role grants, masks, RLS rules, saved queries, limits and the additive `allowed_functions` extension — and answer role questions for the catalog and the governance pipeline.

---

## Scope

- Implement `packages/ai-parrot-semantic/src/parrot/semantic/policy.py`: `RoleGrant`, `MaskRule`, `SavedQuery`, `ModelPolicy` (+ `digest`, `allowed_members`, `usage_allowed`, `mask_for`), `load_policy`.
- `governed` defaults to `true`; unknown members/tables/roles syntax → `SemanticPolicyError`; missing `connection` when governed → error.
- `allowed_functions: list[str]` — upper-cased at load; anything not a bare SQL identifier (`^[A-Za-z_][A-Za-z0-9_]*$`) → `SemanticPolicyError` (§8 Q4, §7 risk).
- Parse every `rls[].predicate_template` with sqlglot at load (placeholders → typed dummies): single boolean expression over columns of its table, else error.
- Write `test_policy.py`.

**NOT in scope**: registering RLS rules into a registry (TASK-4477 does it at toolkit construction); the positive guard's use of `allowed_functions` (TASK-4471).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-semantic/src/parrot/semantic/policy.py` | CREATE | policy side-file parser |
| `packages/ai-parrot-semantic/tests/test_policy.py` | CREATE | policy tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase
> (re-verified on `dev` @ 754878f67, 2026-10-19). Use these exact imports, class names and
> method signatures. **DO NOT** invent, guess or assume anything not listed here — verify first.
> `grep` in this repo is aliased to `ugrep` by RTK: use `grep -F` for anchors with `(`, `[`, `{`.

### Verified Imports
```python
from parrot.auth import RlsRule                       # verified: packages/ai-parrot/src/parrot/auth/__init__.py:47 (lazy map); class at auth/rls_registry.py:49
from parrot.semantic.models import SemanticQuery, ModelMember, Limits   # TASK-4464
from parrot.semantic.errors import SemanticPolicyError                 # TASK-4464
import sqlglot; from sqlglot import exp                                # sqlglot 30.23.0 in venv
import yaml, hashlib, json
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/auth/rls_registry.py
class RlsRule(BaseModel):   # line 49
    driver: str; table: str; predicate_template: str; subject_attribute: str; description: str = ""   # lines 63-67
    # predicate_template uses ":subject.<attr>" placeholders; table is "schema.table"
```

### Does NOT Exist
- ~~`ModelPolicy.remove_functions` / a deny-list~~ — `allowed_functions` is additive only (§8 Q4).
- ~~`RlsRule.validate_template()`~~ — no such method; the sqlglot parse at load is implemented here.
- ~~`load_policy` reading the sidemantic model~~ — it receives `members` and `tables` from the loader (TASK-4467).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-semantic/src/parrot/semantic/policy.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-semantic/tests/test_policy.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/auth/rls_registry.py#RlsRule"
  ]
}
```

---

## Implementation Notes

- Policy YAML example: spec §2 Data Models (`<model>.policy.yaml`).
- `digest()` = SHA-256 hex of `json.dumps(self.model_dump(mode='json'), sort_keys=True)` — part of every cache key and audit entry.

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
1. Write the models from the spec §3 M3 skeleton — *why*: fixed contract.
2. Implement role answers — *why*: catalog (TASK-4473) and lineage (TASK-4469) depend on them.
3. Implement `load_policy` with member/table/function/RLS validation — *why*: a misspelled binding must never silently remove a restriction.
4. Write the tests.

### `packages/ai-parrot-semantic/src/parrot/semantic/policy.py` (CREATE)
```python
"""`<model>.policy.yaml` side-file: grants, masks, RLS, saved queries (spec §3 Module 3)."""
from __future__ import annotations

import hashlib
import json
import re
from datetime import date
from pathlib import Path
from typing import Literal

import sqlglot
import yaml
from pydantic import BaseModel, Field

from parrot.auth import RlsRule
from .errors import SemanticPolicyError
from .models import Limits, ModelMember, SemanticQuery

_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class RoleGrant(BaseModel):
    metrics: list[str] | Literal["*"] = Field(default_factory=list)
    dimensions: list[str] | Literal["*"] = Field(default_factory=list)
    usage: list[str] | Literal["*"] = Field(default_factory=list)


class MaskRule(BaseModel):
    strategy: Literal["null", "hash", "partial"]
    projection_roles: list[str] = Field(default_factory=list)
    usage_roles: list[str] = Field(default_factory=list)


class SavedQuery(BaseModel):
    name: str
    query: SemanticQuery
    verified_by: str
    verified_at: date
    description: str = ""


class ModelPolicy(BaseModel):
    governed: bool = True
    engine: Literal["sidemantic", "native"] = "sidemantic"
    connection: str | None = None
    limits: Limits = Field(default_factory=Limits)
    roles: dict[str, RoleGrant] = Field(default_factory=dict)
    masks: dict[str, MaskRule] = Field(default_factory=dict)
    rls: list[RlsRule] = Field(default_factory=list)
    saved_queries: list[SavedQuery] = Field(default_factory=list)
    allowed_functions: list[str] = Field(default_factory=list)   # §8 Q4 — additive only

    def digest(self) -> str:
        """SHA-256 of canonical JSON — part of every cache key and audit entry."""
        raw = json.dumps(self.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(raw.encode()).hexdigest()

    def allowed_members(self, roles: frozenset[str], members: list[ModelMember]) -> set[str]:
        """Union of grants over the subject's roles; empty set when no role matches."""
        # FILL IN: "*" expands to every metric (resp. dimension/time_dimension) name in `members`
        raise NotImplementedError

    def usage_allowed(self, roles: frozenset[str], column: str) -> bool:
        """True only when a grant lists the column in `usage` (or "*"); masked columns need `usage_roles`."""
        # FILL IN: masked column (key in self.masks) -> roles ∩ mask.usage_roles non-empty, regardless of grants
        raise NotImplementedError

    def mask_for(self, roles: frozenset[str], column: str) -> MaskRule | None:
        """Mask to apply in projection, or None when the column is unmasked for these roles."""
        # FILL IN: masked + roles ∩ projection_roles empty -> rule; else None
        raise NotImplementedError


def load_policy(path: Path, members: list[ModelMember], tables: set[str]) -> ModelPolicy:
    """Parse and validate a policy file.

    Raises:
        SemanticPolicyError: unknown member/table, bad function name, missing `connection` when governed,
            or an RLS `predicate_template` that is not a single boolean expression over its table's columns.
    """
    # FILL IN: yaml.safe_load; ModelPolicy.model_validate (pydantic errors -> SemanticPolicyError("invalid_policy"));
    #   every grant/mask/saved-query member must exist in `members` ("unknown_member"); mask keys "table.column"
    #   and rls tables must be in `tables` ("unknown_table"); allowed_functions: _IDENT check then .upper();
    #   rls templates: replace ":subject.<attr>" with a typed dummy literal, sqlglot.parse_one(f"SELECT 1 WHERE {tpl}"),
    #   the WHERE must be one boolean expression (no subquery / no exp.Command)
    raise NotImplementedError
```
**Why this shape**: verbatim spec §3 M3 skeleton plus `allowed_functions` (§8 Q4). `connection` is optional in the model so the governed-requires-connection rule is enforced in `load_policy` with a precise error code.

### FILL IN checklist
- [ ] `allowed_members` — `*` expansion; bounded by AC19.
- [ ] `usage_allowed` / `mask_for` — bounded by AC6.
- [ ] `load_policy` validation — bounded by AC15 (unknown members rejected) and §8 Q4.

---

## Acceptance Criteria

- [ ] `test_policy_unknown_member_rejected`, `test_policy_defaults_governed`, `test_policy_allowed_functions_additive` (policy half) pass.
- [ ] A policy with an RLS template `region IN (:subject.programs); DROP TABLE x` is rejected at load.
- [ ] `ModelPolicy().digest()` is stable across key order.

---

## Validation Commands

> File-level pytest only — no directories, no package roots. Run with `PYTHONPATH=packages/ai-parrot-semantic/src:packages/ai-parrot/src` in a worktree.

- `pytest packages/ai-parrot-semantic/tests/test_policy.py -q`

---

## Test Specification

```python
# packages/ai-parrot-semantic/tests/test_policy.py
import pytest
from parrot.semantic.policy import load_policy
from parrot.semantic.models import ModelMember
from parrot.semantic.errors import SemanticPolicyError

MEMBERS = [ModelMember(name="revenue", kind="metric"), ModelMember(name="region", kind="dimension")]
TABLES = {"sales.orders", "dim.customers"}


def test_policy_unknown_member_rejected(tmp_path):
    p = tmp_path / "orders.policy.yaml"
    p.write_text("connection: wh\nroles:\n  analyst: {metrics: [revenu]}\n")
    with pytest.raises(SemanticPolicyError):
        load_policy(p, MEMBERS, TABLES)


def test_policy_defaults_governed(tmp_path):
    # FILL IN: missing `governed` -> True; `governed: false` honoured (connection optional then)
    ...


def test_policy_allowed_functions_additive(tmp_path):
    # FILL IN: `allowed_functions: [regexp_replace]` -> ["REGEXP_REPLACE"]; `["x; drop"]` rejected
    ...
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
7. **Commit** only the listed files: `feat(semantic-layer): TASK-4465 — Model policy side-file (M3)`.
8. **Close** with `scripts/sdd/close_task.sh TASK-4465 semantic-layer verified` and fill in the Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:
**Deviations from spec**: none | describe if any

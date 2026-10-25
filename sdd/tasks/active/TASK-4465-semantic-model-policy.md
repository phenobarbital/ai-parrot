# TASK-4465: Model policy validation and role grants (M3)

**Feature**: FEAT-704 — Semantic Layer — governed metric queries for agents
**Spec**: `sdd/specs/semantic-layer.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2–4h)
**Depends-on**: TASK-4464
**Assigned-to**: unassigned
**Spec revision**: 0.4

## Context

Spec rev 0.4, §3 M3; replaces the prior task text for this same reserved identity. The unmerged branch is a salvage reference only; no completion state is inherited.

## Scope

- Implement ModelPolicy/RoleGrant/MaskRule/SavedQuery and load_policy exactly as the spec; remove the engine field and reject unknown keys. Governed defaults true.
- Validate policy members, physical table references and RLS template boolean expressions before use. Unknown bindings must fail rather than remove restrictions.
- Union matching role grants, distinguish usage from projection and mask exemptions; implement additive function allowlist and canonical policy digest. Expand model-local saved query definitions with the enclosing model before validating SemanticQuery.

**NOT in scope**: changes outside the target table; provider SDK calls; a third-party semantic engine; symmetric aggregates; reviving the removed M12 core RLS work. Blueprint gaps are planning instructions only and must not survive in implementation files.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-semantic/src/parrot/semantic/policy.py` | CREATE | Scoped deliverable per blueprint |
| `packages/ai-parrot-semantic/tests/test_policy.py` | CREATE | Focused regression evidence |

## Codebase Contract (Anti-Hallucination)

Verified against main-checkout `dev` at `c431642e2` on 2026-10-25. Existing source definitions below were re-read. Satellite imports are **planned contracts**, not claims that those files already exist on dev; their producer tasks must land first.

### Verified Imports

```python
from .errors import SemanticPolicyError
from .models import Limits, ModelMember, SemanticQuery
from __future__ import annotations
from datetime import date
from parrot.auth import RlsRule
from pathlib import Path
from pydantic import BaseModel, Field
from typing import Literal
import hashlib
import json
import pytest
import re
import sqlglot
import yaml
```

Standard-library imports are built in; pydantic v2, sqlglot, PyYAML/jsonschema and pytest are governed by existing metadata and M1's explicit dependency/extra declarations. Reverify optional backend imports in the implementation environment. Relative satellite imports below resolve within the target package and are bounded by the listed dependency contracts.

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/auth/rls_registry.py:49
class RlsRule(BaseModel):
```

### Dependency Contracts and Parallelism Evidence

- TASK-4464: consumes packages/ai-parrot-semantic/src/parrot/semantic/errors.py, packages/ai-parrot-semantic/src/parrot/semantic/models.py (Query/result contracts and trusted identity model (M2))

- Consumer-specific evidence: SemanticQuery/ModelMember in models.py and SemanticPolicyError in errors.py

### Does NOT Exist

- `parrot.semantic` on dev — the package and symbols are created by this graph, never imported from the salvage branch environment.
- A semantic engine selector, sidemantic adapter or sidemantic parity oracle — native SQL generation is the only path.
- `PermissionContext.session_id` or `.agent_id` — the satellite identity contract carries trusted scope; request_id is not a session id.
- Automatic semantic authorization in `DatasetManager.add_dataframe()` — retained snapshots require the guarded host-sink contract.

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

## Implementation Notes

- Keep the scope and signatures fixed by spec rev 0.4. Complete the bounded blueprint gaps, not a broad refactor. Preserve the clean-room rule: do not open sidemantic source/API glue.
- Use async I/O, Pydantic v2, strict types and Google-style docstrings. CPU SQL passes run off the event loop. Use logging, not print; black/ruff are the format/lint gates.
- Run in the feature worktree with the existing venv activated; never repair the shared environment. Write test logs to `artifacts/logs/`.
- The full-file snippets below are starting points. Recheck dependency-created MODIFY anchors after their tasks land; they cannot be falsely reported verified on dev today.

## Implementation Blueprint

### Steps (in order)

1. Verify existing anchors and dependency contracts — because stale signatures invalidate a mechanical implementation.
2. Implement the listed targets in their blueprint order — because each target has one explicit owner and the graph orders shared writers.
3. Complete all scope-specific validation branches and regression scenarios — because success-path-only tests cannot establish the required fail-closed behavior.
4. Run this task's validation commands and focused lint — because only evidence from its declared files closes this task.

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
    connection: str
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

**Why**: this file implements the scoped responsibility above; preserve its public contract and complete its marked decisions under the task acceptance criteria.

### `packages/ai-parrot-semantic/tests/test_policy.py` (CREATE)

```python
"""Regression contract: Model policy validation and role grants (M3)."""
from pathlib import Path
import pytest


def test_governed_defaults_and_unknown_bindings(tmp_path: Path) -> None:
    """Verify governed defaults and unknown bindings."""
    # FILL IN: arrange isolated inputs, exercise public behavior, assert the exact
    # result/denial and side effects required by this task scope and spec ACs.
    # For async paths use pytest.mark.asyncio and async def; never nest asyncio.run.
    ...


def test_role_usage_and_mask_permissions(tmp_path: Path) -> None:
    """Verify role usage and mask permissions."""
    # FILL IN: arrange isolated inputs, exercise public behavior, assert the exact
    # result/denial and side effects required by this task scope and spec ACs.
    # For async paths use pytest.mark.asyncio and async def; never nest asyncio.run.
    ...


def test_typed_rls_template_and_additive_functions(tmp_path: Path) -> None:
    """Verify typed rls template and additive functions."""
    # FILL IN: arrange isolated inputs, exercise public behavior, assert the exact
    # result/denial and side effects required by this task scope and spec ACs.
    # For async paths use pytest.mark.asyncio and async def; never nest asyncio.run.
    ...
```

**Why**: this file implements the scoped responsibility above; preserve its public contract and complete its marked decisions under the task acceptance criteria.

### FILL IN checklist

- [ ] `packages/ai-parrot-semantic/src/parrot/semantic/policy.py` — complete the bounded behavior, validation and error paths in its blueprint; no unfinished placeholders in the implementation.
- [ ] `packages/ai-parrot-semantic/tests/test_policy.py` — complete the bounded behavior, validation and error paths in its blueprint; no unfinished placeholders in the implementation.

## Acceptance Criteria

- [ ] Implement ModelPolicy/RoleGrant/MaskRule/SavedQuery and load_policy exactly as the spec; remove the engine field and reject unknown keys. Governed defaults true.
- [ ] Validate policy members, physical table references and RLS template boolean expressions before use. Unknown bindings must fail rather than remove restrictions.
- [ ] Union matching role grants, distinguish usage from projection and mask exemptions; implement additive function allowlist and canonical policy digest. Expand model-local saved query definitions with the enclosing model before validating SemanticQuery.
- [ ] The task-specific regression cases below pass; focused black/ruff checks pass on changed code. No unrelated target is modified.

## Validation Commands

- `pytest packages/ai-parrot-semantic/tests/test_policy.py -q`

## Test Specification

- `test_governed_defaults_and_unknown_bindings`: assert the observable behavior and denial/cleanup effects described in Scope; use deterministic isolated fixtures.
- `test_role_usage_and_mask_permissions`: assert the observable behavior and denial/cleanup effects described in Scope; use deterministic isolated fixtures.
- `test_typed_rls_template_and_additive_functions`: assert the observable behavior and denial/cleanup effects described in Scope; use deterministic isolated fixtures.

## Agent Instructions

Use `$sdd-start TASK-4465` in the feature worktree; it provisions isolation. Read spec/dependencies, reverify contracts, implement only declared targets, run validation and commit code. Use `scripts.sdd.finalize_task` with real TaskCompletionEvidence and the exact implementation HEAD; do not use close_task.sh or manually move/stamp completion artifacts.

## Completion Note

Populated only by the authorized completion workflow with implementation/validation evidence. Task planning is not completion.

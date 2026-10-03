# TASK-4022: Entity vocabulary and strict frontmatter normalization

---

**Feature**: FEAT-627 — wikitoolkit standup: entity attributes and daily/period briefs
**Spec**: `sdd/specs/wikitoolkit-standup.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2–4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Implement spec M3 and AC3. Keep the vocabulary pure: no store, CLI, click or framework imports. Preserve unknown scalars as x_ keys; coerce dates, alias meeting-source/issue and meeting_date/primary_project/due_date. Keep status_raw for every input status. Canonical status must belong to its resolved type. Preserve x_assignee_id and x_assignee for Jira matching; do not introduce email fields. Unknown type is omitted in lenient mode and rejected in strict mode. Parse only a leading YAML block, using the delimiter and top-level-key rules of repo_scan; log malformed input at DEBUG. Copy the complete status and alias tables from spec section 2, not a second taxonomy.

---

## Scope

Implement spec M3 and AC3. Keep the vocabulary pure: no store, CLI, click or framework imports. Preserve unknown scalars as x_ keys; coerce dates, alias meeting-source/issue and meeting_date/primary_project/due_date. Keep status_raw for every input status. Canonical status must belong to its resolved type. Preserve x_assignee_id and x_assignee for Jira matching; do not introduce email fields. Unknown type is omitted in lenient mode and rejected in strict mode. Parse only a leading YAML block, using the delimiter and top-level-key rules of repo_scan; log malformed input at DEBUG. Copy the complete status and alias tables from spec section 2, not a second taxonomy.

**NOT in scope**: changes outside the declared file table; new runtime dependencies; unrelated cleanup. Follow the approved v1 non-goals for backend parity and pre-existing ledger import cost.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/entities.py` | CREATE | The inbox feature consumes this exact import-light API; no persistence belongs here. |
| `packages/ai-parrot/tests/knowledge/wiki/test_entities.py` | CREATE | Cover the full vocabulary and malformed input matrix. |

---

## Codebase Contract (Anti-Hallucination)

Verified at `75fe680a0`. Dependency-created imports below are planned contracts, not claims of current existence.

### Verified Imports

```python
from collections.abc import Mapping  # stdlib or existing pyproject dependency/test environment
from datetime import date, datetime  # stdlib or existing pyproject dependency/test environment
from typing import Any, Literal  # stdlib or existing pyproject dependency/test environment
import logging  # stdlib or existing pyproject dependency/test environment
import yaml  # stdlib or existing pyproject dependency/test environment
from pydantic import BaseModel, Field  # stdlib or existing pyproject dependency/test environment
from pathlib import Path  # stdlib or existing pyproject dependency/test environment
import pytest  # stdlib or existing pyproject dependency/test environment
import parrot.knowledge.wiki.entities as subject  # planned in TASK-4022; not present before that task
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/repo_scan.py:524
def _markdown_summary(content: str) -> str:
```

### Does NOT Exist

- `packages/ai-parrot/src/parrot/knowledge/wiki/entities.py` is created by this task; do not assume it already exists.
- `packages/ai-parrot/tests/knowledge/wiki/test_entities.py` is created by this task; do not assume it already exists.
- `list_pages(offset=...)`, `DecisionRecord.updated_at`, and a JiraPerson email field are not existing APIs. Do not invent them.
- Category names remain open strings; no new WikiPageCategory enum members are required.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/wiki/entities.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/wiki/test_entities.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/repo_scan.py#_markdown_summary"
  ]
}
```

---

## Implementation Notes

Independent entity-vocabulary deliverable; uses existing verified code only and owns its declared files.

Use async I/O paths, existing lifecycle/context managers, module logging, strict types and Google-style docstrings. Black uses 120 columns; ruff is the lint gate. Keep tests isolated and file-scoped. Fresh dependency code may shift anchors: reverify before edits, and retain the semantic attachment site.

---

## Implementation Blueprint

### Steps (in order)

1. Verify the existing references and completed dependency interfaces — because the blueprint must match the executing worktree.
2. Apply the per-file blocks below in declared order and complete only bounded FILL IN work — because each task owns a limited surface.
3. Implement the listed adversarial cases and run Validation Commands — because the acceptance criteria cover observable behavior, not only imports.

---

### `packages/ai-parrot/src/parrot/knowledge/wiki/entities.py` (CREATE)

```python
"""Pure entity vocabulary and frontmatter normalization."""
from collections.abc import Mapping
from datetime import date, datetime
from typing import Any, Literal
import logging
import yaml
from pydantic import BaseModel, Field

EntityType = Literal["project", "engagement", "meeting", "ticket", "task", "decision", "deliverable", "person"]
# FILL IN: define STATUS_BY_TYPE, OPEN_STATUSES, URGENT_STATUSES, ATTR_KEYS,
# TYPE_ALIASES and KEY_ALIASES exactly as spec section 2; AC3 bounds all values.
logger = logging.getLogger(__name__)

class EntityValidationError(ValueError):
    """Strict normalization error with a stable machine-readable code."""
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code

class EntityAttrs(BaseModel):
    """Validated entity fields and prefixed scalar extensions."""
    type: EntityType | None = None
    status: str | None = None
    status_raw: str | None = None
    project: str | None = None
    date: str | None = None
    due: str | None = None
    owner: str | None = None
    source: str | None = None
    language: str | None = None
    extra: dict[str, str] = Field(default_factory=dict)
    def to_rows(self) -> dict[str, str]:
        """Flatten non-null fields and x_-prefixed extensions to string rows."""
        # FILL IN: omit nulls and preserve extension strings; AC3.
        raise NotImplementedError

def normalize_frontmatter(fm: Mapping[str, Any], *, source: str, strict: bool = False) -> EntityAttrs:
    """Normalize aliases, dates and per-type statuses; optionally reject invalid values."""
    # FILL IN: implement the normalization cases listed in this task; AC3.
    raise NotImplementedError

def parse_leading_yaml(text: str) -> dict[str, Any] | None:
    """Return a leading YAML mapping, or None for missing/invalid frontmatter."""
    # FILL IN: match verified delimiter/key rules without importing repo_scan; AC3.
    raise NotImplementedError

def canonical_ticket_status(raw: str | None, status_map: Mapping[str, str]) -> str | None:
    """Map a case-insensitive raw ticket status, returning None when unmapped."""
    # FILL IN: normalize lookup case without inventing a fallback status; AC11.
    raise NotImplementedError
```

**Why**: The inbox feature consumes this exact import-light API; no persistence belongs here.

---

### `packages/ai-parrot/tests/knowledge/wiki/test_entities.py` (CREATE)

```python
"""Regression cases for FEAT-627."""
from pathlib import Path
import pytest
import parrot.knowledge.wiki.entities as subject


def test_normalize_aliases_dates_and_statuses(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify normalize aliases dates and statuses."""
    # FILL IN: build isolated inputs and assert the corresponding AC below.
    # Use pytest.mark.asyncio / async def when exercising async APIs.
    raise NotImplementedError


def test_strict_errors_and_malformed_yaml(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify strict errors and malformed yaml."""
    # FILL IN: build isolated inputs and assert the corresponding AC below.
    # Use pytest.mark.asyncio / async def when exercising async APIs.
    raise NotImplementedError


def test_canonical_ticket_status_map(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify canonical ticket status map."""
    # FILL IN: build isolated inputs and assert the corresponding AC below.
    # Use pytest.mark.asyncio / async def when exercising async APIs.
    raise NotImplementedError
```

**Why**: Cover the full vocabulary and malformed input matrix.

---

### FILL IN checklist

- [ ] `packages/ai-parrot/src/parrot/knowledge/wiki/entities.py` — complete the block instructions and tests within this task’s acceptance criteria; leave no implementation placeholders.
- [ ] `packages/ai-parrot/tests/knowledge/wiki/test_entities.py` — complete the block instructions and tests within this task’s acceptance criteria; leave no implementation placeholders.

---

## Acceptance Criteria

- [ ] AC3: all eight entity types, complete per-type STATUS_BY_TYPE and OPEN_STATUSES match the spec.
- [ ] FEAT-481 aliases, project-list first element/x_projects, ISO date/datetime coercion and canonical/raw statuses are deterministic.
- [ ] Strict errors carry E_ENTITY_TYPE, E_ENTITY_STATUS or E_ENTITY_DATE; malformed YAML/non-mappings return None without crashing.
- [ ] Case-insensitive ticket mapping returns None for unknown values; import loads neither cli nor store.
- [ ] All declared-file tests pass; no ruff errors or unfinished implementation placeholders remain.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/wiki/test_entities.py -q`

---

## Test Specification

- AC3: all eight entity types, complete per-type STATUS_BY_TYPE and OPEN_STATUSES match the spec.
- FEAT-481 aliases, project-list first element/x_projects, ISO date/datetime coercion and canonical/raw statuses are deterministic.
- Strict errors carry E_ENTITY_TYPE, E_ENTITY_STATUS or E_ENTITY_DATE; malformed YAML/non-mappings return None without crashing.
- Case-insensitive ticket mapping returns None for unknown values; import loads neither cli nor store.

Use temporary local state, deterministic clocks and fake network/model adapters. Test failures and negative cases as well as success. New tests live alongside the core distribution; legacy suites are validation references only unless explicitly declared MODIFY above.

---

## Agent Instructions

1. Run `$sdd-start TASK-4022`; implementation belongs in the feature worktree, never directly on dev.
2. Read the approved spec and verify dependency completion in `sdd/tasks/index/wikitoolkit-standup.json`.
3. Recheck imports/anchors, implement only declared files and run the validation commands.
4. Commit scoped implementation and finalize with `scripts.sdd.finalize_task` plus real `TaskCompletionEvidence` for the exact implementation HEAD. Do not manually move the task or manufacture completion evidence.

## Completion Note

Pending; owned by the evidence-based finalizer.

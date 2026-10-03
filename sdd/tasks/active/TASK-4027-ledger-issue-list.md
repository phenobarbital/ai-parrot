# TASK-4027: Public ledger open and claimed issue inventory

---

**Feature**: FEAT-627 — wikitoolkit standup: entity attributes and daily/period briefs
**Spec**: `sdd/specs/wikitoolkit-standup.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Implement the ledger half of M8/AC16. Add list_issues next to ready_work, preserving existing ready_work behavior. Sync best-effort first; select statuses, optional kind and any about path starting with about_prefix. Return _issue_dict rows, including claimed_by, ordered by (SEVERITY_ORDER, issue_id). Do not invent timestamps.

---

## Scope

Implement the ledger half of M8/AC16. Add list_issues next to ready_work, preserving existing ready_work behavior. Sync best-effort first; select statuses, optional kind and any about path starting with about_prefix. Return _issue_dict rows, including claimed_by, ordered by (SEVERITY_ORDER, issue_id). Do not invent timestamps.

**NOT in scope**: changes outside the declared file table; new runtime dependencies; unrelated cleanup. Follow the approved v1 non-goals for backend parity and pre-existing ledger import cost.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py` | MODIFY | Consumers must not call the private _all_issues API directly. |
| `packages/ai-parrot/tests/knowledge/wiki/test_ledger_list_issues.py` | CREATE | Use a temporary ledger root and real event projection. |

---

## Codebase Contract (Anti-Hallucination)

Verified at `75fe680a0`. Dependency-created imports below are planned contracts, not claims of current existence.

### Verified Imports

```python
from collections.abc import Sequence  # stdlib or existing pyproject dependency/test environment
from typing import Any  # stdlib or existing pyproject dependency/test environment
from parrot.knowledge.wiki.ledger.events import IssueKind  # verified source packages/ai-parrot/src/parrot/knowledge/wiki/ledger/events.py
from pathlib import Path  # stdlib or existing pyproject dependency/test environment
import pytest  # stdlib or existing pyproject dependency/test environment
import parrot.knowledge.wiki.ledger.service as subject  # verified source packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py:201
    async def ready_work(self, kind: IssueKind | None = None) -> list[dict[str, Any]]:

# packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py:152
    async def _all_issues(self) -> list[tuple[str, dict[str, Any]]]:

# packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py:80
def _issue_dict(issue_id: str, state: dict[str, Any]) -> dict[str, Any]:
```

### Does NOT Exist

- `packages/ai-parrot/tests/knowledge/wiki/test_ledger_list_issues.py` is created by this task; do not assume it already exists.
- `list_pages(offset=...)`, `DecisionRecord.updated_at`, and a JiraPerson email field are not existing APIs. Do not invent them.
- Category names remain open strings; no new WikiPageCategory enum members are required.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/wiki/test_ledger_list_issues.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py#LedgerService.ready_work",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py#LedgerService._all_issues",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py#_issue_dict"
  ]
}
```

---

## Implementation Notes

Independent ledger-issue-list deliverable; uses existing verified code only and owns its declared files.

Use async I/O paths, existing lifecycle/context managers, module logging, strict types and Google-style docstrings. Black uses 120 columns; ruff is the lint gate. Keep tests isolated and file-scoped. Fresh dependency code may shift anchors: reverify before edits, and retain the semantic attachment site.

---

## Implementation Blueprint

### Steps (in order)

1. Verify the existing references and completed dependency interfaces — because the blueprint must match the executing worktree.
2. Apply the per-file blocks below in declared order and complete only bounded FILL IN work — because each task owns a limited surface.
3. Implement the listed adversarial cases and run Validation Commands — because the acceptance criteria cover observable behavior, not only imports.

---

### `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py` (MODIFY)

Anchor `    async def ready_work(self, kind: IssueKind | None = None) -> list[dict[str, Any]]:` — occurrences: 1 (verified: `grep -F -c`), `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py:201`.

```python
from collections.abc import Sequence
from typing import Any
from parrot.knowledge.wiki.ledger.events import IssueKind
# Add collections.abc.Sequence to imports; use existing Any/IssueKind/SEVERITY_ORDER.
async def list_issues(
    self, statuses: Sequence[str] = ("open", "claimed"), *,
    kind: IssueKind | None = None, about_prefix: str | None = None,
) -> list[dict[str, Any]]:
    """List issues by status, optional kind and about-path prefix, severity first."""
    # FILL IN: sync, project through _issue_dict, filter and sort; AC16.
    raise NotImplementedError
```

**Why**: Consumers must not call the private _all_issues API directly.

---

### `packages/ai-parrot/tests/knowledge/wiki/test_ledger_list_issues.py` (CREATE)

```python
"""Regression cases for FEAT-627."""
from pathlib import Path
import pytest
import parrot.knowledge.wiki.ledger.service as subject


def test_status_filters_and_order(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify status filters and order."""
    # FILL IN: build isolated inputs and assert the corresponding AC below.
    # Use pytest.mark.asyncio / async def when exercising async APIs.
    raise NotImplementedError


def test_ready_work_unchanged(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify ready work unchanged."""
    # FILL IN: build isolated inputs and assert the corresponding AC below.
    # Use pytest.mark.asyncio / async def when exercising async APIs.
    raise NotImplementedError
```

**Why**: Use a temporary ledger root and real event projection.

---

### FILL IN checklist

- [ ] `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py` — complete the block instructions and tests within this task’s acceptance criteria; leave no implementation placeholders.
- [ ] `packages/ai-parrot/tests/knowledge/wiki/test_ledger_list_issues.py` — complete the block instructions and tests within this task’s acceptance criteria; leave no implementation placeholders.

---

## Acceptance Criteria

- [ ] Default inventory includes open and claimed, excludes closed/superseded; explicit statuses work.
- [ ] Kind/about-prefix filters and deterministic severity ties work; ready_work remains open/unclaimed.
- [ ] All declared-file tests pass; no ruff errors or unfinished implementation placeholders remain.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/wiki/test_ledger_list_issues.py -q`
- `pytest tests/knowledge/wiki/test_ledger_service.py -q`

---

## Test Specification

- Default inventory includes open and claimed, excludes closed/superseded; explicit statuses work.
- Kind/about-prefix filters and deterministic severity ties work; ready_work remains open/unclaimed.

Use temporary local state, deterministic clocks and fake network/model adapters. Test failures and negative cases as well as success. New tests live alongside the core distribution; legacy suites are validation references only unless explicitly declared MODIFY above.

---

## Agent Instructions

1. Run `$sdd-start TASK-4027`; implementation belongs in the feature worktree, never directly on dev.
2. Read the approved spec and verify dependency completion in `sdd/tasks/index/wikitoolkit-standup.json`.
3. Recheck imports/anchors, implement only declared files and run the validation commands.
4. Commit scoped implementation and finalize with `scripts.sdd.finalize_task` plus real `TaskCompletionEvidence` for the exact implementation HEAD. Do not manually move the task or manufacture completion evidence.

## Completion Note

Pending; owned by the evidence-based finalizer.

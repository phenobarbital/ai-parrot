# TASK-4036: Project resolution and deterministic brief grouping

---

**Feature**: FEAT-627 — wikitoolkit standup: entity attributes and daily/period briefs
**Spec**: `sdd/specs/wikitoolkit-standup.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-4031
**Assigned-to**: unassigned

---

## Context

Implement M5 grouping. Resolve project_hint as project page ID then title slug, configured project_map, raw Jira project key, SDD feature slug, then Internal. Fetch project metadata through ctx.store without mutation. Assign blocked/tickets/recent/upcoming/decisions/drafts/tasks/memories sections; stable urgent-first then due/date ascending then ID ordering; projects activity descending with lexical ties. Omit empty slices. Treat ready tasks using dependency metadata supplied by their collector, not an invented task status.

---

## Scope

Implement M5 grouping. Resolve project_hint as project page ID then title slug, configured project_map, raw Jira project key, SDD feature slug, then Internal. Fetch project metadata through ctx.store without mutation. Assign blocked/tickets/recent/upcoming/decisions/drafts/tasks/memories sections; stable urgent-first then due/date ascending then ID ordering; projects activity descending with lexical ties. Omit empty slices. Treat ready tasks using dependency metadata supplied by their collector, not an invented task status.

**NOT in scope**: changes outside the declared file table; new runtime dependencies; unrelated cleanup. Follow the approved v1 non-goals for backend parity and pre-existing ledger import cost.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/standup/grouping.py` | CREATE | Async project lookup is explicit; sorting remains deterministic and rendering-independent. |
| `packages/ai-parrot/tests/knowledge/wiki/standup/test_grouping.py` | CREATE | Shuffle identical inputs and assert exactly identical output. |

---

## Codebase Contract (Anti-Hallucination)

Verified at `75fe680a0`. Dependency-created imports below are planned contracts, not claims of current existence.

### Verified Imports

```python
from parrot.knowledge.wiki.standup.collectors import CollectContext  # planned in TASK-4031; not present before that task
from parrot.knowledge.wiki.standup.models import BriefItem, BriefSection, ProjectSlice  # planned in TASK-4031; not present before that task
from pathlib import Path  # stdlib or existing pyproject dependency/test environment
import pytest  # stdlib or existing pyproject dependency/test environment
import parrot.knowledge.wiki.standup.grouping as subject  # planned in TASK-4036; not present before that task
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/store.py:565
    async def get_page(self, concept_id: str, include_body: bool = True) -> Optional[dict[str, Any]]: ...
```

### Does NOT Exist

- `packages/ai-parrot/src/parrot/knowledge/wiki/standup/grouping.py` is created by this task; do not assume it already exists.
- `packages/ai-parrot/tests/knowledge/wiki/standup/test_grouping.py` is created by this task; do not assume it already exists.
- `list_pages(offset=...)`, `DecisionRecord.updated_at`, and a JiraPerson email field are not existing APIs. Do not invent them.
- Category names remain open strings; no new WikiPageCategory enum members are required.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/wiki/standup/grouping.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/wiki/standup/test_grouping.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/store.py#BaseWikiStore.get_page"
  ]
}
```

---

## Implementation Notes

TASK-4031: consumes BriefItem, ProjectSlice and CollectContext

Use async I/O paths, existing lifecycle/context managers, module logging, strict types and Google-style docstrings. Black uses 120 columns; ruff is the lint gate. Keep tests isolated and file-scoped. Fresh dependency code may shift anchors: reverify before edits, and retain the semantic attachment site.

---

## Implementation Blueprint

### Steps (in order)

1. Verify the existing references and completed dependency interfaces — because the blueprint must match the executing worktree.
2. Apply the per-file blocks below in declared order and complete only bounded FILL IN work — because each task owns a limited surface.
3. Implement the listed adversarial cases and run Validation Commands — because the acceptance criteria cover observable behavior, not only imports.

---

### `packages/ai-parrot/src/parrot/knowledge/wiki/standup/grouping.py` (CREATE)

```python
"""Deterministic project lookup, sections and activity ordering."""
from parrot.knowledge.wiki.standup.collectors import CollectContext
from parrot.knowledge.wiki.standup.models import BriefItem, BriefSection, ProjectSlice

async def resolve_project(item: BriefItem, ctx: CollectContext) -> str:
    """Resolve a project label using the precedence fixed by M5."""
    # FILL IN: page ID/title, configured aliases, source hints, Internal; AC6.
    raise NotImplementedError

async def group_items(items: list[BriefItem], ctx: CollectContext) -> tuple[list[ProjectSlice], list[BriefSection]]:
    """Return activity-sorted projects and Internal sections with stable item order."""
    # FILL IN: section routing and urgent/date/ID ordering; AC6.
    raise NotImplementedError
```

**Why**: Async project lookup is explicit; sorting remains deterministic and rendering-independent.

---

### `packages/ai-parrot/tests/knowledge/wiki/standup/test_grouping.py` (CREATE)

```python
"""Regression cases for FEAT-627."""
from pathlib import Path
import pytest
import parrot.knowledge.wiki.standup.grouping as subject


def test_project_resolution_chain(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify project resolution chain."""
    # FILL IN: build isolated inputs and assert the corresponding AC below.
    # Use pytest.mark.asyncio / async def when exercising async APIs.
    raise NotImplementedError


def test_stable_urgent_first_grouping(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify stable urgent first grouping."""
    # FILL IN: build isolated inputs and assert the corresponding AC below.
    # Use pytest.mark.asyncio / async def when exercising async APIs.
    raise NotImplementedError
```

**Why**: Shuffle identical inputs and assert exactly identical output.

---

### FILL IN checklist

- [ ] `packages/ai-parrot/src/parrot/knowledge/wiki/standup/grouping.py` — complete the block instructions and tests within this task’s acceptance criteria; leave no implementation placeholders.
- [ ] `packages/ai-parrot/tests/knowledge/wiki/standup/test_grouping.py` — complete the block instructions and tests within this task’s acceptance criteria; leave no implementation placeholders.

---

## Acceptance Criteria

- [ ] Resolution precedence and Internal fallback match M5.
- [ ] Input permutation does not affect output; urgent/date/project ties are stable and no item disappears.
- [ ] All declared-file tests pass; no ruff errors or unfinished implementation placeholders remain.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/wiki/standup/test_grouping.py -q`

---

## Test Specification

- Resolution precedence and Internal fallback match M5.
- Input permutation does not affect output; urgent/date/project ties are stable and no item disappears.

Use temporary local state, deterministic clocks and fake network/model adapters. Test failures and negative cases as well as success. New tests live alongside the core distribution; legacy suites are validation references only unless explicitly declared MODIFY above.

---

## Agent Instructions

1. Run `$sdd-start TASK-4036`; implementation belongs in the feature worktree, never directly on dev.
2. Read the approved spec and verify dependency completion in `sdd/tasks/index/wikitoolkit-standup.json`.
3. Recheck imports/anchors, implement only declared files and run the validation commands.
4. Commit scoped implementation and finalize with `scripts.sdd.finalize_task` plus real `TaskCompletionEvidence` for the exact implementation HEAD. Do not manually move the task or manufacture completion evidence.

## Completion Note

Pending; owned by the evidence-based finalizer.

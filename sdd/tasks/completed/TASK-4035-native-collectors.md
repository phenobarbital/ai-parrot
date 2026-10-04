# TASK-4035: Ledger task decision and memory collectors

---

**Feature**: FEAT-627 — wikitoolkit standup: entity attributes and daily/period briefs
**Spec**: `sdd/specs/wikitoolkit-standup.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2–4h)
**Depends-on**: TASK-4031, TASK-4027
**Assigned-to**: unassigned

---

## Context

Implement four M5 native collectors. Ledger uses from_root(find_shared_root(root)), list_issues open/claimed and merge_blockers for in-progress features; critical and unacknowledged is urgent. Tasks read per-spec index JSON off-thread, skip _orphans.json, include in-progress and pending whose dependencies are all done (mark ready without inventing a canonical status); filter assigned_to by wiki identity/aliases unless team. Decisions use inventory proposed or inferred+unreviewed; hydrate ADR pages for updated_at and asserted_by because records lack timestamps. Memories read origin memory/authored, filter updated_at in window/author, exclude category brief and native ADR/task duplicates. Map memory categories to valid EntityType (note/concept/lesson map deliverable; decision stays decision). For roll-ups include accepted decisions during window. Missing/malformed native sources append diagnostics and return remaining healthy data; no direct private ledger API.

---

## Scope

Implement four M5 native collectors. Ledger uses from_root(find_shared_root(root)), list_issues open/claimed and merge_blockers for in-progress features; critical and unacknowledged is urgent. Tasks read per-spec index JSON off-thread, skip _orphans.json, include in-progress and pending whose dependencies are all done (mark ready without inventing a canonical status); filter assigned_to by wiki identity/aliases unless team. Decisions use inventory proposed or inferred+unreviewed; hydrate ADR pages for updated_at and asserted_by because records lack timestamps. Memories read origin memory/authored, filter updated_at in window/author, exclude category brief and native ADR/task duplicates. Map memory categories to valid EntityType (note/concept/lesson map deliverable; decision stays decision). For roll-ups include accepted decisions during window. Missing/malformed native sources append diagnostics and return remaining healthy data; no direct private ledger API.

**NOT in scope**: changes outside the declared file table; new runtime dependencies; unrelated cleanup. Follow the approved v1 non-goals for backend parity and pre-existing ledger import cost.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/standup/collectors/ledger.py` | CREATE | Each source owns its adaptation and error handling; all share one typed context. |
| `packages/ai-parrot/src/parrot/knowledge/wiki/standup/collectors/tasks.py` | CREATE | Each source owns its adaptation and error handling; all share one typed context. |
| `packages/ai-parrot/src/parrot/knowledge/wiki/standup/collectors/decisions.py` | CREATE | Each source owns its adaptation and error handling; all share one typed context. |
| `packages/ai-parrot/src/parrot/knowledge/wiki/standup/collectors/memories.py` | CREATE | Each source owns its adaptation and error handling; all share one typed context. |
| `packages/ai-parrot/tests/knowledge/wiki/standup/test_native_collectors.py` | CREATE | Use real small ledger/index/ADR fixtures with injected time; no shared conftest. |

---

## Codebase Contract (Anti-Hallucination)

Verified at `75fe680a0`. Dependency-created imports below are planned contracts, not claims of current existence.

### Verified Imports

```python
from parrot.knowledge.wiki.standup.collectors import CollectContext  # planned in TASK-4031; not present before that task
from parrot.knowledge.wiki.standup.models import BriefItem  # planned in TASK-4031; not present before that task
from parrot.knowledge.wiki.ledger.service import LedgerService  # verified source packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py
from parrot.knowledge.wiki.project import find_shared_root  # verified source packages/ai-parrot/src/parrot/knowledge/wiki/project.py
from parrot.knowledge.wiki.decisions.repository import DecisionRepository  # verified source packages/ai-parrot/src/parrot/knowledge/wiki/decisions/repository.py
from pathlib import Path  # stdlib or existing pyproject dependency/test environment
import pytest  # stdlib or existing pyproject dependency/test environment
import parrot.knowledge.wiki.standup.collectors.tasks as subject  # planned in TASK-4035; not present before that task
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py:116
    def from_root(cls, root: Path | None = None) -> "LedgerService":

# packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py:322
    async def merge_blockers(self, feature_id: str) -> list[dict[str, Any]]:

# packages/ai-parrot/src/parrot/knowledge/wiki/decisions/repository.py:63
    async def inventory(self) -> list[DecisionRecord]:

# packages/ai-parrot/src/parrot/knowledge/wiki/store.py:568
    async def list_pages(
        self,
        category: Optional[str] = None,
        limit: int = 100,
        origin: Optional[list[str]] = None,

# packages/ai-parrot/src/parrot/knowledge/wiki/project.py:1220
def find_shared_root(start: Path | None = None) -> Path | None:

# packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py:98
class LedgerService:

# packages/ai-parrot/src/parrot/knowledge/wiki/decisions/repository.py:26
class DecisionRepository:
```

### Does NOT Exist

- `packages/ai-parrot/src/parrot/knowledge/wiki/standup/collectors/ledger.py` is created by this task; do not assume it already exists.
- `packages/ai-parrot/src/parrot/knowledge/wiki/standup/collectors/tasks.py` is created by this task; do not assume it already exists.
- `packages/ai-parrot/src/parrot/knowledge/wiki/standup/collectors/decisions.py` is created by this task; do not assume it already exists.
- `packages/ai-parrot/src/parrot/knowledge/wiki/standup/collectors/memories.py` is created by this task; do not assume it already exists.
- `packages/ai-parrot/tests/knowledge/wiki/standup/test_native_collectors.py` is created by this task; do not assume it already exists.
- `list_pages(offset=...)`, `DecisionRecord.updated_at`, and a JiraPerson email field are not existing APIs. Do not invent them.
- Category names remain open strings; no new WikiPageCategory enum members are required.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/wiki/standup/collectors/ledger.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/wiki/standup/collectors/tasks.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/wiki/standup/collectors/decisions.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/wiki/standup/collectors/memories.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/wiki/standup/test_native_collectors.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py#LedgerService.from_root",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py#LedgerService.merge_blockers",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/decisions/repository.py#DecisionRepository.inventory",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/store.py#BaseWikiStore.list_pages",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/project.py#find_shared_root",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py#LedgerService",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/decisions/repository.py#DecisionRepository"
  ]
}
```

---

## Implementation Notes

TASK-4031: consumes CollectContext and BriefItem; TASK-4027: consumes LedgerService.list_issues

Use async I/O paths, existing lifecycle/context managers, module logging, strict types and Google-style docstrings. Black uses 120 columns; ruff is the lint gate. Keep tests isolated and file-scoped. Fresh dependency code may shift anchors: reverify before edits, and retain the semantic attachment site.

---

## Implementation Blueprint

### Steps (in order)

1. Verify the existing references and completed dependency interfaces — because the blueprint must match the executing worktree.
2. Apply the per-file blocks below in declared order and complete only bounded FILL IN work — because each task owns a limited surface.
3. Implement the listed adversarial cases and run Validation Commands — because the acceptance criteria cover observable behavior, not only imports.

---

### `packages/ai-parrot/src/parrot/knowledge/wiki/standup/collectors/ledger.py` (CREATE)

```python
"""Collect ledger items without making missing sources fatal."""
from parrot.knowledge.wiki.standup.collectors import CollectContext
from parrot.knowledge.wiki.standup.models import BriefItem

from parrot.knowledge.wiki.ledger.service import LedgerService
from parrot.knowledge.wiki.project import find_shared_root

async def collect(ctx: CollectContext) -> list[BriefItem]:
    """Return normalized items and append source failures to ctx.diagnostics."""
    # FILL IN: wrap the following native read with source error diagnostics.
    service = LedgerService.from_root(find_shared_root(ctx.root))
    rows = await service.list_issues(("open", "claimed"))
    # FILL IN: adapt public list_issues and merge_blockers; AC11/AC16.
    # Preserve qualified IDs, deterministic order and AC7 personal/team filtering.
    # Catch source I/O failures, not cancellation; return [] with a diagnostic.
    raise NotImplementedError
```

**Why**: Each source owns its adaptation and error handling; all share one typed context.

---

### `packages/ai-parrot/src/parrot/knowledge/wiki/standup/collectors/tasks.py` (CREATE)

```python
"""Collect tasks items without making missing sources fatal."""
from parrot.knowledge.wiki.standup.collectors import CollectContext
from parrot.knowledge.wiki.standup.models import BriefItem

async def collect(ctx: CollectContext) -> list[BriefItem]:
    """Return normalized items and append source failures to ctx.diagnostics."""
    # FILL IN: parse per-spec indexes and ready dependencies; AC6/AC7.
    # Preserve qualified IDs, deterministic order and AC7 personal/team filtering.
    # Catch source I/O failures, not cancellation; return [] with a diagnostic.
    raise NotImplementedError
```

**Why**: Each source owns its adaptation and error handling; all share one typed context.

---

### `packages/ai-parrot/src/parrot/knowledge/wiki/standup/collectors/decisions.py` (CREATE)

```python
"""Collect decisions items without making missing sources fatal."""
from parrot.knowledge.wiki.standup.collectors import CollectContext
from parrot.knowledge.wiki.standup.models import BriefItem

from parrot.knowledge.wiki.decisions.repository import DecisionRepository

async def collect(ctx: CollectContext) -> list[BriefItem]:
    """Return normalized items and append source failures to ctx.diagnostics."""
    # FILL IN: wrap the following native read with source error diagnostics.
    repository = DecisionRepository(ctx.store)
    records = await repository.inventory()
    # FILL IN: inventory plus ADR page metadata; AC7/AC11.
    # Preserve qualified IDs, deterministic order and AC7 personal/team filtering.
    # Catch source I/O failures, not cancellation; return [] with a diagnostic.
    raise NotImplementedError
```

**Why**: Each source owns its adaptation and error handling; all share one typed context.

---

### `packages/ai-parrot/src/parrot/knowledge/wiki/standup/collectors/memories.py` (CREATE)

```python
"""Collect memories items without making missing sources fatal."""
from parrot.knowledge.wiki.standup.collectors import CollectContext
from parrot.knowledge.wiki.standup.models import BriefItem



async def collect(ctx: CollectContext) -> list[BriefItem]:
    """Return normalized items and append source failures to ctx.diagnostics."""
    # FILL IN: wrap the following native read with source error diagnostics.
    pages = await ctx.store.list_pages(origin=["memory", "authored"], limit=10_000)
    # FILL IN: origin, category, time and asserted_by filtering; AC7.
    # Preserve qualified IDs, deterministic order and AC7 personal/team filtering.
    # Catch source I/O failures, not cancellation; return [] with a diagnostic.
    raise NotImplementedError
```

**Why**: Each source owns its adaptation and error handling; all share one typed context.

---

### `packages/ai-parrot/tests/knowledge/wiki/standup/test_native_collectors.py` (CREATE)

```python
"""Regression cases for FEAT-627."""
from pathlib import Path
import pytest
import parrot.knowledge.wiki.standup.collectors.tasks as subject


def test_ledger_and_task_mapping(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify ledger and task mapping."""
    # FILL IN: build isolated inputs and assert the corresponding AC below.
    # Use pytest.mark.asyncio / async def when exercising async APIs.
    raise NotImplementedError


def test_decision_and_memory_ownership(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify decision and memory ownership."""
    # FILL IN: build isolated inputs and assert the corresponding AC below.
    # Use pytest.mark.asyncio / async def when exercising async APIs.
    raise NotImplementedError


def test_missing_native_sources(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify missing native sources."""
    # FILL IN: build isolated inputs and assert the corresponding AC below.
    # Use pytest.mark.asyncio / async def when exercising async APIs.
    raise NotImplementedError
```

**Why**: Use real small ledger/index/ADR fixtures with injected time; no shared conftest.

---

### FILL IN checklist

- [ ] `packages/ai-parrot/src/parrot/knowledge/wiki/standup/collectors/ledger.py` — complete the block instructions and tests within this task’s acceptance criteria; leave no implementation placeholders.
- [ ] `packages/ai-parrot/src/parrot/knowledge/wiki/standup/collectors/tasks.py` — complete the block instructions and tests within this task’s acceptance criteria; leave no implementation placeholders.
- [ ] `packages/ai-parrot/src/parrot/knowledge/wiki/standup/collectors/decisions.py` — complete the block instructions and tests within this task’s acceptance criteria; leave no implementation placeholders.
- [ ] `packages/ai-parrot/src/parrot/knowledge/wiki/standup/collectors/memories.py` — complete the block instructions and tests within this task’s acceptance criteria; leave no implementation placeholders.
- [ ] `packages/ai-parrot/tests/knowledge/wiki/standup/test_native_collectors.py` — complete the block instructions and tests within this task’s acceptance criteria; leave no implementation placeholders.

---

## Acceptance Criteria

- [ ] Native ledger rows preserve status/claim ownership and report blockers without fabricated timestamps.
- [ ] Task readiness, personal assignment, malformed indexes and missing roots behave deterministically.
- [ ] ADR age/ownership comes from page rows; memories obey window/author filters and exclude generated briefs.
- [ ] All declared-file tests pass; no ruff errors or unfinished implementation placeholders remain.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/wiki/standup/test_native_collectors.py -q`

---

## Test Specification

- Native ledger rows preserve status/claim ownership and report blockers without fabricated timestamps.
- Task readiness, personal assignment, malformed indexes and missing roots behave deterministically.
- ADR age/ownership comes from page rows; memories obey window/author filters and exclude generated briefs.

Use temporary local state, deterministic clocks and fake network/model adapters. Test failures and negative cases as well as success. New tests live alongside the core distribution; legacy suites are validation references only unless explicitly declared MODIFY above.

---

## Agent Instructions

1. Run `$sdd-start TASK-4035`; implementation belongs in the feature worktree, never directly on dev.
2. Read the approved spec and verify dependency completion in `sdd/tasks/index/wikitoolkit-standup.json`.
3. Recheck imports/anchors, implement only declared files and run the validation commands.
4. Commit scoped implementation and finalize with `scripts.sdd.finalize_task` plus real `TaskCompletionEvidence` for the exact implementation HEAD. Do not manually move the task or manufacture completion evidence.

## Completion Note

Pending; owned by the evidence-based finalizer.

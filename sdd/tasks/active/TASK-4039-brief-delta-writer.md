# TASK-4039: Same-period delta and locked atomic brief persistence

---

**Feature**: FEAT-627 — wikitoolkit standup: entity attributes and daily/period briefs
**Spec**: `sdd/specs/wikitoolkit-standup.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2–4h)
**Depends-on**: TASK-4031, TASK-4023, TASK-4032
**Assigned-to**: unassigned

---

## Context

Implement M5 delta and writer. Select latest earlier same-period brief by period bounds/ID, accepting daily/weekly/monthly ID prefixes with attrs.period day/week/month. Compare current ID list against previous attrs.items JSON; malformed data becomes a diagnostic, not a crash. First run has no delta. Closed IDs mean absent from this brief, not necessarily business-status closed; hydrate available previous/current pages and retain qualified IDs for missing items. WriteResult has written_page bool, written_file str|None, diagnostics list[str]. Page attrs include type=deliverable, status=draft,date,owner,period,items,source=brief,language; origin=authored/category=brief. Hold wiki_write_lock(storage_dir) around actual local store upsert; honor its yielded acquired flag. File writes use a per-run temp sibling then os.replace to avoid concurrent .tmp clobbering. Offload synchronous file/lock I/O; never block while waiting for locks. Vault markers only for resolved containment in vault_dir. Support each write flag independently; preserve/report successful output if the other fails, clean temporary files and bookkeep STANDUP only for writes.

---

## Scope

Implement M5 delta and writer. Select latest earlier same-period brief by period bounds/ID, accepting daily/weekly/monthly ID prefixes with attrs.period day/week/month. Compare current ID list against previous attrs.items JSON; malformed data becomes a diagnostic, not a crash. First run has no delta. Closed IDs mean absent from this brief, not necessarily business-status closed; hydrate available previous/current pages and retain qualified IDs for missing items. WriteResult has written_page bool, written_file str|None, diagnostics list[str]. Page attrs include type=deliverable, status=draft,date,owner,period,items,source=brief,language; origin=authored/category=brief. Hold wiki_write_lock(storage_dir) around actual local store upsert; honor its yielded acquired flag. File writes use a per-run temp sibling then os.replace to avoid concurrent .tmp clobbering. Offload synchronous file/lock I/O; never block while waiting for locks. Vault markers only for resolved containment in vault_dir. Support each write flag independently; preserve/report successful output if the other fails, clean temporary files and bookkeep STANDUP only for writes.

**NOT in scope**: changes outside the declared file table; new runtime dependencies; unrelated cleanup. Follow the approved v1 non-goals for backend parity and pre-existing ledger import cost.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/standup/delta.py` | CREATE | ID comparison is separate from item hydration and Markdown rendering. |
| `packages/ai-parrot/src/parrot/knowledge/wiki/standup/writer.py` | CREATE | One receipt explicitly distinguishes requested and successful writes for both CLI and MCP. |
| `packages/ai-parrot/tests/knowledge/wiki/standup/test_delta_writer.py` | CREATE | Exercise real files and lock contention with injected page/file failure. |

---

## Codebase Contract (Anti-Hallucination)

Verified at `75fe680a0`. Dependency-created imports below are planned contracts, not claims of current existence.

### Verified Imports

```python
from collections.abc import Mapping, Sequence  # stdlib or existing pyproject dependency/test environment
from typing import Any  # stdlib or existing pyproject dependency/test environment
from parrot.knowledge.wiki.store import BaseWikiStore  # verified source packages/ai-parrot/src/parrot/knowledge/wiki/store.py
from parrot.knowledge.wiki.standup.models import PeriodWindow  # planned in TASK-4031; not present before that task
from pathlib import Path  # stdlib or existing pyproject dependency/test environment
from pydantic import BaseModel, Field  # stdlib or existing pyproject dependency/test environment
from parrot.knowledge.wiki.store import BaseWikiStore, WikiPageRecord  # verified source packages/ai-parrot/src/parrot/knowledge/wiki/store.py
from parrot.knowledge.wiki.project import wiki_write_lock  # verified source packages/ai-parrot/src/parrot/knowledge/wiki/project.py
from parrot.knowledge.wiki.standup.models import BriefDocument  # planned in TASK-4031; not present before that task
import pytest  # stdlib or existing pyproject dependency/test environment
import parrot.knowledge.wiki.standup.writer as subject  # planned in TASK-4039; not present before that task
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/project.py:74
def wiki_write_lock(store_dir: Path, timeout: float = 0.0) -> Iterator[bool]:

# packages/ai-parrot/src/parrot/knowledge/wiki/project.py:1045
def parrot_home() -> Path:

# packages/ai-parrot/src/parrot/knowledge/wiki/store.py:409
class WikiPageRecord(BaseModel):

# packages/ai-parrot/src/parrot/knowledge/wiki/bookkeeper.py:175
    def log_operation(
        self,
        wiki_dir: Path,
        operation: str,
        details: str,
        timestamp: Optional[str] = None,
    ) -> None:

# packages/ai-parrot/src/parrot/knowledge/wiki/store.py:525
class BaseWikiStore(ABC):
```

### Does NOT Exist

- `packages/ai-parrot/src/parrot/knowledge/wiki/standup/delta.py` is created by this task; do not assume it already exists.
- `packages/ai-parrot/src/parrot/knowledge/wiki/standup/writer.py` is created by this task; do not assume it already exists.
- `packages/ai-parrot/tests/knowledge/wiki/standup/test_delta_writer.py` is created by this task; do not assume it already exists.
- `list_pages(offset=...)`, `DecisionRecord.updated_at`, and a JiraPerson email field are not existing APIs. Do not invent them.
- Category names remain open strings; no new WikiPageCategory enum members are required.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/wiki/standup/delta.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/wiki/standup/writer.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/wiki/standup/test_delta_writer.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/project.py#wiki_write_lock",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/project.py#parrot_home",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/store.py#WikiPageRecord",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/bookkeeper.py#WikiBookkeeper.log_operation",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/store.py#BaseWikiStore"
  ]
}
```

---

## Implementation Notes

TASK-4031: consumes BriefDocument and identity; TASK-4023: consumes WikiPageRecord.attrs persistence; TASK-4032: consumes stable brief identities

Use async I/O paths, existing lifecycle/context managers, module logging, strict types and Google-style docstrings. Black uses 120 columns; ruff is the lint gate. Keep tests isolated and file-scoped. Fresh dependency code may shift anchors: reverify before edits, and retain the semantic attachment site.

---

## Implementation Blueprint

### Steps (in order)

1. Verify the existing references and completed dependency interfaces — because the blueprint must match the executing worktree.
2. Apply the per-file blocks below in declared order and complete only bounded FILL IN work — because each task owns a limited surface.
3. Implement the listed adversarial cases and run Validation Commands — because the acceptance criteria cover observable behavior, not only imports.

---

### `packages/ai-parrot/src/parrot/knowledge/wiki/standup/delta.py` (CREATE)

```python
"""Stable new/absent item IDs against the previous same-period brief."""
from collections.abc import Mapping, Sequence
from typing import Any
from parrot.knowledge.wiki.store import BaseWikiStore
from parrot.knowledge.wiki.standup.models import PeriodWindow

async def previous_brief(store: BaseWikiStore, window: PeriodWindow) -> dict[str, Any] | None:
    """Select the most recent strictly earlier brief of the same period."""
    # FILL IN: attrs.period plus stable identity/date ordering; AC10.
    raise NotImplementedError

def diff(current_ids: Sequence[str], previous_page: Mapping[str, Any] | None) -> tuple[list[str], list[str]]:
    """Return sorted new and absent IDs using the persisted items JSON attribute."""
    # FILL IN: deterministic sets and first-run behavior; AC10.
    raise NotImplementedError
```

**Why**: ID comparison is separate from item hydration and Markdown rendering.

---

### `packages/ai-parrot/src/parrot/knowledge/wiki/standup/writer.py` (CREATE)

```python
"""Locked local-plane persistence and atomic Markdown output."""
from pathlib import Path
from pydantic import BaseModel, Field
from parrot.knowledge.wiki.store import BaseWikiStore, WikiPageRecord
from parrot.knowledge.wiki.project import wiki_write_lock
from parrot.knowledge.wiki.standup.models import BriefDocument

class WriteResult(BaseModel):
    """Independent page/file receipts plus nonfatal write diagnostics."""
    written_page: bool = False
    written_file: str | None = None
    diagnostics: list[str] = Field(default_factory=list)

async def write(
    doc: BriefDocument, rendered: str, *, store: BaseWikiStore, storage_dir: Path,
    out_dir: Path, write_page: bool, write_file: bool, vault_dir: Path | None,
) -> WriteResult:
    """Persist requested outputs independently without writing foreign namespaces."""
    # FILL IN: lock-protected upsert, attrs.items, atomic file, vault markers; AC9.
    # Record partial success, remove owned temporary files and log STANDUP.
    raise NotImplementedError
```

**Why**: One receipt explicitly distinguishes requested and successful writes for both CLI and MCP.

---

### `packages/ai-parrot/tests/knowledge/wiki/standup/test_delta_writer.py` (CREATE)

```python
"""Regression cases for FEAT-627."""
from pathlib import Path
import pytest
import parrot.knowledge.wiki.standup.writer as subject


def test_same_period_delta(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify same period delta."""
    # FILL IN: build isolated inputs and assert the corresponding AC below.
    # Use pytest.mark.asyncio / async def when exercising async APIs.
    raise NotImplementedError


def test_locked_page_and_atomic_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify locked page and atomic file."""
    # FILL IN: build isolated inputs and assert the corresponding AC below.
    # Use pytest.mark.asyncio / async def when exercising async APIs.
    raise NotImplementedError


def test_partial_failure_and_vault_markers(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify partial failure and vault markers."""
    # FILL IN: build isolated inputs and assert the corresponding AC below.
    # Use pytest.mark.asyncio / async def when exercising async APIs.
    raise NotImplementedError
```

**Why**: Exercise real files and lock contention with injected page/file failure.

---

### FILL IN checklist

- [ ] `packages/ai-parrot/src/parrot/knowledge/wiki/standup/delta.py` — complete the block instructions and tests within this task’s acceptance criteria; leave no implementation placeholders.
- [ ] `packages/ai-parrot/src/parrot/knowledge/wiki/standup/writer.py` — complete the block instructions and tests within this task’s acceptance criteria; leave no implementation placeholders.
- [ ] `packages/ai-parrot/tests/knowledge/wiki/standup/test_delta_writer.py` — complete the block instructions and tests within this task’s acceptance criteria; leave no implementation placeholders.

---

## Acceptance Criteria

- [ ] Delta uses persisted attrs.items and an earlier brief of exactly the same period; first run and corrupt input are tested.
- [ ] Page write occurs under an acquired local lock with complete attrs; disabled outputs produce no mutations.
- [ ] Atomic replacement, concurrent runs, failure cleanup and vault containment are tested with actual temporary files.
- [ ] All declared-file tests pass; no ruff errors or unfinished implementation placeholders remain.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/wiki/standup/test_delta_writer.py -q`
- `pytest tests/knowledge/wiki/test_project_lock.py -q`

---

## Test Specification

- Delta uses persisted attrs.items and an earlier brief of exactly the same period; first run and corrupt input are tested.
- Page write occurs under an acquired local lock with complete attrs; disabled outputs produce no mutations.
- Atomic replacement, concurrent runs, failure cleanup and vault containment are tested with actual temporary files.

Use temporary local state, deterministic clocks and fake network/model adapters. Test failures and negative cases as well as success. New tests live alongside the core distribution; legacy suites are validation references only unless explicitly declared MODIFY above.

---

## Agent Instructions

1. Run `$sdd-start TASK-4039`; implementation belongs in the feature worktree, never directly on dev.
2. Read the approved spec and verify dependency completion in `sdd/tasks/index/wikitoolkit-standup.json`.
3. Recheck imports/anchors, implement only declared files and run the validation commands.
4. Commit scoped implementation and finalize with `scripts.sdd.finalize_task` plus real `TaskCompletionEvidence` for the exact implementation HEAD. Do not manually move the task or manufacture completion evidence.

## Completion Note

Pending; owned by the evidence-based finalizer.

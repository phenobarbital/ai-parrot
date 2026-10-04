# TASK-4032: Deterministic day week and month windows

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

Implement periods.window with the exact three-argument skeleton; resolve now/timezone in the pipeline before passing an anchor. Day start/end are anchor +/- horizon; week uses configured Monday/Sunday and month calendar bounds. Set recent_start/upcoming_end consistently with M5. Stable IDs use brief:daily:YYYY-MM-DD, brief:weekly:YYYY-Www and brief:monthly:YYYY-MM per resolved Q9. Derive weekly identity from its window start so all dates in a Sunday-start week converge; test year boundaries explicitly.

---

## Scope

Implement periods.window with the exact three-argument skeleton; resolve now/timezone in the pipeline before passing an anchor. Day start/end are anchor +/- horizon; week uses configured Monday/Sunday and month calendar bounds. Set recent_start/upcoming_end consistently with M5. Stable IDs use brief:daily:YYYY-MM-DD, brief:weekly:YYYY-Www and brief:monthly:YYYY-MM per resolved Q9. Derive weekly identity from its window start so all dates in a Sunday-start week converge; test year boundaries explicitly.

**NOT in scope**: changes outside the declared file table; new runtime dependencies; unrelated cleanup. Follow the approved v1 non-goals for backend parity and pre-existing ledger import cost.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/standup/periods.py` | CREATE | The pipeline owns the injectable clock, keeping this function pure. |
| `packages/ai-parrot/tests/knowledge/wiki/standup/test_periods.py` | CREATE | Cover Sunday/Monday start, leap day and year rollover. |

---

## Codebase Contract (Anti-Hallucination)

Verified at `75fe680a0`. Dependency-created imports below are planned contracts, not claims of current existence.

### Verified Imports

```python
from datetime import date, timedelta  # stdlib or existing pyproject dependency/test environment
from parrot.knowledge.wiki.project import StandupConfig  # verified source packages/ai-parrot/src/parrot/knowledge/wiki/project.py; StandupConfig planned in TASK-4029 (not yet present)
from parrot.knowledge.wiki.standup.models import Period, PeriodWindow  # planned in TASK-4031; not present before that task
from pathlib import Path  # stdlib or existing pyproject dependency/test environment
import pytest  # stdlib or existing pyproject dependency/test environment
import parrot.knowledge.wiki.standup.periods as subject  # planned in TASK-4032; not present before that task
```

### Existing Signatures to Use

No existing implementation symbol is required beyond the explicitly listed dependency contracts and installed libraries.

### Does NOT Exist

- `packages/ai-parrot/src/parrot/knowledge/wiki/standup/periods.py` is created by this task; do not assume it already exists.
- `packages/ai-parrot/tests/knowledge/wiki/standup/test_periods.py` is created by this task; do not assume it already exists.
- `list_pages(offset=...)`, `DecisionRecord.updated_at`, and a JiraPerson email field are not existing APIs. Do not invent them.
- Category names remain open strings; no new WikiPageCategory enum members are required.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/wiki/standup/periods.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/wiki/standup/test_periods.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

TASK-4031: consumes Period and PeriodWindow

Use async I/O paths, existing lifecycle/context managers, module logging, strict types and Google-style docstrings. Black uses 120 columns; ruff is the lint gate. Keep tests isolated and file-scoped. Fresh dependency code may shift anchors: reverify before edits, and retain the semantic attachment site.

---

## Implementation Blueprint

### Steps (in order)

1. Verify the existing references and completed dependency interfaces — because the blueprint must match the executing worktree.
2. Apply the per-file blocks below in declared order and complete only bounded FILL IN work — because each task owns a limited surface.
3. Implement the listed adversarial cases and run Validation Commands — because the acceptance criteria cover observable behavior, not only imports.

---

### `packages/ai-parrot/src/parrot/knowledge/wiki/standup/periods.py` (CREATE)

```python
"""Pure calendar windows for deterministic brief identities."""
from datetime import date, timedelta
from parrot.knowledge.wiki.project import StandupConfig
from parrot.knowledge.wiki.standup.models import Period, PeriodWindow

def window(period: Period, anchor: date, cfg: StandupConfig) -> PeriodWindow:
    """Compute inclusive period and horizon bounds from an already-local anchor."""
    # FILL IN: calendar/week boundaries and spec Q9 IDs; AC6/AC9.
    raise NotImplementedError
```

**Why**: The pipeline owns the injectable clock, keeping this function pure.

---

### `packages/ai-parrot/tests/knowledge/wiki/standup/test_periods.py` (CREATE)

```python
"""Regression cases for FEAT-627."""
from pathlib import Path
import pytest
import parrot.knowledge.wiki.standup.periods as subject


def test_day_week_month_boundaries(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify day week month boundaries."""
    # FILL IN: build isolated inputs and assert the corresponding AC below.
    # Use pytest.mark.asyncio / async def when exercising async APIs.
    raise NotImplementedError


def test_stable_period_ids(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify stable period ids."""
    # FILL IN: build isolated inputs and assert the corresponding AC below.
    # Use pytest.mark.asyncio / async def when exercising async APIs.
    raise NotImplementedError
```

**Why**: Cover Sunday/Monday start, leap day and year rollover.

---

### FILL IN checklist

- [ ] `packages/ai-parrot/src/parrot/knowledge/wiki/standup/periods.py` — complete the block instructions and tests within this task’s acceptance criteria; leave no implementation placeholders.
- [ ] `packages/ai-parrot/tests/knowledge/wiki/standup/test_periods.py` — complete the block instructions and tests within this task’s acceptance criteria; leave no implementation placeholders.

---

## Acceptance Criteria

- [ ] Day horizon, week-start variants, leap months and year boundaries have inclusive bounds.
- [ ] Repeated anchors inside one week/month yield the same brief ID; no wall-clock access inside window.
- [ ] All declared-file tests pass; no ruff errors or unfinished implementation placeholders remain.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/wiki/standup/test_periods.py -q`

---

## Test Specification

- Day horizon, week-start variants, leap months and year boundaries have inclusive bounds.
- Repeated anchors inside one week/month yield the same brief ID; no wall-clock access inside window.

Use temporary local state, deterministic clocks and fake network/model adapters. Test failures and negative cases as well as success. New tests live alongside the core distribution; legacy suites are validation references only unless explicitly declared MODIFY above.

---

## Agent Instructions

1. Run `$sdd-start TASK-4032`; implementation belongs in the feature worktree, never directly on dev.
2. Read the approved spec and verify dependency completion in `sdd/tasks/index/wikitoolkit-standup.json`.
3. Recheck imports/anchors, implement only declared files and run the validation commands.
4. Commit scoped implementation and finalize with `scripts.sdd.finalize_task` plus real `TaskCompletionEvidence` for the exact implementation HEAD. Do not manually move the task or manufacture completion evidence.

## Completion Note

Pending; owned by the evidence-based finalizer.

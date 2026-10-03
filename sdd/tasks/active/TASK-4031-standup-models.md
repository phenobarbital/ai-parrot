# TASK-4031: Brief data models and collector context

---

**Feature**: FEAT-627 — wikitoolkit standup: entity attributes and daily/period briefs
**Spec**: `sdd/specs/wikitoolkit-standup.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2–4h)
**Depends-on**: TASK-4022, TASK-4029, TASK-4030
**Assigned-to**: unassigned

---

## Context

Create spec M5 data contracts, standup package initializers, config re-export, and the previously unspecified CollectContext shared by all collectors. Define CollectContext in collectors/__init__.py as a Pydantic model with arbitrary_types_allowed=True: root Path, store BaseWikiStore, cfg StandupConfig, window PeriodWindow, identity StandupIdentity, team bool, diagnostics list[str], unmapped_statuses dict[str,int]. Use default factories. BriefDocument may additionally carry diagnostics, written_page and written_file so pipeline.run keeps the required BriefDocument return type while CLI/MCP can report outcomes. Do not perform I/O or import collectors/pipeline from package initializers. Keep all data models fully typed.

---

## Scope

Create spec M5 data contracts, standup package initializers, config re-export, and the previously unspecified CollectContext shared by all collectors. Define CollectContext in collectors/__init__.py as a Pydantic model with arbitrary_types_allowed=True: root Path, store BaseWikiStore, cfg StandupConfig, window PeriodWindow, identity StandupIdentity, team bool, diagnostics list[str], unmapped_statuses dict[str,int]. Use default factories. BriefDocument may additionally carry diagnostics, written_page and written_file so pipeline.run keeps the required BriefDocument return type while CLI/MCP can report outcomes. Do not perform I/O or import collectors/pipeline from package initializers. Keep all data models fully typed.

**NOT in scope**: changes outside the declared file table; new runtime dependencies; unrelated cleanup. Follow the approved v1 non-goals for backend parity and pre-existing ledger import cost.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/standup/__init__.py` | CREATE | A passive initializer avoids loading optional clients or collectors. |
| `packages/ai-parrot/src/parrot/knowledge/wiki/standup/config.py` | CREATE | Configuration ownership remains in project.py for overlay validation. |
| `packages/ai-parrot/src/parrot/knowledge/wiki/standup/models.py` | CREATE | These types are the shared dependency for disjoint collector/render/writer tasks. |
| `packages/ai-parrot/src/parrot/knowledge/wiki/standup/collectors/__init__.py` | CREATE | All collectors share a declared context rather than assuming ambient CLI state. |
| `packages/ai-parrot/tests/knowledge/wiki/standup/test_models.py` | CREATE | Validate all DTOs and reject overlong titles/private fields. |

---

## Codebase Contract (Anti-Hallucination)

Verified at `75fe680a0`. Dependency-created imports below are planned contracts, not claims of current existence.

### Verified Imports

```python
from parrot.knowledge.wiki.project import StandupConfig  # verified source packages/ai-parrot/src/parrot/knowledge/wiki/project.py; StandupConfig planned in TASK-4029 (not yet present)
from datetime import date as CalendarDate  # stdlib or existing pyproject dependency/test environment
from typing import Literal  # stdlib or existing pyproject dependency/test environment
from pydantic import BaseModel, Field  # stdlib or existing pyproject dependency/test environment
from parrot.knowledge.wiki.entities import EntityType  # planned in TASK-4022; not present before that task
from parrot.knowledge.wiki.standup.identity import StandupIdentity  # planned in TASK-4030; not present before that task
from pathlib import Path  # stdlib or existing pyproject dependency/test environment
from pydantic import BaseModel, ConfigDict, Field  # stdlib or existing pyproject dependency/test environment
from parrot.knowledge.wiki.store import BaseWikiStore  # verified source packages/ai-parrot/src/parrot/knowledge/wiki/store.py
from parrot.knowledge.wiki.standup.models import PeriodWindow  # planned in TASK-4031; not present before that task
import pytest  # stdlib or existing pyproject dependency/test environment
import parrot.knowledge.wiki.standup.models as subject  # planned in TASK-4031; not present before that task
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/store.py:525
class BaseWikiStore(ABC):
```

### Does NOT Exist

- `packages/ai-parrot/src/parrot/knowledge/wiki/standup/__init__.py` is created by this task; do not assume it already exists.
- `packages/ai-parrot/src/parrot/knowledge/wiki/standup/config.py` is created by this task; do not assume it already exists.
- `packages/ai-parrot/src/parrot/knowledge/wiki/standup/models.py` is created by this task; do not assume it already exists.
- `packages/ai-parrot/src/parrot/knowledge/wiki/standup/collectors/__init__.py` is created by this task; do not assume it already exists.
- `packages/ai-parrot/tests/knowledge/wiki/standup/test_models.py` is created by this task; do not assume it already exists.
- `list_pages(offset=...)`, `DecisionRecord.updated_at`, and a JiraPerson email field are not existing APIs. Do not invent them.
- Category names remain open strings; no new WikiPageCategory enum members are required.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/wiki/standup/__init__.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/wiki/standup/config.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/wiki/standup/models.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/wiki/standup/collectors/__init__.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/wiki/standup/test_models.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/store.py#BaseWikiStore"
  ]
}
```

---

## Implementation Notes

TASK-4022: consumes EntityType; TASK-4029: consumes StandupConfig; TASK-4030: consumes StandupIdentity

Use async I/O paths, existing lifecycle/context managers, module logging, strict types and Google-style docstrings. Black uses 120 columns; ruff is the lint gate. Keep tests isolated and file-scoped. Fresh dependency code may shift anchors: reverify before edits, and retain the semantic attachment site.

---

## Implementation Blueprint

### Steps (in order)

1. Verify the existing references and completed dependency interfaces — because the blueprint must match the executing worktree.
2. Apply the per-file blocks below in declared order and complete only bounded FILL IN work — because each task owns a limited surface.
3. Implement the listed adversarial cases and run Validation Commands — because the acceptance criteria cover observable behavior, not only imports.

---

### `packages/ai-parrot/src/parrot/knowledge/wiki/standup/__init__.py` (CREATE)

```python
"""Deterministic wiki briefs; importing this package performs no I/O."""
```

**Why**: A passive initializer avoids loading optional clients or collectors.

---

### `packages/ai-parrot/src/parrot/knowledge/wiki/standup/config.py` (CREATE)

```python
"""Standup configuration compatibility exports."""
from parrot.knowledge.wiki.project import StandupConfig

__all__ = ["StandupConfig"]
```

**Why**: Configuration ownership remains in project.py for overlay validation.

---

### `packages/ai-parrot/src/parrot/knowledge/wiki/standup/models.py` (CREATE)

```python
"""Validated data passed between brief collection, rendering and persistence."""
from datetime import date as CalendarDate
from typing import Literal
from pydantic import BaseModel, Field
from parrot.knowledge.wiki.entities import EntityType
from parrot.knowledge.wiki.standup.identity import StandupIdentity
Period = Literal["day", "week", "month"]
class PeriodWindow(BaseModel):
    """Inclusive period bounds plus meeting horizons and stable page identity."""
    period: Period
    anchor: CalendarDate
    start: CalendarDate
    end: CalendarDate
    recent_start: CalendarDate
    upcoming_end: CalendarDate
    brief_id: str
class BriefItem(BaseModel):
    """One qualified, attributable item from a native or attrs source."""
    id: str
    kind: EntityType
    title: str
    status: str | None = None
    status_raw: str | None = None
    project_hint: str | None = None
    date: CalendarDate | None = None
    due: CalendarDate | None = None
    owner: str | None = None
    urgent: bool = False
    namespace: str | None = None
    url: str | None = None
    source: str
    age_days: int | None = None
class BriefSection(BaseModel):
    """A named ordered collection of brief items."""
    key: str
    items: list[BriefItem]
class ProjectSlice(BaseModel):
    """Project grouping with deterministic activity ordering."""
    project: str
    status: str | None = None
    sections: list[BriefSection]
    activity: int
class HygieneReport(BaseModel):
    """Deterministic source health and optional synthesis outcome."""
    ledger_blockers: int = 0
    proposed_decisions_older_than: int = 0
    stale_tickets: int = 0
    unmapped_statuses: dict[str, int] = Field(default_factory=dict)
    jira_watermark: str | None = None
    attrs_indexed: int | None = None
    last_lint: str | None = None
    llm: str = "skipped: no model"
class BriefDocument(BaseModel):
    """Complete brief with safe write receipts and source diagnostics."""
    window: PeriodWindow
    identity: StandupIdentity
    team: bool
    language: str
    on_your_plate: list[str]
    projects: list[ProjectSlice]
    internal: list[BriefSection]
    delta_new: list[BriefItem]
    delta_closed: list[BriefItem]
    previous_brief_id: str | None = None
    sources: list[str]
    hygiene: HygieneReport
    item_ids: list[str]
    diagnostics: list[str] = Field(default_factory=list)
    written_page: bool = False
    written_file: str | None = None
class BriefProjection(BaseModel):
    """Only bounded, whitelisted scalar facts sent to a model."""
    period: Period
    language: str
    items: list[dict[str, str | int | bool | None]] = Field(max_length=40)
    # FILL IN: validate exact keys/title bounds; AC8. No bodies, URLs or emails.
```

**Why**: These types are the shared dependency for disjoint collector/render/writer tasks.

---

### `packages/ai-parrot/src/parrot/knowledge/wiki/standup/collectors/__init__.py` (CREATE)

```python
"""Shared context only; concrete source collectors are imported at execution."""
from pathlib import Path
from pydantic import BaseModel, ConfigDict, Field
from parrot.knowledge.wiki.project import StandupConfig
from parrot.knowledge.wiki.store import BaseWikiStore
from parrot.knowledge.wiki.standup.identity import StandupIdentity
from parrot.knowledge.wiki.standup.models import PeriodWindow

class CollectContext(BaseModel):
    """Explicit shared read context and per-run diagnostic accumulators."""
    model_config = ConfigDict(arbitrary_types_allowed=True)
    root: Path
    store: BaseWikiStore
    cfg: StandupConfig
    window: PeriodWindow
    identity: StandupIdentity
    team: bool = False
    diagnostics: list[str] = Field(default_factory=list)
    unmapped_statuses: dict[str, int] = Field(default_factory=dict)
```

**Why**: All collectors share a declared context rather than assuming ambient CLI state.

---

### `packages/ai-parrot/tests/knowledge/wiki/standup/test_models.py` (CREATE)

```python
"""Regression cases for FEAT-627."""
from pathlib import Path
import pytest
import parrot.knowledge.wiki.standup.models as subject


def test_model_serialization_and_defaults(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify model serialization and defaults."""
    # FILL IN: build isolated inputs and assert the corresponding AC below.
    # Use pytest.mark.asyncio / async def when exercising async APIs.
    raise NotImplementedError


def test_projection_rejects_unbounded_fields(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify projection rejects unbounded fields."""
    # FILL IN: build isolated inputs and assert the corresponding AC below.
    # Use pytest.mark.asyncio / async def when exercising async APIs.
    raise NotImplementedError
```

**Why**: Validate all DTOs and reject overlong titles/private fields.

---

### FILL IN checklist

- [ ] `packages/ai-parrot/src/parrot/knowledge/wiki/standup/__init__.py` — complete the block instructions and tests within this task’s acceptance criteria; leave no implementation placeholders.
- [ ] `packages/ai-parrot/src/parrot/knowledge/wiki/standup/config.py` — complete the block instructions and tests within this task’s acceptance criteria; leave no implementation placeholders.
- [ ] `packages/ai-parrot/src/parrot/knowledge/wiki/standup/models.py` — complete the block instructions and tests within this task’s acceptance criteria; leave no implementation placeholders.
- [ ] `packages/ai-parrot/src/parrot/knowledge/wiki/standup/collectors/__init__.py` — complete the block instructions and tests within this task’s acceptance criteria; leave no implementation placeholders.
- [ ] `packages/ai-parrot/tests/knowledge/wiki/standup/test_models.py` — complete the block instructions and tests within this task’s acceptance criteria; leave no implementation placeholders.

---

## Acceptance Criteria

- [ ] All spec section 2 fields serialize cleanly with ISO dates and independent mutable defaults.
- [ ] BriefProjection constrains <=40 items and <=120-character titles with only the six allowed scalar fields.
- [ ] Collector context has one explicit contract, and config re-exports the same class from project.py.
- [ ] All declared-file tests pass; no ruff errors or unfinished implementation placeholders remain.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/wiki/standup/test_models.py -q`

---

## Test Specification

- All spec section 2 fields serialize cleanly with ISO dates and independent mutable defaults.
- BriefProjection constrains <=40 items and <=120-character titles with only the six allowed scalar fields.
- Collector context has one explicit contract, and config re-exports the same class from project.py.

Use temporary local state, deterministic clocks and fake network/model adapters. Test failures and negative cases as well as success. New tests live alongside the core distribution; legacy suites are validation references only unless explicitly declared MODIFY above.

---

## Agent Instructions

1. Run `$sdd-start TASK-4031`; implementation belongs in the feature worktree, never directly on dev.
2. Read the approved spec and verify dependency completion in `sdd/tasks/index/wikitoolkit-standup.json`.
3. Recheck imports/anchors, implement only declared files and run the validation commands.
4. Commit scoped implementation and finalize with `scripts.sdd.finalize_task` plus real `TaskCompletionEvidence` for the exact implementation HEAD. Do not manually move the task or manufacture completion evidence.

## Completion Note

Pending; owned by the evidence-based finalizer.

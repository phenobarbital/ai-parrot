# TASK-4040: End-to-end collection grouping hygiene and output pipeline

---

**Feature**: FEAT-627 — wikitoolkit standup: entity attributes and daily/period briefs
**Spec**: `sdd/specs/wikitoolkit-standup.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2–4h)
**Depends-on**: TASK-4034, TASK-4035, TASK-4036, TASK-4037, TASK-4038, TASK-4039
**Assigned-to**: unassigned

---

## Context

Implement M5 pipeline.run with the exact public signature. Resolve effective config, local writable store and separate namespace read facade; keep an injected caller store open and close only owned stores/handles. Resolve anchor from explicit date or options.now in configured timezone (local when absent); horizon/language overrides do not mutate shared config. Collect concurrently, retain healthy sources, de-duplicate by qualified ID, group, compute delta/hydration and Hygiene, then optional synthesis, render and write. Compute delta BEFORE final rendering so output includes it. Hygiene counts blockers/old proposed decisions/stale tickets/unmapped statuses, sync watermark, attrs size, optional lint report timestamp; no new lint run. Read week/month daily source briefs in window. Set document diagnostics and writer receipts. No email in serialized document. Store open failure is actionable; missing optional sources/models never fail the brief. MCP read-only mode must not mutate through caches/audit/init: when both write flags are false, resolve identity from config/existing cache without cache writes or live probes.

---

## Scope

Implement M5 pipeline.run with the exact public signature. Resolve effective config, local writable store and separate namespace read facade; keep an injected caller store open and close only owned stores/handles. Resolve anchor from explicit date or options.now in configured timezone (local when absent); horizon/language overrides do not mutate shared config. Collect concurrently, retain healthy sources, de-duplicate by qualified ID, group, compute delta/hydration and Hygiene, then optional synthesis, render and write. Compute delta BEFORE final rendering so output includes it. Hygiene counts blockers/old proposed decisions/stale tickets/unmapped statuses, sync watermark, attrs size, optional lint report timestamp; no new lint run. Read week/month daily source briefs in window. Set document diagnostics and writer receipts. No email in serialized document. Store open failure is actionable; missing optional sources/models never fail the brief. MCP read-only mode must not mutate through caches/audit/init: when both write flags are false, resolve identity from config/existing cache without cache writes or live probes.

**NOT in scope**: changes outside the declared file table; new runtime dependencies; unrelated cleanup. Follow the approved v1 non-goals for backend parity and pre-existing ledger import cost.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/standup/pipeline.py` | CREATE | One orchestration path keeps CLI and MCP behavior aligned without importing cli. |
| `packages/ai-parrot/tests/knowledge/wiki/standup/test_pipeline.py` | CREATE | Assert no side effects in read-only mode and exact independent output receipts. |

---

## Codebase Contract (Anti-Hallucination)

Verified at `75fe680a0`. Dependency-created imports below are planned contracts, not claims of current existence.

### Verified Imports

```python
from datetime import date, datetime  # stdlib or existing pyproject dependency/test environment
from pathlib import Path  # stdlib or existing pyproject dependency/test environment
from typing import Literal  # stdlib or existing pyproject dependency/test environment
from pydantic import BaseModel  # stdlib or existing pyproject dependency/test environment
from parrot.knowledge.wiki.project import WikiEffectiveConfig  # verified source packages/ai-parrot/src/parrot/knowledge/wiki/project.py
from parrot.knowledge.wiki.store import BaseWikiStore  # verified source packages/ai-parrot/src/parrot/knowledge/wiki/store.py
from parrot.knowledge.wiki.standup.models import BriefDocument, Period  # planned in TASK-4031; not present before that task
import pytest  # stdlib or existing pyproject dependency/test environment
import parrot.knowledge.wiki.standup.pipeline as subject  # planned in TASK-4040; not present before that task
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/project.py:933
def load_effective_config(root: Path, env: str | None = None) -> WikiEffectiveConfig:

# packages/ai-parrot/src/parrot/knowledge/wiki/federation.py:461
async def resolve_namespaces(
    root: Path,
    config: WikiProjectConfig,
    *,
    only: set[str] | None = None,
    registry_path: Path | None = None,
    read_only: bool = True,
    arango_timeout: float = DEFAULT_ARANGO_TIMEOUT,
) -> tuple[list[NamespaceHandle], list[NamespaceSkip]]:

# packages/ai-parrot/src/parrot/knowledge/wiki/jira_sync.py:176
def load_sync_state(issues_dir: Path) -> JiraSyncState:

# packages/ai-parrot/src/parrot/knowledge/wiki/jira_sync.py:152
def resolve_issues_dir(explicit: Path | str | None = None) -> Path:

# packages/ai-parrot/src/parrot/knowledge/wiki/project.py:878
class WikiEffectiveConfig(BaseModel):

# packages/ai-parrot/src/parrot/knowledge/wiki/store.py:525
class BaseWikiStore(ABC):
```

### Does NOT Exist

- `packages/ai-parrot/src/parrot/knowledge/wiki/standup/pipeline.py` is created by this task; do not assume it already exists.
- `packages/ai-parrot/tests/knowledge/wiki/standup/test_pipeline.py` is created by this task; do not assume it already exists.
- `list_pages(offset=...)`, `DecisionRecord.updated_at`, and a JiraPerson email field are not existing APIs. Do not invent them.
- Category names remain open strings; no new WikiPageCategory enum members are required.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/wiki/standup/pipeline.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/wiki/standup/test_pipeline.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/project.py#load_effective_config",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/federation.py#resolve_namespaces",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/jira_sync.py#load_sync_state",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/jira_sync.py#resolve_issues_dir",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/project.py#WikiEffectiveConfig",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/store.py#BaseWikiStore"
  ]
}
```

---

## Implementation Notes

TASK-4034: consumes entities/jira collect functions; TASK-4035: consumes ledger/tasks/decisions/memories collect functions; TASK-4036: consumes group_items; TASK-4037: consumes render_markdown; TASK-4038: consumes resolve_optional_llm and summarize; TASK-4039: consumes previous_brief, diff and write receipts

Use async I/O paths, existing lifecycle/context managers, module logging, strict types and Google-style docstrings. Black uses 120 columns; ruff is the lint gate. Keep tests isolated and file-scoped. Fresh dependency code may shift anchors: reverify before edits, and retain the semantic attachment site.

---

## Implementation Blueprint

### Steps (in order)

1. Verify the existing references and completed dependency interfaces — because the blueprint must match the executing worktree.
2. Apply the per-file blocks below in declared order and complete only bounded FILL IN work — because each task owns a limited surface.
3. Implement the listed adversarial cases and run Validation Commands — because the acceptance criteria cover observable behavior, not only imports.

---

### `packages/ai-parrot/src/parrot/knowledge/wiki/standup/pipeline.py` (CREATE)

```python
"""Shared deterministic brief orchestration for CLI and MCP."""
from datetime import date, datetime
from pathlib import Path
from typing import Literal
from pydantic import BaseModel
from parrot.knowledge.wiki.project import WikiEffectiveConfig
from parrot.knowledge.wiki.store import BaseWikiStore
from parrot.knowledge.wiki.standup.models import BriefDocument, Period

class StandupOptions(BaseModel):
    """Explicit run options; callers control every persistence side effect."""
    period: Period = "day"
    anchor: date | None = None
    horizon_days: int | None = None
    team: bool = False
    me: str | None = None
    language: Literal["en", "es"] | None = None
    use_llm: bool = True
    write_page: bool = True
    write_file: bool = True
    out_dir: Path | None = None
    namespaces: str | None = None
    now: datetime | None = None

async def run(
    root: Path, options: StandupOptions, *, store: BaseWikiStore | None = None,
    effective: WikiEffectiveConfig | None = None,
) -> BriefDocument:
    """Collect, group, diff, synthesize, render and optionally persist a brief."""
    # FILL IN: wire dependency APIs and explicit ownership/side-effect semantics.
    # Healthy sources survive errors; final render follows delta/synthesis; AC6-12.
    raise NotImplementedError
```

**Why**: One orchestration path keeps CLI and MCP behavior aligned without importing cli.

---

### `packages/ai-parrot/tests/knowledge/wiki/standup/test_pipeline.py` (CREATE)

```python
"""Regression cases for FEAT-627."""
from pathlib import Path
import pytest
import parrot.knowledge.wiki.standup.pipeline as subject


def test_all_sources_and_hygiene(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify all sources and hygiene."""
    # FILL IN: build isolated inputs and assert the corresponding AC below.
    # Use pytest.mark.asyncio / async def when exercising async APIs.
    raise NotImplementedError


def test_offline_model_failure_still_writes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify offline model failure still writes."""
    # FILL IN: build isolated inputs and assert the corresponding AC below.
    # Use pytest.mark.asyncio / async def when exercising async APIs.
    raise NotImplementedError


def test_readonly_and_resource_ownership(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify readonly and resource ownership."""
    # FILL IN: build isolated inputs and assert the corresponding AC below.
    # Use pytest.mark.asyncio / async def when exercising async APIs.
    raise NotImplementedError
```

**Why**: Assert no side effects in read-only mode and exact independent output receipts.

---

### FILL IN checklist

- [ ] `packages/ai-parrot/src/parrot/knowledge/wiki/standup/pipeline.py` — complete the block instructions and tests within this task’s acceptance criteria; leave no implementation placeholders.
- [ ] `packages/ai-parrot/tests/knowledge/wiki/standup/test_pipeline.py` — complete the block instructions and tests within this task’s acceptance criteria; leave no implementation placeholders.

---

## Acceptance Criteria

- [ ] Daily/week/month documents include expected sections, source IDs, correct delta and all Hygiene counters.
- [ ] Missing sources/model timeout retain deterministic fallback and requested writes.
- [ ] Injected stores remain open; all owned handles close; writes never target a scoped foreign namespace.
- [ ] Read-only mode causes no page/file/cache/audit mutations; user options override configuration predictably.
- [ ] All declared-file tests pass; no ruff errors or unfinished implementation placeholders remain.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/wiki/standup/test_pipeline.py -q`

---

## Test Specification

- Daily/week/month documents include expected sections, source IDs, correct delta and all Hygiene counters.
- Missing sources/model timeout retain deterministic fallback and requested writes.
- Injected stores remain open; all owned handles close; writes never target a scoped foreign namespace.
- Read-only mode causes no page/file/cache/audit mutations; user options override configuration predictably.

Use temporary local state, deterministic clocks and fake network/model adapters. Test failures and negative cases as well as success. New tests live alongside the core distribution; legacy suites are validation references only unless explicitly declared MODIFY above.

---

## Agent Instructions

1. Run `$sdd-start TASK-4040`; implementation belongs in the feature worktree, never directly on dev.
2. Read the approved spec and verify dependency completion in `sdd/tasks/index/wikitoolkit-standup.json`.
3. Recheck imports/anchors, implement only declared files and run the validation commands.
4. Commit scoped implementation and finalize with `scripts.sdd.finalize_task` plus real `TaskCompletionEvidence` for the exact implementation HEAD. Do not manually move the task or manufacture completion evidence.

## Completion Note

Pending; owned by the evidence-based finalizer.

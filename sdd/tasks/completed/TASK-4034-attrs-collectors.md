# TASK-4034: Entity and Jira attrs collectors with legacy fallback

---

**Feature**: FEAT-627 — wikitoolkit standup: entity attributes and daily/period briefs
**Spec**: `sdd/specs/wikitoolkit-standup.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2–4h)
**Depends-on**: TASK-4031, TASK-4025
**Assigned-to**: unassigned

---

## Context

Implement M5 entity and Jira collectors. Inspect capability per plane, not only the composed store flag. Use list_by_attrs and hydrate attrs through get_attrs if stubs omit them. Fallback scans document/entity-category stubs, fetches bodies, unwraps repo Content wrappers and parses YAML; report lost/unsupported metadata. Entity meetings use recent/upcoming windows, decisions/drafts use canonical open statuses. Jira reads issues namespace ticket attrs from markdown/jira sources; x_assignee_id matching first, display name only when no ID is usable. Apply cfg.ticket_status_map; unmapped status counts as open and increments ctx.unmapped_statuses. Week/month include closed tickets dated in window for roll-ups. De-duplicate qualified IDs across the two sources by assigning issues tickets to Jira collector. Never include briefs as source entities.

---

## Scope

Implement M5 entity and Jira collectors. Inspect capability per plane, not only the composed store flag. Use list_by_attrs and hydrate attrs through get_attrs if stubs omit them. Fallback scans document/entity-category stubs, fetches bodies, unwraps repo Content wrappers and parses YAML; report lost/unsupported metadata. Entity meetings use recent/upcoming windows, decisions/drafts use canonical open statuses. Jira reads issues namespace ticket attrs from markdown/jira sources; x_assignee_id matching first, display name only when no ID is usable. Apply cfg.ticket_status_map; unmapped status counts as open and increments ctx.unmapped_statuses. Week/month include closed tickets dated in window for roll-ups. De-duplicate qualified IDs across the two sources by assigning issues tickets to Jira collector. Never include briefs as source entities.

**NOT in scope**: changes outside the declared file table; new runtime dependencies; unrelated cleanup. Follow the approved v1 non-goals for backend parity and pre-existing ledger import cost.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/standup/collectors/entities.py` | CREATE | Each source owns its adaptation and error handling; all share one typed context. |
| `packages/ai-parrot/src/parrot/knowledge/wiki/standup/collectors/jira.py` | CREATE | Each source owns its adaptation and error handling; all share one typed context. |
| `packages/ai-parrot/tests/knowledge/wiki/standup/test_attrs_collectors.py` | CREATE | Include mixed-capability federation and missing issues namespace. |

---

## Codebase Contract (Anti-Hallucination)

Verified at `75fe680a0`. Dependency-created imports below are planned contracts, not claims of current existence.

### Verified Imports

```python
from parrot.knowledge.wiki.standup.collectors import CollectContext  # planned in TASK-4031; not present before that task
from parrot.knowledge.wiki.standup.models import BriefItem  # planned in TASK-4031; not present before that task
from pathlib import Path  # stdlib or existing pyproject dependency/test environment
import pytest  # stdlib or existing pyproject dependency/test environment
import parrot.knowledge.wiki.standup.collectors.entities as subject  # planned in TASK-4034; not present before that task
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/federation.py:712
    def scoped(self, selector: str | None) -> BaseWikiStore:

# packages/ai-parrot/src/parrot/knowledge/wiki/context.py:83
def qualify_id(namespace: str | None, page_id: str) -> str:

# packages/ai-parrot/src/parrot/knowledge/wiki/repo_scan.py:572
def build_file_slice(
    root: Path,
    rel_path: str,
    body_max_chars: int = DEFAULT_BODY_MAX_CHARS,
    max_file_bytes: int = DEFAULT_MAX_FILE_BYTES,
    symbol_depth: int = 2,
) -> FileSlice | None:
```

### Does NOT Exist

- `packages/ai-parrot/src/parrot/knowledge/wiki/standup/collectors/entities.py` is created by this task; do not assume it already exists.
- `packages/ai-parrot/src/parrot/knowledge/wiki/standup/collectors/jira.py` is created by this task; do not assume it already exists.
- `packages/ai-parrot/tests/knowledge/wiki/standup/test_attrs_collectors.py` is created by this task; do not assume it already exists.
- `list_pages(offset=...)`, `DecisionRecord.updated_at`, and a JiraPerson email field are not existing APIs. Do not invent them.
- Category names remain open strings; no new WikiPageCategory enum members are required.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/wiki/standup/collectors/entities.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/wiki/standup/collectors/jira.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/wiki/standup/test_attrs_collectors.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/federation.py#FederatedWikiStore.scoped",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/context.py#qualify_id",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/repo_scan.py#build_file_slice"
  ]
}
```

---

## Implementation Notes

TASK-4031: consumes CollectContext and BriefItem; TASK-4025: consumes per-namespace attrs reads

Use async I/O paths, existing lifecycle/context managers, module logging, strict types and Google-style docstrings. Black uses 120 columns; ruff is the lint gate. Keep tests isolated and file-scoped. Fresh dependency code may shift anchors: reverify before edits, and retain the semantic attachment site.

---

## Implementation Blueprint

### Steps (in order)

1. Verify the existing references and completed dependency interfaces — because the blueprint must match the executing worktree.
2. Apply the per-file blocks below in declared order and complete only bounded FILL IN work — because each task owns a limited surface.
3. Implement the listed adversarial cases and run Validation Commands — because the acceptance criteria cover observable behavior, not only imports.

---

### `packages/ai-parrot/src/parrot/knowledge/wiki/standup/collectors/entities.py` (CREATE)

```python
"""Collect entities items without making missing sources fatal."""
from parrot.knowledge.wiki.standup.collectors import CollectContext
from parrot.knowledge.wiki.standup.models import BriefItem

async def collect(ctx: CollectContext) -> list[BriefItem]:
    """Return normalized items and append source failures to ctx.diagnostics."""
    # FILL IN: apply entity vocabulary/window filters and per-plane fallback; AC6/AC11.
    # Preserve qualified IDs, deterministic order and AC7 personal/team filtering.
    # Catch source I/O failures, not cancellation; return [] with a diagnostic.
    raise NotImplementedError
```

**Why**: Each source owns its adaptation and error handling; all share one typed context.

---

### `packages/ai-parrot/src/parrot/knowledge/wiki/standup/collectors/jira.py` (CREATE)

```python
"""Collect jira items without making missing sources fatal."""
from parrot.knowledge.wiki.standup.collectors import CollectContext
from parrot.knowledge.wiki.standup.models import BriefItem

async def collect(ctx: CollectContext) -> list[BriefItem]:
    """Return normalized items and append source failures to ctx.diagnostics."""
    # FILL IN: read issues namespace; canonical status, G9 identity and unmapped counts; AC7/AC11.
    # Preserve qualified IDs, deterministic order and AC7 personal/team filtering.
    # Catch source I/O failures, not cancellation; return [] with a diagnostic.
    raise NotImplementedError
```

**Why**: Each source owns its adaptation and error handling; all share one typed context.

---

### `packages/ai-parrot/tests/knowledge/wiki/standup/test_attrs_collectors.py` (CREATE)

```python
"""Regression cases for FEAT-627."""
from pathlib import Path
import pytest
import parrot.knowledge.wiki.standup.collectors.entities as subject


def test_entity_attrs_and_body_fallback(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify entity attrs and body fallback."""
    # FILL IN: build isolated inputs and assert the corresponding AC below.
    # Use pytest.mark.asyncio / async def when exercising async APIs.
    raise NotImplementedError


def test_jira_identity_statuses_and_periods(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify jira identity statuses and periods."""
    # FILL IN: build isolated inputs and assert the corresponding AC below.
    # Use pytest.mark.asyncio / async def when exercising async APIs.
    raise NotImplementedError
```

**Why**: Include mixed-capability federation and missing issues namespace.

---

### FILL IN checklist

- [ ] `packages/ai-parrot/src/parrot/knowledge/wiki/standup/collectors/entities.py` — complete the block instructions and tests within this task’s acceptance criteria; leave no implementation placeholders.
- [ ] `packages/ai-parrot/src/parrot/knowledge/wiki/standup/collectors/jira.py` — complete the block instructions and tests within this task’s acceptance criteria; leave no implementation placeholders.
- [ ] `packages/ai-parrot/tests/knowledge/wiki/standup/test_attrs_collectors.py` — complete the block instructions and tests within this task’s acceptance criteria; leave no implementation placeholders.

---

## Acceptance Criteria

- [ ] Attrs and supported legacy fallback yield equivalent qualified items and diagnostic evidence.
- [ ] Jira personal/team filtering uses IDs before display names and never email.
- [ ] Unmapped, stale, blocked and period-closed tickets retain correct metadata and counts.
- [ ] All declared-file tests pass; no ruff errors or unfinished implementation placeholders remain.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/wiki/standup/test_attrs_collectors.py -q`

---

## Test Specification

- Attrs and supported legacy fallback yield equivalent qualified items and diagnostic evidence.
- Jira personal/team filtering uses IDs before display names and never email.
- Unmapped, stale, blocked and period-closed tickets retain correct metadata and counts.

Use temporary local state, deterministic clocks and fake network/model adapters. Test failures and negative cases as well as success. New tests live alongside the core distribution; legacy suites are validation references only unless explicitly declared MODIFY above.

---

## Agent Instructions

1. Run `$sdd-start TASK-4034`; implementation belongs in the feature worktree, never directly on dev.
2. Read the approved spec and verify dependency completion in `sdd/tasks/index/wikitoolkit-standup.json`.
3. Recheck imports/anchors, implement only declared files and run the validation commands.
4. Commit scoped implementation and finalize with `scripts.sdd.finalize_task` plus real `TaskCompletionEvidence` for the exact implementation HEAD. Do not manually move the task or manufacture completion evidence.

## Completion Note

Pending; owned by the evidence-based finalizer.

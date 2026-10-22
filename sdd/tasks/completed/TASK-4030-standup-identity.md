# TASK-4030: Shared authoring identity and private Jira identity cache

---

**Feature**: FEAT-627 — wikitoolkit standup: entity attributes and daily/period briefs
**Spec**: `sdd/specs/wikitoolkit-standup.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2–4h)
**Depends-on**: TASK-4029, TASK-4028
**Assigned-to**: unassigned

---

## Context

Implement the M5 identity seam. Move the existing authoring helper unchanged to wiki/identity.py and re-export it from cli.py under its old name. Add StandupIdentity and resolve_identity in standup/identity.py; no import from cli in the standup package. Follow spec precedence: configured wiki identity, explicit --me, authoring helper; Jira ID: config, safe cache, configured Jira probe. Do not query Jira without configured credentials. Cache only account_id/display_name/resolved_at under PARROT_HOME. Keep git_email=None and excluded from dumps because AC7 forbids email in persisted planes/caches. Read/write cache off the event loop and replace atomically. Missing credentials/cache corruption/network failure preserve wiki-only identity.

---

## Scope

Implement the M5 identity seam. Move the existing authoring helper unchanged to wiki/identity.py and re-export it from cli.py under its old name. Add StandupIdentity and resolve_identity in standup/identity.py; no import from cli in the standup package. Follow spec precedence: configured wiki identity, explicit --me, authoring helper; Jira ID: config, safe cache, configured Jira probe. Do not query Jira without configured credentials. Cache only account_id/display_name/resolved_at under PARROT_HOME. Keep git_email=None and excluded from dumps because AC7 forbids email in persisted planes/caches. Read/write cache off the event loop and replace atomically. Missing credentials/cache corruption/network failure preserve wiki-only identity.

**NOT in scope**: changes outside the declared file table; new runtime dependencies; unrelated cleanup. Follow the approved v1 non-goals for backend parity and pre-existing ledger import cost.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/identity.py` | CREATE | Preserve the verified helper behavior exactly while removing the CLI import cycle. |
| `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py` | MODIFY | Existing command and test imports must continue to work. |
| `packages/ai-parrot/src/parrot/knowledge/wiki/standup/identity.py` | CREATE | StandupIdentity is defined here as fixed by the spec, avoiding a models/identity cycle. |
| `packages/ai-parrot/tests/knowledge/wiki/standup/test_identity.py` | CREATE | Stub Jira; isolate PARROT_HOME and assert exact cache keys. |

---

## Codebase Contract (Anti-Hallucination)

Verified at `75fe680a0`. Dependency-created imports below are planned contracts, not claims of current existence.

### Verified Imports

```python
import getpass  # stdlib or existing pyproject dependency/test environment
import os  # stdlib or existing pyproject dependency/test environment
from parrot.knowledge.wiki.identity import authoring_identity as _authoring_identity  # planned in TASK-4030; not present before that task
from pathlib import Path  # stdlib or existing pyproject dependency/test environment
from pydantic import BaseModel, Field  # stdlib or existing pyproject dependency/test environment
from parrot.knowledge.wiki.identity import authoring_identity  # planned in TASK-4030; not present before that task
from parrot.knowledge.wiki.project import StandupConfig, parrot_home  # verified source packages/ai-parrot/src/parrot/knowledge/wiki/project.py; StandupConfig planned in TASK-4029 (not yet present)
import pytest  # stdlib or existing pyproject dependency/test environment
import parrot.knowledge.wiki.standup.identity as subject  # planned in TASK-4030; not present before that task
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/cli.py:3513
def _authoring_identity(by: str | None) -> str:

# packages/ai-parrot/src/parrot/knowledge/wiki/project.py:1045
def parrot_home() -> Path:

# packages/ai-parrot/src/parrot/interfaces/jira/models.py:21
class JiraPerson(BaseModel):
```

### Does NOT Exist

- `packages/ai-parrot/src/parrot/knowledge/wiki/identity.py` is created by this task; do not assume it already exists.
- `packages/ai-parrot/src/parrot/knowledge/wiki/standup/identity.py` is created by this task; do not assume it already exists.
- `packages/ai-parrot/tests/knowledge/wiki/standup/test_identity.py` is created by this task; do not assume it already exists.
- `list_pages(offset=...)`, `DecisionRecord.updated_at`, and a JiraPerson email field are not existing APIs. Do not invent them.
- Category names remain open strings; no new WikiPageCategory enum members are required.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/wiki/identity.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/wiki/cli.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/wiki/standup/identity.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/wiki/standup/test_identity.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/cli.py#_authoring_identity",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/project.py#parrot_home",
    "sym:packages/ai-parrot/src/parrot/interfaces/jira/models.py#JiraPerson"
  ]
}
```

---

## Implementation Notes

TASK-4029: consumes StandupConfig.me; TASK-4028: consumes JiraInterface.myself returning JiraPerson

Use async I/O paths, existing lifecycle/context managers, module logging, strict types and Google-style docstrings. Black uses 120 columns; ruff is the lint gate. Keep tests isolated and file-scoped. Fresh dependency code may shift anchors: reverify before edits, and retain the semantic attachment site.

---

## Implementation Blueprint

### Steps (in order)

1. Verify the existing references and completed dependency interfaces — because the blueprint must match the executing worktree.
2. Apply the per-file blocks below in declared order and complete only bounded FILL IN work — because each task owns a limited surface.
3. Implement the listed adversarial cases and run Validation Commands — because the acceptance criteria cover observable behavior, not only imports.

---

### `packages/ai-parrot/src/parrot/knowledge/wiki/identity.py` (CREATE)

```python
"""Lightweight author attribution shared by wiki commands."""
import getpass
import os

def authoring_identity(by: str | None) -> str:
    """Resolve explicit identity, agent environment, then the local user."""
    if by:
        return by
    for env_name in ("CLAUDE_AGENT_ID", "PARROT_AGENT_ID"):
        value = os.environ.get(env_name)
        if value:
            return f"agent:{value}"
    try:
        return f"human:{getpass.getuser()}"
    except Exception:
        return "human:unknown"
```

**Why**: Preserve the verified helper behavior exactly while removing the CLI import cycle.

---

### `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py` (MODIFY)

Anchor `def _authoring_identity(by: str | None) -> str:` — occurrences: 1 (verified: `grep -F -c`), `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py:3513`.

```python
# Replace the old helper definition (not its callers) with this compatibility alias:
from parrot.knowledge.wiki.identity import authoring_identity as _authoring_identity
```

**Why**: Existing command and test imports must continue to work.

---

### `packages/ai-parrot/src/parrot/knowledge/wiki/standup/identity.py` (CREATE)

```python
"""Resolve wiki ownership and G9-safe Jira identity."""
from pathlib import Path
from pydantic import BaseModel, Field
from parrot.knowledge.wiki.identity import authoring_identity
from parrot.knowledge.wiki.project import StandupConfig, parrot_home

class StandupIdentity(BaseModel):
    """Identity used for personal brief filtering; no persisted email."""
    wiki: str
    jira_account_id: str | None = None
    jira_display_name: str | None = None
    git_email: str | None = Field(default=None, exclude=True)
    aliases: list[str] = Field(default_factory=list)

async def resolve_identity(cfg: StandupConfig, *, explicit: str | None = None, root: Path) -> StandupIdentity:
    """Resolve configured/cache/probed identity, retaining wiki-only fallback."""
    # FILL IN: lazy Jira import, safe cache and precedence specified above; AC7.
    # Cache failures must not prevent a deterministic offline brief.
    raise NotImplementedError
```

**Why**: StandupIdentity is defined here as fixed by the spec, avoiding a models/identity cycle.

---

### `packages/ai-parrot/tests/knowledge/wiki/standup/test_identity.py` (CREATE)

```python
"""Regression cases for FEAT-627."""
from pathlib import Path
import pytest
import parrot.knowledge.wiki.standup.identity as subject


def test_identity_precedence_and_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify identity precedence and cache."""
    # FILL IN: build isolated inputs and assert the corresponding AC below.
    # Use pytest.mark.asyncio / async def when exercising async APIs.
    raise NotImplementedError


def test_g9_and_offline_fallback(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify g9 and offline fallback."""
    # FILL IN: build isolated inputs and assert the corresponding AC below.
    # Use pytest.mark.asyncio / async def when exercising async APIs.
    raise NotImplementedError


def test_authoring_compatibility(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify authoring compatibility."""
    # FILL IN: build isolated inputs and assert the corresponding AC below.
    # Use pytest.mark.asyncio / async def when exercising async APIs.
    raise NotImplementedError
```

**Why**: Stub Jira; isolate PARROT_HOME and assert exact cache keys.

---

### FILL IN checklist

- [ ] `packages/ai-parrot/src/parrot/knowledge/wiki/identity.py` — complete the block instructions and tests within this task’s acceptance criteria; leave no implementation placeholders.
- [ ] `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py` — complete the block instructions and tests within this task’s acceptance criteria; leave no implementation placeholders.
- [ ] `packages/ai-parrot/src/parrot/knowledge/wiki/standup/identity.py` — complete the block instructions and tests within this task’s acceptance criteria; leave no implementation placeholders.
- [ ] `packages/ai-parrot/tests/knowledge/wiki/standup/test_identity.py` — complete the block instructions and tests within this task’s acceptance criteria; leave no implementation placeholders.

---

## Acceptance Criteria

- [ ] Existing authoring precedence and imports remain compatible; standup never imports cli.
- [ ] Config/cache/probe precedence, aliases and failure fallback are deterministic.
- [ ] Cache contains exactly three approved keys; raw response/email never enters a brief, cache or log.
- [ ] All declared-file tests pass; no ruff errors or unfinished implementation placeholders remain.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/wiki/standup/test_identity.py -q`

---

## Test Specification

- Existing authoring precedence and imports remain compatible; standup never imports cli.
- Config/cache/probe precedence, aliases and failure fallback are deterministic.
- Cache contains exactly three approved keys; raw response/email never enters a brief, cache or log.

Use temporary local state, deterministic clocks and fake network/model adapters. Test failures and negative cases as well as success. New tests live alongside the core distribution; legacy suites are validation references only unless explicitly declared MODIFY above.

---

## Agent Instructions

1. Run `$sdd-start TASK-4030`; implementation belongs in the feature worktree, never directly on dev.
2. Read the approved spec and verify dependency completion in `sdd/tasks/index/wikitoolkit-standup.json`.
3. Recheck imports/anchors, implement only declared files and run the validation commands.
4. Commit scoped implementation and finalize with `scripts.sdd.finalize_task` plus real `TaskCompletionEvidence` for the exact implementation HEAD. Do not manually move the task or manufacture completion evidence.

## Completion Note

Pending; owned by the evidence-based finalizer.

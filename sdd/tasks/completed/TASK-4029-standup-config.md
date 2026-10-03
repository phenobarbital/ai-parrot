# TASK-4029: Validated standup base and environment configuration

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

Implement AC15 and M5 configuration in project.py, independent of standup imports. Define StandupIdentityConfig (wiki, jira_account_id, jira_display_name optional; aliases list), the exact DEFAULT_TICKET_STATUS_MAP from spec and StandupConfig fields. Validate IANA timezone with zoneinfo and ticket_status_map values against fixed canonical ticket statuses without importing entities on startup. Use default factories. Add standup to WikiProjectConfig and optional standup to WikiEnvOverlay. Retain existing whole-field overlay replacement semantics.

---

## Scope

Implement AC15 and M5 configuration in project.py, independent of standup imports. Define StandupIdentityConfig (wiki, jira_account_id, jira_display_name optional; aliases list), the exact DEFAULT_TICKET_STATUS_MAP from spec and StandupConfig fields. Validate IANA timezone with zoneinfo and ticket_status_map values against fixed canonical ticket statuses without importing entities on startup. Use default factories. Add standup to WikiProjectConfig and optional standup to WikiEnvOverlay. Retain existing whole-field overlay replacement semantics.

**NOT in scope**: changes outside the declared file table; new runtime dependencies; unrelated cleanup. Follow the approved v1 non-goals for backend parity and pre-existing ledger import cost.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/project.py` | MODIFY | The config must be available during startup without importing the collectors. |
| `packages/ai-parrot/tests/knowledge/wiki/test_standup_config.py` | CREATE | Use temporary base/overlay files and fresh-process import assertions. |

---

## Codebase Contract (Anti-Hallucination)

Verified at `75fe680a0`. Dependency-created imports below are planned contracts, not claims of current existence.

### Verified Imports

```python
from typing import Literal  # stdlib or existing pyproject dependency/test environment
from pydantic import BaseModel, ConfigDict, Field  # stdlib or existing pyproject dependency/test environment
from pathlib import Path  # stdlib or existing pyproject dependency/test environment
import pytest  # stdlib or existing pyproject dependency/test environment
import parrot.knowledge.wiki.project as subject  # verified source packages/ai-parrot/src/parrot/knowledge/wiki/project.py
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/project.py:382
class WikiProjectConfig(BaseModel):

# packages/ai-parrot/src/parrot/knowledge/wiki/project.py:816
class WikiEnvOverlay(BaseModel):

# packages/ai-parrot/src/parrot/knowledge/wiki/project.py:933
def load_effective_config(root: Path, env: str | None = None) -> WikiEffectiveConfig:
```

### Does NOT Exist

- `packages/ai-parrot/tests/knowledge/wiki/test_standup_config.py` is created by this task; do not assume it already exists.
- `list_pages(offset=...)`, `DecisionRecord.updated_at`, and a JiraPerson email field are not existing APIs. Do not invent them.
- Category names remain open strings; no new WikiPageCategory enum members are required.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/wiki/project.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/wiki/test_standup_config.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/project.py#WikiProjectConfig",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/project.py#WikiEnvOverlay",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/project.py#load_effective_config"
  ]
}
```

---

## Implementation Notes

Independent standup-config deliverable; uses existing verified code only and owns its declared files.

Use async I/O paths, existing lifecycle/context managers, module logging, strict types and Google-style docstrings. Black uses 120 columns; ruff is the lint gate. Keep tests isolated and file-scoped. Fresh dependency code may shift anchors: reverify before edits, and retain the semantic attachment site.

---

## Implementation Blueprint

### Steps (in order)

1. Verify the existing references and completed dependency interfaces — because the blueprint must match the executing worktree.
2. Apply the per-file blocks below in declared order and complete only bounded FILL IN work — because each task owns a limited surface.
3. Implement the listed adversarial cases and run Validation Commands — because the acceptance criteria cover observable behavior, not only imports.

---

### `packages/ai-parrot/src/parrot/knowledge/wiki/project.py` (MODIFY)

Anchor `    obsidian_sync: ObsidianSyncConfig | None = Field(` — occurrences: 1 (verified: `grep -F -c`), `packages/ai-parrot/src/parrot/knowledge/wiki/project.py:458`.

Anchor `    sync_graph: bool | None = None` — occurrences: 1 (verified: `grep -F -c`), `packages/ai-parrot/src/parrot/knowledge/wiki/project.py:859`.

```python
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field
# Define these models before WikiProjectConfig; retain existing BaseModel/Field/ConfigDict.
class StandupIdentityConfig(BaseModel):
    """Explicit non-secret wiki/Jira identity and task-assignment aliases."""
    model_config = ConfigDict(extra="forbid")
    wiki: str | None = None
    jira_account_id: str | None = None
    jira_display_name: str | None = None
    aliases: list[str] = Field(default_factory=list)

class StandupConfig(BaseModel):
    """Daily and period brief settings, safe to import on the hook fast path."""
    model_config = ConfigDict(extra="forbid")
    default_language: Literal["en", "es"] = "en"
    horizon_days: int = Field(default=7, ge=1, le=90)
    timezone: str | None = None
    week_start: Literal["monday", "sunday"] = "monday"
    out_dir: str | None = None
    me: StandupIdentityConfig = Field(default_factory=StandupIdentityConfig)
    ticket_status_map: dict[str, str] = Field(default_factory=lambda: dict(DEFAULT_TICKET_STATUS_MAP))
    project_map: dict[str, str] = Field(default_factory=dict)
    stale_ticket_days: int = 10
    stale_decision_days: int = 14
    llm_env: str = "WIKI_LIGHTWEIGHT_MODEL"
    # FILL IN: validators and exact default map from spec section 2; AC15.
# WikiProjectConfig: standup: StandupConfig = Field(default_factory=StandupConfig)
# WikiEnvOverlay: standup: StandupConfig | None = None
# FILL IN: Google-style field documentation; do not import the standup package.
```

**Why**: The config must be available during startup without importing the collectors.

---

### `packages/ai-parrot/tests/knowledge/wiki/test_standup_config.py` (CREATE)

```python
"""Regression cases for FEAT-627."""
from pathlib import Path
import pytest
import parrot.knowledge.wiki.project as subject


def test_config_defaults_and_overlay(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify config defaults and overlay."""
    # FILL IN: build isolated inputs and assert the corresponding AC below.
    # Use pytest.mark.asyncio / async def when exercising async APIs.
    raise NotImplementedError


def test_config_validation_and_import_budget(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify config validation and import budget."""
    # FILL IN: build isolated inputs and assert the corresponding AC below.
    # Use pytest.mark.asyncio / async def when exercising async APIs.
    raise NotImplementedError
```

**Why**: Use temporary base/overlay files and fresh-process import assertions.

---

### FILL IN checklist

- [ ] `packages/ai-parrot/src/parrot/knowledge/wiki/project.py` — complete the block instructions and tests within this task’s acceptance criteria; leave no implementation placeholders.
- [ ] `packages/ai-parrot/tests/knowledge/wiki/test_standup_config.py` — complete the block instructions and tests within this task’s acceptance criteria; leave no implementation placeholders.

---

## Acceptance Criteria

- [ ] All specified defaults and fields parse in base and overlay; typo keys are forbidden.
- [ ] Invalid timezone/language/week-start/horizon and noncanonical mapped ticket statuses are rejected.
- [ ] Overlay keeps typed StandupConfig and existing precedence; importing project does not import entities or standup.
- [ ] All declared-file tests pass; no ruff errors or unfinished implementation placeholders remain.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/wiki/test_standup_config.py -q`
- `pytest tests/knowledge/wiki/test_env_config.py -q`

---

## Test Specification

- All specified defaults and fields parse in base and overlay; typo keys are forbidden.
- Invalid timezone/language/week-start/horizon and noncanonical mapped ticket statuses are rejected.
- Overlay keeps typed StandupConfig and existing precedence; importing project does not import entities or standup.

Use temporary local state, deterministic clocks and fake network/model adapters. Test failures and negative cases as well as success. New tests live alongside the core distribution; legacy suites are validation references only unless explicitly declared MODIFY above.

---

## Agent Instructions

1. Run `$sdd-start TASK-4029`; implementation belongs in the feature worktree, never directly on dev.
2. Read the approved spec and verify dependency completion in `sdd/tasks/index/wikitoolkit-standup.json`.
3. Recheck imports/anchors, implement only declared files and run the validation commands.
4. Commit scoped implementation and finalize with `scripts.sdd.finalize_task` plus real `TaskCompletionEvidence` for the exact implementation HEAD. Do not manually move the task or manufacture completion evidence.

## Completion Note

Pending; owned by the evidence-based finalizer.

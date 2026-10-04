# TASK-4028: G9-safe Jira current-user API

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

Implement Jira half of M8/AC16. Add async myself() returning JiraPerson via parse._person. Fresh verification: _probe_auth_sync currently returns authentication metadata only, not response JSON. Extend that existing probe to project the successful response into account_id/display_name immediately; never attach raw user dictionaries or emailAddress to a result/log. Keep auth header/status detection intact and reuse the probe rather than inventing result["user"]. Ensure connection initialization uses the existing lifecycle. The synchronous transport stays inside the existing to_thread probe; no new HTTP library.

---

## Scope

Implement Jira half of M8/AC16. Add async myself() returning JiraPerson via parse._person. Fresh verification: _probe_auth_sync currently returns authentication metadata only, not response JSON. Extend that existing probe to project the successful response into account_id/display_name immediately; never attach raw user dictionaries or emailAddress to a result/log. Keep auth header/status detection intact and reuse the probe rather than inventing result["user"]. Ensure connection initialization uses the existing lifecycle. The synchronous transport stays inside the existing to_thread probe; no new HTTP library.

**NOT in scope**: changes outside the declared file table; new runtime dependencies; unrelated cleanup. Follow the approved v1 non-goals for backend parity and pre-existing ledger import cost.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/interfaces/jira/client.py` | MODIFY | The existing probe has no accountId payload; this required change is explicit to avoid a fabricated contract. |
| `packages/ai-parrot/tests/knowledge/wiki/test_jira_myself.py` | CREATE | Use synthetic transport responses including emailAddress as a negative control. |

---

## Codebase Contract (Anti-Hallucination)

Verified at `75fe680a0`. Dependency-created imports below are planned contracts, not claims of current existence.

### Verified Imports

```python
from .models import JiraPerson  # verified source packages/ai-parrot/src/parrot/interfaces/jira/models.py
from .parse import _person  # verified source packages/ai-parrot/src/parrot/interfaces/jira/parse.py
from pathlib import Path  # stdlib or existing pyproject dependency/test environment
import pytest  # stdlib or existing pyproject dependency/test environment
import parrot.interfaces.jira.client as subject  # verified source packages/ai-parrot/src/parrot/interfaces/jira/client.py
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/interfaces/jira/client.py:376
    def _probe_auth_sync(self) -> dict[str, Any]:

# packages/ai-parrot/src/parrot/interfaces/jira/client.py:460
    async def _probe_myself(self) -> dict[str, Any]:

# packages/ai-parrot/src/parrot/interfaces/jira/client.py:485
    async def verify_auth(self) -> dict[str, Any]:

# packages/ai-parrot/src/parrot/interfaces/jira/models.py:21
class JiraPerson(BaseModel):

# packages/ai-parrot/src/parrot/interfaces/jira/parse.py:47
def _person(raw_user: dict[str, Any] | None) -> JiraPerson | None:
```

### Does NOT Exist

- `packages/ai-parrot/tests/knowledge/wiki/test_jira_myself.py` is created by this task; do not assume it already exists.
- `list_pages(offset=...)`, `DecisionRecord.updated_at`, and a JiraPerson email field are not existing APIs. Do not invent them.
- Category names remain open strings; no new WikiPageCategory enum members are required.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/interfaces/jira/client.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/wiki/test_jira_myself.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/interfaces/jira/client.py#JiraInterface._probe_auth_sync",
    "sym:packages/ai-parrot/src/parrot/interfaces/jira/client.py#JiraInterface._probe_myself",
    "sym:packages/ai-parrot/src/parrot/interfaces/jira/client.py#JiraInterface.verify_auth",
    "sym:packages/ai-parrot/src/parrot/interfaces/jira/models.py#JiraPerson",
    "sym:packages/ai-parrot/src/parrot/interfaces/jira/parse.py#_person"
  ]
}
```

---

## Implementation Notes

Independent jira-current-user deliverable; uses existing verified code only and owns its declared files.

Use async I/O paths, existing lifecycle/context managers, module logging, strict types and Google-style docstrings. Black uses 120 columns; ruff is the lint gate. Keep tests isolated and file-scoped. Fresh dependency code may shift anchors: reverify before edits, and retain the semantic attachment site.

---

## Implementation Blueprint

### Steps (in order)

1. Verify the existing references and completed dependency interfaces — because the blueprint must match the executing worktree.
2. Apply the per-file blocks below in declared order and complete only bounded FILL IN work — because each task owns a limited surface.
3. Implement the listed adversarial cases and run Validation Commands — because the acceptance criteria cover observable behavior, not only imports.

---

### `packages/ai-parrot/src/parrot/interfaces/jira/client.py` (MODIFY)

Anchor `    async def _probe_myself(self) -> dict[str, Any]:` — occurrences: 1 (verified: `grep -F -c`), `packages/ai-parrot/src/parrot/interfaces/jira/client.py:460`.

```python
from .models import JiraPerson
from .parse import _person
# Add to JiraInterface, after _probe_myself:
async def myself(self) -> JiraPerson:
    """Return the authenticated user projected to G9-safe identity fields."""
    # FILL IN: initialize through existing lifecycle; use the extended safe probe.
    # Project response JSON inside the probe, never return/log the raw payload.
    # Preserve JiraAuthError semantics and reject unusable identity; AC7/AC16.
    raise NotImplementedError
```

**Why**: The existing probe has no accountId payload; this required change is explicit to avoid a fabricated contract.

---

### `packages/ai-parrot/tests/knowledge/wiki/test_jira_myself.py` (CREATE)

```python
"""Regression cases for FEAT-627."""
from pathlib import Path
import pytest
import parrot.interfaces.jira.client as subject


def test_myself_g9_projection(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify myself g9 projection."""
    # FILL IN: build isolated inputs and assert the corresponding AC below.
    # Use pytest.mark.asyncio / async def when exercising async APIs.
    raise NotImplementedError


def test_auth_and_malformed_user_failures(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify auth and malformed user failures."""
    # FILL IN: build isolated inputs and assert the corresponding AC below.
    # Use pytest.mark.asyncio / async def when exercising async APIs.
    raise NotImplementedError
```

**Why**: Use synthetic transport responses including emailAddress as a negative control.

---

### FILL IN checklist

- [ ] `packages/ai-parrot/src/parrot/interfaces/jira/client.py` — complete the block instructions and tests within this task’s acceptance criteria; leave no implementation placeholders.
- [ ] `packages/ai-parrot/tests/knowledge/wiki/test_jira_myself.py` — complete the block instructions and tests within this task’s acceptance criteria; leave no implementation placeholders.

---

## Acceptance Criteria

- [ ] Authenticated myself returns typed JiraPerson containing only account_id/display_name.
- [ ] 401/403 and Seraph failure still raise JiraAuthError; malformed/empty user payload fails actionably.
- [ ] Raw fixture emailAddress is absent from returned models, probe metadata and logs; no live Jira requests.
- [ ] All declared-file tests pass; no ruff errors or unfinished implementation placeholders remain.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/wiki/test_jira_myself.py -q`

---

## Test Specification

- Authenticated myself returns typed JiraPerson containing only account_id/display_name.
- 401/403 and Seraph failure still raise JiraAuthError; malformed/empty user payload fails actionably.
- Raw fixture emailAddress is absent from returned models, probe metadata and logs; no live Jira requests.

Use temporary local state, deterministic clocks and fake network/model adapters. Test failures and negative cases as well as success. New tests live alongside the core distribution; legacy suites are validation references only unless explicitly declared MODIFY above.

---

## Agent Instructions

1. Run `$sdd-start TASK-4028`; implementation belongs in the feature worktree, never directly on dev.
2. Read the approved spec and verify dependency completion in `sdd/tasks/index/wikitoolkit-standup.json`.
3. Recheck imports/anchors, implement only declared files and run the validation commands.
4. Commit scoped implementation and finalize with `scripts.sdd.finalize_task` plus real `TaskCompletionEvidence` for the exact implementation HEAD. Do not manually move the task or manufacture completion evidence.

## Completion Note

Pending; owned by the evidence-based finalizer.

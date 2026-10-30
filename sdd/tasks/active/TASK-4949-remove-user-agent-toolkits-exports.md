# TASK-4949: Remove user_agent_toolkits code; export the new oauth2 surface

**Feature**: FEAT-773 — Delegated Auth Connections — S-1 Connections Core
**Spec**: `sdd/specs/delegated-auth-connections.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-4948, TASK-4943, TASK-4938
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 6 (U2, AC-3, AC-16). Per-agent enablement is retired. Once no reader is left, delete
`UserAgentToolkitRow`, the three repository functions, `USER_AGENT_TOOLKITS_COLLECTION` and the deprecated
`IntegrationDescriptor.enabled_on_agent`, and export the new public names from `parrot.auth.oauth2`.
The DocumentDB collection itself is left in place (spec Worktree Strategy: code change only).

---

## Scope

- `models.py`: delete `UserAgentToolkitRow`, `enabled_on_agent`; fix the module docstring.
- `persistence.py`: delete `USER_AGENT_TOOLKITS_COLLECTION`, `upsert_user_agent_toolkit`, `list_user_agent_toolkits`,
  `delete_user_agent_toolkits_by_provider`, the section header and the model import.
- `oauth2/__init__.py`: drop `UserAgentToolkitRow`; export `ConnectionEvent`, `ChannelNotifier`, `ChannelNotifierRegistry`,
  `ConnectionEventPublisher`, `OAuth2ProviderDescriptor`, `RefreshPolicy`, `StandardOAuth2Manager`,
  `DescriptorOAuth2Provider`, `register_descriptor_providers`, `list_users_integrations` (respect the module's existing
  import style; if it imports eagerly, keep `descriptor` lazy only if an import cycle appears).
- Test: AC-3 grep — no `user_agent_toolkit` reader/writer left in `packages/`.

**NOT in scope**: dropping the DocumentDB collection; touching tests owned by TASK-4964.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/auth/oauth2/models.py` | MODIFY | delete UserAgentToolkitRow + enabled_on_agent |
| `packages/ai-parrot/src/parrot/auth/oauth2/persistence.py` | MODIFY | delete toolkit repository |
| `packages/ai-parrot/src/parrot/auth/oauth2/__init__.py` | MODIFY | exports |
| `packages/ai-parrot/tests/unit/auth/test_no_user_agent_toolkits.py` | CREATE | AC-3 guard |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: verified against `dev` @ `a848d5a73e` (2026-10-30) while writing this task.
> Use these exact imports and signatures. Anything not listed: VERIFY it exists before using it.

### Verified Imports
```python
from parrot.auth.oauth2.events import ConnectionEvent, ChannelNotifier, ChannelNotifierRegistry, ConnectionEventPublisher  # TASK-4938
from parrot.auth.oauth2.descriptor import (OAuth2ProviderDescriptor, RefreshPolicy, StandardOAuth2Manager,
                                           DescriptorOAuth2Provider, register_descriptor_providers)   # TASK-4939/4943
from parrot.auth.oauth2.persistence import list_users_integrations                                    # TASK-4946
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/auth/oauth2/__init__.py
    UserAgentToolkitRow,          # :26 anchor (import list)   ;  "UserAgentToolkitRow",  # :47 (__all__, distinct text)
# packages/ai-parrot/src/parrot/auth/oauth2/models.py
class UserAgentToolkitRow(BaseModel):                                  # :183 anchor
# packages/ai-parrot/src/parrot/auth/oauth2/persistence.py
USER_AGENT_TOOLKITS_COLLECTION: str = "user_agent_toolkits"            # :34 anchor
async def upsert_user_agent_toolkit(row: UserAgentToolkitRow) -> None: # :113 anchor ; list_ (:148) ; delete_ (:171)
```

### Does NOT Exist
- After this task: ~~`UserAgentToolkitRow`~~, ~~`list_user_agent_toolkits`~~, ~~`upsert_user_agent_toolkit`~~,
  ~~`delete_user_agent_toolkits_by_provider`~~ — gone; any remaining reference is a bug.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/auth/oauth2/models.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/auth/oauth2/persistence.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/auth/oauth2/__init__.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/unit/auth/test_no_user_agent_toolkits.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/auth/oauth2/models.py#UserAgentToolkitRow",
    "sym:packages/ai-parrot/src/parrot/auth/oauth2/persistence.py#list_user_agent_toolkits"
  ]
}
```

---

## Implementation Notes

- Before deleting, `grep -rn "user_agent_toolkit\|UserAgentToolkitRow\|enabled_on_agent" packages/*/src` must show
  only the definitions; tests under `tests/integration/oauth2/` still reference them — those are TASK-4964's files.

---

## Implementation Blueprint

> Executor-ready starting point. Write each block to its declared path, then complete every
> `# FILL IN:` marker. Business branches, edge cases and test bodies are stubs by design.
> Never change a signature, class name or file path the blueprint fixes.

### Steps (in order)
1. Grep for readers (must be definitions only) — *why*: U2 removal must not orphan a caller.
2. Delete from models/persistence (blocks) — *why*: hard cut, spec §7.
3. Update `__init__` exports.
4. Add the guard test.

### `packages/ai-parrot/src/parrot/auth/oauth2/models.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'class UserAgentToolkitRow(BaseModel):' oauth2/models.py → :183)
# DELETE the class UserAgentToolkitRow (:183-end of class) and the line
#   `    enabled_on_agent: bool = Field(default=False, exclude=True)` (left deprecated by TASK-4946)
```

### `packages/ai-parrot/src/parrot/auth/oauth2/persistence.py` (MODIFY)
```python
# occurrences: 1 each (verified: 'USER_AGENT_TOOLKITS_COLLECTION: str = "user_agent_toolkits"' :34,
#   'async def upsert_user_agent_toolkit(row: UserAgentToolkitRow) -> None:' :113)
# DELETE: the constant (:34), the `# user_agent_toolkits repository` section (:109-end of delete_user_agent_toolkits_by_provider),
#         `UserAgentToolkitRow` from the models import (:25) and the docstring mention (:9)
```

### `packages/ai-parrot/src/parrot/auth/oauth2/__init__.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '^    UserAgentToolkitRow,$' oauth2/__init__.py → :26; __all__ entry at :47 is a quoted string)
# DELETE `    UserAgentToolkitRow,` (:26) and `"UserAgentToolkitRow",` (:47)
# FILL IN: add the new names (Scope list) to the imports and __all__ following the file's current style
```

### FILL IN checklist
- [ ] confirm zero readers before deletion
- [ ] `__init__.py` new exports
- [ ] `test_no_user_agent_toolkits.py`

---

## Acceptance Criteria

- [ ] AC-3: `grep -rn user_agent_toolkit packages/*/src` returns nothing
- [ ] `from parrot.auth.oauth2 import StandardOAuth2Manager, ConnectionEventPublisher, list_users_integrations` works

---

## Validation Commands

- `pytest packages/ai-parrot/tests/unit/auth/test_no_user_agent_toolkits.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/unit/auth/test_no_user_agent_toolkits.py
from pathlib import Path

def test_no_user_agent_toolkits_reader_or_writer():
    root = Path(__file__).resolve().parents[4]          # packages/
    hits = [p for p in root.glob("*/src/**/*.py") if "user_agent_toolkit" in p.read_text(errors="ignore")]
    assert hits == []

def test_new_oauth2_exports():
    from parrot.auth.oauth2 import ConnectionEventPublisher, StandardOAuth2Manager, list_users_integrations  # noqa: F401
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `dev`
   (`python -m scripts.sdd.ensure_worktree --slug delegated-auth-connections --feature-id FEAT-773`)
2. **Read the spec** (`sdd/specs/delegated-auth-connections.spec.md`) — at least §2, the module section named in Context, §5 and §7
3. **Check dependencies** — every `Depends-on` task must be `"done"` in `sdd/tasks/index/delegated-auth-connections.json`
4. **Verify the Codebase Contract** before writing ANY code (re-grep each anchor; line numbers drift). If an entry is stale, fix the contract in this file first
5. **Update status** in the per-spec index → `"in-progress"` (set `started_at`) and commit only that index file
6. **Implement** from the Implementation Blueprint; complete every `# FILL IN:`; never change a signature or path the blueprint fixes
7. **Verify** — run the Validation Commands with `PYTHONPATH` set to every touched `packages/<dist>/src` (the shared `.venv` imports the main checkout otherwise)
8. **Commit the code** — stage only the files listed above (never `git add .` / `-A`)
9. **Close the task** with `scripts/sdd/close_task.sh <TASK-ID> delegated-auth-connections verified`
10. **Fill in the Completion Note**, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any

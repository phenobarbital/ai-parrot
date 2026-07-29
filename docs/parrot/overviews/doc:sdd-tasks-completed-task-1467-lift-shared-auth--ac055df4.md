---
type: Wiki Overview
title: 'TASK-1467: Lift Shared Auth Primitives to integrations/core/auth/'
id: doc:sdd-tasks-completed-task-1467-lift-shared-auth-primitives-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: This is the gating task for the entire feature. The Telegram integration
relates_to:
- concept: mod:parrot.integrations.core.auth
  rel: mentions
- concept: mod:parrot.integrations.core.auth.oauth2_providers
  rel: mentions
- concept: mod:parrot.integrations.core.auth.post_auth
  rel: mentions
- concept: mod:parrot.integrations.telegram
  rel: mentions
---

# TASK-1467: Lift Shared Auth Primitives to integrations/core/auth/

**Feature**: FEAT-225 — JiraToolkit Integrations OAuth2
**Spec**: `sdd/specs/jiratoolkit-integrations-oauth2.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

This is the gating task for the entire feature. The Telegram integration
currently owns `PostAuthProvider`, `PostAuthRegistry`, `OAUTH2_PROVIDERS`,
and `OAuth2ProviderConfig` in `telegram/post_auth.py` and
`telegram/oauth2_providers.py`. These are provider-agnostic abstractions
that Slack and MS Teams also need. Moving them to `integrations/core/auth/`
allows all three integrations to share one source of truth.

Implements Spec §3 Module 1.

---

## Scope

- Create `packages/ai-parrot-integrations/src/parrot/integrations/core/auth/__init__.py` that re-exports `PostAuthProvider`, `PostAuthRegistry`, `OAUTH2_PROVIDERS`, `OAuth2ProviderConfig`, and `get_provider`.
- Move `PostAuthProvider` protocol and `PostAuthRegistry` class from `telegram/post_auth.py` to `core/auth/post_auth.py` (copy content, then delete original).
- Move `OAuth2ProviderConfig`, `OAUTH2_PROVIDERS`, and `get_provider` from `telegram/oauth2_providers.py` to `core/auth/oauth2_providers.py` (copy content, then delete original).
- Update ALL imports in the Telegram integration to use the new `core.auth.*` paths:
  - `telegram/auth.py`
  - `telegram/wrapper.py`
  - `telegram/post_auth_jira.py`
  - `telegram/jira_commands.py` (if it imports from these modules)
  - Any other files that import from `telegram/post_auth` or `telegram/oauth2_providers`
- Delete the original `telegram/post_auth.py` and `telegram/oauth2_providers.py` files (hard rename, no backwards-compat shims).
- Update existing tests to import from the new paths.

**NOT in scope**: Adding new auth providers, Slack/Teams command modules, or any OAuth callback changes.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-integrations/src/parrot/integrations/core/auth/__init__.py` | CREATE | Re-exports: PostAuthProvider, PostAuthRegistry, OAUTH2_PROVIDERS, OAuth2ProviderConfig, get_provider |
| `packages/ai-parrot-integrations/src/parrot/integrations/core/auth/post_auth.py` | CREATE | PostAuthProvider protocol + PostAuthRegistry (moved from telegram/) |
| `packages/ai-parrot-integrations/src/parrot/integrations/core/auth/oauth2_providers.py` | CREATE | OAuth2ProviderConfig, OAUTH2_PROVIDERS, get_provider (moved from telegram/) |
| `packages/ai-parrot-integrations/src/parrot/integrations/telegram/post_auth.py` | DELETE | Replaced by core/auth/post_auth.py |
| `packages/ai-parrot-integrations/src/parrot/integrations/telegram/oauth2_providers.py` | DELETE | Replaced by core/auth/oauth2_providers.py |
| `packages/ai-parrot-integrations/src/parrot/integrations/telegram/auth.py` | MODIFY | Update imports to core.auth.* |
| `packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py` | MODIFY | Update imports to core.auth.* |
| `packages/ai-parrot-integrations/src/parrot/integrations/telegram/post_auth_jira.py` | MODIFY | Update imports to core.auth.* |
| `packages/ai-parrot-integrations/tests/integrations/telegram/` | MODIFY | Update test imports |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# Current paths (to be moved):
from parrot.integrations.telegram.post_auth import PostAuthProvider, PostAuthRegistry  # post_auth.py:39, :95
from parrot.integrations.telegram.oauth2_providers import OAUTH2_PROVIDERS, OAuth2ProviderConfig, get_provider  # oauth2_providers.py:13, :32, :55

# After move, new imports will be:
# from parrot.integrations.core.auth.post_auth import PostAuthProvider, PostAuthRegistry
# from parrot.integrations.core.auth.oauth2_providers import OAUTH2_PROVIDERS, OAuth2ProviderConfig, get_provider
# from parrot.integrations.core.auth import PostAuthProvider, PostAuthRegistry  (re-export)

# Existing core/ directory:
# packages/ai-parrot-integrations/src/parrot/integrations/core/__init__.py exists
# packages/ai-parrot-integrations/src/parrot/integrations/core/state.py exists
# packages/ai-parrot-integrations/src/parrot/integrations/core/auth/ DOES NOT EXIST (will be created)
```

### Existing Signatures to Use

```python
# packages/ai-parrot-integrations/src/parrot/integrations/telegram/post_auth.py
class PostAuthProvider(Protocol):  # line 39
    provider_name: str
    async def build_auth_url(self, session, config, callback_base_url) -> str: ...
    async def handle_result(self, data, session, primary_auth_data=None) -> bool: ...

class PostAuthRegistry:  # line 95
    def __init__(self) -> None: ...  # line 108
    def register(self, provider: PostAuthProvider) -> None: ...  # line 112
    def get(self, name: str) -> Optional[PostAuthProvider]: ...  # line 136

# packages/ai-parrot-integrations/src/parrot/integrations/telegram/oauth2_providers.py
class OAuth2ProviderConfig:  # line 13
    name: str
    authorization_url: str
    token_url: str
    scopes: List[str]
    # ...

OAUTH2_PROVIDERS: Dict[str, OAuth2ProviderConfig] = { ... }  # line 32
def get_provider(key: str) -> OAuth2ProviderConfig: ...  # line 55
```

### Does NOT Exist

- ~~`parrot.integrations.core.auth`~~ — does not exist yet (will be created by this task)
- ~~`parrot.integrations.core.auth.post_auth`~~ — does not exist yet
- ~~`parrot.integrations.core.auth.oauth2_providers`~~ — does not exist yet

---

## Implementation Notes

### Pattern to Follow

The move is a pure relocation + import update. The code itself does not change.

```bash
# 1. Create the new directory
mkdir -p packages/ai-parrot-integrations/src/parrot/integrations/core/auth/

# 2. Copy files
cp telegram/post_auth.py → core/auth/post_auth.py
cp telegram/oauth2_providers.py → core/auth/oauth2_providers.py

# 3. Create __init__.py with re-exports
# 4. grep -r for all imports of the old paths and update them
# 5. Delete the originals
# 6. Run tests to confirm nothing broke
```

### Key Constraints

- Hard rename: do NOT leave shims, re-exports, or `import *` in the old locations.
- ALL imports across the ENTIRE repo must be updated. Use `grep -r` to find them all.
- The `telegram/post_auth_jira.py` file stays in `telegram/` — only its import of `PostAuthProvider` changes.

### References in Codebase

- `packages/ai-parrot-integrations/src/parrot/integrations/telegram/post_auth.py` — source of truth for PostAuthProvider/Registry
- `packages/ai-parrot-integrations/src/parrot/integrations/telegram/oauth2_providers.py` — source of truth for OAUTH2_PROVIDERS
- `packages/ai-parrot-integrations/src/parrot/integrations/core/state.py` — existing module in core/ (confirms the directory structure)

---

## Acceptance Criteria

- [ ] `from parrot.integrations.core.auth.post_auth import PostAuthProvider, PostAuthRegistry` works
- [ ] `from parrot.integrations.core.auth.oauth2_providers import OAUTH2_PROVIDERS, get_provider` works
- [ ] `from parrot.integrations.core.auth import PostAuthProvider, PostAuthRegistry` works (re-export)
- [ ] `telegram/post_auth.py` and `telegram/oauth2_providers.py` are DELETED
- [ ] No remaining imports of `parrot.integrations.telegram.post_auth` or `parrot.integrations.telegram.oauth2_providers` anywhere in the repo
- [ ] All existing Telegram tests pass: `pytest tests/integrations/telegram/ -v`
- [ ] No linting errors: `ruff check packages/ai-parrot-integrations/`

---

## Test Specification

```python
# tests/integrations/core/test_auth_imports.py
def test_post_auth_imports():
    from parrot.integrations.core.auth.post_auth import PostAuthProvider, PostAuthRegistry
    assert PostAuthProvider is not None
    assert PostAuthRegistry is not None

def test_oauth2_providers_imports():
    from parrot.integrations.core.auth.oauth2_providers import OAUTH2_PROVIDERS, get_provider
    assert isinstance(OAUTH2_PROVIDERS, dict)
    assert callable(get_provider)

def test_reexport_from_init():
    from parrot.integrations.core.auth import PostAuthProvider, PostAuthRegistry
    assert PostAuthProvider is not None

def test_old_paths_removed():
    """Confirm the old modules no longer exist at the old paths."""
    import importlib
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("parrot.integrations.telegram.post_auth")
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("parrot.integrations.telegram.oauth2_providers")
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — this task has no dependencies
3. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source)
   - Confirm every class/method in "Existing Signatures" still has the listed attributes
   - If anything has changed, update the contract FIRST, then implement
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
4. **Update status** in `sdd/tasks/index/jiratoolkit-integrations-oauth2.json` → `"in-progress"` with your session ID
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-1467-lift-shared-auth-primitives.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (claude-sonnet-4-6)
**Date**: 2026-06-04
**Notes**: Created `integrations/core/auth/__init__.py`, `post_auth.py`, and `oauth2_providers.py` with content moved from `telegram/`. Updated imports in `telegram/auth.py`, `telegram/wrapper.py`, and all test files referencing the old paths. Deleted originals using `git rm`. Created core auth import tests in `tests/integrations/core/test_auth_imports.py`. Pre-existing ruff warnings in `telegram/__init__.py` are unrelated to this task.

**Deviations from spec**: none

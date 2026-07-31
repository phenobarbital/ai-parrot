---
type: Wiki Overview
title: 'TASK-1342: OAuth2 Relocation to parrot/auth/oauth2/'
id: doc:sdd-tasks-completed-task-1342-oauth2-relocation-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: The `integrations/oauth2/` package (7 files, ~37 KB) provides OAuth2
relates_to:
- concept: mod:parrot.auth.oauth2
  rel: mentions
- concept: mod:parrot.auth.oauth2.jira_provider
  rel: mentions
- concept: mod:parrot.auth.oauth2.models
  rel: mentions
- concept: mod:parrot.auth.oauth2.registry
  rel: mentions
- concept: mod:parrot.auth.oauth2.service
  rel: mentions
- concept: mod:parrot.auth.oauth2_base
  rel: mentions
- concept: mod:parrot.integrations
  rel: mentions
---

# TASK-1342: OAuth2 Relocation to parrot/auth/oauth2/

**Feature**: FEAT-202 — ai-parrot-integrations
**Spec**: `sdd/specs/ai-parrot-integrations.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

The `integrations/oauth2/` package (7 files, ~37 KB) provides OAuth2
infrastructure (provider registry, persistence, Jira/O365 providers) that
is consumed by 5 production files **outside** of `parrot/integrations/`.
It transcends messaging channels — it's authentication infrastructure.
Relocating it to `parrot/auth/oauth2/` removes the coupling and allows
the satellite extraction to proceed cleanly.

This is a core-only change with no dependency on the satellite package.

Implements **Spec Module 10**.

---

## Scope

- Move `packages/ai-parrot/src/parrot/integrations/oauth2/` →
  `packages/ai-parrot/src/parrot/auth/oauth2/`
  (7 files: `__init__.py`, `jira_provider.py`, `models.py`,
  `o365_provider.py`, `persistence.py`, `registry.py`, `service.py`).
- Update all internal imports within the moved files
  (`from parrot.integrations.oauth2.X` → `from parrot.auth.oauth2.X`).
- Update the 5 production consumers:
  1. `parrot/auth/routes.py:34`
  2. `parrot/auth/oauth2_routes.py:28`
  3. `parrot/handlers/integrations.py:27,187`
  4. `parrot/manager/manager.py:1659-1660`
- Remove the old `integrations/oauth2/` directory after move.
- Move related tests if any exist under `tests/`.

**NOT in scope**: Creating error-guía stub at old path (done in TASK-1347
common files task). No functional changes to oauth2 logic.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/auth/oauth2/__init__.py` | CREATE (move) | Moved from integrations/oauth2/ |
| `parrot/auth/oauth2/jira_provider.py` | CREATE (move) | JiraOAuth2Provider |
| `parrot/auth/oauth2/models.py` | CREATE (move) | AuthRequiredEnvelope, EnableResponse |
| `parrot/auth/oauth2/o365_provider.py` | CREATE (move) | O365 provider |
| `parrot/auth/oauth2/persistence.py` | CREATE (move) | list_user_agent_toolkits |
| `parrot/auth/oauth2/registry.py` | CREATE (move) | OAuth2ProviderRegistry, register_oauth2_provider |
| `parrot/auth/oauth2/service.py` | CREATE (move) | IntegrationsService |
| `parrot/auth/routes.py` | MODIFY | Update oauth2 import path (line 34) |
| `parrot/auth/oauth2_routes.py` | MODIFY | Update oauth2 import path (line 28) |
| `parrot/handlers/integrations.py` | MODIFY | Update oauth2 import paths (lines 27, 187) |
| `parrot/manager/manager.py` | MODIFY | Update oauth2 import paths (lines 1659-1660) |
| `parrot/integrations/oauth2/` | DELETE | Remove old directory after move |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# Current imports that MUST be updated:
from parrot.integrations.oauth2.service import IntegrationsService  # auth/routes.py:34
from parrot.integrations.oauth2.service import IntegrationsService  # auth/oauth2_routes.py:28
from parrot.integrations.oauth2.service import IntegrationsService  # handlers/integrations.py:27
from parrot.integrations.oauth2.models import EnableResponse        # handlers/integrations.py:187
from parrot.integrations.oauth2.jira_provider import JiraOAuth2Provider  # manager/manager.py:1659
from parrot.integrations.oauth2.registry import register_oauth2_provider  # manager/manager.py:1660

# New imports after relocation:
# from parrot.auth.oauth2.service import IntegrationsService
# from parrot.auth.oauth2.models import EnableResponse
# from parrot.auth.oauth2.jira_provider import JiraOAuth2Provider
# from parrot.auth.oauth2.registry import register_oauth2_provider
```

### Existing Signatures to Use

```python
# parrot/integrations/oauth2/__init__.py — exports to preserve
from .models import ...
from .registry import OAuth2ProviderRegistry, register_oauth2_provider
from .service import IntegrationsService

# parrot/integrations/oauth2/service.py — main class
class IntegrationsService:
    ...

# parrot/integrations/oauth2/registry.py — registry pattern
class OAuth2ProviderRegistry:
    ...
def register_oauth2_provider(...):
    ...
```

### Does NOT Exist

- ~~`parrot.auth.oauth2`~~ — does NOT exist yet; this task creates it
- ~~`parrot.auth.oauth2_base`~~ — `oauth2_base.py` exists at
  `parrot/auth/oauth2_base.py` but is a different file (OAuth2 base
  class); do NOT confuse with the relocated package

---

## Implementation Notes

### Pattern to Follow

Use `git mv` to move files (preserves history):
```bash
mkdir -p packages/ai-parrot/src/parrot/auth/oauth2
git mv packages/ai-parrot/src/parrot/integrations/oauth2/*.py \
  packages/ai-parrot/src/parrot/auth/oauth2/
```

Then update internal imports within the moved files (any
`from parrot.integrations.oauth2.X` or relative imports that assumed
the old location).

### Key Constraints

- All 5 consumer files must be updated atomically — partial update
  breaks imports.
- The `manager/manager.py` imports are lazy (inside function bodies
  at lines 1659-1660); the others are top-level.
- Verify no other files import from `parrot.integrations.oauth2` via
  `grep -rn 'integrations.oauth2' packages/ai-parrot/src/`.

---

## Acceptance Criteria

- [ ] `from parrot.auth.oauth2.service import IntegrationsService` works
- [ ] `from parrot.auth.oauth2.registry import OAuth2ProviderRegistry` works
- [ ] `from parrot.auth.oauth2.models import EnableResponse` works
- [ ] All 5 consumer files updated and importable
- [ ] Old `parrot/integrations/oauth2/` directory removed
- [ ] `grep -rn 'integrations.oauth2' packages/ai-parrot/src/` returns empty
  (excluding comments/docstrings)
- [ ] Existing tests still pass

---

## Test Specification

```python
# Verify import paths work
def test_oauth2_new_path():
    from parrot.auth.oauth2.service import IntegrationsService
    from parrot.auth.oauth2.registry import OAuth2ProviderRegistry
    from parrot.auth.oauth2.models import EnableResponse
    assert IntegrationsService is not None
    assert OAuth2ProviderRegistry is not None

def test_oauth2_old_path_gone():
    import pytest
    with pytest.raises(ImportError):
        from parrot.integrations.oauth2.service import IntegrationsService
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — this task has none
3. **Verify the Codebase Contract** — grep for all oauth2 consumers
4. **Use `git mv`** to preserve file history
5. **Update internal imports** within the moved files
6. **Update all 5 consumer files** (verify via grep)
7. **Verify** all acceptance criteria are met

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:
**Deviations from spec**: none | describe if any

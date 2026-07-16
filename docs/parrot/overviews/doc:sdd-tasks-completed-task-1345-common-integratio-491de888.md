---
type: Wiki Overview
title: 'TASK-1345: Common Integrations Files Move'
id: doc:sdd-tasks-completed-task-1345-common-integrations-files-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Move the shared/common files from `parrot/integrations/` to the satellite
relates_to:
- concept: mod:parrot.integrations
  rel: mentions
- concept: mod:parrot.integrations.models
  rel: mentions
---

# TASK-1345: Common Integrations Files Move

**Feature**: FEAT-202 — ai-parrot-integrations
**Spec**: `sdd/specs/ai-parrot-integrations.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-1344
**Assigned-to**: unassigned

---

## Context

Move the shared/common files from `parrot/integrations/` to the satellite
package. These files are imported by all channels and must be moved first.
After this task, the core `parrot/integrations/` directory retains only a
stub `__init__.py` that provides error guidance when extras are not installed.

Implements **Spec Module 7**.

---

## Scope

- Move to `packages/ai-parrot-integrations/src/parrot/integrations/`:
  - `__init__.py` (lazy PEP 562 `__getattr__` with `_LAZY_EXPORTS`)
  - `manager.py` (`IntegrationBotManager`)
  - `models.py` (`IntegrationBotConfig` + per-channel config imports)
  - `parser.py` (`ResponseParser`)
  - `core/state.py` (`InMemoryStateStore`)
  - `core/__init__.py`
- Replace the core's `parrot/integrations/__init__.py` with a stub that:
  - Detects which submodules are available via the satellite package.
  - On missing submodule access, raises `ImportError` with guidance:
    `"Install ai-parrot-integrations[<channel>] to use X integration"`.
- Update internal imports within moved files (relative imports may need
  adjustment since the package root changes).
- Verify `from parrot.integrations import IntegrationBotManager` still
  works when satellite is installed (PEP 420 namespace resolution).

**NOT in scope**: Moving channel subdirectories (separate tasks per channel).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-integrations/src/parrot/integrations/__init__.py` | CREATE (move) | Lazy PEP 562 exports |
| `packages/ai-parrot-integrations/src/parrot/integrations/manager.py` | CREATE (move) | IntegrationBotManager |
| `packages/ai-parrot-integrations/src/parrot/integrations/models.py` | CREATE (move) | IntegrationBotConfig |
| `packages/ai-parrot-integrations/src/parrot/integrations/parser.py` | CREATE (move) | ResponseParser |
| `packages/ai-parrot-integrations/src/parrot/integrations/core/__init__.py` | CREATE (move) | Core subpackage |
| `packages/ai-parrot-integrations/src/parrot/integrations/core/state.py` | CREATE (move) | InMemoryStateStore |
| `packages/ai-parrot/src/parrot/integrations/__init__.py` | MODIFY | Replace with error-guía stub |
| `packages/ai-parrot/src/parrot/integrations/manager.py` | DELETE | Moved to satellite |
| `packages/ai-parrot/src/parrot/integrations/models.py` | DELETE | Moved to satellite |
| `packages/ai-parrot/src/parrot/integrations/parser.py` | DELETE | Moved to satellite |
| `packages/ai-parrot/src/parrot/integrations/core/` | DELETE | Moved to satellite |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# parrot/integrations/__init__.py:17-36 — lazy exports to preserve
_LAZY_EXPORTS = {
    "IntegrationBotConfig": ".models",       # line 18
    "TelegramAgentConfig": ".models",        # line 19
    "MSTeamsAgentConfig": ".models",         # line 20
    "WhatsAppAgentConfig": ".models",        # line 21
    "SlackAgentConfig": ".models",           # line 22
    "IntegrationBotManager": ".manager",     # line 23
}

# parrot/integrations/manager.py:12,18-22 — runtime imports
from aiogram import Bot, Dispatcher
from ..human import (
    HumanInteractionManager,
    TelegramHumanChannel,
    set_default_human_manager,
)

# parrot/integrations/models.py:6-9 — per-channel config imports
# (these import from channel subdirs which will be moved later)

# parrot/integrations/models.py:13
class IntegrationBotConfig:  # dataclass
```

### Existing Signatures to Use

```python
# parrot/integrations/manager.py:42
class IntegrationBotManager:
    human_manager: Optional[HumanInteractionManager]  # ~line 70
```

### Does NOT Exist

- ~~`parrot.integrations.BaseIntegration`~~ — no such class
- ~~`parrot.integrations.channel_registry`~~ — no such module

---

## Implementation Notes

### Pattern to Follow — Error-Guía Stub

```python
# packages/ai-parrot/src/parrot/integrations/__init__.py (STUB)
"""Integrations stub — actual implementations in ai-parrot-integrations."""

_CHANNEL_EXTRAS = {
    "slack": "slack", "telegram": "telegram", "msteams": "msteams",
    "whatsapp": "whatsapp", "matrix": "matrix",
}

def __getattr__(name: str):
    # Try PEP 420 namespace resolution first (satellite installed)
    # If that fails, give a helpful error
    raise ImportError(
        f"'{name}' requires ai-parrot-integrations. "
        f"Install with: pip install ai-parrot-integrations[all]"
    )
```

### Key Constraints

- `manager.py` imports from `..human` (relative) — these must become
  absolute imports since the package root changes to the satellite.
- `models.py` imports per-channel configs which aren't moved yet —
  use lazy/conditional imports temporarily.
- The stub `__init__.py` in core must NOT conflict with the satellite's
  `__init__.py` under PEP 420 — test namespace resolution carefully.

---

## Acceptance Criteria

- [ ] `from parrot.integrations import IntegrationBotManager` works with satellite installed
- [ ] `from parrot.integrations.models import IntegrationBotConfig` works
- [ ] Stub `__init__.py` in core gives helpful error when satellite NOT installed
- [ ] All moved files importable from their new location
- [ ] Internal imports within moved files work correctly
- [ ] No linting errors in moved files

---

## Test Specification

```python
def test_lazy_exports_work():
    from parrot.integrations import IntegrationBotManager
    assert IntegrationBotManager is not None

def test_models_importable():
    from parrot.integrations.models import IntegrationBotConfig
    assert IntegrationBotConfig is not None
```

---

## Agent Instructions

When you pick up this task:

1. Verify TASK-1344 (scaffold) is complete
2. Read all files being moved in their entirety
3. Move files to satellite, adjusting relative imports to absolute
4. Create the error-guía stub in core
5. Test PEP 420 namespace resolution
6. Verify no broken imports

---

## Completion Note

*(Agent fills this in when done)*

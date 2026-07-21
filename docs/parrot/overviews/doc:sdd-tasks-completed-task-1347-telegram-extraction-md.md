---
type: Wiki Overview
title: 'TASK-1347: Telegram Channel Extraction'
id: doc:sdd-tasks-completed-task-1347-telegram-extraction-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Move the Telegram channel integration (29 Python files, ~1 MB) from
relates_to:
- concept: mod:parrot.integrations
  rel: mentions
- concept: mod:parrot.integrations.telegram
  rel: mentions
- concept: mod:parrot.integrations.telegram.combined_callback
  rel: mentions
- concept: mod:parrot.integrations.telegram.jira_commands
  rel: mentions
- concept: mod:parrot.integrations.telegram.wrapper
  rel: mentions
- concept: mod:parrot.voice
  rel: mentions
---

# TASK-1347: Telegram Channel Extraction

**Feature**: FEAT-202 — ai-parrot-integrations
**Spec**: `sdd/specs/ai-parrot-integrations.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-1345
**Assigned-to**: unassigned

---

## Context

Move the Telegram channel integration (29 Python files, ~1 MB) from
`parrot/integrations/telegram/` to the satellite package. Telegram is
the largest channel — it includes jira_commands, combined_callback,
webhooks, voice handling, and more. Several core files import from
telegram (jira_specialist.py, handlers/agent.py) — these continue
working via PEP 420 namespace extension.

Implements **Spec Module 3**.

---

## Scope

- Move `packages/ai-parrot/src/parrot/integrations/telegram/` →
  `packages/ai-parrot-integrations/src/parrot/integrations/telegram/`
  (29 files, byte-identical).
- Move related tests:
  - `packages/ai-parrot/tests/integrations/telegram/`
  - `packages/ai-parrot/tests/test_telegram_integration.py`
  - `packages/ai-parrot/tests/test_telegram_crew/`
  - `packages/ai-parrot/tests/integrations/test_telegram_photo_attachments.py`
  - `packages/ai-parrot/tests/integrations/test_telegram_wrapper_send.py`
- Verify PEP 420 resolution for cross-package consumers:
  - `parrot/bots/jira_specialist.py` → `TelegramOAuthNotifier`
  - `parrot/handlers/agent.py` → `telegram.combined_callback`
- Remove old directory from core.

**NOT in scope**: Changing telegram wrapper logic. Updating pyproject.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-integrations/src/parrot/integrations/telegram/` | CREATE (move) | 29 Python files |
| `packages/ai-parrot-integrations/tests/integrations/telegram/` | CREATE (move) | Telegram tests |
| `packages/ai-parrot-integrations/tests/test_telegram_crew/` | CREATE (move) | Crew tests |
| `packages/ai-parrot/src/parrot/integrations/telegram/` | DELETE | Removed from core |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# Cross-package consumers (MUST keep working via PEP 420):
from parrot.integrations.telegram.jira_commands import TelegramOAuthNotifier  # bots/jira_specialist.py
from parrot.integrations.telegram.combined_callback import ...                # handlers/agent.py
from parrot.integrations import TelegramAgentConfig                           # __init__.py lazy

# Internal to telegram/:
from ..models import IntegrationBotConfig   # relative to integrations
from ..parser import ResponseParser         # relative to integrations
```

### Does NOT Exist

- ~~`parrot.integrations.telegram.TelegramBot`~~ — the class is `TelegramWrapper`
- ~~`parrot.integrations.telegram.webhook_handler`~~ — verify actual module names

---

## Implementation Notes

### Key Constraints

- Largest channel (29 files) — most complex move.
- `telegram/` has internal sub-imports that may reference `..models`,
  `..parser`, `..core.state` — these now resolve within the satellite.
- `manager.py` (moved in TASK-1345) imports `from ..human import TelegramHumanChannel`
  — verify this still works (human/channels/ moved in TASK-1352).
- Telegram has voice-related modules that import from `parrot.voice` —
  voice moves in TASK-1351.

### Order sensitivity

Telegram imports from voice and human/channels. If those haven't moved
yet, the imports resolve from core. If they have moved, they resolve
from satellite. Either way PEP 420 handles it — just verify.

---

## Acceptance Criteria

- [ ] All 29 telegram Python files present in satellite
- [ ] `from parrot.integrations.telegram.wrapper import TelegramWrapper` works
- [ ] `from parrot.integrations.telegram.jira_commands import TelegramOAuthNotifier` works
- [ ] `from parrot.integrations import TelegramAgentConfig` works
- [ ] Old `parrot/integrations/telegram/` removed from core
- [ ] Moved tests pass
- [ ] No linting errors

---

## Completion Note

*(Agent fills this in when done)*

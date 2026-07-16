---
type: Wiki Overview
title: 'TASK-001: Vendor Bot Framework plumbing & resolve packaging clash'
id: doc:sdd-tasks-completed-task-001-vendor-bf-plumbing-and-packaging-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Foundation task (spec §3 Module 2 + §7 packaging constraints). Before any
---

# TASK-001: Vendor Bot Framework plumbing & resolve packaging clash

**Feature**: FEAT-205 — TeamsHumanChannel
**Spec**: `sdd/specs/hitl-teams-channel.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Foundation task (spec §3 Module 2 + §7 packaging constraints). Before any
Teams HITL code can import cleanly, two things must be true: (1) the Bot
Framework plumbing (adapter / Adaptive-Card helpers / `/api/messages` service)
the channel relies on must be present — vendored from the **private
`azure_teambots` fork**; and (2) the `botbuilder`↔`aiogram` `emoji` version
clash (both live in `ai-parrot-integrations`) must be resolved without breaking
either channel.

**OQ-VENDOR is part of this task**: the public `azure-teambots>=0.1.1` exports
ONLY `AzureBots`. Confirm what the *private fork* actually provides BEFORE
vendoring. Working assumption: the fork provides the adapter + card helpers at
most; `GraphClient` (TASK-002) and proactive 1:1 (TASK-004) are net-new.

---

## Scope

- **Confirm OQ-VENDOR**: inspect the private `azure_teambots` fork and record
  exactly which classes it ships (adapter? card builder? service? Graph?
  proactive?). Document findings in the Completion Note.
- **Vendor** the adapter / Adaptive-Card-builder / service helpers the channel
  needs into `ai-parrot-integrations` (copy, not depend — decision D1). Where
  the fork lacks a piece, reuse the existing `Adapter(CloudAdapter)` settings
  pattern (`msteams/adapter.py:18`).
- **Resolve the `emoji` clash (D3)**: add `[tool.uv] override-dependencies`
  pinning a single `emoji` version compatible with both `botbuilder` and
  `aiogram>=3.12` in `packages/ai-parrot-integrations/pyproject.toml`.
- **Strict lazy imports**: ensure importing the Teams path never imports
  `aiogram` and importing the Telegram path never imports `botbuilder`.
- Add an **import-isolation test** proving the two channels' heavy deps don't
  cross-import.

**NOT in scope**: GraphClient (TASK-002), card *content* per InteractionType
(TASK-003), proactive messaging (TASK-004), the channel class itself (TASK-005).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-integrations/src/parrot/integrations/msteams/` (vendored modules) | CREATE | Vendored adapter / card-builder / service helpers from the private fork |
| `packages/ai-parrot-integrations/pyproject.toml` | MODIFY | `[tool.uv] override-dependencies` for `emoji`; confirm `azure-teambots` handling |
| `packages/ai-parrot-integrations/tests/test_import_isolation.py` | CREATE | Assert teams import ≠ aiogram import and vice-versa |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# Existing reuse pattern (verified):
# packages/ai-parrot-integrations/src/parrot/integrations/msteams/adapter.py:18
from botbuilder.core import ConversationState, TurnContext, BotFrameworkAdapterSettings
from botbuilder.integration.aiohttp import CloudAdapter, ConfigurationBotFrameworkAuthentication
# botbuilder is present transitively (v4.17.1) via azure-teambots>=0.1.1
# (packages/ai-parrot-integrations/pyproject.toml:42, msteams extra)
# aiogram>=3.12 — packages/ai-parrot-integrations/pyproject.toml:39
```

### Existing Signatures to Use
```python
# packages/ai-parrot-integrations/src/parrot/integrations/msteams/adapter.py:18
class Adapter(CloudAdapter):
    # ConfigurationBotFrameworkAuthentication + BotFrameworkAdapterSettings(APP_ID, APP_PASSWORD)
    ...
```

### Does NOT Exist
- ~~`azure_teambots.AdapterHandler`~~ — NOT in the installed package (exports only `AzureBots`). Confirm whether the private fork adds it (OQ-VENDOR).
- ~~`azure_teambots.GraphClient` / `get_user_by_upn` / `get_user_manager`~~ — not present; `GraphClient` is net-new (TASK-002).
- ~~`azure_teambots.CardBot` / `create_adaptive_card`~~ — not present.
- ~~explicit `botbuilder` line in any `pyproject.toml`~~ — it is transitive via `azure-teambots`, not declared directly.

---

## Implementation Notes

### Key Constraints
- Copy (vendor), do NOT add new runtime deps beyond what `azure-teambots`
  already pulls. The fork's code is *copied in*, per D1.
- The `emoji` override must be the MINIMAL pin that satisfies both libs — verify
  `uv pip install`/lock resolves cleanly afterward.
- Lazy imports: keep `botbuilder` imports inside functions/`_LAZY_EXPORTS`
  targets, never at the top of a module that the Telegram path imports.

### References in Codebase
- `packages/ai-parrot-integrations/src/parrot/integrations/msteams/adapter.py:18` — adapter pattern.
- `packages/ai-parrot/src/parrot/human/__init__.py:11-12,37` — `extend_path` + `_LAZY_EXPORTS` lazy mechanism.

---

## Acceptance Criteria

- [ ] OQ-VENDOR confirmed and documented in the Completion Note (what the fork ships).
- [ ] Vendored adapter/card/service helpers present and importable.
- [ ] `[tool.uv] override-dependencies` pins a single `emoji` version; lock/resolve succeeds.
- [ ] `import`ing the Teams path does not import `aiogram`; importing the Telegram path does not import `botbuilder` (proven by test).
- [ ] No linting errors: `ruff check packages/ai-parrot-integrations/src/parrot/integrations/msteams/`
- [ ] Tests pass: `pytest packages/ai-parrot-integrations/tests/test_import_isolation.py -v`

---

## Test Specification
```python
# packages/ai-parrot-integrations/tests/test_import_isolation.py
import sys

def test_teams_path_does_not_import_aiogram():
    # importing teams-side modules must not pull aiogram
    ...  # assert "aiogram" not in sys.modules after import

def test_telegram_path_does_not_import_botbuilder():
    ...  # assert "botbuilder" not in sys.modules after import
```

---

## Agent Instructions
Follow the standard SDD flow: read the spec §3 (Module 2) and §7, verify the
contract, confirm OQ-VENDOR against the actual fork before vendoring, implement,
then move this file to `sdd/tasks/completed/` and update the index.

---

## Completion Note

**Completed by**: Claude Sonnet 4.6 (sdd-worker)
**Date**: 2026-05-29
**Notes**:
OQ-VENDOR confirmed: The private azure_teambots fork provides AdapterHandler(CloudAdapter) (mirrors existing adapter.py),
a basic GraphClient (no Pydantic, no mail-filter fallback — used as reference only), and CardBot (not HITL-specific).
The fork's __init__.py exports only AzureBots. Created hitl_adapter.py with HitlCloudAdapter(CloudAdapter) + HitlBotConfig
using the same ConfigurationBotFrameworkAuthentication + BotFrameworkAdapterSettings pattern.
Emoji clash: botbuilder-dialogs==4.17.1 pins emoji==1.7.0; aiogram 3.28.2 has no emoji dependency. Added
[tool.uv.override-dependencies] emoji = ["emoji==1.7.0"] to pyproject.toml. All 4 import isolation tests pass.
Created conftest.py to prepend worktree src to sys.path for test discovery during development.
**Deviations from spec**: none

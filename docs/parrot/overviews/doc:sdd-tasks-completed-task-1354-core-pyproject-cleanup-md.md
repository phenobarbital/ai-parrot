---
type: Wiki Overview
title: 'TASK-1354: Core pyproject.toml Cleanup + Workspace Integration'
id: doc:sdd-tasks-completed-task-1354-core-pyproject-cleanup-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: After all channels, voice, human/channels, and zoom have been moved,
relates_to:
- concept: mod:parrot.integrations
  rel: mentions
- concept: mod:parrot.integrations.telegram
  rel: mentions
- concept: mod:parrot.voice
  rel: mentions
---

# TASK-1354: Core pyproject.toml Cleanup + Workspace Integration

**Feature**: FEAT-202 — ai-parrot-integrations
**Spec**: `sdd/specs/ai-parrot-integrations.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-1346, TASK-1347, TASK-1348, TASK-1349, TASK-1350, TASK-1351, TASK-1352, TASK-1353
**Assigned-to**: unassigned

---

## Context

After all channels, voice, human/channels, and zoom have been moved,
clean up `packages/ai-parrot/pyproject.toml` to remove the deps that
were only needed by integrations. Add meta-extra `[messaging]` that
aliases to `ai-parrot-integrations[messaging]` for backward compat.
Update workspace root pyproject.

Implements **Spec Module 13**.

---

## Scope

- **Remove from BASE deps** (line 82-83):
  - `pywa>=3.8.0` (line 83) — WhatsApp SDK, now in satellite `[whatsapp]`
  - Evaluate `async-notify[default]` (line 82) — reduce to minimal or
    move to satellite `[messaging]` extra
- **Remove/update extras**:
  - `[integrations]` extra (line ~380): remove `azure-teambots>=0.1.1`
    (now in satellite `[msteams]`)
  - `[matrix]` extra (line ~433): remove entirely (`mautrix`, `python-olm`
    now in satellite `[matrix]`)
  - Remove any voice-related entries (faster-whisper, openai for voice)
- **Add meta-extra**:
  - `messaging = ["ai-parrot-integrations[messaging]"]`
  - Update `[all]` extra to include `ai-parrot-integrations[all]`
- **Remove package-data entries** for `parrot.integrations.telegram`,
  `parrot.voice` (now in satellite).
- **Remove `parrot.integrations.*` from `[tool.setuptools.packages.find]`
  include** if those subpackages no longer exist in core.
- **Update workspace root `pyproject.toml`**:
  - Add `ai-parrot-integrations` to `[tool.uv.sources]`
  - Add as workspace member if `[tool.uv.workspace]` exists
- **Verify** `pip install ai-parrot` no longer pulls `pywa`, `aiogram`,
  `azure-teambots`, `mautrix`, `python-olm`.
- Clean up any `parrot/integrations/` remnants in core (should only
  have the stub `__init__.py` from TASK-1345).

**NOT in scope**: Documentation (TASK-1355).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/pyproject.toml` | MODIFY | Remove deps, add meta-extras |
| `pyproject.toml` (workspace root) | MODIFY | Add workspace member + uv source |
| `packages/ai-parrot/src/parrot/integrations/` | VERIFY | Only stub __init__.py remains |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# packages/ai-parrot/pyproject.toml key lines:
# Line 82: "async-notify[default]>=1.4.2",  ← evaluate reduction
# Line 83: "pywa>=3.8.0",                   ← REMOVE
# Lines 380-384: [integrations] extra       ← remove azure-teambots
# Lines 433-436: [matrix] extra             ← REMOVE entirely
```

### Does NOT Exist

- ~~`packages/ai-parrot/src/parrot/integrations/slack/`~~ — moved in TASK-1346
- ~~`packages/ai-parrot/src/parrot/integrations/telegram/`~~ — moved in TASK-1347
- ~~Other channel dirs in core~~ — all moved by this point

---

## Implementation Notes

### Key Constraints

- `async-notify[default]` brings `aiogram`, `slack-sdk` transitively.
  Options: reduce to `async-notify` (no channel extras) or remove
  entirely. This is an open question — check what `async-notify` is
  used for beyond integrations.
- The `[integrations]` extra may still need `querysource` — only remove
  deps that moved to the satellite.
- The meta-extra `messaging` enables backward-compat:
  `pip install ai-parrot[messaging]` maps to
  `pip install ai-parrot-integrations[messaging]`.
- Verify no core code imports directly from removed deps.

---

## Acceptance Criteria

- [ ] `pywa` removed from BASE deps
- [ ] `[matrix]` extra removed from core pyproject
- [ ] `azure-teambots` removed from `[integrations]` extra
- [ ] Meta-extra `messaging` added
- [ ] `pip install ai-parrot` does NOT install pywa, aiogram, mautrix
- [ ] Workspace root pyproject updated with new member
- [ ] `uv pip install -e packages/ai-parrot` succeeds without channel SDKs
- [ ] Core tests still pass (no imports broken)

---

## Completion Note

*(Agent fills this in when done)*

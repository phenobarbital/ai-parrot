---
type: Wiki Overview
title: 'TASK-1348: WhatsApp Channel Extraction'
id: doc:sdd-tasks-completed-task-1348-whatsapp-extraction-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Move the WhatsApp channel integration (7 Python files, ~116 KB) from
relates_to:
- concept: mod:parrot.integrations
  rel: mentions
- concept: mod:parrot.integrations.whatsapp
  rel: mentions
---

# TASK-1348: WhatsApp Channel Extraction

**Feature**: FEAT-202 — ai-parrot-integrations
**Spec**: `sdd/specs/ai-parrot-integrations.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-1345
**Assigned-to**: unassigned

---

## Context

Move the WhatsApp channel integration (7 Python files, ~116 KB) from
`parrot/integrations/whatsapp/` to the satellite package. WhatsApp has
been dormant since monorepo migration. Its SDK `pywa` is currently in
BASE deps (line 83 of pyproject) — removing it is handled in TASK-1354.

Implements **Spec Module 5**.

---

## Scope

- Move `packages/ai-parrot/src/parrot/integrations/whatsapp/` →
  `packages/ai-parrot-integrations/src/parrot/integrations/whatsapp/`
  (7 files, byte-identical).
- Move related tests if any exist.
- Remove old directory from core.

**NOT in scope**: Removing `pywa` from BASE deps (TASK-1354).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-integrations/src/parrot/integrations/whatsapp/` | CREATE (move) | 7 Python files |
| `packages/ai-parrot/src/parrot/integrations/whatsapp/` | DELETE | Removed from core |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from parrot.integrations import WhatsAppAgentConfig  # __init__.py lazy (line 21)
```

### Does NOT Exist

- ~~`parrot.integrations.whatsapp.WhatsAppBot`~~ — verify actual class names

---

## Acceptance Criteria

- [ ] All 7 whatsapp Python files present in satellite
- [ ] `from parrot.integrations import WhatsAppAgentConfig` works
- [ ] Old `parrot/integrations/whatsapp/` removed from core
- [ ] No linting errors

---

## Completion Note

*(Agent fills this in when done)*

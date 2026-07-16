---
type: Wiki Overview
title: 'TASK-1353: Zoom Relocation to ai-parrot-tools'
id: doc:sdd-tasks-completed-task-1353-zoom-relocation-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: bot — it's an API integration for Zoom with its only production consumer
relates_to:
- concept: mod:parrot.integrations
  rel: mentions
- concept: mod:parrot_tools.zoom
  rel: mentions
- concept: mod:parrot_tools.zoom.client
  rel: mentions
---

# TASK-1353: Zoom Relocation to ai-parrot-tools

**Feature**: FEAT-202 — ai-parrot-integrations
**Spec**: `sdd/specs/ai-parrot-integrations.spec.md`
**Status**: pending
**Priority**: low
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

`parrot/integrations/zoom/` (2 Python files, ~4.5 KB) is not a messaging
bot — it's an API integration for Zoom with its only production consumer
being `parrot_tools/zoomtoolkit.py`. It makes more sense in
`ai-parrot-tools` than in `ai-parrot-integrations`.

Implements **Spec Module 12**.

---

## Scope

- Move `packages/ai-parrot/src/parrot/integrations/zoom/` →
  `packages/ai-parrot-tools/src/parrot_tools/zoom/`
  (2 files: `__init__.py`, `client.py`).
- Update `packages/ai-parrot-tools/src/parrot_tools/zoomtoolkit.py`
  import from `parrot.integrations.zoom.client` →
  `parrot_tools.zoom.client` (or `from .zoom.client`).
- Move test: `packages/ai-parrot/tests/integrations/test_zoom_interface.py`
  to `packages/ai-parrot-tools/tests/`.
- Remove `parrot/integrations/zoom/` from core.
- Update `ai-parrot-tools/pyproject.toml` if needed (add zoom as
  subpackage).

**NOT in scope**: Changing zoom API logic.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/zoom/__init__.py` | CREATE (move) | Zoom package |
| `packages/ai-parrot-tools/src/parrot_tools/zoom/client.py` | CREATE (move) | ZoomUsInterface |
| `packages/ai-parrot-tools/src/parrot_tools/zoomtoolkit.py` | MODIFY | Update import path (line 6) |
| `packages/ai-parrot-tools/tests/test_zoom_interface.py` | CREATE (move) | Zoom test |
| `packages/ai-parrot/src/parrot/integrations/zoom/` | DELETE | Removed from core |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# Current import to update:
from parrot.integrations.zoom.client import ZoomUsInterface  # parrot_tools/zoomtoolkit.py:6

# New import after relocation:
# from parrot_tools.zoom.client import ZoomUsInterface
# or: from .zoom.client import ZoomUsInterface
```

### Does NOT Exist

- ~~`parrot_tools.zoom`~~ — does NOT exist yet; this task creates it
- ~~`parrot.integrations.zoom.ZoomBot`~~ — the class is `ZoomUsInterface`

---

## Acceptance Criteria

- [ ] `from parrot_tools.zoom.client import ZoomUsInterface` works
- [ ] `zoomtoolkit.py` updated to import locally
- [ ] Old `parrot/integrations/zoom/` removed from core
- [ ] Zoom test passes in ai-parrot-tools
- [ ] No linting errors

---

## Completion Note

*(Agent fills this in when done)*

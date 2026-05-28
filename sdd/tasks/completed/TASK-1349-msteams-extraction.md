# TASK-1349: MS Teams Channel Extraction

**Feature**: FEAT-202 — ai-parrot-integrations
**Spec**: `sdd/specs/ai-parrot-integrations.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-1345
**Assigned-to**: unassigned

---

## Context

Move the MS Teams channel integration (22 Python files, ~444 KB) from
`parrot/integrations/msteams/` to the satellite package. MS Teams
includes dialogs, forms integration, voice handling, and the botbuilder
adapter. The extra `[msteams]` declares `parrot-formdesigner` as a
dependency (resolves FEAT-199 U2).

Implements **Spec Module 4**.

---

## Scope

- Move `packages/ai-parrot/src/parrot/integrations/msteams/` →
  `packages/ai-parrot-integrations/src/parrot/integrations/msteams/`
  (22 files, byte-identical).
- Move related tests:
  - `packages/ai-parrot/tests/integrations/msteams/`
- Remove old directory from core.

**NOT in scope**: Forms abstraction (FEAT-199). Changing msteams logic.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-integrations/src/parrot/integrations/msteams/` | CREATE (move) | 22 Python files |
| `packages/ai-parrot-integrations/tests/integrations/msteams/` | CREATE (move) | MS Teams tests |
| `packages/ai-parrot/src/parrot/integrations/msteams/` | DELETE | Removed from core |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from parrot.integrations import MSTeamsAgentConfig  # __init__.py lazy (line 20)
# msteams/ has voice/ subdir that imports from parrot.voice
```

### Does NOT Exist

- ~~`parrot.integrations.msteams.TeamsBot`~~ — verify actual class names

---

## Implementation Notes

### Key Constraints

- msteams has a `voice/` subdirectory with 4 files that imports from
  `parrot.voice` — verify these resolve after voice moves (TASK-1351).
- msteams has a `tools/` subdirectory and `dialogs/` — move everything.
- The extra `[msteams]` in satellite pyproject includes
  `parrot-formdesigner` and `azure-teambots>=0.1.1`.

---

## Acceptance Criteria

- [ ] All 22 msteams Python files present in satellite
- [ ] `from parrot.integrations import MSTeamsAgentConfig` works
- [ ] Old `parrot/integrations/msteams/` removed from core
- [ ] Moved tests pass
- [ ] No linting errors

---

## Completion Note

*(Agent fills this in when done)*

---

**Completed by**: SDD Worker (Claude Sonnet 4.6)
**Date**: 2026-05-28
**Notes**: Moved all 22 msteams Python files including dialogs/, dialogs/presets/, tools/, and voice/ subdirectories to satellite. Moved 12 test files from tests/integrations/msteams/. No import changes needed.
**Deviations from spec**: none

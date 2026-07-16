---
type: Wiki Overview
title: 'TASK-1390: SpawnSubAgentTool export & registration'
id: doc:sdd-tasks-completed-task-1390-spawn-tool-export-registration-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: With `SpawnSubAgentTool` implemented (TASK-1389), this task wires the public
relates_to:
- concept: mod:parrot.tools
  rel: mentions
- concept: mod:parrot.tools.registry
  rel: mentions
- concept: mod:parrot.tools.spawn
  rel: mentions
---

# TASK-1390: SpawnSubAgentTool export & registration

**Feature**: FEAT-208 — Spawn Ephemeral Sub-Agent Tool
**Spec**: `sdd/specs/FEAT-208-spawn-ephemeral-subagent-tool.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-1389
**Assigned-to**: unassigned

---

## Context

> Implements Module 4 of FEAT-208 (§3).

With `SpawnSubAgentTool` implemented (TASK-1389), this task wires the public
exports so the tool is discoverable and importable from the standard
`parrot.tools` namespace.

---

## Scope

- Export `SpawnSubAgentTool` and `SpawnSubAgentInput` from
  `packages/ai-parrot/src/parrot/tools/__init__.py`.
- Add appropriate `__all__` entries if the module uses explicit `__all__`.
- Verify the import works: `from parrot.tools.spawn import SpawnSubAgentTool`.
- Verify the top-level import works: `from parrot.tools import SpawnSubAgentTool`.
- Write a smoke test confirming the import.

**NOT in scope**: implementation changes to `spawn.py` (done in TASK-1389),
tool registry integration (if `parrot/tools/registry.py` has a lazy loader,
add the entry there — otherwise skip).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/tools/__init__.py` | MODIFY | Add exports for `SpawnSubAgentTool`, `SpawnSubAgentInput` |
| `packages/ai-parrot/tests/tools/test_spawn_import.py` | CREATE | Smoke test for import paths |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# The module created by TASK-1389:
from parrot.tools.spawn import SpawnSubAgentTool, SpawnSubAgentInput

# The __init__.py to modify:
# packages/ai-parrot/src/parrot/tools/__init__.py
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/tools/abstract.py
class AbstractTool(EventEmitterMixin, ABC):              # line 81

# After TASK-1389:
# packages/ai-parrot/src/parrot/tools/spawn.py
class SpawnSubAgentInput(BaseModel): ...
class SpawnSubAgentTool(AbstractTool): ...
```

### Does NOT Exist
- ~~`parrot.tools.registry`~~ — check if this module exists. If not, skip registry integration.
- ~~`parrot.tools.spawn`~~ — does not exist until TASK-1389 creates it.

---

## Implementation Notes

### Pattern to Follow
Check how other tools are exported in `__init__.py`:

```bash
grep -n "import\|from" packages/ai-parrot/src/parrot/tools/__init__.py | head -20
```

Follow the same pattern (lazy import, explicit import, or `__all__` entry).

### Key Constraints
- If `__init__.py` uses lazy loading (`__getattr__`), add a lazy entry rather than
  a top-level import — avoid importing `BotManager` (server package) at module load.
- If it uses direct imports, add a conditional/try import since `BotManager` is in
  the server package (optional dependency).

---

## Acceptance Criteria

- [ ] `from parrot.tools.spawn import SpawnSubAgentTool` works
- [ ] `from parrot.tools import SpawnSubAgentTool` works (if the __init__ pattern supports it)
- [ ] No circular import errors
- [ ] `ruff check packages/ai-parrot/src/parrot/tools/__init__.py` passes
- [ ] Smoke test passes: `pytest packages/ai-parrot/tests/tools/test_spawn_import.py -v`

---

## Test Specification

```python
# packages/ai-parrot/tests/tools/test_spawn_import.py
import pytest


class TestSpawnToolImport:
    def test_direct_import(self):
        from parrot.tools.spawn import SpawnSubAgentTool, SpawnSubAgentInput
        assert SpawnSubAgentTool is not None
        assert SpawnSubAgentInput is not None

    def test_top_level_import(self):
        from parrot.tools import SpawnSubAgentTool
        assert SpawnSubAgentTool is not None
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/FEAT-208-spawn-ephemeral-subagent-tool.spec.md` §3 (M4)
2. **Check dependencies** — TASK-1389 must be in `sdd/tasks/completed/`
3. **Read** `packages/ai-parrot/src/parrot/tools/__init__.py` to understand the current export pattern
4. **Verify the Codebase Contract** — confirm `spawn.py` exists (TASK-1389)
5. **Update status** in `sdd/tasks/index/spawn-ephemeral-subagent-tool.json` → `"in-progress"`
6. **Implement** the exports
7. **Run**: `pytest packages/ai-parrot/tests/tools/test_spawn_import.py -v`
8. **Verify** all acceptance criteria
9. **Move this file** to `sdd/tasks/completed/` and update index → `"done"`

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: sdd-worker (Claude Sonnet)
**Date**: 2026-06-01
**Notes**: Added `from .spawn import SpawnSubAgentTool, SpawnSubAgentInput` to
`packages/ai-parrot/src/parrot/tools/__init__.py`. Added both to `__all__`. Also
added `# noqa: E402` to the block of existing and new imports that come after the
`_ParrotToolsRedirector` meta_path setup code (pre-existing E402 issues fixed to
make `ruff check` pass). 7 smoke tests, all passing.

**Deviations from spec**: none

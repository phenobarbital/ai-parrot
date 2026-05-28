# TASK-1333: Move transport/ package into autonomous/transport/

**Feature**: FEAT-196 — Fix Parrot Transport
**Spec**: `sdd/specs/fix-parrot-transport.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

The `parrot/transport/` package currently lives as a top-level package but is only
consumed by `parrot/autonomous` and its test suite. This task moves the entire package
tree into `parrot/autonomous/transport/` to reflect correct ownership. This is the
foundation task — all subsequent tasks depend on this move being complete.

Implements: Spec Module 1 (Package Move).

---

## Scope

- Use `git mv` to move `packages/ai-parrot/src/parrot/transport/` →
  `packages/ai-parrot/src/parrot/autonomous/transport/`
- Preserve all files and internal structure (base.py, filesystem/ with all subfiles)
- Verify `autonomous/transport/__init__.py` exports `AbstractTransport`
- Verify all internal relative imports within filesystem/ still resolve correctly

**NOT in scope**:
- Fixing `hook.py` broken imports (TASK-1334)
- Deleting shims or updating pyproject.toml (TASK-1335)
- Updating test imports (TASK-1336)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/autonomous/transport/__init__.py` | CREATE (via git mv) | Package init, exports `AbstractTransport` |
| `packages/ai-parrot/src/parrot/autonomous/transport/base.py` | CREATE (via git mv) | `AbstractTransport` ABC |
| `packages/ai-parrot/src/parrot/autonomous/transport/filesystem/` | CREATE (via git mv) | Entire filesystem transport subdirectory (14 files) |
| `packages/ai-parrot/src/parrot/transport/` | DELETE (via git mv) | Source directory removed after move |

### Complete file manifest (all via `git mv`):

```
transport/__init__.py           → autonomous/transport/__init__.py
transport/base.py               → autonomous/transport/base.py
transport/filesystem/__init__.py → autonomous/transport/filesystem/__init__.py
transport/filesystem/base.py    → autonomous/transport/filesystem/base.py
transport/filesystem/channel.py → autonomous/transport/filesystem/channel.py
transport/filesystem/cli.py     → autonomous/transport/filesystem/cli.py
transport/filesystem/config.py  → autonomous/transport/filesystem/config.py
transport/filesystem/feed.py    → autonomous/transport/filesystem/feed.py
transport/filesystem/hook.py    → autonomous/transport/filesystem/hook.py
transport/filesystem/inbox.py   → autonomous/transport/filesystem/inbox.py
transport/filesystem/__main__.py → autonomous/transport/filesystem/__main__.py
transport/filesystem/registry.py → autonomous/transport/filesystem/registry.py
transport/filesystem/reservation.py → autonomous/transport/filesystem/reservation.py
transport/filesystem/transport.py → autonomous/transport/filesystem/transport.py
```

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# Current transport __init__.py exports (will be preserved):
from .base import AbstractTransport  # packages/ai-parrot/src/parrot/transport/__init__.py:3

# Current filesystem __init__.py exports (will be preserved):
from .config import FilesystemTransportConfig  # packages/ai-parrot/src/parrot/transport/filesystem/__init__.py:3
from .hook import FilesystemHook               # packages/ai-parrot/src/parrot/transport/filesystem/__init__.py:4
from .transport import FilesystemTransport      # packages/ai-parrot/src/parrot/transport/filesystem/__init__.py:5
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/transport/base.py:9
class AbstractTransport(ABC):
    async def start(self) -> None: ...                    # line 23
    async def stop(self) -> None: ...                     # line 28
    async def send(self, to: str, content: str, ...) -> str: ...  # line 33
    async def __aenter__(self) -> "AbstractTransport": ...  # line 132
    async def __aexit__(self, ...) -> None: ...            # line 137
```

### Does NOT Exist
- ~~`parrot.autonomous.transport`~~ — does NOT exist yet; this task creates it
- ~~`parrot/autonomous/__init__.py` has imports~~ — file is empty (1 line, no content). No circular import risk.

---

## Implementation Notes

### Pattern to Follow
```bash
# Use git mv for the entire directory (preserves history)
cd packages/ai-parrot/src/parrot
git mv transport autonomous/transport
```

### Key Constraints
- All internal imports within filesystem/ are relative (`.config`, `.feed`, `.transport`, etc.) —
  these do NOT need updating after the move
- `autonomous/__init__.py` is empty — no risk of circular imports
- `__main__.py` uses relative import `from .cli import main` — no content change needed
- The `hook.py` file has broken imports (`parrot.autonomous.hooks.*`) — do NOT fix them in
  this task; that's TASK-1334

### References in Codebase
- `packages/ai-parrot/src/parrot/transport/__init__.py` — current package init (line 3: exports AbstractTransport)
- `packages/ai-parrot/src/parrot/transport/filesystem/__init__.py` — current filesystem package init
- `packages/ai-parrot/src/parrot/autonomous/__init__.py` — empty file, safe to add transport/ alongside

---

## Acceptance Criteria

- [ ] `packages/ai-parrot/src/parrot/autonomous/transport/` exists with all 14 files
- [ ] `packages/ai-parrot/src/parrot/transport/` no longer exists
- [ ] `git log --follow packages/ai-parrot/src/parrot/autonomous/transport/base.py` shows history
- [ ] `autonomous/transport/__init__.py` exports `AbstractTransport`
- [ ] `autonomous/transport/filesystem/__init__.py` exports `FilesystemTransport`, `FilesystemTransportConfig`, `FilesystemHook`
- [ ] All relative imports within filesystem/ resolve (no immediate import errors aside from hook.py's known broken `parrot.autonomous.hooks.*` imports)

---

## Test Specification

No new tests for this task. Existing tests will fail because their import paths haven't
been updated yet (that's TASK-1336). Verification is structural:

```bash
# Verify the move completed:
ls packages/ai-parrot/src/parrot/autonomous/transport/base.py
ls packages/ai-parrot/src/parrot/autonomous/transport/filesystem/transport.py
ls packages/ai-parrot/src/parrot/autonomous/transport/filesystem/cli.py

# Verify old location is gone:
! ls packages/ai-parrot/src/parrot/transport/ 2>/dev/null

# Verify __init__.py content preserved:
grep "AbstractTransport" packages/ai-parrot/src/parrot/autonomous/transport/__init__.py
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/fix-parrot-transport.spec.md` for full context
2. **Check dependencies** — none for this task
3. **Verify the Codebase Contract** — confirm `packages/ai-parrot/src/parrot/transport/` still exists and `packages/ai-parrot/src/parrot/autonomous/__init__.py` is still empty
4. **Update status** in per-spec index → `"in-progress"`
5. **Implement** using `git mv` to move the entire directory
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-1333-move-transport-package.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any

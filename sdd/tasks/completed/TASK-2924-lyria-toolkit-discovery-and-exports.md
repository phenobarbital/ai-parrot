# TASK-2924: LyriaToolkit Discovery and Package Exports

**Feature**: FEAT-534 — Lyria Toolkit for Natural Language Music Generation
**Spec**: `sdd/specs/lyria-toolkit.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 1h)
**Depends-on**: TASK-2923
**Assigned-to**: unassigned

---

## Context

Spec §2 Architectural Design, §3 Module 4, and §6 Codebase Contract. For agents and runtime discovery to dynamically find and instantiate `LyriaToolkit`, it must be exported from `parrot_tools.google` and registered in `parrot_tools.TOOL_REGISTRY`.

---

## Scope

- Modify `packages/ai-parrot-tools/src/parrot_tools/google/__init__.py`:
  - Import `LyriaToolkit` from `.lyria`.
  - Add `"LyriaToolkit"` to `__all__`.
- Modify `packages/ai-parrot-tools/src/parrot_tools/__init__.py`:
  - Add `"google_lyria": "parrot_tools.google.lyria.LyriaToolkit"` to `TOOL_REGISTRY`.
  - Add `"lyria": "parrot_tools.google.lyria.LyriaToolkit"` to `TOOL_REGISTRY`.

**NOT in scope**:
- Modifications to `ai-parrot` core registry (handled by automatic package discovery via `parrot.tools.discovery`).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/google/__init__.py` | MODIFY | Export `LyriaToolkit` |
| `packages/ai-parrot-tools/src/parrot_tools/__init__.py` | MODIFY | Register `"lyria"` and `"google_lyria"` in `TOOL_REGISTRY` |

---

## Codebase Contract (Anti-Hallucination)

### Verified Signatures & Paths
```python
# packages/ai-parrot-tools/src/parrot_tools/__init__.py:12
TOOL_REGISTRY: dict[str, str] = { ... }

# packages/ai-parrot-tools/src/parrot_tools/google/__init__.py:12
__all__ = (
    "GoogleSearchTool",
    "GoogleSiteSearchTool",
    # ...
)
```

---

## Implementation Notes (Detailed Code Reference)

### In `packages/ai-parrot-tools/src/parrot_tools/google/__init__.py`

```python
from .tools import (
    GoogleSearchTool,
    GoogleSiteSearchTool,
    GoogleLocationTool,
    GoogleRoutesTool,
    GoogleReviewsTool,
    GoogleTrafficTool,
)
from .places import GoogleBusinessTool
from .base import GoogleBaseTool
from .lyria import LyriaToolkit

__all__ = (
    "GoogleSearchTool",
    "GoogleSiteSearchTool",
    "GoogleLocationTool",
    "GoogleRoutesTool",
    "GoogleReviewsTool",
    "GoogleTrafficTool",
    "GoogleBusinessTool",
    "GoogleBaseTool",
    "LyriaToolkit",
)
```

### In `packages/ai-parrot-tools/src/parrot_tools/__init__.py`

Add entries to `TOOL_REGISTRY`:

```python
    "google_lyria": "parrot_tools.google.lyria.LyriaToolkit",
    "lyria": "parrot_tools.google.lyria.LyriaToolkit",
```

---

## Acceptance Criteria

- [ ] `from parrot_tools.google import LyriaToolkit` succeeds.
- [ ] `from parrot_tools import TOOL_REGISTRY; TOOL_REGISTRY["lyria"] == "parrot_tools.google.lyria.LyriaToolkit"` succeeds.
- [ ] `TOOL_REGISTRY["google_lyria"] == "parrot_tools.google.lyria.LyriaToolkit"` succeeds.

---

### Completion Note

Exported `LyriaToolkit` from `parrot_tools.google.__init__` and registered
both `"lyria"` and `"google_lyria"` in `parrot_tools.TOOL_REGISTRY`. Manually
verified: `from parrot_tools.google import LyriaToolkit` succeeds, and both
registry entries resolve to `"parrot_tools.google.lyria.LyriaToolkit"`.

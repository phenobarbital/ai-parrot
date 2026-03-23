# TASK-399: Import Proxy — Tools

**Feature**: monorepo-migration
**Spec**: `sdd/specs/monorepo-migration.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-398
**Assigned-to**: unassigned

---

## Context

Creates the `__getattr__`-based proxy in `parrot/tools/__init__.py` that resolves imports from `parrot_tools` (the separate package) transparently. This enables backward-compatible `from parrot.tools.X import Y` imports after tools are moved to `parrot_tools`. Base classes and core tools stay directly in `parrot/tools/`.

Implements: Spec Module 2 — Import Proxy (Tools).

---

## Scope

- Replace `parrot/tools/__init__.py` with `__getattr__` proxy that:
  1. Tries `parrot_tools.<name>` (installed ai-parrot-tools package)
  2. Tries `plugins.tools.<name>` (user plugins directory)
  3. Falls back to `TOOL_REGISTRY` in `parrot_tools` for class-level resolution
  4. Raises clear `ImportError` with install instructions if not found
- Cache resolved modules via `setattr(sys.modules[__name__], name, result)`
- Keep direct re-exports of base classes: `AbstractTool`, `AbstractToolkit`, `ToolManager`
- Keep direct re-exports of core tools: `PythonREPLTool`, `VectorStoreSearchTool`, `MultiStoreSearchTool`, `OpenAPIToolkit`, `RESTTool`, `MCPToolManagerMixin`, `ToJsonTool`, `AgentTool`
- Proxy must NOT fire for core tools (they're direct imports, not `__getattr__`)

**NOT in scope**: Moving any tool code. Loader proxy (TASK-400). Discovery system (TASK-401).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/tools/__init__.py` | MODIFY | Replace with __getattr__ proxy + core re-exports |

---

## Implementation Notes

### Pattern (from brainstorm §4.1)

```python
import importlib
import sys
from typing import Optional

TOOL_SOURCES = [
    "parrot_tools",
    "plugins.tools",
]

def _resolve_from_sources(name: str) -> Optional[object]:
    for source in TOOL_SOURCES:
        try:
            return importlib.import_module(f"{source}.{name}")
        except ImportError:
            continue
    return None

def _resolve_from_registry(name: str) -> Optional[object]:
    try:
        from parrot_tools import TOOL_REGISTRY
    except ImportError:
        return None
    dotted_path = TOOL_REGISTRY.get(name)
    if not dotted_path:
        return None
    module_path, class_name = dotted_path.rsplit(".", 1)
    mod = importlib.import_module(module_path)
    return getattr(mod, class_name)

def __getattr__(name: str):
    if name.startswith("_"):
        raise AttributeError(name)
    result = _resolve_from_sources(name)
    if result is not None:
        setattr(sys.modules[__name__], name, result)
        return result
    result = _resolve_from_registry(name)
    if result is not None:
        setattr(sys.modules[__name__], name, result)
        return result
    raise ImportError(
        f"Tool '{name}' not found. "
        f"Install with: uv pip install ai-parrot-tools  or  "
        f"uv pip install ai-parrot-tools[{name}]"
    )

# Base classes (always available in core)
from parrot.tools.abstract import AbstractTool
from parrot.tools.toolkit import AbstractToolkit
from parrot.tools.manager import ToolManager

# Core tools (always available without ai-parrot-tools)
# Import paths TBD — use actual current file locations
```

### Key Constraints
- Must preserve ALL current exports from `parrot/tools/__init__.py`
- Core tools must be importable without `ai-parrot-tools`
- `__getattr__` only fires for names NOT already defined in the module
- Thread-safe (importlib.import_module is already thread-safe)

---

## Acceptance Criteria

- [ ] `from parrot.tools import AbstractTool, AbstractToolkit, ToolManager` works without `ai-parrot-tools`
- [ ] `from parrot.tools import PythonREPLTool` works without `ai-parrot-tools`
- [ ] `from parrot.tools import VectorStoreSearchTool` works without `ai-parrot-tools`
- [ ] `from parrot.tools.openapi import OpenAPIToolkit` works without `ai-parrot-tools`
- [ ] When `ai-parrot-tools` IS installed: `from parrot.tools.jira import JiraToolkit` works via proxy
- [ ] When `ai-parrot-tools` is NOT installed: `from parrot.tools.jira import JiraToolkit` raises clear `ImportError`
- [ ] All existing tests pass

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** and brainstorm §4 for proxy design
2. **Read current `parrot/tools/__init__.py`** to understand existing exports
3. **Update status** in `tasks/.index.json` → `"in-progress"`
4. **Implement** the proxy preserving all existing functionality
5. **Verify** all acceptance criteria are met
6. **Move this file** to `tasks/completed/TASK-399-import-proxy-tools.md`
7. **Update index** → `"done"`

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any

# TASK-401: Tool Discovery System

**Feature**: monorepo-migration
**Spec**: `sdd/specs/monorepo-migration.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-399
**Assigned-to**: unassigned

---

## Context

Creates the multi-source discovery system for `ToolManager`. Two strategies: FAST (read `TOOL_REGISTRY` dicts — no imports needed) and FULL (walk_packages for plugins/). Updates `ToolManager` to use discovery. Deprecates old `ToolkitRegistry`.

Implements: Spec Module 4 — Tool Discovery System.

---

## Scope

- Create `packages/ai-parrot/src/parrot/tools/discovery.py` with:
  - `discover_from_registry(sources)` — reads TOOL_REGISTRY dicts from installed packages
  - `discover_from_walk(sources)` — pkgutil.walk_packages for plugins/ directory
  - `discover_all(sources)` — combined: registry + walk
  - `DEFAULT_SOURCES = ["parrot_tools", "plugins.tools"]`
  - `WALK_SOURCES = {"plugins.tools"}` (only walk plugins, not installed packages)
- Update `packages/ai-parrot/src/parrot/tools/manager.py`:
  - Add `_discover()` method using `discover_all()`
  - Add `_resolve_class()` for lazy class resolution from dotted paths
  - `available_tools()` returns discovered tool names
  - `get_tool(name)` resolves and instantiates
  - Keep backward compat with existing `register_tool()` / `register_toolkit()` methods
- Deprecate `parrot/tools/registry.py` (`ToolkitRegistry`) — add deprecation warning, delegate to new discovery

**NOT in scope**: Moving tools. Registry generation script (TASK-407).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/tools/discovery.py` | CREATE | Multi-source discovery module |
| `packages/ai-parrot/src/parrot/tools/manager.py` | MODIFY | Integrate discovery |
| `packages/ai-parrot/src/parrot/tools/registry.py` | MODIFY | Add deprecation, delegate to discovery |

---

## Implementation Notes

### Reference implementation in brainstorm §5

Follow the `discover_from_registry`, `discover_from_walk`, `discover_all` pattern from brainstorm §5.1.

### Key Constraints
- Discovery must be lazy (not triggered at import time)
- `discover_from_registry` must NOT import tool modules — only read the TOOL_REGISTRY dict
- `discover_from_walk` only runs for `plugins.tools` (not installed packages)
- Must handle gracefully: `ai-parrot-tools` not installed, empty registry, missing plugins dir

---

## Acceptance Criteria

- [ ] `discovery.py` exists with 3 public functions
- [ ] `ToolManager(lazy=True)` doesn't trigger discovery until first use
- [ ] `ToolManager().available_tools()` returns tool names from registry
- [ ] `ToolManager().get_tool("name")` resolves class from dotted path
- [ ] Old `ToolkitRegistry` usage emits deprecation warning
- [ ] All existing tests pass

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any

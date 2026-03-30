# TASK-493: Auto-Registration Hooks

**Feature**: intent-router
**Spec**: `sdd/specs/intent-router.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-490
**Parallel**: true
**Assigned-to**: unassigned

---

## Context

> Adds optional `routing_meta` dictionaries to DataSource and AbstractTool, and optional `capability_registry` parameters to DatasetManager.add_source() and ToolManager.register(). This enables automatic capability registration when data sources or tools are added, removing the need for manual registry.register() calls.
> Implements spec Section 3 — Module 5 (Auto-Registration Hooks).
> This task can run in parallel with TASK-491 since it only depends on TASK-490.

---

## Scope

- Add optional `routing_meta: dict = {}` field to `DataSource` base class in `parrot/tools/dataset_manager/sources/base.py`.
- Add optional `routing_meta: dict = {}` field to `AbstractTool` base class in `parrot/tools/base.py`.
- Modify `DatasetManager.add_source()` in `parrot/tools/dataset_manager/tool.py`:
  - Accept optional `capability_registry: Optional[CapabilityRegistry] = None` parameter.
  - If registry is provided, call `registry.register_from_datasource(source)` after adding the source.
- Modify `ToolManager.register()` in `parrot/tools/manager.py`:
  - Accept optional `capability_registry: Optional[CapabilityRegistry] = None` parameter.
  - If registry is provided, call `registry.register_from_tool(tool)` after registering the tool.
- All changes are backward-compatible: existing code that doesn't pass `routing_meta` or `capability_registry` continues to work unchanged.

**NOT in scope**: CapabilityRegistry implementation (TASK-490 — already done), IntentRouterMixin (TASK-491), AbstractBot changes (TASK-492).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/tools/dataset_manager/sources/base.py` | MODIFY | Add `routing_meta: dict = {}` field to DataSource |
| `parrot/tools/base.py` | MODIFY | Add `routing_meta: dict = {}` field to AbstractTool |
| `parrot/tools/dataset_manager/tool.py` | MODIFY | Add optional `capability_registry` param to add_source() |
| `parrot/tools/manager.py` | MODIFY | Add optional `capability_registry` param to register() |
| `tests/tools/test_auto_registration.py` | CREATE | Tests for auto-registration hooks |

---

## Implementation Notes

### Pattern to Follow
```python
# parrot/tools/dataset_manager/sources/base.py
class DataSource:
    # ... existing fields ...
    routing_meta: dict = {}  # Optional routing metadata for CapabilityRegistry
    # routing_meta can contain:
    #   "description": str — override for capability description
    #   "not_for": list[str] — query patterns this should NOT match


# parrot/tools/base.py
class AbstractTool:
    # ... existing fields ...
    routing_meta: dict = {}  # Optional routing metadata for CapabilityRegistry


# parrot/tools/dataset_manager/tool.py
from typing import Optional

class DatasetManager:
    def add_source(self, source, capability_registry=None):
        # ... existing add logic ...
        if capability_registry is not None:
            capability_registry.register_from_datasource(source)


# parrot/tools/manager.py
class ToolManager:
    def register(self, tool, capability_registry=None):
        # ... existing register logic ...
        if capability_registry is not None:
            capability_registry.register_from_tool(tool)
```

### Key Constraints
- **Backward-compatible**: All new parameters must be optional with defaults. Existing call sites must not break.
- **No hard import**: Use `Optional` typing for CapabilityRegistry. Only import if needed, or use TYPE_CHECKING import to avoid circular deps.
- **routing_meta is a plain dict**: Not a Pydantic model, to keep it lightweight. Convention-based keys: `description`, `not_for`, etc.
- **Field placement**: If DataSource/AbstractTool are Pydantic models, use `Field(default_factory=dict)`. If they are regular classes, use `= {}` in __init__ (but be careful of mutable default — use None + dict copy pattern).

### References in Codebase
- `parrot/tools/dataset_manager/sources/base.py` — DataSource class
- `parrot/tools/base.py` — AbstractTool class
- `parrot/tools/dataset_manager/tool.py` — DatasetManager.add_source()
- `parrot/tools/manager.py` — ToolManager.register()
- `parrot/registry/capabilities/registry.py` — CapabilityRegistry.register_from_datasource(), register_from_tool()

---

## Acceptance Criteria

- [ ] `DataSource` has `routing_meta` field defaulting to empty dict
- [ ] `AbstractTool` has `routing_meta` field defaulting to empty dict
- [ ] `DatasetManager.add_source()` accepts optional `capability_registry` parameter
- [ ] `DatasetManager.add_source()` auto-registers when registry is provided
- [ ] `ToolManager.register()` accepts optional `capability_registry` parameter
- [ ] `ToolManager.register()` auto-registers when registry is provided
- [ ] Existing code without `routing_meta` or `capability_registry` works unchanged
- [ ] No linting errors on all modified files

---

## Test Specification

```python
# tests/tools/test_auto_registration.py
import pytest
from unittest.mock import MagicMock, AsyncMock, patch


class TestDataSourceRoutingMeta:
    def test_default_empty_dict(self):
        """DataSource has routing_meta defaulting to empty dict."""
        from parrot.tools.dataset_manager.sources.base import DataSource
        # Create a DataSource instance (may need required fields)
        # Assert routing_meta == {}
        pass

    def test_custom_routing_meta(self):
        """DataSource accepts custom routing_meta."""
        from parrot.tools.dataset_manager.sources.base import DataSource
        # Create with routing_meta={"description": "Sales data", "not_for": ["admin"]}
        # Assert values are set
        pass


class TestAbstractToolRoutingMeta:
    def test_default_empty_dict(self):
        """AbstractTool has routing_meta defaulting to empty dict."""
        from parrot.tools.base import AbstractTool
        # Assert routing_meta == {}
        pass

    def test_custom_routing_meta(self):
        """AbstractTool accepts custom routing_meta."""
        from parrot.tools.base import AbstractTool
        # Create with routing_meta={"not_for": ["internal"]}
        pass


class TestDatasetManagerAutoRegistration:
    def test_add_source_without_registry(self):
        """add_source works without capability_registry (backward compat)."""
        from parrot.tools.dataset_manager.tool import DatasetManager
        # Create DatasetManager, call add_source without registry
        # Assert no error
        pass

    def test_add_source_with_registry(self):
        """add_source auto-registers when registry provided."""
        from parrot.tools.dataset_manager.tool import DatasetManager
        from parrot.registry.capabilities.registry import CapabilityRegistry

        registry = MagicMock(spec=CapabilityRegistry)
        # Create DatasetManager, create source, call add_source with registry
        # Assert registry.register_from_datasource called once
        pass


class TestToolManagerAutoRegistration:
    def test_register_without_registry(self):
        """register works without capability_registry (backward compat)."""
        from parrot.tools.manager import ToolManager
        # Create ToolManager, register a tool without registry
        # Assert no error
        pass

    def test_register_with_registry(self):
        """register auto-registers when registry provided."""
        from parrot.tools.manager import ToolManager
        from parrot.registry.capabilities.registry import CapabilityRegistry

        registry = MagicMock(spec=CapabilityRegistry)
        # Create ToolManager, create tool, register with registry
        # Assert registry.register_from_tool called once
        pass
```

---

## Agent Instructions

1. Read this task file completely before starting.
2. Read the spec at `sdd/specs/intent-router.spec.md` for full context on Module 5.
3. Verify TASK-490 is complete: `from parrot.registry.capabilities.registry import CapabilityRegistry` must work.
4. Read the existing source files to understand current class structures:
   - `parrot/tools/dataset_manager/sources/base.py`
   - `parrot/tools/base.py`
   - `parrot/tools/dataset_manager/tool.py`
   - `parrot/tools/manager.py`
5. Make minimal, backward-compatible changes.
6. Run existing tests for `parrot/tools/` to verify no regressions.
7. Run `ruff check` on all modified files.
8. Run the tests in **Test Specification** with `pytest`.
9. Do NOT implement anything outside the **Scope** section.
10. When done, fill in the **Completion Note** below and commit.

---

## Completion Note

*(Agent fills this in when done)*

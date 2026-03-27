# TASK-458: Backward Compatibility Wrapper + Registry Updates

**Feature**: whatif-toolkit-decomposition
**Spec**: `sdd/specs/whatif-toolkit-decomposition.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-455, TASK-456, TASK-457
**Assigned-to**: unassigned

---

## Context

> Existing agents use `WhatIfTool` (single tool) and `integrate_whatif_tool()`. This task
> ensures those APIs continue working by making `WhatIfTool._execute()` delegate to the
> new `WhatIfToolkit` internally. Also updates the tool registry.
> Reference: Spec sections 3.3 (Backward Compatibility Wrapper) and 4 (Registry Updates).

---

## Scope

- Modify `WhatIfTool._execute()` in `packages/ai-parrot-tools/src/parrot_tools/whatif.py` to delegate to `WhatIfToolkit`:
  - If no objectives/constraints → delegate to `quick_impact`
  - If objectives/constraints present → run full workflow (describe → add_actions → set_constraints → simulate) internally
  - Preserve the same `ToolResult` return format

- Update `integrate_whatif_tool()` to create a `WhatIfToolkit` under the hood and register its tools alongside the legacy `WhatIfTool`

- Update `TOOL_REGISTRY` in `packages/ai-parrot-tools/src/parrot_tools/__init__.py`:
  - Add `"whatif_toolkit": "parrot_tools.whatif_toolkit.WhatIfToolkit"`
  - Add all 5 statistical tools (registry entries only, implementations in separate tasks)
  - Keep existing `"whatif"` entry for backward compat

- Verify existing `tests/tools/test_whatif.py` tests still pass

**NOT in scope**: Removing the old WhatIfTool, modifying existing agents

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/whatif.py` | MODIFY | Delegate _execute to WhatIfToolkit |
| `packages/ai-parrot-tools/src/parrot_tools/__init__.py` | MODIFY | Update TOOL_REGISTRY |
| `tests/tools/test_whatif_backward_compat.py` | CREATE | Verify legacy API still works |

---

## Implementation Notes

### Delegation Pattern
```python
class WhatIfTool(AbstractTool):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._toolkit = None  # Lazy init
        # ... existing init ...

    def _get_toolkit(self):
        if self._toolkit is None:
            from parrot_tools.whatif_toolkit import WhatIfToolkit
            dm = getattr(self._parent_agent, 'dataset_manager', None) if self._parent_agent else None
            pt = getattr(self._parent_agent, 'pandas_tool', None) if self._parent_agent else None
            self._toolkit = WhatIfToolkit(dataset_manager=dm, pandas_tool=pt)
        return self._toolkit

    async def _execute(self, **kwargs) -> ToolResult:
        input_data = WhatIfInput(**kwargs)
        # Simple scenario → quick_impact
        if not input_data.objectives and not input_data.constraints:
            # Map to quick_impact call
            ...
        else:
            # Map to full workflow
            ...
```

### Key Constraints
- Existing tests in `tests/tools/test_whatif.py` MUST continue to pass without modification
- The `ToolResult` format returned must be identical to current output
- Lazy import of `WhatIfToolkit` to avoid circular imports

### References in Codebase
- `packages/ai-parrot-tools/src/parrot_tools/whatif.py` lines 963-1169 — current _execute
- `packages/ai-parrot-tools/src/parrot_tools/__init__.py` — TOOL_REGISTRY

---

## Acceptance Criteria

- [ ] Existing `test_whatif.py` tests pass without modification
- [ ] `WhatIfTool` delegates to `WhatIfToolkit` internally
- [ ] `integrate_whatif_tool()` registers toolkit tools alongside legacy tool
- [ ] `TOOL_REGISTRY` contains `whatif_toolkit` and all 5 statistical tool entries
- [ ] Tests pass: `pytest tests/tools/test_whatif.py tests/tools/test_whatif_backward_compat.py -v`

---

## Test Specification

```python
import pytest
import pandas as pd
from parrot_tools.whatif import WhatIfTool, WhatIfInput


class TestBackwardCompat:
    @pytest.mark.asyncio
    async def test_simple_scenario_still_works(self):
        """Existing simple scenario pattern still returns ToolResult."""
        # This mirrors existing test patterns from test_whatif.py
        tool = WhatIfTool()
        # ... setup with parent agent and dataframes ...
        # Verify same output format

    def test_registry_has_toolkit(self):
        from parrot_tools import TOOL_REGISTRY
        assert "whatif_toolkit" in TOOL_REGISTRY
        assert "whatif" in TOOL_REGISTRY  # preserved

    def test_registry_has_statistical_tools(self):
        from parrot_tools import TOOL_REGISTRY
        assert "sensitivity_analysis" in TOOL_REGISTRY
        assert "montecarlo" in TOOL_REGISTRY
        assert "statistical_tests" in TOOL_REGISTRY
        assert "regression_analysis" in TOOL_REGISTRY
        assert "breakeven" in TOOL_REGISTRY
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/whatif-toolkit-decomposition.spec.md` sections 3.3 and 4
2. **Check dependencies** — verify TASK-455, TASK-456, TASK-457 are in `tasks/completed/`
3. **Update status** in `tasks/.index.json` → `"in-progress"`
4. **Run existing tests first**: `pytest tests/tools/test_whatif.py -v` to capture baseline
5. **Implement** following the scope and notes above
6. **Verify** existing tests still pass
7. **Move this file** to `tasks/completed/TASK-458-backward-compat-registry.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any

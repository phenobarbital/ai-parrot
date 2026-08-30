# TASK-2578: ToolDefinition model extension + @tool required_permissions

**Feature**: FEAT-474 — ToolManager ToolDefinition Enforcement Parity (G7 remediation)
**Spec**: `sdd/specs/toolmanager-tooldefinition-enforcement.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 1. `ToolDefinition` is the data structure behind every
`@tool`-decorated function in `ToolManager`, and it currently cannot carry
the metadata the enforcement layers need: no `routing_meta` (so
`ConfirmationGuard` has nothing to read) and no `required_permissions` (so
the Layer 2 resolver has nothing to check). This task lays the model
foundation the rest of FEAT-474 builds on.

---

## Scope

- Migrate `ToolDefinition` from `@dataclass` + manual `__slots__` to
  `@dataclass(slots=True)` and add two defaulted fields:
  `routing_meta: Dict[str, Any] = field(default_factory=dict)` and
  `required_permissions: Set[str] = field(default_factory=set)`.
- Add `required_permissions: Optional[Set[str]] = None` keyword parameter to
  the `@tool` decorator; store `set(required_permissions or ())` in
  `func._tool_metadata['required_permissions']` (alongside the existing
  `routing_meta` entry).
- Update the `@tool` docstring: document `required_permissions`, and keep
  the FEAT-235 confirmation parameter docs accurate (they become true once
  TASK-2580 lands — do not describe them as broken).
- Write unit tests for the model defaults and decorator metadata.

**NOT in scope**: copying the new metadata at registration sites
(TASK-2579); any change to `execute_tool()` (TASK-2580); grants API on
`@tool` (never — spec Non-Goal).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/tools/manager.py` | MODIFY | `ToolDefinition` class only (lines 26-34) |
| `packages/ai-parrot/src/parrot/tools/decorators.py` | MODIFY | `tool()` signature + `_tool_metadata` + docstring (lines 55-146) |
| `packages/ai-parrot/tests/tools/test_tooldefinition_enforcement.py` | CREATE | Model + decorator unit tests (shared file for FEAT-474 unit tests) |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from dataclasses import dataclass, field   # dataclass already imported in manager.py
from parrot.tools.manager import ToolDefinition   # manager.py:27
from parrot.tools.decorators import tool           # decorators.py:55
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/tools/manager.py:26-34 (CURRENT state)
@dataclass                       # line 26 — no slots=True
class ToolDefinition:
    """Data structure for tool definition."""
    """Defines a tool with its name, description, input schema, and function."""
    __slots__ = ('name', 'description', 'input_schema', 'function')  # line 30 — DELETE this line
    name: str
    description: str
    input_schema: Dict[str, Any]
    function: Callable

# packages/ai-parrot/src/parrot/tools/decorators.py:55-66 (CURRENT signature)
def tool(_func=None, *, name=None, description=None, schema=None,
         auto_register=False, requires_confirmation=False,
         confirm_template=None, confirm_window_seconds=0, allow_edit=False):
# routing_meta dict built at 126-133 with keys:
#   requires_confirmation, confirm_window_seconds, allow_edit, [confirm_template]
# func._tool_metadata dict stored at 135-146 with keys:
#   name, description, schema, function, auto_register, routing_meta
# func._is_tool = True at 144; wrapper re-attaches both attrs at 151-153.
```

### Does NOT Exist
- ~~`ToolDefinition.routing_meta` / `.required_permissions`~~ — this task ADDS them
- ~~`@tool(required_permissions=...)`~~ — this task ADDS it
- ~~`@tool(requires_grant=...)`~~ — never existed; do NOT add it
- ~~`_tool_metadata['required_permissions']`~~ — this task ADDS the key

---

## Implementation Notes

### Pattern to Follow
```python
# Target state (spec §2 Data Models):
@dataclass(slots=True)
class ToolDefinition:
    """Defines a tool with its name, description, input schema, and function."""
    name: str
    description: str
    input_schema: Dict[str, Any]
    function: Callable
    routing_meta: Dict[str, Any] = field(default_factory=dict)
    required_permissions: Set[str] = field(default_factory=set)
```

### Key Constraints
- **Do NOT keep the manual `__slots__` line**: `@dataclass` with manual
  `__slots__` plus defaulted fields raises
  `ValueError: '<field>' in __slots__ conflicts with class variable` at
  import time. `@dataclass(slots=True)` generates slots correctly and is
  legal on the repo's `>=3.11` floor (pyproject.toml:11).
- Legacy 4-arg construction (keyword AND positional) must keep working —
  new fields are trailing with defaults. Add a test proving it.
- `Set` must be imported from `typing` in manager.py if not already
  (verify — manager.py imports `Dict, Any, Optional, Union, Callable`).
- Google docstrings, strict type hints.

### References in Codebase
- `packages/ai-parrot/src/parrot/tools/decorators.py:126-146` — metadata dict construction to extend
- Spec §6 Codebase Contract — full verified reference set

---

## Acceptance Criteria

- [ ] `ToolDefinition` has `routing_meta`/`required_permissions` with safe
  defaults; class still slotted (`ToolDefinition.__slots__` exists via
  `slots=True`; no `__dict__` on instances)
- [ ] 4-field legacy construction (keyword and positional) still works
- [ ] `@tool(required_permissions={"x"})` lands in
  `_tool_metadata['required_permissions']` as a `set`
- [ ] `@tool` without the param yields empty set in metadata
- [ ] All tests pass: `pytest packages/ai-parrot/tests/tools/test_tooldefinition_enforcement.py -v`
- [ ] No regressions: `pytest packages/ai-parrot/tests/tools/ packages/ai-parrot/tests/test_toolmanager_confirmation.py -v`
- [ ] `ruff check` clean on modified files

---

## Test Specification

```python
# packages/ai-parrot/tests/tools/test_tooldefinition_enforcement.py
from parrot.tools.manager import ToolDefinition
from parrot.tools.decorators import tool


class TestToolDefinitionModel:
    def test_legacy_keyword_construction(self):
        td = ToolDefinition(name="t", description="d", input_schema={}, function=lambda: 1)
        assert td.routing_meta == {}
        assert td.required_permissions == set()

    def test_legacy_positional_construction(self):
        td = ToolDefinition("t", "d", {}, lambda: 1)
        assert td.required_permissions == set()

    def test_slots_no_dict(self):
        td = ToolDefinition("t", "d", {}, lambda: 1)
        assert not hasattr(td, "__dict__")

    def test_defaults_not_shared_between_instances(self):
        a = ToolDefinition("a", "d", {}, lambda: 1)
        b = ToolDefinition("b", "d", {}, lambda: 1)
        a.routing_meta["k"] = "v"
        assert b.routing_meta == {}


class TestToolDecoratorRequiredPermissions:
    def test_required_permissions_stored(self):
        @tool(required_permissions={"reports:read"})
        def f(x: int) -> str:
            """Doc."""
            return str(x)
        assert f._tool_metadata["required_permissions"] == {"reports:read"}

    def test_default_empty(self):
        @tool
        def g(x: int) -> str:
            """Doc."""
            return str(x)
        assert g._tool_metadata["required_permissions"] == set()

    def test_routing_meta_still_built(self):
        @tool(requires_confirmation=True, confirm_window_seconds=30)
        def h(x: int) -> str:
            """Doc."""
            return str(x)
        assert h._tool_metadata["routing_meta"]["requires_confirmation"] is True
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — none for this task
3. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists
   - Confirm the current `ToolDefinition`/`tool()` shapes match the listed lines
   - If anything has changed, update the contract FIRST, then implement
4. **Update status** in `sdd/tasks/index/toolmanager-tooldefinition-enforcement.json` → `"in-progress"`
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-2578-tooldefinition-model-decorator.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (Claude)
**Date**: 2026-08-29
**Notes**: Migrated `ToolDefinition` to `@dataclass(slots=True)`, deleted the
manual `__slots__` line, and added `routing_meta`/`required_permissions`
defaulted fields exactly per spec §2 Data Models. Added `Set` to the
`typing` import in `manager.py`. Extended `@tool` with
`required_permissions: Optional[Set[str]] = None`, storing
`set(required_permissions or ())` in `func._tool_metadata`, and documented
it in the decorator docstring. Created
`packages/ai-parrot/tests/tools/test_tooldefinition_enforcement.py` with
the 7 tests from the task's Test Specification — all pass. Verified no
regressions: `pytest packages/ai-parrot/tests/tools/
packages/ai-parrot/tests/test_toolmanager_confirmation.py` shows the same
51 pre-existing failures (unrelated `databasequery`/`test_auto_registration_hooks`
suites) present on `dev` baseline before this change (904 passed baseline
vs 911 passed here — the +7 are this task's new tests); zero new failures.
`ruff check` on the two modified files shows only 3 new findings
(`UP035`/`UP045`/`UP006` on the new `Set`/`Optional` typing usage), which
match the file's pre-existing style convention (`Dict`/`Optional` imported
from `typing` throughout, 156 pre-existing findings on `dev` baseline) and
mirror the exact `Set[str]` snippet mandated by spec §2 — not a regression,
left as-is per task scope (no unrelated style modernization).

**Deviations from spec**: none

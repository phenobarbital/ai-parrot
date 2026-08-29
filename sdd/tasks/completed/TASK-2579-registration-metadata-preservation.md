# TASK-2579: Registration metadata preservation + inert-grant warning

**Feature**: FEAT-474 — ToolManager ToolDefinition Enforcement Parity (G7 remediation)
**Spec**: `sdd/specs/toolmanager-tooldefinition-enforcement.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-2578
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 2 / Goals G2, G5. Registration currently DROPS the `@tool`
decorator's `routing_meta` when converting a decorated function to
`ToolDefinition` — this is why `@tool(requires_confirmation=True)` (FEAT-235)
is silently inert. There are **two** conversion sites: `ToolManager`'s
registration internals and a second one in `parrot/interfaces/tools.py`.
This task makes every construction site carry the new metadata, and makes
the grant residual loud.

---

## Scope

- In `ToolManager.register_tool()`'s `@tool`-function path
  (manager.py:783-788): copy `meta.get('routing_meta', {})` and
  `meta.get('required_permissions', set())` onto the `ToolDefinition`.
- In the dict path (manager.py:794-799) and explicit-params path
  (manager.py:802-807): default the new fields (`{}` / `set()`); accept
  optional `routing_meta`/`required_permissions` keys from the dict form if
  present.
- In `parrot/interfaces/tools.py:77-82` (`@tool`-function → `ToolDefinition`
  conversion): copy the same two metadata entries.
- Add the **inert-grant warning** (G5): at registration
  (`register_tool`/`add_tool` accept-paths for `ToolDefinition`), if
  `routing_meta.get("requires_grant")` is truthy, log
  `self.logger.warning(...)` naming the tool and stating that grant
  policies (FEAT-211) are NOT enforced on the ToolDefinition path —
  anything needing grants must be an `AbstractTool`.
- Unit tests for both conversion sites and the warning.

**NOT in scope**: any change to `execute_tool()` (TASK-2580); the
`ToolDefinition` class itself (TASK-2578, prerequisite).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/tools/manager.py` | MODIFY | `register_tool()`/`add_tool()` internals (lines ~690-818) |
| `packages/ai-parrot/src/parrot/interfaces/tools.py` | MODIFY | 5th construction site (lines 73-84) |
| `packages/ai-parrot/tests/tools/test_tooldefinition_enforcement.py` | MODIFY | Add registration tests (file created by TASK-2578) |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.tools.manager import ToolDefinition, ToolManager   # manager.py:27, ~240
from parrot.tools.decorators import tool                        # decorators.py:55
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/tools/manager.py:690-699
def add_tool(self, tool: Union[ToolDefinition, AbstractTool], name: Optional[str] = None) -> None:
    # accepts ToolDefinition/AbstractTool instances directly

# packages/ai-parrot/src/parrot/tools/manager.py — register_tool() internals:
# name resolution at 739-744 (reads tool._tool_metadata for decorated fns);
# collision handling 745-765;
# ToolDefinition/AbstractTool accept-path 767-777;
# @tool-function → ToolDefinition conversion at 778-788:
    elif callable(tool) and getattr(tool, '_is_tool', False) and hasattr(tool, '_tool_metadata'):
        meta = tool._tool_metadata
        self._tools[tool_name] = ToolDefinition(
            name=tool_name,
            description=meta.get('description', ''),
            input_schema=meta.get('schema', {}),
            function=meta.get('function', tool),
        )   # ← routing_meta / required_permissions DROPPED here — fix
# dict path 789-799 (uses tool.get('parameters'), tool.get('_tool_instance'));
# explicit-params path 800-807.

# packages/ai-parrot/src/parrot/interfaces/tools.py:73-84 — 2nd conversion site:
    elif callable(tool) and getattr(tool, '_is_tool', False):
        metadata = getattr(tool, '_tool_metadata', None)
        if metadata:
            tool_def = ToolDefinition(
                name=metadata['name'],
                description=metadata['description'],
                input_schema=metadata['schema'],
                function=metadata['function']
            )   # ← same drop — fix identically
            self.tool_manager.register_tool(tool_def)

# After TASK-2578, ToolDefinition is:
@dataclass(slots=True)
class ToolDefinition:
    name: str; description: str; input_schema: Dict[str, Any]; function: Callable
    routing_meta: Dict[str, Any] = field(default_factory=dict)
    required_permissions: Set[str] = field(default_factory=set)

# @tool metadata keys (decorators.py:135-146, extended by TASK-2578):
#   name, description, schema, function, auto_register, routing_meta,
#   required_permissions
```

### Does NOT Exist
- ~~`@tool(requires_grant=...)`~~ — never existed; the warning fires only on a
  hand-built `ToolDefinition`/dict carrying `routing_meta["requires_grant"]`
- ~~grant enforcement on the ToolDefinition path~~ — intentionally NOT added
  (spec Non-Goal); the warning is the whole G5 deliverable
- ~~a third @tool→ToolDefinition conversion site~~ — grep on 2026-08-29 found
  exactly two (manager.py:783, interfaces/tools.py:77); if you find another,
  update this contract first

---

## Implementation Notes

### Pattern to Follow
```python
# Registration copy (manager.py:783-788 target shape):
self._tools[tool_name] = ToolDefinition(
    name=tool_name,
    description=meta.get('description', ''),
    input_schema=meta.get('schema', {}),
    function=meta.get('function', tool),
    routing_meta=dict(meta.get('routing_meta') or {}),
    required_permissions=set(meta.get('required_permissions') or ()),
)
```

### Key Constraints
- Copy (`dict(...)`/`set(...)`) rather than alias the metadata containers —
  two registrations of the same decorated function must not share state.
- The warning must use lazy `%s` logger formatting (manager.py house style)
  and mention FEAT-211 + the AbstractTool alternative so operators know the
  remediation.
- Do not fire the warning for `requires_confirmation` — that IS enforced
  after TASK-2580.
- `interfaces/tools.py` uses `self.logger` too — same conventions.

### References in Codebase
- `packages/ai-parrot/src/parrot/tools/manager.py:762-764` — existing
  registration-warning style to imitate
- Spec §6/§7 — contract and gotchas

---

## Acceptance Criteria

- [ ] `@tool(requires_confirmation=True)` registered via
  `ToolManager.register_tool` yields a stored `ToolDefinition` with
  `routing_meta["requires_confirmation"] is True` (AC-6)
- [ ] Same through the `interfaces/tools.py` path (AC-6)
- [ ] `required_permissions` survives registration on both paths (AC-6)
- [ ] Registering a `ToolDefinition` with truthy
  `routing_meta["requires_grant"]` logs a WARNING (caplog test) (AC-7)
- [ ] dict/param registration paths default new fields without error
- [ ] All tests pass: `pytest packages/ai-parrot/tests/tools/test_tooldefinition_enforcement.py -v`
- [ ] No regressions: `pytest packages/ai-parrot/tests/tools/ -v`
- [ ] `ruff check` clean on modified files

---

## Test Specification

```python
# extend packages/ai-parrot/tests/tools/test_tooldefinition_enforcement.py
import logging
import pytest
from parrot.tools.manager import ToolDefinition, ToolManager
from parrot.tools.decorators import tool


class TestRegistrationMetadata:
    def test_manager_preserves_routing_meta(self):
        tm = ToolManager()
        @tool(requires_confirmation=True, required_permissions={"p"})
        def f(x: int) -> str:
            """Doc."""
            return str(x)
        tm.register_tool(f)
        td = tm.get_tool("f")
        assert td.routing_meta["requires_confirmation"] is True
        assert td.required_permissions == {"p"}

    def test_inert_grant_warning(self, caplog):
        tm = ToolManager()
        td = ToolDefinition("g", "d", {}, lambda: 1,
                            routing_meta={"requires_grant": True})
        with caplog.at_level(logging.WARNING):
            tm.register_tool(td)
        assert any("grant" in r.message.lower() for r in caplog.records)

    def test_no_warning_for_confirmation_only(self, caplog):
        tm = ToolManager()
        td = ToolDefinition("h", "d", {}, lambda: 1,
                            routing_meta={"requires_confirmation": True})
        with caplog.at_level(logging.WARNING):
            tm.register_tool(td)
        assert not any("grant" in r.message.lower() for r in caplog.records)
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — TASK-2578 must be in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** before writing ANY code; update it first
   if the code shifted
4. **Update status** in `sdd/tasks/index/toolmanager-tooldefinition-enforcement.json` → `"in-progress"`
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-2579-registration-metadata-preservation.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (Claude)
**Date**: 2026-08-29
**Notes**: Both `@tool`-function → `ToolDefinition` conversion sites now
copy `routing_meta`/`required_permissions` (deep-copied via `dict(...)`/
`set(...)`, never aliased) — `manager.py:register_tool()`'s `@tool`-function
branch (~783-790) and `interfaces/tools.py`'s `_initialize_tools()` @tool
branch (~77-84). The dict-registration path also now reads optional
`routing_meta`/`required_permissions` keys with safe defaults; the
explicit-params path needed no change since `ToolDefinition`'s own
dataclass defaults already cover it. Added `ToolManager._warn_if_inert_grant()`
helper (`self.logger.warning`, lazy `%s` formatting, names FEAT-211 +
AbstractTool remediation) called from both `ToolDefinition` accept-paths
(`add_tool()` and `register_tool()`) — fires only on
`routing_meta["requires_grant"]` truthy, never on `requires_confirmation`.
Extended `test_tooldefinition_enforcement.py` with 4 new tests (manager
path preserves routing_meta, inert-grant warning fires, no warning for
confirmation-only, and the `interfaces/tools.py` path preserves metadata
identically) — all pass (11/11 total in the file). Regression sweep
`pytest packages/ai-parrot/tests/tools/` shows the same 51 pre-existing
failures as the `dev` baseline (907 passed here vs 900 on `dev` in that
dir — the +7 diff is this feature's own new tests); zero new failures.
`test_toolmanager_confirmation.py` + `test_knowledge_index_flags.py` (the
existing `ToolInterface` harness pattern, reused for the new test) both
pass clean. `ruff check` on the fresh test file is clean (fixed its one
import-order nit); `manager.py`/`interfaces/tools.py` findings are 100%
pre-existing debt untouched by this task's edits (same file-wide style
convention as TASK-2578).

**Deviations from spec**: none

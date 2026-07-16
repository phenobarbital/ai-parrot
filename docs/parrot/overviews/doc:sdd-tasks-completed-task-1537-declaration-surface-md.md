---
type: Wiki Overview
title: 'TASK-1537: Declaration surface (@tool, spawn, toolkit)'
id: doc:sdd-tasks-completed-task-1537-declaration-surface-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Spec §3 Module 4. Exposes the confirmation metadata to tool authors via three
relates_to:
- concept: mod:parrot.tools.decorators
  rel: mentions
---

# TASK-1537: Declaration surface (@tool, spawn, toolkit)

**Feature**: FEAT-235 — HITL Tool-Call Confirmation
**Spec**: `sdd/specs/hitl-confirmation.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1533
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 4. Exposes the confirmation metadata to tool authors via three
surfaces: the `@tool` decorator, the `spawn.py` routing-meta default, and
toolkit-level marking. This task shares NO files with the guard core (TASK-1534/35)
or ToolManager (TASK-1536), so it is **parallelizable** (see index `parallel: true`)
— it only needs the well-known key names defined conceptually in TASK-1533.

---

## Scope

- `parrot/tools/decorators.py`: extend `tool(...)` with kwargs
  `requires_confirmation: bool = False`, `confirm_template: Optional[str] = None`,
  `confirm_window_seconds: int = 0`, `allow_edit: bool = False`. Store them in
  `func._tool_metadata` (decorators.py:104) under a `routing_meta` sub-dict (or
  individual keys), so downstream tool construction projects them into
  `AbstractTool.routing_meta`. Match how `_tool_metadata` is consumed when the
  decorated function becomes an `AbstractTool` — verify the consumption path before
  choosing the storage shape.
- `parrot/tools/spawn.py`: next to `effective_routing.setdefault("requires_grant",
  False)` (spawn.py:147), add `effective_routing.setdefault("requires_confirmation",
  False)`.
- Toolkit-level marking in `parrot/tools/toolkit.py`: allow an `AbstractToolkit` to
  declare a set/list of tool names (or a class attribute) whose generated tools get
  `routing_meta["requires_confirmation"] = True`. Apply during the toolkit's tool
  generation (where it already propagates executor/webhook — toolkit.py ~268-272).
- Tests in `packages/ai-parrot/tests/test_confirmation_declaration.py`.

**NOT in scope**: the guard (TASK-1534/35), ToolManager (TASK-1536), exports/docs
(TASK-1538). Do NOT change `confirmation.py`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/tools/decorators.py` | MODIFY | `@tool` confirmation kwargs → `_tool_metadata` |
| `packages/ai-parrot/src/parrot/tools/spawn.py` | MODIFY | `setdefault("requires_confirmation", False)` |
| `packages/ai-parrot/src/parrot/tools/toolkit.py` | MODIFY | toolkit-level confirming-tool marking |
| `packages/ai-parrot/tests/test_confirmation_declaration.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Existing Signatures to Use
```python
# parrot/tools/decorators.py
def tool(_func=None, *, name=None, description=None, schema=None,
         auto_register=False):                                   # line 55 (ADD new kwargs here)
    func._tool_metadata = {                                      # line 104
        'name': tool_name, 'description': tool_description,
        'schema': tool_schema, 'function': func, 'auto_register': auto_register,
    }
    func._is_tool = True                                         # line 113

# parrot/tools/spawn.py
effective_routing.setdefault("requires_grant", False)           # line 147 (ADD peer line)
# (lines 109, 142-147 document routing_meta + requires_grant placeholder)

# parrot/tools/toolkit.py
class AbstractToolkit(...):                                      # line 191
    tool_prefix; prefix_separator                                # lines 242, 245
    # propagation of executor/webhook to generated tools         # ~lines 268-272

# parrot/tools/abstract.py
class AbstractTool(EventEmitterMixin, ABC):                     # line 81
    routing_meta: Dict                                          # per-instance, line 140
```

### Does NOT Exist
- ~~`@tool(requires_confirmation=...)`~~ today — the decorator accepts ONLY
  name/description/schema/auto_register (decorators.py:55). This task adds the kwargs.
- ~~`spawn.py` confirmation default~~ — only `requires_grant` is defaulted (line 147).
- ~~A toolkit attribute for confirming tools~~ — none exists; design a clear one
  (e.g. `confirming_tools: set[str]` class attr) and document it.

---

## Implementation Notes

### Key Constraints
- Backwards compatible: existing `@tool` / `spawn` / toolkit usage must behave
  identically when the new kwargs/attrs are unset (all default to off).
- Before choosing where `_tool_metadata` confirmation keys land, `read` the code path
  that turns a decorated function into an `AbstractTool` (so the keys actually reach
  `routing_meta`). Verify, don't assume.
- The well-known keys MUST match what `ConfirmationGuard` reads:
  `requires_confirmation`, `confirm_template`, `confirm_window_seconds`, `allow_edit`
  (and optionally `wait_strategy`). Keep them consistent with TASK-1533/1534.

### References in Codebase
- `parrot/tools/spawn.py:142-147` — `requires_grant` placeholder precedent.
- `parrot/tools/decorators.py:55-128` — decorator metadata flow.

---

## Acceptance Criteria

- [ ] `@tool(requires_confirmation=True, confirm_template="…", confirm_window_seconds=30, allow_edit=True)` results in those keys present in the tool's `routing_meta`.
- [ ] A plain `@tool` (no new kwargs) yields `requires_confirmation` falsy/absent — no behavior change.
- [ ] `spawn.py` sets `requires_confirmation=False` by default in routing_meta.
- [ ] A toolkit declaring confirming tool names marks those generated tools' `routing_meta["requires_confirmation"] = True`.
- [ ] All tests pass: `pytest packages/ai-parrot/tests/test_confirmation_declaration.py -v`
- [ ] `ruff check packages/ai-parrot/src/parrot/tools/decorators.py packages/ai-parrot/src/parrot/tools/spawn.py packages/ai-parrot/src/parrot/tools/toolkit.py`

---

## Test Specification
```python
# packages/ai-parrot/tests/test_confirmation_declaration.py
from parrot.tools.decorators import tool

@tool(requires_confirmation=True, confirm_window_seconds=30, allow_edit=True)
def workday_checkin(employee_id: int, time: str) -> str:
    "Register a check-in."
    return "ok"

def test_decorator_carries_confirmation_metadata():
    md = workday_checkin._tool_metadata
    # assert the confirmation keys are present in metadata (exact shape per impl)
    ...
```

---

## Agent Instructions
1. Read spec §2/§6. 2. Trace `_tool_metadata` → `routing_meta` path; verify keys.
3. Index → `in-progress`. 4. Implement (backwards compatible) + verify. 5. Move to completed, index → `done`, note.

---

## Completion Note
**Completed by**: SDD Worker (Claude Sonnet 4.6)
**Date**: 2026-06-12
**Notes**: @tool extended with requires_confirmation/confirm_template/confirm_window_seconds/
allow_edit kwargs projected into routing_meta. spawn.py adds setdefault("requires_confirmation", False).
toolkit.py adds confirming_tools class attr + _create_tool_from_method wiring.
All 15 declaration tests pass. ruff clean.
**Deviations from spec**: none

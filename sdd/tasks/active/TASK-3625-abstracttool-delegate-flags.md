# TASK-3625: AbstractTool delegate flags

**Feature**: FEAT-590 — Tool-Call Delegate
**Spec**: `sdd/specs/tool-call-delegate.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec Module 2. This adds two class attributes. `delegate_safe` is the opt-in
flag the delegate side-effect policy is built on (validator: TASK-3628;
runtime re-check: TASK-3631). `delegate_description` is an optional short
description tuned for tiny local models, and `tool_specs()` (TASK-3627)
prefers it. With the defaults, existing tools behave exactly as before.

---

## Scope

- Add `delegate_safe: bool = False` and `delegate_description: Optional[str] = None` to `AbstractTool`, right after `a2ui_hidden`.
- Write unit tests for the defaults and a per-subclass override.

**NOT in scope**: decorator support (`@tool(delegate_safe=True)`); marking any existing tool safe; the validator and node that read the flags.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/tools/abstract.py` | MODIFY | Two class attributes |
| `packages/ai-parrot/tests/tools/test_abstract_delegate_flags.py` | CREATE | Default/override tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.tools.abstract import AbstractTool  # verified: packages/ai-parrot/src/parrot/tools/abstract.py:281
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/tools/abstract.py
class AbstractTool(EventEmitterMixin, ABC):      # line 281
    name: str = None                             # line 296
    description: str = None                      # line 297
    a2ui_requires_user_activation: bool = False  # line 326
    a2ui_hidden: bool = False                    # line 333  <-- anchor
    @abstractmethod
    async def _execute(self, **kwargs) -> Any    # the only abstract member a test subclass must implement
```
`Optional` is already imported in `abstract.py`; it is used in `credential_provider: Optional[str] = None` at line 305.

### Does NOT Exist
- ~~`AbstractTool.delegate_safe`~~ / ~~`AbstractTool.delegate_description`~~: added by this task.
- ~~A `delegate_safe=` argument to `AbstractTool.__init__`~~: not added. These are class attributes; subclasses override them.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/tools/abstract.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/tools/test_abstract_delegate_flags.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/tools/abstract.py#AbstractTool"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Match the existing comment style (the FEAT-469 attributes directly above are the model).
- No `__init__` change. Class attributes only.

---

## Implementation Blueprint

### Steps (in order)
1. Insert the two attributes after `a2ui_hidden` — *why*: keeps opt-in capability flags grouped (spec M2 anchor).
2. Write the test file — *why*: AC for M2 (defaults are what keep existing tools unaffected).

### `packages/ai-parrot/src/parrot/tools/abstract.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '    a2ui_hidden: bool = False' packages/ai-parrot/src/parrot/tools/abstract.py)
# AFTER — insert below `    a2ui_hidden: bool = False` (verified: packages/ai-parrot/src/parrot/tools/abstract.py:333)
    # FEAT-590 (Tool-Call Delegate, spec §3 Module 2): read-only or
    # idempotent tools opt IN to being chosen by a tool-call delegate inside
    # an ExecutionPlan. Default False — existing tools are unaffected, and a
    # plan listing a non-safe tool in a delegate node is rejected unless the
    # node and the host both allow side effects.
    delegate_safe: bool = False
    # FEAT-590: optional short description tuned for tiny local models;
    # tool_specs() falls back to `description` when None.
    delegate_description: Optional[str] = None
```
**Why**: spec M2's interface skeleton, verbatim.

### `packages/ai-parrot/tests/tools/test_abstract_delegate_flags.py` (CREATE)
```python
"""FEAT-590: AbstractTool delegate flags."""
from __future__ import annotations

from typing import Any

from parrot.tools.abstract import AbstractTool


class _PlainTool(AbstractTool):
    name = "plain"
    description = "A plain tool."

    async def _execute(self, **kwargs: Any) -> Any:
        return None


class _SafeTool(_PlainTool):
    name = "safe"
    delegate_safe = True
    delegate_description = "Fetch a page."


def test_abstract_tool_delegate_defaults() -> None:
    """Unflagged tools are not delegate-safe and carry no delegate description."""
    tool = _PlainTool()
    assert tool.delegate_safe is False
    assert tool.delegate_description is None


def test_subclass_override() -> None:
    """A subclass opts in by overriding the class attributes."""
    # FILL IN: assert _SafeTool() flags; assert _PlainTool still False (no class-level leak)
```

### FILL IN checklist
- [ ] `test_subclass_override` body

---

## Acceptance Criteria

- [ ] Both attributes exist with the stated defaults
- [ ] `ruff check packages/ai-parrot/src/parrot/tools/abstract.py` is clean
- [ ] Tests pass

---

## Validation Commands

- `pytest packages/ai-parrot/tests/tools/test_abstract_delegate_flags.py -q`

---

## Test Specification

See the test file block above.

---

## Agent Instructions

Standard: verify the contract, implement the blueprint, run the validation commands, commit only the listed files.

---

## Completion Note

*(Agent fills this in when done)*

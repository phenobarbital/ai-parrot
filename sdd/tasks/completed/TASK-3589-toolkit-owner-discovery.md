# TASK-3589: Shared toolkit-owner discovery and answer-memory injection fix

**Feature**: FEAT-585 — Plan-then-Execute Hardening
**Spec**: `sdd/specs/plan-then-execute-hardening.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Implements spec §3 **Module 1** and goal **D9** / AC12.

`BasicAgent._inject_answer_memory_into_toolkits()` (`bots/agent.py:234`) iterates
the manager's registered tools and tests `isinstance(tool, WorkingMemoryToolkit)`.
A toolkit never registers as itself: `ToolManager.register_toolkit` registers one
`ToolkitTool` per public async method, and the toolkit instance is only reachable
as `tool.bound_method.__self__` (the idiom the manager already uses at
`tools/manager.py:2589`). The check therefore never matches, injection never
happens, and the reference documentation tells users to wire `answer_memory`
by hand as a "workaround". The sibling loop `_adopt_task_memory_from_toolkits()`
(`bots/agent.py:190`) has the identical defect.

This task introduces **one** owner lookup in `tools/manager.py`, reuses it from the
manager's own scan and from both agent loops, and deduplicates owners so a toolkit
with N wrapped methods is injected exactly once. No feature flag: this is the
behaviour the code always documented (§8 resolved answer).

---

## Scope

- Add module-level `get_toolkit_owner(tool: Any) -> AbstractToolkit | None` to
  `packages/ai-parrot/src/parrot/tools/manager.py`.
- Rewrite `ToolManager._find_working_memory_toolkit` to call it (same result, one idiom).
- Rewrite `BasicAgent._inject_answer_memory_into_toolkits` and
  `BasicAgent._adopt_task_memory_from_toolkits` to resolve owners through
  `get_toolkit_owner`, deduplicate by `id(owner)`, and keep explicit wiring
  (`_answer_memory is not None`) untouched.
- Write `packages/ai-parrot/tests/tools/execution_plan/test_toolkit_owner.py`.

**NOT in scope**:
- Any change to `ExecutionPlanToolkit`, `WorkingMemoryToolkit` or the docs file
  (the docs wrapper-workaround removal is TASK-3604).
- Changing what `register_toolkit` registers or how `ToolkitTool` is built.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/tools/manager.py` | MODIFY | Add `get_toolkit_owner`; use it in `_find_working_memory_toolkit` |
| `packages/ai-parrot/src/parrot/bots/agent.py` | MODIFY | Owner-based discovery in both toolkit loops, deduplicated |
| `packages/ai-parrot/tests/tools/execution_plan/test_toolkit_owner.py` | CREATE | Unit tests: direct instance, wrapped method, unrelated tool, duplicate wrappers, explicit binding |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `dev` @ `3028213ee` on 2026-09-21.

### Verified Imports
```python
from parrot.tools.toolkit import AbstractToolkit, ToolkitTool  # verified: packages/ai-parrot/src/parrot/tools/toolkit.py:206, :35
from parrot.tools.manager import ToolManager                  # verified: packages/ai-parrot/src/parrot/tools/manager.py
from parrot.tools.working_memory import WorkingMemoryToolkit  # verified: packages/ai-parrot/src/parrot/tools/working_memory/__init__.py:3
from parrot.bots.agent import BasicAgent                      # verified: packages/ai-parrot/src/parrot/bots/agent.py
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/tools/toolkit.py:35
class ToolkitTool(AbstractTool):
    self.bound_method = bound_method          # line 58 — bound method of the owning toolkit instance

# packages/ai-parrot/src/parrot/tools/manager.py:2573
def _find_working_memory_toolkit(self) -> Optional[Any]:
    for tool in self._tools.values():
        owner = getattr(getattr(tool, "bound_method", None), "__self__", None)   # line 2589 — THE owner idiom
        if isinstance(owner, WorkingMemoryToolkit):
            return owner
    return None

# packages/ai-parrot/src/parrot/tools/manager.py:763 — AbstractToolkit is imported LOCALLY inside methods:
from .toolkit import AbstractToolkit as _AbstractToolkit

# packages/ai-parrot/src/parrot/bots/agent.py:190
def _adopt_task_memory_from_toolkits(self) -> None:     # loop at 221-231 uses isinstance(tool, WorkingMemoryToolkit)
# packages/ai-parrot/src/parrot/bots/agent.py:234
def _inject_answer_memory_into_toolkits(self) -> None:  # loop at 262-268 uses isinstance(tool, WorkingMemoryToolkit)
#   both resolve `tool_iter` via get_tools() (dict or list) / all_tools() / _tools (lines 244-261)

# packages/ai-parrot/src/parrot/tools/working_memory/tool.py:165
self._answer_memory: Optional[Any] = answer_memory   # None means "not explicitly wired"
# packages/ai-parrot/src/parrot/tools/working_memory/tool.py:144
self._task_memory: Optional[Any] = task_memory
```

### Does NOT Exist
- ~~`ToolManager.get_toolkit_owner`~~ / ~~`ToolkitTool.owner`~~ / ~~`AbstractToolkit.owner_of()`~~ — no owner helper exists anywhere; you create the module-level function.
- ~~`ToolManager.get_toolkits()`~~ — there is no registry of toolkit instances; only `_wired_toolkits: set[int]` (ids, line 340) for auto-wiring.
- ~~a top-level `from .toolkit import AbstractToolkit` in manager.py~~ — it is imported lazily inside methods (circular import); keep your import lazy inside `get_toolkit_owner` too.
- ~~any existing test of `_inject_answer_memory_into_toolkits`~~ — `grep -rln _inject_answer_memory_into_toolkits packages/ai-parrot/tests tests` returns nothing.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/tools/manager.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/bots/agent.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/tools/execution_plan/test_toolkit_owner.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/tools/manager.py#ToolManager._find_working_memory_toolkit",
    "sym:packages/ai-parrot/src/parrot/tools/toolkit.py#ToolkitTool",
    "sym:packages/ai-parrot/src/parrot/tools/toolkit.py#AbstractToolkit"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- `agent.py` and `manager.py` are high-traffic files (spec §7): keep the diff local to the
  three functions named above. Do not reformat surrounding code.
- Explicit wiring wins: a toolkit constructed with `answer_memory=...` must never be overwritten.
- A toolkit registered directly (its instance in the iterable) AND through wrapped methods
  is the same owner: deduplicate by `id(owner)`, never by `name`.
- Keep the lazy `from parrot.tools.working_memory import WorkingMemoryToolkit` in agent.py
  (working_memory is an optional dependency).

### References in Codebase
- `tools/manager.py:915-933` `_auto_wire_toolkit` — the dedupe-by-`id(toolkit)` pattern.
- `tools/manager.py:2732-2770` `cleanup_toolkits` — another owner scan you may unify later (out of scope now).

---

## Implementation Blueprint

### Steps (in order)
1. Add `get_toolkit_owner` to `manager.py` — *why*: one idiom, one place; every scan below imports it.
2. Route `_find_working_memory_toolkit` through it — *why*: proves the helper on an existing caller with existing behaviour.
3. Add a private `_iter_toolkit_owners()` generator to `BasicAgent` and use it in both loops — *why*: both loops share the `tool_iter` resolution and the dedupe; writing it twice is how the bug survived.
4. Write the five tests, then run them — *why*: AC12 is a behavioural claim ("injects once per actual toolkit"); the duplicate-wrapper test is the one that would have caught this originally.

### `packages/ai-parrot/src/parrot/tools/manager.py` (MODIFY — new module-level helper)
```python
# occurrences: 1 (verified: grep -c '^class ToolManager' packages/ai-parrot/src/parrot/tools/manager.py)
# BEFORE — insert ABOVE the line `class ToolManager(` (verified: it is the only class ToolManager definition)
def get_toolkit_owner(tool: Any) -> Optional["AbstractToolkit"]:
    """Return the toolkit that owns ``tool``, or ``None``.

    A toolkit is reachable two ways: it is registered directly (``tool`` IS
    an ``AbstractToolkit``), or one of its methods is registered as a
    ``ToolkitTool`` whose ``bound_method.__self__`` is the owner. Anything
    else (plain ``AbstractTool``, ``ToolDefinition``, ``None``) has no owner.

    Args:
        tool: Any object a ``ToolManager`` iterable may yield.

    Returns:
        The owning ``AbstractToolkit`` instance, or ``None``.
    """
    from .toolkit import AbstractToolkit as _AbstractToolkit  # lazy: circular import

    if isinstance(tool, _AbstractToolkit):
        return tool
    owner = getattr(getattr(tool, "bound_method", None), "__self__", None)
    return owner if isinstance(owner, _AbstractToolkit) else None
```
**Why this shape**: the existing owner idiom (`manager.py:2589`) plus the direct-instance
case, behind one name. The lazy import mirrors `manager.py:763`; a top-level import of
`.toolkit` is circular.

### `packages/ai-parrot/src/parrot/tools/manager.py` (MODIFY — `_find_working_memory_toolkit`)
```python
# occurrences: 1 (verified: grep -c 'owner = getattr(getattr(tool, "bound_method", None), "__self__", None)' packages/ai-parrot/src/parrot/tools/manager.py)
# REPLACE the line above (verified: manager.py:2589) with:
            owner = get_toolkit_owner(tool)
```
**Why**: same result for every existing caller; the function is now exercised by production code.

### `packages/ai-parrot/src/parrot/bots/agent.py` (MODIFY — shared owner iterator)
```python
# occurrences: 1 (verified: grep -c '    def _adopt_task_memory_from_toolkits' packages/ai-parrot/src/parrot/bots/agent.py)
# BEFORE — insert ABOVE `    def _adopt_task_memory_from_toolkits(self) -> None:` (verified: agent.py:190)
    def _iter_toolkit_owners(self) -> "list[Any]":
        """Return each registered toolkit owner once, in registration order.

        Resolves owners through ``parrot.tools.manager.get_toolkit_owner`` so a
        toolkit registered as N wrapped ``ToolkitTool``s appears exactly once.
        """
        tool_manager = getattr(self, "tool_manager", None)
        if tool_manager is None:
            return []
        from parrot.tools.manager import get_toolkit_owner

        if hasattr(tool_manager, "get_tools"):
            tools = tool_manager.get_tools()
            tool_iter = tools.values() if isinstance(tools, dict) else tools
        elif hasattr(tool_manager, "all_tools"):
            tool_iter = tool_manager.all_tools()
        else:
            tool_iter = getattr(tool_manager, "_tools", {}).values()
        owners: "list[Any]" = []
        seen: set[int] = set()
        for tool in tool_iter:
            owner = get_toolkit_owner(tool)
            if owner is None or id(owner) in seen:
                continue
            seen.add(id(owner))
            owners.append(owner)
        return owners
```
**Why**: the two loops at `agent.py:221` and `:262` duplicate the `tool_iter` resolution;
this centralizes it and adds the dedupe. Then, in **both** methods, replace the
`tool_iter` resolution + `for tool in tool_iter:` loop with
`for owner in self._iter_toolkit_owners():` and test
`isinstance(owner, WorkingMemoryToolkit)`; keep the existing `tool_manager is None`
early return and the lazy `WorkingMemoryToolkit` import (needed for the isinstance).
`# FILL IN: rewrite the two loop bodies — bounded by "explicit _answer_memory is never overwritten"
# (inject only when owner._answer_memory is None) and "adopt the first owner with a non-None _task_memory".`

### `packages/ai-parrot/tests/tools/execution_plan/test_toolkit_owner.py` (CREATE)
```python
"""FEAT-585 M1 — toolkit-owner discovery (AC12)."""
from __future__ import annotations

import pytest

from parrot.tools.manager import ToolManager, get_toolkit_owner
from parrot.tools.toolkit import AbstractToolkit
from parrot.tools.working_memory import WorkingMemoryToolkit


class _OtherToolkit(AbstractToolkit):
    """A toolkit that is NOT a WorkingMemoryToolkit, with one public tool."""

    name = "other"

    async def ping(self) -> str:
        """Return pong."""
        return "pong"


def test_direct_instance_is_its_own_owner():
    tk = WorkingMemoryToolkit()
    assert get_toolkit_owner(tk) is tk


def test_wrapped_method_resolves_to_toolkit():
    tk = WorkingMemoryToolkit()
    tools = tk.get_tools_sync() if hasattr(tk, "get_tools_sync") else []
    # FILL IN: pick one ToolkitTool from the generated tools — bounded by ToolkitTool.bound_method.__self__ is tk
    assert tools, "WorkingMemoryToolkit must generate at least one ToolkitTool"
    assert get_toolkit_owner(tools[0]) is tk


def test_unrelated_objects_have_no_owner():
    assert get_toolkit_owner(object()) is None
    assert get_toolkit_owner(None) is None


@pytest.mark.asyncio
async def test_duplicate_wrappers_inject_once():
    """N wrapped methods -> exactly one injection into the same owner."""
    # FILL IN: build a ToolManager, register a WorkingMemoryToolkit + _OtherToolkit,
    # build a minimal BasicAgent-like object (or a real BasicAgent with tool_manager set)
    # and call _inject_answer_memory_into_toolkits(); assert wm._answer_memory is the agent's
    # answer_memory and that _OtherToolkit got nothing — bounded by AC12 "once per actual toolkit".
    raise NotImplementedError


@pytest.mark.asyncio
async def test_explicit_answer_memory_is_preserved():
    # FILL IN: WorkingMemoryToolkit(answer_memory=sentinel) registered; after injection
    # wm._answer_memory is still sentinel — bounded by "explicit wiring wins".
    raise NotImplementedError
```
**Why**: the five cases named in spec §4 `test_toolkit_owner`. Constructing a real
`BasicAgent` may need an LLM stub; if that proves heavy, call the two methods unbound on a
`SimpleNamespace(tool_manager=..., answer_memory=..., logger=..., task_memory=None)` —
they only read those attributes.

### FILL IN checklist
- [ ] `agent.py::_inject_answer_memory_into_toolkits` loop body — inject only when `owner._answer_memory is None`; AC12
- [ ] `agent.py::_adopt_task_memory_from_toolkits` loop body — adopt first owner with non-None `_task_memory`; AC11
- [ ] `test_toolkit_owner.py` — wrapped-tool selection, duplicate-wrapper test, explicit-binding test

---

## Acceptance Criteria

- [ ] AC-1 — `get_toolkit_owner` returns the toolkit for a direct instance and for a `ToolkitTool`, `None` otherwise.
- [ ] AC-2 — With a `WorkingMemoryToolkit` registered through `register_toolkit`, `_inject_answer_memory_into_toolkits` sets `_answer_memory` exactly once (AC12).
- [ ] AC-3 — A toolkit constructed with `answer_memory=X` keeps `X` after injection (AC11).
- [ ] AC-4 — `_find_working_memory_toolkit` behaviour is unchanged (existing tests in `packages/ai-parrot/tests/` that use it still pass).
- [ ] `ruff check` clean on the three files.

## Validation Commands
- `pytest packages/ai-parrot/tests/tools/execution_plan/test_toolkit_owner.py -q`
- `pytest packages/ai-parrot/tests/tools/execution_plan/test_toolkit_core.py -q`

---

## Test Specification

See the CREATE block above — it is the scaffold. Add one test asserting
`ToolManager._find_working_memory_toolkit()` still returns the registered toolkit.

---

## Agent Instructions

1. Read the spec §3 Module 1 and §7 "agent.py and manager.py are high-traffic files".
2. Verify every anchor in the Codebase Contract (`grep -n`), then implement from the Blueprint.
3. Run the Validation Commands; keep the diff local.
4. Move this file to `sdd/tasks/completed/`, update the per-spec index, fill the Completion Note.

---

## Completion Note

**Completed by**: sdd-worker (resumed interrupted session; original implementation by a prior
coder attempt, merged as commits 740673155/6ac1efbcc/b651dac05 before this session began)
**Date**: 2026-09-22
**Notes**:
- Implementation verified by hand against this task's Codebase Contract and Implementation
  Blueprint: `get_toolkit_owner()` added to `tools/manager.py`, `_find_working_memory_toolkit`
  routed through it, `BasicAgent._iter_toolkit_owners()` added and used by both
  `_adopt_task_memory_from_toolkits` / `_inject_answer_memory_into_toolkits` with `id(owner)`
  dedup — matches the blueprint exactly, no deviations.
- **Regression found and fixed in this session**: the engine's automatic `ruff check --fix`
  (commit `6ac1efbcc`) removed a required side-effect import in `manager.py`
  (`from .compression import codecs as _compression_codecs`) because its `# noqa: F401` sat on
  the closing paren of a multi-line import, a line ruff's F401 diagnostic does not bind to.
  This silently broke `CompressorRegistry.load()` (`ValueError: Unknown codec 'columnar' ...
  (known: <none registered>)`) for every caller constructing `ToolManager()` — confirmed via
  `ai-parrot-client-anthropic`'s suite (12 failed -> 13 passed after the fix). Fixed in commit
  `9be7b1b51` by restoring the import as a single line with the noqa on the same line (mirrors
  `tools/compression/codecs/__init__.py`'s own idiom).
- **Validation status**: the required merge-tier `coder_run_validation` (tier=merge) was run
  twice. It genuinely settled with `outcome=timed_out` (900s budget) — never treated as green.
  Before timing out it exercised ~20 of ~24 workspace distributions in full: `ai-parrot-advisors`
  (6 passed), `ai-parrot-client-amazon` (69 passed), `ai-parrot-client-anthropic` (13 passed,
  post-fix), `ai-parrot-client-gemma4`/`-google` (208 passed, 8 pre-existing unrelated
  `test_reel_assembly.py` video-encoding failures)/`-groq`/`-hf`/`-local`/`-meta`/`-moonshot`/
  `-nvidia`/`-openai` (54 passed)/`-openrouter`/`-vllm`/`-zai`, `ai-parrot-embeddings`
  (213 passed, 1 pre-existing unrelated namespace-surface failure), and part of
  `ai-parrot-integrations`. Every observed failure across the whole run (video reel assembly,
  a grok client `NameError: chat_kwargs`, jev entry-points, embeddings namespace drift,
  assorted integrations tests) is pre-existing and unrelated to this task's files
  (`tools/manager.py`, `bots/agent.py`) — confirmed by identical failure sets before and after
  the codec fix, and by none of them touching toolkit-owner discovery or working-memory
  injection. The `ai-parrot` distribution's own pytest run could not execute any test at all
  (25 pre-existing, unrelated collection errors abort the whole session before test execution
  — a known separate environment issue, e.g. `test_expense_approval.py`,
  `test_marketnews_tool.py`), so this task's own new `test_toolkit_owner.py` could not be
  proven to pass by the merge-tier run either; it was reviewed by hand against the Test
  Specification and matches AC-1..AC-4 exactly (five cases: direct instance, wrapped method,
  unrelated object, duplicate-wrapper dedup, explicit-binding preserved).
- Local `pytest` execution is blocked by a pre-existing, documented environment issue
  (`ModuleNotFoundError: No module named 'parrot.utils.types'` — navigator-session version
  mismatch in this machine's `.venv`), unrelated to this feature.

**Deviations from spec**: none. Codec-registration regression fix (commit `9be7b1b51`) is an
engine-lint-autofix correction, not a spec deviation.

# TASK-4596: ToolManager keep-first toolkit re-registration

**Feature**: FEAT-721 — Double-`configure()` Is Not a Crash
**Spec**: `sdd/specs/double-configure-agents.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 1 — the load-bearing fix. Today a second `register_toolkit()` of a
toolkit whose class declares `tool_prefix` (e.g. `WorkingMemoryToolkit`, `"wm"`)
raises `ToolNameCollisionError` (`manager.py:881→891`), and an unprefixed one
(`GitToolkit`, `JiraToolkit`) silently warn-and-skips each tool. Both shapes fire
whenever a bot's `post_configure()` runs twice. Reproduced:

```
first: 13 tools
RAISED ToolNameCollisionError: Tool name collision: 'wm_compute_and_store' is already registered ...
```

This task makes re-registering an already-registered toolkit a **no-op that keeps
the FIRST registration** and returns its live tools. Keep-first (not replace) was
the user's decision: `cleanup_toolkits()` (`manager.py:2867`) discovers toolkits only
through `self._tools`, so a replaced instance's open pool/session would leak.

---

## Scope

- Add `ToolManager.find_registered_toolkit(toolkit_cls, *, tool_prefix=None)` (public).
- Add private helpers `_registered_toolkit_owners()`, `_match_registered_toolkit()`,
  `_registered_tools_of()`, `_keep_first()`.
- In `register_toolkit()`, detect a same-class + same-prefix registration **before**
  `build_toolkit()` runs (name and class paths) and before `get_tools_sync()` runs
  (instance path), and return the registered owner's tools.
- Update the `register_toolkit()` docstring with the keep-first contract.
- Write `packages/ai-parrot/tests/tools/test_toolkit_reregistration.py`.

**NOT in scope**:
- `AbstractBot.configure()` idempotency (TASK-4597).
- Changing any agent's `post_configure()` (TASK-4598, TASK-4599, TASK-4600).
- Changing `register_tool()`'s collision logic — a foreign owner claiming a name
  must keep raising exactly as today.
- Callers that consume the return value (`handlers/studio/toolkits.py:410-484`,
  `interfaces/tools.py:327`): they keep working; see Key Constraints.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/tools/manager.py` | MODIFY | keep-first detection in `register_toolkit` + lookup helpers |
| `packages/ai-parrot/tests/tools/test_toolkit_reregistration.py` | CREATE | unit tests for every keep-first rule |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.tools.manager import ToolManager, ToolNameCollisionError, get_toolkit_owner  # verified: tools/manager.py:289, :43, :53
from parrot.tools.toolkit import AbstractToolkit, ToolkitTool                            # verified: tools/toolkit.py:225, :37
from parrot.tools.working_memory import WorkingMemoryToolkit                             # verified: tools/working_memory/__init__.py:3
from parrot.tools.reminder import ReminderToolkit                                        # verified: tools/reminder.py (tool_prefix at :177)
```
Inside `manager.py` itself: `Set`, `List`, `Optional`, `Any` are already imported
(`manager.py:2`); `AbstractToolkit` is imported locally inside `register_toolkit`
(`manager.py:1220`) to avoid a cycle — keep doing that, and use string annotations
`"AbstractToolkit"` at method level.

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/tools/manager.py
def get_toolkit_owner(tool: Any) -> Optional["AbstractToolkit"]: ...       # line 53 — MODULE-LEVEL function
class ToolManager(MCPToolManagerMixin):                                     # line 289
    def __init__(self, ..., include_search_tool: bool = False, ...): ...    # line 299/303
    self._tools: Dict[str, Union[ToolDefinition, AbstractTool]]             # line 335
    def build_toolkit(self, cls: type, slug: str, params: Dict[str, Any], *,
                      phase: Optional[str] = None) -> Any: ...              # line 628
    def _slug_of_class(self, cls: type) -> str: ...                         # line 651
    def register_tool(self, tool=None, name=None, description=None,
                      input_schema=None, function=None) -> None: ...        # line 853
        #   881: `if tool_name in self._tools:` → prefixed toolkit: raise ToolNameCollisionError (891)
        #                                        legacy: logger.warning + return
    def register_toolkit(self, toolkit: Union[str, "AbstractToolkit", type],
                         **kwargs) -> List[AbstractTool]: ...               # line 1190
        #   1226 str branch:   toolkit_class = ToolkitRegistry.get(toolkit) (1229); 1232 raise ValueError(unknown)
        #                      1233-1237 build_toolkit(toolkit_class, toolkit, kwargs)
        #   1239 class branch: toolkit_name = toolkit.__name__ (1241); 1242-1246 build_toolkit(...)
        #   1248 instance:     toolkit_instance = toolkit; toolkit_name = ...__class__.__name__ (1251)
        #   1260: tools = toolkit_instance.get_tools_sync()   ← has side effects (_generate_tools)
        #   1264: toolkit_instance.set_tool_manager(self)
        #   returns registered_tools (list of tools actually registered)
    def get_tool(self, tool_name: str) -> Optional[Any]: ...                # line 1373
    def _find_working_memory_toolkit(self) -> Optional[Any]: ...            # line 2703 (WM-specific scan — insert helpers ABOVE it)
    async def cleanup_toolkits(self) -> None: ...                           # line 2867

# packages/ai-parrot/src/parrot/tools/toolkit.py
class AbstractToolkit(ServerManagedToolkit, ABC):                           # line 225
    tool_prefix: str | None = None                                          # line 276 — CLASS attribute (readable pre-build)
    #   line 615: tool._from_prefixed_toolkit = bool(self.tool_prefix)
class ToolkitTool(AbstractTool):                                            # line 37
    self.bound_method                                                       # line 55 — owner is bound_method.__self__

# packages/ai-parrot/src/parrot/tools/working_memory/tool.py
class WorkingMemoryToolkit(TaskMemoryToolsMixin, AbstractToolkit):          # line 47
    tool_prefix: str = "wm"                                                 # line 81 (13 tools)
```

### Does NOT Exist
- ~~`ToolManager.unregister_toolkit()`~~ — only `unregister_tool(name)` (`:1415`) / `remove_tool(name)` (`:1428`).
- ~~`ToolManager._toolkits`~~ / ~~`_registered_toolkits`~~ — there is no toolkit registry; owners are found only via `self._tools`.
- ~~`ToolManager.get_toolkit()`~~ / ~~`find_toolkit()`~~ — do not exist (`find_registered_toolkit` is new HERE).
- ~~`ToolManager.find_registered_toolkit()`~~ before this task — you create it.
- ~~`GitToolkit.tool_prefix` / `JiraToolkit.tool_prefix` set to a value~~ — both inherit `None`.
- ~~`AbstractToolkit.is_registered`~~ — no such flag; `set_tool_manager()` is not a registration signal.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/tools/manager.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/tools/test_toolkit_reregistration.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/tools/manager.py#get_toolkit_owner",
    "sym:packages/ai-parrot/src/parrot/tools/manager.py#ToolManager.register_toolkit",
    "sym:packages/ai-parrot/src/parrot/tools/manager.py#ToolManager.register_tool",
    "sym:packages/ai-parrot/src/parrot/tools/manager.py#ToolManager.build_toolkit",
    "sym:packages/ai-parrot/src/parrot/tools/manager.py#ToolManager._find_working_memory_toolkit",
    "sym:packages/ai-parrot/src/parrot/tools/manager.py#ToolNameCollisionError",
    "sym:packages/ai-parrot/src/parrot/tools/toolkit.py#AbstractToolkit",
    "sym:packages/ai-parrot/src/parrot/tools/working_memory/tool.py#WorkingMemoryToolkit"
  ]
}
```

---

## Implementation Notes

### Pattern to Follow
`_find_working_memory_toolkit()` (`manager.py:2703`) is the existing owner scan:
iterate `self._tools.values()`, map through `get_toolkit_owner()`. Generalize it;
do not change it.

### Key Constraints
- **Match rule (strict)**: an owner matches a candidate iff `type(owner) is cls`
  (exact class — never `isinstance`, a subclass is a different toolkit) **and**
  `owner.tool_prefix == prefix` (so `None == None` matches, `"a" != None`).
- **Decide before constructing**: name/class path reads the prefix from
  `kwargs.get("tool_prefix", getattr(cls, "tool_prefix", None))` — because
  `tool_prefix` is a class attribute — and returns before `build_toolkit()` so no
  second pool/client is opened (AC-2).
- **Decide before `get_tools_sync()`** on the instance path — it has side effects.
- **Logging**: a distinct instance skipped → `self.logger.warning(...)` naming the
  class and prefix; the identical object, or a name/class re-request (nothing was
  constructed) → `self.logger.debug(...)`. `%s`-style args, never f-strings.
- **Return value change is intentional**: a duplicate used to return `[]` (or
  raise). It now returns the owner's live tools. Callers that do
  `self.tools.extend(result)` (GitHubReviewer, JiraSpecialist) get de-duplicated in
  TASK-4599/TASK-4600. Studio handlers report `[t.name for t in registered]` — names
  of tools that are genuinely registered, which stays truthful.
- `find_registered_toolkit(cls)` with `tool_prefix=None` means "don't filter on
  prefix" (any instance of that exact class); `_match_registered_toolkit` is the
  strict one `register_toolkit` uses. Do not merge them.

### References in Codebase
- `packages/ai-parrot/src/parrot/memory/episodic/mixin.py:181` — the hand-rolled guard this generalizes.
- `packages/ai-parrot/src/parrot/interfaces/tools.py:228` — `_tooling_applied` precedent.

---

## Implementation Blueprint

### Steps (in order)
1. Insert the lookup helpers above `_find_working_memory_toolkit` — *why*: they sit with the existing owner scan they generalize.
2. Add the keep-first check in each of the three `register_toolkit` branches — *why*: the name/class branches must return before `build_toolkit()` constructs a second instance.
3. Update the `register_toolkit` docstring — *why*: the return-value change is a contract change and must be documented where callers read it.
4. Write the test file and run it — *why*: AC-1…AC-6 are only proven by tests.
5. `ruff check` both files.

### `packages/ai-parrot/src/parrot/tools/manager.py` (MODIFY) — helpers
```python
# occurrences: 1 (verified: grep -c '    def _find_working_memory_toolkit(self) -> Optional[Any]:' manager.py)
# BEFORE — insert above `    def _find_working_memory_toolkit(self) -> Optional[Any]:` (verified: manager.py:2703)
    def _registered_toolkit_owners(self) -> List["AbstractToolkit"]:
        """Return the unique toolkit owners of the registered tools, in registration order."""
        owners: List[Any] = []
        seen: Set[int] = set()
        for tool in self._tools.values():
            owner = get_toolkit_owner(tool)
            if owner is None or id(owner) in seen:
                continue
            seen.add(id(owner))
            owners.append(owner)
        return owners

    def find_registered_toolkit(
        self,
        toolkit_cls: type,
        *,
        tool_prefix: Optional[str] = None,
    ) -> Optional["AbstractToolkit"]:
        """Return the registered instance of ``toolkit_cls``, or ``None``.

        Matches on the EXACT class (never a subclass) and, when ``tool_prefix``
        is given, on an equal ``tool_prefix`` — so one toolkit class registered
        under two different prefixes stays two distinct registrations.

        Args:
            toolkit_cls: The toolkit class to look for.
            tool_prefix: Optional prefix filter; ``None`` means "any prefix".

        Returns:
            The first registered matching instance, or ``None``.
        """
        for owner in self._registered_toolkit_owners():
            if type(owner) is not toolkit_cls:
                continue
            if tool_prefix is not None and owner.tool_prefix != tool_prefix:
                continue
            return owner
        return None

    def _match_registered_toolkit(self, toolkit_cls: type, tool_prefix: Optional[str]) -> Optional["AbstractToolkit"]:
        """Strict keep-first match: exact class AND equal ``tool_prefix`` (``None == None``)."""
        # FILL IN: same loop as find_registered_toolkit but compare `owner.tool_prefix == tool_prefix`
        #          unconditionally — bounded by AC-4 (different prefixes must both register).

    def _registered_tools_of(self, owner: "AbstractToolkit") -> List[AbstractTool]:
        """Return the tools in ``self._tools`` owned by ``owner``, in registration order."""
        return [tool for tool in self._tools.values() if get_toolkit_owner(tool) is owner]

    def _keep_first(self, existing: "AbstractToolkit", candidate: Optional["AbstractToolkit"]) -> List[AbstractTool]:
        """Log a keep-first skip and return ``existing``'s registered tools (nothing is mutated)."""
        # FILL IN: candidate is not None and candidate is not existing → self.logger.warning(
        #          "Toolkit %s (tool_prefix=%r) is already registered; keeping the first instance "
        #          "and ignoring the new one.", type(existing).__name__, existing.tool_prefix)
        #          otherwise → self.logger.debug(...) — bounded by AC-6.
        return self._registered_tools_of(existing)
```
**Why this shape**: the spec fixes `find_registered_toolkit`'s signature (§3 M1) — it is the
public helper TASK-4598/4599/4600 call. The strict matcher is separate because the
public helper's `None` means "no filter", while keep-first needs `None == None`.

### `packages/ai-parrot/src/parrot/tools/manager.py` (MODIFY) — string branch
```python
# occurrences: 1 (verified: grep -cF "raise ValueError(f\"Unknown toolkit: '{toolkit}'. \" f\"Available toolkits: {available}\")" manager.py)
# AFTER — insert below that `raise ValueError(...)` line, BEFORE the `try:` that calls build_toolkit (verified: manager.py:1232)
            existing = self._match_registered_toolkit(
                toolkit_class, kwargs.get("tool_prefix", getattr(toolkit_class, "tool_prefix", None))
            )
            if existing is not None:
                return self._keep_first(existing, candidate=None)
```

### `packages/ai-parrot/src/parrot/tools/manager.py` (MODIFY) — class branch
```python
# occurrences: 1 (verified: grep -cF '            toolkit_name = toolkit.__name__' manager.py)
# AFTER — insert below `            toolkit_name = toolkit.__name__` (verified: manager.py:1241)
            existing = self._match_registered_toolkit(
                toolkit, kwargs.get("tool_prefix", getattr(toolkit, "tool_prefix", None))
            )
            if existing is not None:
                return self._keep_first(existing, candidate=None)
```

### `packages/ai-parrot/src/parrot/tools/manager.py` (MODIFY) — instance branch
```python
# occurrences: 1 (verified: grep -cF '            toolkit_name = toolkit.__class__.__name__' manager.py)
# AFTER — insert below `            toolkit_name = toolkit.__class__.__name__` (verified: manager.py:1251)
            existing = self._match_registered_toolkit(type(toolkit), toolkit.tool_prefix)
            if existing is not None:
                return self._keep_first(existing, candidate=toolkit)
```
**Why**: three insertion points because each branch resolves the class differently; all
three return before `get_tools_sync()` (`:1260`). Add to the `register_toolkit`
docstring (above `Example:`) a paragraph: *"Re-registration is a no-op that keeps the
FIRST registration: when a toolkit of the same exact class and the same ``tool_prefix``
is already registered, its registered tools are returned and nothing is mutated — a
name or class is not even constructed. A name claimed by a DIFFERENT owner still raises
``ToolNameCollisionError``."*

### `packages/ai-parrot/tests/tools/test_toolkit_reregistration.py` (CREATE)
```python
"""FEAT-721 — ToolManager keep-first toolkit re-registration."""

import logging
from unittest.mock import patch

import pytest

from parrot.tools.manager import ToolManager, ToolNameCollisionError
from parrot.tools.toolkit import AbstractToolkit
from parrot.tools.working_memory import WorkingMemoryToolkit


class _AlphaToolkit(AbstractToolkit):
    """Prefixed toolkit used to provoke a foreign-owner collision."""

    tool_prefix = "wm"

    async def get_stored(self, key: str) -> str:
        """Return a stored value (collides with WorkingMemoryToolkit's wm_get_stored)."""
        return key


@pytest.fixture
def manager() -> ToolManager:
    return ToolManager(include_search_tool=False)


def test_reregistering_same_toolkit_keeps_first(manager: ToolManager) -> None:
    first, second = WorkingMemoryToolkit(session_id="s1"), WorkingMemoryToolkit(session_id="s2")
    manager.register_toolkit(first)
    snapshot = dict(manager._tools)
    manager.register_toolkit(second)
    assert manager._tools == snapshot
    assert manager.find_registered_toolkit(WorkingMemoryToolkit) is first


def test_reregistration_returns_registered_tools(manager: ToolManager) -> None:
    # FILL IN: second register_toolkit() returns the same tool OBJECTS as the first call (AC-1)
    ...


def test_reregistration_by_class_does_not_construct(manager: ToolManager) -> None:
    # FILL IN: register WorkingMemoryToolkit instance, then register_toolkit(WorkingMemoryToolkit)
    #          with patch.object(manager, "build_toolkit") → assert_not_called (AC-2)
    ...


def test_second_instance_logs_warning(manager: ToolManager, caplog: pytest.LogCaptureFixture) -> None:
    # FILL IN: distinct instance → WARNING record; identical object re-registered → no WARNING (AC-6)
    ...


def test_same_class_different_prefix_registers_twice(manager: ToolManager) -> None:
    # FILL IN: second WorkingMemoryToolkit with tool_prefix overridden on the instance (e.g. "wm2")
    #          registers its own tools; both prefixes present in manager.list_tools() (AC-4)
    ...


def test_foreign_owner_collision_still_raises(manager: ToolManager) -> None:
    manager.register_toolkit(WorkingMemoryToolkit(session_id="s1"))
    with pytest.raises(ToolNameCollisionError):
        manager.register_toolkit(_AlphaToolkit())


def test_find_registered_toolkit_exact_class_only(manager: ToolManager) -> None:
    # FILL IN: register an instance of a subclass of WorkingMemoryToolkit; assert
    #          find_registered_toolkit(WorkingMemoryToolkit) is None (AC-5)
    ...
```
**Why**: `test_foreign_owner_collision_still_raises` pins the behaviour that must NOT change;
`_AlphaToolkit` reuses prefix `"wm"` so its `get_stored` resolves to `wm_get_stored`, a name
`WorkingMemoryToolkit` already owns. Remove the `...` bodies — they are FILL IN markers.

### FILL IN checklist
- [ ] `manager.py::_match_registered_toolkit` — strict equality loop; bounded by AC-4
- [ ] `manager.py::_keep_first` — WARNING vs DEBUG split; bounded by AC-6
- [ ] `manager.py::register_toolkit` docstring paragraph — wording given above
- [ ] five test bodies marked FILL IN; bounded by AC-1, AC-2, AC-4, AC-5, AC-6
- [ ] verify `_AlphaToolkit` really generates `wm_get_stored` (if `AbstractToolkit` needs extra ctor args, construct accordingly — read `toolkit.py:225` first)

---

## Acceptance Criteria

- [ ] AC-1: re-registering a toolkit of the same exact class + same `tool_prefix` returns the already-registered tools, raises nothing, leaves `_tools` unchanged.
- [ ] AC-2: on the name/class path, `build_toolkit()` is not called for a duplicate.
- [ ] AC-3: a different owner claiming an existing prefixed name still raises `ToolNameCollisionError`.
- [ ] AC-4: two instances of one class with different `tool_prefix` both register.
- [ ] AC-5: `find_registered_toolkit()` matches the exact class only.
- [ ] AC-6: skipping a distinct instance logs WARNING; the identical object logs DEBUG.
- [ ] `ruff check packages/ai-parrot/src/parrot/tools/manager.py packages/ai-parrot/tests/tools/test_toolkit_reregistration.py` clean.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/tools/test_toolkit_reregistration.py -q`
- `pytest packages/ai-parrot/tests/tools/test_toolkit_resolver.py -q`
- `pytest packages/ai-parrot/tests/tools/test_auto_registration_hooks.py -q`

---

## Test Specification

See the CREATE block above — seven tests, one per AC plus the identity check.

---

## Agent Instructions

1. **Work in the feature worktree** — never on `dev`
   (`python -m scripts.sdd.ensure_worktree --slug double-configure-agents --feature-id FEAT-721`).
2. **Read the spec** (`sdd/specs/double-configure-agents.spec.md`, §2, §3 M1, §6).
3. **Check dependencies** — none.
4. **Verify the Codebase Contract** — re-run the `grep -c` for every anchor above; a count of 0 means drift: stop and report.
5. **Update status** in `sdd/tasks/index/double-configure-agents.json` → `"in-progress"` and commit only that file.
6. **Implement** from the blueprint; complete every `# FILL IN:`.
7. **Verify** — run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src`.
8. **Commit the code** — only the two files above.
9. **Close** with `scripts/sdd/close_task.sh TASK-4596 double-configure-agents verified`.
10. **Fill in the Completion Note**, then commit the staged SDD state.

---

## Completion Note

**Completed by**: sdd-worker (attempt 3)

Keep-first re-registration in ToolManager.register_toolkit + find_registered_toolkit helpers. Delivered by codex seat (gpt-5.6-terra/luna); engine task-tier validation failed only because the Cython/.so build artifacts are absent in sub-worktrees (env). Worker merged the a3 branch manually and ran test_toolkit_reregistration.py in the feature worktree with .so copied: all pass.

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none

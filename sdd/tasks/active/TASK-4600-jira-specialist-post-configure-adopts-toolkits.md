# TASK-4600: JiraSpecialist.post_configure adopts its toolkits

**Feature**: FEAT-721 — Double-`configure()` Is Not a Crash
**Spec**: `sdd/specs/double-configure-agents.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-4596
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 3. `JiraSpecialist.post_configure()` (`jira_specialist.py:432`) has the
same shape as the reviewer plus a **prefixed** toolkit: it builds a new `JiraToolkit`
(`:443`) and a new `ReminderToolkit` (`tool_prefix = "reminder"`, `tools/reminder.py:177`,
built at `:487`) on every call and extends `self.tools` twice (`:458`, `:495`). On a second
pass the reminder registration used to raise `ToolNameCollisionError` (caught and logged at
`:490-492`, so the reminder tools were silently lost from `self.tools`). After TASK-4596 a
repeat returns the live tools, so the two `extend` calls would now duplicate entries.

---

## Scope

- Adopt `JiraToolkit` / `ReminderToolkit` via `self.tool_manager.find_registered_toolkit()`;
  call `_configure_jira()` / construct `ReminderToolkit` only when it returns `None`.
- Add a private `_extend_unique_tools(tools)` helper and use it at both `extend` sites.
- Update the `post_configure` docstring.
- Create `packages/ai-parrot/tests/bots/test_jira_specialist_reconfigure.py`.

**NOT in scope**: `clone_for_user()` (builds a fresh instance — already correct);
`_configure_jira()` auth logic; the `scheduler_manager is None` early-return path.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/jira_specialist.py` | MODIFY | adopt-or-build + `_extend_unique_tools` |
| `packages/ai-parrot/tests/bots/test_jira_specialist_reconfigure.py` | CREATE | re-entrancy test |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# already imported in jira_specialist.py — do not re-import
from parrot_tools.jiratoolkit import JiraToolkit       # verified: bots/jira_specialist.py:53
from parrot.tools.reminder import ReminderToolkit      # verified: bots/jira_specialist.py:54
# for the test
from parrot.bots.jira_specialist import JiraSpecialist # verified: bots/jira_specialist.py:172
from parrot.tools.manager import ToolManager           # verified: tools/manager.py:289
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/bots/jira_specialist.py
class JiraSpecialist(Agent):                                           # line 172
    def _configure_jira(self) -> Optional[JiraToolkit]: ...            # line 354 (overridable auth hook)
    async def post_configure(self) -> None:                            # line 432
        # 441 await super().post_configure()
        # 443 self.jira_toolkit = self._configure_jira()
        # 444 if self.jira_toolkit is None: return
        # 447-451 tools = self.tool_manager.register_toolkit(self.jira_toolkit) (try/except → log + return)
        # 453-454 if not tools: return
        # 456-457 if not hasattr(self, "tools") or self.tools is None: self.tools = []
        # 458 self.tools.extend(tools)
        # 460-470 sync_tools(self._llm)
        # 478 scheduler_manager = self.app.get("scheduler_manager") if self.app else None
        # 487 reminder_toolkit = ReminderToolkit(scheduler_manager=scheduler_manager)
        # 488-492 reminder_tools = self.tool_manager.register_toolkit(reminder_toolkit) (try/except)
        # 494-495 if reminder_tools: self.tools.extend(reminder_tools)
    async def clone_for_user(self, user_context: UserContext) -> "JiraSpecialist":  # line 497

# packages/ai-parrot/src/parrot/tools/reminder.py
class ReminderToolkit(AbstractToolkit):                                # line 158
    tool_prefix = "reminder"                                           # line 177
    def __init__(self, scheduler_manager: Any, **kwargs: Any) -> None  # line 179

# packages/ai-parrot/src/parrot/tools/manager.py — created by TASK-4596
def find_registered_toolkit(self, toolkit_cls: type, *, tool_prefix: Optional[str] = None) -> Optional[AbstractToolkit]
```

### Does NOT Exist
- ~~`JiraSpecialist._extend_unique_tools`~~ — created by THIS task.
- ~~`JiraSpecialist.reminder_toolkit` attribute~~ — the reminder toolkit is a local; keep it local.
- ~~`ToolManager.get_toolkit()`~~ — use `find_registered_toolkit()`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/bots/jira_specialist.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/bots/test_jira_specialist_reconfigure.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/bots/jira_specialist.py#JiraSpecialist.post_configure",
    "sym:packages/ai-parrot/src/parrot/bots/jira_specialist.py#JiraSpecialist._configure_jira",
    "sym:packages/ai-parrot/src/parrot/tools/reminder.py#ReminderToolkit"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Explicit `is None` checks, never `a or b`.
- Adopting a registered `JiraToolkit` skips the `_configure_jira()` hook on the repeat — intended:
  the hook's output is already registered and the attribute must name it.
- `_extend_unique_tools` de-duplicates by tool **name** and creates `self.tools` when missing,
  replacing the inline `hasattr` init at `:456-457`.

---

## Implementation Blueprint

### Steps (in order)
1. Replace `:443` with adopt-or-build — *why*: keep-first means the manager's instance wins.
2. Replace `:456-458` and `:495` with `_extend_unique_tools(...)` — *why*: keep-first now returns live tools on a repeat.
3. Replace `:487` with adopt-or-build for `ReminderToolkit`.
4. Add `_extend_unique_tools` above `clone_for_user`; update the docstring; write the test.

### `packages/ai-parrot/src/parrot/bots/jira_specialist.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -cF '        self.jira_toolkit = self._configure_jira()' jira_specialist.py)
# REPLACE line 443 with:
        jira_toolkit = self.tool_manager.find_registered_toolkit(JiraToolkit)
        if jira_toolkit is None:
            jira_toolkit = self._configure_jira()
        self.jira_toolkit = jira_toolkit

# occurrences: 1 (verified: grep -cF '        if not hasattr(self, "tools") or self.tools is None:' jira_specialist.py)
# REPLACE lines 456-458 (the hasattr init + `self.tools.extend(tools)`) with:
        self._extend_unique_tools(tools)

# occurrences: 1 (verified: grep -cF '        reminder_toolkit = ReminderToolkit(scheduler_manager=scheduler_manager)' jira_specialist.py)
# REPLACE line 487 with:
        reminder_toolkit = self.tool_manager.find_registered_toolkit(ReminderToolkit)
        if reminder_toolkit is None:
            reminder_toolkit = ReminderToolkit(scheduler_manager=scheduler_manager)

# occurrences: 1 (verified: grep -cF '            self.tools.extend(reminder_tools)' jira_specialist.py)
# REPLACE line 495 with:
            self._extend_unique_tools(reminder_tools)

# occurrences: 1 (verified: grep -cF '    async def clone_for_user(self, user_context: UserContext) -> "JiraSpecialist":' jira_specialist.py)
# BEFORE — insert above `    async def clone_for_user(...)` (verified: jira_specialist.py:497)
    def _extend_unique_tools(self, tools: list) -> None:
        """Append ``tools`` to ``self.tools``, skipping names already present (FEAT-721)."""
        if not hasattr(self, "tools") or self.tools is None:
            self.tools = []
        present = {getattr(tool, "name", None) for tool in self.tools}
        self.tools.extend(tool for tool in tools if getattr(tool, "name", None) not in present)

```
Append to the `post_configure` docstring: *"Re-entrant (FEAT-721): already-registered Jira and
Reminder toolkits are adopted, and ``self.tools`` never gains duplicate names."*
Apply the edits bottom-up (495 → 487 → 456 → 443) so earlier line numbers stay valid, or re-grep each anchor.

### `packages/ai-parrot/tests/bots/test_jira_specialist_reconfigure.py` (CREATE)
```python
"""FEAT-721 — JiraSpecialist.post_configure() is re-entrant."""

from unittest.mock import MagicMock

import pytest

from parrot.bots.jira_specialist import JiraSpecialist
from parrot.tools.manager import ToolManager


async def test_jira_specialist_post_configure_twice_adopts(monkeypatch: pytest.MonkeyPatch) -> None:
    agent = JiraSpecialist.__new__(JiraSpecialist)
    agent.logger = MagicMock()
    agent.tool_manager = ToolManager(include_search_tool=False)
    agent.tools = []
    agent._llm = None
    agent.app = {"scheduler_manager": MagicMock()}
    # FILL IN: make `_configure_jira` return ONE offline JiraToolkit (exact class, so
    #   find_registered_toolkit can match it) via a MagicMock(side_effect=[toolkit]) so a second
    #   call would fail loudly; read packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py:874 for
    #   the ctor. Stub any other attribute post_configure() reads that __new__ left unset.
    await agent.post_configure()
    await agent.post_configure()
    # FILL IN: assert _configure_jira called once; names starting "reminder_" registered exactly once
    #          in agent.tool_manager.list_tools(); no duplicate names in agent.tools;
    #          agent.jira_toolkit is agent.tool_manager.find_registered_toolkit(type(agent.jira_toolkit))
```
**Why**: `asyncio_mode = "auto"` (`packages/ai-parrot/pyproject.toml:1048`) — no marker needed.
`ReminderToolkit` is constructed for real (it only stores the scheduler manager), so the
`reminder_*` names are the prefixed path that used to raise.

### FILL IN checklist
- [ ] offline `JiraToolkit` construction (record the approach in the Completion Note)
- [ ] the four assertions above

---

## Acceptance Criteria

- [ ] Two `post_configure()` passes raise nothing and log no "Failed to register Reminder tools" error.
- [ ] `_configure_jira()` runs once; `reminder_*` tools are registered once.
- [ ] `self.tools` has no duplicate names; `self.jira_toolkit` is the registered instance.
- [ ] `ruff check packages/ai-parrot/src/parrot/bots/jira_specialist.py packages/ai-parrot/tests/bots/test_jira_specialist_reconfigure.py` clean.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/bots/test_jira_specialist_reconfigure.py -q`
- `pytest packages/ai-parrot/tests/bots/test_jira_standup.py -q`

---

## Test Specification

One new test (above).

---

## Agent Instructions

1. **Work in the feature worktree** — never on `dev`
   (`python -m scripts.sdd.ensure_worktree --slug double-configure-agents --feature-id FEAT-721`).
2. **Read the spec** (§2 Overview, §3 M3, §7 Known Risks).
3. **Check dependencies** — TASK-4596 must be `"done"` in `sdd/tasks/index/double-configure-agents.json`.
4. **Verify the Codebase Contract** — re-run every `grep -cF` above; 0 means drift: stop and report.
5. **Update status** → `"in-progress"`; commit only the index file.
6. **Implement** from the blueprint; complete every `# FILL IN:`.
7. **Verify** — Validation Commands with `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-tools/src`.
8. **Commit the code** — only the files this task lists.
9. **Close** with `scripts/sdd/close_task.sh TASK-4600 double-configure-agents verified`.
10. **Fill in the Completion Note**, commit the SDD state.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none

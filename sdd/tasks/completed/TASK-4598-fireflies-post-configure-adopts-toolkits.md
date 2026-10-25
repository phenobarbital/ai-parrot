# TASK-4598: FirefliesInsightsAgent.post_configure adopts its toolkits

**Feature**: FEAT-721 — Double-`configure()` Is Not a Crash
**Spec**: `sdd/specs/double-configure-agents.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-4596
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 3. `FirefliesInsightsAgent.post_configure()` (`fireflies_insights.py:162`)
builds a **new** `WorkingMemoryToolkit` on every call (`:165`) and registers it untried
(`:167-169`) — the exact path where the collision was found. After TASK-4596 the second
registration no longer raises, but keep-first means the manager keeps the FIRST instance:
if this body keeps assigning a fresh instance to `self.working_memory`, the attribute
points at a toolkit the manager does not serve (split-brain). This task makes the body
adopt the registered instance.

---

## Scope

- In `post_configure()`, adopt `WorkingMemoryToolkit` and `JiraToolkit` via
  `self.tool_manager.find_registered_toolkit(...)`; construct only when it returns `None`.
- Update the method docstring.
- Add a re-entrancy test to `packages/ai-parrot/tests/bots/test_fireflies_insights.py`.

**NOT in scope**: `configure()` of this class (its post-`super()` work is idempotent);
`_build_jira_toolkit()` internals; any other agent.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/fireflies_insights.py` | MODIFY | adopt-or-build in `post_configure()` |
| `packages/ai-parrot/tests/bots/test_fireflies_insights.py` | MODIFY | append re-entrancy test |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# already imported in fireflies_insights.py — do not re-import
from parrot.tools.working_memory import WorkingMemoryToolkit   # verified: bots/fireflies_insights.py:30
from parrot_tools.jiratoolkit import JiraToolkit                # verified: bots/fireflies_insights.py:31
# for the test
from parrot.tools.manager import ToolManager                    # verified: tools/manager.py:289
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/bots/fireflies_insights.py
class FirefliesInsightsAgent(SkillRegistryMixin, Agent):                     # line 101
    self.working_memory: WorkingMemoryToolkit | None = None                  # line 144
    self.jira_toolkit: JiraToolkit | None = None                             # line 145
    async def post_configure(self) -> None:                                  # line 162
        # 163 docstring; 164 await super().post_configure()
        # 165 self.working_memory = WorkingMemoryToolkit(session_id=f"{self.name}-meetings")
        # 166 self.jira_toolkit = self._build_jira_toolkit()
        # 167-169 for toolkit in (self.working_memory, self.jira_toolkit): if toolkit is not None: register_toolkit(toolkit)
    def _build_jira_toolkit(self) -> JiraToolkit | None:                     # line 171

# packages/ai-parrot/src/parrot/tools/manager.py — created by TASK-4596
def find_registered_toolkit(self, toolkit_cls: type, *, tool_prefix: Optional[str] = None) -> Optional[AbstractToolkit]
    # exact-class match; returns None when absent

# packages/ai-parrot/tests/bots/test_fireflies_insights.py
def _bare_agent() -> FirefliesInsightsAgent:                                 # line 26 (no tool_manager set)
```

### Does NOT Exist
- ~~`ToolManager.get_toolkit()`~~ — use `find_registered_toolkit()` (TASK-4596).
- ~~`SkillRegistryMixin.post_configure` / `Agent.post_configure`~~ — neither overrides it; `super().post_configure()` reaches `AbstractBot`'s no-op.
- ~~`_bare_agent().tool_manager`~~ — the helper does not set one; the test must.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/bots/fireflies_insights.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/bots/test_fireflies_insights.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/bots/fireflies_insights.py#FirefliesInsightsAgent.post_configure",
    "sym:packages/ai-parrot/src/parrot/bots/fireflies_insights.py#FirefliesInsightsAgent._build_jira_toolkit",
    "sym:packages/ai-parrot/src/parrot/tools/working_memory/tool.py#WorkingMemoryToolkit"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Use explicit `is None` checks, not `a or b` — a toolkit's truthiness is not a contract.
- Keep the registration loop: on a first call it registers; on a repeat, keep-first
  (TASK-4596) makes it a no-op — so the body needs no "already registered?" branch of its own.
- `find_registered_toolkit(WorkingMemoryToolkit)` with no prefix adopts any WM toolkit the
  agent already serves — intended: an agent has one working memory.

---

## Implementation Blueprint

### Steps (in order)
1. Replace lines 165-166 with adopt-or-build — *why*: keep-first means the manager's instance wins; the attribute must name it.
2. Update the docstring — *why*: the re-entrancy contract must be visible where the next author edits.
3. Append the test, run both Validation Commands.

### `packages/ai-parrot/src/parrot/bots/fireflies_insights.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -cF '        self.working_memory = WorkingMemoryToolkit(session_id=f"{self.name}-meetings")' fireflies_insights.py)
# REPLACE lines 165-166 (the two assignments) with:
        working_memory = self.tool_manager.find_registered_toolkit(WorkingMemoryToolkit)
        if working_memory is None:
            working_memory = WorkingMemoryToolkit(session_id=f"{self.name}-meetings")
        self.working_memory = working_memory
        jira_toolkit = self.tool_manager.find_registered_toolkit(JiraToolkit)
        if jira_toolkit is None:
            jira_toolkit = self._build_jira_toolkit()
        self.jira_toolkit = jira_toolkit
```
Docstring (line 163) becomes:
`"""Wire WorkingMemoryToolkit and JiraToolkit once self.app exists.` + blank line +
`Re-entrant: adopts the registered toolkits instead of constructing new ones, so`
```self.working_memory`` is always the instance the manager serves (FEAT-721).`
`"""`

### `packages/ai-parrot/tests/bots/test_fireflies_insights.py` (MODIFY — append at end of file)
```python
@pytest.mark.asyncio
async def test_fireflies_post_configure_twice_adopts(monkeypatch: pytest.MonkeyPatch) -> None:
    """A second post_configure() raises nothing and keeps the registered working memory (FEAT-721)."""
    from parrot.tools.manager import ToolManager

    agent = _bare_agent()
    agent.tool_manager = ToolManager(include_search_tool=False)
    monkeypatch.setattr(agent, "_build_jira_toolkit", lambda: None)

    await agent.post_configure()
    first = agent.working_memory
    await agent.post_configure()

    assert agent.working_memory is first
    assert agent.tool_manager.find_registered_toolkit(type(first)) is first
    # FILL IN: assert the wm_* tool count did not grow (len of names starting "wm_" is unchanged)
```
**Why**: monkeypatching `_build_jira_toolkit` keeps the test offline; the WM path is the one
that used to raise. If `pytest.mark.asyncio` is not how this file marks async tests, follow
the file's existing convention (check its other `async def test_` functions).

### FILL IN checklist
- [ ] tool-count assertion in the test
- [ ] confirm `_bare_agent()` exposes `self.name` (it does: line 29) and nothing else `post_configure` reads is missing

---

## Acceptance Criteria

- [ ] Calling `post_configure()` twice raises nothing.
- [ ] `agent.working_memory is agent.tool_manager.find_registered_toolkit(WorkingMemoryToolkit)` after both calls.
- [ ] The `wm_*` tools are registered exactly once.
- [ ] `ruff check packages/ai-parrot/src/parrot/bots/fireflies_insights.py packages/ai-parrot/tests/bots/test_fireflies_insights.py` clean.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/bots/test_fireflies_insights.py -q`

---

## Test Specification

One appended test (above); the existing file must stay green.

---

## Agent Instructions

1. **Work in the feature worktree** — never on `dev`
   (`python -m scripts.sdd.ensure_worktree --slug double-configure-agents --feature-id FEAT-721`).
2. **Read the spec** (§2 Overview, §3 M3, §7 Known Risks).
3. **Check dependencies** — TASK-4596 must be `"done"` in `sdd/tasks/index/double-configure-agents.json`.
4. **Verify the Codebase Contract** — re-run every `grep -cF` above; 0 means drift: stop and report.
5. **Update status** → `"in-progress"`; commit only the index file.
6. **Implement** from the blueprint; complete every `# FILL IN:`.
7. **Verify** — Validation Commands with `PYTHONPATH=packages/ai-parrot/src` (+ `packages/ai-parrot-tools/src`).
8. **Commit the code** — only the files this task lists.
9. **Close** with `scripts/sdd/close_task.sh TASK-4598 double-configure-agents verified`.
10. **Fill in the Completion Note**, commit the SDD state.

---

## Completion Note

**Completed by**: sdd-worker

Delivered by gpt-5.6-terra; merged by engine; tests pass.

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none

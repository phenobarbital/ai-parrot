# TASK-4602: Document the agent configure lifecycle

**Feature**: FEAT-721 — Double-`configure()` Is Not a Crash
**Spec**: `sdd/specs/double-configure-agents.spec.md`
**Status**: pending
**Priority**: low
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-4596, TASK-4597
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 5 and §7 *Patterns to Follow*. Agent authors need one page stating the
contract their `configure()` / `post_configure()` overrides must satisfy now that
`configure()` is idempotent and `register_toolkit()` keeps the first registration.
`AbstractBot.post_configure`'s docstring (TASK-4597) already points here.

---

## Scope

- Create `docs/agent-configure-lifecycle.md`, styled like the sibling
  `docs/bot-cleanup-lifecycle.md` (title, Feature/Spec block quote, sections).

**NOT in scope**: code changes; editing other docs.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `docs/agent-configure-lifecycle.md` | CREATE | configure / post_configure contract for agent authors |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.tools.manager import ToolManager                 # verified: tools/manager.py:289
from parrot.tools.working_memory import WorkingMemoryToolkit  # verified: tools/working_memory/__init__.py:3
```

### Existing Signatures to Use
```python
# created by TASK-4597 (bots/abstract.py)
AbstractBot.configure(self, app=None) -> None          # idempotent per instance
AbstractBot.reconfigure(self, app=None) -> None
AbstractBot.configure_count -> int                     # property
# created by TASK-4596 (tools/manager.py)
ToolManager.find_registered_toolkit(self, toolkit_cls, *, tool_prefix=None)
# existing
AbstractBot.post_configure(self) -> None               # bots/abstract.py:1767
docs/bot-cleanup-lifecycle.md                          # sibling doc, style reference
```

### Does NOT Exist
- ~~`configure(app, force=True)`~~ — document `reconfigure()` instead.
- ~~a lock around `configure()`~~ — the doc must NOT imply concurrency safety on one instance.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "docs/agent-configure-lifecycle.md", "action": "CREATE"}
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

The spec fixes the order of the content (§7): (1) `configure()` is idempotent per
instance; (2) `reconfigure()` is the only way to force a re-run; (3) `post_configure()`
may run more than once per instance and must adopt, not rebuild; (4)
`find_registered_toolkit()` is how you adopt; (5) keep-first means the manager wins —
never assume your fresh instance is the registered one. Add the concurrency caveat from
spec §7 *Known Risks* and the `configure_count > 1` guard for post-`super()` work.

---

## Implementation Blueprint

### Steps (in order)
1. Write the page from the skeleton below — *why*: the order is fixed by the spec.
2. Verify every symbol you name exists on the merged code (TASK-4596/4597 are done).

### `docs/agent-configure-lifecycle.md` (CREATE)
```markdown
# Agent Configure Lifecycle

> **Feature**: FEAT-721 — Double-`configure()` Is Not a Crash
> **Spec**: [sdd/specs/double-configure-agents.spec.md](../sdd/specs/double-configure-agents.spec.md)

This document describes what `AbstractBot.configure()` guarantees and the contract
`configure()` / `post_configure()` overrides must follow so an agent can be configured
more than once in one process.

---

## 1. `configure()` is idempotent per instance
<!-- FILL IN: the guard rule — re-entry with no app or the same app is a logged no-op; a
     newly arriving app re-runs the pipeline; configure_count; the unchanged finally contract. -->

## 2. Forcing a re-run: `reconfigure()`
<!-- FILL IN: resets the counter, re-runs configure() (and post_configure()) with the given or bound app. -->

## 3. `post_configure()` must be re-entrant
<!-- FILL IN: it runs again under reconfigure() and when a new app arrives; adopt, don't rebuild. -->

## 4. Adopting a toolkit: `find_registered_toolkit()`

```python
async def post_configure(self) -> None:
    await super().post_configure()
    working_memory = self.tool_manager.find_registered_toolkit(WorkingMemoryToolkit)
    if working_memory is None:
        working_memory = WorkingMemoryToolkit(session_id=f"{self.name}-wm")
        self.tool_manager.register_toolkit(working_memory)
    self.working_memory = working_memory
```

## 5. Keep-first: the manager wins
<!-- FILL IN: re-registering the same class + tool_prefix returns the registered tools; a
     different instance is ignored (WARNING); a different owner claiming a name still raises
     ToolNameCollisionError; de-duplicate if you extend a list with the returned tools. -->

## 6. Work after `super().configure()`
<!-- FILL IN: `if self.configure_count > 1: return` guard for subclass-owned work. -->

## 7. Not a concurrency guarantee
<!-- FILL IN: two coroutines configuring the SAME instance at once can both pass the counter;
     keep-first keeps that from raising. Concurrent configure of DIFFERENT instances is fine. -->
```
**Why**: section order and examples come straight from spec §7; the code sample is the
FEAT-721 adopt pattern used by TASK-4598.

### FILL IN checklist
- [ ] the six prose sections marked FILL IN

---

## Acceptance Criteria

- [ ] `docs/agent-configure-lifecycle.md` exists and covers the five points in the spec's order plus the concurrency caveat.
- [ ] Every symbol it names exists in the merged code.
- [ ] The spec link resolves (`sdd/specs/double-configure-agents.spec.md`).

---

## Validation Commands

- `pytest packages/ai-parrot/tests/interfaces/test_configure_applies_tooling.py -q`

---

## Test Specification

Documentation only; the validation command re-runs the behaviour the page documents.

---

## Agent Instructions

1. **Work in the feature worktree** — never on `dev`
   (`python -m scripts.sdd.ensure_worktree --slug double-configure-agents --feature-id FEAT-721`).
2. **Read the spec** (§2, §4, §5).
3. **Check dependencies** — TASK-4596 and TASK-4597 must be `"done"` in `sdd/tasks/index/double-configure-agents.json`.
4. **Verify the Codebase Contract** — confirm the symbols the dependencies created exist before writing.
5. **Update status** → `"in-progress"`; commit only the index file.
6. **Implement** from the blueprint; complete every `# FILL IN:`.
7. **Verify** — Validation Commands with `PYTHONPATH=packages/ai-parrot/src`.
8. **Commit** — only the files this task lists.
9. **Close** with `scripts/sdd/close_task.sh TASK-4602 double-configure-agents verified`.
10. **Fill in the Completion Note**, commit the SDD state.

---

## Completion Note

**Completed by**: sdd-worker

Delivered by glm (after mistral timeout). Validation test test_configure_applies_tooling fails on origin/dev too (pre-existing, AbstractBot abstract instantiation); docs/agent-configure-lifecycle.md present.

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none

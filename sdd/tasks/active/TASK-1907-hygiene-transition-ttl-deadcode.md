# TASK-1907: Hygiene — Jira transition candidates, review_escalation TTL, dead JSON-schema path

**Feature**: FEAT-377 — Graph Engineering Hardening
**Spec**: `sdd/specs/graphindex-as-engineering-devloop.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Module 1 items 2, 4, 5 (spec §3). Three small verified defects:
(a) `FailureHandlerNode` hard-codes a Jira transition label and breaks on
workflows without it; (b) `_GATE_TTL_CONF_ATTR` lacks a `review_escalation`
entry so `gate_ttl_for("review_escalation")` raises `KeyError`;
(c) the Claude dispatcher carries a dead `_materialize_json_schema` +
`json_schema_path=None` plumbing.

---

## Scope

- In `nodes/failure_handler.py` (lines 87-89): replace
  `jira_transition_issue(issue=issue_key, transition="Needs Human Review")`
  with `transition_issue_with_candidates(...)` using ordered candidates
  `["Needs Human Review", "Blocked", "To Do"]` — same pattern as
  `deployment_handoff.py` and `close.py`.
- In `runner.py` (lines 71-76): add
  `"review_escalation": "DEV_LOOP_GATE_TTL_REVIEW_ESCALATION"` to
  `_GATE_TTL_CONF_ATTR`, and declare the config default alongside the other
  `DEV_LOOP_GATE_TTL_*` keys (grep for where they get defaults; match that
  mechanism and pick a default consistent with `deployment_approval`'s).
- In `dispatcher.py`: delete `ClaudeCodeDispatcher._materialize_json_schema`
  (line ~618) and the pinned `json_schema_path=None` parameter plumbing
  (lines ~280, ~307-315). KEEP the explanatory comment's content by folding
  a one-line note where the option used to be if the call site still needs
  context. Do NOT touch `CodexCodeDispatcher._materialize_json_schema`
  (line ~1006) — it is actively used.
- Unit tests for (a) and (b).

**NOT in scope**: `RevisionBrief` changes (TASK-1908); prompt sync
(TASK-1906); any behavioral change to gates beyond the TTL map entry.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/nodes/failure_handler.py` | MODIFY | transition candidates |
| `packages/ai-parrot/src/parrot/flows/dev_loop/runner.py` | MODIFY | TTL map entry + default |
| `packages/ai-parrot/src/parrot/flows/dev_loop/dispatcher.py` | MODIFY | delete dead Claude-dispatcher schema path |
| `packages/ai-parrot/tests/flows/dev_loop/test_failure_handler.py` | MODIFY/CREATE | candidates fallback test |
| `packages/ai-parrot/tests/flows/dev_loop/test_runner_gates.py` | MODIFY/CREATE | `gate_ttl_for("review_escalation")` test |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.flows.dev_loop.nodes.base import transition_issue_with_candidates
# verified: nodes/base.py:53
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/flows/dev_loop/nodes/base.py:53-60
async def transition_issue_with_candidates(
    jira: Any, issue: str, candidates: Sequence[str], *,
    logger: logging.Logger, **kwargs: Any,
) -> Optional[Dict[str, Any]]:
# already used by deployment_handoff.py:204,397 and close.py:78 — copy that call shape

# packages/ai-parrot/src/parrot/flows/dev_loop/nodes/failure_handler.py:87-89 (the defect)
await self._jira.jira_transition_issue(issue=issue_key, transition="Needs Human Review")

# packages/ai-parrot/src/parrot/flows/dev_loop/runner.py:71-76
_GATE_TTL_CONF_ATTR: Dict[GateKind, str] = {
    "deployment_approval": "DEV_LOOP_GATE_TTL_DEPLOYMENT",
    "manual_criterion": "DEV_LOOP_GATE_TTL_MANUAL",
    "revision_approval": "DEV_LOOP_GATE_TTL_REVISION",
    "plan_approval": "DEV_LOOP_GATE_TTL_PLAN",
}
# gate_ttl_for at line 79 — KeyErrors on "review_escalation" today

# packages/ai-parrot/src/parrot/flows/dev_loop/dispatcher.py
# ClaudeCodeDispatcher.dispatch ~line 280: json_schema_path: Optional[str] = None
# lines ~307-315: json_schema_path=None passed with explanatory comment
# line ~618: ClaudeCodeDispatcher._materialize_json_schema — DEAD, delete
# line ~1006: CodexCodeDispatcher._materialize_json_schema — ACTIVE, keep
```

### Does NOT Exist
- ~~`_GATE_TTL_CONF_ATTR["review_escalation"]`~~ — missing today; this task adds it
- ~~`DEV_LOOP_GATE_TTL_REVIEW_ESCALATION`~~ — config key does not exist yet; this task declares it
- ~~any caller of `ClaudeCodeDispatcher._materialize_json_schema`~~ — zero callers (that is why it is dead)

---

## Implementation Notes

### Key Constraints
- `review_escalation` gates are opened by `qa.py:508` — after the TTL entry
  lands, verify that call path picks up the TTL without further change.
- Line numbers are from 2026-07-26; re-verify before editing.
- Async throughout; `self.logger` for the fallback-path log line.

### References in Codebase
- `packages/ai-parrot/src/parrot/flows/dev_loop/nodes/deployment_handoff.py:204,397` — candidate-transition call pattern
- `packages/ai-parrot/src/parrot/flows/dev_loop/nodes/qa.py:508` — review_escalation open_gate site

---

## Acceptance Criteria

- [ ] `FailureHandlerNode` succeeds against a mock Jira lacking "Needs Human Review" (falls through candidates)
- [ ] `gate_ttl_for("review_escalation")` returns a TTL, no `KeyError`
- [ ] `ClaudeCodeDispatcher._materialize_json_schema` is gone; `CodexCodeDispatcher`'s copy untouched
- [ ] `pytest packages/ai-parrot/tests/flows/dev_loop/ -v` passes
- [ ] `ruff check packages/ai-parrot/src/parrot/flows/dev_loop/` clean

---

## Test Specification

```python
# test: mock jira whose transitions lack "Needs Human Review" but have "Blocked"
async def test_failure_handler_falls_through_candidates(mock_jira): ...

# test: every GateKind member resolves a TTL
@pytest.mark.parametrize("kind", get_args(GateKind))
def test_gate_ttl_for_all_kinds(kind):
    assert gate_ttl_for(kind) is not None or ...  # match actual return contract
```

---

## Agent Instructions

1. **Read the spec** for full context
2. **Check dependencies** — none
3. **Verify the Codebase Contract** before writing any code
4. **Update status** in `sdd/tasks/index/graphindex-as-engineering-devloop.json` → `"in-progress"`
5. **Implement**, **verify**, move this file to `sdd/tasks/completed/`, update index → `"done"`, fill the Completion Note

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none

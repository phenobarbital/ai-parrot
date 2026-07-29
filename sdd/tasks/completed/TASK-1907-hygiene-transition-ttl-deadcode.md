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

### Contract correction (found during implementation, 2026-07-26)
- ~~`DEV_LOOP_GATE_TTL_REVIEW_ESCALATION` config key does not exist yet~~ —
  **FALSE**. `parrot/conf.py:1004-1006` already declares it
  (`config.getint("DEV_LOOP_GATE_TTL_REVIEW_ESCALATION", fallback=86400)`)
  and `nodes/qa.py:470` already reads `conf.DEV_LOOP_GATE_TTL_REVIEW_ESCALATION`
  directly for the `review_escalation` gate's `ttl_seconds`. The ONLY
  missing piece was the `_GATE_TTL_CONF_ATTR` dict entry in `runner.py`
  (confirmed by grep before editing) — no `conf.py` change was needed.
- The test-file scope named `test_runner_gates.py` (MODIFY/CREATE) for the
  TTL fix, but the real, pre-existing `gate_ttl_for` coverage lives in
  `test_runner_host.py::test_gate_ttl_for_all_kinds` (verified via grep).
  Extended that test in place rather than creating a duplicate new file.

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

**Completed by**: sdd-worker (Claude)
**Date**: 2026-07-26
**Notes**:
- `failure_handler.py`: replaced the hard-coded `jira_transition_issue(...,
  transition="Needs Human Review")` call with
  `transition_issue_with_candidates(self._jira, issue_key, ["Needs Human
  Review", "Blocked", "To Do"], logger=self.logger)`, matching
  `deployment_handoff.py`/`close.py`. Updated the `jira` test fixture to
  add `jira_transition_to` (the helper's preferred walker method) and
  added two new tests: preferred-candidate success, and fallback through
  all three candidates when the workflow lacks the first two.
- `runner.py`: added `"review_escalation": "DEV_LOOP_GATE_TTL_REVIEW_ESCALATION"`
  to `_GATE_TTL_CONF_ATTR`. The conf default already existed
  (`conf.py:1004-1006`, added by FEAT-375) — see Codebase Contract
  correction above. Extended `test_gate_ttl_for_all_kinds` in
  `test_runner_host.py` plus a new `test_gate_ttl_for_covers_every_gate_kind`
  regression guard over `get_args(GateKind)`.
- `dispatcher.py`: deleted `ClaudeCodeDispatcher._materialize_json_schema`
  (zero callers, confirmed by grep) and the entirely-dead `json_schema_path`
  plumbing: the local var in `dispatch()`, the `finally:` unlink guard
  (always `None`, never reassigned), and the unused keyword parameter on
  `_resolve_run_options` (never referenced inside that method's body
  either — confirmed by full read before removing; no test references it).
  `CodexCodeDispatcher._materialize_json_schema` (line ~1326, now shifted)
  is untouched and still has its live caller.
- `pytest packages/ai-parrot/tests/flows/dev_loop/ -m "not live"` (minus
  the pre-existing `hypothesis`-missing `test_session_state_properties.py`):
  650 passed, 1 skipped, plus the same one pre-existing unrelated
  test-order-dependent failure noted in TASK-1906
  (`test_lazy_import.py::test_models_module_is_pure`, passes in isolation).
- `ruff check` clean on all touched files.

**Deviations from spec**: none beyond the two Codebase Contract
corrections above (both additive-knowledge, not behavior changes).

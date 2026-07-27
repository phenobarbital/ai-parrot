# TASK-1919: Session-state extension — feature NodeIds, actions and reducers

**Feature**: FEAT-378 — DevLoop Enhancement — Feature-Mode Topology
**Spec**: `sdd/specs/devloop-enhancement.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-1918
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 7 (state slice, pulled forward because the four new nodes
record these actions). FEAT-322 mandates event-sourced state: all new
feature-mode state enters `DevLoopSessionState` as action types + reducers —
never mutable attributes.

---

## Scope

- Extend `NodeId` Literal (session_state.py:139) with: `"planner"`,
  `"synthesis"`, `"feedback_router"`, `"feature_handoff"`.
- Add action types + reducers:
  - `JudgeVerdictRecorded` — payload: judge id/backend/model, passed,
    findings count, summary (one action per judge per QA round).
  - `FeedbackDecisionRecorded` — payload: the `FeedbackDecision` fields +
    qa attempt number.
  - `DocsArtifactLinked` — payload: docs_path, wiki_page_id (optional),
    pr_url (optional).
- Reducers accumulate (append-only lists / keyed maps) following the existing
  reducer style in `reduce()` (session_state.py:560).
- Unit tests for each reducer + a regression test that unknown-action
  behavior is unchanged.

**NOT in scope**: emitting these actions from nodes (TASK-1921/1923/1924),
new GateKinds (none needed — spec reuses existing gates), topology wiring
(TASK-1925).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/session_state.py` | MODIFY | NodeId +4, actions, reducers |
| `packages/ai-parrot/tests/flows/dev_loop/test_session_state_feature.py` | CREATE | Reducer unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# Verify exact exported names at task start (session_state.py is large):
# grep -n "^class \|^def \|^NodeId\|^GateKind" packages/ai-parrot/src/parrot/flows/dev_loop/session_state.py
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/flows/dev_loop/session_state.py  (verified 2026-07-27)
NodeId = Literal[...]        # :139 — currently ONLY the 9 ids: intent_classifier,
                             # bug_intake, research, development, qa,
                             # deployment_handoff, failure_handler, close, revision_handoff
GateKind = Literal["manual_criterion","deployment_approval","revision_approval",
                   "plan_approval","review_escalation"]   # :166 — do NOT extend
class SessionHost:           # :724 — open_gate :862, wait_gate :932, resolve_gate :817
def reduce(...): ...         # :560 — dispatch point for all action reducers (FEAT-322)
```

### Does NOT Exist
- ~~`QaAttemptRecorded`, `qa_attempts` field~~ — FEAT-377 TASK-1910 (in
  progress on branch `feat-377-graphindex-as-engineering-devloop`, NOT on
  dev as of 2026-07-27). If it has merged by the time you start, place the
  new actions alongside it and reference the attempt counter in
  `FeedbackDecisionRecorded`; if not, carry attempt number in the action
  payload only.
- ~~Cross-process persistence of `SessionHost`~~ — in-memory per run (FEAT-D future). Do not add serialization.
- ~~Mutable state fields for verdicts/decisions~~ — forbidden by FEAT-322; reducers only.

---

## Implementation Notes

### Pattern to Follow
Copy the structure of an existing recorded action + its reducer branch in
`reduce()` (session_state.py:560) — e.g. how gate resolutions or QA results
are appended. Keep naming consistent (`*Recorded`, past tense).

### Key Constraints
- Append-only semantics; reducers must be pure.
- `JudgeVerdictRecorded` must key by QA round so retries don't overwrite
  earlier panels.
- Update any exhaustiveness checks/tests over `NodeId` in the same commit.

### References in Codebase
- `packages/ai-parrot/src/parrot/flows/dev_loop/session_state.py:560` — reducer dispatch
- FEAT-322 spec (`sdd/specs/`) — event-sourcing rules

---

## Acceptance Criteria

- [ ] `NodeId` accepts the 4 new ids; existing 9 unchanged
- [ ] Three new actions reduce correctly (append/accumulate, keyed by round where applicable)
- [ ] Unknown-action behavior unchanged (regression test)
- [ ] All tests pass: `pytest packages/ai-parrot/tests/flows/dev_loop/test_session_state_feature.py -v` AND the existing session-state suite stays green
- [ ] `ruff check packages/ai-parrot/src/parrot/flows/dev_loop/session_state.py`

---

## Test Specification

```python
# packages/ai-parrot/tests/flows/dev_loop/test_session_state_feature.py
def test_judge_verdict_recorded_accumulates_per_round(): ...
def test_feedback_decision_recorded(): ...
def test_docs_artifact_linked(): ...
def test_unknown_action_still_ignored_or_raises_as_before(): ...
def test_new_node_ids_valid(): ...
```

---

## Agent Instructions

1. **Read the spec** (§2 Internal Behavior items 5-7, §6, §7 Patterns)
2. **Check dependencies** — TASK-1918 in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — CRITICAL: check whether FEAT-377
   (branch `feat-377-graphindex-as-engineering-devloop`) has merged; it also
   edits session_state.py (QaAttemptRecorded, plan-gate work). Re-grep all
   line anchors either way.
4. **Update status** in `sdd/tasks/index/devloop-enhancement.json` → `"in-progress"`
5. **Implement**, **verify criteria**, move file to `sdd/tasks/completed/`, update index → `"done"`, fill Completion Note

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none

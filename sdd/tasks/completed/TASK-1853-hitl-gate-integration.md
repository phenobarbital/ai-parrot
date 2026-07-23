# TASK-1853: HITL gate integration — blocking ManualCriterion + deployment approval

**Feature**: FEAT-322 — AHP-style Session State, Host & HITL Approval Gates for dev-loop
**Spec**: `sdd/specs/agent-host-protocol-session-state.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-1851
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 5 — the `dev-loop-approval-gates` capability's product value:
QA manual criteria can block on a human (per-criterion opt-in, resolved
proposal U1), and DeploymentHandoff requires human approval before the Jira
transition (reject/expire → `failure_handler`, resolved in brainstorm).

---

## Scope

- **`models.py` — `ManualCriterion` (:70)**: add `blocking: bool = False`
  with a field description. Default `False` preserves today's behavior
  everywhere.
- **`nodes/qa.py`**: in `execute` (:108), after the FEAT-270 code-review
  loop and where `_merge_manual_results` is called today (:166-167):
  - Split `manual` into blocking vs non-blocking.
  - Non-blocking → existing `_merge_manual_results` path, unchanged.
  - Blocking → get `host = shared.get("session_host")`; if None (legacy
    runner without hosts) log a WARNING and fall back to the non-blocking
    synthesis (never crash a legacy run). Otherwise per criterion:
    `gate_id, _ = host.open_gate(kind="manual_criterion", node_id="qa",
    title=c.name, instructions=c.text, ttl_seconds=<DEV_LOOP_GATE_TTL_MANUAL>,
    on_expiry="fail")`; then `gate = await host.wait_gate(gate_id)`;
    fold into a `CriterionResult(kind="manual", passed=(gate.status=="approved"),
    ...)` with the resolution audit (resolved_by/comment) appended to notes.
  - A rejected/expired blocking criterion ⇒ report `passed=False` (combined
    with the existing `deterministic_passed and cr_passed` logic) so CEL
    routes the run to `failure_handler`.
- **`nodes/deployment_handoff.py`** — `execute` (:89), between PR creation
  success (:160-162, `pr_number` known) and the Jira transition (:164):
  - `host = shared.get("session_host")`; if None → log WARNING, proceed as
    today (backward compat).
  - Open `deployment_approval` gate (`title=f"Deploy approval: {issue_key}"`,
    `instructions` includes pr_url, `payload_ref=changeset_channel(run_id)`,
    `ttl_seconds=<DEV_LOOP_GATE_TTL_DEPLOYMENT>`, `on_expiry="fail"`);
    `gate = await host.wait_gate(gate_id)`.
  - `approved` → continue to Jira transition + comment exactly as today.
  - `rejected`/`expired` → `await self._mark_blocked(issue_key, <reason with resolver + comment>)`
    and `return {"status": "blocked", "error": f"deployment_approval {gate.status} by {gate.resolved_by or 'ttl'}"}`
    — reuses the existing blocked path; no new edges (verify how a
    "blocked" result routes in the current graph and note it — the hard
    guarantee is: NO Jira transition happens).
- Gate TTLs come from the conf helper added in TASK-1851 (`gate_ttl_for`).
- Tests per spec §4 M5 rows (blocking default false byte-identical;
  approved/rejected paths; handoff gate ordering; no-host fallback).

**NOT in scope**: `revision_approval` / `plan_approval` gate call-sites
(kinds exist in the union; no node opens them in this feature — document
in Completion Note); REST endpoints (TASK-1855); runner changes.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/models.py` | MODIFY | `ManualCriterion.blocking: bool = False` |
| `packages/ai-parrot/src/parrot/flows/dev_loop/nodes/qa.py` | MODIFY | blocking-criteria gates |
| `packages/ai-parrot/src/parrot/flows/dev_loop/nodes/deployment_handoff.py` | MODIFY | deployment_approval gate pre-Jira |
| `packages/ai-parrot/tests/flows/dev_loop/test_gate_integration.py` | CREATE | node-level gate tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.flows.dev_loop.session_state import (   # TASK-1848/1849
    ApprovalGate, SessionHost, changeset_channel,
)
from parrot.flows.dev_loop.models import ManualCriterion  # existing (nodes/qa.py:38)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/flows/dev_loop/models.py
class ManualCriterion(BaseModel): ...        # :70 — kind="manual"; fields: name, text. NO blocking yet.
class QAReport(BaseModel): ...               # :349 — passed, criterion_results: List[CriterionResult],
                                             #   lint_passed, lint_output, notes, code_review_passed, code_review_findings
# CriterionResult fields (see qa.py:311-322 synthesis): name, kind, exit_code,
#   duration_seconds, stdout_tail, stderr_tail, passed

# packages/ai-parrot/src/parrot/flows/dev_loop/nodes/qa.py
class QANode(DevLoopNode):
    async def execute(self, ctx, deps=None, **kwargs) -> QAReport: ...   # :108
    # shared = self.shared_state(ctx) :125 — dict with research_output, bug_brief
    # manual filter :129-136; review loop :148-164;
    # manual merge point :166-167:  if manual: report = self._merge_manual_results(report, manual)
    # final passed :170: deterministic_passed and cr_passed
    # stores shared["qa_report"] :205
    @staticmethod
    def _merge_manual_results(report, manual) -> QAReport: ...           # :301 (keep for non-blocking)

# packages/ai-parrot/src/parrot/flows/dev_loop/nodes/deployment_handoff.py
class DeploymentHandoffNode(DevLoopNode):                                # :46
    async def execute(self, ctx, deps=None, **kwargs) -> Dict[str, Any]: # :89
    # shared state :111-116 (research_output, bug_brief, qa_report)
    # push :118-126 → PR retry-once :128-160 (pr_url; blocked return :153-160)
    # pr_number = self._parse_pr_number(pr_url) :162
    # Jira transition :164-175 (transition_issue_with_candidates,
    #   conf.DEV_LOOP_JIRA_TRANSITIONS_READY) — GATE GOES IMMEDIATELY BEFORE
    # _mark_blocked(issue_key, reason) exists (used :125, :154) — reuse it
    # attribute style: object.__setattr__ in __init__ :74-83

# SessionHost (TASK-1849): open_gate(...)-> (gate_id, envelope); wait_gate(gate_id) -> ApprovalGate
# gate_ttl_for(kind) helper: added by TASK-1851 (runner module) — import from there
```

### Does NOT Exist
- ~~`ManualCriterion.blocking`~~ — THIS task adds it
- ~~any gate/approval logic in qa.py or deployment_handoff.py~~ — confirmed absent (qa.py:301 synthesizes passed=True; Jira transition unconditional)
- ~~`shared["session_host"]` before TASK-1851~~ — seeded by the runner; nodes must handle its absence gracefully
- ~~new CEL edges or "rejected" statuses in definition.py~~ — routing reuses the existing blocked/failure paths; do not touch definition.py
- ~~`DevLoopNode.open_gate`~~ — gates open via the host from shared state, not via node base-class API

---

## Implementation Notes

### Key Constraints
- **Fold before return** (spec §7): CEL predicates route on `result.passed`
  (definition.py:49-50) — all gate awaiting must complete inside `execute`.
- Preserve FEAT-270 semantics untouched: blocking-gate logic slots in at the
  manual-merge point only; `cr_passed`/degrade-to-pass logic unmodified.
- No-host fallback keeps the run non-blocking (WARNING log) — legacy
  construction must never deadlock.
- Multiple blocking criteria: open ALL gates first, then await all
  (concurrent human review), e.g. `asyncio.gather(*[host.wait_gate(g) for g in gate_ids])`.
- Audit visibility: append `"{name}: {status} by {resolved_by} — {comment}"`
  lines to `QAReport.notes` for blocking criteria.

---

## Acceptance Criteria

- [ ] `blocking` unset ⇒ existing tests pass unmodified (byte-identical behavior)
- [ ] Blocking criterion approved ⇒ passed=True result + audit in notes
- [ ] Blocking criterion rejected/expired ⇒ `QAReport.passed=False` (routes to failure per existing CEL)
- [ ] Deployment: Jira transition called ONLY after gate approved; reject/expire ⇒ `_mark_blocked` + blocked return, NO transition
- [ ] No-host fallback: both nodes behave exactly as today with a WARNING
- [ ] Multiple blocking criteria awaited concurrently
- [ ] Tests pass: `pytest packages/ai-parrot/tests/flows/dev_loop/ -v`; `ruff check` clean

---

## Test Specification

```python
# packages/ai-parrot/tests/flows/dev_loop/test_gate_integration.py
async def test_manual_blocking_default_false_unchanged(): ...
async def test_qa_blocking_gate_approved_folds_passed(): ...
async def test_qa_blocking_gate_rejected_fails_report(): ...
async def test_qa_no_host_falls_back_with_warning(caplog): ...
async def test_handoff_jira_not_called_until_approved(): ...
async def test_handoff_rejected_marks_blocked_no_transition(): ...
# Pattern: resolve gates from the test via host.resolve_gate(...) after a
# short asyncio.sleep(0), or pre-resolve before invoking execute.
```

---

## Agent Instructions

1. Read spec §2 Overview (gate flows) + §3 M5 + §7. Verify TASK-1851 completed.
2. RE-VERIFY qa.py / deployment_handoff.py anchors (active files, FEAT-270).
3. Implement; run full dev_loop suite; move to completed; update index.

---

## Completion Note

**Completed by**: sdd-worker (autonomous)
**Date**: 2026-07-22
**Notes**: `ManualCriterion.blocking: bool = False` added. `QANode.execute`
now splits `manual` into blocking/non-blocking; non-blocking keeps the
exact `_merge_manual_results` path; blocking criteria open one
`manual_criterion` gate each via `shared["session_host"]`
(TTL from `gate_ttl_for("manual_criterion")`), open ALL gates first then
`asyncio.gather` all `wait_gate` calls (concurrent human review), fold
`CriterionResult(kind="manual", passed=(status=="approved"))` + audit
lines into `QAReport.notes`, and combine into
`passed = deterministic_passed and cr_passed and blocking_passed`. No-host
fallback (`shared.get("session_host") is None`) logs a WARNING and
degrades to the non-blocking synthesis — never deadlocks.
`DeploymentHandoffNode` gained a `deployment_approval` gate between PR
creation and the Jira transition, opened via `_await_deployment_approval`
(`gate_ttl_for("deployment_approval")`, `payload_ref=changeset_channel(run_id)`);
reject/expire → `_mark_blocked` + `{"status": "blocked", "error":
"deployment_approval <status> by <resolver>"}`, reusing the existing
blocked path (no new edges; verified `_mark_blocked` already fires the
BLOCKED Jira transition + comment via the same
`transition_issue_with_candidates` walker). 20 new tests in
`test_gate_integration.py` (approved/rejected/concurrent-gates/no-host
paths for both nodes, default-off regression guard). Full dev_loop suite:
484 passed (same 4 pre-existing unrelated failures as prior tasks in this
feature), no hangs.

**Deviations from spec**:
1. **`DeploymentHandoffNode.require_deployment_approval: bool = False`
   constructor flag added (NOT in the task's file-list scope beyond
   `deployment_handoff.py` itself, but a necessary correction discovered
   while validating this task).** The task's scope said to gate on
   `host = shared.get("session_host"); if host is not None: <open gate>`.
   But TASK-1851 (already completed) made `DevLoopRunner.run()`/
   `run_revision()` ALWAYS seed `shared["session_host"]` — unconditionally,
   for every construction style, not just "AHP-enabled" runners. Gating
   purely on host-presence would therefore make the `deployment_approval`
   gate MANDATORY for every existing and future run through the real
   runner, with nothing to resolve it — verified as a concrete regression:
   the full `pytest packages/ai-parrot/tests/flows/dev_loop/` run hung
   indefinitely inside `test_runner.py`'s pre-existing happy-path tests
   (which exercise `DeploymentHandoffNode` via `runner.run()` and never
   resolve a gate). Added `require_deployment_approval` (default `False`)
   as the explicit opt-in — the same "per-criterion opt-in" philosophy
   spec §1 G4 already establishes for `ManualCriterion.blocking` — so the
   gate only activates when BOTH a host is present AND the node was
   explicitly constructed with the flag on. `factories.py`/`runner.py` were
   NOT touched to wire this flag on by default anywhere (out of this
   task's file-list scope) — flagging that a follow-up task must decide
   how/when to turn `require_deployment_approval=True` on for real runs
   (e.g. a new conf key threaded through `build_dev_loop_node_factories`)
   for the deployment-approval gate to ever fire in production. Added a
   regression-guard test
   (`test_handoff_default_skips_gate_even_with_host_present`) documenting
   exactly this scenario.
2. **`revision_approval` / `plan_approval` gate call-sites**: confirmed
   NOT in scope per the task; no node opens them. `plan_approval` would
   naturally slot into `ResearchNode` (approve the plan before
   Development) and `revision_approval` into `RevisionHandoffNode`
   (approve before pushing to the existing PR) — neither touched here.

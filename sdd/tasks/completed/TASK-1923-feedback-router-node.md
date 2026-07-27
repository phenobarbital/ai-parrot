# TASK-1923: FeedbackRouterNode + sdd-feedback subagent — bounded retry / escalate / accept

**Feature**: FEAT-378 — DevLoop Enhancement — Feature-Mode Topology
**Spec**: `sdd/specs/devloop-enhancement.spec.md`
**Status**: done
**Completed**: 2026-07-27
**Verification**: verified
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1918, TASK-1919, TASK-1920
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 5. On QA failure, a short read-only LLM dispatch
(`sdd-feedback`) translates the QAReport + judge-panel verdicts into a
`FeedbackDecision`: `retry` (with an actionable dev-brief, bounded by the
FEAT-377/A stop rule), `escalate`, or `accept_with_notes` — the latter ONLY
inside a hard deterministic envelope enforced in Python, never by the prompt.

---

## Scope

- Implement `FeedbackRouterNode(DevLoopNode)` in
  `parrot/flows/dev_loop/nodes/feedback_router.py`, node id
  `"feedback_router"`, registered via `@register_dev_loop_node`:
  - Input: `QAReport` + recorded judge verdicts from session state.
  - Compute the deterministic envelope FIRST, in Python:
    `envelope_ok = deterministic QA passed AND all pending findings are
    minor/nit AND all failed manual criteria are non-blocking`.
  - Dispatch subagent `sdd-feedback` (read-only, plan-mode style like
    sdd-qa) → parse `FeedbackDecision`.
  - Enforcement (Python, post-parse — the LLM only proposes):
    - `accept_with_notes` proposed but `envelope_ok` is False → downgrade to
      `retry` if attempts remain else `escalate` (log the override).
    - `retry` proposed but attempts exhausted → `escalate` (stop rule is
      inviolable; see contract re FEAT-377/A availability).
  - Record `FeedbackDecisionRecorded` action (TASK-1919).
  - Publish the decision + dev-brief to shared state for the conditional
    edges (wired in TASK-1925): retry → development (brief injected),
    escalate → failure_handler, accept_with_notes → feature_handoff (notes
    for the PR body).
- Write `sdd-feedback` prompt: `_subagent_data/sdd-feedback.md` +
  `.claude/agents/sdd-feedback.md` mirror. Output: ONE JSON object matching
  `FeedbackDecision`; no prose.
- Unit tests with stubbed dispatcher.

**NOT in scope**: the retry edge itself and CEL predicates (TASK-1925);
feedback-injection plumbing into DevelopmentNode (FEAT-377/A provides it —
consume only); judge panel internals (TASK-1920).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/nodes/feedback_router.py` | CREATE | FeedbackRouterNode |
| `packages/ai-parrot/src/parrot/flows/dev_loop/_subagent_data/sdd-feedback.md` | CREATE | Subagent prompt (authoritative) |
| `.claude/agents/sdd-feedback.md` | CREATE | Mirror |
| `packages/ai-parrot/src/parrot/flows/dev_loop/_subagent_defs.py` | MODIFY | Add `"sdd-feedback"` to `_VALID_NAMES` — same gap TASK-1921 found and flagged for this task: `load_subagent_definition()` gates on this frozenset independently of `ClaudeCodeDispatchProfile.subagent`'s Literal (TASK-1918). |
| `packages/ai-parrot/tests/flows/dev_loop/test_feedback_router.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.flows.dev_loop.nodes.base import register_dev_loop_node, DevLoopNode  # verified 2026-07-27
from parrot.flows.dev_loop.models import FeedbackDecision  # TASK-1918
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/flows/dev_loop/models.py  (verified 2026-07-27)
class QAReport(BaseModel):  # :487 — passed, criterion_results, lint_passed,
                            # notes, code_review_passed, code_review_findings
class AdversarialFinding(CodeReviewFinding):  # :793 — source,
                            # disposition: Optional[Literal["confirm","reject","escalate"]]

# packages/ai-parrot/src/parrot/flows/dev_loop/nodes/qa.py  (verified 2026-07-27)
# sdd-qa dispatches in plan mode :280-285 — copy this read-only dispatch style
# for sdd-feedback.
```

### Does NOT Exist
- ~~`qa_attempts` / `DEV_LOOP_QA_MAX_RETRIES` / `QaAttemptRecorded` /
  `_CEL_QA_RETRY`~~ — FEAT-377 TASK-1910/1911, in progress on branch
  `feat-377-graphindex-as-engineering-devloop`, NOT on dev as of 2026-07-27.
  **At task start, check merge status:**
  - **Merged**: read the attempt counter + max-retries conf exactly as
    landed; `retry` allowed while `attempts < max`.
  - **Not merged**: implement the documented degradation (spec §7): the
    router may only emit `escalate` / `accept_with_notes`; a proposed
    `retry` downgrades to `escalate` with a warning log. Keep the
    enforcement seam isolated in one method so the FEAT-377 wiring is a
    one-line change.
- ~~Finding severity field named `severity` with values minor/nit~~ —
  VERIFY the actual finding severity/level field name on
  `CodeReviewFinding` (models.py, near :757) before coding the envelope;
  do not guess.
- ~~`sdd-feedback` in any dispatch profile Literal~~ — added by TASK-1918.

---

## Implementation Notes

### Pattern to Follow
QANode's plan-mode dispatch (qa.py:280-285) for the read-only subagent call;
ResearchNode for JSON-parse-and-validate.

### Key Constraints
- **The envelope and the stop rule live in Python.** The prompt must state
  the decision space, but every constraint is re-checked post-parse. A test
  MUST prove the LLM cannot force `accept_with_notes` outside the envelope
  nor `retry` past the stop rule.
- Read-only dispatch (no edits) — same permission posture as sdd-qa.
- Notes for `accept_with_notes` must be preserved verbatim for the PR body.

### References in Codebase
- `packages/ai-parrot/src/parrot/flows/dev_loop/nodes/qa.py` — dispatch + triage patterns
- Spec §2 Internal Behavior item 6; §7 Known Risks (stop rule, envelope)

---

## Acceptance Criteria

- [ ] Envelope computed deterministically in Python; LLM proposal overridden when outside it (tested)
- [ ] Stop rule cannot be bypassed: exhausted attempts (or FEAT-377/A absent) → never `retry` (tested)
- [ ] `FeedbackDecisionRecorded` action emitted with attempt context
- [ ] Decision + dev-brief/notes published to shared state
- [ ] `sdd-feedback.md` in `_subagent_data/` + `.claude/agents/` mirror
- [ ] All tests pass: `pytest packages/ai-parrot/tests/flows/dev_loop/test_feedback_router.py -v`
- [ ] `ruff check packages/ai-parrot/src/parrot/flows/dev_loop/nodes/feedback_router.py`

---

## Test Specification

```python
# packages/ai-parrot/tests/flows/dev_loop/test_feedback_router.py
async def test_retry_with_dev_brief(): ...
async def test_accept_with_notes_inside_envelope(): ...
async def test_accept_outside_envelope_downgraded(): ...
async def test_retry_after_exhaustion_escalates(): ...
async def test_escalate_passthrough(): ...
async def test_decision_recorded_action(): ...
```

---

## Agent Instructions

1. **Read the spec** (§2 item 6, §5 envelope criterion, §7)
2. **Check dependencies** — TASK-1918, TASK-1919, TASK-1920 completed
3. **Verify the Codebase Contract** — FIRST check FEAT-377 merge status
   (repair-loop pieces); verify the finding-severity field name; re-grep anchors
4. **Update status** in `sdd/tasks/index/devloop-enhancement.json` → `"in-progress"`
5. **Implement**, **verify criteria**, move file to `sdd/tasks/completed/`, update index → `"done"`, fill Completion Note

---

## Completion Note

**Completed by**: sdd-worker (Claude)
**Date**: 2026-07-27
**Notes**: `FeedbackRouterNode` implemented in `nodes/feedback_router.py`,
registered as `"dev_loop.feedback_router"` (node id `"feedback_router"`).
Confirmed FEAT-377 (`qa_attempts`/`DEV_LOOP_QA_MAX_RETRIES`/
`QaAttemptRecorded`/`_CEL_QA_RETRY`) is still NOT on `dev` — implemented
the documented degradation: `_retry_allowed()` unconditionally returns
`False` (isolated seam, one-line change once FEAT-377/A lands); every
proposed `retry` downgrades to `escalate` with a warning log. Verified
`CodeReviewFinding.severity` field name/values (`critical/major/minor/
nit`) directly in models.py before coding the envelope. The envelope's
per-finding severity check reads `shared["_code_review_verdict"]` —
QANode's own internal/underscored stash of the structured
`CodeReviewVerdict` — since `QAReport.code_review_findings` is plain
strings with no severity data; documented this cross-node shared-state
read explicitly in `_envelope_ok`'s docstring since it's the only place
severities exist. Fail-closed when no verdict is available (cannot
verify "all minor" without it). `FeedbackDecisionRecorded` is applied via
`session_host.apply()` — the first node in the codebase to call `.apply()`
directly for a custom action (previously only `qa.py`'s `open_gate` did).
Judge-panel verdicts (TASK-1919's `judge_verdicts`) are surfaced to the
LLM's brief as human-readable summaries of the latest round, for
situational context only — the strict Python envelope does not depend on
them (they don't carry per-finding severity). Same `_VALID_NAMES`
frozenset gap TASK-1921 flagged: added `"sdd-feedback"` to
`_subagent_defs.py` here (contract updated first, then implemented). All
8 unit tests pass (including a fail-closed no-verdict case beyond the
task's own list); full dev_loop suite green except the pre-existing,
unrelated `test_models_module_is_pure` test-order flake.

**Deviations from spec**: none — the FEAT-377/A stop-rule degradation is
explicitly documented as expected/interim behavior by the task's own
Codebase Contract, not a deviation.

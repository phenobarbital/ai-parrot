# F005 — QANode: manual-criteria synthesis + FEAT-270 review loop

**Query**: Q008 (read nodes/qa.py:96-216, 290-337)
**File**: packages/ai-parrot/src/parrot/flows/dev_loop/nodes/qa.py

## Facts
- `execute` (:108) filters `ManualCriterion` out before dispatching `sdd-qa`
  (:129-136); deterministic QA runs on executable criteria only.
- FEAT-270 additive code-review gate (:148-164): `_run_code_review` via a
  `codereview_dispatcher` (defaults to `ClaudeCodeReviewDispatcher` wrapping
  the dev dispatcher, :100-102). Reviewer may FIX and commit; deterministic
  QA then re-runs (:155-164). Degrade-to-pass on infra error with loud
  skip-note (:174-189) — `code_review_passed=True` can mean "not reviewed".
- `_merge_manual_results` (:301) synthesizes
  `CriterionResult(passed=True, kind="manual", exit_code=0)` for EVERY
  manual criterion (:311-322) and appends a "Manual verification required:"
  block to notes (:324-329). Confirms brainstorm: manual criteria NEVER gate.
- Final `passed = deterministic_passed and cr_passed` (:170); report stored
  in `shared["qa_report"]` (:205).

## Gate-integration implication
The gate insertion point is AFTER `_run_deterministic_qa` + review loop,
replacing the `_merge_manual_results` call (:166-167) for criteria marked
blocking: open one `manual_criterion` gate per blocking ManualCriterion,
await resolution, then fold resolutions into criterion_results
(approved→passed=True, rejected/expired→passed=False). Non-blocking criteria
keep today's synthesis path. Note: QANode.execute returns a QAReport that
CEL predicates route on (`result.passed`) — gate outcomes must land in the
report BEFORE the node returns.

---
type: feature
base_branch: dev
projects: [ai-parrot, sdd-tooling]
tags: [sdd-coder, mcp, coder-review, ledger-fix]
---

# Feature Specification: coder_record_review/feedback accept validated models, and re-dispatched attempts never collide on a leftover sub-worktree

**Feature ID**: FEAT-812
**Date**: 2026-11-05
**Author**: Jesus Lara (with Claude)
**Status**: approved
**Target version**: 2.1.0

Source: ledger `issue:3b913ffd77cd` (major, bug), discovered from `spec:FEAT-806`. Authored by
`/sdd-fix` (SDD lane, group `fixgroup:84b6cffe0c64`). Parent FEAT-806 is closed, so this is a new
feature rather than a task on the parent.

---

## 1. Motivation & Business Requirements

### Problem Statement

The ledger issue reports two defects seen in the same FEAT-806 run of the `parrot-sdd-coder` MCP
server.

**B1 — every `coder_record_review` call fails.** A valid payload is rejected with
`CoderReview() argument after ** must be a mapping, not CoderReview`. Root cause (verified):
commit `197fdeaaa0` ("keep nested Pydantic models intact through argument validation") changed
`AbstractTool._resolve_call_kwargs` to use `AbstractTool._shallow_dump`, which keeps nested models
as model instances. `SddCoderToolkit._create_tool_from_method` installs
`CoderRecordReviewArgs` (field `review: CoderReview`) as the tool's `args_schema`, so the method
`SddCoderToolkit.coder_record_review(..., review)` now receives a `CoderReview` instance, and its
body does `CoderReview(**review)`. `coder_record_feedback` has the identical pattern
(`CoderRecordFeedbackArgs.feedback: CoderFeedback` → `CoderFeedback(**feedback)`), so it is broken
the same way through the MCP adapter. Consequence: no review `EvidenceRef` can be produced, so
`parrot sdd task finalize` (needs `TaskCompletionEvidence.review_evidence`) is unusable and workers
fall back to `parrot sdd task close`.

**B2 — re-dispatching a task in the same execution fails with `git worktree add failed`.**
`SddCoderEngine._run_attempt` names the sub-worktree and branch from
`_worker_id(task_id, attempt, execution_id)` (`<task>.a<N>.<exec-hex>`). Each `_run_task`
invocation restarts `attempt` at 1 (then 2 for the retry ladder). When an attempt fails validation,
its unmerged branch and sub-worktree are intentionally kept (the orchestrator may inspect or repair
from them), so a second `coder_run_chunk` for the same task in the same execution asks
`SubWorktreeManager.create()` for `…a1…` again and `git worktree add -b` fails on the existing
branch (FEAT-806 run: TASK-5210 a1..a3 kept, re-dispatch collided).

### Goals

- G1: `coder_record_review` and `coder_record_feedback` work through the MCP adapter (validated
  model instance) AND when called directly with a plain dict.
- G2: a re-dispatch of a task within one execution allocates an attempt number whose branch and
  sub-worktree path are both free, so it never collides with a kept attempt; attempt numbers stay
  monotonic per (task, execution).

### Non-Goals

- Reclaiming or deleting kept attempt worktrees (they stay for inspection/repair; `coder_cleanup`
  still owns reclamation).
- Changing `AbstractTool._shallow_dump` (its nested-model behavior is intentional).
- Changing the `<task>.a<N>.<exec-hex>` naming scheme or the parsers that read it
  (`_merged_attempt_branch`, `inspection.py`).

---

## 2. Architectural Design

### B1 — accept model or mapping

In `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/toolkit.py` replace
`CoderReview(**review)` with `CoderReview.model_validate(review)` and
`CoderFeedback(**feedback)` with `CoderFeedback.model_validate(feedback)`. Pydantic v2
`model_validate` accepts either an instance of the model (returned as-is, revalidation per model
config) or a mapping, so both call paths work. Update the parameter annotations to
`Union[CoderReview, Dict[str, Any]]` / `Union[CoderFeedback, Dict[str, Any]]` only if needed for
type correctness; the advertised MCP schema comes from `arg_models`, not the signature.

### B2 — skip occupied attempt slots

Add a private helper on `SddCoderEngine` that, given `(ctx, task_id, requested_attempt,
execution_id)`, returns the smallest attempt number `n >= requested_attempt` that is also greater
than every attempt number already used for this task+execution, such that neither
`_branch_for(ctx, task_id, n, execution_id)` exists as a local branch nor
`_path_for(ctx, task_id, n, execution_id)` exists on disk. "Already used" is discovered from git
refs (same prefix/`exec-hex` filtering as `_merged_attempt_branch`) plus the engine's in-memory
`_branch_attempts`. `_run_attempt` calls it once at entry, before deriving `manager`, `branch` and
`path`, and uses the returned number everywhere it used `attempt` (including the returned
`AttemptRecord`). The happy path (no leftovers) keeps `attempt` unchanged, so first-run numbering
is identical to today.

Native `prepare_native` reservations already reuse an existing sub-worktree for a duplicate
reservation; they are out of scope.

---

## 3. Acceptance Criteria

- AC1: Executing the `coder_record_review` tool through `parrot.mcp.adapter.MCPToolAdapter` with a
  valid review payload reaches `SddCoderEngine.record_review` with a `CoderReview` instance (no
  `argument after ** must be a mapping` error).
- AC2: Same for `coder_record_feedback` → `SddCoderEngine.record_feedback` with a `CoderFeedback`.
- AC3: Calling both toolkit methods directly with a plain dict still works.
- AC4: When a branch `<feature>--<task>-a1-<exec-hex>` (and/or its pool path) already exists for
  the execution, `_run_attempt(..., attempt=1, ...)` creates attempt 2 (or the next free number
  above every used one) instead of failing, and the returned `AttemptRecord.attempt` and branch
  reflect that number.
- AC5: With no leftovers, `_run_attempt(..., attempt=1)` still uses attempt 1.
- AC6: Existing `test_toolkit.py`, `test_feedback.py`, `test_engine_dispatch.py` stay green.

---

## 4. Task Breakdown (guidance for /sdd-task)

1. B1 — toolkit record tools accept validated models (`toolkit.py` + tests). Discovered-from
   `issue:3b913ffd77cd`.
2. B2 — monotonic free attempt slot in `_run_attempt` (`engine.py` + tests). Discovered-from
   `issue:3b913ffd77cd`.

The two tasks touch different files and can run in parallel.

---

## 5. Risks

- R1: `model_validate` on an instance with `revalidate_instances='never'` (default) returns the same
  object — intended.
- R2: The free-slot scan adds one `git branch --list` per attempt; negligible next to a dispatch.
- R3: Ledger two-key close: the issue's `files` list only `coder_reviews.py`, while the fix lands in
  `toolkit.py`/`engine.py`. Closing the issue therefore needs a human/`/sdd-done` decision; the fix
  does not modify `coder_reviews.py` just to satisfy the diff key.

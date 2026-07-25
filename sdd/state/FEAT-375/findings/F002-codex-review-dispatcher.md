# F002 — Codex code review exists but is WRITE-ENABLED, not adversarial/advisory (queries Q002, Q005)

**Type**: read + wiki (TASK-1695, score 1.00; sdd/specs/new-codereviewers.spec.md FEAT-270)
**Citations**:
- `packages/ai-parrot/src/parrot/flows/dev_loop/code_review.py:35-127` — `AbstractCodeReviewDispatcher` + `CodeReviewDispatcherFactory`
- `packages/ai-parrot/src/parrot/flows/dev_loop/code_review.py:151-168` — `CodexCodeReviewDispatcher` registered as `"codex"`
- `packages/ai-parrot/src/parrot/flows/dev_loop/models.py:797-809` — `CodexCodeReviewProfile`

Facts:
- `CodexCodeReviewDispatcher` uses `sandbox="workspace-write"`, `approval_policy="on-request"` — the reviewer FIXES issues and COMMITS to the worktree branch (FEAT-270 design).
- Output contract: `CodeReviewVerdict {passed, findings[], summary, files_modified[]}` (models.py:760-775).
- Degrade-on-infra-error: any dispatch failure returns `passed=True` + nit finding (code_review.py:85-97).
- Selected via `DEV_LOOP_CODEREVIEW_AGENT` env ("claude-code" default | "codex" | "gemini"), `conf.py:927-932`.
- QANode runs a review→fix→rerun loop (TASK-1697).

**Gap vs. request**: the source asks for an *adversarial second-opinion* reviewer — advisory-only, read-only sandbox, neutral brief (diff + requirement + question, never the primary agent's reasoning), findings triaged CONFIRM/REJECT/ESCALATE by the primary loop rather than auto-applied. No such mode exists.

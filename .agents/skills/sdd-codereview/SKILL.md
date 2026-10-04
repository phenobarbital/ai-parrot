---
name: sdd-codereview
description: Code review a completed SDD task against acceptance criteria, code quality, security, and adversarial cross-checks.
---

# SDD Code Review

## Full procedure and Codex adaptations

Before executing, read the [full sdd-codereview procedure](../../../.claude/commands/sdd-codereview.md)
and the [Codex adaptation contract](../../../docs/sdd/CODEX.md#codex-adaptation-contract).
Follow the full procedure for details omitted from this summary. The adaptation
contract and the Codex-specific instructions below override Claude runtime syntax
and legacy shell examples; retain all workflow gates and evidence requirements.

Use this skill when the user asks to review a completed SDD task, run `sdd-codereview`, or perform an adversarial code review on completed task artifacts.

**Mandatory Deferred Findings Table**: Every CONFIRMED 🔴/🟡 finding not fixed in-review MUST be
attempted with `wikitoolkit ledger open` and listed in the report's Deferred findings table. The
ledger intentionally resolves to the main checkout. If a sandbox makes it read-only, do not request
broader filesystem access or create a worktree-local ledger; list the full finding with
`(NOT filed: shared ledger is read-only)`. Reviews with unfiled confirmed findings and an empty
Deferred table are invalid.

## Purpose

Reads the task file from `sdd/tasks/completed/`, loads all referenced source files and the parent spec, applies code review criteria (Correctness, Code Quality, Performance, Security, Documentation, Testing), and produces a structured review report.

## Guardrails

- Reads strictly completed tasks from `sdd/tasks/completed/`.
- Verify the chain of thought and code anchors: check actual files, classes, methods, and line ranges.
- Treat reviewer second-opinions as advisory: confirm, reject, or escalate each finding.
- Never report an unverifiable claim as a finding.

## Workflow

## Durable review boundary (FEAT-584)
Before feature review, settle owned attempts and supervised validations and close execution.
Unknown activity is a blocker, never evidence of an idle worktree. Persist the checkpoint,
record actual supported compaction outcome once per checkpoint/context, revalidate and start
a fresh reviewer. Unsupported contexts continue from checkpoint with an explicit reason.
Keep review criteria, adversarial checks, full lint, integration validation and ledger gates.
Changes after checkpoint require new hashes/evidence and invalidate old review coverage.
For sdd-done, preserve existing verification stamping, approval and push/merge policy;
do not run task closure again on base_branch and do not clean worktrees with unknown activity.

1. Resolve task:
   - Accept full path, `TASK-NNN`, or slug.
   - Match against `sdd/tasks/completed/TASK-*.md`.
2. Load context:
   - Read the task markdown file.
   - Read the referenced spec in `sdd/specs/`.
   - Read every file in the task's "Files to Create/Modify" section.
   - Read the Acceptance Criteria and Completion Note.
3. Review criteria:
   - **Correctness & Logic**: Acceptance criteria satisfaction, edge cases, error paths.
   - **Code Quality**: DRY, SOLID, abstraction seams, framework patterns.
   - **Performance**: N+1 queries, async blocking calls, algorithmic efficiency.
   - **Security**: Input validation, SQL/injection risks, credentials, auth.
   - **Documentation**: Docstrings, type annotations, clarity.
   - **Testing**: Test coverage against criteria, assertions, failure modes.
4. Adversarial cross-check:
   - Run external reviewer (`codex exec review`) or spawn a dedicated read-only subagent.
   - Supply only neutral brief: requirements, diff/commit, question.
   - Synthesize agreements and disagreements.
5. Generate report:
   - Summary, Critical, Major, Minor/Suggestions.
   - **Deferred Findings table**: Every CONFIRMED 🔴/🟡 finding not fixed in-review MUST be attempted with `wikitoolkit ledger open` and listed in this table. If the shared ledger is read-only, retain the full finding with `(NOT filed: shared ledger is read-only)`.
   - Acceptance Criteria check table.
   - Adversarial cross-check disposition table.
   - Positive highlights.
6. Optional save:
   - Save to `sdd/reviews/TASK-<NNN>-review.md` if requested.

## References

- `sdd/tasks/completed/`
- `sdd/tasks/index/<feature>.json`
- `sdd/WORKFLOW.md`

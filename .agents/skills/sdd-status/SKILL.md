---
name: sdd-status
description: Aggregate task state across per-spec indexes and display the SDD task board.
---

# SDD Status

Use this skill when the user asks for SDD status, runs `sdd-status`, or wants to see the task board.

Invocation: `sdd-status [<feature-name>] [--project <project>] [--tag <tag>]`.

## Purpose

Aggregate task states across all per-spec indexes (`sdd/tasks/index/*.json`) and display a clear, human-friendly status report.

## Guardrails

- Read-only: never modifies any files.
- Honors the four exact status states: `in-progress`, `pending`, `done-with-issues`, `done`.
- Displays orphans from `_orphans.json` in a dedicated panel.

## Workflow

1. Load all per-spec indexes:
   - Glob `sdd/tasks/index/*.json`.
   - Filter by feature slug or `FEAT-NNN` if argument is provided.
   - Optional `--project` / `--tag` (FEAT-576): get matching spec paths from `python -m scripts.sdd.doc_taxonomy --kind spec --paths-only ...` and keep only indexes whose `spec` is listed.
1.5. Discover worktree state (FEAT-582):
   - Run `python -m scripts.sdd.worktree_status --json` to get worktree reports.
   - Build a map from `feature_slug` → `WorktreeReport`.
   - For features with a worktree (`index_found: true`): use the worktree's `tasks[]` instead of the dev-branch index. Label with `(from worktree: <branch>)`.
2. Group tasks by feature and status:
   - `in-progress` (🔄)
   - `pending` (⏳)
   - `done-with-issues` (⚠️)
   - `done` (✅)
3. Highlight blockers:
   - Identify pending tasks blocked by incomplete dependencies.
4. Surface orphans:
   - If `sdd/tasks/index/_orphans.json` has entries, display them in an Unowned Tasks panel.
5. Print summary totals (done, done-with-issues, in-progress, pending, total).
6. Show worktree summary (FEAT-582):
   - List all SDD worktrees with: name, branch, task progress (N/M done), health flags, ready-for-done.
   - Non-SDD worktrees show health only, no task counts.
   - Flag `✅ Ready for /sdd-done` when `ready_for_done: true`.
   - Include worktree count in the summary line.

## References

- `sdd/tasks/index/*.json`
- `sdd/WORKFLOW.md`
- `scripts/sdd/worktree_status.py` (FEAT-582)

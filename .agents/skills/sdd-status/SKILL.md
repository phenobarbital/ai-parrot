---
name: sdd-status
description: Aggregate task state across per-spec indexes and display the SDD task board.
---

# SDD Status

## Full procedure and Codex adaptations

Before executing, read the [full sdd-status procedure](../../../.claude/commands/sdd-status.md)
and the [Codex adaptation contract](../../../docs/sdd/CODEX.md#codex-adaptation-contract).
Follow the full procedure for details omitted from this summary. The adaptation
contract and the Codex-specific instructions below override Claude runtime syntax
and legacy shell examples; retain all workflow gates and evidence requirements.

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
1.5. Reconcile with worktree state (FEAT-582):
   - Run `python -m scripts.sdd.worktree_status --reconcile --json` — it merges each per-spec index on this branch with its worktree's index and returns one `ReconciledFeature` per feature. Use its `tasks[]` for the board.
   - Never prefer one side: the merge is **monotonic** — a worktree may only advance a task (`pending` < `in-progress` < `done` = `done-with-issues`), never roll it back. Ties between the two terminal states keep dev's value; worktree-only tasks are appended; `index_found: false` contributes nothing.
   - Label the feature header from the flags: `worktree_ahead` → `(worktree ahead: <branch>)`; `worktree_only` → `(worktree only: <branch>)`; `worktree_stale` → `(stale worktree: <branch> — dev is ahead)`, plus `/remove-worktree` when `dev_closed` is also true. No flag, no label.
   - A stale worktree must never make a finished feature print as pending (the FEAT-561 failure).
   - Run `python -m scripts.sdd.worktree_status --json` too for the health data the worktree panel (step 6) needs.
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
   - Flag `✅ Ready for /sdd-done` when `ready_for_done: true`, and `🧹 Stale — dev is ahead` when the feature's reconciled entry has `worktree_stale: true`.
   - Include worktree count in the summary line.

## References

- `sdd/tasks/index/*.json`
- `sdd/WORKFLOW.md`
- `scripts/sdd/worktree_status.py` (FEAT-582) — `--reconcile` for the board, `--json` for the health panel

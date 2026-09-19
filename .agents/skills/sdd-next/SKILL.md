---
name: sdd-next
description: Suggest next unblocked SDD tasks to assign across per-spec indexes.
---

# SDD Next

Use this skill when the user asks what task to work on next, runs `sdd-next`, or needs unblocked SDD assignments.

Invocation: `sdd-next`.

## Purpose

Inspect all per-spec indexes (`sdd/tasks/index/*.json`), identify tasks whose dependencies are satisfied, and suggest optimal work assignments with worktree commands.

## Guardrails

- Read-only: does not modify index or task files.
- Skip `sdd/tasks/index/_orphans.json` (orphans are displayed only by `sdd-status`).
- Only suggest tasks with `status: "pending"` where all `depends_on` tasks are `"done"`.

## Workflow

1. Aggregate tasks:
   - Read all `sdd/tasks/index/*.json` excluding `_orphans.json`.
   - Optional `--project` / `--tag` (FEAT-576): get matching spec paths from `python -m scripts.sdd.doc_taxonomy --kind spec --paths-only ...` and keep only indexes whose `spec` is listed.
2. Inspect worktrees:
   - Run `git worktree list` to match active feature worktrees.
   - Additionally run `python -m scripts.sdd.worktree_status --json` for task-level progress and `ready_for_done` flags.
3. Compute unblocked tasks:
   - Check `status == "pending"`.
   - Verify every ID in `depends_on` has `status == "done"`.
4. Group & annotate:
   - Tasks with active worktree: suggest running `sdd-start TASK-NNN` inside the worktree.
   - Tasks needing new worktree: provide `git worktree add` command.
   - Parallel tasks: indicate `parallel: true` tasks that can run concurrently.
   - For features with `ready_for_done: true`: suggest `/sdd-done` instead of new tasks.
   - For features with worktree progress: annotate header with `(N/M done in worktree)`.
5. Sort:
   - Priority (high -> medium -> low), then effort (S -> M -> L -> XL).
6. Present list and show currently in-progress tasks.
7. (FEAT-566, best-effort) Show ready ledger issues:
   - `wikitoolkit ledger ready 2>/dev/null || true`
   - list open, unclaimed issues (discovered work with no TASK-NNN yet)
   - each entry suggests `sdd-fix <id>` (FEAT-572: plan-fix routes the issue's group to the Fast or SDD lane)
   - a missing/unbuilt ledger prints nothing here; never fatal, never blocks the rest of `sdd-next`

## References

- `sdd/tasks/index/*.json`
- `sdd/WORKFLOW.md`

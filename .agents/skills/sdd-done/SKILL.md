---
name: sdd-done
description: Verify a completed SDD feature worktree, check for merge blockers, snapshot ledger issues, stamp task verification, push or open the PR, optionally sync hotfixes down, and clean the worktree.
---

# SDD Done

Use this skill when the user asks to run `sdd-done`, close a feature, push an
SDD worktree, open the feature PR, or clean up a completed SDD worktree.

Codex invocation: `$sdd-done FEAT-NNN [--dry-run] [--merge] [--force] [--resolve-jira] [--sync-down]`.

## Purpose

Verify evidence in the feature worktree, check for merge blockers scoped to
the current feature, snapshot ledger issues on base branch, stamp verification
on the feature branch, push it, open or describe the PR, and remove the worktree
when safe.

## Guardrails

- Run from the main repo, not inside `.claude/worktrees/`.
- Must be on the spec's `base_branch`.
- Do not modify the spec.
- Do not mark tasks done unless there is evidence in the worktree.
- Always show a verification report before writing closeout state.
- Hotfixes never merge directly to `main`.
- Hotfixes never push directly to `main`.
- For hotfixes, print a manual `gh pr create --base main` command instead of
  creating or merging the PR automatically.
- Use `--sync-down` only after the hotfix PR has merged to `main`.
- Use `--sync-dev` only as a deprecated alias for `--sync-down`.
- Merge gate checks apply only to `--merge` flag, not PR flow.
- Ledger snapshots use throwaway worktrees and never modify active worktrees.
- Hotfixes skip ledger snapshots.
- Bounded retry for rejected pushes (max 3 attempts).

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

1. Resolve feature:
   - scan `sdd/tasks/index/*.json`, excluding `_orphans.json`
   - match `feature_id`, numeric suffix, exact feature slug, or slug substring
   - read `feature`, `feature_id`, `spec`, `type`, and `base_branch`
2. Verify branch and location:
   - current path must not contain `.claude/worktrees/`
   - current branch must equal `base_branch`
3. Locate worktree:
   - prefer `git worktree list` match for `feat-<FEAT-ID>` or hotfix branch
   - if missing, check remote/local branches and report next steps
4. Gather evidence per task:
   - commits matching task ID or slug in the worktree
   - files listed in each task's "Files to Create / Modify" table exist in the
     worktree
   - do not rerun the whole test suite here; tests should have run during task
     execution
5. Classify:
   - `VERIFIED`: commit found and files exist
   - `PARTIAL`: commit found but files are missing
   - `NO EVIDENCE`: neither commits nor files support completion
6. Present verification report:
   - worktree
   - branch
   - commit count
   - task count by status
   - task-by-task evidence
7. Respect flags:
   - `--dry-run`: stop after the report
   - `--force`: allow forced closeout with partial/no evidence noted
   - otherwise ask before closing if any task is not verified
8. Stamp verification in the worktree branch (closing any task the lane left open):
   - clear staging first (the close step below stages its own moves)
   - verified is not closed: for each task being closed whose file is still in
     `sdd/tasks/active/` or whose index status is not `done`/`done-with-issues`
     (lanes such as `/sdd-fix` commit code without closing), run
     `scripts/sdd/close_task.sh <TASK-ID> <feature-slug> <verification>` inside
     the worktree — never on `base_branch` (FEAT-414); leave tasks the lane
     already closed untouched
   - set each task `verification` to `verified`, `partial`, or `forced` in
     `sdd/tasks/index/<feature>.json` inside the worktree
   - set feature `completed_at` only when all tasks are done
   - run `scripts/sdd/heal_orphans.sh <feature-slug>` inside the worktree
     (PR flow and `--merge` alike)
   - stage only the index and this feature's task files, verify cached names
   - commit `sdd: close tasks for FEAT-NNN - <feature-slug>`
9. Push feature branch:
   - `git -C <worktree> push origin <branch>`
10. Check merge blockers (feature flows only):
    - If `--merge` flag is set and not a hotfix, run `wikitoolkit ledger blockers <FEAT-ID>`
    - The command prints plain-text blocker lines (never JSON) and exits non-zero
      exactly when blockers exist — gate on the **exit code**, not on parsing its output
    - If blockers found and not `--force`, refuse merge and list the blockers
      (`wikitoolkit ledger acknowledge <ISSUE-ID> --reason "..." --actor human:<name>`
      is how a human resolves one)
    - If `--force`, warn but proceed with merge

11. Snapshot ledger issues (feature flows only):
    - For features (not hotfixes), `git fetch origin <BASE_BRANCH>` then create a
      throwaway detached worktree at `origin/<BASE_BRANCH>` (`git worktree add --detach`)
    - Run `wikitoolkit ledger export` there; only when its output contains `(changed)`:
      `git add sdd/ledger/issues.jsonl`, commit `sdd: ledger snapshot for <FEAT-ID>`,
      and `git push origin HEAD:<BASE_BRANCH>`
    - On a rejected push, `git fetch` + `git reset --hard origin/<BASE_BRANCH>` inside
      the throwaway worktree only, re-export, commit, push again — up to 3 attempts,
      then warn and continue without failing `/sdd-done`
    - Always `git worktree remove --force` the throwaway worktree afterward
    - Skip the snapshot entirely for hotfixes

12. Integrate:
    - If `base_branch == main`, refuse automatic merge or PR creation. Print
      the manual hotfix PR command:
      `gh pr create --base main --head <branch> --title "<title>" --body "<verification summary>"`.
    - If feature and no `--merge`, run `gh pr create --base <base_branch> --head <branch>`.
    - If `gh` is missing or not authenticated, print the manual command.
    - If feature and `--merge`, merge into `base_branch`, run
      `scripts/sdd/heal_orphans.sh <feature-slug>`, commit any staged orphan
      cleanup, and push `base_branch`.
11. Hotfix sync-down:
    - only with `--sync-down` or deprecated `--sync-dev`
    - verify feature branch is ancestor of `origin/main`
    - merge into `staging`, abort cleanly on conflict
    - merge into `dev`, abort cleanly on conflict
    - leave user on `main`
12. Resolve Jira if requested:
    - find Jira key in spec or proposal metadata
    - prefer Jira MCP tools if available
    - fallback to configured Jira environment variables
    - transition to Done, Resolved, Ready for UAT, Complete, or Close
    - report missing credentials or missing transitions without failing closeout
13. Cleanup:
    - remove the worktree only after successful push/PR or merge path
    - if uncommitted changes exist in the worktree, ask before force removal
    - prune stale metadata if the worktree was already removed
    - delete local feature branch only when safe and merged/pushed

## Output

Report:

```text
FEAT-NNN - <title>: <closed>/<total> tasks closed
Branch pushed: <branch>
PR opened: <url> or manual command printed
Worktree removed: .claude/worktrees/<name>
Jira: <key> -> Done, when requested and successful
```

## References

- `sdd/tasks/index/<feature>.json`
- `sdd/tasks/active/`
- `sdd/tasks/completed/`
- `scripts/sdd/sdd_meta.py`
- `scripts/sdd/heal_orphans.sh`
- `sdd/WORKFLOW.md`


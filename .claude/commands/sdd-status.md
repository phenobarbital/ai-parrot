---
model: haiku
---

# /sdd-status — SDD Task Board

Aggregate task state across all per-spec indexes (`sdd/tasks/index/*.json`)
and print a human-friendly status report.

## Usage
```
/sdd-status
/sdd-status <feature-name>
/sdd-status --project <project> [--project …] [--tag <tag> …]
```

## Guardrails
- If `sdd/tasks/index/` is empty or does not exist, inform the user and suggest running `/sdd-task` first.
- Read-only — do not modify any files.
- Show orphans (tasks rescued by the migration script with no feature attribution) in a dedicated panel — they are tracked but never suggested as work by `/sdd-next`.

## Steps

### 1. Read All Per-Spec Indexes (FEAT-145)

Glob `sdd/tasks/index/*.json` and load each per-spec index. The header
fields (`feature`, `feature_id`, `spec`, `type`, `base_branch`,
`completed_at`) drive the per-feature panel; the `tasks[]` array drives
the task lines.

```bash
ALL=$(jq -s '.' sdd/tasks/index/*.json)
```

If a `<feature-name>` filter is provided, show only the index whose
`feature` slug matches (substring) or whose `feature_id` matches exactly.

If `--project` / `--tag` is given (FEAT-576), resolve the matching specs from
their frontmatter — the index header does not carry taxonomy — and keep only
indexes whose `spec` is in the list (AND across flags, OR within a repeated
flag; `_orphans.json` is excluded because it has no spec):

```bash
SPECS=$(python -m scripts.sdd.doc_taxonomy --kind spec --paths-only --project <p> --tag <t>)
ALL=$(jq -s --arg specs "$SPECS" '[.[] | select(.spec as $s | ($specs | split("\n")) | index($s))]' sdd/tasks/index/*.json)
```

### 1.5. Reconcile With Worktree State (FEAT-582)

A feature's tasks can be ahead **in the worktree** (`sdd-worker` updates the
worktree's copy of the index; `dev` only learns about it when `/sdd-done`
merges), and they can be ahead **on dev** (the worktree was branched before
`/sdd-task`/`/sdd-start` stamped the index, or it was left behind after the
feature merged). So do **not** prefer one side — reconcile them:

```bash
FEATURES=$(python -m scripts.sdd.worktree_status --reconcile --json 2>/dev/null || echo "[]")
WT_REPORTS=$(python -m scripts.sdd.worktree_status --json 2>/dev/null || echo "[]")   # health, for §5
```

`--reconcile` merges every per-spec index on this branch with its worktree's
index and returns one `ReconciledFeature` per feature. The merge rule is
deterministic and **monotonic — a worktree may only advance a task, never roll
it back**:

- The worktree status wins only when it ranks strictly higher
  (`pending` < `in-progress` < `done` = `done-with-issues`).
- `done` and `done-with-issues` tie, and a tie keeps dev's value — the
  merged record is authoritative about which terminal state a task reached.
- Tasks that exist only in the worktree index are appended (they were
  generated in-worktree and never merged).
- A worktree with `index_found: false` contributes nothing.

Use `FEATURES` for the task lines in §2 (its `tasks[]` is already merged;
each task carries `source: "dev" | "worktree"`), and label the feature header
from the flags:

- `worktree_ahead: true` → `(worktree ahead: <worktree_branch>)`
- `worktree_only: true` → `(worktree only: <worktree_branch>)` — the spec and
  tasks exist only inside the worktree, nothing on this branch yet
- `worktree_stale: true` → `(stale worktree: <worktree_branch> — dev is ahead)`;
  when `dev_closed` is also true the feature is finished and the worktree is a
  leftover that `/remove-worktree` can drop
- no flag → no label; the dev index and the worktree agree

Never let a `worktree_stale` feature print as pending/not-started: that is the
FEAT-561 failure this rule exists to prevent — a worktree left over from a
feature that merged on 2026-09-16 reported all 10 of its tasks as pending.

### 2. Group and Display

The task `status` field has **exactly four** valid values — match each
task's status literally against this set; never fall through to a
default bucket for a status string you don't recognize:

- `"pending"` → ⏳ Pending
- `"in-progress"` → 🔄 In-Progress
- `"done"` → ✅ Done
- `"done-with-issues"` → ⚠️ Done (with issues) — a task `sdd-worker`
  completed but flagged after being unable to satisfy every acceptance
  criterion within scope (see its Completion Note for details). This is
  a completed state, NOT pending — never group it under ⏳ Pending.

Group tasks by status (in-progress → pending → done-with-issues → done)
and by feature. Print:

```
📊 SDD Task Board
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Feature: <feature>
Spec: sdd/specs/<feature>.spec.md
Projects: <a, b> · Tags: <x, y>

  🔄 In-Progress
     TASK-<NNN> — <title>  [<priority>/<effort>]  assigned: <who>

  ⏳ Pending
     TASK-<NNN> — <title>  [<priority>/<effort>]  blocked-by: <deps or —>

  ⚠️ Done (with issues)
     TASK-<NNN> — <title>  — see Completion Note in the task file

  ✅ Done
     TASK-<NNN> — <title>

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Summary: <N> done / <N> done-with-issues / <N> in-progress / <N> pending / <N> total | <W> worktrees (<R> ready for /sdd-done)
```

### 3. Highlight Blockers
If any pending tasks are blocked (deps not done), add a blockers section:
```
⚠ Blockers:
  TASK-<NNN> waiting on TASK-<X> (<status>)
```

### 4. Show Orphan Tasks (FEAT-145)

If `sdd/tasks/index/_orphans.json` exists and has any tasks, append a
final panel after the main board:

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
⚠ Unowned tasks (no feature attribution):

  TASK-<NNN> — <title>  [<status>]

These were rescued by the FEAT-145 migration but lack a feature link.
Consider relocating them via /sdd-task or removing them.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

If `_orphans.json` does not exist or has an empty `tasks[]` array, skip this panel silently.

### 5. Show Worktree Summary (FEAT-582)

After the orphan panel, show a worktree health panel for all SDD worktrees
from the `WT_REPORTS` data:

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🌳 Worktrees (N active):

  feat-FEAT-550-token-budget-bedrock
    Branch: feat-FEAT-550-token-budget-bedrock
    Tasks: 14/14 done  |  Health: clean  |  ✅ Ready for /sdd-done

  feat-FEAT-582-sdd-status-worktrees
    Branch: feat-FEAT-582-sdd-status-worktrees
    Tasks: 2/5 done  |  Health: 3 dirty, 1 unpushed  |  🔄 In progress

  chore-ruff-config  (non-SDD)
    Branch: chore-ruff-config
    Health: clean
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

Health flags:
- `clean` = dirty_count == 0 AND unpushed_count == 0
- `N dirty` = dirty_count > 0
- `N unpushed` = unpushed_count > 0
- `N live processes` = live_process_count > 0

Ready-for-done flag:
- `✅ Ready for /sdd-done` when `ready_for_done: true`
- `🔄 In progress` when tasks are not all done
- `⚠️ Done but needs cleanup` when all done but dirty/unpushed
- `🧹 Stale — dev is ahead` when the feature's reconciled entry (§1.5) has
  `worktree_stale: true`; add `— feature already closed, /remove-worktree`
  when `dev_closed` is also true

Non-SDD worktrees (those with no parsed feature_id) show health only, no task
counts.

Update the Summary line to include:
```
Summary: <N> done / ... / <N> total | <W> worktrees (<R> ready for /sdd-done)
```

## Reference
- Worktree reconciliation: `scripts/sdd/worktree_status.py` (`--reconcile`)
- Per-spec index files: `sdd/tasks/index/*.json`
- Orphans file: `sdd/tasks/index/_orphans.json` (only present if migration found unattributable tasks)
- SDD methodology: `sdd/WORKFLOW.md`

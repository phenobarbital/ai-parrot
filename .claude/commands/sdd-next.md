---
model: haiku
---

# /sdd-next — Suggest Next Unblocked SDD Tasks

Aggregate tasks across all per-spec indexes (`sdd/tasks/index/*.json`),
identify unblocked tasks, and suggest assignments. Shows worktree context
to help the user decide where to run each task.

## Usage
```
/sdd-next
/sdd-next --project <project> [--tag <tag>]     # FEAT-576 taxonomy filter
```

## Guardrails
- Only suggest tasks with status `"pending"` and all dependencies `"done"`.
- If `sdd/tasks/index/` is empty or does not exist, inform the user and suggest running `/sdd-task` first.
- **Skip `sdd/tasks/index/_orphans.json`** — orphans have no resolvable feature; they are surfaced by `/sdd-status`, never suggested by `/sdd-next`.
- Sort by priority (high → medium → low), then by effort (S → M → L → XL).

## Steps

### 1. Read All Per-Spec Indexes (FEAT-145)

Glob `sdd/tasks/index/*.json` (excluding `_orphans.json`) and aggregate
the `tasks[]` arrays:

```bash
TASKS=$(jq -s '[.[] | select(.feature != "_orphans") | .tasks[]]' sdd/tasks/index/*.json)
```

If `--project` / `--tag` is given (FEAT-576), resolve the matching specs and
keep only tasks whose index's `spec` is in the taxonomy list (AND across flags,
OR within a repeated flag):

```bash
SPECS=$(python -m scripts.sdd.doc_taxonomy --kind spec --paths-only --project <p> --tag <t>)
TASKS=$(jq -s --arg specs "$SPECS" '[.[] | select(.feature != "_orphans") | select(.spec as $s | ($specs | split("\n")) | index($s)) | .tasks[]]' sdd/tasks/index/*.json)
```

If no per-spec index files exist, suggest the user run `/sdd-task` first.

### 2. Detect Active Worktrees
Run `git worktree list` to identify which feature worktrees are currently active.
Map each active worktree to its feature ID by matching the worktree name pattern
`feat-<FEAT-ID>-<slug>` or `task-<TASK-ID>-<slug>`.

Additionally, call the worktree status library for richer data:
```bash
WT_REPORTS=$(python -m scripts.sdd.worktree_status --json 2>/dev/null || echo "[]")
```
Build a lookup from `feature_slug` → `WorktreeReport`. This provides task progress
counts and `ready_for_done` flags that the bare `git worktree list` cannot give.

### 3. Compute Unblocked Tasks
For each task with `status: "pending"`:
- Check that every task in `depends_on` has `status: "done"`.
- If all deps are done (or `depends_on` is empty) → task is **unblocked**.

### 4. Group and Annotate
Group unblocked tasks by feature. For each task, determine:
- **Has active worktree**: the feature already has a worktree running → suggest
  `/sdd-start TASK-<NNN>` inside that worktree session.
- **Needs new worktree**: no active worktree for this feature → show the
  `git worktree add` command.
- **Parallel task**: marked `parallel: true` → can use its own worktree.

For features with a `WorktreeReport`:
- If `ready_for_done: true`: do NOT suggest new tasks. Instead show:
  ```
  FEAT-550 — Token Budget Bedrock
    ✅ All 14 tasks done — ready for /sdd-done FEAT-550
  ```
- If tasks are partially done: annotate the feature header with progress:
  ```
  FEAT-582 — SDD Status Worktrees  (3/5 done in worktree)
    🟢 Active worktree: feat-FEAT-582-sdd-status-worktrees
  ```

The progress count comes from: `done_count = sum(1 for t in report.tasks if t.status in ("done", "done-with-issues"))`.

### 5. Sort and Present
Sort unblocked tasks by priority, then effort. Output:

```
📋 Next unblocked SDD tasks:

FEAT-007 — Ontological RAG
  🟢 Active worktree: feat-007-ontology-rag
  1. TASK-003 — GraphStore           [high / M]
     Depends-on: TASK-001 ✅, TASK-002 ✅
     → /sdd-start TASK-003  (run inside existing worktree)

FEAT-008 — MCP Security Layer
  🔵 No worktree — create one:
     git worktree add -b feat-008-mcp-security .claude/worktrees/feat-008-mcp-security HEAD
     cd .claude/worktrees/feat-008-mcp-security
  2. TASK-010 — SecurityLayer base   [high / M]
     Depends-on: none
     → /sdd-start TASK-010

FEAT-009 — Security Toolkits
  ⚡ Parallel tasks (can run in separate worktrees):
  3. TASK-042 — Prowler Toolkit      [medium / S]
     git worktree add -b task-042-prowler .claude/worktrees/task-042-prowler HEAD
     → cd .claude/worktrees/task-042-prowler && /sdd-start TASK-042
  4. TASK-043 — Trivy Toolkit        [medium / S]
     git worktree add -b task-043-trivy .claude/worktrees/task-043-trivy HEAD
     → cd .claude/worktrees/task-043-trivy && /sdd-start TASK-043
```

If no tasks are unblocked:
```
⚠ No unblocked tasks found.
  All pending tasks are waiting on: <list of blocking task IDs>
  Run /sdd-status for the full board.
```

### 6. Show In-Progress Summary
After the unblocked list, show a brief summary of what's currently running:

```
🔄 In progress:
  TASK-002 — OntologyParser [in feat-007-ontology-rag]
  TASK-021 — Trivy Toolkit  [in task-021-trivy-toolkit]
```

### 7. Show Ready Ledger Issues (FEAT-566, best-effort)

Alongside unblocked tasks, surface open, unclaimed ledger issues — discovered
work that has no `TASK-<NNN>` yet. Never fatal (a missing/unbuilt ledger
prints nothing here, it does not block the rest of `/sdd-next`):

```bash
wikitoolkit ledger ready 2>/dev/null || true
```

```
🗒  Ready ledger issues (not yet promoted to a task):
  issue:3f8a1c9e [major] Leak in connection pool (bug)
     → /sdd-fix issue:3f8a1c9e        (plan-fix routes its group to the Fast or SDD lane; supersedes the deprecated --from-issue flow, FEAT-572)
```

If the command prints nothing (or fails), omit this section entirely —
do not print an empty header.

## Reference
- Per-spec index files: `sdd/tasks/index/*.json` (excluding `_orphans.json`)
- Active worktrees: `git worktree list`
- Worktree policy: `CLAUDE.md` (section "Worktree Policy")
- SDD methodology: `sdd/WORKFLOW.md`
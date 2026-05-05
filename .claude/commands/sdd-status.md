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

### 2. Group and Display
Group tasks by `status` (in-progress → pending → done) and by feature. Print:

```
📊 SDD Task Board
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Feature: <feature>
Spec: sdd/specs/<feature>.spec.md

  🔄 In-Progress
     TASK-<NNN> — <title>  [<priority>/<effort>]  assigned: <who>

  ⏳ Pending
     TASK-<NNN> — <title>  [<priority>/<effort>]  blocked-by: <deps or —>

  ✅ Done
     TASK-<NNN> — <title>

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Summary: <N> done / <N> in-progress / <N> pending / <N> total
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

## Reference
- Per-spec index files: `sdd/tasks/index/*.json`
- Orphans file: `sdd/tasks/index/_orphans.json` (only present if migration found unattributable tasks)
- SDD methodology: `sdd/WORKFLOW.md`

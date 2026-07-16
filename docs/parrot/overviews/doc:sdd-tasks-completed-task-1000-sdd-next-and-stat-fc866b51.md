---
type: Wiki Overview
title: 'TASK-1000: Update `/sdd-next` and `/sdd-status` to scan per-spec indexes'
id: doc:sdd-tasks-completed-task-1000-sdd-next-and-status-glob-indexes-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Implements **Module 7** of FEAT-145. Both commands are read-only —
---

# TASK-1000: Update `/sdd-next` and `/sdd-status` to scan per-spec indexes

**Feature**: FEAT-145 — SDD Flow Types and Per-Spec Index
**Spec**: `sdd/specs/sdd-flow-types-and-per-spec-index.spec.md`
**Status**: done
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-995
**Assigned-to**: unassigned

---

## Context

Implements **Module 7** of FEAT-145. Both commands are read-only —
they aggregate task state and present it. Today they read the
monolithic `sdd/tasks/.index.json`. After this task they glob
`sdd/tasks/index/*.json` and merge results.

`_orphans.json` is included in `/sdd-status` (as a separate "Unowned tasks" panel) but excluded from `/sdd-next` suggestions.

---

## Scope

### `.claude/commands/sdd-next.md` (rewrite §1)

- Read every JSON file matching `sdd/tasks/index/*.json` EXCEPT `_orphans.json`.
- Concatenate their `tasks[]` arrays in memory.
- Apply the existing "unblocked tasks" filter (status pending + all deps done).
- Annotate each task with its `feature` slug and `feature_id` (already present in each per-spec index header — the existing per-task entry has them too, but the header is the canonical source).
- Output format unchanged.

### `.claude/commands/sdd-status.md` (rewrite §1, §2)

- Same glob pattern.
- Group output by `feature` slug as today.
- Add a final "Unowned tasks" panel that reads `_orphans.json` (if present) and lists its tasks. This makes orphans visible without polluting the main board.

**NOT in scope**:
- Implementing a Python helper to do the aggregation (the markdown commands invoke `jq` or inline Python via Bash).
- Changing the visual format of the output.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `.claude/commands/sdd-next.md` | MODIFY | §1 read-source replacement |
| `.claude/commands/sdd-status.md` | MODIFY | §1 + §2 read-source; add orphans panel |

---

## Codebase Contract (Anti-Hallucination)

### Existing Files to Modify (verified line counts on 2026-05-05)

- `.claude/commands/sdd-next.md` — 88 lines. §1 at lines 17–18. §3 (compute unblocked) at 25–28.
- `.claude/commands/sdd-status.md` — 56 lines. §1 at 21–22. §2 at 24–44.

### Per-Spec Index Schema (relevant fields)

```json
{
  "feature": "<slug>",
  "feature_id": "FEAT-NNN",
  "tasks": [ {"id": "TASK-NNN", "status": "pending|in-progress|done", "depends_on": [...], ...} ]
}
```

### Aggregation Pattern (use `jq` — already required by `/sdd-done`)

```bash
ALL_TASKS=$(jq -s '
  [.[] | select(.feature != "_orphans") | .tasks[]]
' sdd/tasks/index/*.json)
```

For status, include orphans in a separate read:

```bash
ORPHAN_TASKS=$(jq '.tasks // []' sdd/tasks/index/_orphans.json 2>/dev/null || echo "[]")
```

### Does NOT Exist

- ~~`sdd/tasks/.index.json` post-migration~~ — still exists on disk per spec (preserved as historical artifact) but the new commands MUST ignore it.
- ~~Any aggregation helper script~~ — done inline via `jq` in command markdown.

---

## Implementation Notes

### `/sdd-next` rewritten §1

```markdown
### 1. Read All Per-Spec Indexes

Glob `sdd/tasks/index/*.json` (excluding `_orphans.json`) and merge the
`tasks[]` arrays:

```bash
TASKS=$(jq -s '[.[] | select(.feature != "_orphans") | .tasks[]]' sdd/tasks/index/*.json)
```

If `sdd/tasks/index/` is empty or does not exist, suggest the user run
`/sdd-task` first.
```

### `/sdd-status` rewritten §2 (Group and Display)

Keep the existing per-feature grouping. After the main board, add:

```markdown
### 4. Show Orphan Tasks (if any)

If `sdd/tasks/index/_orphans.json` exists and has tasks:

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
⚠ Unowned tasks (no feature attribution):

  TASK-NNN — <title>  [<status>]

These were rescued by the migration but lack a feature link.
Consider relocating them via /sdd-task or removing them.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```
```

### Key Constraints

- No removal of existing output sections.
- Both commands continue to be read-only.
- Use `jq` for JSON aggregation (already in tree usage).

---

## Acceptance Criteria

- [ ] `.claude/commands/sdd-next.md` references `sdd/tasks/index/*.json`.
- [ ] `.claude/commands/sdd-next.md` no longer references `sdd/tasks/.index.json`.
- [ ] `.claude/commands/sdd-next.md` excludes `_orphans.json` from suggestions.
- [ ] `.claude/commands/sdd-status.md` references `sdd/tasks/index/*.json`.
- [ ] `.claude/commands/sdd-status.md` documents the new "Unowned tasks" panel for orphans.
- [ ] Output format examples in both files remain (unchanged).

---

## Test Specification

```bash
grep -c "sdd/tasks/index/" .claude/commands/sdd-next.md       # ≥ 1
grep -c "sdd/tasks/index/" .claude/commands/sdd-status.md     # ≥ 1
grep -c "_orphans" .claude/commands/sdd-next.md               # ≥ 1 (exclusion)
grep -c "_orphans\|Unowned" .claude/commands/sdd-status.md    # ≥ 1
grep -c "sdd/tasks/.index.json" .claude/commands/sdd-next.md   # 0
grep -c "sdd/tasks/.index.json" .claude/commands/sdd-status.md # 0
```

All counts must match.

---

## Agent Instructions

1. Read both files end-to-end (they are short — 88 and 56 lines).
2. Use `Edit` for surgical updates.
3. Run the grep verifications.
4. Commit: `feat(sdd): TASK-1000 — sdd-next and sdd-status read per-spec indexes`.

---

## Completion Note

**Completed by**: Claude (Opus 4.7) — interactive session via `/sdd-start TASK-1000`
**Date**: 2026-05-05
**Notes**: Both read-only commands now glob `sdd/tasks/index/*.json` instead of reading the monolith. Output format preserved. All 6 acceptance grep checks pass.

**Changes per file:**
- **`sdd-next.md`**: §1 replaced with a `jq -s` aggregation pattern that excludes `_orphans.json`. Guardrail added: orphans are never suggested. Reference section updated.
- **`sdd-status.md`**: §1 rewritten to load each per-spec index header (feature/feature_id/type/base_branch/completed_at) and the tasks array. Filter logic now matches against the index header. New §4 "Show Orphan Tasks" appends the Unowned-tasks panel when `_orphans.json` has any entries. Reference section updated.

**Acceptance grep results:**
| Check                           | sdd-next.md | sdd-status.md |
|---------------------------------|-------------|---------------|
| `sdd/tasks/index/` refs (≥ 1)   | 6 ✅        | 7 ✅          |
| `sdd/tasks/.index.json` (= 0)   | 0 ✅        | 0 ✅          |
| `_orphans` / `Unowned` (≥ 1)    | 4 ✅        | 4 ✅          |

**Deviations from contract**: none.

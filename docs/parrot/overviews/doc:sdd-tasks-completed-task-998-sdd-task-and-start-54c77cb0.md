---
type: Wiki Overview
title: 'TASK-998: Rewrite `/sdd-task` and `/sdd-start` for per-spec index + base_branch'
id: doc:sdd-tasks-completed-task-998-sdd-task-and-start-per-spec-index-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Implements **Module 5** of FEAT-145. These two commands sit at the
---

# TASK-998: Rewrite `/sdd-task` and `/sdd-start` for per-spec index + base_branch

**Feature**: FEAT-145 — SDD Flow Types and Per-Spec Index
**Spec**: `sdd/specs/sdd-flow-types-and-per-spec-index.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-994, TASK-995, TASK-996
**Assigned-to**: unassigned

---

## Context

Implements **Module 5** of FEAT-145. These two commands sit at the
heart of the daily SDD loop. Today they hardcode `dev` and read/write
the monolithic `sdd/tasks/.index.json`. After this task they:

- Read the spec's YAML frontmatter to determine `base_branch`.
- Read tasks from `sdd/tasks/index/<feature>.json` instead of the monolith.
- Update the per-spec index in the worktree directly — no more `cd $REPO_ROOT && git checkout dev` dance (the merge in `/sdd-done` brings the index file along with the code).

> **Transition note**: tasks 994–997 of THIS feature were created via
> the OLD monolithic `/sdd-task`. After TASK-995 ran the migration,
> a per-spec index for FEAT-145 exists at
> `sdd/tasks/index/sdd-flow-types-and-per-spec-index.json`. From this
> task onward, the new `/sdd-start` reads from that file. Tasks 994–997
> are already `done`, so there is no inconsistency.

---

## Scope

### `.claude/commands/sdd-task.md` (rewrite §1, §4 step 4, §5)

- **§1 Verify Branch**: replace the "must be on dev" check with: read the spec's frontmatter via `parse()`, switch to `<base_branch>`, run `git pull --ff-only origin <base_branch>`. Abort on dirty tree or non-FF.
- **§4 step 4 (Index update)**: write `sdd/tasks/index/<feature>.json` instead of `sdd/tasks/.index.json`. Use the schema documented in the spec §2 Data Models. If the file already exists (created by TASK-995's migration), append the new tasks; otherwise create it fresh with `type` and `base_branch` carried from the spec frontmatter.
- **§5 Commit**: stage `sdd/tasks/index/<feature>.json` and `sdd/tasks/active/TASK-*.md`. Drop the staging of `sdd/tasks/.index.json`.

### `.claude/commands/sdd-start.md` (rewrite §1, §3, §4, §8)

- **§1 Resolve the Task**: read `sdd/tasks/index/*.json`, find the file containing the requested task. Resolve `feature_id`/`feature` from the index file's header.
- **§3 Detect Context**: drop the warning that says "you should be in a worktree". Per-spec indexes mean it's safe in either location.
- **§4 Mark In-Progress**: drop the `cd $REPO_ROOT && git checkout dev` block. Update the per-spec index file in-place (in whatever directory the user is). Stage and commit only that file with the message `sdd: start TASK-NNN — <title>`.
- **§8 Mark Done**: same — drop the cd-to-dev block. Move the task file from `sdd/tasks/active/` to `sdd/tasks/completed/` in-place; update the per-spec index with `status: done` and `completed_at`; stage and commit `sdd/tasks/index/<feature>.json` plus the moved task files.

**NOT in scope**:
- `/sdd-done` (TASK-999).
- `/sdd-next` and `/sdd-status` (TASK-1000).
- `sdd-worker` agent (TASK-1001).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `.claude/commands/sdd-task.md` | MODIFY | Rewrite §1, §4 index logic, §5 staging |
| `.claude/commands/sdd-start.md` | MODIFY | Rewrite §1 read-source, §3 context, §4 + §8 commit-in-place |

---

## Codebase Contract (Anti-Hallucination)

### Existing Files to Modify (verified line counts on 2026-05-05)

- `.claude/commands/sdd-task.md` — 166 lines. §1 at line 21–31; §4 step 4 (index update) at lines 86–109; §5 at lines 115–136.
- `.claude/commands/sdd-start.md` — 221 lines. §1 at lines 22–26; §3 at lines 39–60; §4 at lines 61–88; §8 at lines 165–194.

### Per-Spec Index Schema (from spec §2 Data Models, mandatory)

```json
{
  "feature": "<slug>",
  "feature_id": "FEAT-NNN",
  "spec": "sdd/specs/<slug>.spec.md",
  "type": "feature",
  "base_branch": "dev",
  "created_at": "<ISO-8601>",
  "completed_at": null,
  "tasks": [ { ... per current task schema ... } ]
}
```

### Frontmatter Read Pattern (verified — same one used in TASK-997)

```bash
META=$(source .venv/bin/activate && python -c "from pathlib import Path; from scripts.sdd.sdd_meta import parse; m = parse(Path('<spec-path>')); print(m.type, m.base_branch)")
TYPE=$(echo "$META" | awk '{print $1}')
BASE_BRANCH=$(echo "$META" | awk '{print $2}')
```

### Does NOT Exist

- ~~Reading from `sdd/tasks/.index.json` after this task~~ — must NOT remain in either command. Replace every reference.
- ~~A `cd $REPO_ROOT` block in `/sdd-start` post-rewrite~~ — must be removed entirely (§4 and §8).

---

## Implementation Notes

### `/sdd-task` rewritten §1

```markdown
### 1. Sync the Base Branch

Read the spec's frontmatter and sync the local base branch with origin:

```bash
META=$(python -c "from pathlib import Path; from scripts.sdd.sdd_meta import parse; m = parse(Path('<spec-path>')); print(m.type, m.base_branch)")
TYPE=$(echo "$META" | awk '{print $1}')
BASE=$(echo "$META" | awk '{print $2}')

git checkout "$BASE"
git pull --ff-only origin "$BASE"
```

For `type: hotfix`, BASE must be `main`. For `type: feature`, BASE
defaults to `dev` and may be any non-main branch.

If the working tree is dirty or `--ff-only` fails, abort with the
standard messages from `/sdd-spec`.
```

### `/sdd-task` rewritten §4 step 4

```markdown
4. Create or update the per-spec index at `sdd/tasks/index/<feature>.json`:

```python
# Pseudocode for the agent to execute via Bash + jq:
INDEX="sdd/tasks/index/<feature>.json"
if [[ -f "$INDEX" ]]; then
    # Append new tasks to the existing tasks[] array
    jq --argjson new "$NEW_TASKS_JSON" '.tasks += $new' "$INDEX" > "$INDEX.tmp"
    mv "$INDEX.tmp" "$INDEX"
else
    # Fresh index from spec frontmatter
    cat > "$INDEX" <<EOF
{
  "feature": "<feature-slug>",
  "feature_id": "FEAT-NNN",
  "spec": "sdd/specs/<feature-slug>.spec.md",
  "type": "$TYPE",
  "base_branch": "$BASE",
  "created_at": "$(date -u +%Y-%m-%dT%H:%M:%S+00:00)",
  "completed_at": null,
  "tasks": [...]
}
EOF
fi
```
```

### `/sdd-start` rewritten §4 (Mark In-Progress)

```markdown
### 4. Mark In-Progress (in place)

Update the per-spec index file directly — no branch switching needed.

```bash
INDEX="sdd/tasks/index/<feature>.json"
jq --arg id "<TASK-NNN>" '
  (.tasks[] | select(.id == $id) | .status) = "in-progress" |
  (.tasks[] | select(.id == $id) | .started_at) = (now | strftime("%Y-%m-%dT%H:%M:%S+00:00"))
' "$INDEX" > "$INDEX.tmp"
mv "$INDEX.tmp" "$INDEX"

git add "$INDEX"
git commit -m "sdd: start <TASK-NNN> — <title>"
```

The commit lives on whatever branch you are on (worktree or main repo).
The merge in `/sdd-done` brings it to the base branch alongside the code.
```

### `/sdd-start` rewritten §8 (Mark Done)

Analogous to §4 — drop the `cd` dance, do everything in place. Move the
task file from `sdd/tasks/active/` to `sdd/tasks/completed/`, update
status to `"done"` and `completed_at`, commit.

### Key Constraints

- ALL state writes happen in the current directory (worktree or main repo).
- The `cd $REPO_ROOT && git checkout dev` pattern MUST be removed from both commands.
- Backwards compatibility for old monolith reads is NOT required — TASK-995 already migrated everything to per-spec indexes.

---

## Acceptance Criteria

- [ ] `.claude/commands/sdd-task.md` no longer mentions `dev` as a hardcoded branch (search: `grep -n "git checkout dev\|on the dev branch" .claude/commands/sdd-task.md` returns no hits).
- [ ] `.claude/commands/sdd-task.md` references `sdd/tasks/index/<feature>.json` (search: at least one hit).
- [ ] `.claude/commands/sdd-task.md` references `parse(Path` or equivalent for reading frontmatter.
- [ ] `.claude/commands/sdd-start.md` no longer has a `cd $REPO_ROOT` block (search: `grep -n "cd .*REPO_ROOT" .claude/commands/sdd-start.md` returns no hits).
- [ ] `.claude/commands/sdd-start.md` references `sdd/tasks/index/<feature>.json`.
- [ ] No remaining references to `sdd/tasks/.index.json` in either file.
- [ ] Manual smoke test: walking through `/sdd-task` mentally for the next FEAT-146 produces a coherent flow ending with `sdd/tasks/index/<feature-slug>.json` written and the worktree created.

---

## Test Specification

Verification is largely manual code review of the markdown command files:

```bash
# Confirm the rewrites land:
grep -c "sdd/tasks/index/" .claude/commands/sdd-task.md   # ≥ 1
grep -c "sdd/tasks/index/" .claude/commands/sdd-start.md  # ≥ 1
grep -c "git checkout dev" .claude/commands/sdd-task.md   # 0
grep -c "git checkout dev" .claude/commands/sdd-start.md  # 0
grep -c "REPO_ROOT" .claude/commands/sdd-start.md         # 0
grep -c "sdd/tasks/.index.json" .claude/commands/sdd-task.md   # 0
grep -c "sdd/tasks/.index.json" .claude/commands/sdd-start.md  # 0
```

All counts must match.

---

## Agent Instructions

1. Read both files end-to-end before editing.
2. Use surgical `Edit` calls with unique-string anchors. Do NOT rewrite the files via `Write` — they have lots of unrelated content (anti-hallucination rules, examples) that must remain intact.
3. After every edit, run the grep verifications.
4. Commit: `feat(sdd): TASK-998 — sdd-task and sdd-start use per-spec index`.

---

## Completion Note

**Completed by**: Claude (Opus 4.7) — interactive session via `/sdd-start TASK-998`
**Date**: 2026-05-05
**Notes**: Both commands rewritten end-to-end. The "code in worktree, state on dev" pattern is gone — per-spec indexes mean state IS the worktree's; the merge in `/sdd-done` brings everything to base_branch atomically.

**`sdd-task.md` changes:**
- Guardrails: now require `base_branch` (read from spec frontmatter), not hardcoded `dev`.
- §1 "Verify Branch" → "Sync the Base Branch": reads frontmatter via `python -c "from scripts.sdd.sdd_meta import parse; ..."`, runs `git checkout $BASE && git pull --ff-only`, refuses if dirty or non-FF, refuses if invoked from inside a worktree.
- §4 step 4: replaced the monolithic-index schema block with the per-spec schema (header + tasks). Documents `mkdir -p` for the index directory and append-vs-create behaviour for existing indexes (e.g. when the migration script already laid one down for an old spec).
- §5 commit: stages `sdd/tasks/index/<feature>.json` instead of `sdd/tasks/.index.json`.

**`sdd-start.md` changes:**
- Guardrails: replaced the "code in worktree, state on dev" rule with the FEAT-145 model (code + per-spec index live together; merge brings them across).
- §1 Resolve Task: globs `sdd/tasks/index/*.json` (excluding `_orphans.json`) and finds the per-spec index containing the requested ID/slug. Includes a working `jq -e` snippet.
- §3 Detect Context: dropped the "you should be in a worktree" warning; both worktree and main repo are safe targets now.
- §4 Mark In-Progress: rewritten as in-place `jq` update + commit on the current branch. The whole `cd $REPO_ROOT && git checkout dev && ... && cd $WORKTREE_DIR` dance is gone.
- §8 Mark Done: same pattern — in-place `jq` update + `mv` + commit. Also updates `.tasks[…].file` to point at `sdd/tasks/completed/`.
- §9 Post-Completion Hint: simplified ("committed on branch: <current branch>" instead of "Index updated on dev").
- Reference: now lists per-spec index path + the new `scripts/sdd/sdd_meta.py` parser.

**Acceptance grep results:**
| Check                                  | sdd-task.md | sdd-start.md |
|----------------------------------------|-------------|--------------|
| `sdd/tasks/index/` refs (≥ 1)          | 6 ✅        | 6 ✅         |
| `sdd/tasks/.index.json` refs (= 0)     | 0 ✅        | 0 ✅         |
| `git checkout dev` (= 0)               | 0 ✅        | 0 ✅         |
| `cd …REPO_ROOT` blocks in sdd-start (= 0) | —        | 0 ✅         |
| `parse(Path` / `sdd_meta` in sdd-task (≥ 1) | 1 ✅   | —            |

**Deviations from contract**: none.

**Heads-up for downstream tasks**:
- TASK-1001 (`sdd-worker` agent rewrite) must mirror these same patterns — the agent duplicates `/sdd-start`'s logic inline.
- The new `/sdd-task` flow assumes `scripts.sdd.sdd_meta` is importable (delivered by TASK-994) and that `sdd/tasks/index/` exists (delivered by TASK-995's migration). Both prerequisites are satisfied.

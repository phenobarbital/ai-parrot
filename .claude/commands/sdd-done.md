---
model: haiku
description: Verify that a feature's tasks were implemented, push the branch, optionally resolve the linked Jira ticket, and clean up the worktree.
---

# /sdd-done — Verify, Push, and Cleanup a Feature

Verify that a feature's tasks were implemented in its worktree, ensure the branch is
pushed, and clean up the worktree. Optionally transitions the linked Jira ticket to
"Done" / "Resolved".

**This command runs on `dev` (or the main repo), NOT inside a worktree.**
It looks INTO the worktree to verify work, but modifies state only on `dev`.

## Usage
```
/sdd-done FEAT-014
/sdd-done videoreel-visual-changes
/sdd-done FEAT-014 --dry-run           # show what would change, don't change anything
/sdd-done FEAT-014 --force             # mark done even if some checks fail
/sdd-done FEAT-014 --resolve-jira      # also transition the Jira ticket to Done
```

## Guardrails
- **Must run on `dev`**, not inside a worktree.
- Do NOT mark tasks as done unless evidence exists in the worktree (commits, files).
- Do NOT modify the spec — only task statuses and task files.
- If a task has no evidence of implementation, flag it explicitly.
- Always show a verification report before making changes.

## Steps

### 1. Verify We're on `dev`
```bash
CURRENT_BRANCH=$(git branch --show-current)
```
If not on `dev`, warn:
```
⚠️  /sdd-done should run on dev, not inside a worktree.
   Current branch: <branch>
   Switch: git checkout dev
```

### 2. Resolve the Feature
1. Read `sdd/tasks/.index.json`.
2. Find all tasks belonging to the given feature. Match against:
   - `feature_id` — exact match (e.g., `"FEAT-014"`)
   - `feature` — exact match (e.g., `"videoreel-visual-changes"`)
   - `feature_id` — numeric suffix (e.g., `"014"` → `"FEAT-014"`)
   - `feature` — substring match (e.g., `"videoreel"` → `"videoreel-visual-changes"`)
   If no match, list available features and ask the user to clarify.
3. Read the spec file referenced by the tasks.

### 3. Locate the Worktree
Find the feature's worktree:
```bash
git worktree list | grep "feat-<FEAT-ID>"
```
Extract the worktree path. If no worktree found:
```
⚠️  No worktree found for FEAT-<ID>.
   Looking for branch feat-<FEAT-ID>-<slug> in remote...
```
Fall back to checking remote branches.

### 4. Gather Evidence from the Worktree
For each task in the feature, check the WORKTREE for implementation evidence:

**a) Git history check (in the worktree):**
```bash
git -C <worktree-path> log --oneline --grep="TASK-<NNN>"
git -C <worktree-path> log --oneline --grep="<task-slug>"
```

**b) File existence check (in the worktree):**
Read the task file and extract the "Files to create/modify" section.
```bash
test -f <worktree-path>/<filepath>
```

**c) Test check (optional, skip if --force):**
If the task file lists test commands, run them in the worktree:
```bash
cd <worktree-path> && npx vitest run <test-path> 2>&1 | tail -10
# or
cd <worktree-path> && pytest <test-path> -x -q 2>&1 | tail -5
```

### 5. Build Verification Report
Classify each task:

- **✅ VERIFIED** — commit found AND files exist AND tests pass (or no tests specified).
- **⚠️ PARTIAL** — commit found but some files missing or tests failing.
- **❌ NO EVIDENCE** — no matching commits, files don't exist.

Present the report:
```
📋 Verification Report: FEAT-<ID> — <title>

Worktree: .claude/worktrees/feat-<ID>-<slug>
Branch: feat-<ID>-<slug>
Commits found: <N>
Tasks: <total> total, <verified> verified, <partial> partial, <missing> missing

  ✅ TASK-096 — Scene Editor Refactor
     Commits: feat(videoreel): TASK-096 — Scene Editor Refactor (abc1234)
     Files: src/lib/components/SceneEditor.svelte ✅
     Tests: 3 passed ✅

  ⚠️ TASK-097 — Visual Transitions
     Commits: feat(videoreel): TASK-097 — Visual Transitions (def5678)
     Files: src/lib/components/Transitions.svelte ✅
     Tests: 1 failed ⚠️

  ❌ TASK-098 — Export Pipeline
     Commits: none found
     Files: src/lib/utils/export.ts ❌
```

### 6. Confirm
If all tasks are ✅ VERIFIED:
```
All tasks verified. Proceed with closing? (Y/n)
```

If any tasks are ⚠️ PARTIAL or ❌ NO EVIDENCE:
```
<N> task(s) have issues. Options:
  1. Close verified tasks only (mark others as "pending")
  2. Close all with --force (mark partial as "done-with-issues")
  3. Abort — fix issues first
```

If `--dry-run`, show the report and STOP.
If `--force`, close all tasks regardless.

### 7. Close Tasks (on `dev`)
For each task being closed, update `dev`:

```bash
# Already on dev (verified in Step 1)

# Move task files to completed
mkdir -p sdd/tasks/completed/
mv sdd/tasks/active/TASK-<NNN>-<slug>.md sdd/tasks/completed/
# Repeat for each closed task...

# Update index: set status → "done", completed_at → now, verification → verified|partial|forced
# Update task file headers: Status, Completed date, Verification

git add sdd/tasks/.index.json sdd/tasks/active/ sdd/tasks/completed/
git commit -m "sdd: close tasks for FEAT-<ID> — <title>"
```

### 8. Push the Feature Branch
If the worktree branch hasn't been pushed yet:
```bash
git -C <worktree-path> push origin feat-<FEAT-ID>-<slug>
```

### 9. Merge Feature Branch into `dev`

> **CRITICAL**: This is the step that brings the implementation code into `dev`.
> Without this merge, the task index is updated but the code changes remain
> only on the feature branch — causing "marked done but not implemented" issues.

```bash
# We're already on dev (verified in Step 1)
git merge feat-<FEAT-ID>-<slug> --no-edit
```

If the merge has conflicts:
```
⚠️  Merge conflict when merging feat-<FEAT-ID>-<slug> into dev.
   Conflicting files:
     - <file1>
     - <file2>

   Options:
     1. Resolve conflicts now (recommended)
     2. Abort merge: git merge --abort
```
If conflicts are resolved, commit the merge. If the user aborts, STOP and
do NOT proceed to cleanup.

After a successful merge, push `dev`:
```bash
git push origin dev
```

### 10. Transition Jira Ticket (if --resolve-jira)

If `--resolve-jira` is passed AND the spec has a Jira key (set by `/sdd-tojira`):

**a) Extract the Jira key from the spec:**
```bash
# Look for "**Jira**: [NAV-8036](...)" or a "jira:" metadata field in the spec
JIRA_KEY=$(grep -oP '(?<=\*\*Jira\*\*: \[)[A-Z]+-\d+' sdd/specs/<feature>.spec.md)
# Or from the brainstorm "## Jira Source" table
if [[ -z "$JIRA_KEY" ]]; then
    JIRA_KEY=$(grep -oP '(?<=\| Key \| )[A-Z]+-\d+' sdd/proposals/<key>-*.brainstorm.md)
fi
```

If no Jira key is found, skip this step with a note:
```
ℹ️  No Jira key found in spec — skipping Jira transition.
   To link a spec to Jira: /sdd-tojira <spec-path>
```

**b) Load Jira credentials:**
```bash
eval "$(python -c "from navconfig import config; import os; [print(f'export {k}={v}') for k,v in os.environ.items() if k.startswith('JIRA_')]")"
JIRA_INSTANCE="${JIRA_INSTANCE%/}"
```

If `JIRA_INSTANCE` or `JIRA_API_TOKEN` are not set, warn and skip.

**c) Get available transitions for the ticket:**

Jira transitions are workflow-dependent — you cannot set a status directly.
First, fetch the available transitions:

**MCP path:**
```
jira_transition_issue(issue_key="<JIRA_KEY>")  # list available transitions
```

**curl fallback:**
```bash
TRANSITIONS=$(curl -s -u "$JIRA_USERNAME:$JIRA_API_TOKEN" \
  "$JIRA_INSTANCE/rest/api/3/issue/$JIRA_KEY/transitions")
echo "$TRANSITIONS" | jq '.transitions[] | {id, name}'
```

**d) Find and execute the "Done" / "Resolved" transition:**

Look for a transition whose name matches (case-insensitive):
`Done`, `Resolved`, `Close`, `Ready for UAT`, `Complete`.

```bash
# Find the transition ID
TRANSITION_ID=$(echo "$TRANSITIONS" | jq -r '
  .transitions[] |
  select(.name | test("(?i)done|resolved|close|complete|ready for uat")) |
  .id' | head -1)
```

If found, execute it:

**MCP path:**
```
jira_transition_issue(issue_key="<JIRA_KEY>", transition_id="<TRANSITION_ID>")
```

**curl fallback:**
```bash
curl -s -u "$JIRA_USERNAME:$JIRA_API_TOKEN" \
  -H "Content-Type: application/json" \
  -X POST "$JIRA_INSTANCE/rest/api/3/issue/$JIRA_KEY/transitions" \
  -d "{\"transition\": {\"id\": \"$TRANSITION_ID\"}}"
```

If multiple matching transitions exist, prefer in this order:
1. "Done"
2. "Resolved"
3. "Ready for UAT"
4. "Complete"
5. "Close"

If no matching transition is found:
```
⚠️  No "Done" or "Resolved" transition available for <JIRA_KEY>.
   Current status: <current_status>
   Available transitions: <list>
   You may need to transition it manually in Jira.
```

**e) Optionally resolve subtasks too:**

If the ticket has subtasks (created by `--with-subtasks` in `/sdd-tojira`),
transition each one that is still open:
```bash
SUBTASKS=$(curl -s -u "$JIRA_USERNAME:$JIRA_API_TOKEN" \
  "$JIRA_INSTANCE/rest/api/3/issue/$JIRA_KEY?fields=subtasks" \
  | jq -r '.fields.subtasks[].key')

for SUBTASK in $SUBTASKS; do
    # Get transitions for this subtask, find "Done", execute
    # Same logic as above
done
```

### 11. Cleanup the Worktree
```bash
git worktree remove .claude/worktrees/feat-<FEAT-ID>-<slug>
```
If there are uncommitted changes in the worktree, warn:
```
⚠️  Worktree has uncommitted changes. Force remove? (y/N)
```

If the worktree was already removed, prune stale metadata:
```bash
git worktree prune
```

Optionally delete the local feature branch (it's been merged):
```bash
git branch -d feat-<FEAT-ID>-<slug>
```

### 12. Output
```
✅ FEAT-<ID> — <title>: <N>/<total> tasks closed.

Closed:
  ✅ TASK-096 — Scene Editor Refactor (verified)
  ✅ TASK-097 — Visual Transitions (verified)

Index updated on dev and committed.
Branch pushed: feat-<ID>-<slug>
Merged into dev: feat-<ID>-<slug> ✅
Worktree removed: .claude/worktrees/feat-<ID>-<slug>
Local branch deleted: feat-<ID>-<slug>
```

If `--resolve-jira` was used and succeeded:
```
Jira: NAV-8036 → Done ✅
  Subtasks transitioned: 4/4
```

If ALL tasks were closed:
```
✅ FEAT-<ID> — <title>: all <N> tasks closed and merged into dev.

Worktree cleaned up.
Feature branch merged and deleted.
{if --resolve-jira} Jira NAV-8036 → Done ✅ {end if}
```

## Reference
- Index file: `sdd/tasks/.index.json` (on `dev`)
- Active tasks: `sdd/tasks/active/` (on `dev`)
- Completed tasks: `sdd/tasks/completed/` (on `dev`)
- SDD methodology: `sdd/WORKFLOW.md`
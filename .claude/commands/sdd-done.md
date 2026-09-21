---
model: haiku
description: Verify that a feature's tasks were implemented, check for merge blockers, snapshot ledger issues, push the branch, optionally resolve the linked Jira ticket, and clean up the worktree.
---

# /sdd-done — Verify, Check Blockers, Snapshot, Push, and Cleanup a Feature

Verify that a feature's tasks were implemented in its worktree, check for merge
blockers scoped to the current feature, snapshot ledger issues on base branch,
ensure the branch is pushed, and clean up the worktree. Optionally transitions
the linked Jira ticket to "Done" / "Resolved".

**This command runs on the spec's `base_branch`** — read from the spec's
YAML frontmatter (FEAT-145). For `type: feature` that is `dev` (default)
or `staging` (during a release freeze); for `type: hotfix` that is `main`.
It may be invoked from the main repo or from inside the feature worktree
(the `sdd-worker` agent does the latter). It looks INTO the worktree to
verify work, but modifies state only on `base_branch`.

## Usage
```
/sdd-done FEAT-014
/sdd-done videoreel-visual-changes
/sdd-done FEAT-014 --dry-run           # show what would change, don't change anything
/sdd-done FEAT-014 --merge             # direct merge into base_branch (checks blockers)
/sdd-done FEAT-014 --force             # mark done even if some checks fail, bypass blockers
/sdd-done FEAT-014 --resolve-jira      # also transition the Jira ticket to Done
/sdd-done FEAT-014 --sync-down         # for hotfixes: after the user merges the PR
                                       # to main, propagate the change to staging + dev
                                       # (mostly redundant with sync-down.yml Action)
/sdd-done FEAT-014 --sync-dev          # deprecated alias for --sync-down
```

## Guardrails
- **Targets the spec's `base_branch`** (read from spec frontmatter — `dev` for features, `main` for hotfixes). From the main repo it must be checked out on that branch; from inside the feature worktree (`IN_WORKTREE=1`, Step 1) every primary-checkout path goes through `$MAIN_ROOT` / `$WORKTREES_DIR`.
- Do NOT mark tasks as done unless evidence exists in the worktree (commits, files).
- Do NOT modify the spec — only task statuses and task files.
- If a task has no evidence of implementation, flag it explicitly.
- Always show a verification report before making changes.

> **CRITICAL — `/sdd-done` NEVER pushes to `main` and NEVER opens a PR against `main` (FEAT-145).**
> Hotfixes go to `main` ONLY via a manually-opened PR. This rule is non-negotiable
> and applies to every flag combination — including `--merge`, `--force`, and `--resolve-jira`.
> For hotfixes, this command pushes the hotfix branch and prints a `gh pr create
> --base main` snippet. After the user merges the PR, the `.github/workflows/sync-down.yml`
> Action propagates the change to `staging` and `dev` automatically. If the Action
> fails or you are offline, re-run with `--sync-down` to propagate the change back to
> both `staging` and `dev` manually. (`--sync-dev` is a deprecated alias for `--sync-down`.)
>
> **Default behavior for features**: `/sdd-done` opens a PR against `BASE_BRANCH`
> (typically `dev` or `staging`). Pass `--merge` to merge directly instead.

## Steps

## Durable review boundary (FEAT-584)
Before feature review, settle owned attempts and supervised validations and close execution.
Unknown activity is a blocker, never evidence of an idle worktree. Persist the checkpoint,
record actual supported compaction outcome once per checkpoint/context, revalidate and start
a fresh reviewer. Unsupported contexts continue from checkpoint with an explicit reason.
Keep review criteria, adversarial checks, full lint, integration validation and ledger gates.
Changes after checkpoint require new hashes/evidence and invalidate old review coverage.
For sdd-done, preserve existing verification stamping, approval and push/merge policy;
do not run task closure again on base_branch and do not clean worktrees with unknown activity.

### 1. Verify We're on the Base Branch (FEAT-145)

Read the spec's frontmatter to discover `BASE_BRANCH`:

```bash
META=$(python -c "from pathlib import Path; from scripts.sdd.sdd_meta import parse; m = parse(Path('<spec-path>')); print(m.type, m.base_branch)")
TYPE=$(echo "$META" | awk '{print $1}')
BASE_BRANCH=$(echo "$META" | awk '{print $2}')
CURRENT_BRANCH=$(git branch --show-current)

# /sdd-done runs either from the main repo or from inside the feature worktree
# (the sdd-worker agent runs it from its own worktree). Resolve the primary
# checkout once and address it ONLY through these variables afterwards.
MAIN_ROOT=$(cd "$(git rev-parse --path-format=absolute --git-common-dir)/.." && pwd)
WORKTREES_DIR="$MAIN_ROOT/.claude/worktrees"
IN_WORKTREE=0
if [[ "$(git rev-parse --path-format=absolute --git-dir)" != "$(git rev-parse --path-format=absolute --git-common-dir)" ]]; then
    IN_WORKTREE=1
fi
```

If `IN_WORKTREE=0` and `CURRENT_BRANCH != BASE_BRANCH`, abort:
```
⚠️  /sdd-done must run on the spec's base_branch (got <CURRENT_BRANCH>, expected <BASE_BRANCH>).
   Switch: git checkout <BASE_BRANCH>
```

If `IN_WORKTREE=1`, the current branch is the feature branch — that is expected,
skip the base-branch check. Only the PR flow is available from here: `--merge`
and `--sync-down` are refused in Steps 9.2 / 9.5 because they need a writable
checkout of `BASE_BRANCH`. The worktree sandbox keeps the primary checkout
read-only except its `.git` and `$WORKTREES_DIR`, so: never `cd` to
`$MAIN_ROOT`, never write anywhere else under it, and reference every
primary-checkout path through `$MAIN_ROOT` / `$WORKTREES_DIR` (never relative
to the worktree's cwd). Ledger writes that need the primary checkout fall back
to `(NOT filed: shared ledger is read-only)` as documented in `sdd-worker`.

### 2. Resolve the Feature
1. Glob `sdd/tasks/index/*.json` (excluding `_orphans.json`) and find the
   per-spec index whose header matches the user's input. Match against:
   - `feature_id` — exact match (e.g., `"FEAT-014"`)
   - `feature` — exact match (e.g., `"videoreel-visual-changes"`)
   - `feature_id` — numeric suffix (e.g., `"014"` → `"FEAT-014"`)
   - `feature` — substring match (e.g., `"videoreel"` → `"videoreel-visual-changes"`)
   If no match, list available features (one per per-spec index file) and ask the user to clarify.
2. Read the spec file referenced by the per-spec index header.
3. The list of tasks for this feature is the `tasks[]` array in the matched per-spec index file.

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

**Note:** Test validation is intentionally skipped here — each task already ran
its acceptance-criteria tests during `/sdd-start` or `sdd-worker` execution.
Re-running them at close time adds latency without new signal.

### 4.5. Full Lint Pass (once per feature)

Per-task lint is engine-owned and only auto-fixes (`sdd-coder` engine, merge
boundary). This step is the ONE place the repo's full ruff rule set is enforced
for the feature — never per task. With `--dry-run`, run only the final
`ruff check` and report; do not fix or commit.

```bash
WT="<worktree-path>"
git -C "$WT" fetch origin <base_branch>
mapfile -t PY < <(git -C "$WT" diff --name-only --diff-filter=ACMR "origin/<base_branch>...HEAD" -- '*.py')
if [ ${#PY[@]} -gt 0 ]; then
  (cd "$WT" && ruff check --fix --exit-zero --quiet "${PY[@]}")
  if grep -q '^\[tool\.black\]' "$WT/pyproject.toml"; then (cd "$WT" && black -q "${PY[@]}"); fi
  git -C "$WT" add -- "${PY[@]}"
  git -C "$WT" diff --cached --quiet || git -C "$WT" commit -m "style(<slug>): FEAT-<ID> — full lint pass"
  (cd "$WT" && ruff check --output-format concise "${PY[@]}")
fi
```

Then fix what `ruff check` still reports, in those files only (pre-existing
violations in a touched file included — that is deliberate code improvement):
- Keep each fix behavior-neutral; when one is not (e.g. narrowing a blind
  `except Exception`), run `TASK_FILES=$(jq -r '.tasks[].file' "sdd/tasks/index/<feature-slug>.json");
  python -m scripts.sdd.select_tests --tier feature --base origin/<base_branch> --worktree "$WT"
  $(printf -- '--task-file %s ' $TASK_FILES) --run` before committing.
- Commit as `style(<slug>): FEAT-<ID> — lint fixes`.
- A finding you cannot fix safely goes under **Lint residual** in the report.
  Residual syntax errors / undefined names (`E9`, `F63`, `F7`, `F82`) are merge
  blockers: they turn Step 6 into the "issues" branch. Other residue does not.

### 5. Build Verification Report
Classify each task:

- **✅ VERIFIED** — commit found AND files exist.
- **⚠️ PARTIAL** — commit found but some files missing.
- **❌ NO EVIDENCE** — no matching commits, files don't exist.

Present the report:
```
📋 Verification Report: FEAT-<ID> — <title>

Worktree: .claude/worktrees/feat-<ID>-<slug>
Branch: feat-<ID>-<slug>
Commits found: <N>
Tasks: <total> total, <verified> verified, <partial> partial, <missing> missing
Lint: <autofixed files> auto-fixed, <fixed> hand-fixed, <residual> residual (<blocking> blocking)

  ✅ TASK-096 — Scene Editor Refactor
     Commits: feat(videoreel): TASK-096 — Scene Editor Refactor (abc1234)
     Files: src/lib/components/SceneEditor.svelte ✅

  ⚠️ TASK-097 — Visual Transitions
     Commits: feat(videoreel): TASK-097 — Visual Transitions (def5678)
     Files: src/lib/components/Transitions.svelte ✅ | src/lib/utils/transitions.ts ❌

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

### 7. Stamp Verification (on feature branch)

Stamp verification metadata on each closed task in the worktree's per-spec
index. The feature branch already carries the task files in `completed/` and
the index with `status: "done"` — this step only adds the `verification`
field and the feature-level `completed_at`.

> **Why not close_task.sh?** The feature branch already moved files
> `active/` → `completed/` and set status/completed_at/file during
> `sdd-worker`/`sdd-start`. Running `close_task.sh` again on `base_branch`
> would create duplicate state that conflicts on merge (FEAT-414).

```bash
WORKTREE_PATH="$WORKTREES_DIR/feat-<FEAT-ID>-<slug>"   # absolute: valid from the main repo and from inside the worktree
INDEX="sdd/tasks/index/${FEATURE_SLUG}.json"
NOW="$(date -u +%Y-%m-%dT%H:%M:%S+00:00)"

# Stamp verification on each task being closed.
# Use "verified" for ✅ VERIFIED tasks, "partial" for ⚠️ PARTIAL, "forced" for --force.
for TASK_ID in "${TASK_IDS[@]}"; do
  jq --arg id "$TASK_ID" --arg ver "$VERIFICATION" '
    (.tasks[] | select(.id == $id) | .verification) = $ver
  ' "$WORKTREE_PATH/$INDEX" > tmp && mv tmp "$WORKTREE_PATH/$INDEX"
done

# Stamp feature-level completed_at if all tasks are done.
jq --arg now "$NOW" '
  if all(.tasks[]; .status == "done") then .completed_at = $now else . end
' "$WORKTREE_PATH/$INDEX" > tmp && mv tmp "$WORKTREE_PATH/$INDEX"

# Commit on the feature branch (inside the worktree) — never on base_branch.
git -C "$WORKTREE_PATH" add "$INDEX"
git -C "$WORKTREE_PATH" diff --cached --name-only   # sanity-check: only the index
git -C "$WORKTREE_PATH" commit -m "sdd: close tasks for FEAT-<ID> — <slug>"
```

### 8. Push the Feature Branch
If the worktree branch hasn't been pushed yet:
```bash
git -C <worktree-path> push origin feat-<FEAT-ID>-<slug>
```

### 9. Check Merge Blockers (FEAT-566)

Before integrating the feature branch, check for critical unacknowledged issues
(blockers) that were discovered by this feature. Issues from other features do
not block this feature's merge.

```bash
if [[ "$MERGE_FLAG" == "--merge" ]]; then
    # `ledger blockers <FEAT-ID>` prints plain text lines (one per blocker) and
    # exits 1 when any exist, exit 0 otherwise — it never emits JSON, so the
    # gate below checks the EXIT CODE, not the (human-readable) output shape.
    BLOCKERS_OUTPUT=$(wikitoolkit ledger blockers "$FEAT_ID" 2>&1)
    BLOCKERS_EXIT=$?
    if [[ $BLOCKERS_EXIT -ne 0 ]]; then
        echo "⚠️  Merge blocked by critical unacknowledged issues:"
        echo "$BLOCKERS_OUTPUT"
        echo ""
        echo "Resolve these issues or acknowledge them as accepted risks before merging."
        echo "To acknowledge an issue: wikitoolkit ledger acknowledge <ISSUE-ID> --reason \"...\" --actor human:<name>"
        if [[ "$FORCE_FLAG" != "--force" ]]; then
            echo ""
            echo "Use --force to bypass blocker checks (not recommended)."
            exit 1
        else
            echo ""
            echo "⚠️  Proceeding with --force despite blockers."
        fi
    fi
fi
```

### 9.1. Snapshot Ledger Issues (FEAT-566)

For feature flows (not hotfixes), regenerate `sdd/ledger/issues.jsonl` from a
throwaway worktree at `origin/<BASE_BRANCH>` and commit/push it directly to
`base_branch` when it changed — never from an active worktree, never on the
feature branch. Bounded retry on a rejected push; never fails `/sdd-done`.

```bash
if [[ "$TYPE" != "hotfix" ]]; then
    git fetch origin "$BASE_BRANCH" >/dev/null 2>&1

    # Absolute path under the primary checkout: from inside a feature worktree a
    # relative path would land inside that worktree, and the sandbox only lets
    # worktree agents write to $WORKTREES_DIR outside their own checkout.
    TEMP_WORKTREE="$WORKTREES_DIR/_ledger-snapshot-$$"
    git worktree add --detach "$TEMP_WORKTREE" "origin/$BASE_BRANCH" >/dev/null 2>&1
    # No --force: the throwaway checkout only ever touches issues.jsonl, so
    # restoring that one file leaves it clean and a plain remove succeeds
    # (a detached, unpushed snapshot commit does not block `worktree remove`).
    cleanup_snapshot_worktree() {
        git -C "$TEMP_WORKTREE" restore --staged --worktree -- sdd/ledger/issues.jsonl >/dev/null 2>&1
        git worktree remove "$TEMP_WORKTREE" >/dev/null 2>&1 || true
    }
    trap cleanup_snapshot_worktree EXIT

    ATTEMPT=1
    MAX_ATTEMPTS=3
    while (( ATTEMPT <= MAX_ATTEMPTS )); do
        EXPORT_OUTPUT=$(cd "$TEMP_WORKTREE" && wikitoolkit ledger export 2>&1)
        if [[ "$EXPORT_OUTPUT" != *"(changed)"* ]]; then
            echo "📝 Ledger snapshot unchanged — nothing to commit."
            break
        fi

        git -C "$TEMP_WORKTREE" add sdd/ledger/issues.jsonl
        git -C "$TEMP_WORKTREE" commit -q -m "sdd: ledger snapshot for $FEAT_ID"
        if git -C "$TEMP_WORKTREE" push origin "HEAD:$BASE_BRANCH" >/dev/null 2>&1; then
            echo "📝 Ledger snapshot updated with changed issues."
            break
        fi

        # Rejected push: re-sync the throwaway worktree only, re-export, retry.
        git fetch origin "$BASE_BRANCH" >/dev/null 2>&1
        git -C "$TEMP_WORKTREE" restore --staged --worktree -- sdd/ledger/issues.jsonl >/dev/null 2>&1
        git -C "$TEMP_WORKTREE" checkout -q --detach "origin/$BASE_BRANCH" >/dev/null 2>&1
        ATTEMPT=$((ATTEMPT + 1))
        if (( ATTEMPT > MAX_ATTEMPTS )); then
            echo "⚠️  Ledger snapshot push failed after $MAX_ATTEMPTS attempts — continuing without failing /sdd-done."
        fi
    done

    cleanup_snapshot_worktree
    trap - EXIT
fi
```

### 9.2. Integrate Feature Branch (FEAT-145, flow-aware)

> **CRITICAL**: This is the step that brings the implementation code into the
> base branch. The default is to open a PR; pass `--merge` to merge directly.

**Hard refusal — `BASE_BRANCH == "main"`:**

Hotfixes ALWAYS go through a PR, regardless of flags (including `--merge`):

```bash
if [[ "$BASE_BRANCH" == "main" ]]; then
    cat <<EOF
⚠️ Hotfix merging into 'main' MUST go through a PR. /sdd-done refuses to merge
   into main directly, regardless of flags.

   Open the PR manually:

     gh pr create --base main --head feat-<FEAT-ID>-<slug> \\
       --title "<hotfix title>" \\
       --body "<verification summary>"

   After the PR merges, the sync-down.yml Action propagates the change to staging
   and dev automatically. If the Action fails or you are offline, re-run with
   --sync-down to propagate the change manually:

     /sdd-done <FEAT-ID> --sync-down

EOF
    exit 0   # NOT an error — the hotfix workflow continues outside this command
fi
```

**Feature flow (`BASE_BRANCH != "main"`) — default: open a PR:**

Unless `--merge` is passed, push the feature branch and open a PR against
`BASE_BRANCH`:

```bash
# Push the feature branch (already done in Step 8, but ensure it's up to date)
git -C <worktree-path> push origin feat-<FEAT-ID>-<slug>

# Open a PR against the base branch
gh pr create \
  --base "$BASE_BRANCH" \
  --head "feat-<FEAT-ID>-<slug>" \
  --title "feat(<feature-slug>): FEAT-<ID> — <title>" \
  --body "$(cat <<EOF
## Summary

<Verification report from Step 5 — list of tasks implemented>

## Tasks

<N>/<total> tasks verified.

---
_Closed by /sdd-done_
EOF
)"
```

If `gh` is not installed or not authenticated, print the manual command:
```
ℹ️  Could not create PR automatically. Run manually:

    gh pr create --base <BASE_BRANCH> --head feat-<FEAT-ID>-<slug> \
      --title "feat(<feature-slug>): FEAT-<ID> — <title>" \
      --body "<verification summary>"
```

**Feature flow with `--merge` — direct merge (old behavior):**

When `--merge` is explicitly passed, perform a direct merge instead of a PR.

**Hard refusal — `IN_WORKTREE=1`:** a direct merge needs a writable checkout of
`BASE_BRANCH`, and inside the feature worktree HEAD *is* the feature branch:
the merge below would be a no-op self-merge and `git push origin "$BASE_BRANCH"`
would publish a stale base branch without the feature commits, while the
command still reports success and removes the worktree. Refuse and fall back
to the PR flow above:

```bash
if [[ "$IN_WORKTREE" == "1" && "$MERGE_FLAG" == "--merge" ]]; then
    cat <<EOF
⚠️  --merge is not available from inside the feature worktree (HEAD is the
   feature branch, and the primary checkout is read-only here).
   Either re-run /sdd-done from the main repo checked out on $BASE_BRANCH,
   or drop --merge to open a PR instead.
EOF
    exit 1
fi
```

```bash
# We're on $BASE_BRANCH in the main repo (verified in Step 1, IN_WORKTREE=0)
git merge --no-edit feat-<FEAT-ID>-<slug>
```

If the merge has conflicts (e.g. code-level changes to the same files):
```
⚠️  Merge conflict when merging feat-<FEAT-ID>-<slug> into <BASE_BRANCH>.
   Resolve conflicts, then continue with: git merge --continue
   Or abort: git merge --abort
```
If the user aborts, STOP and do NOT proceed to cleanup.

**Self-heal — reap stalled `active/` orphans (runs after every `--merge`):**

> Only applies when `--merge` is used. When using PR flow, the orphan sweep
> happens on the PR merge side.

```bash
scripts/sdd/heal_orphans.sh <feature-slug>
# If it reaped anything, commit the cleanup before pushing:
if ! git diff --cached --quiet -- sdd/tasks/active sdd/tasks/completed; then
  git commit -m "sdd: reap stalled active task orphans for FEAT-<ID> — <title>"
fi
```

After a successful merge and self-heal, push `<BASE_BRANCH>`:
```bash
git push origin "$BASE_BRANCH"
```

### 9.5. Hotfix → Sync-down (FEAT-187, only with `--sync-down`)

This sub-step runs ONLY when the user passes `--sync-down` (or the deprecated
`--sync-dev` alias) AND `TYPE == "hotfix"`. It propagates a hotfix that has just
been merged into `main` (via the manual PR from §9) back into `staging` and `dev`
so both stay in sync.

**Hard refusal — `IN_WORKTREE=1`:** the sync-down below runs `git checkout
staging` / `git checkout dev` and merges in the current checkout. Inside a
worktree those branches are checked out elsewhere (the primary checkout) and
`git checkout` fails, so refuse and point at the main repo:

```bash
if [[ "$IN_WORKTREE" == "1" ]]; then
    echo "⚠️  --sync-down must run from the main repo, not inside a worktree: cd to \$MAIN_ROOT and re-run."
    exit 1
fi
```

If `--sync-dev` is used instead of `--sync-down`, first emit:
```
ℹ️  --sync-dev is deprecated; use --sync-down. Continuing with sync-down behaviour.
```

In normal operation, `.github/workflows/sync-down.yml` does this automatically
after every push to `main`. Run this command only when the Action has failed or
the user is operating offline.

**Pre-flight (run once):** verify the hotfix landed on `origin/main`:
```bash
git fetch origin
if ! git merge-base --is-ancestor "feat-<FEAT-ID>-<slug>" origin/main; then
    echo "⚠️  feat-<FEAT-ID>-<slug> is not yet an ancestor of origin/main."
    echo "   Open the PR and merge it first, then re-run with --sync-down."
    exit 1
fi
```

**Sync to `staging`** — optimistic auto-merge with safe abort on conflict:
```bash
git checkout staging
git pull --ff-only origin staging

if git merge --no-edit feat-<FEAT-ID>-<slug>; then
    git push origin staging
    echo "✅ staging synced with hotfix feat-<FEAT-ID>-<slug>."
    STAGING_OK=true
else
    git merge --abort
    STAGING_OK=false
    cat <<EOF
⚠️  Conflict syncing hotfix into staging. The merge has been aborted (no changes left).

    Resolve manually:
      git checkout staging
      git merge feat-<FEAT-ID>-<slug>
      # ...resolve conflicts in your editor...
      git commit
      git push origin staging

EOF
fi
```

**Sync to `dev`** — optimistic auto-merge with safe abort on conflict
(independent of `staging` outcome — always attempt):
```bash
git checkout dev
git pull --ff-only origin dev

if git merge --no-edit feat-<FEAT-ID>-<slug>; then
    git push origin dev
    echo "✅ dev synced with hotfix feat-<FEAT-ID>-<slug>."
    DEV_OK=true
else
    git merge --abort
    DEV_OK=false
    cat <<EOF
⚠️  Conflict syncing hotfix into dev. The merge has been aborted (no changes left).

    Resolve manually:
      git checkout dev
      git merge feat-<FEAT-ID>-<slug>
      # ...resolve conflicts in your editor...
      git commit
      git push origin dev

EOF
fi
```

**Return to base:** leave the user on `main` (the hotfix's base branch):
```bash
git checkout main
```

**Summary and exit code:**
```bash
if $STAGING_OK && $DEV_OK; then
    echo "✅ Sync-down complete: staging and dev are in sync with main."
    exit 0
else
    echo "⚠️  Sync-down partially failed. See above for failed targets."
    exit 1
fi
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
git worktree remove "$WORKTREES_DIR/feat-<FEAT-ID>-<slug>"
```
This also works with `IN_WORKTREE=1` (git allows removing the current
worktree, and the sandbox binds `$WORKTREES_DIR` writable), but the shell's
cwd disappears with it — make this the LAST filesystem step and run any
remaining git command as `git -C "$MAIN_ROOT" ...`.

If there are uncommitted changes in the worktree, warn:
```
⚠️  Worktree has uncommitted changes. Force remove? (y/N)
```

If the worktree was already removed, prune stale metadata:
```bash
git -C "$MAIN_ROOT" worktree prune
```

Optionally delete the local feature branch (it's been merged):
```bash
git -C "$MAIN_ROOT" branch -d feat-<FEAT-ID>-<slug>
```

### 12. Output

**Default (PR flow):**
```
✅ FEAT-<ID> — <title>: <N>/<total> tasks closed.

Closed:
  ✅ TASK-096 — Scene Editor Refactor (verified)
  ✅ TASK-097 — Visual Transitions (verified)

Index updated and committed.
Branch pushed: feat-<ID>-<slug>
PR opened: feat-<ID>-<slug> → <BASE_BRANCH>  <PR-URL>
Worktree removed: .claude/worktrees/feat-<ID>-<slug>
Local branch deleted: feat-<ID>-<slug>
```

**With `--merge`:**
```
✅ FEAT-<ID> — <title>: <N>/<total> tasks closed.

Closed:
  ✅ TASK-096 — Scene Editor Refactor (verified)
  ✅ TASK-097 — Visual Transitions (verified)

Index updated and committed.
Branch pushed: feat-<ID>-<slug>
Merged into <BASE_BRANCH>: feat-<ID>-<slug> ✅
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
✅ FEAT-<ID> — <title>: all <N> tasks closed.

Branch pushed. PR opened → <BASE_BRANCH>.
{if --merge} Merged into <BASE_BRANCH> directly. {end if}
Worktree cleaned up. Feature branch deleted.
{if --resolve-jira} Jira NAV-8036 → Done ✅ {end if}
```

## Reference
- Per-spec index files: `sdd/tasks/index/<feature>.json` (on `<base_branch>`)
- Active tasks: `sdd/tasks/active/` (on `<base_branch>`)
- Completed tasks: `sdd/tasks/completed/` (on `<base_branch>`)
- Frontmatter parser: `scripts/sdd/sdd_meta.py`
- SDD methodology: `sdd/WORKFLOW.md`

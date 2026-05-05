# /sdd-task — Decompose a Spec into SDD Tasks

Decompose an approved Feature Specification into atomic, assignable implementation tasks.

## Usage
```
/sdd-task sdd/specs/<feature-name>.spec.md
```

## Guardrails
- Only decompose specs with `status: approved`.
- Each task must be independently implementable and testable.
- Check `sdd/tasks/index/<feature>.json` for existing tasks to avoid duplication.
- Do NOT write implementation code — tasks are plans, not code.
- Mark tasks that can run in parallel worktrees with `parallel: true`.
- **Must run on the spec's `base_branch`** (read from frontmatter — `dev` for features, `main` for hotfixes). Not inside a worktree.
- **Always commit task files and per-spec index to `base_branch`** before creating the worktree.

## Steps

### 1. Sync the Base Branch (FEAT-145)

Read the spec's frontmatter to determine the base branch, switch to it, and pull from origin:

```bash
META=$(python -c "from pathlib import Path; from scripts.sdd.sdd_meta import parse; m = parse(Path('<spec-path>')); print(m.type, m.base_branch)")
TYPE=$(echo "$META" | awk '{print $1}')
BASE=$(echo "$META" | awk '{print $2}')

git checkout "$BASE"
git pull --ff-only origin "$BASE"
```

For `type: hotfix`, `BASE` MUST be `main`. For `type: feature`, `BASE` defaults
to `dev` and may be any non-main branch (sub-features extend a parent feature
branch — see `CLAUDE.md`).

**Abort conditions (do NOT stash or auto-resolve):**
- Working tree dirty: `⚠️  Cannot sync <BASE>: working tree has uncommitted changes. Stash or commit first, then re-run /sdd-task.`
- `--ff-only` fails: `⚠️  Cannot fast-forward <BASE>. Reconcile manually (git pull --rebase or merge), then re-run /sdd-task.`

**Refuse** if the user is currently inside a worktree:
```
⚠️  /sdd-task must run from the main repo on <BASE>, not inside a worktree.
   cd back to the main repo and re-run.
```

### 2. Read the Spec
Read the spec file provided by the user (e.g., `sdd/specs/<feature>.spec.md`).
- If spec is not `status: approved`, warn and ask to confirm.
- Extract: Feature ID, title, module breakdown, acceptance criteria, dependencies.

### 3. Plan Task Decomposition
Analyze the spec and identify atomic tasks:
- One task per module, class, or distinct deliverable.
- Order tasks to respect implementation dependencies.
- Aim for tasks completable in 1–4 hours each.

**Parallelism analysis:**
- Identify tasks within the spec that share NO files or imports with other tasks.
- Mark those tasks as `parallel: true` — they CAN run in separate worktrees.
- Tasks that import/extend code from a prior task in the same spec are `parallel: false` (default).
- Document the rationale in the `parallelism_notes` field.

**CRITICAL — Codebase Contract per Task (Anti-Hallucination):**
For EACH task, you MUST populate its `## Codebase Contract` section:

1. **Extract from the spec's Section 6 (Codebase Contract)**: copy the verified imports,
   signatures, and "Does NOT Exist" entries that are relevant to THIS specific task.
2. **Verify freshness**: `read` or `grep` each referenced file to confirm the signatures
   are still accurate. Code may have changed since the spec was written.
3. **Add task-specific references**: if the task touches files not covered by the spec's
   contract, read those files now and add their signatures.
4. **Be precise about scope**: only include imports/signatures the task actually needs.
   A task that modifies `parrot/tools/` does not need signatures from `parrot/loaders/`.
5. **Include the "Does NOT Exist" section**: this is the strongest anti-hallucination
   measure. List plausible-sounding things that an agent might assume exist but don't.

**Quality bar**: A task without a populated Codebase Contract section is incomplete.
The implementing agent (often Sonnet or Haiku) WILL hallucinate if not given
explicit, verified code anchors.

### 4. Generate Tasks
1. Ensure `sdd/tasks/active/` directory exists (create if needed).
2. Read the task template at `sdd/templates/task.md`.
3. For each task, create `sdd/tasks/active/TASK-<NNN>-<slug>.md` using the template.

**CRITICAL — Task file header must include the Feature ID:**
The `**Feature**:` line at the top of every task file MUST combine the formal
Feature ID and the human-readable feature title, separated by an em-dash:
```
**Feature**: FEAT-<NNN> — <Feature Title>
```
Example: `**Feature**: FEAT-015 — PlaywrightDriver`

Do NOT use the kebab-case slug alone (e.g., `**Feature**: playwrightdriver`) —
this loses the ability to trace which formal feature the task belongs to.
The slug is already captured in the `feature` field of `.index.json`; the
task header must surface the Feature ID for humans scanning the file.

Create or update the **per-spec index** at `sdd/tasks/index/<feature>.json`
(NOT the legacy monolith — that file is preserved as a historical artifact
and ignored by all FEAT-145 commands). Schema:

```json
{
  "feature": "<feature-slug>",
  "feature_id": "FEAT-<NNN>",
  "spec": "sdd/specs/<feature-slug>.spec.md",
  "type": "feature",
  "base_branch": "dev",
  "created_at": "<ISO-8601>",
  "completed_at": null,
  "tasks": [
    {
      "id": "TASK-<NNN>",
      "slug": "<slug>",
      "title": "<title>",
      "feature_id": "FEAT-<NNN>",
      "feature": "<feature-slug>",
      "spec": "sdd/specs/<feature>.spec.md",
      "status": "pending",
      "priority": "<high|medium|low>",
      "effort": "<S|M|L|XL>",
      "depends_on": [],
      "parallel": false,
      "parallelism_notes": "<rationale>",
      "assigned_to": null,
      "started_at": null,
      "completed_at": null,
      "file": "sdd/tasks/active/TASK-<NNN>-<slug>.md"
    }
  ]
}
```

**Header fields (`type`, `base_branch`)** are populated from the spec's
frontmatter (resolved in §1 above). If `sdd/tasks/index/<feature>.json`
already exists (created by the migration script for older specs), append
the new tasks to its `tasks[]` array — do NOT overwrite the header.

**Index location helper:**
```bash
INDEX="sdd/tasks/index/<feature-slug>.json"
mkdir -p "$(dirname "$INDEX")"
```

**Field clarification:**
- `feature_id`: Formal Feature ID from the spec (e.g., `"FEAT-014"`).
- `feature`: Kebab-case slug (e.g., `"videoreel-visual-changes"`).

### 5. Commit Tasks and Per-Spec Index to `<BASE>`

> **CRITICAL — Only commit the per-spec index and the new task files. NEVER
> commit unrelated changes.** Other files may be modified or unstaged in the
> working directory — do NOT touch them. Follow the exact sequence below.

```bash
# 1. Unstage everything first to ensure a clean staging area
git reset HEAD

# 2. Stage ONLY the per-spec index and new task files — NEVER use "git add ." or "git add -A"
git add sdd/tasks/index/<feature-slug>.json
git add sdd/tasks/active/TASK-*

# 3. Verify ONLY task files are staged (nothing else)
git diff --cached --name-only
# Expected: sdd/tasks/index/<feature-slug>.json and sdd/tasks/active/TASK-*.md only
# If ANY other files appear, run "git reset HEAD" and start over

# 4. Commit
git commit -m "sdd: add <N> tasks for FEAT-<ID> — <feature-name>"
```

### 6. Create the Feature Worktree

After committing to `dev`, create the worktree so it inherits the tasks:

```bash
git worktree add -b feat-<FEAT-ID>-<slug> \
  .claude/worktrees/feat-<FEAT-ID>-<slug> HEAD
```

### 7. Output
```
✅ Generated and committed <N> tasks for FEAT-<ID> — <feature-name>

Tasks created:
  TASK-<NNN> — <title> [<priority>/<effort>]
  ...

Feature worktree created:
  .claude/worktrees/feat-<FEAT-ID>-<slug>

Next:
  cd .claude/worktrees/feat-<FEAT-ID>-<slug>
  /sdd-start TASK-<NNN>   # begin first task
```

## Reference
- Task template: `sdd/templates/task.md`
- Index schema: `sdd/WORKFLOW.md` (section "Task Index Schema")
- Completed tasks go to: `sdd/tasks/completed/`
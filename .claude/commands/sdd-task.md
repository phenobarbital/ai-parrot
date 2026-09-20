# /sdd-task — Decompose a Spec into SDD Tasks

Decompose an approved Feature Specification into atomic, assignable implementation tasks.


## Usage
```
/sdd-task sdd/specs/<feature-name>.spec.md
/sdd-task sdd/specs/<feature-name>.spec.md --from-issue <issue-id>
```

`--from-issue <issue-id>` (FEAT-566, optional): seed one generated task from
an open ledger issue (`wikitoolkit ledger ready` / `/sdd-next`'s "Ready
ledger issues" section) instead of writing its Context/Scope from scratch.
Promotion is always explicit — no ledger issue is ever auto-promoted.

## Guardrails
- Only decompose specs with `status: approved`.
- Each task must be independently implementable and testable.
- Check `sdd/tasks/index/<feature>.json` for existing tasks to avoid duplication.
- Do NOT write the full implementation — but every task MUST carry an
  **Implementation Blueprint** (executor-ready per-file code blocks + why +
  `FILL IN` checklist, see §3). Blueprints stop at the mechanical parts;
  branches, edge cases and test bodies stay as `FILL IN` stubs.
- Build the task graph by §3's **Task graph rules** — `depends_on` is the only
  ordering, `parallel: false` means *exclusive* — and run
  `scripts/sdd/check_task_graph.py` on the index before committing (§4b).
- **`TASK-<NNN>` numbers are reserved via `scripts/sdd/reserve_ids.py`
  (FEAT-387), never hand-computed by scanning existing files for the
  highest number in use.** That scan-and-increment approach has no lock
  and no re-check against `origin/<base_branch>` immediately before
  committing, so two `/sdd-task` runs racing each other (e.g. concurrent
  dev-loop planner dispatches) can silently allocate the same number to
  different features. See §4 below.
- **Must run on the spec's `base_branch`** (read from frontmatter — `dev` for features, `main` for hotfixes). Not inside a worktree.
- **Always commit task files and per-spec index to `base_branch`** — they are
  versioned artifacts, and the machine that implements the feature pulls them
  from there. This command creates no worktree (FEAT-552).

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
to `dev` and may be `staging` (during a release freeze) or any non-main branch
(sub-features extend a parent feature branch — see `CLAUDE.md`).

**A hotfix normally does not reach this command at all (FEAT-466).**
`sdd-research.md` skips `/sdd-task` entirely for `type: hotfix` runs — a
one-or-two-commit bugfix is handled directly by the dev-loop's single-agent
path (spec §3 Module 2's "Interaction with Module 7": no per-spec task index
⇒ `DevelopmentNode._build_scheduler` returns `None` ⇒ single-agent dispatch,
made to honour the operator's declared dev agent by TASK-2506). If a human
invokes `/sdd-task` directly against a `type: hotfix` spec anyway (e.g. an
unusually large hotfix that genuinely benefits from decomposition), proceed
but see §4's hotfix branch below — it does **not** reserve `TASK-<NNN>` ids.
A hotfix's per-spec index header carries `"feature_id": null` (there is no
reserved `FEAT-<NNN>`) and a `"jira_issue_key"` field carrying the Jira key
instead — the identity the rest of the flow labels this run by.

**Validation:** if `TYPE == "feature"` and `BASE_BRANCH == "main"`, abort:
```
⚠️  type='feature' cannot base on 'main'. Features land on dev (default)
   or staging (during a release freeze). For changes that must base on
   main, set type='hotfix' in the document frontmatter.
```

Note: `staging` is a valid `base_branch` for `type: feature` during a release freeze
(FEAT-187). Use `base_branch: staging` when decomposing stabilization fixes for a
frozen release candidate.

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

**Task graph rules (`depends_on`, `parallel`, `parallelism_notes`):**

Every task runs in its own sub-worktree, dispatched by the `sdd-coder` engine as
soon as its `depends_on` are done; tasks whose dependencies are met run
**concurrently**. So the graph, not the prose, decides how long a feature takes
(querysource FEAT-147: 18 tasks chained 1→2→…→18 with one copy-pasted
rationale ran strictly in series for ~7 h).

- **`depends_on` is the ONLY ordering.** Add `B depends_on A` only with evidence:
  - B imports, calls, extends or tests a symbol A **creates**; or
  - B consumes a file/table/config/fixture A creates; or
  - B and A both **modify the same file** (serialize them: the lower id first).

  Never add an edge because tasks share a module, a spec section or a "phase", or
  "to be safe". A spec that says tasks run *sequentially* or *per-spec* means ONE
  feature worktree — it is NOT a dependency chain. Transitive edges may be
  omitted.
- **`parallel` defaults to `true`.** Set `parallel: false` (*exclusive* — never
  dispatched alongside any other task, even with its dependencies met) only when
  the task mutates shared state **outside its declared files**: rebuilding
  compiled extensions (Cython `make build-inplace`, maturin), editing dependency
  manifests or lockfiles (`pyproject.toml`, `uv.lock`), running DDL/migrations
  against a shared database, regenerating shared generated code, or changing a
  `conftest.py` other tasks' tests load.
- **`parallelism_notes` is per task and names its evidence**: for each
  `depends_on` edge, the dependency id plus the symbol/file it needs
  (`"imports TenantRegistry from TASK-716 (querysource/tenants.py)"`); for an
  exclusive task, the shared resource. Identical notes on several tasks is a
  defect.
- Write `"parallel_semantics": "exclusive"` in the index header (see schema) —
  without it the engine ignores every `parallel` flag.

**CRITICAL — Codebase Contract per Task (Anti-Hallucination):**
For EACH task, you MUST populate its `## Codebase Contract` section:

1. **Extract from the spec's Section 6 (Codebase Contract)**: copy the verified imports,
   signatures, and "Does NOT Exist" entries that are relevant to THIS specific task.
2. **Verify freshness**: `read` or `grep` each referenced file to confirm the signatures
   are still accurate. Code may have changed since the spec was written.
3. **Add task-specific references**: if the task touches files not covered by the spec's
   contract, read those files now and add their signatures.
4. **Be precise about scope**: only include imports/signatures the task actually needs.
   A task that modifies one module does not need signatures from unrelated modules.
5. **Include the "Does NOT Exist" section**: this is the strongest anti-hallucination
   measure. List plausible-sounding things that an agent might assume exist but don't.

**Quality bar**: A task without a populated Codebase Contract section is incomplete.
The implementing agent (often Sonnet or Haiku) WILL hallucinate if not given
explicit, verified code anchors.

**CRITICAL — Implementation Blueprint per Task (Executor Readiness, FEAT-545):**
For EACH task, you MUST populate its `## Implementation Blueprint` section so a
non-thinking executor (Haiku) can write the declared code to disk and complete
only the marked gaps:

1. **One block per file** listed in "Files to Create / Modify" — CREATE blocks
   are whole-file starting points; MODIFY blocks quote the verified anchor line
   they attach to (`# AFTER — insert below \`<anchor>\` (verified: path:NN)`).
   **MODIFY blocks MUST state the anchor's occurrence count**
   (`# occurrences: <N> (verified: grep -c '<anchor>' path)`); if `<N>` is `> 1`,
   the block is `# FILL IN: disambiguate — quote enough surrounding context (2–3
   lines) to make the anchor unique` instead of a bare one-line anchor.
2. **Mechanical code is complete**: imports, class/function signatures,
   docstrings, `self.logger` calls, registration/wiring, return types.
3. **Judgement calls are `FILL IN` stubs**: `# FILL IN: <decision> — bounded by
   <constraint | AC-N>`. Never leave a gap without the constraint that bounds it.
4. **Every import comes from the task's Verified Imports** — the blueprint may
   not introduce a symbol the Codebase Contract does not list.
5. **Derive from the spec's Interface Skeletons** (spec §3) and re-verify the
   anchors now; signatures fixed by the skeleton are not renegotiable.
6. **Size cap**: no block over ~80 lines. If a file needs more, split the task.
7. **Explain-for-executor rule**: every non-trivial decision is written as an
   imperative instruction *plus its reason* ("do X — because Y"), in the
   Steps list and in the **Why** paragraph under each block. Do not rely on
   the executor to infer intent.
8. **Steps (in order)** and the **FILL IN checklist** are mandatory even when
   a task has a single file.

**Quality bar**: A task without a populated Implementation Blueprint section is
incomplete — same bar as the Codebase Contract. If the blueprint would be the
full implementation, the task is too small; if it needs more than ~80 lines per
file, the task is too big.

### 4. Generate Tasks
1. Ensure `sdd/tasks/active/` directory exists (create if needed).
2. Read the task template at `sdd/templates/task.md`.
3. **Reserve task IDs — the mechanism depends on `TYPE` (FEAT-466):**

   **`TYPE == "feature"`** — reserve `TASK-<NNN>` IDs via the git-native
   compare-and-swap ledger (FEAT-387), never scan existing files and
   increment by hand:
   ```bash
   TASK_IDS=$(python -m scripts.sdd.reserve_ids --kind task --count <N> \
     --base-branch "$BASE" --label <feature-slug>)
   ```
   Where `<N>` is the total number of tasks about to be generated for this
   spec. On success this prints exactly `<N>` lines, one `TASK-<NNN>` per
   line, e.g.:
   ```
   TASK-1968
   TASK-1969
   TASK-1970
   ```
   `reserve_ids.py` pushes its own ledger-only commit to `origin/<BASE>` as
   part of this call (retrying internally on a non-fast-forward rejection);
   it refuses to run if tracked files have any uncommitted changes besides
   the ledger file. The commit is built on `origin/<BASE>` with git
   plumbing and pushed by sha, so local-only commits on `<BASE>` are
   neither published nor discarded by a lost race. If the command exits
   non-zero (retries exhausted, or the working tree wasn't clean), **STOP**
   and report the error to the user — do NOT fall back to hand-computing a
   number.

   **`TYPE == "hotfix"`** — do **NOT** call
   `reserve_ids.py --kind task`. A hotfix is not a feature and reserves no
   ledger id at all (same rationale as `/sdd-spec` §5's `FEAT-<NNN>` skip).
   Number tasks **locally within this spec only**, as
   `HOTFIX-<JIRA-KEY>-1`, `HOTFIX-<JIRA-KEY>-2`, … — these are literal
   string ids scoped to this hotfix's own index file, never compared
   against or drawn from `sdd/tasks/.id_ledger.json`'s `TASK-<NNN>`
   namespace. (Note: this is the defensive path for the rare case a human
   runs `/sdd-task` directly against a hotfix spec — the *normal* hotfix
   flow skips `/sdd-task` entirely; see §1 above.)
4. For each task, create `sdd/tasks/active/<id>-<slug>.md` using the
   template (`<id>` is `TASK-<NNN>` for a feature, `HOTFIX-<JIRA-KEY>-N`
   for a hotfix) — consume the reserved/assigned ids in order, one per
   task. Use each id verbatim for both the filename and every `id` field
   in the per-spec index; never invent, recompute, or reuse a `TASK-<NNN>`
   number outside of what `reserve_ids.py` returned.

   **`--from-issue <issue-id>` (FEAT-566):** the promoted task still gets a
   normally-reserved `TASK-<NNN>` from `reserve_ids.py` above — a ledger
   issue id is never used as (or in place of) a task id. Seed the task's
   Context/Scope from `wikitoolkit ledger context <issue-id>` (title, body,
   `about` targets), and link back to the source issue by including
   `discovered_from: <issue-id>` in the generated task's frontmatter/notes
   so `wikitoolkit ledger close <issue-id> --reason "promoted to TASK-<NNN>"`
   can be run once the task is filed. Promotion never runs `ledger close`
   automatically — that stays an explicit, separate step for the human/agent
   doing the promotion.
   **Deprecated (FEAT-572)**: `--from-issue` remains for one deprecation cycle but is no
   longer the ledger entry point — it can only append a task to an *existing* spec, which
   for a finished feature (per-spec index `completed_at` set) is wrong. Use `/sdd-fix
   <issue-id>` instead: it plans the issue's group, routes it to the Fast lane (branch → PR)
   or the SDD lane (reuse the open parent spec, else mint a fresh `FEAT-<NNN>`), and closes
   by evidence.
   Fill the template's `## Implementation Blueprint` section for every task
   per §3's rules; a task without one is incomplete.

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
  "parallel_semantics": "exclusive",
  "validation_contract": "required",
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
      "parallel": true,
      "parallelism_notes": "<per-task evidence: 'needs <symbol> from TASK-<X> (<file>)' | exclusive resource>",
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
the new tasks to its `tasks[]` array — do NOT overwrite the header. Do not add
`parallel_semantics` to an existing header whose tasks were written before these
rules: their `parallel: false` meant something else and would serialize them.

**Index location helper:**
```bash
INDEX="sdd/tasks/index/<feature-slug>.json"
mkdir -p "$(dirname "$INDEX")"
```

**Field clarification:**
- `feature_id`: Formal Feature ID from the spec (e.g., `"FEAT-014"`).
  **`null` for a hotfix** (FEAT-466 — no id reserved); use `jira_issue_key`
  as the identity instead.
- `feature`: Kebab-case slug (e.g., `"videoreel-visual-changes"`).

#### Delegation Contract (optional, per task)

Emit a `## Delegation Contract` packet ONLY for a task whose design is
complete. `design_complete: true` is a declaration the task author signs.

- List every target file with its `action` (`create`/`modify`), and give each
  `modify` target a REAL `expected_sha256` — compute it, never guess:
  `sha256sum <path>` or
  `python -c "import hashlib,sys;print(hashlib.sha256(open(sys.argv[1],'rb').read()).hexdigest())" <path>`.
- Every `create` target needs a block tagged `path=<target>` holding the new
  file's full content; every referenced block id must exist in the task file.
- Never leave placeholders (`...`, `TODO`, `FIXME`, `XXX`, `<angle>`,
  `raise NotImplementedError`) in an implementation block — the validator
  rejects them and the packet is not delegated.
- Hashes are re-validated at execution time, after dependencies land. If they
  are stale then, the executor refreshes the packet in the task file FIRST and
  only then re-runs `writer_generate`.
- Omit the section entirely when the task is not eligible. Most tasks are not,
  and that is the normal, expected route.

#### Validation Commands (mandatory, per task — FEAT-563)

Every generated task MUST carry a `## Validation Commands` section placed right
after `## Acceptance Criteria`: one bullet per command, each a backticked
`pytest` invocation whose operands are **test files or node ids** — never a
directory, never `tests/` or `packages/<dist>/tests`, never a bare `pytest`.

```markdown
## Validation Commands
- `pytest packages/ai-parrot/tests/flows/dev_loop/test_scope/test_mirror.py -q`
- `pytest tests/sdd_scripts/test_check_task_graph.py::test_validation_contract_findings -q`
```

This is what the sdd-coder guard rewrites a broad pytest to. New per-spec index
headers MUST include `"validation_contract": "required"`; `check_task_graph`
then reports `missing-validation-commands`, `broad-validation-command` and
`directory-validation-target` as errors (`validation-path-unknown` warns).

#### Complexity Contract (mandatory, per task)

Every generated task MUST carry a `## Complexity Contract` section containing
a JSON block with `schema_version: 1`.
- **`targets`**: A list of objects with `path` (repo-relative path) and
  `action` (`"CREATE"` or `"MODIFY"`, uppercase) matching the "Files to
  Create / Modify" table exactly.
- **`contract_symbols`**: A list of exact symbol IDs referenced by the
  Codebase Contract (e.g.,
  `"sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/models.py#RosterConfig"`).
  If there are no existing symbol references, use an empty list `[]` (do not
  omit the field — an absent list means legacy/unknown coverage).
- Legacy tasks without this section default to unknown complexity.
  Natural-language assurances cannot downgrade this — the deterministic
  evaluator, not the task author's prose, decides classification.

Example:
```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/complexity.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": []
}
```

### 4b. Validate the Task Graph

Run the deterministic graph check on the index you just wrote:

```bash
python -m scripts.sdd.check_task_graph sdd/tasks/index/<feature-slug>.json
```

- **Errors** (exit 1) block the commit: `file-overlap` (two tasks declare the
  same file with no dependency path between them — they would run concurrently
  and conflict), `unknown-dependency`, `cycle`. Fix the graph, re-run.
- **Every warning is resolved, not ignored**: `unjustified-edge` → remove the
  edge, or write its evidence in `parallelism_notes` (naming the dependency id);
  `possible-missing-dependency` → add the edge or confirm the reference is not
  a use; `duplicate-notes` / `exclusive-without-notes` → write per-task notes.
- FEAT-563 validation-contract codes: `missing-validation-commands`,
  `broad-validation-command`, `directory-validation-target` (errors when the
  header requires the contract) and `validation-path-unknown` (warning) — add
  or fix the task's `## Validation Commands` section.
- Copy the report's first line (`<N> tasks, <W> waves, max width <M>`) into the
  §6 output. A width of 1 on a multi-task feature needs a one-line justification.

### 5. Commit Tasks and Per-Spec Index to `<BASE>`

> **CRITICAL — Only commit the per-spec index and the new task files. NEVER
> commit unrelated changes.** Other files may be modified or unstaged in the
> working directory — do NOT touch them. Follow the exact sequence below.

> **CRITICAL — Only commit task files and the index. NEVER commit unrelated changes.**
> Other files may be modified or unstaged in the working directory — do NOT
> touch them. Follow the exact sequence below.

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

### 6. Output

Before printing the summary, count the delegation-eligible tasks. This is the
number the targeted writer will actually receive when the worker runs, so it
is worth seeing up front:

```bash
grep -l '^## Delegation Contract' sdd/tasks/active/TASK-*.md | wc -l
```

```
✅ Generated and committed <N> tasks for FEAT-<ID> — <feature-name>
   (hotfix: for Jira <KEY> — <feature-name>, no FEAT-<NNN>/TASK-<NNN> reserved)

Tasks created:
  TASK-<NNN> — <title> [<priority>/<effort>]      # feature
  HOTFIX-<JIRA-KEY>-<N> — <title> [<priority>/<effort>]  # hotfix

Blueprints: <N>/<N> tasks carry an Implementation Blueprint
Graph:      <N> tasks, <W> waves, max width <M>; exclusive: <ids or "none">
Delegated:  <D>/<N> tasks carry a Delegation Contract (targeted writer)
            TASK-<NNN>, TASK-<NNN>          # list them, or "none"

Worktree: not created. /sdd-task produces versioned artifacts only — the
          worktree is created by whoever implements, on the machine that
          implements (FEAT-552).

Next:
  /sdd-start <task-id>        # creates the worktree, then begins the task
  # or, unattended:  claude --agent sdd-worker --model sonnet --verbose
```

## Reference
- Task template: `sdd/templates/task.md`
- Index schema: `sdd/WORKFLOW.md` (section "Task Index Schema")
- Completed tasks go to: `sdd/tasks/completed/`

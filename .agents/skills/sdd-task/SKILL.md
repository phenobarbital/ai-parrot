---
name: sdd-task
description: Decompose an approved SDD spec into atomic task files, validate their contracts and dependency graph, and commit the per-spec task index.
---

# SDD Task

## Full procedure and Codex adaptations

Before executing, read the [full sdd-task procedure](../../../.claude/commands/sdd-task.md)
and the [Codex adaptation contract](../../../docs/sdd/CODEX.md#codex-adaptation-contract).
Follow the full procedure for details omitted from this summary. The adaptation
contract and the Codex-specific instructions below override Claude runtime syntax
and legacy shell examples; retain all workflow gates and evidence requirements.

Use this skill when the user asks to run `sdd-task`, decompose an approved spec,
or create SDD task artifacts.

Codex invocation: `$sdd-task sdd/specs/<feature-slug>.spec.md`.
Optional (FEAT-566): `$sdd-task sdd/specs/<feature-slug>.spec.md --from-issue <issue-id>`
seeds one task from an open ledger issue (`wikitoolkit ledger ready`) instead
of writing its Context/Scope from scratch. Promotion is always explicit —
no ledger issue is ever auto-promoted.

## Purpose

Create atomic, bounded, testable task artifacts from an approved spec and commit
them to the spec's base branch. This command creates no worktree (FEAT-552);
`$sdd-start` provisions it on the machine that implements the task.

## Guardrails

- Do not implement code.
- Only decompose an approved spec. If status is not `approved`, warn and ask
  for confirmation before proceeding.
- Must run from the main repo, not inside `.claude/worktrees/`.
- Must run on the spec's `base_branch`.
- Do not hand-compute `TASK-NNN` IDs for feature work.
- Use per-spec indexes under `sdd/tasks/index/`; ignore the historical
  monolithic `sdd/tasks/.index.json`.
- Commit only the task files and the per-spec index.

## Workflow

1. Read spec frontmatter with `scripts.sdd.sdd_meta.parse()`:
   - `type`
   - `base_branch`
2. Validate:
   - `hotfix` requires `main`
   - `feature` must not use `main`
   - `staging` is valid for feature stabilization during release freeze
3. Sync:
   - refuse if inside `.claude/worktrees/`
   - refuse dirty worktree
   - `git checkout <base_branch>`
   - `git pull --ff-only origin <base_branch>`
4. Read the full spec:
   - status
   - Feature ID or hotfix identity
   - title and slug
   - Module Breakdown
   - Test Specification
   - Acceptance Criteria
   - Codebase Contract
   - Worktree Strategy
5. Plan task decomposition:
   - one task per module, class, or distinct deliverable
   - target 1-4 hours per task
   - `depends_on` is the only ordering: add an edge only for a consumed symbol,
     file, fixture or configuration created by another task, or overlapping
     modified files (serialize overlapping writers, lower ID first)
   - shared modules, phases and per-spec isolation do not justify a dependency
   - `parallel` defaults to `true`; `parallel: false` means exclusive execution
     for mutations of shared state outside declared files, such as compiled
     extensions, dependency manifests/lockfiles, shared DDL or loaded conftest.py
   - write per-task `parallelism_notes` naming each dependency ID and the
     consumed symbol/file, or the shared resource requiring exclusivity
6. For every task, build a task-specific Codebase Contract:
   - copy relevant verified imports/signatures from the spec
   - re-read each referenced file to verify freshness
   - add task-specific references for touched files
   - include "Does NOT Exist" entries

#### Implementation Blueprint (mandatory, per task)

Populate `## Implementation Blueprint` from the spec's Interface Skeletons.
Use one block per declared file: CREATE blocks give whole-file starting points;
MODIFY blocks quote verified anchors and their occurrence counts. Disambiguate
non-unique anchors with surrounding context. Keep imports, signatures, wiring,
docstrings and types complete; every import must be in Verified Imports.
When the spec has a §6 Edit Sites table, start from its anchor rows and
re-run `grep -c` for each row used: code may have moved since spec creation.
If the count no longer matches, re-locate the anchor and correct the task
blueprint; if it is zero, stop and report drift. Derive anchors normally only
when an older spec has no Edit Sites table.
Bound remaining design decisions by their acceptance criteria. Include ordered
steps, a reason for each non-trivial instruction, and the template's FILL IN
checklist. No block should exceed about 80 lines; split oversized tasks.
Blueprint gaps are planning instructions only: completed implementation files
must contain no unfinished placeholders.

#### Validation Commands (mandatory, per task — FEAT-563)

Place `## Validation Commands` immediately after `## Acceptance Criteria`.
Use one backticked pytest command per bullet, targeting test files or node IDs;
never bare pytest or directory-wide test operands. Set new index headers to
`"validation_contract": "required"` so missing or broad commands fail validation.

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

7. Reserve task IDs:
   - For `type: feature`, run:
     `python -m scripts.sdd.reserve_ids --kind task --count <N> --base-branch <base_branch> --label <feature-slug>`.
   - Use returned IDs verbatim.
   - Stop if reservation fails.
   - For `type: hotfix`, do not reserve `TASK-NNN`; use local IDs
     `HOTFIX-<JIRA-KEY>-1`, `HOTFIX-<JIRA-KEY>-2`, and so on.
   - `--from-issue <issue-id>` (FEAT-566): the promoted task still gets a
     normally-reserved `TASK-NNN` here — a ledger issue id is never used as
     a task id. Seed Context/Scope from the selected issue and
     `wikitoolkit ledger context <issue.files...>` using repo-relative paths,
     not the issue ID. Preserve the selected FixPlan/claimed issue passed by
     `$sdd-fix`; a fresh ready-work query would omit that claimed issue.
     For standalone promotion locate the issue in `wikitoolkit ledger plan-fix --json`.
     Record `discovered_from: <issue-id>`. Filing a task is not resolution:
     run `wikitoolkit ledger close <issue-id>` separately only after implementation
     and validation, with the two-key evidence required by `$sdd-fix`.
     Deprecated (FEAT-572): prefer `sdd-fix <issue-id>`, which routes the issue's group to
     the Fast or SDD lane; `--from-issue` stays for one deprecation cycle only.
8. Create task files:
   - directory: `sdd/tasks/active/`
   - template: `sdd/templates/task.md`
   - filename: `TASK-NNN-<slug>.md` or `HOTFIX-<KEY>-N-<slug>.md`
   - `Feature` header must include `FEAT-NNN - <title>` for features
9. Create or update `sdd/tasks/index/<feature-slug>.json`:
   - preserve existing header if present
   - new headers include `"parallel_semantics": "exclusive"`; do not retrofit
     this onto legacy indexes whose `parallel: false` had different semantics
   - include `feature`, `feature_id`, `spec`, `type`, `base_branch`,
     `created_at`, `completed_at`, and `tasks[]`
   - each task entry includes id, slug, title, feature metadata, spec, status,
     priority, effort, dependencies, parallel fields, assignment timestamps,
     and file path
10. Validate the task graph before committing:
    - run `python -m scripts.sdd.check_task_graph sdd/tasks/index/<feature-slug>.json`
    - errors block the commit: fix file overlaps without dependency paths,
      unknown dependencies, cycles, and validation-contract errors, then rerun
    - resolve every warning: justify/remove edges, check possible missing
      dependencies, and replace generic parallelism notes with task evidence
    - report the task count, wave count and maximum width; justify width 1
      for multi-task features
11. Commit:
   - preserve unrelated staging; stop before committing if it is outside this run's scope
   - stage only `sdd/tasks/index/<feature-slug>.json` and new active task
     files
   - verify cached names
   - commit `sdd: add <N> tasks for FEAT-NNN - <feature-slug>`

## Output

Count the delegation-eligible tasks first, so the report shows how many tasks
the targeted writer will receive when the worker runs:

```bash
grep -l '^## Delegation Contract' sdd/tasks/active/TASK-*.md | wc -l
```

Report:

```text
Generated and committed <N> tasks for FEAT-NNN - <feature-slug>
Tasks created:
  TASK-NNN - <title> [priority/effort]
Delegated: <D>/<N> tasks carry a Delegation Contract (list them, or "none")
Graph: <N> tasks, <W> waves, max width <M>
Worktree: not created; sdd-start provisions it before implementation.
Next:
  $sdd-start TASK-NNN
```

## References

- `sdd/templates/task.md`
- `sdd/WORKFLOW.md`
- `scripts/sdd/sdd_meta.py`
- `scripts/sdd/reserve_ids.py`
- `scripts/sdd/check_task_graph.py`

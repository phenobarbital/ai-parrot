---
name: sdd-done
description: Verify a completed SDD feature worktree, check for merge blockers, snapshot ledger issues, stamp task verification, push or open the PR, optionally sync hotfixes down, and clean the worktree.
---

# SDD Done

## Full procedure and Codex adaptations

Before executing, read the [full sdd-done procedure](../../../.claude/commands/sdd-done.md)
and the [Codex adaptation contract](../../../docs/sdd/CODEX.md#codex-adaptation-contract).
Follow the full procedure for details omitted from this summary. The adaptation
contract and the Codex-specific instructions below override Claude runtime syntax
and legacy shell examples; retain all workflow gates and evidence requirements.

Use this skill when the user asks to run `sdd-done`, close a feature, push an
SDD worktree, open the feature PR, or clean up a completed SDD worktree.

Codex invocation: `$sdd-done FEAT-NNN [--dry-run] [--merge] [--force] [--sync-down]`.

## Purpose

Verify evidence in the feature worktree, check for merge blockers scoped to
the current feature, snapshot ledger issues on base branch, stamp verification
on the feature branch, push it, open or describe the PR, and remove the worktree
when safe.

## Guardrails

- Run from the main repo on the spec's `base_branch`, or from the feature
  worktree for the PR flow. `--merge` and `--sync-down` require the main repo.
- Do not modify the spec.
- Do not mark tasks done unless there is evidence in the worktree.
- Always show a verification report before writing closeout state.
- Never push directly to `main` and never merge into `main` (`--merge` with base `main` is refused before any push).
- `$sdd-done` opens the PR itself in every flow against `base_branch`, `main` included; on `gh` failure keep the worktree/branch, print the manual command and exit non-zero.
- A brief (`sdd/briefs/<slug>.index.json`, no FEAT id) uses its own lane: resolve by scanning worktrees, verify the per-brief index + Validation Commands, close in place, never check out a branch in the shared checkout; close its `ledger_issue` only after a confirmed merge.
- Use `--sync-down` only after the hotfix PR has merged to `main`.
- Use `--sync-dev` only as a deprecated alias for `--sync-down`.
- Merge gate checks apply only to `--merge` flag, not PR flow.
- Ledger snapshots use throwaway worktrees and never modify active worktrees.
- Hotfixes skip ledger snapshots.
- Bounded retry for rejected pushes (max 3 attempts).
- Required E2E evidence (FEAT-581) is checked before any index stamp, push,
  PR, merge or cleanup. Missing, stale, tampered, blocked or failed required
  evidence aborts closeout. `--force` bypasses per-task partial/missing
  evidence and ledger merge blockers only — it never bypasses a required
  E2E gate (spec AC9).
- The E2E check is read-only (`parrot e2e verify`); it never reruns the
  ordinary task test suite and never reads an exploration report —
  exploratory-tier scenarios can never satisfy the gate.

## Workflow

## Durable review boundary (FEAT-584)
Before feature review, settle owned attempts and supervised validations and close execution.
Unknown activity is a blocker, never evidence of an idle worktree. Persist the checkpoint,
record actual supported compaction outcome once per checkpoint/context, revalidate and start
a fresh reviewer. Unsupported contexts continue from checkpoint with an explicit reason.
Keep review criteria, adversarial checks, full lint, integration validation and ledger gates.
Changes after checkpoint require new hashes/evidence and invalidate old review coverage.
For sdd-done, preserve existing verification stamping, approval and push/merge policy;
do not run task closure again on base_branch and do not clean worktrees with unknown activity.

1. Resolve feature:
   - scan `sdd/tasks/index/*.json`, excluding `_orphans.json`
   - match `feature_id`, numeric suffix, exact feature slug, or slug substring
   - read `feature`, `feature_id`, `spec`, `type`, and `base_branch`
2. Verify branch and location:
   - resolve `MAIN_ROOT` from the absolute `git-common-dir` parent and
     `WORKTREES_DIR` as `<MAIN_ROOT>/.claude/worktrees`
   - compare absolute `git-dir` and `git-common-dir` to detect `IN_WORKTREE`
   - in the main checkout, current branch must equal `base_branch`
   - in a linked worktree, verify it is the selected feature's worktree;
     refuse `--merge` and `--sync-down` (including `--sync-dev`)
   - address primary-checkout paths through `MAIN_ROOT` / `WORKTREES_DIR`;
     never change to the primary checkout to bypass worktree restrictions
3. Locate worktree:
   - prefer `git worktree list` match for `feat-<FEAT-ID>` or hotfix branch
   - if missing, check remote/local branches and report next steps
4. Gather evidence per task:
   - commits matching task ID or slug in the worktree
   - files listed in each task's "Files to Create / Modify" table exist in the
     worktree
   - do not rerun the whole test suite here; tests should have run during task
     execution
4.5. Full lint pass, once per feature:
   - resolve changed Python files with `git diff --name-only --diff-filter=ACMR
     origin/<base_branch>...HEAD -- '*.py'` from the feature worktree
   - `--dry-run`: run only `ruff check` and report; never fix or commit
   - otherwise run Ruff fixes and the configured Black formatter on those
     files, inspect the diff, commit only those paths, then run full `ruff check`
   - keep fixes behavior-neutral; when behavior changes, run the feature-tier
     selector from `scripts.sdd.select_tests` with this feature's task files
     before committing; refresh checkpoint/review evidence after any change
   - report unfixable findings under Lint residual; residual `E9`, `F63`, `F7`
     or `F82` errors block normal closeout and enter the issues/confirmation path
4.6. Verify E2E evidence (FEAT-581/FEAT-703), before any stamp/push/
   merge-blocker/PR/merge/cleanup step below — the gate is code, not prose:
   - run `python -m scripts.sdd.check_e2e_closeout --spec <spec-path>
     --feat-id <FEAT-ID> --worktree <worktree>`; it reads the spec's
     `e2e.policy`, resolves the worktree-scoped plan at
     `sdd/state/<FEAT-ID>/e2e-plan.md`, and runs the same read-only validator
     the Claude twin uses — it never executes pytest or a target, only
     validates a previously persisted verdict, and never reads an
     `e2e-exploration.json` report (exploration can never satisfy this gate)
   - exit 0: record `E2E: <policy> - <status> (gate_satisfied: <bool>)` from
     the JSON on stdout and continue; `none` is exempt (no execution expected
     or fabricated) and `optional` outcomes are advisory only — never
     blocking, always reported with their real status, never upgraded to a pass
   - exit non-zero: abort the entire command now, before building the
     verification report — `--force` does not bypass this (spec AC9); it only
     overrides per-task partial/missing evidence and ledger merge blockers
     - before exiting, run the `on_failure` hooks (FEAT-764): write the hook context
       (step 4.8 fields, `abort_reason` = "E2E gate <status>") to
       `${SDD_HOOKS_ARTIFACT_ROOT:-/tmp/claude-$(id -u)/sdd-hooks}/<FEAT-ID>/context.json`, then
       `python -m scripts.sdd.run_closeout_hooks --event on_failure --context <ctx> --root <worktree> || true`;
       non-blocking, its exit code is ignored and it never changes the abort
   - the decision table itself (policy resolution, where a missing `e2e` key
     defaults to `optional` and a malformed value is never coerced; missing
     plans; validator errors; an uninstalled `ai-parrot-server`) lives in
     `scripts/sdd/check_e2e_closeout.py`, not here — the exit code is the
     contract, and the gate takes no `--force` argument at all
4.8. Closeout hooks — pre_pr (FEAT-764), after 4.7's test report and before step 6:
   - write the hook context JSON (`feat_id`, `spec_path`, `branch`, `base_branch`, `worktree`,
     `test_report_md` as the rendered report text, `e2e_gate` as the step 4.6 JSON object,
     `abort_reason` null, `dry_run`) to `${SDD_HOOKS_ARTIFACT_ROOT:-/tmp/claude-$(id -u)/sdd-hooks}/<FEAT-ID>/context.json`
   - run `python -m scripts.sdd.run_closeout_hooks --event pre_pr --context <ctx> --root <worktree>`
     (add `--dry-run` when `$sdd-done --dry-run`; pre_pr runs under dry-run). Its stdout JSON carries
     `results[]`, `pending_agents[]`, `blocking_failed` and `evidence_md`
   - exit 0: continue; keep `evidence_md` for the PR body (`## Evidence`) and the step 12 `Hooks:` line
   - exit 3 (agent hooks pending): for each `pending_agents[]` entry, native subagent dispatch is
     unavailable on Codex, so record it as unsupported: `python -m scripts.sdd.run_closeout_hooks --event pre_pr --feat-id <FEAT-ID> --root <worktree> --record <name> --status fail --summary "agent hooks unsupported on this host"`
     (run inline instead only if the host can actually run it); then
     `python -m scripts.sdd.run_closeout_hooks --event pre_pr --feat-id <FEAT-ID> --root <worktree> --finalize`
     and continue on exit 0
   - exit 1 (a blocking pre_pr hook failed) or exit 2 (config/usage error, e.g. malformed
     `.parrot/sdd_hooks.toml`): abort before step 8. Run the `on_failure` hooks as in step 4.6
     (`--event on_failure`, `abort_reason` set, `|| true`). `--force` does not bypass this
   - the pre_pr hook decision is the exit code; never re-derive it here
5. Classify:
   - `VERIFIED`: commit found and files exist
   - `PARTIAL`: commit found but files are missing
   - `NO EVIDENCE`: neither commits nor files support completion
6. Present verification report:
   - worktree
   - branch
   - commit count
   - task count by status
   - task-by-task evidence
   - E2E policy/status/gate_satisfied recorded in step 4.6
   - Test report (FEAT-695), never blocking: run
     `python -m scripts.sdd.test_report decide-rerun --index sdd/tasks/index/<feature-slug>.json`;
     when it says `rerun`, run in the background
     `timeout -k 10 1800 python -m scripts.sdd.select_tests --tier feature --base origin/<base_branch> --worktree <wt> --index <idx> $(printf -- '--task-file %s ' <every task file of the index>) --feature FEAT-<ID> --report-task _rerun --no-ledger --timeout 300 --run`;
     then `python -m scripts.sdd.test_report render --index <idx> --worktree <wt> --out "$TEST_REPORT_MD"`
     (always writes the file and exits 0; an unusable index renders a visible `## Tests — no data`
     section rather than failing — issue:326c8c0da36c)
     (a path under the report root). Report `Tests: <passed>/<tests> (<failed> failed) - re-run: done`. The feature tier always re-runs fresh at the final HEAD, driven by the index's `test_contract`; the table has New red / Baseline red / Unknown columns and a `cached` line, and the PR is blocked only by new reds or unknowns; baseline reds are reported, not blocking; rows are labeled `<runner>:<distribution>` with `n/a` for cache/baseline for non-pytest runners
   - lint residuals and any missing review evidence
7. Respect flags:
   - `--dry-run`: stop after the report
   - `--force`: allow forced closeout with partial/no evidence noted
   - otherwise ask before closing if any task is not verified
8. Stamp verification in the worktree branch (closing any task the lane left open):
   - require staging to contain only this feature's owned changes before the
     close step stages its moves; never reset unrelated staging
   - verified is not closed: for each task being closed whose file is still in
     `sdd/tasks/active/` or whose index status is not `done`/`done-with-issues`
     (lanes such as `/sdd-fix` commit code without closing), run
     `scripts/sdd/close_task.sh <TASK-ID> <feature-slug> <verification>` inside
     the worktree — never on `base_branch` (FEAT-414), then set its status to
     `done-with-issues` when verification is `partial`/`forced`; leave tasks
     the lane already closed untouched, and skip (with a warning) any id not in
     the index
   - set each task `verification` to `verified`, `partial`, or `forced` in
     `sdd/tasks/index/<feature>.json` inside the worktree
   - set feature `completed_at` only when all tasks are done
   - run `scripts/sdd/heal_orphans.sh <feature-slug>` inside the worktree
     (PR flow and `--merge` alike)
   - stage only the index and this feature's task files, verify cached names
   - commit `sdd: close tasks for FEAT-NNN - <feature-slug>`
8.1. Close resolved ledger issues (feature flows only, after step 8, before step 11's snapshot):
   - the `$sdd-fix` SDD lane hands issue closure to this step; without it fixed
     issues stay `claimed`/`open` after merge
   - run `python -m scripts.sdd.close_resolved_issues --worktree <worktree>
     --index sdd/tasks/index/<feature>.json --base origin/<BASE_BRANCH>
     --feature-id FEAT-NNN` inside the worktree (`--dry-run` to preview);
     strip any banner before the JSON report
   - links: a task's `**Discovered-from**: \`issue:<id>\`` line, or `issue:<id>`
     in the spec frontmatter (never the spec body)
   - two keys, fail-closed: every linked task `done` + `verified`, AND one of the
     issue's files in `git diff --name-only origin/<BASE_BRANCH>...HEAD`; closes with
     `ledger close --resolved-by task:TASK-NNN --actor agent:sdd-done`
   - report `skipped`/`read-only`/`error` rows (read-only →
     `(NOT closed: shared ledger is read-only)`); never fails `$sdd-done`
9. Push feature branch:
   - `git -C <worktree> push origin <branch>`
10. Check merge blockers (feature flows only):
    - If `--merge` flag is set and not a hotfix, run `wikitoolkit ledger blockers <FEAT-ID>`
    - The command prints plain-text blocker lines (never JSON) and exits non-zero
      exactly when blockers exist — gate on the **exit code**, not on parsing its output
    - If blockers found and not `--force`, refuse merge and list the blockers
      (`wikitoolkit ledger acknowledge <ISSUE-ID> --reason "..." --actor human:<name>`
      is how a human resolves one); before refusing, run the `on_failure` hooks
      (`abort_reason` = "merge blocked by critical ledger issues", `|| true`, exit code ignored)
    - If `--force`, warn but proceed with merge

11. Snapshot ledger issues (feature flows only):
    - For features (not hotfixes), `git fetch origin <BASE_BRANCH>` then create a
      throwaway detached worktree at `origin/<BASE_BRANCH>` (`git worktree add --detach`)
    - Run `wikitoolkit ledger export`, `wikitoolkit ledger export-log` and
      `wikitoolkit ledger rotate-log --older-than-days 30` there (this step is the only
      place rotation may run); only when `export` reports `(changed)`, `export-log`
      reports `(+N ...)` or `rotate-log` reports `Rotated`:
      `git add sdd/ledger/issues.jsonl sdd/ledger/events.jsonl` (plus `sdd/ledger/archive`
      when it exists), commit `sdd: ledger snapshot for <FEAT-ID>`,
      and `git push origin HEAD:<BASE_BRANCH>`
    - On cleanup, restore and clean `sdd/ledger` in the throwaway worktree
      (`git restore --staged --worktree -- sdd/ledger` + `git clean -fdq -- sdd/ledger`)
      so a stale untracked archive never survives a rejected push
    - On a rejected push, fetch and create a fresh throwaway worktree at the
      updated remote base, re-export, commit and retry — up to 3 attempts,
      then warn and continue without failing `$sdd-done`
    - Remove only clean, owned, idle throwaway worktrees without force; report
      any retained worktree requiring recovery instead of deleting its changes
    - Skip the snapshot entirely for hotfixes

12. Integrate:
    - If `base_branch == main` and `--merge` is set, refuse before any push; merging a `main` PR is the human act.
    - Without `--merge` (every flow, `main` included), run `gh pr create --base <base_branch> --head <branch>`; the PR body includes the
      rendered `## Tests` section (`$(cat "$TEST_REPORT_MD" 2>/dev/null)`) after `<N>/<total> tasks verified.`, followed by the
      pre_pr `evidence_md` as `## Evidence` when it is non-empty.
      Guard any `--body-file "$TEST_REPORT_MD"` fallback with `[ -s "$TEST_REPORT_MD" ]`.
    - If `gh` is missing, not authenticated or fails, keep the worktree/branch, print the manual command and exit non-zero.
    - If feature and `--merge`, merge into `base_branch`, run
      `scripts/sdd/heal_orphans.sh <feature-slug>`, commit any staged orphan
      cleanup, and push `base_branch`.
12.1. Closeout hooks — post_pr (FEAT-764), after step 12 and skipped under `--dry-run`:
    - set `pr_url` (PR flow) or `merge_sha` (`--merge`, the HEAD of the main repo after the merge)
      in the hook context, then run `python -m scripts.sdd.run_closeout_hooks --event post_pr --context <ctx> --root <worktree>`
    - agent hooks follow the same loop as 4.8 (`--event post_pr`, record unsupported as `fail`, then `--finalize`)
    - post_pr never aborts closeout; report its outcome in the step 12 output only
    - the Jira transition is now the opt-in `jira.transition` builtin in `.parrot/sdd_hooks.toml`
      (a `post_pr` hook); it skips with a note when the spec has no Jira key
13. Hotfix sync-down:
    - only with `--sync-down` or deprecated `--sync-dev`
    - verify feature branch is ancestor of `origin/main`
    - merge into `staging`, abort cleanly on conflict
    - merge into `dev`, abort cleanly on conflict
    - leave user on `main`
15. Cleanup:
    - remove the worktree only after successful push/PR or merge path
    - if running inside it, leave the feature worktree for an allowed directory
      before removing it; if host restrictions prevent this, report cleanup pending
    - if uncommitted changes exist in the worktree, ask before force removal
    - prune stale metadata if the worktree was already removed
    - delete local feature branch only when safe and merged/pushed

## Output

Report:

```text
FEAT-NNN - <title>: <closed>/<total> tasks closed
Branch pushed: <branch>
PR opened: <url> or manual command printed
Ledger: closed issue:<id> (task:TASK-NNN) / skipped issue:<id> - <reason>
E2E: <policy> - <status> (gate_satisfied: <bool>)
Hooks: pre_pr <n pass / m fail>, post_pr <n pass / m fail, or skipped (--dry-run)>
Hook evidence: <absolute artifact paths from evidence_md, or none>
Tests: <passed>/<tests> (<failed> failed) - re-run: done
Worktree removed: .claude/worktrees/<name>
```

## References

- `sdd/tasks/index/<feature>.json`
- `sdd/tasks/active/`
- `sdd/tasks/completed/`
- `scripts/sdd/sdd_meta.py`
- `scripts/sdd/heal_orphans.sh`
- `sdd/WORKFLOW.md`
- `sdd/state/<FEAT-ID>/e2e-plan.md` (E2E plan, FEAT-581); validator:
  `parrot e2e verify --plan <path>` (`ai-parrot-server`, optional install)

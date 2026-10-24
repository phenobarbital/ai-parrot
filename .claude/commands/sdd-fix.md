# /sdd-fix — Ledger-Driven Fix Lane

Drain the SDD work ledger: plan a severity-ordered, file-grouped batch with
`wikitoolkit ledger plan-fix --json`, claim the selected issues, route each group to the
Fast lane (branch → PR) or the SDD lane (spec → tasks → worktree), close by evidence and
release the rest. The twins never re-implement ordering, grouping or lane rules — the plan is
the contract (`planner_version` is checked before use).

**Read-only ledger**: the ledger resolves to the main checkout. If a sandbox makes it read-only,
report `shared ledger is read-only`, do not request broader filesystem access, do not create a
worktree-local ledger, and exit non-zero WITHOUT claiming anything.

## Usage
/sdd-fix                          # interactive picker, severity-ordered
/sdd-fix <issue-id>               # non-interactive: that issue's whole group
/sdd-fix --top N                  # non-interactive: first N groups
/sdd-fix ... --kind K --severity S --lane fast|sdd   # --lane fast is REFUSED (exit 1) for critical or vulnerability groups

## Steps
1. **Plan** — `wikitoolkit ledger plan-fix --json` (pass `--kind/--severity/--lane` through). Parse stdout as a FixPlan.
   Require a successful exit and `planner_version == "1"` before selecting or claiming anything.
   Reject missing/unsupported versions or malformed output; never re-implement ordering, grouping or lane rules.
   `--lane fast` is refused for critical or vulnerability groups; stop on that planner error.
   The plan presents severity-ordered groups with metadata: group_id, max_severity, lane assignment with reason,
   suggested_slug, and the list of issues/files per group. In interactive mode, render a table showing each group's
   key attributes for selection.
2. **Select** — picker, or deterministic resolution from the arguments (issue-id → its whole group; --top N → first N groups).
   Require a positive N. An empty plan or an issue absent from it is a no-op with an explanation, never a guessed selection.
3. **Claim** — one `wikitoolkit ledger claim <issue-id> --actor agent:sdd-fix` per issue in the group, immediately before
   executing. The plan is a snapshot; the claim is authoritative: a non-zero exit DROPS that issue and continues. Never close an
   issue merely because an earlier plan listed it. Skip groups with no successful claims; preserve the planned lane for remaining issues.
4. **Prime** — `wikitoolkit ledger context <group.files…> --max-tokens 3000` (full repo-relative paths from the plan, never basenames).
5. **Route** by `group.lane`:
   - NEVER switch the main checkout's branch and never require it to be clean; every lane
     works inside a worktree provisioned by `python -m scripts.sdd.ensure_worktree`.
     If execution cannot proceed, release successful claims in step 7.
   - **Fast lane** (`lane == "fast"`): one worktree and one PR per group.
     `python -m scripts.sdd.ensure_worktree --json --slug <suggested_slug> --brief-key <issue-short-id> --base-branch dev`
     plans `fix-<issue-short-id>-<suggested_slug>` off `origin/dev` and returns `<wt>`;
     `--base-branch dev` is what selects the `fix-` prefix. Edit inside `<wt>`, run the affected
     package's tests from `<wt>` with `PYTHONPATH=packages/<dist>/src` (a bare `pytest` there
     imports the main checkout), `ruff check --fix` the changed files, `git -C <wt> commit`,
     `git -C <wt> push -u origin fix-<issue-short-id>-<suggested_slug>` (the tree has no
     upstream by design), then `gh pr create --base dev --title … --body …`.
     ALWAYS a PR — there is no direct-push path. Once step 6 has closed the group's issues, reap
     the tree: `python scripts/remove_worktree.py remove fix-<issue-short-id>-<suggested_slug>`
     — never `--force`, never `--delete-branch` (the PR needs the remote branch). A refusal
     means something is uncommitted or unpushed: keep the tree and report it.
   - **SDD lane** (`lane == "sdd"`): if any `group.parents[].open` is true, reuse that parent spec (`/sdd-task <spec> --from-issue …` per issue);
     otherwise `python -m scripts.sdd.reserve_ids --kind feature --count 1 --base-branch dev --label <suggested_slug>`, author
     `sdd/specs/<suggested_slug>.spec.md` from the group, `/sdd-task`, then
     `python -m scripts.sdd.ensure_worktree --slug <suggested_slug> --feature-id FEAT-<NNN>`. `/sdd-done <FEAT-ID>` closes it out, including the issues its verified tasks resolve.
     For a new spec, the slug comes from `suggested_slug`; never re-derive it. For a reused parent,
     use that parent index's existing slug, feature_id, spec and base_branch when provisioning the worktree.
     Task creation alone is not resolution: implement and validate the task in that worktree before step 6.
     Every task filed for an issue MUST carry `` **Discovered-from**: `issue:<id>` `` — that link is how
     `/sdd-done` finds the issue to close. If implementation does not finish in this session, hand the claim off (step 7).
6. **Close** — two keys, fail-closed: an issue closes only if the implementing agent asserts its id as resolved AND at least one of
   its `files` appears in `git diff --name-only <base>...HEAD`. Then `wikitoolkit ledger close <issue-id> --reason "<what changed>"
   --actor agent:sdd-fix --resolved-by commit:<sha>` (fast, the implementing commit on the pushed PR branch)
   or `--resolved-by task:TASK-<NNN>` (SDD, a completed and validated task).
   Capture `<base>` before implementation and check the diff from the implementing checkout.
   Do not infer a merge or fabricate a merge SHA merely because a PR was opened.
7. **Release** — every claimed issue that failed either key: `wikitoolkit ledger unclaim <issue-id> --reason "<why>" --actor agent:sdd-fix`.
   Run release on every exit path, including test/push/PR failures or interrupted execution.
   If unclaim itself fails, report the issue ID and reason for recovery; do not claim success.
   Never leave an issue claimed silently; acknowledgement stays human-only and out of scope here.
   **SDD-lane hand-off**: an issue whose `Discovered-from` task is filed in the feature's per-spec index but not yet
   implemented STAYS claimed and is reported as `handed off to /sdd-done <FEAT-ID>`, which closes it by the same two
   keys once the task is verified. Release it instead when no filed task cites it.
   **Fast-lane failure**: when tests, commit, push or `gh pr create` fails, KEEP the worktree,
   report its path, and unclaim every issue claimed for that group. Never reap a tree whose
   work is not on origin, and never force-push to rescue a rejected push.

## Output
Per group processed:
- Lane used (Fast/SDD)
- Branch/PR URL (Fast) or FEAT-ID + worktree path (SDD)
- Issues closed with their resolved_by evidence
- Issues released with reason
- Issues handed off to `/sdd-done <FEAT-ID>` (SDD lane)

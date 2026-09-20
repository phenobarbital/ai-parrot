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
   - Before changing branches, require a clean checkout; never carry unrelated changes into a fix.
     If execution cannot proceed, release successful claims in step 7.
   - **Fast lane** (`lane == "fast"`): in the MAIN checkout (no worktree), `git fetch origin dev && git switch -c fix/<issue-short-id>-<suggested_slug> origin/dev`,
     edit, run the affected package's tests, commit, `git push -u origin <branch>`, then `gh pr create --base dev --title … --body …`.
     ALWAYS a PR — there is no direct-push path.
   - **SDD lane** (`lane == "sdd"`): if any `group.parents[].open` is true, reuse that parent spec (`/sdd-task <spec> --from-issue …` per issue);
     otherwise `python -m scripts.sdd.reserve_ids --kind feature --count 1 --base-branch dev --label <suggested_slug>`, author
     `sdd/specs/<suggested_slug>.spec.md` from the group, `/sdd-task`, then
     `python -m scripts.sdd.ensure_worktree --slug <suggested_slug> --feature-id FEAT-<NNN>`. `/sdd-done <FEAT-ID>` closes it out unchanged.
     For a new spec, the slug comes from `suggested_slug`; never re-derive it. For a reused parent,
     use that parent index's existing slug, feature_id, spec and base_branch when provisioning the worktree.
     Task creation alone is not resolution: implement and validate the task in that worktree before step 6.
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

## Output
Per group processed:
- Lane used (Fast/SDD)
- Branch/PR URL (Fast) or FEAT-ID + worktree path (SDD)
- Issues closed with their resolved_by evidence
- Issues released with reason

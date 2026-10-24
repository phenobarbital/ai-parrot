# TASK-4695: Fast lane provisions, works in, and reaps its own worktree (three `/sdd-fix` twins)

**Feature**: FEAT-740 — Fast lane runs in its own worktree (never the main checkout)
**Spec**: `sdd/specs/sdd-fix-brief-change.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Implements spec §3 **Module 1**. `/sdd-fix`'s Fast lane is currently told to
`git switch -c fix/<id>-<slug>` *in the main checkout*, which moves the shared
checkout off `dev`, collides with parallel sessions, requires a clean main tree,
and never switches back. This task rewrites that instruction so the lane
provisions a `fix-<id>-<slug>` worktree through `scripts.sdd.ensure_worktree`,
does all work inside it, opens the PR, and reaps the tree with
`scripts/remove_worktree.py` — and adds the Fast-lane failure rule to Step 7.

The procedure exists in three surfaces whose bodies a test asserts are
**byte-identical** (spec §3 M1 CRITICAL constraint). This task owns all three.

---

## Scope

- Replace Step 5's first two bullets (the clean-checkout precondition and the
  Fast-lane bullet) with the spec's Interface Skeleton text, in all three twins.
- Append the **Fast-lane failure** paragraph to the end of Step 7, in all three twins.
- Keep the three bodies byte-identical (only frontmatter, the title line and
  `$sdd-` vs `/sdd-` may differ — and the edited blocks contain no `sdd-` command
  references, so they are identical text in all three).

**NOT in scope**:
- The SDD-lane bullet of Step 5, and Steps 1–4 and 6 — unchanged (spec §1 Non-Goals).
- The intro paragraph's "Fast lane (branch → PR)" wording and the Output
  section's "Branch/PR URL (Fast)" line — both remain accurate (a branch and a PR
  are still produced) and the spec does not change them. Leave them.
- `docs/sdd/*`, `worktree-management` — TASK-4696. `/sdd-brief` — TASK-4697.
- Any new test or test edit (spec §8 Q2: "prose only").
- Any file under `scripts/` or `packages/` (spec AC-11).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `.claude/commands/sdd-fix.md` | MODIFY | Step 5 Fast lane rewrite + Step 7 Fast-lane failure rule |
| `.agent/workflows/sdd-fix.md` | MODIFY | Identical edit (Antigravity twin) |
| `.agents/skills/sdd-fix/SKILL.md` | MODIFY | Identical edit (Codex twin) |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: Use exactly the commands and flags listed here. The edited text is
> prose that instructs agents to run these CLIs — a wrong flag in the doc is a bug.

### Verified Imports
None — this task edits Markdown only; it imports nothing.

### Existing Signatures to Use
```text
# scripts/sdd/ensure_worktree.py — CLI the new Fast-lane text instructs
--slug           (line 298, required)
--brief-key      (line 305)  help: "Brief identity (FEAT-698 /sdd-brief): Jira key, ledger short id,
                             or slug. Plans hotfix-<KEY>-<slug> on main (default) or fix-<KEY>-<slug>
                             on --base-branch; mutually exclusive with --feature-id, --jira-key and --type."
--base-branch    (line 313)
--json           (line 317)  prints JSON instead of a bare path

# scripts/sdd/brief_meta.py — why --base-branch dev yields the fix- prefix
def brief_worktree_plan(*, slug: str, key: str, base_branch: str) -> WorktreePlan:   # line 150
    prefix = "hotfix" if base_branch == "main" else "fix"                            # line 166
    name = f"{prefix}-{key}-{slug}"                                                  # line 167
BRIEF_BASE_BRANCHES = frozenset({"main", "dev", "staging"})                          # line 27
_SAFE_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")                           # line 28  (a hex ledger short id passes)

# scripts/remove_worktree.py — the reaper the new text instructs
sub.add_parser("remove", ...)   # line 405 ; positional target at 406
--delete-branch                 # line 410  (the new text FORBIDS it)
--force                         # line 412  (the new text FORBIDS it)
REFUSED: <n> uncommitted change(s).   # line 300  — refusal on a dirty tree
REFUSED: <n> commit(s) not on origin. # line 311  — refusal on unpushed commits
```

### Test contract the edit must keep green (`tests/sdd/test_ledger_workflow_twins.py::TestFixTwins`)
```text
test_complete_procedure_is_identical_across_hosts (line 196): strips frontmatter, drops the first body
    line, maps "$sdd-" -> "/sdd-", then asserts the three bodies are EQUAL.
Must stay present in every twin: "gh pr create --base dev", "wikitoolkit ledger plan-fix --json",
    "Fast lane", "SDD lane", "--lane", "ledger close", "--resolved-by", "two keys", "ledger unclaim",
    "ledger claim", "parents", "reserve_ids", "ensure_worktree", "shared ledger is read-only",
    "ledger context", "--max-tokens 3000"
Must stay ABSENT from every twin: "git push origin dev", "--no-pr", "ledger acknowledge"
tests/sdd_scripts/test_command_contracts.py: no command may contain "git worktree add"
```

### Does NOT Exist
- ~~`ensure_worktree --fix-key`~~ — not a flag; the identity flags are `--feature-id`, `--jira-key`, `--brief-key` only.
- ~~`ensure_worktree --remove`~~ / ~~`--recreate`~~ — no such flags.
- ~~`scripts/sdd/remove_worktree.py`~~ — the reaper is `scripts/remove_worktree.py` (scripts root, NOT `scripts/sdd/`).
- ~~`scripts/sdd/fix_lane.py`~~ — no Fast-lane driver script exists, and this task must not create one.
- ~~`/sdd-fix --worktree`~~ — not a flag.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": ".claude/commands/sdd-fix.md", "action": "MODIFY"},
    {"path": ".agent/workflows/sdd-fix.md", "action": "MODIFY"},
    {"path": ".agents/skills/sdd-fix/SKILL.md", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:scripts/sdd/brief_meta.py#brief_worktree_plan",
    "sym:scripts/sdd/ensure_worktree.py#main"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Write the replacement text ONCE and apply it byte-for-byte to all three files —
  because `TestFixTwins` compares the bodies for equality; a single differing space fails it.
- Keep the house style: numbered step, bold step name, two-space-deeper continuation
  lines under a `   - ` bullet, inline backticked commands, `…` (U+2026) where the
  original uses it (`--title … --body …`).
- `--base-branch dev` is load-bearing — because without it `brief_worktree_plan()`
  defaults to the `hotfix-` prefix on `main` (spec §7 Known Risks). Never drop it.
- Do not add `--force` or `--delete-branch` anywhere except inside the explicit
  "never `--force`, never `--delete-branch`" phrase.

### References in Codebase
- `.claude/commands/sdd-brief.md` Steps 9–11 — the same provision → work in `<wt>` → `git -C <wt> push -u` shape, already in production.

---

## Implementation Blueprint

### Steps (in order)
1. Re-run the anchor counts below; each must be `1` — *why*: a different count means the file moved since 87341f43c and the line numbers here are stale.
2. In `.claude/commands/sdd-fix.md`, replace the **5 lines 34–38** (from `   - Before changing branches…` through `     ALWAYS a PR — there is no direct-push path.`) with Block A — *why*: those lines are the precondition + Fast-lane bullet the spec replaces; the `5. **Route**` header on line 33 and the SDD-lane bullet starting line 39 stay.
3. In the same file, insert Block B immediately **after line 60** (`   keys once the task is verified. Release it instead when no filed task cites it.`) — *why*: the failure rule belongs at the end of Step 7, after the SDD-lane hand-off, before the blank line that precedes `## Output`.
4. Apply the identical two edits to `.agent/workflows/sdd-fix.md` (lines 38–42, insert after 64) and `.agents/skills/sdd-fix/SKILL.md` (lines 39–43, insert after 65) — *why*: twin parity is asserted.
5. Diff the three bodies yourself before running tests (`diff <(sed -n '/^5\. \*\*Route/,/^## Output/p' A) <(… B)`) — *why*: catches whitespace drift faster than the test's single assert.
6. Run the Validation Commands.

### `.claude/commands/sdd-fix.md` (MODIFY) — Block A
```text
# occurrences: 1 (verified: grep -cF '   - Before changing branches, require a clean checkout' .claude/commands/sdd-fix.md)
# occurrences: 1 (verified: grep -cF 'in the MAIN checkout (no worktree)' .claude/commands/sdd-fix.md)
# REPLACE lines 34-38 (verified: .claude/commands/sdd-fix.md:34 and :36) — current text:
#   - Before changing branches, require a clean checkout; never carry unrelated changes into a fix.
#     If execution cannot proceed, release successful claims in step 7.
#   - **Fast lane** (`lane == "fast"`): in the MAIN checkout (no worktree), `git fetch origin dev && git switch -c fix/<issue-short-id>-<suggested_slug> origin/dev`,
#     edit, run the affected package's tests, commit, `git push -u origin <branch>`, then `gh pr create --base dev --title … --body …`.
#     ALWAYS a PR — there is no direct-push path.
# WITH:
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
```
**Why this shape**: verbatim from spec §3 M1 Interface Skeleton. It removes the two
defective instructions (main-checkout branch switch, clean-checkout precondition) and
encodes all five resolved decisions: per-group worktree (AC-4), inline PR, immediate
reap via the guarded reaper (AC-3), in-worktree test prefix (AC-6). Keep
`gh pr create --base dev` and `ensure_worktree` literally — tests grep for both.

### `.claude/commands/sdd-fix.md` (MODIFY) — Block B
```text
# occurrences: 1 (verified: grep -cF 'keys once the task is verified. Release it instead when no filed task cites it.' .claude/commands/sdd-fix.md)
# AFTER — insert below `   keys once the task is verified. Release it instead when no filed task cites it.` (verified: .claude/commands/sdd-fix.md:60)
   **Fast-lane failure**: when tests, commit, push or `gh pr create` fails, KEEP the worktree,
   report its path, and unclaim every issue claimed for that group. Never reap a tree whose
   work is not on origin, and never force-push to rescue a rejected push.
```
**Why**: spec §8 resolved decision "keep worktree, release claims" (AC-5). The wording
deliberately avoids the literal `git push origin dev` (forbidden by
`test_all_twins_require_a_pr_on_the_fast_lane`).

### `.agent/workflows/sdd-fix.md` (MODIFY)
```text
# occurrences: 1 each (verified: same three grep -cF commands as above, on this file)
# Block A: REPLACE lines 38-42 (verified: .agent/workflows/sdd-fix.md:38 and :40)
# Block B: insert AFTER line 64 (verified: .agent/workflows/sdd-fix.md:64)
# Content: byte-identical to Blocks A and B above.
```
**Why**: twin parity (`test_complete_procedure_is_identical_across_hosts`).

### `.agents/skills/sdd-fix/SKILL.md` (MODIFY)
```text
# occurrences: 1 each (verified: same three grep -cF commands as above, on this file)
# Block A: REPLACE lines 39-43 (verified: .agents/skills/sdd-fix/SKILL.md:39 and :41)
# Block B: insert AFTER line 65 (verified: .agents/skills/sdd-fix/SKILL.md:65)
# Content: byte-identical to Blocks A and B above.
```
**Why**: twin parity. This file also must keep `wikitoolkit ledger plan-fix --json`
(`tests/sdd/test_codex_sdd_sync.py:44`) — untouched by this edit.

### FILL IN checklist
- [ ] none — every line of both blocks is fixed by the spec. If a re-run anchor count is not `1`, STOP and report drift; do not re-locate by guesswork.

---

## Acceptance Criteria

- [ ] AC-1: `grep -lF 'in the MAIN checkout (no worktree)' .claude/commands/sdd-fix.md .agent/workflows/sdd-fix.md .agents/skills/sdd-fix/SKILL.md` prints nothing, and `grep -cF 'require a clean checkout'` is `0` in all three.
- [ ] AC-2: `grep -cF -e '--brief-key <issue-short-id> --base-branch dev'` is `1` in each twin.
- [ ] AC-3: each twin contains `python scripts/remove_worktree.py remove fix-<issue-short-id>-<suggested_slug>` and `never \`--force\`, never \`--delete-branch\``.
- [ ] AC-4: each twin contains `one worktree and one PR per group`.
- [ ] AC-5: each twin contains `**Fast-lane failure**`.
- [ ] AC-6: each twin contains `PYTHONPATH=packages/<dist>/src`.
- [ ] AC-7: `TestFixTwins` passes (bodies byte-identical).
- [ ] Only the three files above are modified (`git diff --name-only` lists exactly them).

---

## Validation Commands

- `pytest tests/sdd/test_ledger_workflow_twins.py::TestFixTwins -q`
- `pytest tests/sdd/test_codex_sdd_sync.py -q`
- `pytest tests/sdd_scripts/test_command_contracts.py -q`

---

## Test Specification

No new tests (spec §8 Q2 — "prose only"). The existing suite above is the gate;
it was **93 passed** on `dev` at `02d113e88` together with the TASK-4696/4697 suites,
so any red after this edit is caused by this edit.

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`python -m scripts.sdd.ensure_worktree --slug sdd-fix-brief-change --feature-id FEAT-740`)
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — none for this task
4. **Verify the Codebase Contract** — re-run the `grep -cF` anchor counts before editing
5. **Update status** in `sdd/tasks/index/sdd-fix-brief-change.json` → `"in-progress"`
   (set `started_at`) and commit only that index file
6. **Implement** — apply Blocks A and B to all three twins exactly
7. **Verify** — run the Validation Commands from the worktree root (these tests read files
   relative to `Path(__file__)`, so no `PYTHONPATH` is needed for them)
8. **Commit the code** — stage only the three twin files (never `git add .` / `-A`)
9. **Close the task** with `scripts/sdd/close_task.sh TASK-4695 sdd-fix-brief-change verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any

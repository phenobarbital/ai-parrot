# TASK-3394: Author the three `/sdd-fix` command twins (Claude, Antigravity, Codex)

**Feature**: FEAT-572 — `/sdd-fix` Ledger-Driven Fix Lane
**Spec**: `sdd/specs/sdd-fix-ledger-lane.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3392
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 5 and §2 Overview (fast lane / SDD lane / two-key close / snapshot-vs-claim).
`/sdd-fix` is the operator- and agent-facing procedure that drains the ledger. Three twins,
one behaviour: every twin shells out to `wikitoolkit ledger plan-fix --json` (TASK-3392) and
parses the `FixPlan`; none re-implements ordering, grouping or lane logic. Any behavioural
statement added to one twin must appear in all three — `TestFixTwins` (TASK-3396) enforces
the token contract below.

This is the one module the spec marks **not delegation-eligible**: the procedure is fixed,
the wording is authored per platform.

---

## Scope

- CREATE `.claude/commands/sdd-fix.md`, `.agent/workflows/sdd-fix.md`,
  `.agents/skills/sdd-fix/SKILL.md` following the platform formats of the `sdd-codereview`
  twins.
- Document exactly the seven steps of spec §3 M5 (Plan → Select → Claim → Prime → Route →
  Close → Release), both lanes, the two-key fail-closed close, the snapshot/claim rule (S3),
  the S7 override guard, the read-only-ledger discipline, and the "never `ledger acknowledge`"
  rule.
- Satisfy the **twin token contract** (below) verbatim — it is what TASK-3396 asserts.

**NOT in scope**: modifying `/sdd-next` or `/sdd-task` twins (TASK-3395); the tests
(TASK-3396); docs (TASK-3398); any Python.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `.claude/commands/sdd-fix.md` | CREATE | Claude Code slash command |
| `.agent/workflows/sdd-fix.md` | CREATE | Antigravity workflow (frontmatter `description:`) |
| `.agents/skills/sdd-fix/SKILL.md` | CREATE | Codex skill (frontmatter `name:` / `description:`) |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
*(markdown task — no Python imports)*

### Existing Signatures to Use
```text
# Platform formats to mirror (verified 2026-09-18):
.claude/commands/sdd-codereview.md:1        "# /sdd-codereview — Code Review a Completed SDD Task"   (no frontmatter)
.agent/workflows/sdd-codereview.md:1-3      "---\ndescription: <one line>\n---" then "# /sdd-codereview — …"
.agents/skills/sdd-codereview/SKILL.md:1-4  "---\nname: sdd-codereview\ndescription: <one line>\n---" then "# SDD Code Review"
# Read-only ledger discipline to copy (sdd-codereview.md:8-11): "…If a sandbox makes it read-only, do not request
#   broader filesystem access or create a worktree-local ledger; list … `(NOT filed: shared ledger is read-only)`."

# CLI surface (TASK-3392) the twins call — exact spellings:
wikitoolkit ledger plan-fix [--kind K] [--severity S] [--lane fast|sdd] [--json]      # stdout = FixPlan JSON
wikitoolkit ledger claim <issue-id> --actor agent:sdd-fix                              # exit 1 = already claimed → DROP the issue, continue
wikitoolkit ledger context <file…> --max-tokens 3000                                   # pass files_for() paths from the plan's group.files
wikitoolkit ledger close <issue-id> --reason TEXT --actor agent:sdd-fix --resolved-by commit:<sha>|task:TASK-<NNN>
wikitoolkit ledger unclaim <issue-id> --reason TEXT --actor agent:sdd-fix
# FixPlan JSON keys: planner_version, generated_at, total_open, groups[]; group: group_id, issues[], files[], max_severity,
#   lane, lane_reason, suggested_slug, parents[{feature_id, completed_at, open}]

# SDD-lane tooling (unchanged, spec §6):
python -m scripts.sdd.reserve_ids --kind feature --count 1 --base-branch dev --label <suggested_slug>   # only when no parent is open
python -m scripts.sdd.ensure_worktree --slug <suggested_slug> --feature-id FEAT-<NNN>                   # → .claude/worktrees/feat-FEAT-<NNN>-<slug>
# Fast-lane precedent branches: fix/ci-test-core-drift (PR #1408), fix/ci-test-core-arxiv-annotations (PR #1414)
```

### Does NOT Exist
- ~~`/sdd-fix`~~ in any of the three trees — this task creates all three files.
- ~~a direct-push path (`git push origin dev`) or a `--no-pr` flag~~ — the fast lane ALWAYS opens a PR (§8 resolved).
- ~~`ledger acknowledge` inside `/sdd-fix`~~ — human-only; the twin never calls it.
- ~~re-deriving the slug or reading `sdd/tasks/index/` in the twin~~ — `suggested_slug` and `parents[].open` come from the plan.
- ~~closing issues "because the plan listed them"~~ — the plan is a snapshot; only a successful `ledger claim` authorises work (S3).
- ~~a `sdd/fixes/` artifact~~ — rejected in brainstorm; the SDD lane reuses `sdd/specs/` + `sdd/tasks/index/`.
- ~~a worktree for the fast lane~~ — `worktree-management.md` §2 excludes single-commit fixes; branch in the main checkout.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": ".claude/commands/sdd-fix.md", "action": "CREATE"},
    {"path": ".agent/workflows/sdd-fix.md", "action": "CREATE"},
    {"path": ".agents/skills/sdd-fix/SKILL.md", "action": "CREATE"}
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

### Twin token contract (TASK-3396 asserts these literally — every twin, verbatim)
| Must contain | Why |
|---|---|
| `wikitoolkit ledger plan-fix --json` | twins *invoke* the plan, never parse `ledger ready` |
| `ledger claim` | claim before execute (S3) |
| `ledger context` and `--max-tokens 3000` | prime step |
| `Fast lane` **and** `SDD lane` | both lanes documented |
| `gh pr create --base dev` | fast lane always a PR |
| `ledger close` **and** `--resolved-by` | evidence-carrying close |
| `two keys` | fail-closed close rule |
| `ledger unclaim` | release step |
| `parents` **and** `reserve_ids` **and** `ensure_worktree` | SDD lane reuse-or-mint |
| `shared ledger is read-only` | EROFS discipline (mirrors codereview twins) |
| `--lane` | override documented (with the S7 refusal) |

| Must NOT contain | Why |
|---|---|
| `ledger acknowledge` | human-only, never from the lane |
| `git push origin dev` | no direct-push path |
| `--no-pr` | rejected escape hatch |

Headings: Claude and Antigravity twins start their H1 with `# /sdd-fix`; Codex uses `# SDD Fix`.
Length: Claude/Antigravity bodies > 1000 chars, Codex > 100 (mirrors `TestCodereviewTwins`).

### Key Constraints
- Claiming happens **immediately before executing**, one `ledger claim` per issue; a
  non-zero exit drops that issue and continues with the rest — never retry in a loop.
- Close only an issue that (1) the implementing agent explicitly asserts as resolved by id
  AND (2) has at least one of its `files` in the final diff (`git diff --name-only`). Every
  other claimed issue is released with `ledger unclaim`.
- Read-only ledger: report and exit non-zero **before** claiming; never create a
  worktree-local ledger.
- `--lane fast` on a critical/vulnerability group is refused by `plan-fix` (exit 1) — say so.

### References in Codebase
- `.claude/commands/sdd-codereview.md`, `.agent/workflows/sdd-codereview.md`, `.agents/skills/sdd-codereview/SKILL.md` — format and read-only-ledger wording.
- `.claude/rules/worktree-management.md` §2, §5 — why the fast lane has no worktree and needs a PR.

---

## Implementation Blueprint

### Steps (in order)
1. Write the Claude twin from the skeleton below — *why*: it is the reference wording the other two paraphrase.
2. Derive the Antigravity twin (add the `description:` frontmatter, keep the body) — *why*: same body keeps parity trivial.
3. Write the Codex skill (frontmatter `name`/`description`, `# SDD Fix`, condensed steps that still carry every contract token) — *why*: Codex skills are shorter but the token contract is not optional.
4. `grep -c` every token in the table against all three files before finishing — *why*: TASK-3396 will.

### `.claude/commands/sdd-fix.md` (CREATE)
```markdown
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
   # FILL IN: the picker rendering (group_id, max_severity, lane, lane_reason, suggested_slug, issues) — bounded by spec §3 M5
2. **Select** — picker, or deterministic resolution from the arguments (issue-id → its group; --top N → first N groups).
3. **Claim** — one `wikitoolkit ledger claim <issue-id> --actor agent:sdd-fix` per issue in the group, immediately before
   executing. The plan is a snapshot; the claim is authoritative: a non-zero exit DROPS that issue and continues. Never close an
   issue merely because an earlier plan listed it.
4. **Prime** — `wikitoolkit ledger context <group.files…> --max-tokens 3000` (full repo-relative paths from the plan, never basenames).
5. **Route** by `group.lane`:
   - **Fast lane** (`lane == "fast"`): in the MAIN checkout (no worktree), `git fetch origin dev && git switch -c fix/<issue-short-id>-<suggested_slug> origin/dev`,
     edit, run the affected package's tests, commit, `git push -u origin <branch>`, then `gh pr create --base dev --title … --body …`.
     ALWAYS a PR — there is no direct-push path.
   - **SDD lane** (`lane == "sdd"`): if any `group.parents[].open` is true, reuse that parent spec (`/sdd-task <spec> --from-issue …` per issue);
     otherwise `python -m scripts.sdd.reserve_ids --kind feature --count 1 --base-branch dev --label <suggested_slug>`, author
     `sdd/specs/<suggested_slug>.spec.md` from the group, `/sdd-task`, then
     `python -m scripts.sdd.ensure_worktree --slug <suggested_slug> --feature-id FEAT-<NNN>`. `/sdd-done <FEAT-ID>` closes it out unchanged.
     The slug comes from the plan; never re-derive it.
6. **Close** — two keys, fail-closed: an issue closes only if the implementing agent asserts its id as resolved AND at least one of
   its `files` appears in `git diff --name-only <base>...HEAD`. Then `wikitoolkit ledger close <issue-id> --reason "<what changed>"
   --actor agent:sdd-fix --resolved-by commit:<merge-sha>` (fast) or `--resolved-by task:TASK-<NNN>` (SDD).
7. **Release** — every claimed issue that failed either key: `wikitoolkit ledger unclaim <issue-id> --reason "<why>" --actor agent:sdd-fix`.
   Never leave an issue claimed; never call `ledger acknowledge` (human-only).

## Output
# FILL IN: summary block — per group: lane, branch/PR URL or FEAT-ID + worktree, issues closed (with resolved_by), issues released
```
**Why this shape**: each numbered step is one of the seven in spec §3 M5; every table token
appears in this skeleton, so the Antigravity/Codex twins derived from it inherit parity.

### `.agent/workflows/sdd-fix.md` (CREATE)
```markdown
---
description: Drain the SDD work ledger — plan-fix, claim, route to the Fast or SDD lane, close by evidence, release the rest.
---

# /sdd-fix — Ledger-Driven Fix Lane
# FILL IN: the Claude twin's body verbatim (frontmatter is the only difference) — bounded by the twin token contract
```

### `.agents/skills/sdd-fix/SKILL.md` (CREATE)
```markdown
---
name: sdd-fix
description: Drain the SDD work ledger — plan-fix, claim, route to the Fast or SDD lane, close by evidence, release the rest.
---

# SDD Fix

Use this skill when the user asks to fix ledger issues, drain the ledger, or runs `$sdd-fix`.

## Procedure
# FILL IN: condensed 7-step list carrying EVERY token in the contract table (plan-fix --json, ledger claim, ledger context
#          --max-tokens 3000, Fast lane, SDD lane, gh pr create --base dev, two keys, ledger close --resolved-by, ledger unclaim,
#          parents / reserve_ids / ensure_worktree, shared ledger is read-only, --lane) — bounded by TASK-3396 TestFixTwins
```

### FILL IN checklist
- [ ] Claude twin — picker rendering + Output block; bounded by spec §3 M5
- [ ] Antigravity twin — body copy; bounded by token contract
- [ ] Codex skill — condensed procedure; bounded by token contract
- [ ] `grep -c` each contract token in all three files = ≥1; each forbidden token = 0

---

## Acceptance Criteria

- [ ] All three files exist with the platform-correct heading/frontmatter.
- [ ] Every "must contain" token appears in all three; no "must NOT contain" token appears in any.
- [ ] The fast lane is always a PR against `dev`; no twin documents a direct push.
- [ ] Both lanes, the two-key close, the claim-drop rule (S3), the S7 refusal and the read-only-ledger exit are documented in all three.
- [ ] Existing twin tests still pass: `pytest tests/sdd/test_ledger_workflow_twins.py -v`.

---

## Validation Commands

- `pytest tests/sdd/test_ledger_workflow_twins.py -q`

---

## Test Specification

```python
# Enforced by TASK-3396 (tests/sdd/test_ledger_workflow_twins.py::TestFixTwins) — write the twins so these will pass:
class TestFixTwins:
    def test_workflow_files_exist(self): ...
    def test_all_twins_call_plan_fix_json(self): ...           # "wikitoolkit ledger plan-fix --json"
    def test_all_twins_document_both_lanes(self): ...          # "Fast lane" and "SDD lane"
    def test_all_twins_require_resolved_by_on_close(self): ... # "ledger close" and "--resolved-by" and "two keys"
    def test_all_twins_release_unfixed_issues(self): ...       # "ledger unclaim"
    def test_all_twins_require_a_pr_on_the_fast_lane(self): ...# "gh pr create --base dev"; not "git push origin dev"; not "--no-pr"
    def test_no_twin_calls_acknowledge(self): ...              # "ledger acknowledge" absent
    def test_all_twins_reuse_open_parent_or_mint(self): ...    # "parents", "reserve_ids", "ensure_worktree"
    def test_read_only_ledger_exits_without_claiming(self): ...# "shared ledger is read-only"
```

---

## Agent Instructions

1. **Read the spec** (§2 Overview — all five bold rules, §3 Module 5, §7 "Claim race", "Read-only ledger", "Three twins, one behaviour").
2. **Check dependencies** — TASK-3392 completed (the CLI the twins call exists; run `wikitoolkit ledger plan-fix --json` once to see the real output shape).
3. **Verify the Codebase Contract** — open the three `sdd-codereview` twins for format.
4. **Update status** in `sdd/tasks/index/sdd-fix-ledger-lane.json` → `"in-progress"`.
5. **Implement** the three files; then grep the token table.
6. **Verify** the Validation Command.
7. **Move this file** to `sdd/tasks/completed/TASK-3394-sdd-fix-twins.md`.
8. **Update index** → `"done"`.
9. **Fill in the Completion Note**.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none | describe if any

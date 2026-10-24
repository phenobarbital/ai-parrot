# TASK-4696: Policy docs describe the Fast lane as a worktree lane

**Feature**: FEAT-740 — Fast lane runs in its own worktree (never the main checkout)
**Spec**: `sdd/specs/sdd-fix-brief-change.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Implements spec §3 **Module 2**. Four policy documents describe the `/sdd-fix`
Fast lane or list who creates worktrees. Once TASK-4695 rewrites the lane, these
must agree with it: the lane produces a `fix-<id>-<slug>` **worktree** (not a
`fix/<id>-<slug>` branch in the main checkout), opens a PR, and reaps the tree.
All wording is fixed by the spec, so this task does not wait for TASK-4695 —
the two touch disjoint files and run concurrently.

---

## Scope

- Rewrite the Fast-lane clause of `docs/sdd/WORKFLOW.md` (lines 134–135).
- Rewrite the `/sdd-fix` row of the command table in `docs/sdd/PLATFORM.md` (line 263).
- Add `/sdd-fix` (Fast lane) to the "Created by whoever implements" bullet in both
  `.claude/rules/worktree-management.md` (line 32) and its twin
  `.agent/skills/worktree-management/SKILL.md` (line 30), with identical text.

**NOT in scope**:
- The three `/sdd-fix` twins — TASK-4695. `/sdd-brief` — TASK-4697.
- `sdd/WORKFLOW.md` — it does not describe the Fast lane at all (no `Fast lane` string there); leave it.
- `CLAUDE.md` — not touched by this feature.
- Any other line of the four files; any test edit (spec §8 Q2).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `docs/sdd/WORKFLOW.md` | MODIFY | Fast-lane clause: worktree `fix-<id>-<slug>`, PR, reap |
| `docs/sdd/PLATFORM.md` | MODIFY | `/sdd-fix` command-table row |
| `.claude/rules/worktree-management.md` | MODIFY | §2 "Created by" bullet gains `/sdd-fix` (Fast lane) |
| `.agent/skills/worktree-management/SKILL.md` | MODIFY | Same bullet, identical text (twin) |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
None — Markdown only.

### Existing Signatures to Use
```text
# scripts/sdd/brief_meta.py — source of the fix-<id>-<slug> name the docs now state
def brief_worktree_plan(*, slug: str, key: str, base_branch: str) -> WorktreePlan:   # line 150
    prefix = "hotfix" if base_branch == "main" else "fix"                            # line 166
    name = f"{prefix}-{key}-{slug}"                                                  # line 167

# scripts/sdd/ensure_worktree.py
--brief-key   (line 305)  accepts "Jira key, ledger short id, or slug"
--base-branch (line 313)
```

### Test contracts these four files must keep green
```text
tests/sdd/test_sdd_fix_docs.py
  docs/sdd/WORKFLOW.md must contain: "## Ledger-Driven Fix Lane", "Fast lane", "SDD lane",
      "plan-fix --json", "gh pr create --base dev" (line 25)
  docs/sdd/PLATFORM.md must contain: "`/sdd-fix"
tests/sdd_scripts/test_pr_policy_wording_contract.py   (_DOCS includes docs/sdd/WORKFLOW.md and
                                                          .claude/rules/worktree-management.md)
  must contain "merges into `main`" or "merge into `main`"
  must NOT contain "opens a PR against `main`", "/sdd-spec --type hotfix", "type: hotfix"
  docs/sdd/WORKFLOW.md must keep a line starting "| `/sdd-brief"
  .claude/rules/worktree-management.md must keep "--brief-key" and "clears the auto-set upstream"
tests/sdd_scripts/test_feat722_doc_contract.py   (both worktree-management copies)
  must keep "[tool.parrot.worktree]", "cd packages/ai-parrot && python setup.py build_ext --inplace",
  "make -C packages/navrules build-rust-wheel"
```

### Does NOT Exist
- ~~`.agent/rules/worktree-management.md`~~ — the twin is `.agent/skills/worktree-management/SKILL.md`.
- ~~a `Fast lane` section in `sdd/WORKFLOW.md`~~ — not there; do not add one.
- ~~`ensure_worktree --fix-key`~~ — not a flag; do not document one.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "docs/sdd/WORKFLOW.md", "action": "MODIFY"},
    {"path": "docs/sdd/PLATFORM.md", "action": "MODIFY"},
    {"path": ".claude/rules/worktree-management.md", "action": "MODIFY"},
    {"path": ".agent/skills/worktree-management/SKILL.md", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:scripts/sdd/brief_meta.py#brief_worktree_plan"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- **The PLATFORM.md row and both worktree-management bullets stay on ONE line each** —
  because a Markdown table row cannot wrap, and the bullets are single long lines in the
  source; the spec's skeleton wraps them only for readability.
- Keep `gh pr create --base dev` literally in `docs/sdd/WORKFLOW.md` — `test_sdd_fix_docs.py:25` greps for it.
- The two worktree-management bullets must be byte-identical — they are twins (not test-enforced; keep them in sync anyway).

---

## Implementation Blueprint

### Steps (in order)
1. Re-run the four anchor counts below; each must be `1` — *why*: a different count means drift since 87341f43c.
2. Apply the four replacements below — *why*: each is the spec §3 M2 skeleton line.
3. Run the Validation Commands.

### `docs/sdd/WORKFLOW.md` (MODIFY)
```text
# occurrences: 1 (verified: grep -cF 'through the **Fast lane** (branch `fix/<id>-<slug>` off `origin/dev`, always' docs/sdd/WORKFLOW.md)
# REPLACE lines 134-135 (verified: docs/sdd/WORKFLOW.md:134) — current text:
#   through the **Fast lane** (branch `fix/<id>-<slug>` off `origin/dev`, always
#   `gh pr create --base dev`). `ledger claim` is authoritative; close with `ledger close --resolved-by`.
# WITH:
through the **Fast lane** (worktree `fix-<id>-<slug>` off `origin/dev`, always
`gh pr create --base dev`, worktree reaped after the PR). `ledger claim` is authoritative; close with `ledger close --resolved-by`.
```
**Why**: line 135 is replaced too because the closing `)` of the Fast-lane parenthetical
lives there; the trailing `ledger claim …` sentence is carried over unchanged.

### `docs/sdd/PLATFORM.md` (MODIFY)
```text
# occurrences: 1 (verified: grep -cF '| `/sdd-fix [issue-id]` |' docs/sdd/PLATFORM.md)
# REPLACE line 263 (verified: docs/sdd/PLATFORM.md:263) WITH this single line:
| `/sdd-fix [issue-id]` | Ledger-driven fix lane: `ledger plan-fix --json` → claim → Fast lane (worktree + PR + reap, one per group) or SDD lane (spec/tasks/worktree) → close with `--resolved-by` → `unclaim` the rest. |
```
**Why**: only `(branch + PR)` changes to `(worktree + PR + reap, one per group)`; the rest of the row is verbatim.

### `.claude/rules/worktree-management.md` (MODIFY)
```text
# occurrences: 1 (verified: grep -cF -e '- Created by whoever implements:' .claude/rules/worktree-management.md)
# REPLACE line 32 (verified: .claude/rules/worktree-management.md:32) WITH this single line:
- Created by whoever implements: `/sdd-start`, `sdd-worker`, `/sdd-fix` (Fast lane, via `--brief-key <ledger-short-id> --base-branch dev`), and the dev-loop orchestrators (`sdd-planner`, `sdd-research`, `sdd-autopilot`). `/sdd-task` creates none (FEAT-552).
```
**Why**: the rule is the canonical list of worktree creators; the Fast lane now is one.

### `.agent/skills/worktree-management/SKILL.md` (MODIFY)
```text
# occurrences: 1 (verified: grep -cF -e '- Created by whoever implements:' .agent/skills/worktree-management/SKILL.md)
# REPLACE line 30 (verified: .agent/skills/worktree-management/SKILL.md:30) WITH the identical single line above.
```
**Why**: twin of the rule; keep in sync.

### FILL IN checklist
- [ ] none — every replacement line is fixed by the spec. A count other than `1` means STOP and report drift.

---

## Acceptance Criteria

- [ ] AC-8: `docs/sdd/WORKFLOW.md` contains ``worktree `fix-<id>-<slug>` off `origin/dev` `` and no longer contains ``branch `fix/<id>-<slug>` ``.
- [ ] AC-8: `docs/sdd/PLATFORM.md:263` contains `Fast lane (worktree + PR + reap, one per group)`.
- [ ] AC-8: both worktree-management copies list `` `/sdd-fix` (Fast lane `` in the "Created by" bullet, with identical text.
- [ ] `gh pr create --base dev` still present in `docs/sdd/WORKFLOW.md`.
- [ ] Only the four files above are modified.

---

## Validation Commands

- `pytest tests/sdd/test_sdd_fix_docs.py -q`
- `pytest tests/sdd_scripts/test_pr_policy_wording_contract.py -q`
- `pytest tests/sdd_scripts/test_feat722_doc_contract.py -q`

---

## Test Specification

No new tests (spec §8 Q2 — "prose only"). Baseline: the suites above were green on
`dev` at `02d113e88` (part of a 93-passed baseline run).

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
6. **Implement** — apply the four replacements exactly
7. **Verify** — run the Validation Commands
8. **Commit the code** — stage only the four files (never `git add .` / `-A`)
9. **Close the task** with `scripts/sdd/close_task.sh TASK-4696 sdd-fix-brief-change verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any

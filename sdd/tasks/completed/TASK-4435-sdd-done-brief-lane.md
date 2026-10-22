# TASK-4435: `/sdd-done` brief lane + "opens the PR, never merges main" policy

**Feature**: FEAT-698 — /sdd-brief One-Command Brief Flow for Hotfixes and Single-Issue Fixes
**Spec**: `sdd/specs/sdd-brief-hotfix-flow.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-4425
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 3, design-research S4/S5/S7. Two changes to `/sdd-done`:

1. **A separate brief lane** (S4) — not conditionals threaded through the
   feature lane. A brief exists only in its worktree, so it is resolved by
   scanning worktrees, verified against its per-brief index + the brief's
   Validation Commands, and closed in place.
2. **PR policy** (S5, binding brainstorm decision): `/sdd-done` opens the PR
   itself in **every** flow, against the flow's `base_branch` — `main`
   included. What stays forbidden is merging into `main`: `--merge` is
   refused **before any push** when the base is `main`.

Ledger (S7): a brief with `ledger_issue` set is closed only once the fix is
confirmed merged; a PR-only finish prints the exact close command.

---

## Scope

In `.claude/commands/sdd-done.md`:

- **CRITICAL callout (line 46)**: reword to "never pushes to `main`, never
  **merges** into `main`; opens the PR — merging a `main` PR is the human
  act".
- **New `### 2b. Brief Lane (FEAT-698)`** after Step 2: input matching a
  brief KEY/slug resolves by scanning `$WORKTREES_DIR` for `hotfix-*`/`fix-*`
  worktrees containing `sdd/briefs/<slug>.index.json` (works from inside the
  worktree and from the main repo **on any branch** — the brief lane never
  checks out `BASE_BRANCH` in the shared checkout). Read `base_branch`,
  `ledger_issue` from the brief frontmatter. Verify every task in the
  per-brief index is `done` and run the brief's Validation Commands. Skip
  `close_task.sh`, the ledger snapshot (Step 9.1) and E2E (as `TYPE ==
  hotfix` does today). Then go to Step 8/9.2 with `BRANCH` = the worktree
  branch.
- **Step 9.2 (line 548)**: replace the hard refusal block with: if
  `BASE_BRANCH == main` and `--merge` → refuse (exit 1) **before** any push;
  otherwise push and run `gh pr create --base "$BASE_BRANCH" --head
  "$BRANCH" …` for both lanes. `$BRANCH` replaces every hardcoded
  `feat-<FEAT-ID>-<slug>` in this step. On `gh` failure: keep the worktree
  and branch, print the manual command, exit non-zero (fail closed).
- **Ledger close** for briefs: after a confirmed merge (`--merge` on a
  dev-based brief) run `wikitoolkit ledger close <id> --resolved-by …`;
  PR-only ⇒ print that exact command next to the PR URL.
- Mirror the semantics in `.agents/skills/sdd-done/SKILL.md` (lines 35-43
  hotfix rules, 207-208 manual-PR rule).
- Create `tests/sdd_scripts/test_sdd_done_brief_contract.py`.

**NOT in scope**: CLAUDE.md / WORKFLOW.md wording (TASK-4437); `--sync-down`
logic beyond replacing the hardcoded branch name.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `.claude/commands/sdd-done.md` | MODIFY | brief lane, PR policy, ledger timing |
| `.agents/skills/sdd-done/SKILL.md` | MODIFY | codex twin |
| `tests/sdd_scripts/test_sdd_done_brief_contract.py` | CREATE | policy + lane guards |

---

## Codebase Contract (Anti-Hallucination)

### Existing Signatures to Use
Anchors in `.claude/commands/sdd-done.md` (all occurrences 1):
- line 46: ``> **CRITICAL — `/sdd-done` NEVER pushes to `main` and NEVER opens a PR against `main` (FEAT-145).**``
- line 107: `### 2. Resolve the Feature`
- line 548: ``**Hard refusal — `BASE_BRANCH == "main"`:**`` (block runs to line 571, `exit 0`)
- Step 1 `IN_WORKTREE`, `$MAIN_ROOT`, `$WORKTREES_DIR` variables: lines 80-104
- Step 9.5 `--sync-down` ancestor check uses `feat-<FEAT-ID>-<slug>`: lines 698-715
- `.agents/skills/sdd-done/SKILL.md` lines 35-43, 76, 207-208.
- Brief index/frontmatter shape: TASK-4425 (`type: "brief"`, `feature_id: "BRIEF-<KEY>"`, `ledger_issue`).
- `wikitoolkit ledger close <id> --reason …` usage: `.claude/commands/sdd-fix.md:49`.

### Does NOT Exist
- ~~`close_task.sh` for briefs~~ — briefs close in place.
- ~~`git checkout main` anywhere in the brief lane~~ — forbidden (shared checkout).
- ~~`gh pr merge` against `main`~~ — never.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": ".claude/commands/sdd-done.md", "action": "MODIFY"},
    {"path": ".agents/skills/sdd-done/SKILL.md", "action": "MODIFY"},
    {"path": "tests/sdd_scripts/test_sdd_done_brief_contract.py", "action": "CREATE"}
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

### Key Constraints
- **Ordering**: the `--merge`-into-main refusal must appear before Step 8's
  push in the procedure text (S5 "rejected before any push"). Move or
  duplicate the check into the pre-push gate — do not leave it only at 9.2.
- The feature lane keeps its current behavior except for the main-PR change
  (which only ever applied to hotfix specs, now gone).
- Ledger close wording must use the flag `/sdd-fix` uses (verify
  `--resolved-by` vs `--reason` with `wikitoolkit ledger close --help`).

---

## Implementation Blueprint

### Steps (in order)
1. Verify `wikitoolkit ledger close --help` flags — *why*: the printed command must work verbatim.
2. Reword the CRITICAL callout — *why*: it is the policy statement every reader sees first.
3. Add §2b and rewrite Step 9.2 — *why*: S4/S5.
4. Mirror in the codex twin; write the contract test — *why*: parity + AC-1..AC-5.

### `.claude/commands/sdd-done.md` (MODIFY)
```markdown
# occurrences: 1 (verified: grep -c 'NEVER opens a PR against `main` (FEAT-145)' .claude/commands/sdd-done.md)
# REPLACE the callout at lines 46-53 with:
> **CRITICAL — `/sdd-done` NEVER pushes to `main` and NEVER merges into `main` (FEAT-145, FEAT-698).**
> It opens the PR itself in every flow, against the flow's `base_branch` — `main` for a
> hotfix brief, `dev`/`staging` for a feature. Merging a `main` PR is the human act:
> `--merge` with `BASE_BRANCH == main` is refused before anything is pushed, under every
> flag combination. After a `main` PR merges, `.github/workflows/sync-down.yml`
> propagates it to `staging` and `dev`; `--sync-down` is the manual fallback.
```
```markdown
# occurrences: 1 (verified: grep -c '^### 2. Resolve the Feature$' .claude/commands/sdd-done.md)
# AFTER — new subsection after Step 2's last line ("The list of tasks … per-spec index file.")
### 2b. Brief Lane (FEAT-698)
<!-- FILL IN: Scope bullet "New ### 2b" — resolution by worktree scan, no checkout, verification,
     skipped steps, BRANCH assignment -->
```
```markdown
# occurrences: 1 (verified: grep -c 'Hard refusal — `BASE_BRANCH == "main"`' .claude/commands/sdd-done.md)
# FILL IN: replace lines 548-571 with the fail-closed PR block for both lanes using "$BRANCH";
#          keep the post-merge sync-down note
```

### `tests/sdd_scripts/test_sdd_done_brief_contract.py` (CREATE)
```python
"""/sdd-done opens PRs (main included), never merges main; brief lane present — FEAT-698 / TASK-4435."""

from __future__ import annotations

from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_DOC = _ROOT / ".claude/commands/sdd-done.md"
_TWIN = _ROOT / ".agents/skills/sdd-done/SKILL.md"


def test_old_never_open_pr_rule_gone() -> None:
    assert "NEVER opens a PR against `main`" not in _DOC.read_text(encoding="utf-8")

# FILL IN: test_pr_created_with_base_branch_variable — `gh pr create` lines use --base "$BASE_BRANCH" and
#          --head "$BRANCH", never a hardcoded feat-<FEAT-ID> head (AC-2)
# FILL IN: test_merge_into_main_refused_before_push — the refusal text precedes "### 8." (AC-3)
# FILL IN: test_brief_lane_present_and_never_checks_out_main (AC-4)
# FILL IN: test_twin_no_longer_prints_manual_main_pr — twin no longer says "print a manual `gh pr create --base main`" (AC-5)
```

### FILL IN checklist
- [ ] §2b body
- [ ] Step 9.2 rewrite + pre-push refusal
- [ ] ledger close timing
- [ ] codex twin
- [ ] contract tests AC-2..AC-5

---

## Acceptance Criteria

- [ ] AC-1: the "NEVER opens a PR against `main`" rule is gone; "NEVER merges into `main`" replaces it.
- [ ] AC-2: both lanes create the PR with `gh pr create --base "$BASE_BRANCH" --head "$BRANCH"`; on failure the worktree/branch are kept and the command exits non-zero.
- [ ] AC-3: `--merge` with base `main` is refused before any push.
- [ ] AC-4: the brief lane resolves via worktree scan, verifies via the per-brief index + Validation Commands, closes in place, and never checks out a branch in the shared checkout.
- [ ] AC-5: the codex twin carries the same policy.
- [ ] AC-6: ledger close only after confirmed merge; PR-only prints the exact command.

---

## Validation Commands

- `pytest tests/sdd_scripts/test_sdd_done_brief_contract.py -q`
- `pytest tests/sdd_scripts/test_e2e_closeout_contract.py -q`

---

## Test Specification

See the CREATE block above.

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`python -m scripts.sdd.ensure_worktree --slug sdd-brief-hotfix-flow --feature-id FEAT-698`)
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — every `Depends-on` task must be `"done"` in
   `sdd/tasks/index/sdd-brief-hotfix-flow.json`
4. **Verify the Codebase Contract** before writing ANY code
5. **Update status** in the per-spec index → `"in-progress"` (set `started_at`) and commit only that index file
6. **Implement** from the Implementation Blueprint; complete every `# FILL IN:`; never change a fixed signature or path
7. **Verify** all acceptance criteria — run the Validation Commands from the worktree root
8. **Commit the code** — stage only the files this task lists
9. **Close the task** with `scripts/sdd/close_task.sh TASK-4435 sdd-brief-hotfix-flow verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none | describe if any

# TASK-4437: Policy docs — `/sdd-brief` and "opens the PR, never merges main"

**Feature**: FEAT-698 — /sdd-brief One-Command Brief Flow for Hotfixes and Single-Issue Fixes
**Spec**: `sdd/specs/sdd-brief-hotfix-flow.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-4435, TASK-4436
**Assigned-to**: unassigned

---

## Context

Spec §3 Modules 3/4/6. The always-loaded docs still state the old FEAT-187
rule ("`/sdd-done` NEVER pushes to or opens a PR against `main`") and
describe the `/sdd-spec --type hotfix` path. Once TASK-4435/4436 land, they
must say what the commands now do. CLAUDE.md is loaded into every session,
so it is the highest-leverage file here.

---

## Scope

- `CLAUDE.md`:
  - line 159 rule → "`/sdd-done` never pushes to or merges into `main`; it
    opens the PR (merging a `main` PR is the human act)";
  - "SDD Auto-Commit Rule" table: add a `/sdd-brief` row (commits the brief,
    task files and per-brief index **inside the worktree**);
  - the FEAT-466 hotfix note under that table: rewrite to "a hotfix is a
    `/sdd-brief`; it reserves no ids" (drop the `/sdd-spec … type: hotfix`
    mechanics);
  - "Flow types": `hotfix` → produced by `/sdd-brief` (base `main`); ledger
    briefs base `dev`.
- `docs/sdd/WORKFLOW.md`: line 89 wording; add `/sdd-brief` to the Commands
  table and a one-paragraph "Hotfixes and single-issue fixes" note in
  Lifecycle (flow `hotfix` no longer goes through `/sdd-spec`).
- `sdd/WORKFLOW.md`: line 62 area and any `--type hotfix` mention.
- `.claude/rules/worktree-management.md` §5 Finish: SDD lane bullet says
  `/sdd-done` opens the PR against `base_branch` "`main` included for a
  hotfix brief; it never merges into `main`"; §2 Create: add the
  `--brief-key` invocation; note that `ensure()` now clears the
  auto-upstream (TASK-4426).
- Create `tests/sdd_scripts/test_pr_policy_wording_contract.py`.

**NOT in scope**: command files (TASK-4435/4436 own them).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `CLAUDE.md` | MODIFY | policy + auto-commit table + flow types |
| `docs/sdd/WORKFLOW.md` | MODIFY | wording + Commands table |
| `sdd/WORKFLOW.md` | MODIFY | wording |
| `.claude/rules/worktree-management.md` | MODIFY | §2/§5 |
| `tests/sdd_scripts/test_pr_policy_wording_contract.py` | CREATE | wording guards |

---

## Codebase Contract (Anti-Hallucination)

### Existing Signatures to Use
- `CLAUDE.md:159` (occurrences 1): ``**`/sdd-done` NEVER pushes to or opens a PR against `main`** —``
- `docs/sdd/WORKFLOW.md:89` (occurrences 1): ``(`--merge` merges directly). It never pushes to or opens a PR against `main`.``
- `sdd/WORKFLOW.md:62`: ``opens a PR against `base_branch` (`--merge` merges directly).``
- `.claude/rules/worktree-management.md` §2 (`python -m scripts.sdd.ensure_worktree --slug <slug> --jira-key <JIRA-KEY>     # hotfix  → origin/main`) and §5 SDD-lane bullet.
- Twin note: `.agent/skills/worktree-management/` is the `.agent` twin of the rule (CLAUDE.md "Worktrees") — check it with `grep -rn "opens a PR" .agent/skills/worktree-management/` and apply the same wording if it carries the rule.

### Does NOT Exist
- ~~a generated CLAUDE.md~~ — hand-edited; keep its existing structure and headings.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "CLAUDE.md", "action": "MODIFY"},
    {"path": "docs/sdd/WORKFLOW.md", "action": "MODIFY"},
    {"path": "sdd/WORKFLOW.md", "action": "MODIFY"},
    {"path": ".claude/rules/worktree-management.md", "action": "MODIFY"},
    {"path": "tests/sdd_scripts/test_pr_policy_wording_contract.py", "action": "CREATE"}
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

### Key Constraints
- If `.agent/skills/worktree-management/` needs the same edit, add it to
  this task's file table **in the Completion Note** as a deviation — do not
  silently edit an unlisted file.
- Keep the "Adversarial Second Opinion" and every unrelated CLAUDE.md
  section byte-identical.

---

## Implementation Blueprint

### Steps (in order)
1. CLAUDE.md edits — *why*: always-loaded; highest leverage.
2. Both WORKFLOW.md files and the worktree rule — *why*: they restate the policy.
3. Guard test — *why*: AC-1..AC-3.

### `CLAUDE.md` (MODIFY)
```markdown
# occurrences: 1 (verified: grep -c '**`/sdd-done` NEVER pushes to or opens a PR against `main`** —' CLAUDE.md)
# REPLACE the paragraph starting at line 159 with:
**`/sdd-done` NEVER pushes to or merges into `main`** — it opens the PR against
the flow's `base_branch` itself (`main` for a hotfix brief); merging a `main` PR is
the human act, and `--merge` into `main` is refused. After the merge, the Action
propagates the change to `staging` and `dev`; `/sdd-done <KEY> --sync-down` is the
manual fallback.
# FILL IN: auto-commit table /sdd-brief row; FEAT-466 note rewrite; Flow types bullet
```

### `tests/sdd_scripts/test_pr_policy_wording_contract.py` (CREATE)
```python
"""Policy docs match the FEAT-698 PR rule — TASK-4437."""

from __future__ import annotations

from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_DOCS = ("CLAUDE.md", "docs/sdd/WORKFLOW.md", "sdd/WORKFLOW.md", ".claude/rules/worktree-management.md")


@pytest.mark.parametrize("rel", _DOCS)
def test_old_rule_gone(rel: str) -> None:
    assert "opens a PR against `main`" not in (_ROOT / rel).read_text(encoding="utf-8")

# FILL IN: test_claude_md_lists_sdd_brief_in_auto_commit_table (AC-2)
# FILL IN: test_workflow_commands_table_has_sdd_brief (AC-3)
# FILL IN: test_worktree_rule_documents_brief_key (AC-4)
```

### FILL IN checklist
- [ ] CLAUDE.md table row, FEAT-466 note, Flow types
- [ ] WORKFLOW.md (both) + worktree rule
- [ ] guard tests AC-2..AC-4

---

## Acceptance Criteria

- [ ] AC-1: none of the four docs says `/sdd-done` won't open a PR against `main`; each says it never merges into `main`.
- [ ] AC-2: CLAUDE.md's auto-commit table has a `/sdd-brief` row ("inside the worktree").
- [ ] AC-3: `docs/sdd/WORKFLOW.md` Commands table lists `/sdd-brief`.
- [ ] AC-4: the worktree rule documents `--brief-key` and the cleared upstream.
- [ ] AC-5: no `/sdd-spec … --type hotfix` instruction remains in these docs.

---

## Validation Commands

- `pytest tests/sdd_scripts/test_pr_policy_wording_contract.py -q`

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
9. **Close the task** with `scripts/sdd/close_task.sh TASK-4437 sdd-brief-hotfix-flow verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(done)*

**Deviations**: `.agent/skills/worktree-management/` twin line 56 still carries the old "opens a PR feature → base_branch" wording; not in this task's file list — left for follow-up.

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none | describe if any

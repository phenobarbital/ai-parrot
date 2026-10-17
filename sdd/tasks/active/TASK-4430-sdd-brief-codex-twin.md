# TASK-4430: Codex twin of `/sdd-brief` (`.agents/skills/sdd-brief/`)

**Feature**: FEAT-698 — /sdd-brief One-Command Brief Flow for Hotfixes and Single-Issue Fixes
**Spec**: `sdd/specs/sdd-brief-hotfix-flow.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-4429
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 1. Codex runs the same SDD workflow through
`.agents/skills/sdd-*` (`$sdd-*`, see docs/sdd/WORKFLOW.md "Codex uses the
same workflow"). `/sdd-brief` needs its twin so a codex session can run the
brief flow with the same guarantees.

---

## Scope

- Create `.agents/skills/sdd-brief/SKILL.md`: frontmatter (`name: sdd-brief`,
  one-line `description`) and a condensed procedure mirroring
  `.claude/commands/sdd-brief.md` steps 1–12 — same CLI invocations, same
  refusal text, same guardrails. Mirror the layout/condensation level of
  `.agents/skills/sdd-spec/SKILL.md`.
- Create `tests/sdd_scripts/test_sdd_brief_twin_contract.py`.

**NOT in scope**: docs/sdd/CODEX.md (TASK-4436 updates it); any Claude-side file.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `.agents/skills/sdd-brief/SKILL.md` | CREATE | Codex skill twin |
| `tests/sdd_scripts/test_sdd_brief_twin_contract.py` | CREATE | twin parity guards |

---

## Codebase Contract (Anti-Hallucination)

### Existing Signatures to Use
- `.agents/skills/sdd-spec/SKILL.md` frontmatter shape (lines 1-4):
  ```
  ---
  name: sdd-spec
  description: <one line>
  ---
  ```
- `.claude/commands/sdd-brief.md` (TASK-4429) — the source of truth to mirror.

### Does NOT Exist
- ~~`.agents/skills/sdd-brief/`~~ — created here.
- ~~a shared generator that builds codex twins~~ — twins are hand-maintained.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": ".agents/skills/sdd-brief/SKILL.md", "action": "CREATE"},
    {"path": "tests/sdd_scripts/test_sdd_brief_twin_contract.py", "action": "CREATE"}
  ],
  "contract_symbols": []
}
```

---

## Implementation Blueprint

### Steps (in order)
1. Read `.claude/commands/sdd-brief.md` and `.agents/skills/sdd-spec/SKILL.md` — *why*: the twin condenses the former in the style of the latter.
2. Write the SKILL.md — *why*: codex parity.
3. Write the parity test — *why*: drift between twins is the recurring failure mode (auto-memory "edit BOTH twins").

### `.agents/skills/sdd-brief/SKILL.md` (CREATE)
```markdown
---
name: sdd-brief
description: Research a bug, code-scanning alert, Jira/GitHub issue, or ledger issue to a root cause and provision a worktree holding an actionable brief — no FEAT/TASK ids; replaces sdd-spec --type hotfix.
---

# SDD Brief
<!-- FILL IN: condensed steps 1–12 of .claude/commands/sdd-brief.md -->
```

### `tests/sdd_scripts/test_sdd_brief_twin_contract.py` (CREATE)
```python
"""Twin parity: .agents/skills/sdd-brief mirrors .claude/commands/sdd-brief.md — FEAT-698 / TASK-4430."""

from __future__ import annotations

from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_CLAUDE = _ROOT / ".claude/commands/sdd-brief.md"
_CODEX = _ROOT / ".agents/skills/sdd-brief/SKILL.md"
_SHARED_TOKENS = (
    "--brief-key",
    "scripts.sdd.ensure_worktree",
    "Ledger-sourced briefs always base on dev; --base-branch main is refused.",
    "path:line",
)

# FILL IN: test_frontmatter_name_is_sdd_brief (AC-1)
# FILL IN: test_shared_tokens_in_both_twins — every _SHARED_TOKENS entry appears in both files (AC-2)
```

### FILL IN checklist
- [ ] SKILL.md body
- [ ] parity tests AC-1/AC-2

---

## Acceptance Criteria

- [ ] AC-1: `.agents/skills/sdd-brief/SKILL.md` has `name: sdd-brief` frontmatter.
- [ ] AC-2: the CLI invocation, the ledger refusal text, and the research-floor wording appear in both twins.
- [ ] AC-3: no `git worktree add` and no `reserve_ids` call in the twin.

---

## Validation Commands

- `pytest tests/sdd_scripts/test_sdd_brief_twin_contract.py -q`

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
9. **Close the task** with `scripts/sdd/close_task.sh TASK-4430 sdd-brief-hotfix-flow verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none | describe if any

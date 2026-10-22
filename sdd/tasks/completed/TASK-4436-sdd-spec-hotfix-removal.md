# TASK-4436: Remove the hotfix path from `/sdd-spec` (and its twins)

**Feature**: FEAT-698 — /sdd-brief One-Command Brief Flow for Hotfixes and Single-Issue Fixes
**Spec**: `sdd/specs/sdd-brief-hotfix-flow.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4429, TASK-4430
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 4, Decision 1 (hard cut). With `/sdd-brief` in place, the
FEAT-466 hotfix branches in `/sdd-spec` are dead weight and a trap. Remove
them from the command and every twin; an explicit `--type hotfix` aborts
with a pointer to `/sdd-brief`. `FlowMeta`/`resolve_flow()` are **not**
touched — legacy `type: hotfix` specs in `sdd/specs/` still parse.

---

## Scope

In `.claude/commands/sdd-spec.md`:
- Usage line: `--type feature|hotfix` → `--type feature` (keep the flag for
  explicitness).
- §2d: add, before the resolver call, the refusal
  `⚠️  /sdd-spec no longer scaffolds hotfixes — use /sdd-brief <source> (FEAT-698).`
  for `--type hotfix` or `type: hotfix` exploration frontmatter; delete the
  "Validation (hotfix/main)" paragraph (line 186) and rewrite the
  feature/not-main message so it points at `/sdd-brief` instead of
  "set type='hotfix'".
- §5: delete the "Feature ID — SKIP ENTIRELY when `TYPE == "hotfix"`" block
  (from line 514) — keep the feature reservation text that follows it.
- §5 frontmatter example: `type: feature        # or: hotfix` → `type: feature`.
- §7: delete the `TYPE == "hotfix"` output block (line 718 to the end of that block).

Apply the same removal to `.agent/workflows/sdd-spec.md`,
`.agents/skills/sdd-spec/SKILL.md`, and update `docs/sdd/CODEX.md` (lines
193, 225, 423: replace the `$sdd-spec … --type hotfix` examples with
`$sdd-brief` equivalents).

Create `tests/sdd_scripts/test_sdd_spec_hotfix_removed_contract.py`.

**NOT in scope**: `scripts/sdd/ensure_worktree.py`'s `--type` choices and
`plan_worktree` (legacy hotfix worktrees still need naming); historical
`sdd/specs/*`, `sdd/tasks/completed/*`; `/sdd-task`'s defensive hotfix
section (noted as follow-up — not in the spec's file list).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `.claude/commands/sdd-spec.md` | MODIFY | remove hotfix path, add refusal |
| `.agent/workflows/sdd-spec.md` | MODIFY | twin |
| `.agents/skills/sdd-spec/SKILL.md` | MODIFY | codex twin |
| `docs/sdd/CODEX.md` | MODIFY | examples → `$sdd-brief` |
| `tests/sdd_scripts/test_sdd_spec_hotfix_removed_contract.py` | CREATE | guards |

---

## Codebase Contract (Anti-Hallucination)

### Existing Signatures to Use
Anchors in `.claude/commands/sdd-spec.md` (all occurrences 1):
- line 8: usage `… [--type feature|hotfix] …`
- line 186: `**Validation (hotfix/main):**`
- line 514: ``   - **Feature ID — SKIP ENTIRELY when `TYPE == "hotfix"` (FEAT-466).** A``
- line 718: ``**`TYPE == "hotfix"` (FEAT-466 — no id reserved):**``
- `.agent/workflows/sdd-spec.md`: same blocks at lines 194, 518, 722.
- `docs/sdd/CODEX.md`: lines 193, 225, 423.
- `tests/sdd_scripts/test_sdd_spec_intake_contract.py` — existing guard on this command; must keep passing.

### Does NOT Exist
- ~~a change to `resolve_flow()` / `FlowMeta`~~ — wheel-shipped, untouched.
- ~~`$sdd-brief`~~ codex skill — created by TASK-4430 (dependency).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": ".claude/commands/sdd-spec.md", "action": "MODIFY"},
    {"path": ".agent/workflows/sdd-spec.md", "action": "MODIFY"},
    {"path": ".agents/skills/sdd-spec/SKILL.md", "action": "MODIFY"},
    {"path": "docs/sdd/CODEX.md", "action": "MODIFY"},
    {"path": "tests/sdd_scripts/test_sdd_spec_hotfix_removed_contract.py", "action": "CREATE"}
  ],
  "contract_symbols": []
}
```

---

## Implementation Blueprint

### Steps (in order)
1. Edit the Claude command per Scope — *why*: it is the reference twin.
2. Apply the same removals to `.agent/workflows/sdd-spec.md` and the codex skill — *why*: parity.
3. Update CODEX.md examples — *why*: they currently teach the removed path.
4. Write the guard test — *why*: AC-1..AC-3.

### `.claude/commands/sdd-spec.md` (MODIFY)
```markdown
# occurrences: 1 (verified: grep -c '**Validation (hotfix/main):**' .claude/commands/sdd-spec.md)
# FILL IN: replace the paragraph at line 186 (through the "re-run /sdd-spec." refusal it introduces) with:
**Hotfixes are not specs (FEAT-698):** if `--type hotfix` was passed, or the exploration
doc's frontmatter says `type: hotfix`, abort before resolving the flow:
⚠️  /sdd-spec no longer scaffolds hotfixes — use /sdd-brief <source> (FEAT-698).
```

### `tests/sdd_scripts/test_sdd_spec_hotfix_removed_contract.py` (CREATE)
```python
"""/sdd-spec no longer scaffolds hotfixes — FEAT-698 / TASK-4436."""

from __future__ import annotations

from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_FILES = (".claude/commands/sdd-spec.md", ".agent/workflows/sdd-spec.md", ".agents/skills/sdd-spec/SKILL.md")


@pytest.mark.parametrize("rel", _FILES)
def test_no_hotfix_type_flag(rel: str) -> None:
    assert "feature|hotfix" not in (_ROOT / rel).read_text(encoding="utf-8")

# FILL IN: test_refusal_points_at_sdd_brief — Claude command carries the exact refusal (AC-2)
# FILL IN: test_hotfix_output_block_removed — no 'TYPE == "hotfix"' in the three files (AC-1)
# FILL IN: test_codex_doc_examples_use_sdd_brief — CODEX.md has no "--type hotfix" (AC-3)
```

### FILL IN checklist
- [ ] Claude command removals + refusal
- [ ] two twins
- [ ] CODEX.md examples
- [ ] guard tests AC-1..AC-3

---

## Acceptance Criteria

- [ ] AC-1: none of the three command files mentions `TYPE == "hotfix"` or `feature|hotfix`.
- [ ] AC-2: `--type hotfix` aborts with the exact `/sdd-brief` pointer.
- [ ] AC-3: `docs/sdd/CODEX.md` contains no `--type hotfix`.
- [ ] AC-4: `test_sdd_spec_intake_contract.py` still passes.
- [ ] AC-5: `git diff` touches nothing under `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/`.

---

## Validation Commands

- `pytest tests/sdd_scripts/test_sdd_spec_hotfix_removed_contract.py -q`
- `pytest tests/sdd_scripts/test_sdd_spec_intake_contract.py -q`

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
9. **Close the task** with `scripts/sdd/close_task.sh TASK-4436 sdd-brief-hotfix-flow verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none | describe if any

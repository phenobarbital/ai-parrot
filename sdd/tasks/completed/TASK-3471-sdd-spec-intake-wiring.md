# TASK-3471: Wire intake mode into the `/sdd-spec` twins and codex skill

**Feature**: FEAT-577 — `/sdd-spec` Intake Mode — Interview-Driven Spec Creation
**Spec**: `sdd/specs/sdd-feature-specification.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3470
**Assigned-to**: unassigned

---

## Context

Implements spec §3 **Module 4** (the `/sdd-spec` twins) and **Module 5** (the
codex-side skill summary). The twins get the new flags, the trigger rule, a
short **§1.5 Intake Mode** that points at `sdd/templates/intake.procedure.md`
(TASK-3470), the §3b intake precondition and brief sources, §3 skipped in intake
mode, intake-staging promotion in §6, an Intake line in §7, and Reference
entries. `.agent/workflows/sdd-spec.md` must stay byte-identical to
`.claude/commands/sdd-spec.md` modulo frontmatter and the one documented
substitution (`tests/sdd_scripts/test_command_twin_parity.py`).

---

## Scope

- Edit `.claude/commands/sdd-spec.md` as in the blueprint.
- Copy the body byte-for-byte to `.agent/workflows/sdd-spec.md`. Keep its
  frontmatter and the substituted "Worktree policy" line.
- Edit `.agents/skills/sdd-spec/SKILL.md`: flags on the invocation line, plus an "Intake mode" paragraph.
- Write `tests/sdd_scripts/test_sdd_spec_intake_contract.py`.

**NOT in scope**: the procedure text itself (TASK-3470), the agent
`--no-interview` edits (TASK-3472), and the FEAT-576 projects/tags carry-forward
(TASK-3465 of FEAT-576, which edits these same files and is expected to land
first; merge on top of it).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `.claude/commands/sdd-spec.md` | MODIFY | flags, trigger, §1.5, §3b, §3, §6, §7, Reference |
| `.agent/workflows/sdd-spec.md` | MODIFY | identical body edit (twin) |
| `.agents/skills/sdd-spec/SKILL.md` | MODIFY | codex invocation + intake paragraph |
| `tests/sdd_scripts/test_sdd_spec_intake_contract.py` | CREATE | contract tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified anchors — `.claude/commands/sdd-spec.md` (647 lines; each anchor occurs exactly **once** in both twins, verified with `grep -cF`)
- `:8` `/sdd-spec <feature-name> [--type feature|hotfix] [--base-branch <branch>] [-- free-form description and notes]`
- `:38` `### 1. Parse Input` (followed by the `feature-name` / `free-form notes` bullets `:39-40`)
- `:48` `If neither exists, proceed to §3.`
- `:218` `**Preconditions (any false ⇒ skip):**`, `:219-220` exploration-doc bullet, `:221` ``- `command -v codex` succeeds.``
- `:278ff` §3b.2 list starting ``- `problem_statement.txt` ← brainstorm``
- `:386` `### 3. Ask Clarifying Questions (only what is genuinely missing)`
- `:569-581` design-research promotion block in §6; `:583-585` `# 3. Verify ONLY those paths are staged` + `# Expected: sdd/specs/<feature-name>.spec.md [+ sdd/state/<FEAT-ID>/design_research/*]`
- `:592` `### 7. Output`; `:601` `   # or:  Design research: skipped (<SKIP_REASON>)`
- `:633` `## Reference`; `:637` **parity anchor** ``- Worktree policy: `CLAUDE.md` (section "Worktree Policy")`` (must stay exactly once, unchanged); `:639` ``- Design-research schema: `sdd/templates/design_research.schema.json` (FEAT-545)``
### `.agent/workflows/sdd-spec.md`
- Same body; line ``- Worktree policy: `AGENTS.md` and `sdd/WORKFLOW.md` `` replaces the parity anchor (`tests/sdd_scripts/test_command_twin_parity.py` `_SUBSTITUTIONS["sdd-spec"]`).
### `.agents/skills/sdd-spec/SKILL.md` (134 lines)
- `:11` ``Codex invocation: `$sdd-spec <feature-slug> [--type feature|hotfix] [--base-branch <branch>] [-- <notes>]`.``
- `:40-44` "1. Parse:" bullets ending ``   - optional `--base-branch` `` (occurs once)

### Does NOT Exist
- ~~`--interview`/`--no-interview`/`--resume`/`--research`/`--no-gate`/`--budget` on `/sdd-spec`~~ — added here.
- ~~A parity test for `.agents/skills/sdd-spec/SKILL.md`~~ — none; keep it a summary.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": ".claude/commands/sdd-spec.md", "action": "MODIFY"},
    {"path": ".agent/workflows/sdd-spec.md", "action": "MODIFY"},
    {"path": ".agents/skills/sdd-spec/SKILL.md", "action": "MODIFY"},
    {"path": "tests/sdd_scripts/test_sdd_spec_intake_contract.py", "action": "CREATE"}
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

### Key Constraints
- Edit `.claude/commands/sdd-spec.md` first, then **regenerate the twin body
  from it**. Write the twin as its frontmatter + the edited original body with
  the one substitution applied. Do not hand-edit both files in parallel.
- Keep §1.5 ≤ 40 lines. The procedure holds the detail.
- The carry-forward path must stay byte-for-byte the same in behavior. Only
  add intake branches.
- If FEAT-576's TASK-3465 has landed, rebase first and re-verify every anchor
  line number (the counts stay 1).

---

## Implementation Blueprint

### Steps (in order)
1. Usage (`:8`): replace the line with the spec §2 "New Public Interfaces"
   signature, then add one paragraph under the existing `--type`/`--base-branch`
   paragraph that explains the intake flags and says they are ignored (with a
   notice) on the carry-forward path. *Why*: G1/G3/G6.
2. §1 (`:38-40`): make `<feature-name>` optional when intake runs, then append
   the trigger rule block (spec §2) and the "cannot ask ⇒ `--no-interview`"
   sentence. *Why*: G1, G11.
3. Insert **§1.5 Intake Mode** after §1 (block below). *Why*: M4.
4. `:48`: change it to "…proceed to §1.5 when intake mode is active, otherwise §3." *Why*: M4.
5. §3b preconditions (`:219-220`): add "**or** §1.5 ran and `intake.json.phase`
   is `rounds_complete`". In §3b.2 add an "in intake mode" sub-list with the
   intake sources from spec §2 "§3b in intake mode". *Why*: G7.
6. §3 (`:386`): add a first line "Skipped in intake mode — §1.5's adaptive
   rounds replace it." *Why*: M4.
7. §6: after the design-research promotion block, add an intake promotion
   block (same copy → mv → rm pattern, no overwrite). Set `feat_id` and
   `phase: committed` in `intake.json` **before** staging. Extend the
   `# Expected:` line with `[+ sdd/state/<FEAT-ID>/intake/*]`. *Why*: G5.
8. §7 feature output: after `:601`, add
   `   Intake: research <depth> (confidence <c> | degraded | skipped), rounds <n>, open questions <m>, Jira <KEY | created KEY | none>`
   plus a line "(intake mode only; after the output, run `/sdd-tojira` when Jira = create)". *Why*: G8.
9. Reference (`:639`): append the procedure and intake-schema bullets. *Why*: discoverability.
10. Regenerate the twin, edit SKILL.md, write the tests, and run the parity test.

### `.claude/commands/sdd-spec.md` (MODIFY) — §1.5
```markdown
# occurrences: 1 (verified: grep -cF '### 2. Check for Prior Exploration (and carry it forward)' .claude/commands/sdd-spec.md)
# BEFORE — insert above `### 2. Check for Prior Exploration (and carry it forward)` (verified: .claude/commands/sdd-spec.md:42)
### 1.5 Intake Mode (interactive only — FEAT-577)

Runs only when §1's trigger rule selects it. Follow
`sdd/templates/intake.procedure.md` §0–§8 end to end. It stages everything
under `sdd/state/.intake/<slug>-<RUN_ID>/` (git-ignored; pruned after 10 days
by a daily git hook), validated by `sdd/templates/intake.schema.json`, and returns
one of two outcomes:

- **handed off** (`phase: handed_off`) — the user chose `/sdd-brainstorm`; stop
  here: no spec, no FEAT-ID.
- **ready** (`phase: rounds_complete`) — continue at §2d with `doc_path=None`
  and the Round 0 flow as `--type`/`--base-branch` overrides; §3b uses the
  intake brief sources; §3 is skipped; §4 is seeded by the synthesis; §5
  reserves the FEAT-ID unchanged; §6 promotes the staging dir.

# FILL IN: ≤ 10 more lines only if needed (e.g. the --research/--no-gate/--budget defaults) — bounded by "§1.5 ≤ 40 lines" (spec M4)
```
**Why**: the twins carry the pointer and outcomes. The procedure carries the
how (spec §2 Overview, "Shared procedure file" decision).

### `.agents/skills/sdd-spec/SKILL.md` (MODIFY)
```markdown
# occurrences: 1 (verified: grep -cF 'Codex invocation: `$sdd-spec' .agents/skills/sdd-spec/SKILL.md) — line 11
# REPLACE with:
Codex invocation: `$sdd-spec [<feature-slug>] [--type feature|hotfix] [--base-branch <branch>] [--interview | --no-interview] [--resume [<staging-dir>]] [--research full|light|none] [--no-gate] [--budget tight|default|loose] [-- <notes>]`.

# occurrences: 1 (verified: grep -cF '   - optional `--base-branch`' .agents/skills/sdd-spec/SKILL.md) — line 44
# AFTER — insert below it:
   - intake flags (FEAT-577): with no brainstorm/proposal and no notes (or
     with `--interview`), run intake mode by following
     `sdd/templates/intake.procedure.md`; never in a non-interactive run.
```

### `tests/sdd_scripts/test_sdd_spec_intake_contract.py` (CREATE)
```python
"""Contract: /sdd-spec twins and codex skill expose intake mode (FEAT-577, spec §4)."""

from __future__ import annotations

from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_TWINS = (".claude/commands/sdd-spec.md", ".agent/workflows/sdd-spec.md")
_PROCEDURE = "sdd/templates/intake.procedure.md"


def _read(rel: str) -> str:
    path = _REPO_ROOT / rel
    if not path.is_file():
        pytest.skip(f"{rel} missing at this checkout")
    return path.read_text(encoding="utf-8")


@pytest.mark.parametrize("rel", _TWINS)
def test_sdd_spec_points_at_intake_procedure(rel: str) -> None:
    assert _PROCEDURE in _read(rel)
    assert (_REPO_ROOT / _PROCEDURE).is_file()


@pytest.mark.parametrize("rel", _TWINS)
def test_sdd_spec_documents_intake_flags(rel: str) -> None:
    text = _read(rel)
    for flag in ("--interview", "--no-interview", "--resume", "--research", "--no-gate", "--budget"):
        assert flag in text, f"{rel} does not document {flag}"


# FILL IN: test_codex_skill_mentions_intake — SKILL.md names intake.procedure.md and --no-interview — bounded by M5
```

### FILL IN checklist
- [ ] §1.5 extra lines (optional, ≤ 40 total)
- [ ] Steps 1, 2, 4–9 prose in the original, then twin regeneration
- [ ] `test_codex_skill_mentions_intake`

---

## Acceptance Criteria

- [ ] Both twins document the six intake flags, the trigger rule, §1.5, the §3b intake variant, the §6 intake promotion and the §7 Intake line
- [ ] The carry-forward path's steps are unchanged in behavior
- [ ] `tests/sdd_scripts/test_command_twin_parity.py` passes
- [ ] `tests/sdd_scripts/test_sdd_spec_intake_contract.py` passes

---

## Validation Commands

- `pytest tests/sdd_scripts/test_command_twin_parity.py -q`
- `pytest tests/sdd_scripts/test_sdd_spec_intake_contract.py -q`

---

## Test Specification

See the blueprint test module.

---

## Agent Instructions

1. Read spec §2 (trigger rule, §3b in intake mode, New Public Interfaces) and §3 Modules 4–5.
2. Rebase on `dev`; re-verify anchors (FEAT-576 TASK-3465 may have shifted lines).
3. Implement; regenerate the twin; run the Validation Commands.
4. Move this file to `sdd/tasks/completed/` and set the index status to `done`.

---

## Completion Note

Wired intake mode into both `/sdd-spec` twins (`.claude/commands/sdd-spec.md`,
`.agent/workflows/sdd-spec.md`, kept byte-identical apart from the
documented substitution) and `.agents/skills/sdd-spec/SKILL.md`: new flags,
§1 trigger rule, new §1.5 Intake Mode pointing at
`sdd/templates/intake.procedure.md`, §3b intake precondition + brief-source
mapping, §6 staging promotion, §7 output line. Created
`tests/sdd_scripts/test_sdd_spec_intake_contract.py`. Merged cleanly by the
engine (outcome: merged; lint autofix commit `8da826f75`, black only).

Merge-tier `select_tests --tier merge` run (with TASK-3474/3476 also
merged): 46 + 7 passed, no failures.

Seat: qwen (nova) · Backend: nova · Model: qwen.qwen3-coder-480b-a35b-instruct · Attempts: 1 · Duration: 613.5s · Tokens: 2602909/18556

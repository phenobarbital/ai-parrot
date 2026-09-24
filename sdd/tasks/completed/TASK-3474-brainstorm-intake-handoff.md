# TASK-3474: `/sdd-brainstorm` accepts a hand-off from `/sdd-spec` intake

**Feature**: FEAT-577 — `/sdd-spec` Intake Mode — Interview-Driven Spec Creation
**Spec**: `sdd/specs/sdd-feature-specification.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3469, TASK-3470
**Assigned-to**: unassigned

---

## Context

Implements spec §3 **Module 10** (G12). When `--research full` produces a
synthesis that recommends `sdd-brainstorm`, the intake offers a switch. If the
user accepts, it prints `/sdd-brainstorm <slug> -- intake: <staging-dir>`
(TASK-3470 §3b). `/sdd-brainstorm` must then treat the intake facts as already
answered, seed Round 1 from the synthesis, and still run its two mandatory
rounds.

**Deviation note**: the spec's Module 10 names only
`.claude/commands/sdd-brainstorm.md`. Its `.agent/workflows` twin (body
identical except the "Worktree policy" line, `:215`) and
`.agents/skills/sdd-brainstorm/SKILL.md` are updated too, so the three lanes
don't drift. There is no parity test for them.

---

## Scope

- `.claude/commands/sdd-brainstorm.md` + `.agent/workflows/sdd-brainstorm.md`:
  in §1 Parse Input, recognise `intake: <staging-dir>` in the `--` notes. Add an
  "Intake hand-off" block before Round 0 in §3. In §4, carry the synthesis
  `localization` into Code Context after re-verifying it.
- `.agents/skills/sdd-brainstorm/SKILL.md`: one bullet under "1. Parse input".
- `tests/sdd_scripts/test_brainstorm_intake_contract.py`.

**NOT in scope**: changing the brainstorm template, or making `/sdd-brainstorm`
write or delete anything under `sdd/state/.intake/`. It only reads; retention
is TASK-3473's.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `.claude/commands/sdd-brainstorm.md` | MODIFY | intake pointer parsing + hand-off block |
| `.agent/workflows/sdd-brainstorm.md` | MODIFY | identical body edit |
| `.agents/skills/sdd-brainstorm/SKILL.md` | MODIFY | codex summary bullet |
| `tests/sdd_scripts/test_brainstorm_intake_contract.py` | CREATE | contract test |

---

## Codebase Contract (Anti-Hallucination)

### Verified anchors (each occurs once per file)
- `.claude/commands/sdd-brainstorm.md` (214 lines): `:24` `### 1. Parse Input`; `:26` ``- **free-form notes**: anything after `--`, used as initial context.``; `:37` `### 3. Interactive Discovery (Mandatory — minimum 2 rounds)`; `:42` `**Round 0 — Flow type (always ask first; FEAT-145):**`; `:105` `### 4. Research the Codebase & Build Code Context`. The `.agent/workflows/sdd-brainstorm.md` twin has the same lines. Its only difference is `:215` (`AGENTS.md` vs `CLAUDE.md` worktree-policy line).
- `.agents/skills/sdd-brainstorm/SKILL.md`: `:54` `1. Parse input:` followed by ``   - notes after `--` ``.
- `intake.json` shape: `sdd/templates/intake.schema.json` (TASK-3469). Fields used here: `answers.{feature_name, projects, tags, overview, problem, why_important, jira}`, `flow.{type, base_branch}`, `research.synthesis_path`, `phase` (expected `handed_off`).
- `synthesis.json` fields used: `unknowns`, hypotheses / scope, `localization[].{path, symbol, lines}`, `recommended_next_command.{command, rationale}` (`sdd/templates/synthesis.prompt.md:158-166`, `:292-295`).

### Does NOT Exist
- ~~An `intake:` pointer in `/sdd-brainstorm`~~ — added here.
- ~~`/sdd-brainstorm` reading `sdd/state/` today~~ — it never has.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": ".claude/commands/sdd-brainstorm.md", "action": "MODIFY"},
    {"path": ".agent/workflows/sdd-brainstorm.md", "action": "MODIFY"},
    {"path": ".agents/skills/sdd-brainstorm/SKILL.md", "action": "MODIFY"},
    {"path": "tests/sdd_scripts/test_brainstorm_intake_contract.py", "action": "CREATE"}
  ],
  "contract_symbols": []
}
```

---

## Implementation Blueprint

### Steps (in order)
1. §1: add the pointer bullet. *Why*: a stable, greppable hand-off syntax.
2. §3: insert the hand-off block above Round 0. *Why*: facts already answered
   in intake must not be re-asked. The same principle as `/sdd-spec` §2b.
3. §4: add one sentence carrying the synthesis localization into Code Context.
4. Mirror the body to the `.agent` twin (keep its `:215` line). Update SKILL.md. Write the test.

### `.claude/commands/sdd-brainstorm.md` (MODIFY) — and the `.agent/workflows` twin
```markdown
# occurrences: 1 (verified: grep -cF -- '- **free-form notes**: anything after `--`, used as initial context.' .claude/commands/sdd-brainstorm.md) — line 26
# AFTER — insert below it:
- **intake hand-off** (FEAT-577): if the notes contain `intake: <staging-dir>`,
  this run continues a `/sdd-spec` intake that recommended a brainstorm — see
  "Intake hand-off" in §3.

# occurrences: 1 (verified: grep -cF '**Round 0 — Flow type (always ask first; FEAT-145):**' .claude/commands/sdd-brainstorm.md) — line 42
# BEFORE — insert above it:
**Intake hand-off (FEAT-577) — only when §1 found `intake: <staging-dir>`:**

Read `<staging-dir>/intake.json` (validate against
`sdd/templates/intake.schema.json`) and, when `research.synthesis_path` is set,
`<staging-dir>/synthesis.json`. Then:
- Round 0 and the intake facts (feature name, projects, overview, problem,
  Jira, why it matters) are **answered** — show them as a carry-in summary and
  do not re-ask them.
# FILL IN: seed Round 1 with the synthesis `unknowns` and competing hypotheses and the recommend rationale;
# the two mandatory rounds still run; missing/invalid staging dir ⇒ one-line warning and a normal brainstorm;
# never modify or delete the staging dir — bounded by spec M10 + G12/G13

# FILL IN (§4, after `### 4. Research the Codebase & Build Code Context`): one bullet — carry the synthesis
# `localization` entries into `## Code Context` only after re-reading each cited path/line — bounded by spec M10
```

### `.agents/skills/sdd-brainstorm/SKILL.md` (MODIFY)
```markdown
# occurrences: 1 (verified: grep -cF '   - notes after `--`' .agents/skills/sdd-brainstorm/SKILL.md) — line 56
# AFTER — insert below it:
   - `intake: <staging-dir>` in the notes (FEAT-577): read its `intake.json` /
     `synthesis.json`, treat the intake facts as answered, seed Round 1 from
     the synthesis unknowns.
```

### `tests/sdd_scripts/test_brainstorm_intake_contract.py` (CREATE)
```python
"""Contract: /sdd-brainstorm accepts the /sdd-spec intake hand-off (FEAT-577, spec §4 Module 10)."""

from __future__ import annotations

from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_FILES = (
    ".claude/commands/sdd-brainstorm.md",
    ".agent/workflows/sdd-brainstorm.md",
    ".agents/skills/sdd-brainstorm/SKILL.md",
)


@pytest.mark.parametrize("rel", _FILES)
def test_brainstorm_accepts_intake_pointer(rel: str) -> None:
    path = _REPO_ROOT / rel
    if not path.is_file():
        pytest.skip(f"{rel} missing at this checkout")
    text = path.read_text(encoding="utf-8")
    assert "intake: <staging-dir>" in text
    assert "intake.json" in text


# FILL IN: test_brainstorm_twins_differ_only_by_worktree_line — compare the two command bodies after replacing the
# single AGENTS.md/CLAUDE.md worktree-policy line — bounded by "lanes must not drift"
```

### FILL IN checklist
- [ ] hand-off block remainder (Round 1 seeding, failure mode, read-only)
- [ ] §4 localization bullet
- [ ] twin-drift test

---

## Acceptance Criteria

- [ ] `/sdd-brainstorm <slug> -- intake: <dir>` treats intake facts as answered, seeds Round 1 from the synthesis, and still runs 2 rounds (G12)
- [ ] It never writes to or deletes the staging dir
- [ ] Missing or invalid staging falls back to a normal brainstorm with a warning
- [ ] `pytest tests/sdd_scripts/test_brainstorm_intake_contract.py -q` passes

---

## Validation Commands

- `pytest tests/sdd_scripts/test_brainstorm_intake_contract.py -q`

---

## Test Specification

See the blueprint test module.

---

## Agent Instructions

1. Read spec §2 "Brainstorm hand-off" and §3 Module 10.
2. Confirm TASK-3469 and TASK-3470 are done (the schema and the procedure's §3b exist).
3. Implement; run the Validation Commands.
4. Move this file to `sdd/tasks/completed/` and set the index status to `done`.

---

## Completion Note

`/sdd-brainstorm` now accepts an `intake:` pointer hand-off (G12): §1 parses
the pointer from `--` notes, §3 inserts a hand-off block before Round 0 that
carries intake facts + synthesis `unknowns`/hypotheses forward as answered,
and §4 copies synthesis `localization` into `## Code Context` after
re-verification, with a graceful fallback (warning + normal run) on a
missing/invalid staging dir. Both twins (`.claude/commands/sdd-brainstorm.md`,
`.agent/workflows/sdd-brainstorm.md`) and `.agents/skills/sdd-brainstorm/SKILL.md`
updated; `tests/sdd_scripts/test_brainstorm_intake_contract.py` created.
Merged cleanly (outcome: merged; lint autofix commit `12a975976`).

Seat: mistral (nova) · Backend: nova · Model: mistral.devstral-2-123b · Attempts: 1 · Duration: 222.2s · Tokens: 974098/6014

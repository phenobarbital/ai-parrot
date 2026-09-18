# TASK-3475: Document `/sdd-spec` intake mode in the SDD workflow

**Feature**: FEAT-577 — `/sdd-spec` Intake Mode — Interview-Driven Spec Creation
**Spec**: `sdd/specs/sdd-feature-specification.spec.md`
**Status**: pending
**Priority**: low
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-3470
**Assigned-to**: unassigned

---

## Context

Implements the documentation half of spec §3 **Module 8** (the `.gitignore`
half is in TASK-3473). It documents the new entry point, its flags, and how it
relates to `/sdd-brainstorm` / `/sdd-proposal`.

**Deviation note**: the spec names `docs/sdd/WORKFLOW.md`. That file is a stale
copy last touched 2026-06-15. The canonical, current workflow doc is
`sdd/WORKFLOW.md` (16,981 bytes, updated 2026-09-06). It holds `## Commands
Reference` at `:352`, and `CLAUDE.md` points to it ("see `sdd/WORKFLOW.md`").
Edit `sdd/WORKFLOW.md`, and do not touch the stale copy.

---

## Scope

- Add a section "## Starting from an interview: `/sdd-spec` intake mode
  (FEAT-577)" to `sdd/WORKFLOW.md`, placed immediately **before**
  `## Commands Reference`.
- Update the `/sdd-spec` row in the Commands Reference table to mention intake mode.
- Write `tests/sdd_scripts/test_intake_docs.py`.

**NOT in scope**: `docs/sdd/WORKFLOW.md` (stale), `CLAUDE.md`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `sdd/WORKFLOW.md` | MODIFY | new intake section + Commands Reference row |
| `tests/sdd_scripts/test_intake_docs.py` | CREATE | doc contract test |

---

## Codebase Contract (Anti-Hallucination)

### Verified anchors
- `sdd/WORKFLOW.md`: `:352` `## Commands Reference` (occurs once); the `/sdd-spec` table row
  ``| `/sdd-spec` | `sdd-spec` | Scaffold a formal Feature Specification from exploration or direct request |`` (occurs once).
- Flags and behavior to document: spec §2 "New Public Interfaces", trigger rule, research depths, brainstorm hand-off (G12), retention (G13), resume.
- `sdd/templates/intake.procedure.md` — created by TASK-3470 (link to it rather than duplicating it).

### Does NOT Exist
- ~~A `/sdd-feature` command~~ — do not document one.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "sdd/WORKFLOW.md", "action": "MODIFY"},
    {"path": "tests/sdd_scripts/test_intake_docs.py", "action": "CREATE"}
  ],
  "contract_symbols": []
}
```

---

## Implementation Blueprint

### Steps (in order)
1. Insert the section before `## Commands Reference`. *Why*: readers of the
   lifecycle find it next to the command table.
2. Edit the `/sdd-spec` table row.
3. Write the test.

### `sdd/WORKFLOW.md` (MODIFY)
```markdown
# occurrences: 1 (verified: grep -cxF '## Commands Reference' sdd/WORKFLOW.md) — line 352
# BEFORE — insert above it:
## Starting from an interview: `/sdd-spec` intake mode (FEAT-577)

When you already know what you want and have no brainstorm or proposal, run
`/sdd-spec` with no `--` notes (or pass `--interview`). It asks a fixed intake
batch, researches the codebase (`--research full|light|none`, default `full`),
runs 2–4 follow-up rounds informed by the findings, and writes a **spec**
directly. The full procedure is `sdd/templates/intake.procedure.md`.

# FILL IN: a short flow line (intake → research → rounds → spec), a flags table (--interview, --no-interview,
# --resume [<staging-dir>], --research, --no-gate, --budget), the brainstorm hand-off (G12), staging + 10-day
# pruning by /sdd-status (G13), "unattended lanes always pass --no-interview", and when to prefer /sdd-brainstorm
# or /sdd-proposal instead — bounded by spec §2; ≤ 60 lines

# occurrences: 1 (verified: grep -cF '| `/sdd-spec` | `sdd-spec` |' sdd/WORKFLOW.md)
# REPLACE the row's description cell with:
Scaffold a formal Feature Specification from exploration, a direct request, or an intake interview (FEAT-577)
```

### `tests/sdd_scripts/test_intake_docs.py` (CREATE)
```python
"""Contract: sdd/WORKFLOW.md documents /sdd-spec intake mode (FEAT-577)."""

from __future__ import annotations

from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]


def test_workflow_documents_intake_mode() -> None:
    text = (_REPO_ROOT / "sdd" / "WORKFLOW.md").read_text(encoding="utf-8")
    assert "intake mode" in text
    assert "sdd/templates/intake.procedure.md" in text
    for flag in ("--interview", "--no-interview", "--research"):
        assert flag in text
    # FILL IN: assert the section precedes "## Commands Reference" — bounded by Step 1
```

### FILL IN checklist
- [ ] section body (≤ 60 lines)
- [ ] ordering assertion

---

## Acceptance Criteria

- [ ] `sdd/WORKFLOW.md` documents intake mode, its flags, the hand-off and retention
- [ ] `docs/sdd/WORKFLOW.md` is untouched
- [ ] `pytest tests/sdd_scripts/test_intake_docs.py -q` passes

---

## Validation Commands

- `pytest tests/sdd_scripts/test_intake_docs.py -q`

---

## Test Specification

See the blueprint test module.

---

## Agent Instructions

1. Confirm TASK-3470 is done (the procedure exists).
2. Implement; run the Validation Commands.
3. Move this file to `sdd/tasks/completed/` and set the index status to `done`.

---

## Completion Note

*(Agent fills this in when done)*

# TASK-3639: Git tracking rules for `examples/planogram/aws/`

**Feature**: FEAT-592 — Amazon Nova 2 Lite slot identification for planogram images
**Spec**: `sdd/specs/nova-image-planogram.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Implements spec §3 Module 1. `.gitignore:418` ignores the whole
`examples/planogram/*` tree, so every file the rest of FEAT-592 creates under
`examples/planogram/aws/` would silently never reach a commit. The repo's
established convention for example code is explicit negation rules — see the
`pipelines/` block at `.gitignore:438-441` — not `git add -f`. This task lands
those rules FIRST so the other five tasks can commit their files normally.

Design-research suggestion S11 (spec §9) raised the same point; it is confirmed
there and corrects the brainstorm, which had said `git add -f`.

---

## Scope

- Add a negation block for `examples/planogram/aws/` to `.gitignore`, copying the
  shape of the existing `pipelines/` block so code and README are tracked while
  photos, results and the vision cache stay ignored.
- Add one `NOT_IGNORED` row to the existing gitignore invariant test.

**NOT in scope**: creating any file under `examples/planogram/aws/` (tasks
TASK-3640…TASK-3644 own those); touching the `tests/` negation rules
(`.gitignore:424-425` already un-ignores `examples/planogram/tests/**/*.py`, so
the new test files of the other tasks are covered).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `.gitignore` | MODIFY | Negation block un-ignoring `examples/planogram/aws/` code + README |
| `examples/planogram/tests/test_plancheck_gitignore.py` | MODIFY | One `NOT_IGNORED` row for the new example path |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# No new imports. The test module already has everything it needs:
import subprocess          # verified: examples/planogram/tests/test_plancheck_gitignore.py:4
from pathlib import Path   # verified: examples/planogram/tests/test_plancheck_gitignore.py:5
import pytest              # verified: examples/planogram/tests/test_plancheck_gitignore.py:7
```

### Existing Signatures to Use
```python
# examples/planogram/tests/test_plancheck_gitignore.py
REPO_ROOT = Path(__file__).resolve().parents[3]          # line 9
NOT_IGNORED = [                                          # line 11  ← the list to extend
    "examples/planogram/plancheck/any_module.py",        # line 12
    "examples/planogram/tests/test_any_module.py",       # line 13
    "examples/planogram/planogram_check.py",             # line 14
    "examples/planogram/white_label_detector/detect_price_labels.py",   # line 15
]
IGNORED = [...]                                          # line 17
def _is_ignored(path: str) -> bool: ...                  # line 25 — git check-ignore -q, rc 0 = ignored
@pytest.mark.parametrize("path", NOT_IGNORED)            # line 33
def test_gitignore_tracks_code_not_photos(path: str) -> None: ...   # line 34
```

```gitignore
# .gitignore — the block this task copies (verified: .gitignore:437-441)
# FEAT-574: ink-wall pipeline example (code only — generated definitions,
# renders, reports and the vision cache are retailer-derived and stay ignored)
!examples/planogram/pipelines/
examples/planogram/pipelines/*
!examples/planogram/pipelines/*.py
!examples/planogram/pipelines/README.md
```

### Does NOT Exist
- ~~`examples/planogram/aws/`~~ — the directory does not exist yet; this task does NOT create it.
- ~~a `NOT_IGNORED` entry for any `aws/` path~~ — none today.
- ~~a `.gitignore` negation for `examples/planogram/aws/`~~ — `.gitignore:418` ignores it.
- ~~`git add -f` as this repo's convention~~ — negation rules are the convention (`.gitignore:419-441`).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": ".gitignore",
      "action": "MODIFY"
    },
    {
      "path": "examples/planogram/tests/test_plancheck_gitignore.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:examples/planogram/tests/test_plancheck_gitignore.py#_is_ignored",
    "sym:examples/planogram/tests/test_plancheck_gitignore.py#test_gitignore_tracks_code_not_photos"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Order matters in `.gitignore`: a negation must come AFTER the rule that ignored
  the path, and git cannot re-include a file if a parent directory is excluded —
  which is why the block re-includes the directory (`!…/aws/`), re-excludes its
  contents (`…/aws/*`), then re-includes the code (`!…/aws/*.py`).
- Append at the END of the planogram block so the existing rules are untouched.
- Do not broaden the rules: photos, `results/` and any cache dropped inside
  `examples/planogram/aws/` must stay ignored.

### References in Codebase
- `.gitignore:437-441` — the `pipelines/` block, the exact pattern to copy.
- `.gitignore:430-433` — the `perception_spike/` block, the same pattern.
- `examples/planogram/tests/test_plancheck_gitignore.py` — the invariant test.

---

## Implementation Blueprint

### Steps (in order)
1. Append the four-line negation block (plus its comment) to the very end of `.gitignore` — *why*: a negation is only effective after the rule that ignored the path, and `.gitignore:441` is currently the last line of the planogram section.
2. Add the new example path to `NOT_IGNORED` in the invariant test — *why*: the list is what pins the tracking decision; without a row, a future rule change could silently re-ignore `aws/` and no test would notice.
3. Run the validation command and confirm both the new row and the four existing ones pass — *why*: the test is parametrized, so a wrong rule shows up as exactly one failing case.

### `.gitignore` (MODIFY)
```gitignore
# occurrences: 1 (verified: grep -c '!examples/planogram/pipelines/README.md' .gitignore)
# AFTER — insert below `!examples/planogram/pipelines/README.md` (verified: .gitignore:441)
# FEAT-592: Nova 2 Lite planogram identification example (code only — photos,
# results and the vision cache are retailer-derived and stay ignored)
!examples/planogram/aws/
examples/planogram/aws/*
!examples/planogram/aws/*.py
!examples/planogram/aws/README.md
```
**Why this shape**: `.gitignore:418` (`examples/planogram/*`) excludes the `aws`
directory itself, and git will not re-include a file whose parent directory is
excluded — so the directory must be re-included first (`!…/aws/`), its contents
re-excluded (`…/aws/*`), and only then the code and README re-included. This is
the identical four-line shape used for `pipelines/` at `.gitignore:438-441` and
`perception_spike/` at `.gitignore:430-433`. Do NOT replace the `…/aws/*` line
with a broader negation: it is what keeps photos and results ignored.

### `examples/planogram/tests/test_plancheck_gitignore.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '    "examples/planogram/white_label_detector/detect_price_labels.py",' examples/planogram/tests/test_plancheck_gitignore.py)
# AFTER — insert below `    "examples/planogram/white_label_detector/detect_price_labels.py",` (verified: examples/planogram/tests/test_plancheck_gitignore.py:15)
    "examples/planogram/aws/nova2.py",
```
**Why**: `NOT_IGNORED` is the list that pins which example paths must stay
trackable; the parametrized test at line 34 asserts `git check-ignore` reports
each one as NOT ignored. Adding the row makes the FEAT-592 tracking decision a
tested invariant rather than a convention someone can undo by accident. Note the
path need not exist on disk — `git check-ignore` evaluates the pattern, not the
file — so this row is valid before TASK-3643 creates `nova2.py`.

### FILL IN checklist
- [ ] none — this task is fully mechanical; both blocks are complete as written.

---

## Acceptance Criteria

- [ ] `git check-ignore -q examples/planogram/aws/nova2.py` exits 1 (NOT ignored).
- [ ] `git check-ignore -q examples/planogram/aws/README.md` exits 1 (NOT ignored).
- [ ] `git check-ignore -q examples/planogram/aws/results/x.json` exits 0 (still ignored) — spec AC7.
- [ ] `git check-ignore -q examples/planogram/planogram_page1.json` exits 0 (unchanged).
- [ ] All five `NOT_IGNORED` cases and all four `IGNORED` cases pass — spec AC8.
- [ ] No rule outside the FEAT-592 block is modified (`git diff .gitignore` shows only appended lines).

---

## Validation Commands

- `pytest examples/planogram/tests/test_plancheck_gitignore.py -q`

---

## Test Specification

No new test module. The existing parametrized test gains one case through the
`NOT_IGNORED` row:

```python
# examples/planogram/tests/test_plancheck_gitignore.py (existing, extended)
@pytest.mark.parametrize("path", NOT_IGNORED)
def test_gitignore_tracks_code_not_photos(path: str) -> None:
    """Code, tests and the detector script are NOT ignored."""
    assert not _is_ignored(path)
    # new case: "examples/planogram/aws/nova2.py"
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context (§3 Module 1, §9 S11).
2. **Check dependencies** — none.
3. **Verify the Codebase Contract** — re-run both `grep -c` counts in the blueprint
   before editing; a count other than 1 means the anchor moved and you must
   re-locate it, never invent a new attachment point.
4. **Update status** in `sdd/tasks/index/nova-image-planogram.json` → `"in-progress"`.
5. **Implement** — apply both blueprint blocks verbatim.
6. **Verify** all acceptance criteria are met.
7. **Move this file** to `sdd/tasks/completed/TASK-3639-gitignore-tracking-rules.md`.
8. **Update index** → `"done"`.
9. **Fill in the Completion Note** below.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any

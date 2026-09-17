# TASK-3336: Make the planogram example trackable (.gitignore + detector adoption)

**Feature**: FEAT-565 — New Planogram Compliance Algorithm
**Spec**: `sdd/specs/new-planogram-compliance-algo.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 0. `examples/planogram/` is ignored as a whole directory (`.gitignore:5`),
and `examples/**/*.py` (`.gitignore:21`) ignores every example script again. Until this
task lands, `git add` silently drops every file the other FEAT-565 tasks create, and a
feature worktree contains nothing under `examples/planogram/`. Every other task therefore
depends on this one.

The repository is **PUBLIC**. Spec §8 Q1 decided that `planogram_page1.json` (extraction of
a retailer planogram PDF), the store photos, videos, PDFs and result artefacts stay
**untracked**. Only code, tests, the README, `catalog.example.json` and the generic OpenCV
detector script become trackable.

> **EXECUTION CONSTRAINT — read before starting.** This task runs in the **primary
> checkout**, on `dev`, as one plain commit, and is pushed **before** the FEAT-565 feature
> worktree is created. The detector script it adopts is an untracked file that exists only
> in the primary checkout — a sub-worktree cannot see it. It is `parallel: false`
> (exclusive): it edits the repo-wide `.gitignore`.

---

## Scope

- Delete the single line `examples/planogram/` from `.gitignore`.
- Append the FEAT-565 re-include block (below, verbatim) at the **end** of `.gitignore`, so its
  negations outrank `examples/**/*.py` and every other `examples/` rule above it.
- Adopt (first commit of an existing, currently untracked file, content unchanged)
  `examples/planogram/white_label_detector/detect_price_labels.py`.
- Add `examples/planogram/tests/test_plancheck_gitignore.py` asserting the ignore matrix.
- Commit exactly these three paths; push `dev`.

**NOT in scope**: tracking `planogram_page1.json`, photos, `inkcheck/`, `results/`, zips, PDFs,
videos, `white_label_detector/README.md|requirements.txt|examples/`; creating `plancheck/` or
`tests/conftest.py` (TASK-3337); reformatting the detector script.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `.gitignore` | MODIFY | Remove line 5 `examples/planogram/`; append the FEAT-565 re-include block at EOF |
| `examples/planogram/white_label_detector/detect_price_labels.py` | CREATE | Adopt the existing untracked script unchanged (first time in git) |
| `examples/planogram/tests/test_plancheck_gitignore.py` | CREATE | `test_gitignore_tracks_code_not_photos` — ignore-matrix assertions |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
import subprocess   # stdlib
from pathlib import Path  # stdlib
import pytest
```

### Existing Signatures to Use
```text
# .gitignore  (412 lines; sha256 fe10325e08e1957d97745918efc68f71848356d53307b758c5ef32bc7712d3ad at task-writing time)
5:   examples/planogram/            ← occurrences of this exact line: 1 (verified: grep -c '^examples/planogram/$' .gitignore)
21:  examples/**/*.py               ← blanket rule the new negations must come AFTER
51:  !examples/dev_loop/**/*.py     ← precedent: a re-include placed after the blanket rules
314-317: examples/loaders/*.…       ← last examples/ rules; the new block goes at END OF FILE

# examples/planogram/white_label_detector/detect_price_labels.py
#   untracked, 214 lines, sha256 6ac066d61e4ad4d59658fbf0f2590998c1e545beed146fde553bdad82f414c7f
#   def candidates(image, min_width, max_width)               # :15
#   def group_rows(items, image_width, min_row_labels=4, max_slope=.12)  # :55
```
The block below was **dry-run verified** on 2026-09-17 (applied, checked with
`git check-ignore`, reverted): the eight code paths were not ignored; photos, results,
`inkcheck/`, `planogram_page1.json`, `white_label_detector/README.md`, `__pycache__/*.pyc`
and `examples/planogram/yolo_test.py` stayed ignored.

### Does NOT Exist
- ~~a way to re-include a file under an excluded *directory*~~ — git cannot; that is why line 5
  (`examples/planogram/`, a directory rule) must be **deleted** and replaced by `examples/planogram/*`.
- ~~`git add -f` as the mechanism~~ — rejected in the spec: coder agents use plain `git add`.
- ~~`examples/planogram/plancheck/`~~, ~~`the tests conftest`~~ — not created here (TASK-3337).
- ~~tracking `planogram_page1.json`~~ — explicitly forbidden (spec §8 Q1, public repo).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": ".gitignore", "action": "MODIFY"},
    {"path": "examples/planogram/white_label_detector/detect_price_labels.py", "action": "CREATE"},
    {"path": "examples/planogram/tests/test_plancheck_gitignore.py", "action": "CREATE"}
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

### Key Constraints
- Order matters in `.gitignore`: the last matching pattern wins. Append at EOF; do not insert near line 5.
- Do not touch any other `.gitignore` line. Do not stage anything except the three declared paths
  (`git add .` is forbidden — the primary checkout holds other sessions' untracked work).
- The detector script is adopted byte-for-byte (verify the sha256 above before `git add`); if the
  hash differs, STOP and report — someone edited it.
- The test shells out to `git check-ignore`; it must `pytest.skip` when not inside a git work tree.

### References in Codebase
- `.gitignore:44-52` — the `examples/dev_loop` re-include precedent and its explanatory comment style.

---

## Implementation Blueprint

### Steps (in order)
1. `git status --porcelain | grep -v '^??'` must be empty and the branch must be `dev` in the primary checkout — *why*: this is a direct commit to `dev`; never mix it with unrelated edits.
2. Verify `sha256sum examples/planogram/white_label_detector/detect_price_labels.py` equals the contract value — *why*: we publish this file to a public repo; adopt exactly what was reviewed.
3. Delete `.gitignore` line 5 and append the block at EOF — *why*: a directory-level exclude cannot be partially re-included; the block must be last to outrank `examples/**/*.py`.
4. Create the test file and run it — *why*: the ignore matrix is the acceptance criterion and guards against a later `.gitignore` edit re-hiding the code.
5. `git add` the three paths only; confirm with `git diff --cached --name-only`; commit `chore(FEAT-565): track planogram example code, keep retailer data ignored`; push — *why*: the worktree is created from `origin/dev`.

### `.gitignore` (MODIFY)
```gitignore
# occurrences: 1 (verified: grep -c '^examples/planogram/$' .gitignore)
# DELETE the line `examples/planogram/` (verified: .gitignore:5)

# APPEND at end of file (after the current last line, .gitignore:412):

# FEAT-565: planogram compliance example — track code + small inputs only.
# The repo is public: planogram_page1.json (retailer-derived), store photos,
# videos, PDFs, zips, inkcheck/ and results/ stay ignored by the first rule.
examples/planogram/*
!examples/planogram/planogram_check.py
!examples/planogram/README.md
!examples/planogram/catalog.example.json
!examples/planogram/plancheck/
!examples/planogram/plancheck/**/*.py
!examples/planogram/tests/
!examples/planogram/tests/**/*.py
!examples/planogram/white_label_detector/
examples/planogram/white_label_detector/*
!examples/planogram/white_label_detector/detect_price_labels.py
```
**Why**: `examples/planogram/*` ignores the directory's *children* (so they can be re-included),
the directory negations re-open the three code folders, and the `**/*.py` negations defeat the
earlier `examples/**/*.py`. `white_label_detector/` is re-opened and immediately re-closed so
only the one script gets through.

### `examples/planogram/white_label_detector/detect_price_labels.py` (CREATE)
```text
No content change. `git add examples/planogram/white_label_detector/detect_price_labels.py`
after step 2's hash check. (Listed as CREATE because the path is new to git.)
```
**Why**: TASK-3340's parity test loads this script; the README of the example links to it.

### `examples/planogram/tests/test_plancheck_gitignore.py` (CREATE)
```python
"""FEAT-565 M0: the planogram example's code is trackable, retailer data and photos are not."""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]

NOT_IGNORED = [
    "examples/planogram/plancheck/any_module.py",
    "examples/planogram/tests/test_any_module.py",
    "examples/planogram/planogram_check.py",
    "examples/planogram/white_label_detector/detect_price_labels.py",
]
IGNORED = [
    "examples/planogram/images/a.jpeg",
    "examples/planogram/results/x/compliance.json",
    "examples/planogram/inkcheck/README.md",
    "examples/planogram/planogram_page1.json",
]


def _is_ignored(path: str) -> bool:
    """Return True when git ignores ``path`` (exit 0), False when it does not (exit 1)."""
    proc = subprocess.run(["git", "check-ignore", "-q", path], cwd=REPO_ROOT, check=False)
    if proc.returncode not in (0, 1):
        pytest.skip(f"git check-ignore unavailable (rc={proc.returncode})")
    return proc.returncode == 0


@pytest.mark.parametrize("path", NOT_IGNORED)
def test_gitignore_tracks_code_not_photos(path: str) -> None:
    """Code, tests and the detector script are NOT ignored."""
    assert not _is_ignored(path)


@pytest.mark.parametrize("path", IGNORED)
def test_gitignore_keeps_data_ignored(path: str) -> None:
    """Photos, results, inkcheck and the retailer planogram stay ignored."""
    assert _is_ignored(path)
```
**Why this shape**: complete on purpose — the matrix is fully decided by spec §3 Module 0 (seven
assertions + the detector script). `parents[3]` = repo root from `examples/planogram/tests/`.

### FILL IN checklist
- [ ] none — every block above is complete; the only judgement is step 2's STOP condition.

---

## Acceptance Criteria

- [ ] `git check-ignore -q examples/planogram/plancheck/any_module.py` exits 1 (not ignored); same for the other three `NOT_IGNORED` paths.
- [ ] The four `IGNORED` paths exit 0 — in particular `examples/planogram/planogram_page1.json`.
- [ ] `git ls-files examples/planogram` lists exactly the detector script and the new test file.
- [ ] `git diff HEAD~1 --stat` shows only the three declared paths; `.gitignore` diff is −1 line / + the block.
- [ ] Commit is on `dev` and pushed to `origin/dev` before any FEAT-565 worktree exists.

---

## Validation Commands

- `pytest examples/planogram/tests/test_plancheck_gitignore.py -q`

---

## Test Specification

The blueprint's test file is the full specification (`test_gitignore_tracks_code_not_photos`,
`test_gitignore_keeps_data_ignored`).

---

## Agent Instructions

1. Read the EXECUTION CONSTRAINT in Context — primary checkout, `dev`, exclusive.
2. Follow the five blueprint steps in order; STOP on a hash mismatch or a dirty tree.
3. Verify all acceptance criteria.
4. Move this file to `sdd/tasks/completed/` and set the index entry (`sdd/tasks/index/new-planogram-compliance-algo.json`) to `done`.
5. Fill in the Completion Note.

---

## Completion Note

**Completed by**: sdd-worker (Sonnet 5, primary checkout, exclusive execution)
**Date**: 2026-09-18
**Notes**: Executed in the primary checkout on `dev` before the FEAT-565 worktree
existed, per the EXECUTION CONSTRAINT. Deleted `.gitignore:5` (`examples/planogram/`),
appended the FEAT-565 re-include block verbatim at EOF, adopted
`examples/planogram/white_label_detector/detect_price_labels.py` byte-for-byte
(sha256 `6ac066d61e4ad4d59658fbf0f2590998c1e545beed146fde553bdad82f414c7f` matched
the contract), and created
`examples/planogram/tests/test_plancheck_gitignore.py`. All 8 parametrized
assertions pass (`pytest examples/planogram/tests/test_plancheck_gitignore.py -q`).
`git diff --cached --name-only` showed exactly the three declared paths;
`git ls-files examples/planogram` lists exactly the detector script and the test
file. Committed as `f4ea5dc60` and pushed to `origin/dev`.

**Deviations from spec**: none

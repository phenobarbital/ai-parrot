# TASK-2736: `scripts/sdd/lint_new.py` — ruff findings the branch introduced

**Feature**: FEAT-497 — QA Gate: Verified Triage Evidence & Diff-Scoped Lint
**Spec**: `sdd/specs/qa-gate-evidence-and-diff-scoped-lint.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 2 (goals G3 + G4). The QA gate already scopes lint to the
files a feature changed (`QANode._scope_lint_to_files`), but it still lints
each changed file *in full*. On `run-49039bac`, a 5-line addition to
`catalog.py` inherited that file's 28 pre-existing `UP`-series findings plus
an `I001` and the gate went red, with the retry brief telling the worker to
modernise a file the feature barely touched.

This task adds a standalone repo script, `scripts/sdd/lint_new.py`, that
runs `ruff check --output-format json` over given files and keeps only the
findings whose reported **source range** (`location.row` … `end_location.row`)
intersects a line the branch added or modified. Range intersection is what
makes G4 work: `I001` is reported at the top of the import block with an
`end_location` spanning the block, so an import added five lines down still
intersects.

TASK-2737 wires the script into `QANode`; this task only creates and tests
the script. The spec says **write it verbatim** — the §3 Module 2 code block
is the deliverable.

---

## Scope

- Create `scripts/sdd/lint_new.py` exactly as given in spec §3 Module 2
  (module docstring, `_BASE_CANDIDATES`, `_HUNK_RE`, `_git`, `_merge_base`,
  `_parse_hunks`, `_added_lines`, `_ruff_findings`, `_is_new`, `_format`,
  `main`, `if __name__ == "__main__": raise SystemExit(main())`).
- CLI contract: `python -m scripts.sdd.lint_new [--base <ref>] <file> [<file> ...]`.
  Exit 0 = no new finding (pre-existing count reported informationally),
  exit 1 = at least one new finding (each printed in `ruff --output-format concise`
  shape), exit 2 = ruff could not run.
- Create `tests/sdd_scripts/test_lint_new.py` with the six §4 unit tests for
  Module 2, driven against a real `tmp_path` git repo.
- Verify the acceptance criterion from spec §5: on an unmodified `dev`
  checkout, `python -m scripts.sdd.lint_new packages/ai-parrot/src/parrot/flows/dev_loop/nodes/qa.py`
  exits 0 (the file's pre-existing findings do not fail it).

**NOT in scope**:
- Any change to `qa.py` (TASK-2735 and TASK-2737).
- Making `mypy` diff-aware (spec §1 Non-Goals).
- Gating on **removed** lines (spec §8 open question, defaults to "no").
- Fixing the pre-existing `UP`/`I001` debt in any file.
- A new configuration knob (G5).
- A second script name such as `lint_diff.py` — the file is `lint_new.py`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `scripts/sdd/lint_new.py` | CREATE | The diff-scoped ruff runner (spec §3 Module 2, verbatim) |
| `tests/sdd_scripts/test_lint_new.py` | CREATE | Unit tests against a real tmp git repo |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase
> (verified 2026-09-02 on `dev` @ `565e96561`).
> The implementing agent MUST use these exact imports, class names, and method signatures.
> **DO NOT** invent, guess, or assume any import, attribute, or method not listed here.
> If you need something not listed, VERIFY it exists first with `grep` or `read`.

### Verified Imports
```python
# scripts/sdd/lint_new.py — stdlib only, no parrot imports:
from __future__ import annotations
import argparse, json, os, re, subprocess, sys
from pathlib import Path

# tests/sdd_scripts/test_lint_new.py — the package import style used by the sibling tests:
from scripts.sdd.lint_new import main          # verified pattern: tests/sdd_scripts/test_check_id_collisions.py:6
                                               #   `from scripts.sdd.check_id_collisions import find_collisions, main`
```

`scripts/sdd/__init__.py` **exists** (0 bytes) and `tests/sdd_scripts/__init__.py`
**exists** (0 bytes), so `scripts.sdd.lint_new` is importable from the repo
root and `python -m scripts.sdd.lint_new` resolves — the same mechanism
`python -m scripts.sdd.reserve_ids` relies on.

### Existing Signatures to Use
```python
# Tool contract — verified with `ruff 0.16.3` (the venv's version):
#   ruff check --output-format json --force-exclude <paths>
# exits 0 with `[]` when clean, exits 1 with a JSON array when violations exist.
# Each element carries EXACTLY these keys (verified by running ruff on a probe file):
#   "code": "I001", "message": "...", "filename": "<ABSOLUTE path>",
#   "location": {"row": 1, "column": 1}, "end_location": {"row": 3, "column": 24},
#   plus "cell", "fix", "name", "noqa_row", "severity", "url"  (ignored by the script)
# `filename` is ABSOLUTE — hence `os.path.relpath(filename, repo_root)` in `_is_new`/`_format`.
# I001 on a 3-line import block: location.row=1, end_location.row=3  ← this is what G4 relies on.

# Sibling scripts for style reference:
#   scripts/sdd/check_id_collisions.py — argparse CLI with `def main(argv=None) -> int` and `raise SystemExit(main())`
#   scripts/sdd/reserve_ids.py         — `python -m scripts.sdd.<x>` invocation convention

# pytest config (pyproject.toml:216): testpaths = ["tests"] → tests/sdd_scripts/ is collected from the repo root.
```

### Does NOT Exist
- ~~`ruff check --diff-only`~~ / ~~`--changed-only`~~ / ~~`--baseline`~~ — no such
  ruff flags. Filtering MUST be done on ruff's JSON output.
- ~~`ruff check --output-format json-lines`~~ as the parse target — the script
  uses plain `json` (one array) and `json.loads(proc.stdout or "[]")`.
- ~~`scripts/sdd/lint_diff.py`~~ — wrong name; the file is `lint_new.py`.
- ~~`parrot.utils.git`~~ / ~~`parrot.flows.dev_loop.git_utils`~~ — no shared git
  helper module; the script shells out to `git` itself via `subprocess.run`.
- ~~`GitPython` / `git.Repo`~~ — not a dependency.
- ~~`conf.DEV_LOOP_LINT_BASELINE`~~ or any knob — G5: no configuration.
- ~~`origin/dev` in the test fixture~~ — the tmp repo has NO remotes; tests must
  pass `--base dev` explicitly (see Implementation Notes).

---

## Implementation Notes

### Pattern to Follow
The spec §3 Module 2 code block is the implementation — copy it verbatim.
It is a **standalone synchronous CLI**, so `subprocess.run` is correct here
(the async-only rule applies inside `parrot/`, not to repo scripts).

Key behaviours the tests pin down:
- `_added_lines` runs ONE `git diff -U0 <merge-base> -- <paths>` (covers
  committed and uncommitted work together) and then adds every line of any
  **untracked** file (`git ls-files --others --exclude-standard`).
- `_is_new` returns `True` (fail closed, report it) when the finding cannot be
  attributed (`relpath` raises, or `location.row <= 0`), and `False` when the
  file has no added lines at all.
- `--force-exclude` is passed to ruff so explicitly listed files that the
  project excludes stay excluded, matching `ruff check .` behaviour.

### Test fixture (from spec §4)
```python
@pytest.fixture
def repo(tmp_path, monkeypatch):
    """A real git repo on a branch forked from `dev`-shaped history."""
    def run(*args):
        subprocess.run(args, cwd=tmp_path, check=True, capture_output=True)

    run("git", "init", "-q", "-b", "dev")
    run("git", "config", "user.email", "t@t.t")
    run("git", "config", "user.name", "t")
    (tmp_path / "mod.py").write_text("from typing import Dict\n\nX: Dict = {}\n")   # carries UP035 baseline debt
    run("git", "add", "-A")
    run("git", "commit", "-qm", "baseline")
    run("git", "checkout", "-qb", "feature")
    monkeypatch.chdir(tmp_path)
    return tmp_path
```
- **Always pass `--base dev`** in these tests: the fixture has no `origin/*`
  refs, and relying on the `_BASE_CANDIDATES` fallback would make the tests
  depend on the developer's own remote state.
- **Ruff config isolation**: the tmp repo has no `pyproject.toml`, so ruff
  walks up from `tmp_path` and may pick up a user-level config, or default to
  its built-in rule set (which does NOT include `UP` or `I`). To make the
  baseline violation deterministic, write a minimal `ruff.toml` into the
  fixture repo **before the baseline commit**, e.g.
  `[lint]\nselect = ["E", "F", "I", "UP"]\n`, and commit it as part of the
  baseline. Verify locally that `ruff check --output-format json mod.py`
  inside the fixture reports `UP035` before relying on it.
- Call `main([...])` directly with an argv list and assert on the return
  code; use `capsys` to assert the printed finding for the exit-1 cases.
- `test_ruff_failure_exits_two`: `monkeypatch.setattr(subprocess, "run", ...)`
  to raise `OSError` only for the `ruff` invocation (or monkeypatch
  `lint_new._ruff_findings` to return `None`) — do NOT depend on ruff being
  absent from `PATH`.

### Key Constraints
- Google-style docstrings + strict type hints (the spec text already has them).
- Stdlib only; no new dependency (`ruff` is already a dev dependency).
- Run everything from the repo root: `python -m scripts.sdd.lint_new ...`.
- The pre-existing `ModuleNotFoundError: parrot.utils.types` collection error
  seen on `run-49039bac` is an environment problem and NOT in scope.

### References in Codebase
- `scripts/sdd/check_id_collisions.py` — argparse + `main(argv) -> int` style.
- `tests/sdd_scripts/test_check_id_collisions.py` — `tmp_path` fixture and CLI test style (`TestCli` class with `capsys`).
- `packages/ai-parrot/src/parrot/flows/dev_loop/nodes/qa.py:681-708` — `_get_changed_files` tries `origin/dev` then `origin/main`; `_BASE_CANDIDATES` mirrors that order.

---

## Acceptance Criteria

- [ ] `scripts/sdd/lint_new.py` exists and matches spec §3 Module 2.
- [ ] `python -m scripts.sdd.lint_new` with no paths exits 0.
- [ ] From the repo root on an unmodified `dev` checkout: `python -m scripts.sdd.lint_new packages/ai-parrot/src/parrot/flows/dev_loop/nodes/qa.py` exits 0 (pre-existing findings are ignored — G3).
- [ ] Injecting a fresh violation on a changed line makes the script exit 1 and print the finding in `path:row:col: CODE message` shape (G4).
- [ ] An out-of-order import added below an existing block is attributed to the branch via `I001` range intersection (G4).
- [ ] An untracked file with a violation exits 1.
- [ ] ruff unavailable → exit 2.
- [ ] All tests pass: `pytest tests/sdd_scripts/test_lint_new.py -v`.
- [ ] No linting errors: `ruff check scripts/sdd/lint_new.py tests/sdd_scripts/test_lint_new.py`.
- [ ] No new dependency in any `pyproject.toml`; no new entry in `parrot/conf.py`.

---

## Test Specification

```python
# tests/sdd_scripts/test_lint_new.py
from __future__ import annotations

import subprocess

import pytest

from scripts.sdd import lint_new
from scripts.sdd.lint_new import main


@pytest.fixture
def repo(tmp_path, monkeypatch):
    ...  # as in Implementation Notes (includes a committed ruff.toml selecting E,F,I,UP)


def test_no_paths_exits_zero(capsys):
    assert main([]) == 0


def test_pre_existing_finding_on_unchanged_line_is_ignored(repo, capsys):
    """Baseline mod.py carries UP035; the branch appends a clean line → exit 0."""
    (repo / "mod.py").write_text("from typing import Dict\n\nX: Dict = {}\nY = 1\n")
    assert main(["--base", "dev", "mod.py"]) == 0
    assert "pre-existing finding(s)" in capsys.readouterr().out


def test_new_finding_on_added_line_fails(repo, capsys):
    """Branch adds a line with an F841/F401-style violation → exit 1, finding printed."""
    (repo / "mod.py").write_text("from typing import Dict\nimport os\n\nX: Dict = {}\n")  # os unused → F401
    assert main(["--base", "dev", "mod.py"]) == 1
    assert "F401" in capsys.readouterr().out


def test_i001_import_block_is_attributed_to_the_added_import(repo, capsys):
    """Adding an out-of-order import → I001 reported even though its row (1) is unchanged (G4)."""
    (repo / "mod.py").write_text("from typing import Dict\nimport aaa\n\nX: Dict = {}\n")
    assert main(["--base", "dev", "mod.py"]) == 1
    assert "I001" in capsys.readouterr().out


def test_untracked_file_counts_as_fully_added(repo, capsys):
    (repo / "new.py").write_text("import os\n")   # F401
    assert main(["--base", "dev", "new.py"]) == 1


def test_ruff_failure_exits_two(repo, monkeypatch, capsys):
    monkeypatch.setattr(lint_new, "_ruff_findings", lambda paths: None)
    assert main(["--base", "dev", "mod.py"]) == 2
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context — §3 Module 2 is the implementation, verbatim.
2. **Check dependencies** — none.
3. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm `scripts/sdd/__init__.py` and `tests/sdd_scripts/__init__.py` exist
   - Confirm the ruff JSON shape by running ruff on a probe file (`location`/`end_location`/`filename` keys)
   - If anything has changed, update the contract FIRST, then implement
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
4. **Update status** in `sdd/tasks/index/qa-gate-evidence-and-diff-scoped-lint.json` → `"in-progress"` with your session ID
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-2736-lint-new-diff-scoped-ruff.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any

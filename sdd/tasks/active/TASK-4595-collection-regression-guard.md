# TASK-4595: Regression guard for package test-collection identity

**Feature**: FEAT-720 — One Importable Identity per Package Test Tree
**Spec**: `sdd/specs/tests-test-wheel-layout-tech-debt-2.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-4594
**Assigned-to**: unassigned
**Discovered-from**: `issue:45cf6a054e06`

---

## Context

Implements spec **Module 4**.

The collision this feature removes is cheap to reintroduce: adding one
`__init__.py` to a new package's test root brings it all back, and nothing in CI
would notice until two distributions happened to be collected together — which
is exactly how it went unnoticed for months in the first place. This task adds
the test that turns that silent regression into a red build.

It runs last because it asserts the end state TASK-4591–4594 create. Written
earlier, its own validation would be circular.

---

## Scope

- Add `packages/ai-parrot/tests/test_package_test_collection.py` with two tests:
  1. no `packages/*/tests/__init__.py` exists;
  2. two package test trees collect together with exit 0.
- Demonstrate the guard actually guards: add an `__init__.py`, observe red,
  remove it (AC8).

**NOT in scope**: changing any existing test; repairing any import site
(TASK-4592/4593/4594); deleting any `__init__.py` for real (TASK-4591); adding a
CI workflow step (the test runs in the existing suite); any `parrot-formdesigner`
failure (FEAT-618).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/tests/test_package_test_collection.py` | CREATE | The two regression tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# stdlib only — this test must not import parrot, and must not import pytest
# plugins that the subprocess session would also load.
from __future__ import annotations
import subprocess
import sys
from pathlib import Path
```

### Existing Signatures to Use

```toml
# pyproject.toml:247 — the config TASK-4591 amended
[tool.pytest.ini_options]
addopts = [
    "--strict-config",
    "--strict-markers",
    "--import-mode=importlib",   # added by TASK-4591
]
markers = [                      # line 264 — --strict-markers is in force
    "asyncio: ...",
    "real_llm: ...",
    "live_google: ...",
]
```

### Verified facts (measured on `dev c2fd0ae28`, i.e. BEFORE this feature)

| Fact | Value then | Value this task asserts |
|---|---|---|
| top-level `packages/*/tests/__init__.py` | 25 | **0** |
| all `__init__.py` under `packages/*/tests` | 267 | **242** |
| the AC1 pair collect | `ImportPathMismatchError` | exit 0 |

### Does NOT Exist
- ~~a marker for "slow" or "subprocess" tests~~ — `markers` at `pyproject.toml:264`
  declares exactly `asyncio`, `real_llm` and `live_google`. `--strict-markers` is
  in force, so **inventing a marker makes the whole suite error**. Use an existing
  marker or none.
- ~~`pytester` / `testdir` fixtures~~ — verify `pytest-pytester` is actually
  enabled before relying on it; prefer a plain `subprocess` call, which has no
  plugin dependency.
- ~~a repo-root constant pointing at `packages/`~~ — derive the repo root from
  `__file__`, not from `os.getcwd()`, which differs between a worktree, CI and a
  sub-worktree run.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/tests/test_package_test_collection.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

### Key Constraints
- **Do not invent a pytest marker.** `--strict-markers` is on and the allowed set
  is fixed at `pyproject.toml:264`.
- The second test **spawns pytest in a subprocess**. It must not be collected by
  the session it spawns — scope the subprocess to two specific test trees, never
  to the repo root.
- Use `sys.executable -m pytest`, not a bare `pytest`, so the subprocess uses the
  same interpreter and environment.
- Give the subprocess a timeout. A hung collect must fail the test, not the run.
  This repo has a documented history of pytest sessions hanging after the summary
  line.
- Derive the repo root from `Path(__file__).resolve().parents[N]` — count `N`
  against the real path, do not guess.
- Assert on **both** failure shapes: `ImportPathMismatchError` and
  `already registered`. The second is what `--import-mode=importlib` alone
  produces, and catching only the first would let a half-fix pass.

### References in Codebase
- `sdd/specs/tests-test-wheel-layout-tech-debt-2.spec.md` §2 — the two failure
  strings and why both are needed
- `packages/ai-parrot-embeddings/tests/test_wheel_layout.py` — the canonical
  victim; a good second operand for the pair collect

---

## Implementation Blueprint

### Steps (in order)
1. Derive the repo root from `__file__` and assert `packages/` exists under it —
   *why*: a wrong root makes both tests vacuously pass, which is the worst
   possible outcome for a guard.
2. Write the first test as a filesystem assertion — *why*: it is fast, needs no
   subprocess, and catches the regression at its source (a new `__init__.py`).
3. Write the second test as a subprocess collect — *why*: the first test cannot
   catch a collision reintroduced by any other mechanism, and the real invariant
   is "two trees collect", not "no file exists".
4. Verify the guard by temporarily creating a `packages/*/tests/__init__.py`,
   running both tests, and confirming red — *why*: AC8 requires demonstrated
   sensitivity, and a guard that cannot fail is worse than none.
5. Remove the temporary file and confirm green — *why*: the demonstration must
   not land.

### `packages/ai-parrot/tests/test_package_test_collection.py` (CREATE)
```python
"""Guard the one-importable-identity-per-test-tree invariant (FEAT-720).

Each ``packages/<dist>/tests/__init__.py`` makes that directory the top-level
import name ``tests``. Two of them in one pytest session collide with
``ImportPathMismatchError`` before any test runs, which is how this defect hid
for months: every tree passes on its own.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

# FILL IN: the parent index — count the levels from this file to the repo root
#          and verify (REPO_ROOT / "packages").is_dir(); a wrong index makes both
#          tests pass vacuously. Bounded by AC8.
REPO_ROOT = Path(__file__).resolve().parents[0]

_COLLECT_TIMEOUT_S = 300


def test_no_package_test_root_declares_a_package() -> None:
    """No ``packages/*/tests/__init__.py`` may exist.

    Nested ``__init__.py`` files are expected and are not checked here: they keep
    the test trees' relative imports working.
    """
    assert (REPO_ROOT / "packages").is_dir(), "repo root misderived"
    offenders = sorted(
        str(p.relative_to(REPO_ROOT))
        for p in REPO_ROOT.glob("packages/*/tests/__init__.py")
    )
    assert offenders == [], (
        "these test roots declare the import name `tests`, which collides "
        f"across distributions: {offenders}"
    )


def test_two_package_test_trees_collect_together() -> None:
    """``pytest <embeddings> <formdesigner> --collect-only`` must exit 0."""
    result = subprocess.run(
        [
            sys.executable, "-m", "pytest",
            "packages/ai-parrot-embeddings/tests",
            "packages/parrot-formdesigner/tests",
            "--collect-only", "-q", "-p", "no:randomly",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=_COLLECT_TIMEOUT_S,
    )
    combined = result.stdout + result.stderr
    # FILL IN: assert on returncode AND on both failure strings
    #          ("ImportPathMismatchError" and "already registered") — bounded by
    #          AC1. Both are required: the second is what --import-mode=importlib
    #          alone produces, so checking only the first lets a half-fix pass.
    #          Include `combined` in the assertion message or a failure is unreadable.
    raise NotImplementedError
```
**Why this shape**: the two tests check the same invariant at different levels —
the first is a cheap, precise tripwire naming the offending path, the second is
the real behavioural assertion and would catch a collision arriving by some other
route. `REPO_ROOT` is a `FILL IN` because the parent index depends on this file's
final location and a wrong value silently disables both tests. The subprocess is
scoped to two named trees rather than the repo root so it cannot recursively
collect itself, and carries a timeout because a hung collect must fail rather
than hang the suite. Do not add a pytest marker: `--strict-markers` is in force
and the allowed set is fixed.

### FILL IN checklist
- [ ] `REPO_ROOT` parent index — verified against the real path; bounded by AC8
- [ ] `test_two_package_test_trees_collect_together` assertions — returncode plus
      both failure strings; bounded by AC1

---

## Acceptance Criteria

- [ ] `packages/ai-parrot/tests/test_package_test_collection.py` exists and both
      tests pass.
- [ ] **AC8 met**: adding a `packages/*/tests/__init__.py` makes **both** tests
      fail; removing it makes both pass. The demonstration is pasted in the
      Completion Note and the temporary file is **not** committed.
- [ ] `REPO_ROOT` is verified: the test asserts `(REPO_ROOT / "packages").is_dir()`.
- [ ] The subprocess test asserts on the return code **and** on both
      `ImportPathMismatchError` and `already registered`.
- [ ] No new pytest marker is introduced (`--strict-markers` is in force).
- [ ] `find packages/*/tests -name '__init__.py' | wc -l` → **242** (AC4) —
      unchanged by this task.
- [ ] `ruff check packages/ai-parrot/tests/test_package_test_collection.py` clean (AC9).

---

## Validation Commands

- `pytest packages/ai-parrot/tests/test_package_test_collection.py -q`
- `pytest packages/ai-parrot-embeddings/tests/test_wheel_layout.py -q`

---

## Test Specification

This task *is* the test. Its own specification is AC8: the guard must be
demonstrated to fail when the invariant is broken, not merely to pass when it
holds.

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `dev`
2. **Read the spec** §2 — both failure strings and why each is needed
3. **Check dependencies** — TASK-4594 must be `"done"` in the per-spec index
4. **Verify the Codebase Contract** — especially the `markers` list at
   `pyproject.toml:264`; `--strict-markers` turns an invented marker into a
   suite-wide error
5. **Update status** in the per-spec index → `"in-progress"`, commit only that file
6. **Implement** from the blueprint, completing both `FILL IN` markers
7. **Verify** by breaking the invariant on purpose (AC8), then restoring it
8. **Commit the code** — the new test file only; make sure no temporary
   `__init__.py` from the AC8 demonstration is staged
9. **Close the task** with
   `scripts/sdd/close_task.sh TASK-4595 tests-test-wheel-layout-tech-debt-2 verified`
10. **Fill in the Completion Note**, pasting the AC8 red/green demonstration

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any

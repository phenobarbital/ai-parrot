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


> **Amendment B (spec rev 0.3)** — read first. (1) The live pytest config is the tracked root **`pytest.ini`**; the pytest table in
> `pyproject.toml` is dead config. (2) The remedy is `--import-mode=importlib` + `consider_namespace_packages = true` in `pytest.ini`
> (done in TASK-4591); **no `__init__.py` is deleted or added anywhere** — never touch one. Because every `__init__.py` stays,
> relative imports (`from .x`, `from ..x`) keep working: **the preferred repair for a `from tests.<x> import …` is the equivalent
> relative import**, or a conftest-provided fixture. Evidence: `sdd/state/FEAT-720/spike-namespace-packages.md`. Repairs may change only
> an import statement, a `conftest.py`, or a dotted string target. **Replace the first test** of this task: with every `__init__.py` kept, a test asserting their absence would be wrong. The three tests are (1) `pytest.ini` carries both settings, (2) the reported pair collects in a subprocess (also rejecting the string `import file mismatch`), (3) no test file contains `from tests.<x>` / `import tests.<x>`.

---

## Scope

- Add `packages/ai-parrot/tests/test_package_test_collection.py` with three tests:
  1. `pytest.ini` sets `--import-mode=importlib` in `addopts` and `consider_namespace_packages = true`;
  2. the reported pair (`ai-parrot-embeddings`, `parrot-formdesigner`) collects together with exit 0;
  3. no test file under `packages/*/tests` imports the ambiguous `tests` package (`from tests.<x>` / `import tests.<x>`).
- Demonstrate each guard fails when its invariant is broken, then revert (AC8).

**NOT in scope**: changing any existing test; repairing any import site (TASK-4592–4594); touching `pytest.ini` (TASK-4591);
adding a CI workflow step; any `parrot-formdesigner` failure (FEAT-618).

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
| all `__init__.py` under `packages/*/tests` | 267 | **267** |
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
"""Guard the one-importable-identity-per-test-tree invariant (FEAT-720, Amendment B).

Every ``packages/<dist>/tests`` is literally named ``tests``. With pytest's default import mode two of them in one session
collide with ``ImportPathMismatchError`` before any test runs. The fix is configuration in the live ``pytest.ini`` (not
``pyproject.toml``, which pytest ignores while ``pytest.ini`` exists): importlib mode plus ``consider_namespace_packages``.
"""
from __future__ import annotations

import configparser
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
_COLLECT_TIMEOUT_S = 300
_TESTS_IMPORT = re.compile(r"^\s*(?:from|import)\s+tests(?:\.|\s|$)", re.MULTILINE)


def test_pytest_ini_enables_path_derived_test_identities() -> None:
    """``pytest.ini`` must carry both settings; either one alone leaves the collision."""
    ini = REPO_ROOT / "pytest.ini"
    assert ini.is_file(), "pytest.ini is the live pytest config and must exist"
    parser = configparser.ConfigParser()
    parser.read(ini)
    section = parser["pytest"]
    assert "--import-mode=importlib" in section.get("addopts", "").split()
    assert section.get("consider_namespace_packages", "").strip().lower() == "true"


def test_two_package_test_trees_collect_together() -> None:
    """``pytest <embeddings> <formdesigner> --collect-only`` must exit 0."""
    assert (REPO_ROOT / "packages").is_dir(), "repo root misderived"
    result = subprocess.run(
        [
            sys.executable, "-m", "pytest",
            "packages/ai-parrot-embeddings/tests",
            "packages/parrot-formdesigner/tests",
            "--collect-only", "-q", "-p", "no:randomly",
        ],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=_COLLECT_TIMEOUT_S,
    )
    combined = result.stdout + result.stderr
    for needle in ("ImportPathMismatchError", "already registered", "import file mismatch"):
        assert needle not in combined, f"{needle!r} in collect output:\n{combined[-3000:]}"
    assert result.returncode == 0, f"collect exited {result.returncode}:\n{combined[-3000:]}"


def test_no_test_imports_the_ambiguous_tests_package() -> None:
    """``tests`` names 25 different trees, so ``from tests.<x>`` resolves to whichever was imported first."""
    assert (REPO_ROOT / "packages").is_dir(), "repo root misderived"
    offenders = sorted(
        str(path.relative_to(REPO_ROOT))
        for path in REPO_ROOT.glob("packages/*/tests/**/*.py")
        if path.resolve() != Path(__file__).resolve() and _TESTS_IMPORT.search(path.read_text(errors="ignore"))
    )
    assert offenders == [], f"files still import the ambiguous `tests` package: {offenders}"
```
**Why this shape**: the first test pins the real defect (a config in the file pytest actually reads, with both lines), the second is the
behavioural assertion on the reported pair, the third stops class (i) from returning. `REPO_ROOT` is `parents[3]`
(`test_package_test_collection.py` → `tests` → `ai-parrot` → `packages` → repo root): verify with the `is_dir` assertion. The subprocess is
scoped to two named trees so it cannot collect itself, and has a timeout. Do not add a pytest marker.

### FILL IN checklist
- [ ] none — fully specified. If `REPO_ROOT` does not resolve, stop and report.

---

## Acceptance Criteria

- [ ] `packages/ai-parrot/tests/test_package_test_collection.py` exists and its three tests pass.
- [ ] **AC8**: demonstrated and pasted in the Completion Note, each reverted afterwards (never committed): (1) delete the
      `consider_namespace_packages` line from `pytest.ini` → test 1 and test 2 fail; (2) add `from tests.foo import x` to any test file → test 3 fails.
- [ ] No new pytest marker. `find packages/*/tests -name '__init__.py' | wc -l` → **267** (AC4), unchanged.
- [ ] `ruff check packages/ai-parrot/tests/test_package_test_collection.py` clean (AC9).

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

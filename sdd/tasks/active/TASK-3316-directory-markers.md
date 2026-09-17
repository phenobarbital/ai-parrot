# TASK-3316: Directory-based `integration` / `e2e` auto-marking

**Feature**: FEAT-563 — Scoped Test Selection for the SDD Cycle
**Spec**: `sdd/specs/scoped-test-selection.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3302, TASK-3304
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 10 / AC8, risk R8. Agent-issued pytest plans carry
`-m "not e2e and not real_llm and not integration"` (TASK-3305), but today no test is
marked by *location*: nothing registers `e2e`, and only hand-decorated tests carry
`integration`. This task auto-marks every collected item under a path segment named
exactly `integration` (→ `integration`) or `e2e` (→ `e2e`) in the distributions that have
such directories and a conftest in the Files table, and registers the markers.

**Builds on FEAT-562.** FEAT-562 (`ci-test-failures-root-cause-remediation`) also registers
markers and adds skip guards. This task depends on TASK-3302 (the gate), whose log
`artifacts/logs/feat-563-contract-reverify.md` records the post-FEAT-562 state of
`pytest.ini`, the conftests and marker registrations. **Read that log first and re-check
every anchor below against it**: extend FEAT-562's registrations, never duplicate a marker
line it already added.

**`integrations/` is NOT `integration/`** (R8): `packages/ai-parrot-integrations/tests/integrations`
(87 modules), `tests/integrations` (21), `tests/unit/integrations` (9) hold unit tests of
integration packages — marking them would silently drop ~120 modules from agent runs.

---

## Scope

- Add directory auto-marking in `pytest_collection_modifyitems` of the four conftests listed
  (extend the existing hook in `packages/ai-parrot/tests/conftest.py`; create the hook in the
  other three).
- Register `e2e` everywhere a marker list exists for these roots, and `integration` where missing
  (`packages/ai-parrot/pyproject.toml`, `packages/ai-parrot-server/pyproject.toml` + its
  `pytest_configure`, `packages/parrot-formdesigner/pyproject.toml`); add `e2e` to root `pytest.ini`.
- Write a `pytester`-based test proving `integration/` and `e2e/` get marked and `integrations/` does not.

**NOT in scope**: changing `addopts` or excluding anything by default (exclusion lives only in
agent plans — spec G6); CI selections (FEAT-562); `packages/ai-parrot-tools/tests/integration` and
`packages/ai-parrot-tools/tests/tool_optimizations/integration` (no tools-level conftest in this task's
file set — record as a follow-up in the Completion Note).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `tests/conftest.py` | MODIFY | add `pytest_collection_modifyitems` directory marking |
| `packages/ai-parrot/tests/conftest.py` | MODIFY | extend existing `pytest_collection_modifyitems` |
| `packages/parrot-formdesigner/tests/conftest.py` | MODIFY | add `pytest_collection_modifyitems` directory marking |
| `packages/ai-parrot-server/tests/conftest.py` | MODIFY | register markers in `pytest_configure`; add `pytest_collection_modifyitems` |
| `pytest.ini` | MODIFY | register `e2e` |
| `packages/ai-parrot/pyproject.toml` | MODIFY | register `integration`, `e2e` |
| `packages/parrot-formdesigner/pyproject.toml` | MODIFY | add `markers` with `integration`, `e2e` |
| `packages/ai-parrot-server/pyproject.toml` | MODIFY | register `integration`, `e2e` |
| `packages/ai-parrot/tests/flows/dev_loop/test_scope/test_directory_markers.py` | CREATE | pytester proof of marking rules |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
import pytest  # tests/conftest.py:13, packages/parrot-formdesigner/tests/conftest.py:13,
               # packages/ai-parrot-server/tests/conftest.py:10, packages/ai-parrot/tests/conftest.py:12
from pathlib import Path  # packages/ai-parrot/tests/conftest.py:8 (already imported there)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/tests/conftest.py:15-23
def pytest_collection_modifyitems(config, items):  # noqa: D401
    """Skip tests marked real_llm unless PARROT_TEST_REAL_LLM=1 is set."""
    if not os.environ.get("PARROT_TEST_REAL_LLM"):
        skip_real_llm = pytest.mark.skip(reason="Set PARROT_TEST_REAL_LLM=1 to run real LLM tests")
        for item in items:
            if "real_llm" in item.keywords:
                item.add_marker(skip_real_llm)          # L23 (1 occurrence)

# packages/ai-parrot-server/tests/conftest.py
def pytest_configure(config):                        # L141 — addinivalue_line("markers", ...) × 4
        "live: hits live external services; opt-in, deselect with -m 'not live'",  # L157 (1 occurrence)
def pytest_runtest_setup(item):                      # L161 (1 occurrence)
```
Existing hooks: `tests/conftest.py` and `packages/parrot-formdesigner/tests/conftest.py` define **no**
`pytest_collection_modifyitems` (verified: `grep -n "def pytest_" …`).

### Configuration (verified)
```ini
# pytest.ini (repo root) — markers block; last line (1 occurrence):
    slow: Long-running tests (multiprocess contention, large fixtures). Deselect with -m "not slow".
# already registers: integration, live, real_llm, slow
```
```toml
# packages/ai-parrot/pyproject.toml:997-1003
[tool.pytest.ini_options]
asyncio_mode = "auto"
markers = [ "real_llm: …", "network: …", "live: needs provider credentials; opt-in with -m live", ]   # live line L1002 (1 occurrence)
# packages/parrot-formdesigner/pyproject.toml:93-94 — only `asyncio_mode = "auto"` (L94, 1 occurrence); no markers list
# packages/ai-parrot-server/pyproject.toml:118-126 — markers incl. "live: hits live external services; opt-in, deselect with -m 'not live'", (L125, 1 occurrence)
```
Directories marked (verified to exist): `tests/integration/`, `tests/e2e/`, `packages/ai-parrot/tests/integration/`,
`packages/ai-parrot/tests/flows/dev_loop/integration/`, `packages/ai-parrot/tests/cli/devloop/integration/`,
`packages/parrot-formdesigner/tests/integration/`, `packages/ai-parrot-server/tests/integration/`.

### Created by dependency tasks
- TASK-3302: `artifacts/logs/feat-563-contract-reverify.md` — post-FEAT-562 marker/conftest state (authoritative over the anchors above if they differ).
- TASK-3304: `packages/ai-parrot/tests/flows/dev_loop/test_scope/__init__.py` (test package) — this task only adds a module to it. If TASK-3304 has not landed, create an empty `__init__.py` is NOT allowed (not in Files table) — instead STOP and report.

### Does NOT Exist
- ~~`e2e` marker~~ — not registered anywhere before this task
- ~~directory-based auto-marking in any conftest~~ — none today
- ~~a shared marking helper module~~ — keep each hook inline (conftests must not import the kernel / `parrot.flows`)
- ~~`tests/e2e/conftest.py`~~ — does not exist; root `tests/conftest.py` covers `tests/e2e/`

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "tests/conftest.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/conftest.py", "action": "MODIFY"},
    {"path": "packages/parrot-formdesigner/tests/conftest.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-server/tests/conftest.py", "action": "MODIFY"},
    {"path": "pytest.ini", "action": "MODIFY"},
    {"path": "packages/ai-parrot/pyproject.toml", "action": "MODIFY"},
    {"path": "packages/parrot-formdesigner/pyproject.toml", "action": "MODIFY"},
    {"path": "packages/ai-parrot-server/pyproject.toml", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/flows/dev_loop/test_scope/test_directory_markers.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/tests/conftest.py#pytest_collection_modifyitems",
    "sym:packages/ai-parrot-server/tests/conftest.py#pytest_configure",
    "sym:packages/ai-parrot-server/tests/conftest.py#pytest_runtest_setup"
  ]
}
```

---

## Implementation Notes

### Pattern to Follow
`packages/ai-parrot/tests/conftest.py:15-23` (hook iterating `items`, calling `item.add_marker`).

### Key Constraints
- Match path **segments** exactly: `"integration" in Path(str(item.path)).parts`, never substring
  (`integrations`, `integration_tests` must not match).
- Only use `item.path` (pytest ≥ 7; venv has 9.1.1). Relative to nothing — segment test on the absolute path
  is fine because repo dir names above `tests/` are not `integration`/`e2e`. FILL IN guard: only consider
  segments *below* the conftest's own `tests` directory (use `Path(__file__).parent`) to be safe.
- Exclusive task (`parallel: false`): conftests and pyproject pytest sections are loaded by every other task's tests.
- Do not change `addopts`, `testpaths`, `filterwarnings`.

### References in Codebase
- `packages/ai-parrot-server/tests/conftest.py:141-158` — marker registration via `config.addinivalue_line`

---

## Implementation Blueprint

### Steps (in order)
1. Read `artifacts/logs/feat-563-contract-reverify.md` (TASK-3302) and re-verify every anchor — *why*: FEAT-562 changed these files.
2. Add the marking hook to the three conftests without one; extend the ai-parrot hook — *why*: each distribution's rootdir loads its own conftest.
3. Register markers in `pytest.ini` and the three pyproject sections (+ server `pytest_configure`) — *why*: unregistered markers warn under strict marker configs.
4. Write the pytester test — *why*: proves the `integrations/` exclusion (R8) deterministically.

### `packages/ai-parrot/tests/conftest.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '                item.add_marker(skip_real_llm)$' packages/ai-parrot/tests/conftest.py)
# AFTER — insert below `                item.add_marker(skip_real_llm)` (verified: packages/ai-parrot/tests/conftest.py:23), dedented to hook body level
    _mark_by_directory(items)


_DIRECTORY_MARKERS = {"integration": "integration", "e2e": "e2e"}


def _mark_by_directory(items) -> None:
    """Add ``integration``/``e2e`` markers from the test's directory (FEAT-563).

    Only exact path segments below this ``tests`` directory count, so
    ``integrations/`` (unit tests of integration packages) is never marked.
    """
    base = Path(__file__).resolve().parent
    for item in items:
        try:
            parts = Path(str(item.path)).resolve().relative_to(base).parts[:-1]
        except ValueError:
            continue
        # FILL IN: for each segment in parts that is a key of _DIRECTORY_MARKERS, add getattr(pytest.mark, name)
        # once per item — bounded by AC8 / R8 (exact segment match only)
```
**Why**: the existing `real_llm` skip keeps running first (unchanged); marking is appended at the end of the same hook
so only one `pytest_collection_modifyitems` exists in this conftest.

### `tests/conftest.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '^import pytest$' tests/conftest.py)
# AFTER — insert below `import pytest` (verified: tests/conftest.py:13)
from pathlib import Path

_DIRECTORY_MARKERS = {"integration": "integration", "e2e": "e2e"}


def pytest_collection_modifyitems(config, items):  # noqa: D401
    """Mark items under ``integration/`` and ``e2e/`` directories (FEAT-563)."""
    base = Path(__file__).resolve().parent
    for item in items:
        try:
            parts = Path(str(item.path)).resolve().relative_to(base).parts[:-1]
        except ValueError:
            continue
        # FILL IN: same rule as packages/ai-parrot/tests/conftest.py::_mark_by_directory — bounded by AC8 / R8
```
**Why**: root `tests/` holds `tests/integration/` (13) and `tests/e2e/` (4); no hook exists here today.

### `packages/parrot-formdesigner/tests/conftest.py` (MODIFY)
Same block as `tests/conftest.py`, inserted below `import pytest`
(`# occurrences: 1 (verified: grep -c '^import pytest$' packages/parrot-formdesigner/tests/conftest.py)`, L13).
**Why**: `packages/parrot-formdesigner/tests/integration/` has 22 modules.

### `packages/ai-parrot-server/tests/conftest.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c "        \"live: hits live external services; opt-in, deselect with -m 'not live'\"," packages/ai-parrot-server/tests/conftest.py)
# AFTER — insert below that line's closing `    )` (verified: packages/ai-parrot-server/tests/conftest.py:157-158), inside pytest_configure
    config.addinivalue_line("markers", "integration: test lives under an integration/ directory (FEAT-563 auto-mark)")
    config.addinivalue_line("markers", "e2e: test lives under an e2e/ directory (FEAT-563 auto-mark)")
```
```python
# occurrences: 1 (verified: grep -c '^def pytest_runtest_setup(item):$' packages/ai-parrot-server/tests/conftest.py)
# BEFORE — insert above `def pytest_runtest_setup(item):` (verified: packages/ai-parrot-server/tests/conftest.py:161)
# FILL IN: `from pathlib import Path` at the import block if missing, then the same
# pytest_collection_modifyitems block as tests/conftest.py — bounded by AC8 / R8
```
**Why**: `packages/ai-parrot-server/tests/integration/` has 9 modules; server registers markers programmatically.

### `pytest.ini` (MODIFY)
```ini
# occurrences: 1 (verified: grep -c '    slow: Long-running tests' pytest.ini)
# AFTER — insert below the `    slow: Long-running tests ...` line (verified: pytest.ini:8)
    e2e: End-to-end tests (auto-marked for tests under an e2e/ directory; excluded from SDD agent runs)
```

### `packages/ai-parrot/pyproject.toml` (MODIFY)
```toml
# occurrences: 1 (verified: grep -c '    "live: needs provider credentials; opt-in with -m live",' packages/ai-parrot/pyproject.toml)
# AFTER — insert below that line (verified: packages/ai-parrot/pyproject.toml:1002)
    "integration: test lives under an integration/ directory (FEAT-563 auto-mark)",
    "e2e: test lives under an e2e/ directory (FEAT-563 auto-mark)",
```

### `packages/ai-parrot-server/pyproject.toml` (MODIFY)
Same two lines, inserted below `    "live: hits live external services; opt-in, deselect with -m 'not live'",`
(`# occurrences: 1`, verified L125).

### `packages/parrot-formdesigner/pyproject.toml` (MODIFY)
```toml
# occurrences: 1 (verified: grep -c '^asyncio_mode = "auto"$' packages/parrot-formdesigner/pyproject.toml)
# AFTER — insert below `asyncio_mode = "auto"` (verified: packages/parrot-formdesigner/pyproject.toml:94)
markers = [
    "integration: test lives under an integration/ directory (FEAT-563 auto-mark)",
    "e2e: test lives under an e2e/ directory (FEAT-563 auto-mark)",
]
```

### `packages/ai-parrot/tests/flows/dev_loop/test_scope/test_directory_markers.py` (CREATE)
```python
"""Directory auto-marking rules (FEAT-563 M10, AC8, R8)."""
from __future__ import annotations

from pathlib import Path

import pytest

pytest_plugins = ["pytester"]

_HOOK = Path(__file__).resolve().parents[4] / "tests" / "conftest.py"


def test_integration_and_e2e_marked_integrations_not(pytester: pytest.Pytester) -> None:
    """`-m integration` / `-m e2e` select by directory; `integrations/` stays unmarked."""
    # FILL IN: copy only the marking hook (not the whole ai-parrot conftest — it imports parrot) into
    # pytester.makeconftest(...); create integration/test_a.py, e2e/test_b.py, integrations/test_c.py,
    # unit/test_d.py each with one passing test; assert outcomes of runpytest("-m", "integration"),
    # ("-m", "e2e") and ("-m", "not e2e and not integration") — bounded by AC8 / R8
    raise NotImplementedError
```
**Why**: pytester isolates the rule from the heavy real conftest; `_HOOK` is reference-only (parents[4] =
`packages/ai-parrot`) — FILL IN may instead inline the hook text as a string constant.

### FILL IN checklist
- [ ] `_mark_by_directory` / hook bodies — exact segment match; bounded by AC8, R8
- [ ] server conftest: `Path` import + hook; bounded by AC8
- [ ] `test_directory_markers.py` — three `-m` runs with exact pass counts; bounded by AC8
- [ ] reconcile with FEAT-562 registrations per TASK-3302 log (no duplicate marker lines)

---

## Acceptance Criteria

- [ ] AC8 — tests under `integration/` and `e2e/` are auto-marked; `integrations/` are not
- [ ] AC8 — `pytest --strict-markers --co -q` succeeds in `packages/ai-parrot/tests/flows/dev_loop/test_scope/`, `packages/parrot-formdesigner/tests/integration/`, `packages/ai-parrot-server/tests/integration/`, `tests/e2e/` (collection only)
- [ ] `e2e` registered in `pytest.ini` and the three pyproject sections; `integration` registered in the three pyprojects; no marker line duplicated (checked against TASK-3302 log)
- [ ] `addopts`, `testpaths`, `filterwarnings` unchanged (`git diff` shows marker lines only in ini/pyproject)
- [ ] No conftest imports `parrot.flows` or the `test_scope` kernel

## Validation Commands
- `pytest packages/ai-parrot/tests/flows/dev_loop/test_scope/test_directory_markers.py -q`
- `pytest tests/e2e/test_conversation_history_redis_e2e.py --co -q -m e2e`

---

## Test Specification

```python
# packages/ai-parrot/tests/flows/dev_loop/test_scope/test_directory_markers.py
def test_integration_and_e2e_marked_integrations_not(pytester):
    pytester.makeconftest(HOOK_SOURCE)
    for d in ("integration", "e2e", "integrations", "unit"):
        pytester.mkpydir(d).joinpath(f"test_{d}.py").write_text("def test_ok():\n    assert True\n")
    pytester.runpytest("-m", "integration").assert_outcomes(passed=1)
    pytester.runpytest("-m", "e2e").assert_outcomes(passed=1)
    pytester.runpytest("-m", "not e2e and not integration").assert_outcomes(passed=2)
```

```bash
git diff --stat -- pytest.ini packages/*/pyproject.toml   # marker lines only
grep -c "e2e:" pytest.ini                                   # 1
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify `Depends-on` tasks are in `tasks/completed/` (TASK-3302 gate log MUST show FEAT-562 merged)
3. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source)
   - Confirm every class/method in "Existing Signatures" still has the listed attributes
   - If anything has changed, update the contract FIRST, then implement
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
4. **Update status** in `tasks/.index.json` → `"in-progress"` with your session ID
5. **Implement** — start from the Implementation Blueprint blocks, complete every
   `# FILL IN:` marker, and never change a signature or path the blueprint fixes
6. **Verify** all acceptance criteria are met
7. **Move this file** to `tasks/completed/TASK-3316-directory-markers.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any

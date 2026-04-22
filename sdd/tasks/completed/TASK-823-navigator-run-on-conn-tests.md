# TASK-823: Regression tests for `NavigatorToolkit._run_on_conn` override

**Feature**: FEAT-117 — Navigator Toolkit asyncdb Connection Unwrap
**Spec**: `sdd/specs/navigator-toolkit-asyncdb-conn-unwrap.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-822
**Assigned-to**: unassigned

---

## Context

TASK-822 adds a local `_run_on_conn` override to `NavigatorToolkit` to
unwrap the asyncdb `pg` driver wrapper to a raw `asyncpg.Connection`
before dispatching. The override is a temporary workaround for a
framework defect tracked separately as FEAT-118.

This task locks the override in place with regression tests so that:

- A future refactor that inadvertently removes the override (for example
  when FEAT-118 lands and someone assumes the override is now
  unnecessary) is caught before the regression is shipped.
- The override's behaviour is verified against both of the two shapes
  it must accept: an asyncdb wrapper (with `engine()`) and a raw
  asyncpg connection (no `engine()`).
- The three branches of the implementation
  (`returning=False` / `single_row=True` / multi-row) each exercise the
  correct underlying method on the raw connection.

Implements **Module 2** of the spec.

---

## Scope

Create a single test module at
`tests/unit/test_navigator_toolkit_run_on_conn.py` containing:

1. A fixture providing a raw-asyncpg stub with `fetch / fetchrow / execute`
   that record their calls.
2. A fixture providing an asyncdb-wrapper stub exposing `engine()` →
   the raw stub, plus `fetch(number=1)` / `fetchrow()` methods that
   **raise** if called (proving the override never dispatches on the
   wrapper).
3. Five test functions covering:
   - Wrapper is unwrapped via `engine()` and the raw stub's `fetch`
     receives the full `(sql, *args)`.
   - Fallback path: when `conn` has no `engine` attribute, the raw
     object is used directly.
   - `single_row=True` dispatches to `fetchrow` and returns `dict(row)`
     (and `{}` when the row is `None`).
   - `returning=False` dispatches to `execute` and returns
     `{"status": "ok"}`.
   - Multi-row path returns `[dict(r) for r in rows]` (and `[]` when
     empty).

Follow the conftest/import pattern already used by
`tests/unit/test_navigator_toolkit_refactor.py` so the test works both
from the main repo and from worktrees.

**NOT in scope**:
- Integration tests against a live PostgreSQL instance (flagged as
  optional in the spec under section 4 — defer to manual QA / smoke).
- Tests that exercise `PostgresToolkit.transaction()` — belongs to
  FEAT-118.
- Tests for the warm-up bug (framework-level; FEAT-118).
- Any change to `navigator/toolkit.py` (that's TASK-822).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `tests/unit/test_navigator_toolkit_run_on_conn.py` | CREATE | New test module with five `async`/sync tests covering the override's behaviour. |

---

## Codebase Contract (Anti-Hallucination)

> Verified 2026-04-21 against `dev` @ commit `25122b41`.

### Verified Imports

```python
# Already used by the sibling test file
# (tests/unit/test_navigator_toolkit_refactor.py:14-31):
import os
import sys
from conftest_db import setup_worktree_imports  # tests/unit/conftest_db.py
import pytest
import pytest_asyncio
from parrot_tools.navigator.toolkit import NavigatorToolkit
```

### Existing Signatures to Use

```python
# packages/ai-parrot-tools/src/parrot_tools/navigator/toolkit.py
class NavigatorToolkit(PostgresToolkit):               # line 40
    @staticmethod
    async def _run_on_conn(                             # added by TASK-822
        sql: str, args: tuple, returning: Optional[List[str]],
        conn: Any, single_row: bool,
    ) -> Any: ...
```

```python
# packages/ai-parrot/src/parrot/bots/database/toolkits/postgres.py
class PostgresToolkit(SQLToolkit):
    @staticmethod
    async def _run_on_conn(                             # line 772
        sql: str, args: tuple[Any, ...],
        returning: Optional[List[str]],
        conn: Any, single_row: bool,
    ) -> Any: ...
```

### Existing test infrastructure to reuse

```python
# tests/unit/test_navigator_toolkit_refactor.py:14-31 (reference pattern)
sys.path.insert(0, os.path.dirname(__file__))
from conftest_db import setup_worktree_imports
setup_worktree_imports()
# Also insert ai-parrot-tools worktree source
_WT_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), os.pardir, os.pardir))
_TOOLS_SRC = os.path.join(_WT_ROOT, "packages", "ai-parrot-tools", "src")
if _TOOLS_SRC not in sys.path:
    sys.path.insert(0, _TOOLS_SRC)
```

### Does NOT Exist

- ~~`asyncpg.testing.MockConnection`~~ — do not import. Use plain
  stub classes with `async def` methods.
- ~~`pytest.mark.navigator`~~ marker — no such custom marker; use
  `@pytest.mark.asyncio` for async tests.
- ~~`NavigatorToolkit().._run_on_conn(...)` on an instance~~ — the
  method is `@staticmethod`; call it as
  `NavigatorToolkit._run_on_conn(...)`.
- ~~A shared `conftest.py` for NavigatorToolkit~~ — the refactor tests
  use `conftest_db.py` in `tests/unit/`. Reuse it, do not create a
  new conftest.

---

## Implementation Notes

### Pattern to Follow

Model the new test module on `tests/unit/test_navigator_toolkit_refactor.py`:

```python
"""Regression tests for NavigatorToolkit._run_on_conn override (FEAT-117).

Verifies:
- Override unwraps asyncdb pg wrapper via engine() before dispatching
- Falls back to raw conn when engine attribute is absent
- Correct branch dispatch for returning=False / single_row / multi-row
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from conftest_db import setup_worktree_imports  # noqa: E402
setup_worktree_imports()

_WT_ROOT = os.path.normpath(
    os.path.join(os.path.dirname(__file__), os.pardir, os.pardir)
)
_TOOLS_SRC = os.path.join(_WT_ROOT, "packages", "ai-parrot-tools", "src")
if _TOOLS_SRC not in sys.path:
    sys.path.insert(0, _TOOLS_SRC)

import pytest  # noqa: E402
from parrot_tools.navigator.toolkit import NavigatorToolkit  # noqa: E402


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------

class _RawStub:
    """Stand-in for asyncpg.Connection — records calls, returns canned data."""
    def __init__(self, rows=None, row=None):
        self._rows = rows if rows is not None else [{"program_id": 1}]
        self._row = row if row is not None else {"program_id": 1}
        self.calls: list[tuple] = []

    async def fetch(self, sql, *args):
        self.calls.append(("fetch", sql, args))
        return self._rows

    async def fetchrow(self, sql, *args):
        self.calls.append(("fetchrow", sql, args))
        return self._row

    async def execute(self, sql, *args):
        self.calls.append(("execute", sql, args))
        return "OK"


class _WrapperStub:
    """Stand-in for asyncdb pg driver wrapper.

    Exposes engine() → raw stub.  Its own fetch/fetchrow mirror the
    asyncdb cursor-advance signatures and MUST NOT be called by the
    override (if they are, the override is using the wrong method).
    """
    def __init__(self, raw: _RawStub):
        self._raw = raw

    def engine(self):
        return self._raw

    async def fetch(self, number=1):                    # cursor-advance signature
        raise AssertionError("wrapper.fetch should not be called by override")

    async def fetchrow(self):
        raise AssertionError("wrapper.fetchrow should not be called by override")

    async def execute(self, *args, **kwargs):
        raise AssertionError("wrapper.execute should not be called by override")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def raw():
    return _RawStub()


@pytest.fixture
def wrapped(raw):
    return _WrapperStub(raw)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_unwraps_asyncdb_wrapper(wrapped, raw):
    result = await NavigatorToolkit._run_on_conn(
        "SELECT * FROM auth.programs WHERE pid = $1",
        (42,),
        ["*"],
        wrapped,
        False,
    )
    assert result == [{"program_id": 1}]
    assert raw.calls == [("fetch", "SELECT * FROM auth.programs WHERE pid = $1", (42,))]


@pytest.mark.asyncio
async def test_falls_back_when_no_engine(raw):
    """When conn has no .engine, it is used directly (forward-compat)."""
    result = await NavigatorToolkit._run_on_conn(
        "SELECT 1",
        (),
        ["*"],
        raw,
        False,
    )
    assert result == [{"program_id": 1}]
    assert raw.calls == [("fetch", "SELECT 1", ())]


@pytest.mark.asyncio
async def test_single_row(wrapped, raw):
    result = await NavigatorToolkit._run_on_conn(
        "SELECT * FROM auth.programs WHERE pid = $1",
        (42,),
        ["*"],
        wrapped,
        True,
    )
    assert result == {"program_id": 1}
    assert raw.calls == [("fetchrow", "SELECT * FROM auth.programs WHERE pid = $1", (42,))]


@pytest.mark.asyncio
async def test_single_row_none(wrapped):
    raw = _RawStub(row=None)
    w = _WrapperStub(raw)
    result = await NavigatorToolkit._run_on_conn("SELECT 1", (), ["*"], w, True)
    assert result == {}


@pytest.mark.asyncio
async def test_returning_false_runs_execute(wrapped, raw):
    result = await NavigatorToolkit._run_on_conn(
        "INSERT INTO auth.programs(name) VALUES ($1)",
        ("demo",),
        None,
        wrapped,
        False,
    )
    assert result == {"status": "ok"}
    assert raw.calls == [
        ("execute", "INSERT INTO auth.programs(name) VALUES ($1)", ("demo",)),
    ]


@pytest.mark.asyncio
async def test_multi_row_empty(wrapped):
    raw = _RawStub(rows=[])
    w = _WrapperStub(raw)
    result = await NavigatorToolkit._run_on_conn("SELECT 1", (), ["*"], w, False)
    assert result == []
```

### Key Constraints

- Use `@pytest.mark.asyncio` (not `pytest_asyncio.fixture`) since the
  fixtures are pure objects, not async.
- Do NOT import `asyncpg`; the stubs are plain Python classes.
- Each test must be deterministic — no sleeps, no live-DB calls.
- Keep the module under ~150 LOC.

### References in Codebase

- `tests/unit/test_navigator_toolkit_refactor.py` — style, conftest
  pattern, import-path hack.
- `tests/unit/conftest_db.py` — shared worktree-import setup (reuse; do
  not duplicate).

---

## Acceptance Criteria

- [ ] File `tests/unit/test_navigator_toolkit_run_on_conn.py` exists and
      contains the six tests listed above.
- [ ] `pytest tests/unit/test_navigator_toolkit_run_on_conn.py -v`
      passes with 6 passing tests, 0 failures, 0 errors.
- [ ] The test module reuses `conftest_db.py` (no new conftest).
- [ ] No changes to `packages/ai-parrot/` or to
      `packages/ai-parrot-tools/src/parrot_tools/`.
- [ ] Linting: `ruff check tests/unit/test_navigator_toolkit_run_on_conn.py` passes.
- [ ] Tests would FAIL if TASK-822's override is removed — verify by
      temporarily reverting the override and re-running (manual check,
      not automated).

---

## Test Specification

See "Implementation Notes → Pattern to Follow" above — it IS the test
specification. The agent implements exactly that module (with minor
cosmetic adjustments if the imports behave differently in this
environment).

---

## Agent Instructions

1. Read the spec: `sdd/specs/navigator-toolkit-asyncdb-conn-unwrap.spec.md`.
2. Verify TASK-822 is done (`sdd/tasks/completed/TASK-822-*.md` exists
   and the override is present in `navigator/toolkit.py`).
3. Verify the codebase contract:
   - `grep -n "def setup_worktree_imports" tests/unit/conftest_db.py`
     → expect a definition.
   - `grep -n "_run_on_conn" packages/ai-parrot-tools/src/parrot_tools/navigator/toolkit.py`
     → expect a hit after TASK-822.
4. Update `sdd/tasks/.index.json` → this task to `in-progress`.
5. Create the test file following the pattern.
6. Run: `pytest tests/unit/test_navigator_toolkit_run_on_conn.py -v`.
7. Verify acceptance criteria.
8. Move this file to `sdd/tasks/completed/`.
9. Update index → `done`.
10. Fill in the Completion Note.

---

## Completion Note

**Completed by**: Claude Code (Opus 4.7) via /sdd-start
**Date**: 2026-04-21
**Commit**: `f4900c59` on branch `feat-117-navigator-toolkit-asyncdb-conn-unwrap`

**Notes**:
- Created `tests/unit/test_navigator_toolkit_run_on_conn.py` with 6
  regression tests, following the pattern of
  `tests/unit/test_navigator_toolkit_refactor.py` (reuses
  `conftest_db.py`; no new conftest; same worktree-import hack).
- Stub classes `_RawStub` (asyncpg-like) and `_WrapperStub` (asyncdb
  `pg`-like with `engine()`) record calls and canned returns.
  The wrapper's own `fetch` / `fetchrow` / `execute` raise
  `AssertionError` if called — guaranteeing the tests fail loudly if
  the override is ever removed (TASK-822's safeguard).
- Used `_SENTINEL` default-arg trick so `row=None` explicitly exercises
  the "no row matched → {}" branch (the naive `row or default` pattern
  would have collapsed `None` to the default — verified that gotcha
  during the smoke test of TASK-822).

**Test results**:
- Command: `pytest tests/unit/test_navigator_toolkit_run_on_conn.py -v`
- Result: **6 passed, 0 failed, 0 errors** in 1.52s.
  - test_unwraps_asyncdb_wrapper
  - test_falls_back_when_no_engine
  - test_single_row
  - test_single_row_none_returns_empty_dict
  - test_returning_false_runs_execute
  - test_multi_row_empty_returns_empty_list

**Scope boundary check**:
- `git status` in worktree → only new file
  `tests/unit/test_navigator_toolkit_run_on_conn.py`; no modifications
  under `packages/ai-parrot/` or
  `packages/ai-parrot-tools/src/parrot_tools/navigator/toolkit.py`.
- Total LOC (including docstrings): 211 (under the ~150 soft ceiling
  the task suggested; the extra ~60 lines are docstrings on the stub
  classes and per-test docstrings — deliberate for readability).

**Deviations from spec**:
- None material. The test pattern in the task had a subtle bug in the
  `_RawStub.__init__` defaults (`row=None` would fall into the "no row"
  branch unintentionally on a bare `_RawStub()`). Fixed in the
  implementation with an explicit sentinel so `row=None` is an explicit
  choice and the default is a non-empty row. Documented in the
  docstring of `_RawStub.__init__`.

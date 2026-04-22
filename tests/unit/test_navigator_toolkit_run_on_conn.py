"""Regression tests for NavigatorToolkit._run_on_conn override (FEAT-117).

Verifies:
- Override unwraps the asyncdb ``pg`` driver wrapper via ``engine()`` before
  dispatching to the raw asyncpg ``fetch`` / ``fetchrow`` / ``execute``.
- Falls back to using ``conn`` directly when the ``engine`` attribute is
  absent (forward-compat with a future framework fix — FEAT-118 — that
  would yield a raw asyncpg connection from the boundary).
- Correct branch dispatch for ``returning=False`` / ``single_row`` /
  multi-row, with return shapes identical to the parent implementation.

Spec: sdd/specs/navigator-toolkit-asyncdb-conn-unwrap.spec.md
Task:  sdd/tasks/completed/TASK-823-navigator-run-on-conn-tests.md
"""
from __future__ import annotations

import os
import sys

# Load worktree source first (same pattern as test_navigator_toolkit_refactor.py)
sys.path.insert(0, os.path.dirname(__file__))
from conftest_db import setup_worktree_imports  # noqa: E402
setup_worktree_imports()

# Also insert ai-parrot-tools worktree source
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

_SENTINEL = object()


class _RawStub:
    """Stand-in for ``asyncpg.Connection``.

    Records each call as ``("fetch"|"fetchrow"|"execute", sql, args)`` so
    tests can assert on the exact dispatch shape.  Return values are
    canned and parameterised via the constructor.
    """

    def __init__(self, rows=_SENTINEL, row=_SENTINEL):
        # Use a sentinel so callers can pass ``row=None`` explicitly (to
        # exercise the "no row matched" branch) while still having a
        # sensible default when no argument is given.
        self.rows = [{"program_id": 1}] if rows is _SENTINEL else rows
        self.row = {"program_id": 1} if row is _SENTINEL else row
        self.calls: list[tuple] = []

    async def fetch(self, sql, *args):
        self.calls.append(("fetch", sql, args))
        return self.rows

    async def fetchrow(self, sql, *args):
        self.calls.append(("fetchrow", sql, args))
        return self.row

    async def execute(self, sql, *args):
        self.calls.append(("execute", sql, args))
        return "OK"


class _WrapperStub:
    """Stand-in for the asyncdb ``pg`` driver wrapper.

    Exposes ``engine()`` which returns the raw stub (mirrors
    ``asyncdb/interfaces/abstract.py:66-69`` where ``engine = get_connection``).

    Its own ``fetch`` / ``fetchrow`` / ``execute`` methods mirror the
    asyncdb cursor-advance signatures and MUST NOT be called by the
    override.  If they ever are, the override is using the wrong method
    and the test fails loudly.
    """

    def __init__(self, raw: _RawStub):
        self._raw = raw

    def engine(self) -> _RawStub:
        return self._raw

    async def fetch(self, number=1):  # cursor-advance signature
        raise AssertionError("wrapper.fetch should not be called by override")

    async def fetchrow(self):
        raise AssertionError("wrapper.fetchrow should not be called by override")

    async def execute(self, *args, **kwargs):
        raise AssertionError("wrapper.execute should not be called by override")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def raw() -> _RawStub:
    return _RawStub()


@pytest.fixture
def wrapped(raw: _RawStub) -> _WrapperStub:
    return _WrapperStub(raw)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unwraps_asyncdb_wrapper(wrapped: _WrapperStub, raw: _RawStub) -> None:
    """Wrapper -> engine() -> raw.fetch(sql, *args); wrapper.fetch not called."""
    result = await NavigatorToolkit._run_on_conn(
        "SELECT * FROM auth.programs WHERE program_id = $1",
        (42,),
        ["*"],
        wrapped,
        False,
    )
    assert result == [{"program_id": 1}]
    assert raw.calls == [
        ("fetch", "SELECT * FROM auth.programs WHERE program_id = $1", (42,)),
    ]


@pytest.mark.asyncio
async def test_falls_back_when_no_engine(raw: _RawStub) -> None:
    """When conn has no .engine attribute, it is used directly."""
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
async def test_single_row(wrapped: _WrapperStub, raw: _RawStub) -> None:
    """single_row=True dispatches to fetchrow and returns dict(row)."""
    result = await NavigatorToolkit._run_on_conn(
        "SELECT * FROM auth.programs WHERE program_id = $1",
        (42,),
        ["*"],
        wrapped,
        True,
    )
    assert result == {"program_id": 1}
    assert raw.calls == [
        ("fetchrow", "SELECT * FROM auth.programs WHERE program_id = $1", (42,)),
    ]


@pytest.mark.asyncio
async def test_single_row_none_returns_empty_dict() -> None:
    """single_row=True with no matching row returns {} (matches parent shape)."""
    raw = _RawStub(row=None)
    wrapped = _WrapperStub(raw)
    result = await NavigatorToolkit._run_on_conn(
        "SELECT * FROM auth.programs WHERE program_id = $1",
        (999,),
        ["*"],
        wrapped,
        True,
    )
    assert result == {}


@pytest.mark.asyncio
async def test_returning_false_runs_execute(wrapped: _WrapperStub, raw: _RawStub) -> None:
    """returning=False dispatches to execute and returns {'status': 'ok'}."""
    result = await NavigatorToolkit._run_on_conn(
        "INSERT INTO auth.programs(program_name) VALUES ($1)",
        ("demo",),
        None,
        wrapped,
        False,
    )
    assert result == {"status": "ok"}
    assert raw.calls == [
        ("execute", "INSERT INTO auth.programs(program_name) VALUES ($1)", ("demo",)),
    ]


@pytest.mark.asyncio
async def test_multi_row_empty_returns_empty_list() -> None:
    """Empty fetch result returns [] (matches parent shape)."""
    raw = _RawStub(rows=[])
    wrapped = _WrapperStub(raw)
    result = await NavigatorToolkit._run_on_conn(
        "SELECT * FROM auth.programs WHERE 1=0",
        (),
        ["*"],
        wrapped,
        False,
    )
    assert result == []

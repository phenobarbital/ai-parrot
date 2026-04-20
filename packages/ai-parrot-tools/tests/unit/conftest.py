"""Fixtures for NavigatorToolkit unit tests — FEAT-107 TASK-748.

Provides the ``navigator_toolkit_factory`` fixture used by every
NavigatorToolkit unit test in this package.  The factory creates an
instance of :class:`NavigatorToolkit` with **all DB-touching methods
replaced by AsyncMocks** so tests run without a real database.
"""
from __future__ import annotations

import pytest

from parrot_tools.navigator.toolkit import NavigatorToolkit


class _AsyncContextManager:
    """Minimal async context manager stub for :meth:`NavigatorToolkit.transaction`.

    Used so ``async with self.transaction() as conn:`` doesn't raise when
    the toolkit is constructed with a stub DSN.
    """

    def __init__(self, conn: object) -> None:
        self.conn = conn

    async def __aenter__(self) -> object:
        return self.conn

    async def __aexit__(self, *args: object) -> None:
        pass


@pytest.fixture
def navigator_toolkit_factory(mocker):
    """Factory fixture: create a ``NavigatorToolkit`` with all DB calls mocked.

    Usage::

        def test_something(navigator_toolkit_factory):
            tk = navigator_toolkit_factory()
            # tk.insert_row, tk.upsert_row, … are AsyncMocks
            # tk._nav_run_one, tk._nav_run_query, tk._nav_execute are mocked
            # tk._is_superuser == True, permissions are pre-seeded

    Args:
        user_id: User identity pre-loaded into the toolkit (default 1).
        is_superuser: Whether the user has superuser (group_id=1) access.
        **kwargs: Extra kwargs forwarded to :class:`NavigatorToolkit.__init__`.

    Returns:
        A :class:`NavigatorToolkit` instance ready for unit testing.
    """

    def _factory(user_id: int = 1, is_superuser: bool = True, **kwargs) -> NavigatorToolkit:
        tk = NavigatorToolkit(dsn="postgres://stub", user_id=user_id, **kwargs)

        # Pre-seed the permission cache so ``_load_user_permissions`` returns
        # immediately without hitting the database.
        tk._is_superuser = is_superuser
        tk._user_programs = set()
        tk._user_groups = {1}
        tk._user_clients = set()
        tk._user_modules = set()

        # ── PostgresToolkit CRUD primitives ──────────────────────────────
        # These are the methods the migration tasks will wire up.
        # Asserting ``call_count == 0`` on them proves confirm_execution=False
        # guards are intact.
        for name in (
            "insert_row",
            "upsert_row",
            "update_row",
            "delete_row",
            "select_rows",
            "execute_query",
            "execute_sql",  # escape hatch used by migration tasks for raw SQL inside tx
        ):
            setattr(tk, name, mocker.AsyncMock())

        # ── execute_sql stub ──────────────────────────────────────────────
        # After TASK-756, all _nav_* helpers were deleted and callers use
        # execute_sql directly.  We stub execute_sql with a side_effect
        # that returns plausible values so confirm_execution=False code
        # paths can complete without raising before the guard.
        _stub_row: dict = {
            "program_id": 1,
            "program_slug": "stub",
            "module_id": 1,
            "module_slug": "stub_module",
            "dashboard_id": "00000000-0000-0000-0000-000000000001",
            "widget_id": "00000000-0000-0000-0000-000000000002",
        }

        async def _execute_sql_stub(*args, returning=True, single_row=False, **kwargs):
            if not returning:
                return None
            if single_row:
                return _stub_row
            return []

        tk.execute_sql = _execute_sql_stub

        # ── Transaction context manager ───────────────────────────────────
        tk.transaction = mocker.MagicMock(
            return_value=_AsyncContextManager(conn=mocker.AsyncMock())
        )

        return tk

    return _factory

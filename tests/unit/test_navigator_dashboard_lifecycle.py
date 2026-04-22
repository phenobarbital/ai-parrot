"""Regression tests for FEAT-119 — dashboard draft/publish lifecycle.

Covers:
- create_dashboard shape invariants (is_system field removed from API).
- clone_dashboard owner coherence (user_id defaults to self.user_id).
- publish_dashboard authorization (owner OR superuser only).
- publish_dashboard plan/confirm flow.
- publish_dashboard idempotency + atomic UPDATE shape.

Spec: sdd/specs/navigator-dashboard-draft-publish-lifecycle.spec.md
Task:  sdd/tasks/active/TASK-840-dashboard-lifecycle-tests.md
"""
from __future__ import annotations

import inspect
import logging
import os
import sys
from contextlib import asynccontextmanager

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
from parrot_tools.navigator.schemas import (  # noqa: E402
    DashboardCreateInput,
    PublishDashboardInput,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_toolkit(
    *,
    user_id: int | None = 42,
    is_superuser: bool = False,
    dashboard_row: dict | None = None,
    existing_dashboard_matches_name: bool = False,
) -> tuple[NavigatorToolkit, dict]:
    """Build a NavigatorToolkit skeleton bypassing __init__.

    Returns the toolkit plus a ``captures`` dict that records calls
    to ``insert_row`` / ``update_row`` / ``select_rows`` (used by the
    tests to assert on payloads).
    """
    tk = NavigatorToolkit.__new__(NavigatorToolkit)
    tk.user_id = user_id
    tk._is_superuser = is_superuser
    tk._in_transaction = False
    tk.logger = logging.getLogger("test_dashboard_lifecycle")

    captures = {
        "insert_row": [],
        "update_row": [],
        "select_rows": [],
    }

    async def _noop(*a, **kw):
        return None

    async def _load_perms(*a, **kw):
        return None

    async def _check_program_access(program_id, *a, **kw):
        return None

    async def _check_write_access(program_id, *a, **kw):
        return None

    async def _check_module_access(module_id, *a, **kw):
        return None

    async def _resolve_program_id(program_id=None, program_slug=None, **kw):
        return program_id or 1

    async def _resolve_module_id(module_id=None, module_slug=None, program_id=None, **kw):
        return module_id or 1

    async def _select_rows(table, *, where=None, columns=None, **kw):
        captures["select_rows"].append(
            {"table": table, "where": where, "columns": columns, "kwargs": kw}
        )
        if table == "navigator.dashboards":
            # publish_dashboard path: return the dashboard row
            if dashboard_row is not None:
                return [dashboard_row]
            # create_dashboard idempotency check path:
            if existing_dashboard_matches_name:
                return [{"dashboard_id": "existing-uuid", "name": "X", "slug": "x"}]
            return []
        return []

    async def _insert_row(table, *, data, conn=None, returning=None, **kw):
        captures["insert_row"].append(
            {"table": table, "data": dict(data), "conn": conn, "returning": returning}
        )
        return {"dashboard_id": "new-uuid", "name": data.get("name")}

    async def _update_row(table, *, data, where, conn=None, **kw):
        captures["update_row"].append(
            {"table": table, "data": dict(data), "where": dict(where), "conn": conn}
        )
        return {"status": "ok"}

    @asynccontextmanager
    async def _transaction():
        yield object()  # dummy tx handle

    # Bind all stubs to the instance.
    tk._load_user_permissions = _load_perms
    tk._check_program_access = _check_program_access
    tk._check_write_access = _check_write_access
    tk._check_module_access = _check_module_access
    tk._resolve_program_id = _resolve_program_id
    tk._resolve_module_id = _resolve_module_id
    tk.select_rows = _select_rows
    tk.insert_row = _insert_row
    tk.update_row = _update_row
    tk.transaction = _transaction

    return tk, captures


# ---------------------------------------------------------------------------
# Group A — create_dashboard shape invariants
# ---------------------------------------------------------------------------


def test_dashboard_create_input_has_no_is_system_field():
    assert "is_system" not in DashboardCreateInput.model_fields


def test_create_dashboard_has_no_is_system_kwarg():
    params = inspect.signature(NavigatorToolkit.create_dashboard).parameters
    assert "is_system" not in params


@pytest.mark.asyncio
async def test_create_dashboard_insert_payload_is_system_false():
    tk, captures = _make_toolkit()
    result = await tk.create_dashboard(
        name="Metrics Dashboard",
        module_id=1104,
        program_id=7,
        confirm_execution=True,
    )
    assert result["status"] == "success"
    assert len(captures["insert_row"]) == 1
    data = captures["insert_row"][0]["data"]
    assert data["is_system"] is False
    assert data["is_system"] is not True
    assert data["is_system"] is not None


# ---------------------------------------------------------------------------
# Group B — clone_dashboard owner coherence
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_clone_dashboard_defaults_user_id_to_self():
    src_row = {
        "dashboard_id": "src-uuid",
        "description": "Src", "module_id": 1, "program_id": 7,
        "enabled": True, "shared": False, "allow_filtering": True,
        "allow_widgets": True, "dashboard_type": "3", "position": 1,
        "params": {}, "attributes": {}, "conditions": {},
        "render_partials": False, "save_filtering": True,
    }

    tk, captures = _make_toolkit(user_id=42)

    # clone_dashboard calls _check_dashboard_access, select_rows (2×),
    # and insert_row inside a transaction.  Our stubs cover all of these
    # except _check_dashboard_access — add it:
    async def _check_dashboard_access(dashboard_id, *a, **kw):
        return None

    tk._check_dashboard_access = _check_dashboard_access

    # select_rows must return the src dashboard the first time
    # (for the column copy) and empty widgets after.
    # clone_dashboard calls select_rows 3 times: write-access check on
    # navigator.dashboards, the main dashboard fetch, then the widgets
    # fetch (empty = no widgets to clone).
    calls_iter = iter([[src_row], [src_row], []])

    async def _select_rows(table, *, where=None, columns=None, **kw):
        return next(calls_iter, [])

    tk.select_rows = _select_rows

    await tk.clone_dashboard(
        source_dashboard_id="22222222-2222-2222-2222-222222222222",
        new_name="Clone",
        user_id=None,  # explicit None → should fall back to self.user_id
        confirm_execution=True,
    )

    assert len(captures["insert_row"]) == 1
    data = captures["insert_row"][0]["data"]
    assert data["user_id"] == 42, f"expected self.user_id=42, got {data['user_id']}"


@pytest.mark.asyncio
async def test_clone_dashboard_respects_explicit_user_id():
    src_row = {
        "dashboard_id": "src-uuid",
        "description": None, "module_id": 1, "program_id": 7,
        "enabled": True, "shared": False, "allow_filtering": True,
        "allow_widgets": True, "dashboard_type": "3", "position": 1,
        "params": {}, "attributes": {}, "conditions": {},
        "render_partials": False, "save_filtering": True,
    }

    tk, captures = _make_toolkit(user_id=42)

    async def _check_dashboard_access(dashboard_id, *a, **kw):
        return None

    tk._check_dashboard_access = _check_dashboard_access

    # clone_dashboard calls select_rows 3 times: write-access check on
    # navigator.dashboards, the main dashboard fetch, then the widgets
    # fetch (empty = no widgets to clone).
    calls_iter = iter([[src_row], [src_row], []])

    async def _select_rows(table, *, where=None, columns=None, **kw):
        return next(calls_iter, [])

    tk.select_rows = _select_rows

    await tk.clone_dashboard(
        source_dashboard_id="22222222-2222-2222-2222-222222222222",
        new_name="Clone",
        user_id=999,  # explicit value wins
        confirm_execution=True,
    )

    data = captures["insert_row"][0]["data"]
    assert data["user_id"] == 999


# ---------------------------------------------------------------------------
# Group C — publish_dashboard authorization
# ---------------------------------------------------------------------------


def _draft_row(owner: int | None = 99, name: str = "Metrics Dashboard") -> dict:
    return {
        "dashboard_id": "dash-uuid",
        "name": name,
        "program_id": 7,
        "module_id": 1104,
        "is_system": False,
        "user_id": owner,
    }


@pytest.mark.asyncio
async def test_publish_rejects_non_owner_non_superuser():
    tk, _ = _make_toolkit(
        user_id=42, is_superuser=False,
        dashboard_row=_draft_row(owner=99),
    )
    with pytest.raises(PermissionError, match="owner"):
        await tk.publish_dashboard(
            "11111111-1111-1111-1111-111111111111",
            confirm_execution=True,
        )


@pytest.mark.asyncio
async def test_publish_allows_owner():
    tk, captures = _make_toolkit(
        user_id=99, is_superuser=False,
        dashboard_row=_draft_row(owner=99),
    )
    result = await tk.publish_dashboard(
        "11111111-1111-1111-1111-111111111111",
        confirm_execution=True,
    )
    assert result["status"] == "success"
    assert len(captures["update_row"]) == 1


@pytest.mark.asyncio
async def test_publish_allows_superuser_any_owner():
    tk, captures = _make_toolkit(
        user_id=1, is_superuser=True,  # different from owner
        dashboard_row=_draft_row(owner=99),
    )
    result = await tk.publish_dashboard(
        "11111111-1111-1111-1111-111111111111",
        confirm_execution=True,
    )
    assert result["status"] == "success"
    assert len(captures["update_row"]) == 1


@pytest.mark.asyncio
async def test_publish_allows_superuser_orphan():
    tk, captures = _make_toolkit(
        user_id=1, is_superuser=True,
        dashboard_row=_draft_row(owner=None),
    )
    result = await tk.publish_dashboard(
        "11111111-1111-1111-1111-111111111111",
        confirm_execution=True,
    )
    assert result["status"] == "success"


@pytest.mark.asyncio
async def test_publish_rejects_non_superuser_orphan():
    tk, _ = _make_toolkit(
        user_id=42, is_superuser=False,
        dashboard_row=_draft_row(owner=None),
    )
    with pytest.raises(PermissionError, match="orphan|owner"):
        await tk.publish_dashboard(
            "11111111-1111-1111-1111-111111111111",
            confirm_execution=True,
        )


# ---------------------------------------------------------------------------
# Group D — publish_dashboard plan/confirm flow
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_publish_plan_then_confirm():
    tk, captures = _make_toolkit(
        user_id=99,
        dashboard_row=_draft_row(owner=99),
    )

    # First call — no confirm — returns the plan, no UPDATE issued.
    plan = await tk.publish_dashboard(
        "11111111-1111-1111-1111-111111111111",
        confirm_execution=False,
    )
    assert plan["status"] == "confirm_execution"
    assert "action" in plan
    assert captures["update_row"] == []

    # Second call — confirm — executes the UPDATE.
    result = await tk.publish_dashboard(
        "11111111-1111-1111-1111-111111111111",
        confirm_execution=True,
    )
    assert result["status"] == "success"
    assert len(captures["update_row"]) == 1


@pytest.mark.asyncio
async def test_publish_plan_shows_before_after():
    tk, _ = _make_toolkit(
        user_id=99,
        dashboard_row=_draft_row(owner=99),
    )
    plan = await tk.publish_dashboard(
        "11111111-1111-1111-1111-111111111111",
        confirm_execution=False,
    )
    action = plan["action"]
    assert "is_system" in action
    assert "False" in action and "True" in action
    assert "user_id" in action
    assert "NULL" in action


# ---------------------------------------------------------------------------
# Group E — publish_dashboard idempotency + update shape
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_publish_idempotent_on_already_system():
    already_published = _draft_row(owner=None)
    already_published["is_system"] = True

    tk, captures = _make_toolkit(
        user_id=1, is_superuser=True,
        dashboard_row=already_published,
    )
    result = await tk.publish_dashboard(
        "11111111-1111-1111-1111-111111111111",
        confirm_execution=True,
    )
    assert result["status"] == "success"
    assert result["result"].get("already_published") is True
    assert captures["update_row"] == [], "No UPDATE should be issued when already published"


@pytest.mark.asyncio
async def test_publish_update_payload_atomic():
    tk, captures = _make_toolkit(
        user_id=99,
        dashboard_row=_draft_row(owner=99),
    )
    await tk.publish_dashboard(
        "11111111-1111-1111-1111-111111111111",
        confirm_execution=True,
    )
    assert len(captures["update_row"]) == 1
    data = captures["update_row"][0]["data"]
    assert data == {"is_system": True, "user_id": None}


@pytest.mark.asyncio
async def test_publish_missing_dashboard_returns_error():
    tk, _ = _make_toolkit(
        user_id=1, is_superuser=True,
        dashboard_row=None,  # select_rows returns [] → not found
    )
    result = await tk.publish_dashboard(
        "11111111-1111-1111-1111-111111111111",
        confirm_execution=True,
    )
    assert result["status"] == "error"
    assert "not found" in result.get("error", "").lower()


# ---------------------------------------------------------------------------
# Schema sanity
# ---------------------------------------------------------------------------


def test_publish_dashboard_input_fields():
    fields = PublishDashboardInput.model_fields
    assert "dashboard_id" in fields
    assert "confirm_execution" in fields
    # Must not accept is_system directly — publish is explicit semantic.
    assert "is_system" not in fields
    assert "user_id" not in fields

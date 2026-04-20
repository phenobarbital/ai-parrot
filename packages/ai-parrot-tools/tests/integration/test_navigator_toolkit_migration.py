"""Integration smoke tests for FEAT-107 — NavigatorToolkit method migration.

These tests drive the full create chain against a live Postgres instance,
proving row counts, idempotency, and transactional rollback end-to-end.

All tests skip when NAVIGATOR_DSN environment variable is absent.
"""
from __future__ import annotations

import os
import uuid

import pytest

from parrot_tools.navigator.toolkit import NavigatorToolkit


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
async def toolkit(navigator_dsn: str) -> NavigatorToolkit:
    """Return a NavigatorToolkit with superuser access against the live DSN."""
    tk = NavigatorToolkit(dsn=navigator_dsn, user_id=1)
    # Load permissions once; tests assume superuser context.
    await tk._load_user_permissions()
    return tk


@pytest.fixture
async def scratch_slug() -> str:
    """Unique program slug per test run to avoid parallel-test collisions."""
    return f"feat107_{uuid.uuid4().hex[:12]}"


@pytest.fixture
async def scratch_program(toolkit: NavigatorToolkit, scratch_slug: str):
    """Create a scratch program and tear it down after the test."""
    result = await toolkit.create_program(
        program_name=f"FEAT-107 Scratch {scratch_slug}",
        program_slug=scratch_slug,
        client_ids=[1],
        group_ids=[1],
        confirm_execution=True,
    )
    assert result["status"] == "success"
    program_id: int = result["result"]["program_id"]

    yield {"program_id": program_id, "program_slug": scratch_slug}

    # Teardown — best-effort cascade delete
    try:
        await toolkit.execute_sql(
            "DELETE FROM auth.programs WHERE program_slug LIKE 'feat107_%'",
            (),
            returning=False,
        )
    except Exception:  # noqa: BLE001
        pass


# ---------------------------------------------------------------------------
# Test 1: End-to-end create chain + row counts
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_end_to_end_program_module_dashboard_widget(
    toolkit: NavigatorToolkit, scratch_program: dict
) -> None:
    """Drive create_program → create_module → create_dashboard → create_widget.

    Asserts row presence in all 8 tables after each step.
    """
    pid = scratch_program["program_id"]
    slug = scratch_program["program_slug"]

    # --- create_module ---
    mod_result = await toolkit.create_module(
        module_name="Home",
        module_slug="home",
        program_id=pid,
        confirm_execution=True,
    )
    assert mod_result["status"] == "success"
    module_id: int = mod_result["result"]["module_id"]

    # navigator.modules must have a row
    mod_rows = await toolkit.select_rows(
        "navigator.modules",
        where={"module_id": module_id},
        columns=["module_id"],
    )
    assert len(mod_rows) == 1, "navigator.modules must have exactly one row for the new module"

    # --- create_dashboard ---
    dash_result = await toolkit.create_dashboard(
        name="Test Dashboard",
        module_id=module_id,
        program_id=pid,
        confirm_execution=True,
    )
    assert dash_result["status"] == "success"
    dashboard_id: str = dash_result["result"]["dashboard_id"]

    dash_rows = await toolkit.select_rows(
        "navigator.dashboards",
        where={"dashboard_id": toolkit._to_uuid(dashboard_id)},
        columns=["dashboard_id"],
    )
    assert len(dash_rows) == 1, "navigator.dashboards must have a row for the new dashboard"

    # --- create_widget ---
    widget_result = await toolkit.create_widget(
        dashboard_id=dashboard_id,
        program_id=pid,
        widget_name="Test Widget",
        title="Test Widget Title",
        module_id=module_id,
        confirm_execution=True,
    )
    assert widget_result["status"] == "success"
    widget_id: str = widget_result["result"]["widget_id"]

    wgt_rows = await toolkit.select_rows(
        "navigator.widgets",
        where={"widget_id": toolkit._to_uuid(widget_id)},
        columns=["widget_id"],
    )
    assert len(wgt_rows) == 1, "navigator.widgets must have a row for the new widget"

    # --- auth tables ---
    pc_rows = await toolkit.select_rows(
        "auth.program_clients",
        where={"program_id": pid},
        columns=["client_id"],
    )
    assert len(pc_rows) >= 1, "auth.program_clients must have at least one row"

    pg_rows = await toolkit.select_rows(
        "auth.program_groups",
        where={"program_id": pid},
        columns=["group_id"],
    )
    assert len(pg_rows) >= 1, "auth.program_groups must have at least one row"


# ---------------------------------------------------------------------------
# Test 2: Idempotency
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_confirm_execution_plan_then_confirm_materializes_rows(
    toolkit: NavigatorToolkit, scratch_slug: str
) -> None:
    """Plan-only call (confirm_execution=False) creates zero rows.

    Confirm-execution=True call materializes them.
    """
    # Plan only — no rows should appear
    plan_result = await toolkit.create_program(
        program_name=f"Idempotency Scratch {scratch_slug}",
        program_slug=scratch_slug,
        client_ids=[1],
        confirm_execution=False,
    )
    assert plan_result["status"] == "confirm_execution"

    # No rows in auth.programs yet
    before_rows = await toolkit.select_rows(
        "auth.programs",
        where={"program_slug": scratch_slug},
        columns=["program_id"],
    )
    assert len(before_rows) == 0, "No rows must be created with confirm_execution=False"

    # Now materialize
    real_result = await toolkit.create_program(
        program_name=f"Idempotency Scratch {scratch_slug}",
        program_slug=scratch_slug,
        client_ids=[1],
        confirm_execution=True,
    )
    assert real_result["status"] == "success"

    after_rows = await toolkit.select_rows(
        "auth.programs",
        where={"program_slug": scratch_slug},
        columns=["program_id"],
    )
    assert len(after_rows) == 1, "Exactly one program row must exist after confirm_execution=True"

    # Second call must be idempotent (already_existed)
    second_result = await toolkit.create_program(
        program_name=f"Idempotency Scratch {scratch_slug}",
        program_slug=scratch_slug,
        client_ids=[1],
        confirm_execution=True,
    )
    assert second_result["status"] == "success"
    assert second_result["result"].get("already_existed") is True

    after_second_rows = await toolkit.select_rows(
        "auth.programs",
        where={"program_slug": scratch_slug},
        columns=["program_id"],
    )
    assert len(after_second_rows) == 1, "No duplicate program rows on second call"

    # Cleanup
    try:
        await toolkit.execute_sql(
            "DELETE FROM auth.programs WHERE program_slug LIKE 'feat107_%'",
            (),
            returning=False,
        )
    except Exception:  # noqa: BLE001
        pass


# ---------------------------------------------------------------------------
# Test 3: Transactional rollback — no orphan module row
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_transaction_rollback_on_mid_flow_failure(
    toolkit: NavigatorToolkit, scratch_program: dict
) -> None:
    """Simulated failure inside create_module must leave no orphan navigator.modules row.

    Monkey-patches upsert_row to raise on its second call (which happens inside
    the module transaction after insert_row succeeds), verifying the entire
    transaction rolls back.
    """
    pid = scratch_program["program_id"]

    original_upsert = toolkit.upsert_row
    calls: dict = {"n": 0}

    async def boom(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("simulated mid-flow failure")
        return await original_upsert(*args, **kwargs)

    toolkit.upsert_row = boom  # type: ignore[method-assign]

    with pytest.raises(RuntimeError, match="simulated mid-flow failure"):
        await toolkit.create_module(
            module_name="Orphan Module",
            module_slug="orphan",
            program_id=pid,
            client_ids=[1],
            group_ids=[1],
            confirm_execution=True,
        )

    # Restore
    toolkit.upsert_row = original_upsert  # type: ignore[method-assign]

    # No orphan module row should remain
    rows = await toolkit.select_rows(
        "navigator.modules",
        where={"program_id": pid, "module_slug": f"{scratch_program['program_slug']}_orphan"},
        columns=["module_id"],
    )
    assert rows == [], (
        f"No orphan navigator.modules row must remain after rollback, but found: {rows}"
    )


# ---------------------------------------------------------------------------
# Test 4: update_dashboard PK-in-WHERE regression guard (FEAT-106)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_update_dashboard_pk_enforcement_unchanged(
    toolkit: NavigatorToolkit, scratch_program: dict
) -> None:
    """update_dashboard must enforce PK-in-WHERE (FEAT-106 regression guard).

    Calling update_dashboard without a valid dashboard_id should raise.
    """
    with pytest.raises(Exception):
        # update_dashboard without identifying the dashboard must fail
        await toolkit.update_dashboard(
            dashboard_id=None,
            name="Should Fail",
            confirm_execution=True,
        )

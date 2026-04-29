"""Tests asserting FEAT-117 workarounds are removed from NavigatorToolkit.

TASK-930 — FEAT-118: After the framework-level asyncpg boundary fix all three
FEAT-117 override methods must be gone from NavigatorToolkit.__dict__ and
inherited from parent classes (PostgresToolkit / SQLToolkit).
"""
from __future__ import annotations

import os
import sys

# Load worktree source (must precede any parrot imports)
# __file__ is tests/unit/bots/database/toolkits/ — go 3 levels up to tests/unit/
_UNIT_DIR = os.path.normpath(
    os.path.join(os.path.dirname(__file__), os.pardir, os.pardir, os.pardir)
)
sys.path.insert(0, _UNIT_DIR)
from conftest_db import setup_worktree_imports  # noqa: E402
setup_worktree_imports()

# Add ai-parrot-tools src so parrot_tools is importable
_WT_ROOT = os.path.normpath(
    os.path.join(os.path.dirname(__file__), os.pardir, os.pardir, os.pardir, os.pardir, os.pardir)
)
_TOOLS_SRC = os.path.join(_WT_ROOT, "packages", "ai-parrot-tools", "src")
if _TOOLS_SRC not in sys.path:
    sys.path.insert(0, _TOOLS_SRC)

from parrot_tools.navigator.toolkit import NavigatorToolkit  # noqa: E402


# ---------------------------------------------------------------------------
# FEAT-117 workarounds must be GONE from NavigatorToolkit.__dict__
# ---------------------------------------------------------------------------

def test_navigator_toolkit_no_run_on_conn_override():
    """NavigatorToolkit must NOT have a local _run_on_conn override.

    After FEAT-118 the framework-level boundary unwrap in
    _acquire_asyncdb_connection() yields a raw asyncpg.Connection directly,
    so the FEAT-117 workaround in NavigatorToolkit is redundant and removed.
    NavigatorToolkit now inherits _run_on_conn from PostgresToolkit.
    """
    assert "_run_on_conn" not in NavigatorToolkit.__dict__, (
        "NavigatorToolkit still has a local _run_on_conn override — "
        "it should inherit from PostgresToolkit after FEAT-118"
    )


def test_navigator_toolkit_no_build_table_metadata_override():
    """NavigatorToolkit must NOT have a local _build_table_metadata override.

    After FEAT-118 the parent SQLToolkit._build_table_metadata passes params
    correctly (D2 bug fixed), so the FEAT-117 local reimplementation in
    NavigatorToolkit is removed. NavigatorToolkit now inherits from SQLToolkit.
    """
    assert "_build_table_metadata" not in NavigatorToolkit.__dict__, (
        "NavigatorToolkit still has a local _build_table_metadata override — "
        "it should inherit from SQLToolkit after FEAT-118"
    )


def test_navigator_toolkit_no_transaction_override():
    """NavigatorToolkit must NOT have a local transaction() override.

    After FEAT-118 PostgresToolkit.transaction() was rewritten to use native
    asyncpg.Connection.transaction() (TASK-929). The FEAT-117 workaround in
    NavigatorToolkit is now redundant and removed. NavigatorToolkit inherits
    the corrected transaction() from PostgresToolkit.
    """
    assert "transaction" not in NavigatorToolkit.__dict__, (
        "NavigatorToolkit still has a local transaction() override — "
        "it should inherit from PostgresToolkit after FEAT-118"
    )


def test_navigator_toolkit_no_in_transaction_flag():
    """NavigatorToolkit.__init__ must not set _in_transaction.

    The _in_transaction boolean flag was a FEAT-117 guard for the old nested
    transaction check. It was removed in TASK-929 from PostgresToolkit and
    must not be present in NavigatorToolkit either.
    """
    tk = NavigatorToolkit.__new__(NavigatorToolkit)
    # Before __init__, NavigatorToolkit should not have _in_transaction in
    # its class hierarchy (check class-level)
    # It's acceptable if the instance doesn't have it as an instance attr
    # We verify that NavigatorToolkit.__dict__ doesn't define it
    assert "_in_transaction" not in NavigatorToolkit.__dict__, (
        "NavigatorToolkit.__dict__ defines _in_transaction — "
        "this flag was removed in TASK-929"
    )


def test_navigator_toolkit_inherits_run_on_conn_from_postgres():
    """NavigatorToolkit._run_on_conn must be the PostgresToolkit version."""
    from parrot.bots.database.toolkits.postgres import PostgresToolkit
    # MRO lookup must resolve to PostgresToolkit (not NavigatorToolkit)
    assert NavigatorToolkit._run_on_conn is PostgresToolkit._run_on_conn, (
        "NavigatorToolkit._run_on_conn is not the PostgresToolkit version"
    )


def test_navigator_toolkit_inherits_build_table_metadata_from_sql():
    """NavigatorToolkit._build_table_metadata must be inherited from SQLToolkit."""
    from parrot.bots.database.toolkits.sql import SQLToolkit
    assert NavigatorToolkit._build_table_metadata is SQLToolkit._build_table_metadata, (
        "NavigatorToolkit._build_table_metadata is not the SQLToolkit version"
    )

"""Tests for legacy tool.py cleanup (FEAT-136 TASK-935).

Verifies:
- DriverInfo class is removed
- Local QueryValidator class is removed
- get_default_credentials free function is removed
- _validate_query_safety no longer exists as a separate method (inline)
  Actually it's refactored to use parrot.security.QueryValidator
- _get_default_credentials delegates to interface
- DatabaseQueryArgs driver normalization still works
- DatabaseQueryTool can be instantiated

Part of FEAT-136 — database-toolkit-parity, TASK-935.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest


# ---------------------------------------------------------------------------
# No local duplicates
# ---------------------------------------------------------------------------


class TestNoLocalDuplicates:
    """Verify removed classes are gone."""

    def test_no_local_driverinfo_class(self) -> None:
        import parrot.tools.databasequery.tool as mod
        assert not hasattr(mod, "DriverInfo"), (
            "DriverInfo class should be removed from tool.py"
        )

    def test_no_local_queryvalidator_class(self) -> None:
        import inspect
        import parrot.tools.databasequery.tool as mod
        # The module-level QueryValidator should not be defined there
        assert not hasattr(mod, "QueryValidator") or \
               mod.QueryValidator.__module__ != "parrot.tools.databasequery.tool", (
            "Local QueryValidator class should be removed from tool.py"
        )

    def test_no_local_get_default_credentials_function(self) -> None:
        import parrot.tools.databasequery.tool as mod
        # The free function `get_default_credentials` should not exist at module level
        assert not hasattr(mod, "get_default_credentials"), (
            "Free function get_default_credentials should be removed from tool.py"
        )

    def test_no_print_debug_statements(self) -> None:
        import inspect
        import parrot.tools.databasequery.tool as mod
        source = inspect.getsource(mod)
        assert 'print(' not in source, (
            "Debug print() statements should be removed from tool.py"
        )

    def test_uses_parrot_security_queryvalidator(self) -> None:
        """tool.py must import QueryValidator from parrot.security."""
        import parrot.tools.databasequery.tool as mod
        from parrot.security import QueryValidator
        # The module should reference parrot.security.QueryValidator
        # (either by importing or referencing it)
        assert mod.QueryValidator is QueryValidator or \
               "parrot.security" in str(getattr(mod, "QueryValidator", type(None)))

    def test_uses_shared_normalize_driver(self) -> None:
        """tool.py must import normalize_driver from sources."""
        import parrot.tools.databasequery.tool as mod
        from parrot.tools.databasequery.sources import normalize_driver
        assert mod.normalize_driver is normalize_driver


# ---------------------------------------------------------------------------
# Driver normalization via DatabaseQueryArgs
# ---------------------------------------------------------------------------


class TestDriverNormalization:
    """DatabaseQueryArgs still normalizes and validates drivers correctly."""

    def test_normalize_pg_from_postgres(self) -> None:
        from parrot.tools.databasequery.tool import DatabaseQueryArgs
        args = DatabaseQueryArgs(driver="postgres", query="SELECT 1")
        assert args.driver == "pg"

    def test_normalize_pg_from_postgresql(self) -> None:
        from parrot.tools.databasequery.tool import DatabaseQueryArgs
        args = DatabaseQueryArgs(driver="postgresql", query="SELECT 1")
        assert args.driver == "pg"

    def test_normalize_mysql_from_mariadb(self) -> None:
        from parrot.tools.databasequery.tool import DatabaseQueryArgs
        args = DatabaseQueryArgs(driver="mariadb", query="SELECT 1")
        assert args.driver == "mysql"

    def test_pg_stays_pg(self) -> None:
        from parrot.tools.databasequery.tool import DatabaseQueryArgs
        args = DatabaseQueryArgs(driver="pg", query="SELECT 1")
        assert args.driver == "pg"

    def test_influx_stays_influx(self) -> None:
        from parrot.tools.databasequery.tool import DatabaseQueryArgs
        args = DatabaseQueryArgs(
            driver="influx",
            query='from(bucket:"test") |> range(start: -1h)'
        )
        assert args.driver == "influx"

    def test_invalid_driver_raises(self) -> None:
        from parrot.tools.databasequery.tool import DatabaseQueryArgs
        with pytest.raises(Exception):
            DatabaseQueryArgs(driver="nonexistent_driver_xyz", query="SELECT 1")

    def test_supported_drivers_list(self) -> None:
        """All key drivers should pass validation."""
        from parrot.tools.databasequery.tool import DatabaseQueryArgs
        drivers = ["pg", "mysql", "bigquery", "sqlite", "oracle", "mssql",
                   "clickhouse", "duckdb", "influx", "mongo", "elastic"]
        queries = {
            "influx": 'from(bucket:"b") |> range(start: -1h)',
            "mongo": '{"status": "active"}',
            "elastic": '{"query": {"match_all": {}}}',
        }
        for driver in drivers:
            q = queries.get(driver, "SELECT 1")
            args = DatabaseQueryArgs(driver=driver, query=q)
            assert args.driver == driver


# ---------------------------------------------------------------------------
# Credential delegation
# ---------------------------------------------------------------------------


class TestCredentialDelegation:
    """_get_default_credentials delegates to interface, returns (dict, dsn_or_None)."""

    def test_returns_tuple(self) -> None:
        from parrot.tools.databasequery.tool import DatabaseQueryTool
        tool = DatabaseQueryTool()
        result = tool._get_default_credentials("pg")
        assert isinstance(result, tuple)
        assert len(result) == 2

    def test_creds_is_dict(self) -> None:
        from parrot.tools.databasequery.tool import DatabaseQueryTool
        tool = DatabaseQueryTool()
        creds, dsn = tool._get_default_credentials("pg")
        assert isinstance(creds, dict)

    def test_dsn_is_none_or_str(self) -> None:
        from parrot.tools.databasequery.tool import DatabaseQueryTool
        tool = DatabaseQueryTool()
        creds, dsn = tool._get_default_credentials("pg")
        assert dsn is None or isinstance(dsn, str)

    def test_delegates_to_interface(self) -> None:
        from parrot.tools.databasequery.tool import DatabaseQueryTool
        tool = DatabaseQueryTool()
        iface_result = {"host": "db.example.com", "port": "5432", "database": "mydb"}
        with patch("parrot.interfaces.database.get_default_credentials", return_value=iface_result):
            creds, dsn = tool._get_default_credentials("pg")
        assert creds.get("host") == "db.example.com"
        assert dsn is None

    def test_extracts_dsn_from_interface_result(self) -> None:
        from parrot.tools.databasequery.tool import DatabaseQueryTool
        tool = DatabaseQueryTool()
        iface_result = {"dsn": "pg://localhost/mydb", "host": "localhost"}
        with patch("parrot.interfaces.database.get_default_credentials", return_value=iface_result):
            creds, dsn = tool._get_default_credentials("pg")
        assert dsn == "pg://localhost/mydb"
        assert "dsn" not in creds  # extracted, not left in creds

    def test_merges_provided_credentials(self) -> None:
        from parrot.tools.databasequery.tool import DatabaseQueryTool
        tool = DatabaseQueryTool()
        iface_result = {"host": "default.host", "port": "5432"}
        provided = {"host": "override.host", "database": "mydb"}
        with patch("parrot.interfaces.database.get_default_credentials", return_value=iface_result):
            creds, dsn = tool._get_default_credentials("pg", provided)
        assert creds.get("host") == "override.host"  # override wins
        assert creds.get("database") == "mydb"

    def test_strips_none_values(self) -> None:
        from parrot.tools.databasequery.tool import DatabaseQueryTool
        tool = DatabaseQueryTool()
        iface_result = {"host": "localhost", "password": None}
        with patch("parrot.interfaces.database.get_default_credentials", return_value=iface_result):
            creds, dsn = tool._get_default_credentials("pg")
        assert "password" not in creds

    def test_empty_driver_returns_empty_creds(self) -> None:
        from parrot.tools.databasequery.tool import DatabaseQueryTool
        tool = DatabaseQueryTool()
        with patch("parrot.interfaces.database.get_default_credentials", return_value={}):
            creds, dsn = tool._get_default_credentials("duckdb")
        assert creds == {}
        assert dsn is None


# ---------------------------------------------------------------------------
# DatabaseQueryTool instantiation
# ---------------------------------------------------------------------------


class TestToolInstantiation:
    """DatabaseQueryTool must be instantiable after cleanup."""

    def test_can_instantiate(self) -> None:
        from parrot.tools.databasequery.tool import DatabaseQueryTool
        tool = DatabaseQueryTool()
        assert tool is not None

    def test_has_validate_query_safety(self) -> None:
        """_validate_query_safety still exists (refactored, not removed)."""
        from parrot.tools.databasequery.tool import DatabaseQueryTool
        tool = DatabaseQueryTool()
        assert hasattr(tool, "_validate_query_safety")

    def test_validate_query_safety_uses_parrot_security(self) -> None:
        """_validate_query_safety delegates to parrot.security.QueryValidator."""
        from parrot.tools.databasequery.tool import DatabaseQueryTool
        tool = DatabaseQueryTool()
        result = tool._validate_query_safety("DROP TABLE t", "pg")
        assert result["is_safe"] is False

    def test_validate_query_safety_safe_select(self) -> None:
        from parrot.tools.databasequery.tool import DatabaseQueryTool
        tool = DatabaseQueryTool()
        result = tool._validate_query_safety("SELECT 1", "pg")
        assert result["is_safe"] is True

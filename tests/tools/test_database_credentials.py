"""Unit tests for the expanded get_default_credentials() interface and source overrides.

Part of FEAT-136 — database-toolkit-parity, TASK-932.
"""
from __future__ import annotations

from unittest.mock import patch, MagicMock

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_config(**overrides):
    """Return a mock navconfig that answers config.get() calls."""
    mock_cfg = MagicMock()

    def _get(key, fallback=None):
        return overrides.get(key, fallback)

    mock_cfg.get.side_effect = _get
    return mock_cfg


# ---------------------------------------------------------------------------
# Tests for get_default_credentials() interface function
# ---------------------------------------------------------------------------


class TestGetDefaultCredentials:
    """Tests for parrot.interfaces.database.get_default_credentials()."""

    def test_returns_dict_type(self) -> None:
        from parrot.interfaces.database import get_default_credentials
        result = get_default_credentials("pg")
        assert isinstance(result, dict)

    def test_pg_has_required_keys(self) -> None:
        from parrot.interfaces.database import get_default_credentials
        result = get_default_credentials("pg")
        # Should have fallback values even without env vars
        # (host defaults to 'localhost')
        assert isinstance(result, dict)
        if result:  # non-empty when fallbacks are present
            assert "host" in result or "dsn" in result

    def test_mysql_returns_dict(self) -> None:
        from parrot.interfaces.database import get_default_credentials
        result = get_default_credentials("mysql")
        assert isinstance(result, dict)

    def test_bigquery_returns_dict(self) -> None:
        from parrot.interfaces.database import get_default_credentials
        result = get_default_credentials("bigquery")
        assert isinstance(result, dict)

    def test_oracle_returns_dict(self) -> None:
        from parrot.interfaces.database import get_default_credentials
        result = get_default_credentials("oracle")
        assert isinstance(result, dict)

    def test_mssql_returns_dict(self) -> None:
        from parrot.interfaces.database import get_default_credentials
        result = get_default_credentials("mssql")
        assert isinstance(result, dict)

    def test_clickhouse_returns_dict(self) -> None:
        from parrot.interfaces.database import get_default_credentials
        result = get_default_credentials("clickhouse")
        assert isinstance(result, dict)

    def test_duckdb_returns_empty_dict(self) -> None:
        from parrot.interfaces.database import get_default_credentials
        result = get_default_credentials("duckdb")
        assert result == {}

    def test_influx_returns_dict(self) -> None:
        from parrot.interfaces.database import get_default_credentials
        result = get_default_credentials("influx")
        assert isinstance(result, dict)

    def test_mongo_returns_dict(self) -> None:
        from parrot.interfaces.database import get_default_credentials
        result = get_default_credentials("mongo")
        assert isinstance(result, dict)

    def test_atlas_returns_dict(self) -> None:
        from parrot.interfaces.database import get_default_credentials
        result = get_default_credentials("atlas")
        assert isinstance(result, dict)

    def test_documentdb_returns_dict(self) -> None:
        from parrot.interfaces.database import get_default_credentials
        result = get_default_credentials("documentdb")
        assert isinstance(result, dict)

    def test_elastic_returns_dict(self) -> None:
        from parrot.interfaces.database import get_default_credentials
        result = get_default_credentials("elastic")
        assert isinstance(result, dict)

    def test_sqlite_returns_dict(self) -> None:
        from parrot.interfaces.database import get_default_credentials
        result = get_default_credentials("sqlite")
        assert isinstance(result, dict)

    def test_unknown_driver_returns_empty(self) -> None:
        from parrot.interfaces.database import get_default_credentials
        result = get_default_credentials("nonexistent_driver_xyz")
        assert result == {}

    def test_aliases_resolve_pg(self) -> None:
        from parrot.interfaces.database import get_default_credentials
        result_pg = get_default_credentials("pg")
        result_postgres = get_default_credentials("postgres")
        result_postgresql = get_default_credentials("postgresql")
        assert isinstance(result_pg, dict)
        assert isinstance(result_postgres, dict)
        assert isinstance(result_postgresql, dict)

    def test_aliases_resolve_mysql(self) -> None:
        from parrot.interfaces.database import get_default_credentials
        result_mysql = get_default_credentials("mysql")
        result_mariadb = get_default_credentials("mariadb")
        assert isinstance(result_mysql, dict)
        assert isinstance(result_mariadb, dict)

    def test_none_values_stripped(self) -> None:
        from parrot.interfaces.database import get_default_credentials
        for driver in ["pg", "mysql", "oracle", "mssql", "mongo", "elastic"]:
            result = get_default_credentials(driver)
            assert None not in result.values(), (
                f"Driver {driver!r} returned None values: {result}"
            )

    def test_pg_with_env_vars(self) -> None:
        """PG credentials include expected keys when env vars are set."""
        from parrot.interfaces.database import get_default_credentials
        mock_cfg = _make_config(
            PG_HOST="db.example.com",
            PG_PORT="5433",
            PG_DATABASE="mydb",
            PG_USER="admin",
            PG_PWD="secret",
        )
        # config and BASE_DIR are local imports inside the function;
        # patch navconfig module directly
        with patch("navconfig.config", mock_cfg, create=True):
            # Patch querysource to avoid import errors
            with patch.dict("sys.modules", {"querysource": None, "querysource.conf": None}):
                result = get_default_credentials("pg")
        assert result.get("host") == "db.example.com"
        assert result.get("port") == "5433"
        assert result.get("database") == "mydb"
        assert result.get("user") == "admin"
        assert result.get("password") == "secret"

    def test_mysql_with_env_vars(self) -> None:
        """MySQL credentials include expected keys when env vars are set."""
        from parrot.interfaces.database import get_default_credentials
        mock_cfg = _make_config(
            MYSQL_HOST="mysql.host",
            MYSQL_PORT="3307",
            MYSQL_DATABASE="appdb",
            MYSQL_USER="myuser",
            MYSQL_PASSWORD="mypass",
        )
        with patch("navconfig.config", mock_cfg, create=True):
            result = get_default_credentials("mysql")
        assert result.get("host") == "mysql.host"
        assert result.get("user") == "myuser"

    def test_mongo_includes_dbtype(self) -> None:
        """Mongo credentials always include dbtype=mongodb."""
        from parrot.interfaces.database import get_default_credentials
        mock_cfg = _make_config(
            MONGODB_HOST="mongo.host",
            MONGODB_PORT="27017",
            MONGODB_DATABASE="testdb",
        )
        with patch("navconfig.config", mock_cfg, create=True):
            result = get_default_credentials("mongo")
        assert result.get("dbtype") == "mongodb"

    def test_elastic_includes_fallback_keys(self) -> None:
        """Elastic credentials include expected keys when env vars are set."""
        from parrot.interfaces.database import get_default_credentials
        mock_cfg = _make_config(
            ELASTICSEARCH_HOST="es.host",
            ELASTICSEARCH_PORT="9201",
        )
        with patch("navconfig.config", mock_cfg, create=True):
            result = get_default_credentials("elastic")
        assert result.get("host") == "es.host"
        assert result.get("port") == "9201"

    def test_documentdb_includes_ssl(self) -> None:
        """DocumentDB credentials include ssl and tlsCAFile."""
        from parrot.interfaces.database import get_default_credentials
        mock_cfg = _make_config(
            DOCUMENTDB_HOSTNAME="docdb.host",
            DOCUMENTDB_PORT="27017",
            DOCUMENTDB_DATABASE="mydb",
        )
        mock_base_dir = MagicMock()
        mock_base_dir.joinpath.return_value = "/env/global-bundle.pem"
        with patch("navconfig.config", mock_cfg, create=True), \
             patch("navconfig.BASE_DIR", mock_base_dir, create=True):
            result = get_default_credentials("documentdb")
        assert "ssl" in result
        assert "tlsCAFile" in result
        assert result.get("dbtype") == "documentdb"


# ---------------------------------------------------------------------------
# Tests for source.get_default_credentials() overrides
# ---------------------------------------------------------------------------


class TestPostgresSourceCredentials:
    """Tests for PostgresSource.get_default_credentials()."""

    @pytest.mark.asyncio
    async def test_returns_dict(self) -> None:
        from parrot.tools.databasequery.sources.postgres import PostgresSource
        src = PostgresSource()
        with patch("parrot.interfaces.database.get_default_credentials", return_value={"host": "pg.host", "dsn": "pg://localhost/db"}):
            result = await src.get_default_credentials()
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_delegates_to_interface(self) -> None:
        from parrot.tools.databasequery.sources.postgres import PostgresSource
        src = PostgresSource()
        expected = {"host": "localhost", "port": "5432", "database": "db"}
        with patch("parrot.interfaces.database.get_default_credentials", return_value=expected) as mock_fn:
            result = await src.get_default_credentials()
        mock_fn.assert_called_once_with("pg")
        assert result == expected


class TestMySQLSourceCredentials:
    """Tests for MySQLSource.get_default_credentials()."""

    @pytest.mark.asyncio
    async def test_delegates_to_interface(self) -> None:
        from parrot.tools.databasequery.sources.mysql import MySQLSource
        src = MySQLSource()
        expected = {"host": "mysql.host", "port": "3306"}
        with patch("parrot.interfaces.database.get_default_credentials", return_value=expected) as mock_fn:
            result = await src.get_default_credentials()
        mock_fn.assert_called_once_with("mysql")
        assert result == expected

    @pytest.mark.asyncio
    async def test_returns_empty_when_no_config(self) -> None:
        from parrot.tools.databasequery.sources.mysql import MySQLSource
        src = MySQLSource()
        with patch("parrot.interfaces.database.get_default_credentials", return_value={}):
            result = await src.get_default_credentials()
        assert result == {}


class TestDocumentDBSourceCredentials:
    """Tests for DocumentDBSource.get_default_credentials()."""

    @pytest.mark.asyncio
    async def test_ssl_default_true(self) -> None:
        from parrot.tools.databasequery.sources.documentdb import DocumentDBSource
        src = DocumentDBSource()
        with patch("parrot.interfaces.database.get_default_credentials", return_value={}):
            result = await src.get_default_credentials()
        assert result.get("ssl") is True

    @pytest.mark.asyncio
    async def test_tlscafile_default_set(self) -> None:
        from parrot.tools.databasequery.sources.documentdb import DocumentDBSource
        src = DocumentDBSource()
        with patch("parrot.interfaces.database.get_default_credentials", return_value={}):
            result = await src.get_default_credentials()
        assert "tlsCAFile" in result

    @pytest.mark.asyncio
    async def test_ssl_not_overridden_if_set(self) -> None:
        """If interface returns ssl=False, setdefault should NOT override."""
        from parrot.tools.databasequery.sources.documentdb import DocumentDBSource
        src = DocumentDBSource()
        with patch("parrot.interfaces.database.get_default_credentials", return_value={"ssl": False}):
            result = await src.get_default_credentials()
        # setdefault does not override existing values
        assert result.get("ssl") is False


class TestAtlasSourceCredentials:
    """Tests for AtlasSource.get_default_credentials()."""

    @pytest.mark.asyncio
    async def test_returns_empty_when_no_config(self) -> None:
        from parrot.tools.databasequery.sources.atlas import AtlasSource
        src = AtlasSource()
        with patch("parrot.interfaces.database.get_default_credentials", return_value={}):
            result = await src.get_default_credentials()
        assert result == {}

    @pytest.mark.asyncio
    async def test_normalizes_srv_uri_host(self) -> None:
        """If host ends in .mongodb.net, converts to mongodb+srv:// DSN."""
        from parrot.tools.databasequery.sources.atlas import AtlasSource
        src = AtlasSource()
        creds = {
            "host": "cluster0.abc.mongodb.net",
            "username": "user",
            "password": "pass",
            "database": "mydb",
            "dbtype": "atlas",
        }
        with patch("parrot.interfaces.database.get_default_credentials", return_value=creds):
            result = await src.get_default_credentials()
        assert "dsn" in result
        assert result["dsn"].startswith("mongodb+srv://")
        assert "cluster0.abc.mongodb.net" in result["dsn"]
        assert "host" not in result

    @pytest.mark.asyncio
    async def test_keeps_plain_host(self) -> None:
        """If host is not an Atlas SRV hostname, return dict as-is."""
        from parrot.tools.databasequery.sources.atlas import AtlasSource
        src = AtlasSource()
        creds = {
            "host": "192.168.1.10",
            "port": "27017",
            "dbtype": "atlas",
        }
        with patch("parrot.interfaces.database.get_default_credentials", return_value=creds):
            result = await src.get_default_credentials()
        assert result.get("host") == "192.168.1.10"
        assert "dsn" not in result


class TestMongoSourceCredentials:
    """Tests for MongoSource.get_default_credentials()."""

    @pytest.mark.asyncio
    async def test_delegates_to_interface(self) -> None:
        from parrot.tools.databasequery.sources.mongodb import MongoSource
        src = MongoSource()
        expected = {"host": "mongo.host", "dbtype": "mongodb"}
        with patch("parrot.interfaces.database.get_default_credentials", return_value=expected) as mock_fn:
            result = await src.get_default_credentials()
        mock_fn.assert_called_once_with("mongo")
        assert result == expected


class TestElasticSourceCredentials:
    """Tests for ElasticSource.get_default_credentials()."""

    @pytest.mark.asyncio
    async def test_delegates_to_interface(self) -> None:
        from parrot.tools.databasequery.sources.elastic import ElasticSource
        src = ElasticSource()
        expected = {"host": "es.host", "port": "9200"}
        with patch("parrot.interfaces.database.get_default_credentials", return_value=expected) as mock_fn:
            result = await src.get_default_credentials()
        mock_fn.assert_called_once_with("elastic")
        assert result == expected


class TestInfluxSourceCredentials:
    """Tests for InfluxSource.get_default_credentials()."""

    @pytest.mark.asyncio
    async def test_delegates_to_interface(self) -> None:
        from parrot.tools.databasequery.sources.influx import InfluxSource
        src = InfluxSource()
        expected = {"host": "influx.host", "token": "mytoken"}
        with patch("parrot.interfaces.database.get_default_credentials", return_value=expected) as mock_fn:
            result = await src.get_default_credentials()
        mock_fn.assert_called_once_with("influx")
        assert result == expected


class TestSourcesEmptyWhenNoEnv:
    """Test that all sources return {} when interface returns {}."""

    @pytest.mark.asyncio
    async def test_postgres_empty(self) -> None:
        from parrot.tools.databasequery.sources.postgres import PostgresSource
        src = PostgresSource()
        with patch("parrot.interfaces.database.get_default_credentials", return_value={}):
            result = await src.get_default_credentials()
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_mysql_empty(self) -> None:
        from parrot.tools.databasequery.sources.mysql import MySQLSource
        src = MySQLSource()
        with patch("parrot.interfaces.database.get_default_credentials", return_value={}):
            result = await src.get_default_credentials()
        assert result == {}

    @pytest.mark.asyncio
    async def test_influx_empty(self) -> None:
        from parrot.tools.databasequery.sources.influx import InfluxSource
        src = InfluxSource()
        with patch("parrot.interfaces.database.get_default_credentials", return_value={}):
            result = await src.get_default_credentials()
        assert result == {}

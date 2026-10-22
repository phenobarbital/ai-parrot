"""SQL dialect alias map shared by wiki schema and tools (FEAT-540 M4)."""

from typing import Dict

#: Map ``DatabaseToolkit.database_type`` values to sqlglot dialect names.
SQLGLOT_DIALECT_MAP: Dict[str, str] = {
    "postgresql": "postgres",
    "postgres": "postgres",
    "bigquery": "bigquery",
    "mysql": "mysql",
    "mariadb": "mysql",
    "sqlite": "sqlite",
    "mssql": "tsql",
    "sqlserver": "tsql",
    "oracle": "oracle",
    "clickhouse": "clickhouse",
    "duckdb": "duckdb",
    "redshift": "redshift",
    "snowflake": "snowflake",
}

#: Legacy private alias kept for ``parrot.bots.database.toolkits.sql`` importers.
_SQLGLOT_DIALECT_MAP = SQLGLOT_DIALECT_MAP

__all__ = ["SQLGLOT_DIALECT_MAP"]

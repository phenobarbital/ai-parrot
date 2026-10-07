"""SQL dialect name mapping shared by the database toolkits and ``wikitoolkit``.

Kept dependency-free on purpose: ``parrot.knowledge.wiki`` imports it without
pulling ``parrot.bots`` (and its agent/chatbot machinery) into the process.
"""

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

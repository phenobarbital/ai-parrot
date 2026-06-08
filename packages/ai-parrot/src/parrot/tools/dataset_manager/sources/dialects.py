"""Driver–Dialect Map for FEAT-228 Data-Plane Authorization.

Maps ai-parrot driver aliases (as returned by ``normalize_driver``) to
sqlglot 30.9.0 dialect identifiers. Used by the physical-resource resolver
to parse SQL with the correct dialect so that table extraction is accurate
for each database backend.

Usage::

    from parrot.tools.dataset_manager.sources.dialects import driver_to_dialect

    dialect = driver_to_dialect("bigquery")   # returns "bigquery"
    dialect = driver_to_dialect("bq")          # returns "bigquery" (via normalize_driver)
    dialect = driver_to_dialect("unknown")     # returns None
"""
from __future__ import annotations

from typing import Optional

# Map from *canonical* driver names (output of ``normalize_driver``) to
# sqlglot 30.9.0 dialect identifiers.  Keys are the normalized form only;
# raw aliases are handled by calling ``normalize_driver`` first.
_DRIVER_DIALECT_MAP: dict[str, str] = {
    "pg": "postgres",
    "mysql": "mysql",
    "bigquery": "bigquery",
    "mssql": "tsql",
    "oracle": "oracle",
    "snowflake": "snowflake",
    "redshift": "redshift",
    "clickhouse": "clickhouse",
    "duckdb": "duckdb",
    "sqlite": "sqlite",
    "trino": "trino",
    "presto": "presto",
    "spark": "spark",
    "databricks": "databricks",
}


def driver_to_dialect(driver: str) -> Optional[str]:
    """Map an ai-parrot driver name to a sqlglot dialect identifier.

    Normalises the driver name via :func:`normalize_driver` before lookup so
    that raw aliases (``"postgres"``, ``"bq"``, ``"sqlserver"``, …) are
    resolved the same way as canonical names.

    Args:
        driver: Raw or pre-normalised ai-parrot driver name.

    Returns:
        A sqlglot dialect string (e.g. ``"postgres"``, ``"bigquery"``), or
        ``None`` if the driver is not in the known map.  The caller is
        responsible for deciding whether an unmapped driver is fail-open or
        fail-closed.

    Examples::

        >>> driver_to_dialect("pg")
        'postgres'
        >>> driver_to_dialect("bq")
        'bigquery'
        >>> driver_to_dialect("mssql")
        'tsql'
        >>> driver_to_dialect("unknown_db_xyz") is None
        True
    """
    from parrot.tools.databasequery.sources import normalize_driver

    canonical = normalize_driver(driver)
    return _DRIVER_DIALECT_MAP.get(canonical)

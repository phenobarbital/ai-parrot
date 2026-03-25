"""DatabaseToolkit — Source Registry & Driver Alias Resolution.

Provides a pluggable registry for database source implementations.
Sources self-register via the ``@register_source(driver)`` decorator.
The ``normalize_driver()`` function maps all known aliases to their
canonical driver names before registry lookup.

Part of FEAT-062 — DatabaseToolkit.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from parrot.tools.database.base import AbstractDatabaseSource

# ---------------------------------------------------------------------------
# Driver alias map: alias → canonical driver name
# ---------------------------------------------------------------------------

_DRIVER_ALIASES: dict[str, str] = {
    "postgres": "pg",
    "postgresql": "pg",
    "mariadb": "mysql",
    "bq": "bigquery",
    "sqlserver": "mssql",
    "influxdb": "influx",
    "mongodb": "mongo",
    "elasticsearch": "elastic",
    "opensearch": "elastic",
}

# ---------------------------------------------------------------------------
# Source registry
# ---------------------------------------------------------------------------

_SOURCE_REGISTRY: dict[str, type[AbstractDatabaseSource]] = {}

_SOURCES_LOADED = False


def normalize_driver(driver: str) -> str:
    """Map driver aliases to their canonical names.

    This function is idempotent: passing a canonical driver name returns
    the same name unchanged.

    Args:
        driver: Driver name or alias (case-insensitive).

    Returns:
        Canonical driver name.

    Examples:
        >>> normalize_driver("postgresql")
        'pg'
        >>> normalize_driver("pg")
        'pg'
        >>> normalize_driver("opensearch")
        'elastic'
    """
    d = driver.lower().strip()
    return _DRIVER_ALIASES.get(d, d)


def register_source(driver: str) -> Callable[[type], type]:
    """Decorator that registers a database source class in the registry.

    The ``driver`` parameter should be the **canonical** driver name
    (e.g., ``'pg'``, not ``'postgres'``). Aliases are resolved via
    ``normalize_driver()`` before lookup.

    Args:
        driver: Canonical driver name to register the source under.

    Returns:
        Class decorator that registers the source and returns the class unchanged.

    Example:
        >>> @register_source("pg")
        ... class PostgresSource(AbstractDatabaseSource):
        ...     driver = "pg"
    """
    def decorator(cls: type) -> type:
        _SOURCE_REGISTRY[driver] = cls
        return cls
    return decorator


def _ensure_sources_loaded() -> None:
    """Lazy-import all source modules to trigger their @register_source decorators.

    This avoids importing heavy database drivers at module startup.
    Called automatically by ``get_source_class()`` when a driver is not
    yet in the registry.
    """
    global _SOURCES_LOADED
    if _SOURCES_LOADED:
        return
    _SOURCES_LOADED = True

    # Import all source modules — the @register_source decorators fire on import
    _source_modules = [
        "parrot.tools.database.sources.postgres",
        "parrot.tools.database.sources.mysql",
        "parrot.tools.database.sources.sqlite",
        "parrot.tools.database.sources.bigquery",
        "parrot.tools.database.sources.oracle",
        "parrot.tools.database.sources.clickhouse",
        "parrot.tools.database.sources.duckdb",
        "parrot.tools.database.sources.mssql",
        "parrot.tools.database.sources.mongodb",
        "parrot.tools.database.sources.documentdb",
        "parrot.tools.database.sources.atlas",
        "parrot.tools.database.sources.influx",
        "parrot.tools.database.sources.elastic",
    ]
    import importlib

    for module_path in _source_modules:
        try:
            importlib.import_module(module_path)
        except ImportError:
            pass  # Optional sources may not be available


def get_source_class(driver: str) -> type[AbstractDatabaseSource]:
    """Look up a registered database source class by driver name.

    Resolves aliases via ``normalize_driver()`` before lookup.
    Lazily imports all source modules on first call.

    Args:
        driver: Driver name or alias (e.g., ``'pg'``, ``'postgresql'``).

    Returns:
        The registered ``AbstractDatabaseSource`` subclass.

    Raises:
        ValueError: If no source is registered for the given driver.
    """
    canonical = normalize_driver(driver)
    if canonical not in _SOURCE_REGISTRY:
        _ensure_sources_loaded()
        if canonical not in _SOURCE_REGISTRY:
            available = sorted(_SOURCE_REGISTRY.keys())
            raise ValueError(
                f"No DatabaseSource registered for driver '{driver}' "
                f"(canonical: '{canonical}'). "
                f"Available drivers: {available}"
            )
    return _SOURCE_REGISTRY[canonical]

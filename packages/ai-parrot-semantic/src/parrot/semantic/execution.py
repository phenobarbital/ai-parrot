"""Named-connection credential resolution and governed-SQL execution (spec §3 Module 9)."""
from __future__ import annotations

import logging
import os
import re
import time
from typing import Any, Mapping

from parrot.interfaces.database import get_default_credentials
from parrot.tools.databasequery.toolkit import DatabaseQueryToolkit

from .errors import SemanticExecutionError
from .models import GovernedQuery


class ConnectionResolver:
    """Resolve a named connection into a credentials dict from the environment only."""

    PREFIX = "PARROT_SEMANTIC_CONN_"

    def __init__(self, env: Mapping[str, str] | None = None) -> None:
        self.env = env if env is not None else os.environ

    def resolve(self, connection: str, driver: str) -> dict[str, Any]:
        """Defaults for `driver` overlaid with PARROT_SEMANTIC_CONN_<CONNECTION>_<KEY>.

        Args:
            connection: Named connection identifier.
            driver: Database driver name.

        Returns:
            The credentials dict.

        Raises:
            SemanticExecutionError: ``no_credentials`` when nothing resolves.
        """
        prefix = self.PREFIX + re.sub(r"[^A-Za-z0-9]", "_", connection).upper() + "_"
        creds: dict[str, Any] = dict(get_default_credentials(driver) or {})
        for key, value in self.env.items():
            if key.startswith(prefix) and len(key) > len(prefix):
                creds[key[len(prefix):].lower()] = value
        if not creds:
            raise SemanticExecutionError("no_credentials", "no credentials configured for connection")
        return creds


class Executor:
    """Run governed SQL through a DatabaseQueryToolkit source."""

    def __init__(self, toolkit: DatabaseQueryToolkit, resolver: ConnectionResolver) -> None:
        self.toolkit = toolkit
        self.resolver = resolver
        self.logger = logging.getLogger(__name__)

    async def run_with_columns(
        self, governed: GovernedQuery, *, connection: str
    ) -> tuple[list[dict], int, bool, int, list[str]]:
        """Execute and also return column names (kept even for empty results).

        Returns:
            (rows, row_count, truncated, duration_ms, columns).

        Raises:
            SemanticExecutionError: ``no_source``, ``no_credentials`` or ``execution_failed``.
        """
        try:
            source = self.toolkit.get_source(governed.driver)
        except Exception as exc:
            self.logger.warning("semantic source lookup failed: %s", type(exc).__name__)
            raise SemanticExecutionError("no_source", "unknown database driver") from exc
        creds = self.resolver.resolve(connection, governed.driver)
        t0 = time.perf_counter()
        try:
            result = await source.query(creds, governed.sql)
        except Exception as exc:
            self.logger.warning("semantic execution failed: %s", type(exc).__name__)
            raise SemanticExecutionError("execution_failed", "query execution failed") from exc
        duration_ms = int((time.perf_counter() - t0) * 1000)
        all_rows = list(result.rows or [])
        truncated = len(all_rows) > governed.limit
        rows = all_rows[: governed.limit]
        columns = list(result.columns or [])
        if not columns and rows:
            columns = list(rows[0].keys())
        return rows, len(rows), truncated, duration_ms, columns

    async def run(self, governed: GovernedQuery, *, connection: str) -> tuple[list[dict], int, bool, int]:
        """Returns (rows, row_count, truncated, duration_ms); DB errors -> SemanticExecutionError."""
        rows, row_count, truncated, duration_ms, _ = await self.run_with_columns(governed, connection=connection)
        return rows, row_count, truncated, duration_ms

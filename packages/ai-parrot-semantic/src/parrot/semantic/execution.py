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
    """Resolve database credentials from a named connection, never from tool arguments.

    Args:
        env: Optional environment mapping; defaults to ``os.environ``.
    """

    PREFIX = "PARROT_SEMANTIC_CONN_"

    def __init__(self, env: Mapping[str, str] | None = None) -> None:
        """Store the environment mapping used for overrides."""
        self.env = env if env is not None else os.environ

    def resolve(self, connection: str, driver: str) -> dict[str, Any]:
        """Defaults for `driver` overlaid with PARROT_SEMANTIC_CONN_<CONNECTION>_<KEY>.

        Args:
            connection: Connection name from the model policy.
            driver: Database driver name.

        Returns:
            Credentials dictionary.

        Raises:
            SemanticExecutionError: ``no_credentials`` when nothing resolves.
        """
        prefix = self.PREFIX + re.sub(r"[^A-Za-z0-9]", "_", connection).upper() + "_"
        creds: dict[str, Any] = dict(get_default_credentials(driver) or {})
        for name, value in self.env.items():
            if name.startswith(prefix) and len(name) > len(prefix):
                creds[name[len(prefix) :].lower()] = value
        if not creds:
            raise SemanticExecutionError("no_credentials", "no credentials available for the connection")
        return creds


class Executor:
    """Run governed SQL through a ``DatabaseQueryToolkit`` source."""

    def __init__(self, toolkit: DatabaseQueryToolkit, resolver: ConnectionResolver) -> None:
        """Bind the toolkit and credential resolver."""
        self.toolkit = toolkit
        self.resolver = resolver
        self.logger = logging.getLogger(__name__)

    async def run(self, governed: GovernedQuery, *, connection: str) -> tuple[list[dict], int, bool, int]:
        """Execute governed SQL.

        Args:
            governed: Governed query to execute.
            connection: Named connection used to resolve credentials.

        Returns:
            Tuple ``(rows, row_count, truncated, duration_ms)``.

        Raises:
            SemanticExecutionError: ``no_source``, ``no_credentials`` or ``execution_failed``
                (messages never contain SQL).
        """
        try:
            source = self.toolkit.get_source(governed.driver)
        except Exception as exc:
            self.logger.error("no source for driver (%s)", type(exc).__name__)
            raise SemanticExecutionError("no_source", "unknown database driver") from exc
        creds = self.resolver.resolve(connection, governed.driver)
        t0 = time.perf_counter()
        try:
            result = await source.query(creds, governed.sql)
        except Exception as exc:
            self.logger.error("governed query failed (%s)", type(exc).__name__)
            raise SemanticExecutionError("execution_failed", "query execution failed") from exc
        duration_ms = int((time.perf_counter() - t0) * 1000)
        rows = list(result.rows)
        row_count = result.row_count
        truncated = False
        if row_count > governed.limit or len(rows) > governed.limit:
            truncated = True
            rows = rows[: governed.limit]
            row_count = len(rows)
        return rows, row_count, truncated, duration_ms

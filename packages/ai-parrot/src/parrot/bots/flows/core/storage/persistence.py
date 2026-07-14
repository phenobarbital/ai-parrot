"""PersistenceMixin — pluggable persistence for crew/flow execution results (FEAT-147).

Replaces the former hard-wired DocumentDB persistence with a delegating
mixin that respects ``self._persist_results`` (opt-out) and lazily resolves
a ``ResultStorage`` backend on first write.

The host class is responsible for initialising four attributes in its
``__init__``:

    self._persist_results: bool                        # default True
    self._result_storage_arg: str | ResultStorage | None
    self._result_storage: Optional[ResultStorage]      # populated lazily
    self._persist_tasks: set[asyncio.Task]             # initialised to set()

All four are accessed via ``getattr`` with safe defaults so the mixin
remains backwards-compatible with host classes that have not yet been wired.

A host may additionally opt out of per-agent persistence only (FEAT-306)
via a fifth, optional attribute:

    self._persist_agent_results: bool                  # default True

Also accessed via ``getattr`` with a safe default of ``True``, so hosts
that have not been wired for per-agent persistence keep working unchanged.
"""
from __future__ import annotations

import asyncio
import time
from typing import Any, Optional

from navconfig.logging import logging

from .backends import ResultStorage, get_result_storage


class PersistenceMixin:
    """Pluggable persistence for crew/flow execution results.

    The mixin exposes three public async methods:
        - ``_save_result``    — fire-and-forget write (same public contract as before).
        - ``aclose``          — wait for in-flight tasks, release the backend.
        - ``__aenter__`` / ``__aexit__`` — async context-manager protocol.

    Attributes:
        (All owned by the host class — accessed via getattr.)
    """

    # ──────────────────────────────────────────────────────────────────────────
    # Internal helpers
    # ──────────────────────────────────────────────────────────────────────────

    def _ensure_result_storage(self) -> ResultStorage:
        """Lazily resolve and cache the ``ResultStorage`` instance.

        On first call the backend is instantiated via ``get_result_storage``
        using the value of ``self._result_storage_arg``. On subsequent calls
        the cached instance on ``self._result_storage`` is returned.

        Returns:
            A ready-to-use ``ResultStorage`` implementation.
        """
        storage: Optional[ResultStorage] = getattr(self, "_result_storage", None)
        if storage is None:
            storage = get_result_storage(getattr(self, "_result_storage_arg", None))
            self._result_storage = storage  # type: ignore[attr-defined]
        return storage

    # ──────────────────────────────────────────────────────────────────────────
    # Public API
    # ──────────────────────────────────────────────────────────────────────────

    async def _save_result(
        self,
        result: Any,
        method: str,
        *,
        collection: str = "crew_executions",
        **kwargs: Any,
    ) -> None:
        """Persist one crew/flow execution result to the configured backend.

        Returns immediately when ``self._persist_results`` is ``False`` —
        no backend is contacted and no log line is emitted.

        Args:
            result: The execution result.  ``result.to_dict()`` is used when
                available; otherwise ``str(result)`` is stored.
            method: Execution method name (e.g. ``"run_flow"``).
            collection: Target collection / table name.
            **kwargs: Extra fields merged into the persisted document
                (e.g. ``user_id``, ``session_id``, ``prompt``, ``tenant``).
        """
        if not getattr(self, "_persist_results", True):
            return

        logger = getattr(self, "logger", logging.getLogger(__name__))
        try:
            storage = self._ensure_result_storage()
            data: dict[str, Any] = {
                "crew_name": getattr(self, "name", "unknown"),
                "method": method,
                "timestamp": time.time(),
                "result": (
                    result.to_dict() if hasattr(result, "to_dict") else str(result)
                ),
                **kwargs,
            }
            data.setdefault("user_id", "unknown")
            data.setdefault("tenant", "global")
            # prompt comes from kwargs if caller provides it; no default needed (None is fine)
            await storage.save(collection, data)
        except Exception as exc:
            logger.warning(
                "Failed to save result to '%s': %s",
                collection,
                exc,
            )

    async def _save_agent_result(
        self,
        node_result: Any,
        *,
        execution_id: str,
        method: str,
        collection: str = "crew_agent_results",
        **kwargs: Any,
    ) -> None:
        """Persist one agent's execution result incrementally.

        Sibling to ``_save_result`` — writes one document per finished
        agent to a dedicated collection, linked to the crew-level run by
        ``execution_id``. Returns immediately when either
        ``self._persist_results`` or ``self._persist_agent_results`` is
        ``False`` — no backend is contacted and no log line is emitted.

        Args:
            node_result: The per-agent execution record. ``node_result.to_dict()``
                is used when available; otherwise ``str(node_result)`` is stored.
            execution_id: Crew-level execution id linking this document to the
                consolidated ``crew_executions`` record.
            method: Execution method name (e.g. ``"run_sequential"``).
            collection: Target collection / table name.
            **kwargs: Extra fields merged into the persisted document
                (e.g. ``user_id``, ``session_id``).
        """
        if not getattr(self, "_persist_results", True):
            return
        if not getattr(self, "_persist_agent_results", True):
            return

        logger = getattr(self, "logger", logging.getLogger(__name__))
        try:
            storage = self._ensure_result_storage()
            data: dict[str, Any] = {
                "execution_id": execution_id,
                "crew_name": getattr(self, "name", "unknown"),
                "method": method,
                "node_id": (
                    getattr(node_result, "node_id", None)
                    or getattr(node_result, "agent_id", "unknown")
                ),
                "node_execution_id": getattr(node_result, "execution_id", None),
                "timestamp": time.time(),
                "result": (
                    node_result.to_dict()
                    if hasattr(node_result, "to_dict")
                    else str(node_result)
                ),
                **kwargs,
            }
            data.setdefault("user_id", "unknown")
            await storage.save(collection, data)
        except Exception as exc:
            logger.warning(
                "Failed to save agent result to '%s': %s",
                collection,
                exc,
            )

    async def aclose(self) -> None:
        """Wait for all in-flight persist tasks, then release the storage backend.

        Idempotent: safe to call multiple times and safe to call before any
        ``_save_result`` has been scheduled (no-op in that case).

        The method awaits every task in ``self._persist_tasks`` with
        ``return_exceptions=True`` so a failing background save does not
        block the close sequence.
        """
        logger = getattr(self, "logger", logging.getLogger(__name__))

        pending: set[asyncio.Task] = getattr(self, "_persist_tasks", set())  # type: ignore[type-arg]
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
            pending.clear()

        storage: Optional[ResultStorage] = getattr(self, "_result_storage", None)
        if storage is not None:
            try:
                await storage.close()
            except Exception as exc:
                logger.warning("Failed to close result storage: %s", exc)
            finally:
                self._result_storage = None  # type: ignore[attr-defined]

    async def __aenter__(self) -> "PersistenceMixin":
        """Enter the async context manager — returns self."""
        return self

    async def __aexit__(
        self,
        exc_type: Any,
        exc_val: Any,
        exc_tb: Any,
    ) -> None:
        """Exit the async context manager — delegates to ``aclose()``."""
        await self.aclose()

"""InstrumentedBackend — transparent ConversationBackend wrapper.

Wraps any ``ConversationBackend`` and records per-method latency and errors
via a ``StorageMetrics`` instance. Zero overhead when ``PARROT_STORAGE_METRICS``
is unset (the factory returns the raw backend in that case).

FEAT-116: dynamodb-fallback-redis — Module 8 (observability hooks).
"""

import time
from typing import List, Optional

from parrot.storage.backends.base import ConversationBackend
from parrot.storage.metrics import StorageMetrics, NoopStorageMetrics


class InstrumentedBackend(ConversationBackend):
    """Wraps any ConversationBackend and records per-method latency + errors.

    The wrapper delegates every abstract method to the inner backend while
    timing the call and reporting to the configured ``StorageMetrics`` instance.

    ``is_connected`` and ``build_overflow_prefix`` pass through without timing
    since they are synchronous and zero-cost.

    Args:
        inner: Any ``ConversationBackend`` implementation.
        metrics: Optional ``StorageMetrics`` instance. Defaults to no-op.
    """

    def __init__(
        self,
        inner: ConversationBackend,
        metrics: Optional[StorageMetrics] = None,
    ) -> None:
        self._inner = inner
        self._metrics = metrics or NoopStorageMetrics()
        self._name = type(inner).__name__

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def initialize(self) -> None:
        await self._measure("initialize", self._inner.initialize)

    async def close(self) -> None:
        await self._measure("close", self._inner.close)

    @property
    def is_connected(self) -> bool:
        return self._inner.is_connected

    def build_overflow_prefix(
        self,
        user_id: str,
        agent_id: str,
        session_id: str,
        artifact_id: str,
    ) -> str:
        return self._inner.build_overflow_prefix(user_id, agent_id, session_id, artifact_id)

    # ------------------------------------------------------------------
    # Threads
    # ------------------------------------------------------------------

    async def put_thread(self, *a, **kw) -> None:
        return await self._measure("put_thread", self._inner.put_thread, *a, **kw)

    async def update_thread(self, *a, **kw) -> None:
        return await self._measure("update_thread", self._inner.update_thread, *a, **kw)

    async def query_threads(self, *a, **kw) -> List[dict]:
        return await self._measure("query_threads", self._inner.query_threads, *a, **kw)

    # ------------------------------------------------------------------
    # Turns
    # ------------------------------------------------------------------

    async def put_turn(self, *a, **kw) -> None:
        return await self._measure("put_turn", self._inner.put_turn, *a, **kw)

    async def query_turns(self, *a, **kw) -> List[dict]:
        return await self._measure("query_turns", self._inner.query_turns, *a, **kw)

    async def delete_turn(self, *a, **kw) -> bool:
        return await self._measure("delete_turn", self._inner.delete_turn, *a, **kw)

    async def delete_thread_cascade(self, *a, **kw) -> int:
        return await self._measure(
            "delete_thread_cascade", self._inner.delete_thread_cascade, *a, **kw
        )

    # ------------------------------------------------------------------
    # Artifacts
    # ------------------------------------------------------------------

    async def put_artifact(self, *a, **kw) -> None:
        return await self._measure("put_artifact", self._inner.put_artifact, *a, **kw)

    async def get_artifact(self, *a, **kw) -> Optional[dict]:
        return await self._measure("get_artifact", self._inner.get_artifact, *a, **kw)

    async def query_artifacts(self, *a, **kw) -> List[dict]:
        return await self._measure(
            "query_artifacts", self._inner.query_artifacts, *a, **kw
        )

    async def delete_artifact(self, *a, **kw) -> None:
        return await self._measure(
            "delete_artifact", self._inner.delete_artifact, *a, **kw
        )

    async def delete_session_artifacts(self, *a, **kw) -> int:
        return await self._measure(
            "delete_session_artifacts", self._inner.delete_session_artifacts, *a, **kw
        )

    # ------------------------------------------------------------------
    # Internal measurement helper
    # ------------------------------------------------------------------

    async def _measure(self, method: str, fn, *a, **kw):
        """Invoke *fn* with timing and error recording."""
        t0 = time.perf_counter()
        try:
            return await fn(*a, **kw)
        except Exception as exc:
            self._metrics.record_error(self._name, method, type(exc).__name__)
            raise
        finally:
            duration_ms = (time.perf_counter() - t0) * 1000.0
            self._metrics.record_latency(self._name, method, duration_ms)

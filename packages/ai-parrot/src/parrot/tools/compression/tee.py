"""Compression tee — the working-memory escape hatch (spec Sec 3 Module 3, G3).

No unrecoverable loss: anything lossy-compressed must be recoverable by the
agent without re-running the tool. :class:`CompressionTee` persists the full
pre-compression payload into the session's ``WorkingMemoryToolkit`` and
:func:`attach_tee_pointer` appends a ``_tee`` pointer block to the compressed
result so the LLM can call ``wm_get_result`` to recover it.

Consumer relationship only: this module never modifies
``WorkingMemoryToolkit``'s public API, and never constructs one — the caller
(``ToolManager``) locates an already-registered instance.

Provenance and honest failure (FEAT-538)
----------------------------------------

The tee writes *after* the manager's dispatch has finished — the
compression stage runs past the observed execution boundary, so the
per-invocation context has already been reset by the time
:meth:`CompressionTee.store` runs. With task memory enabled the producing
attempt is therefore read from the explicitly retained producer
(:meth:`TurnTaskSession.retained_producer`), or supplied by the caller;
when neither exists the answer is ``None`` and the legacy write runs
unchanged rather than a producer being invented.

The failure rule is unchanged and now stricter about what it claims: a
tee that could not persist still returns ``None`` (the caller must fall
back to the uncompressed payload), attaches **no** artifact receipt, and
marks the producing attempt's tracking as degraded. A failed tee is never
evidence, and never durable.
"""

from __future__ import annotations

import logging
import uuid
from collections import deque
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from ..working_memory import WorkingMemoryToolkit

logger = logging.getLogger(__name__)

#: Cached ``(context, models)`` task-memory modules, ``False`` when the
#: optional package is unavailable, ``None`` before the first lookup.
_TASK_MEMORY: Any = None


def _task_memory() -> Any:
    """Return the task-memory ``(context, models)`` modules, or ``False``.

    Task memory is opt-in: a deployment without it must not pay this
    import at module load, and must keep working when the package is
    absent entirely.

    Returns:
        A ``(context, models)`` tuple, or ``False`` when unavailable.
    """
    global _TASK_MEMORY  # noqa: PLW0603 - module-level import cache
    if _TASK_MEMORY is None:
        try:
            from ..working_memory.task_memory import context as tm_context  # noqa: PLC0415
            from ..working_memory.task_memory import models as tm_models  # noqa: PLC0415
        except Exception:  # noqa: BLE001 - absence is a supported configuration
            _TASK_MEMORY = False
        else:
            _TASK_MEMORY = (tm_context, tm_models)
    return _TASK_MEMORY


def _current_session() -> Any:
    """Return the turn session bound to this context, if any.

    Returns:
        The ``TurnTaskSession``, or ``None`` when task memory is disabled,
        absent, or no turn is open.
    """
    modules = _task_memory()
    return None if modules is False else modules[0].current_session()


def _ambient_producer() -> Optional[str]:
    """Return the retained (or current) producing call id, if any.

    Returns:
        The call id an artifact stored *now* belongs to, or ``None``.
        ``None`` is truthful and is never replaced with a guess.
    """
    modules = _task_memory()
    return None if modules is False else modules[0].producer_call_id()


class CompressionTee:
    """Working-memory escape hatch for lossy/failed tool results.

    Note on ``turn_id``: ``ToolManager`` has no conversational-turn concept
    today (verified — no ``turn_id`` attribute or parameter anywhere in
    ``manager.py``). This class therefore uses a stable per-instance
    identifier (generated once, at construction) as the ``turn_id``
    component of the tee key — stable because one ``CompressionTee`` is
    constructed per ``ToolManager`` (one per user session after
    ``clone()``), which is the closest available proxy for "this session's
    turn". Retention correspondingly tracks the last N tee ENTRIES rather
    than N conversational turns, since no turn boundary signal exists to
    key eviction on. Documented deviation — see TASK-1953 Completion Note.
    """

    def __init__(
        self,
        working_memory: Optional["WorkingMemoryToolkit"] = None,
        *,
        max_retained: int = 200,
    ) -> None:
        """Initialize the tee.

        Args:
            working_memory: An already-registered ``WorkingMemoryToolkit``
                instance, or ``None`` if the session has none (tee
                disabled, see :attr:`available`).
            max_retained: Maximum number of tee entries kept before the
                oldest is evicted via ``drop_stored()``.
        """
        self._wm = working_memory
        self._session_turn_id = uuid.uuid4().hex[:8]
        self._counters: dict[str, int] = {}
        self._retained: deque[str] = deque()
        self._max_retained = max_retained
        self.logger = logging.getLogger(__name__)

    @property
    def available(self) -> bool:
        """``True`` when a ``WorkingMemoryToolkit`` is registered."""
        return self._wm is not None

    def bind_working_memory(
        self,
        working_memory: Optional["WorkingMemoryToolkit"],
    ) -> None:
        """(Re)bind the ``WorkingMemoryToolkit`` instance backing this tee.

        ``ToolManager`` resolves this lazily, since tools/toolkits are
        typically registered AFTER the manager (and its ``CompressionTee``)
        is constructed — a ``WorkingMemoryToolkit`` registered mid-session
        makes the tee available from that point on.

        Args:
            working_memory: The current ``WorkingMemoryToolkit`` instance,
                or ``None`` if none is registered.
        """
        self._wm = working_memory

    def _turn_id(self) -> str:
        return self._session_turn_id

    def _next_counter(self, tool_name: str) -> int:
        """Per-``tool_name`` monotonically increasing counter — defends
        against ``WorkingMemoryCatalog.put_generic()``'s silent overwrite
        on key collision (verified: it does not raise)."""
        n = self._counters.get(tool_name, 0) + 1
        self._counters[tool_name] = n
        return n

    async def store(
        self,
        tool_name: str,
        payload: Any,
        reason: str,
        *,
        producer_call_id: Optional[str] = None,
    ) -> Optional[str]:
        """Persist the full ``payload`` to working memory.

        Never raises: a failing tee must never break a tool call. On
        failure (including "unavailable"), logs a warning (when
        applicable) and returns ``None`` — callers must then fall back to
        returning the original, uncompressed payload (losing data because
        the escape hatch failed is exactly what G3 forbids).

        With task memory enabled the write is versioned and attributed to
        the producing attempt, and the resulting ``artifact_id@version`` is
        attached to that attempt's receipt. A failure attaches nothing and
        marks the attempt's tracking degraded instead: a tee that did not
        persist is not evidence that it did.

        Args:
            tool_name: Name of the tool whose result is being teed.
            payload: The FULL, pre-compression payload to persist.
            reason: Why this payload is being teed (e.g. ``"lossy"``,
                ``"error"``) — stored in the entry's metadata and echoed in
                the ``_tee`` pointer block.
            producer_call_id: The attempt this payload came from. Defaults
                to the retained producer, which is how the correlation
                survives the manager's post-dispatch context reset.

        Returns:
            The tee key on success, ``None`` if unavailable or the store
            failed.
        """
        if not self.available:
            return None
        key = f"__tee__:{tool_name}:{self._turn_id()}:{self._next_counter(tool_name)}"
        session = _current_session()
        producer = producer_call_id if producer_call_id is not None else _ambient_producer()
        try:
            if session is not None and producer is not None and self._enabled_catalog() is not None:
                await self._store_versioned(session, key, tool_name, payload, reason, producer)
            else:
                await self._wm.store_result(
                    key=key,
                    data=payload,
                    data_type="auto",
                    description=f"Full pre-compression payload for {tool_name} ({reason})",
                    metadata={"tee": True, "reason": reason, "tool": tool_name},
                    turn_id=self._turn_id(),
                )
        except Exception as exc:  # noqa: BLE001 — a broken tee must never break a tool call
            self.logger.warning("Tee failed for %s: %s", tool_name, exc)
            self._mark_degraded(session, producer)
            return None
        await self._retain(key)
        return key

    def _enabled_catalog(self) -> Any:
        """Return the working memory's catalog when task memory is enabled.

        Returns:
            The catalog with a versioned artifact-store backend attached,
            or ``None`` — which keeps the legacy write path in force.
        """
        catalog = getattr(self._wm, "_catalog", None)
        return catalog if getattr(catalog, "is_enabled", False) else None

    async def _store_versioned(
        self,
        session: Any,
        key: str,
        tool_name: str,
        payload: Any,
        reason: str,
        producer: str,
    ) -> None:
        """Register the teed payload as an exact version of its producer.

        Args:
            session: The live turn session.
            key: The tee alias.
            tool_name: The tool whose result is being teed.
            payload: The full pre-compression payload.
            reason: Why it was teed.
            producer: The producing attempt's call id.

        Raises:
            Exception: Whatever the catalog raised. :meth:`store` owns the
                failure policy; persisting is not allowed to fail quietly
                here and then be reported as a success.
        """
        catalog = self._enabled_catalog()
        receipt = session.receipt(producer)
        entry = await catalog.aput_generic(
            key,
            payload,
            description=f"Full pre-compression payload for {tool_name} ({reason})",
            metadata={"tee": True, "reason": reason, "tool": tool_name},
            turn_id=self._turn_id(),
            producer_call_id=producer,
            attribution=None if receipt is None else receipt.context.attribution,
        )
        version = getattr(entry, "version_metadata", None)
        if version is None:  # pragma: no cover - an enabled write always versions
            self._mark_degraded(session, producer)
            return
        evidence_ref = _task_memory()[1].EvidenceRef(artifact_id=version.artifact_id, version=version.version)
        if not session.add_artifact_receipt(producer, evidence_ref):
            self._mark_degraded(session, producer)

    def _mark_degraded(self, session: Any, producer: Optional[str]) -> None:
        """Record that this tee write's tracking is degraded.

        Mirrors what ``complete_invocation`` does with the same flag: a
        gap we could not close is still a gap, and marking it is the only
        honest alternative to silently returning ``None`` and letting the
        attempt read as fully tracked.

        Args:
            session: The live turn session, or ``None``.
            producer: The producing attempt's call id, or ``None``.
        """
        if session is None or producer is None:
            return
        receipt = session.receipt(producer)
        if receipt is not None:
            receipt.degraded = True

    async def _retain(self, key: str) -> None:
        """Track ``key`` for turn-based retention; evict the oldest entry
        past ``max_retained`` via ``drop_stored()``."""
        self._retained.append(key)
        while len(self._retained) > self._max_retained:
            evicted = self._retained.popleft()
            try:
                await self._wm.drop_stored(evicted)
            except Exception as exc:  # noqa: BLE001 — eviction must never raise
                self.logger.warning(
                    "Failed to evict tee entry %s: %s",
                    evicted,
                    exc,
                )

    async def cleanup(self) -> None:
        """Drop every retained tee entry — call on session cleanup."""
        if not self.available:
            self._retained.clear()
            return
        while self._retained:
            key = self._retained.popleft()
            try:
                await self._wm.drop_stored(key)
            except Exception as exc:  # noqa: BLE001 — cleanup must never raise
                self.logger.warning(
                    "Failed to drop tee entry %s during cleanup: %s",
                    key,
                    exc,
                )


def attach_tee_pointer(payload: Any, key: str, reason: str) -> Any:
    """Append the ``_tee`` recovery pointer block to ``payload`` (spec Sec 2).

    Args:
        payload: The compressed payload to annotate.
        key: The tee key returned by :meth:`CompressionTee.store`.
        reason: Why the payload was teed (``"lossy"`` or ``"error"``).

    Returns:
        ``payload`` with a ``_tee`` block appended. Dict payloads gain the
        key directly; non-dict payloads are wrapped as
        ``{"result": payload, "_tee": {...}}`` so the pointer is always
        reachable without silently discarding a non-dict result.
    """
    pointer = {
        "key": key,
        "reason": reason,
        "hint": "use wm_get_result for the full payload",
    }
    if isinstance(payload, dict):
        return {**payload, "_tee": pointer}
    return {"result": payload, "_tee": pointer}

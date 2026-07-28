"""``CompressionStage`` — the pure, independently testable core of the
tool-result compression pipeline (spec Sec 3 Module 2).

Given a tool name, its unwrapped result payload, execution status, and
metadata, decides whether to compress, with which codec, at which
:class:`~parrot.tools.compression.levels.FilterLevel`, on which
:class:`~parrot.tools.compression.budget.Route` — and returns the
(possibly compressed) payload plus a compression-metadata dict.

Deliberately decoupled from ``ToolManager``: this module does not import or
touch ``parrot.tools.manager``. Wiring this stage into
``ToolManager.execute_tool()`` is TASK-1952's job.
"""
import asyncio
import inspect
import logging
import os
import time
from functools import partial
from typing import Any, Callable, Optional, Union

from .budget import BudgetRouter, Route, is_rust_available
from .levels import FilterLevel, cap
from .protocol import CompressionOutcome, get_codec
from .registry import CompressorRegistry
from .tee import CompressionTee, attach_tee_pointer

logger = logging.getLogger(__name__)

# Injected tee collaborator: normally a real `CompressionTee` (TASK-1953),
# which exposes `.available` (used to cap NORMAL/AGGRESSIVE to MINIMAL when
# no working memory is registered, per G3) and an async `.store(tool_name,
# payload, reason) -> str | None`. For backward compatibility (and to keep
# unit tests decoupled from `WorkingMemoryToolkit`), a bare callable with the
# legacy `(tool_name, payload, codec_name) -> str | None` shape (sync or
# async) is also accepted — it is always treated as "available" since it
# cannot be introspected for that.
TeeCallback = Callable[[str, Any, str], Optional[str]]
TeeLike = Union[CompressionTee, TeeCallback]


class CompressionStage:
    """Decides whether/how to compress a tool result, and dispatches to a
    codec via the latency-budget router.

    Never raises: every failure path (unknown codec, codec exception,
    budget passthrough) returns the ORIGINAL payload unchanged plus a
    ``compression_skipped`` reason in the metadata dict. A broken codec can
    never break a tool call.
    """

    def __init__(
        self,
        registry: CompressorRegistry,
        router: BudgetRouter,
        tee: Optional[TeeLike] = None,
        *,
        rust_available: Optional[bool] = None,
    ) -> None:
        """Initialize the stage.

        Args:
            registry: Loaded, immutable :class:`CompressorRegistry`.
            router: :class:`BudgetRouter` deciding inline/executor/passthrough.
            tee: Optional :class:`~parrot.tools.compression.tee.CompressionTee`
                (or legacy bare callable, see :data:`TeeLike`) invoked when a
                codec reports ``lossy=True``, to persist the original payload
                to working memory. ``None`` → tee disabled: lossy levels
                (``NORMAL``/``AGGRESSIVE``) are capped to ``MINIMAL`` (G3 —
                never lossy without recovery); a bare callable is always
                treated as available (it cannot be introspected).
            rust_available: Override for Rust-extension detection (mainly
                for tests). Defaults to
                :func:`~parrot.tools.compression.budget.is_rust_available`.
        """
        self._registry = registry
        self._router = router
        self._tee = tee
        self._rust_available = (
            is_rust_available() if rust_available is None else rust_available
        )
        self.logger = logging.getLogger(__name__)

    def _tee_available(self) -> bool:
        """Whether the tee escape hatch can currently persist a payload.

        A :class:`CompressionTee` reports this via its ``available``
        property (``False`` when no ``WorkingMemoryToolkit`` is
        registered). A bare legacy callable cannot be introspected, so it
        is always treated as available.
        """
        if self._tee is None:
            return False
        return bool(getattr(self._tee, "available", True))

    async def _invoke_tee(
        self, tool_name: str, payload: Any, reason: str, codec_name: str,
    ) -> Optional[str]:
        """Invoke the configured tee collaborator, sync- or async-safe.

        Prefers the real :class:`CompressionTee` API
        (``store(tool_name, payload, reason)``) when available; falls back
        to the legacy positional ``(tool_name, payload, codec_name)`` shape
        for a bare callable, awaiting the result only if it is awaitable.
        """
        if self._tee is None:
            return None
        store = getattr(self._tee, "store", None)
        if store is not None:
            result = store(tool_name, payload, reason)
        else:
            result = self._tee(tool_name, payload, codec_name)
        if inspect.isawaitable(result):
            return await result
        return result

    async def run(
        self,
        tool_name: str,
        payload: Any,
        *,
        status: str,
        metadata: dict[str, Any],
        return_direct: bool,
        level_override: Optional[FilterLevel] = None,
    ) -> tuple[Any, dict[str, Any]]:
        """Run the compression pipeline for a single tool result.

        Args:
            tool_name: Name of the tool that produced ``payload``.
            payload: The UNWRAPPED tool result (never a ``ToolResult``).
            status: The tool call's status (e.g. ``"success"``, ``"error"``).
                Anything other than ``"success"`` forces
                :attr:`FilterLevel.NONE` (G5).
            metadata: The result's existing metadata dict. Read-only here —
                this method never mutates it in place; the caller merges the
                returned metadata.
            return_direct: When ``True``, the pipeline is skipped entirely
                (tee included) — the tool author's verbatim output must not
                be altered.
            level_override: Optional per-call override, highest precedence.

        Returns:
            A ``(payload, compression_metadata)`` tuple. ``payload`` is the
            original object, unchanged, on every skip/error path; it is the
            codec's compressed output on the happy path.
        """
        if os.getenv("PARROT_COMPRESSION_DISABLED") == "1":
            return payload, {"compression_skipped": "kill_switch"}
        if return_direct:
            return payload, {"compression_skipped": "return_direct"}
        if metadata.get("_compressed"):
            return payload, {"compression_skipped": "already_compressed"}

        level = self._effective_level(tool_name, status, level_override)
        if level is FilterLevel.NONE:
            return payload, {"compression_skipped": "level_none"}

        entry = self._registry.resolve(tool_name)
        codec_name = entry.codec if entry is not None else "json_compact"
        params = entry.params if entry is not None else {}

        codec_cls = get_codec(codec_name)
        if codec_cls is None:
            self.logger.warning(
                "No codec registered for '%s' (tool '%s'); passthrough.",
                codec_name, tool_name,
            )
            return payload, {"compression_skipped": "unknown_codec"}
        codec = codec_cls()

        started = time.perf_counter()
        route: Route = Route.PASSTHROUGH
        outcome: Optional[CompressionOutcome] = None
        try:
            route = self._router.route(
                payload, level=level, codec_name=codec_name,
                rust_available=self._rust_available,
            )
            if route is Route.PASSTHROUGH:
                return payload, {"compression_skipped": "budget_passthrough"}
            if route is Route.INLINE:
                outcome = codec.compress(payload, level=level, params=params)
            else:
                loop = asyncio.get_running_loop()
                outcome = await loop.run_in_executor(
                    None,
                    partial(codec.compress, payload, level=level, params=params),
                )
        except Exception as exc:  # noqa: BLE001 — a broken codec must never break a tool call
            self.logger.warning(
                "Compressor '%s' failed for tool '%s': %s", codec_name, tool_name, exc,
            )
            return payload, {"compression_skipped": "codec_error"}
        finally:
            duration_ms = (time.perf_counter() - started) * 1000
            self._router.record(codec_name, duration_ms, route)

        teed_key: Optional[str] = None
        if outcome.lossy:
            teed_key = await self._invoke_tee(tool_name, payload, "lossy", codec_name)

        final_payload = outcome.payload
        if teed_key is not None:
            final_payload = attach_tee_pointer(final_payload, teed_key, "lossy")

        result_metadata: dict[str, Any] = {
            "_compressed": True,
            "compression_codec": codec_name,
            "compression_level": level.value,
            "result_size_bytes_original": outcome.bytes_before,
            "result_size_bytes": outcome.bytes_after,
            "compression_duration_ms": duration_ms,
            "compression_teed": teed_key is not None,
        }
        if teed_key is not None:
            result_metadata["compression_tee_key"] = teed_key
        return final_payload, result_metadata

    def _effective_level(
        self,
        tool_name: str,
        status: str,
        level_override: Optional[FilterLevel],
    ) -> FilterLevel:
        """Resolve the effective :class:`FilterLevel` per spec Sec 2
        precedence (highest wins):

        1. per-call override (``level_override``)
        2. ``status != "success"`` forces :attr:`FilterLevel.NONE` (G5)
        3. exact/glob ``tool_name`` entry in the registry
        4. the registry's global (``"*"``) configured default
        5. :attr:`FilterLevel.MINIMAL` when nothing is configured (G2)

        Rules 3 and 4 are both served by
        :meth:`CompressorRegistry.resolve`, which already implements
        exact > glob > ``"*"`` match precedence; rule 5 is the defensive
        fallback for a registry with no entries at all.

        Finally (G3): a resolved ``NORMAL``/``AGGRESSIVE`` level is capped
        to ``MINIMAL`` when the tee escape hatch is unavailable — a lossy
        compression with no way to recover the original is exactly what G3
        forbids. ``NONE``/``MINIMAL`` are lossless and never capped.
        """
        if level_override is not None:
            level = level_override
        elif status != "success":
            level = FilterLevel.NONE
        else:
            entry = self._registry.resolve(tool_name)
            level = entry.level if entry is not None else FilterLevel.MINIMAL

        if level in (FilterLevel.NORMAL, FilterLevel.AGGRESSIVE) and not self._tee_available():
            level = cap(level, FilterLevel.MINIMAL)
        return level

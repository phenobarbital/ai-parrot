"""Hash-verified definition and reference navigation tools (FEAT-580, M3).

:class:`LSPToolkit` is the agent-facing surface of the LSP research pilot.
This module implements only the two "fully implemented navigation methods"
scoped to this task — ``lsp_definition`` and ``lsp_references``. The
checkpoint-diagnostics public methods (``lsp_diagnostics`` /
``lsp_diagnostic_delta``) and their baseline storage are a later task and
are deliberately absent here.

Construction never spawns a process, opens a file, or probes an
executable — :meth:`LSPToolkit.__init__` only validates the trusted
:class:`~parrot_tools.lsp.models.LSPConfig`. Every semantic call:

1. Special-cases the ``environment_id="operator-unconfigured"`` sentinel
   before touching anything else.
2. Validates the request shape via :class:`~parrot_tools.lsp.models.SourcePosition`.
3. Captures a bounded "before" workspace snapshot
   (:func:`parrot_tools.lsp.snapshot.capture_workspace`), verifies the
   caller's ``expected_sha256`` against the exact on-disk content, and
   restarts the owned :class:`~parrot_tools.lsp.session.PyrightSession`
   whenever the workspace/config digest has changed since it was last
   started.
4. Issues the allowlisted request, normalizes ``Location``/``LocationLink``
   results into bounded, confined :class:`~parrot_tools.lsp.models.LSPLocation`
   entries (dropping anything outside ``repo_root`` or not Python
   source/stub, with an explicit omission count).
5. Captures an "after" snapshot; a changed digest discards the response as
   ``workspace_changed`` rather than serving stale cross-file evidence.

Every :class:`~parrot_tools.lsp.models.LSPFailure` raised by the
snapshot/session layers is converted into a typed
:class:`~parrot_tools.lsp.models.LSPResult` here — nothing escapes a public
method as a raw exception except ``asyncio.CancelledError``, which is
always propagated after the per-instance operation lock has been
released (via the enclosing ``async with``/``finally`` blocks).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

from pydantic import ValidationError

from parrot.tools.toolkit import AbstractToolkit

from .models import (
    OPERATOR_UNCONFIGURED_ENVIRONMENT_ID,
    EvidenceMeta,
    LSPConfig,
    LSPFailure,
    LSPLocation,
    LSPResult,
    SourcePosition,
    SourceState,
)
from .session import PyrightSession
from .snapshot import capture_workspace, from_lsp_range, to_lsp_position

__all__ = ["LSPToolkit"]

#: Total call deadline (spec §2.10 "Bounds"): includes startup/checks/cleanup.
#: Fixed pilot constant, not configurable via :class:`LSPConfig`.
_TOTAL_CALL_DEADLINE_S = 90.0

#: Rendered-item cap shared by both navigation tools (spec §2.10 "Bounds":
#: "200 rendered items"). ``lsp_references`` additionally clamps its own
#: 1-200 ``limit`` argument to this same ceiling.
_MAX_RENDERED_ITEMS = 200

#: JSON result byte cap (spec §2.10 "Bounds": "JSON result 32 KiB").
_MAX_RESULT_BYTES = 32 * 1024

#: Supported source suffixes for a normalized target location.
_SOURCE_SUFFIXES = frozenset({".py", ".pyi"})

#: Operational codes that indicate the *server*/environment is unavailable
#: rather than a request-specific error — mapped to ``status="unavailable"``.
_UNAVAILABLE_CODES: frozenset[str] = frozenset(
    {"server_missing", "server_version_mismatch", "startup_timeout", "server_crashed"}
)

#: Deterministic fallback text: recommends existing discovery tools without
#: auto-invoking them (spec §2 "New Public Interfaces").
_FALLBACK_MESSAGE = (
    "LSP evidence is unavailable for this request. Fall back to wiki/AST symbol "
    "search or inspect the source directly; do not retry this operation automatically."
)


def _path_to_file_uri(path: Path) -> str:
    """Return a ``file://`` URI for an absolute filesystem path."""
    return "file://" + urllib.parse.quote(path.as_posix())


class LSPToolkit(AbstractToolkit):
    """Optional Python semantic evidence for saved worktree files.

    Owns exactly one lazy :class:`~parrot_tools.lsp.session.PyrightSession`,
    bound permanently to one canonical ``repo_root``. ``auto_open=False``:
    each public method validates input first, then acquires the session
    itself so server errors return in the typed :class:`LSPResult` envelope
    instead of escaping the framework's ``_ensure_open()`` pre-method hook.
    """

    auto_open = False
    tool_prefix = ""

    def __init__(self, config: LSPConfig | dict[str, Any], **kwargs: Any) -> None:
        """Validate trusted settings without spawning a server or reading source.

        Args:
            config: A trusted, already-validated :class:`LSPConfig`, or a
                plain mapping of the same fields (constructed here — this
                still performs pure, in-memory validation only).
            **kwargs: Forwarded to :class:`AbstractToolkit`.
        """
        super().__init__(**kwargs)
        self._config: LSPConfig = config if isinstance(config, LSPConfig) else LSPConfig(**config)

        # Stable per-instance identity, derived by pure string hashing (no I/O).
        self._workspace_id = hashlib.sha256(str(self._config.repo_root).encode("utf-8")).hexdigest()
        # Resolved lazily on first real operation (symlink resolution touches
        # the filesystem, which construction must never do).
        self._canonical_root: Path | None = None

        # One in-flight semantic operation per instance (spec §2 session contract).
        self._operation_lock: asyncio.Lock = asyncio.Lock()

        # Owned session + the workspace/config digest it was last started under.
        self._session: PyrightSession | None = None
        self._session_digest: str | None = None
        self._session_config_digest: str | None = None
        self._session_generation: int = 0
        self._last_cold_start: bool = False

        # Idle-shutdown timer (spec §2.10 "Bounds": 120s default idle timeout).
        self._idle_task: "asyncio.Task[None] | None" = None

    # ------------------------------------------------------------------
    # Public tools
    # ------------------------------------------------------------------

    async def lsp_definition(self, path: str, line: int, column: int, expected_sha256: str) -> LSPResult:
        """Resolve a verified expression; return bounded locations or an explicit failure."""
        return await self._navigate(
            operation="lsp_definition",
            lsp_method="textDocument/definition",
            path=path,
            line=line,
            column=column,
            expected_sha256=expected_sha256,
            extra_params=None,
            limit=_MAX_RENDERED_ITEMS,
        )

    async def lsp_references(
        self,
        path: str,
        line: int,
        column: int,
        expected_sha256: str,
        include_declaration: bool = False,
        limit: int = 50,
    ) -> LSPResult:
        """Find static references; limit is 1-200 and truncation is explicit."""
        if isinstance(limit, bool) or not isinstance(limit, int) or not (1 <= limit <= 200):
            return LSPResult(
                status="error",
                operation="lsp_references",
                code="invalid_request",
                message=f"limit must be an integer between 1 and 200, got {limit!r}",
                fallback=_FALLBACK_MESSAGE,
            )
        return await self._navigate(
            operation="lsp_references",
            lsp_method="textDocument/references",
            path=path,
            line=line,
            column=column,
            expected_sha256=expected_sha256,
            extra_params={"context": {"includeDeclaration": bool(include_declaration)}},
            limit=limit,
        )

    # ------------------------------------------------------------------
    # Lifecycle hooks (private; never exposed as tools)
    # ------------------------------------------------------------------

    async def _open(self) -> None:
        """Establish ownership only; the Pyright process starts lazily per call."""
        return

    async def _close(self) -> None:
        """Idempotently close any owned session and cancel the idle timer.

        Serializes against in-flight calls via the operation lock, then
        always resets ``_opened`` through ``super()._close()`` — even if
        closing the session itself raised.
        """
        try:
            async with self._operation_lock:
                await self._close_session_locked()
        finally:
            await super()._close()

    async def cleanup(self) -> None:
        """Await :meth:`_close`; idempotent, safe to call repeatedly.

        The local MCP factory (FEAT-580 M4) only calls ``_close()`` when
        ``_opened`` was set by ``_ensure_open()`` — which never happens for
        this toolkit since ``auto_open=False``. ``cleanup()`` is the
        lifecycle hook that unconditionally runs on shutdown, so it is the
        one that must actually release the owned Pyright process.
        """
        await self._close()

    # ------------------------------------------------------------------
    # Navigation: shared implementation
    # ------------------------------------------------------------------

    async def _navigate(
        self,
        *,
        operation: str,
        lsp_method: str,
        path: str,
        line: int,
        column: int,
        expected_sha256: str,
        extra_params: dict[str, Any] | None,
        limit: int,
    ) -> LSPResult:
        """Validate input/sentinel, then run the bounded, lock-serialized call."""
        if self._config.environment_id == OPERATOR_UNCONFIGURED_ENVIRONMENT_ID:
            return LSPResult(
                status="unavailable",
                operation=operation,
                code="invalid_request",
                message="environment_id is the operator-unconfigured sentinel; no LSP process was started",
                fallback=_FALLBACK_MESSAGE,
            )

        try:
            position = SourcePosition(path=path, line=line, column=column, expected_sha256=expected_sha256)
        except ValidationError as exc:
            return LSPResult(
                status="error",
                operation=operation,
                code="invalid_request",
                message=str(exc),
                fallback=_FALLBACK_MESSAGE,
            )

        started_at = time.monotonic()
        try:
            return await asyncio.wait_for(
                self._navigate_locked(operation, lsp_method, position, extra_params, limit, started_at),
                timeout=_TOTAL_CALL_DEADLINE_S,
            )
        except asyncio.TimeoutError:
            return LSPResult(
                status="error",
                operation=operation,
                code="request_timeout",
                message=f"{operation} exceeded the {_TOTAL_CALL_DEADLINE_S:g}s total call deadline",
                fallback=_FALLBACK_MESSAGE,
            )

    async def _navigate_locked(
        self,
        operation: str,
        lsp_method: str,
        position: SourcePosition,
        extra_params: dict[str, Any] | None,
        limit: int,
        started_at: float,
    ) -> LSPResult:
        """Run one semantic operation under the per-instance operation lock."""
        async with self._operation_lock:
            try:
                return await self._navigate_impl(operation, lsp_method, position, extra_params, limit, started_at)
            except LSPFailure as exc:
                return self._failure_result(operation, exc)
            finally:
                self._reset_idle_timer()

    async def _navigate_impl(
        self,
        operation: str,
        lsp_method: str,
        position: SourcePosition,
        extra_params: dict[str, Any] | None,
        limit: int,
        started_at: float,
    ) -> LSPResult:
        path = position.path

        before = await capture_workspace(self._config, [path])
        actual_hash = before.file_hashes.get(path)
        if actual_hash is None:
            raise LSPFailure("file_missing", f"{path} is not part of the tracked workspace manifest")
        if actual_hash != position.expected_sha256:
            raise LSPFailure("source_changed", f"{path} on-disk content does not match the caller's expected_sha256")

        source_text = before.requested_text[path]
        lsp_position = to_lsp_position(source_text, position.line, position.column)

        session = await self._acquire_session(before)

        source_state = SourceState(path=path, sha256=actual_hash, document_version=1)
        await session.sync_documents([source_state], {path: source_text})

        params: dict[str, Any] = {"textDocument": {"uri": self._uri_for_path(path)}, "position": lsp_position}
        if extra_params:
            params.update(extra_params)

        raw_result = await session.request(lsp_method, params, timeout_s=self._config.request_timeout_s)

        raw_entries = self._extract_raw_locations(raw_result)
        resolved, omitted_external = self._resolve_targets(raw_entries)

        # `before.file_hashes` already covers every manifest member (the
        # snapshot worker hashes the whole workspace, not just `path`), so
        # this membership check is free and lets us omit a resolved target
        # that is not actually part of the tracked/untracked manifest
        # (deleted, ignored, or simply nonexistent) instead of failing the
        # second `capture_workspace` call for the whole batch.
        in_manifest = [(rel_path, range_obj) for rel_path, range_obj in resolved if rel_path in before.file_hashes]
        omitted_not_in_manifest = len(resolved) - len(in_manifest)
        resolved = in_manifest

        target_paths = sorted({rel_path for rel_path, _ in resolved} | {path})
        after = await capture_workspace(self._config, target_paths)

        if after.digest != before.digest:
            raise LSPFailure("workspace_changed", "workspace content changed while the request was in flight")

        locations, omitted_missing = self._build_locations(resolved, after)
        locations = self._dedupe(locations)
        kept, truncated, omitted_caps = self._cap_locations(locations, limit)
        omitted_total = omitted_external + omitted_not_in_manifest + omitted_missing + omitted_caps

        elapsed_ms = int((time.monotonic() - started_at) * 1000)
        evidence = EvidenceMeta(
            repo_root=self._config.repo_root,
            workspace_id=self._workspace_id,
            generation=self._session_generation,
            workspace_digest=after.digest,
            environment_id=self._config.environment_id,
            server_version=self._config.expected_server_version,
            config_digest=after.config_digest,
            observed_at=datetime.now(timezone.utc),
            source_states=[source_state],
            elapsed_ms=elapsed_ms,
            cold_start=self._last_cold_start,
            coverage="static_references",
        )
        checked_paths = sorted({path} | {rel_path for rel_path, _ in resolved})
        return LSPResult(
            status="partial" if truncated else "ok",
            operation=operation,
            evidence=evidence,
            locations=kept,
            checked_paths=checked_paths,
            truncated=truncated,
            omitted_count=omitted_total,
        )

    # ------------------------------------------------------------------
    # Session acquisition / lifecycle
    # ------------------------------------------------------------------

    async def _acquire_session(self, before: Any) -> PyrightSession:
        """Return a warm session, restarting it if the workspace/config digest changed."""
        needs_restart = (
            self._session is None
            or self._session_digest != before.digest
            or self._session_config_digest != before.config_digest
        )
        self._last_cold_start = needs_restart
        if needs_restart:
            await self._close_session_locked()
            self._session_generation += 1
            session = PyrightSession()
            await session.start(self._config, self._session_generation)
            self._session = session
            self._session_digest = before.digest
            self._session_config_digest = before.config_digest
        assert self._session is not None
        return self._session

    async def _close_session_locked(self) -> None:
        """Close the owned session (if any) and cancel the idle timer.

        Callers must already hold ``self._operation_lock`` — this method
        never acquires it itself, avoiding recursive acquisition from
        :meth:`_close`, :meth:`_acquire_session`, and the idle-timeout task.
        """
        if self._idle_task is not None and not self._idle_task.done():
            self._idle_task.cancel()
        self._idle_task = None
        session = self._session
        self._session = None
        self._session_digest = None
        self._session_config_digest = None
        if session is not None:
            await session.close()

    def _reset_idle_timer(self) -> None:
        """(Re)schedule the idle-shutdown task if a session is currently owned."""
        if self._idle_task is not None and not self._idle_task.done():
            self._idle_task.cancel()
        if self._session is not None:
            self._idle_task = asyncio.ensure_future(self._idle_shutdown(self._config.idle_timeout_s))
        else:
            self._idle_task = None

    async def _idle_shutdown(self, delay: float) -> None:
        """Close the owned session after ``delay`` seconds of no new call."""
        try:
            await asyncio.sleep(delay)
        except asyncio.CancelledError:
            return
        async with self._operation_lock:
            await self._close_session_locked()

    # ------------------------------------------------------------------
    # Result normalization
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_raw_locations(raw_result: Any) -> list[dict[str, Any]]:
        """Normalize a raw ``Location | LocationLink | list[...] | null`` result."""
        if raw_result is None:
            return []
        if isinstance(raw_result, dict):
            return [raw_result]
        if isinstance(raw_result, list):
            return [item for item in raw_result if isinstance(item, dict)]
        return []

    @staticmethod
    def _extract_uri_and_range(item: dict[str, Any]) -> tuple[str, dict[str, Any]] | None:
        """Return ``(uri, range)`` for one raw ``Location``/``LocationLink`` item."""
        if "targetUri" in item:
            uri = item.get("targetUri")
            range_obj = item.get("targetSelectionRange") or item.get("targetRange")
        else:
            uri = item.get("uri")
            range_obj = item.get("range")
        if not isinstance(uri, str) or not isinstance(range_obj, dict):
            return None
        return uri, range_obj

    def _resolve_targets(self, entries: list[dict[str, Any]]) -> tuple[list[tuple[str, dict[str, Any]]], int]:
        """Resolve raw entries to confined, repo-relative ``(path, range)`` pairs.

        Anything outside ``repo_root`` (external dependency locations),
        non-``file://``, or not a ``.py``/``.pyi`` suffix is omitted rather
        than surfaced — this pilot never reads external content back to
        the agent (spec §2.1).
        """
        if self._canonical_root is None:
            self._canonical_root = self._config.repo_root.resolve()
        resolved: list[tuple[str, dict[str, Any]]] = []
        omitted = 0
        for item in entries:
            parsed = self._extract_uri_and_range(item)
            if parsed is None:
                omitted += 1
                continue
            uri, range_obj = parsed
            rel_path = self._relative_to_root(uri)
            if rel_path is None or PurePosixPath(rel_path).suffix not in _SOURCE_SUFFIXES:
                omitted += 1
                continue
            resolved.append((rel_path, range_obj))
        return resolved, omitted

    def _relative_to_root(self, uri: str) -> str | None:
        """Return the repo-relative POSIX path for a ``file://`` URI, or ``None``."""
        if not uri.startswith("file://"):
            return None
        raw_path = urllib.parse.unquote(urllib.parse.urlparse(uri).path)
        try:
            candidate = Path(raw_path).resolve()
        except OSError:
            return None
        assert self._canonical_root is not None
        try:
            relative = candidate.relative_to(self._canonical_root)
        except ValueError:
            return None
        return relative.as_posix()

    @staticmethod
    def _build_locations(resolved: list[tuple[str, dict[str, Any]]], after: Any) -> tuple[list[LSPLocation], int]:
        """Convert confined ``(path, range)`` pairs into hashed :class:`LSPLocation` entries."""
        locations: list[LSPLocation] = []
        omitted = 0
        for rel_path, range_obj in resolved:
            text = after.requested_text.get(rel_path)
            file_hash = after.file_hashes.get(rel_path)
            if text is None or file_hash is None:
                omitted += 1
                continue
            try:
                source_range = from_lsp_range(text, rel_path, range_obj)
            except LSPFailure:
                omitted += 1
                continue
            locations.append(LSPLocation(range=source_range, sha256=file_hash))
        return locations, omitted

    @staticmethod
    def _dedupe(locations: list[LSPLocation]) -> list[LSPLocation]:
        """Drop exact-duplicate ``(path, range, sha256)`` locations, preserving order."""
        seen: set[tuple[str, int, int, int, int, str]] = set()
        deduped: list[LSPLocation] = []
        for location in locations:
            key = (
                location.range.path,
                location.range.start_line,
                location.range.start_column,
                location.range.end_line,
                location.range.end_column,
                location.sha256,
            )
            if key in seen:
                continue
            seen.add(key)
            deduped.append(location)
        return deduped

    @staticmethod
    def _cap_locations(locations: list[LSPLocation], limit: int) -> tuple[list[LSPLocation], bool, int]:
        """Enforce the count/byte caps, returning ``(kept, truncated, omitted_count)``."""
        truncated = False
        omitted = 0
        effective_limit = min(limit, _MAX_RENDERED_ITEMS)
        if len(locations) > effective_limit:
            omitted += len(locations) - effective_limit
            locations = locations[:effective_limit]
            truncated = True

        kept: list[LSPLocation] = []
        total_bytes = 2  # "[" + "]"
        for location in locations:
            encoded = json.dumps(location.model_dump(mode="json"), separators=(",", ":")).encode("utf-8")
            addition = len(encoded) + (1 if kept else 0)  # ',' separator once non-empty
            if kept and total_bytes + addition > _MAX_RESULT_BYTES:
                break
            kept.append(location)
            total_bytes += addition

        if len(kept) < len(locations):
            omitted += len(locations) - len(kept)
            truncated = True
        return kept, truncated, omitted

    # ------------------------------------------------------------------
    # Small helpers
    # ------------------------------------------------------------------

    def _uri_for_path(self, path: str) -> str:
        """Return the ``file://`` URI for a repository-relative document path."""
        return _path_to_file_uri(self._config.repo_root / path)

    def _failure_result(self, operation: str, exc: LSPFailure) -> LSPResult:
        """Map one :class:`LSPFailure` into its typed :class:`LSPResult` envelope."""
        status = "unavailable" if exc.code in _UNAVAILABLE_CODES else "error"
        return LSPResult(
            status=status,
            operation=operation,
            code=exc.code,
            message=exc.detail or exc.code,
            fallback=_FALLBACK_MESSAGE,
        )

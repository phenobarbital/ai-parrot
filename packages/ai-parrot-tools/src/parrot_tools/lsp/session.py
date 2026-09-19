"""Own Pyright startup, requests and bounded process shutdown (FEAT-580, M2).

:class:`PyrightSession` owns exactly one Pyright ``pyright-langserver``
child process for exactly one ``(config, generation)`` pair. It composes
the byte-level framing in :mod:`parrot_tools.lsp.protocol` under a single
child-process owner: it verifies the server's version, spawns the process
with an explicit working directory/root, negotiates capabilities and
configuration during the ``initialize``/``initialized`` handshake,
continuously drains ``stdout``/``stderr`` so the child never blocks on a
full pipe, maps outgoing request ids to :class:`asyncio.Future` objects,
answers server-to-client requests (and explicitly rejects
``workspace/applyEdit``), and tears the process down through a bounded
``shutdown``/``exit`` -> ``terminate`` -> ``kill`` -> reap sequence.

:meth:`PyrightSession.sync_documents` and :meth:`PyrightSession.diagnostics`
additionally own exact on-disk document synchronization (``didOpen``/
``didChange``/``didClose``, monotonic versions, a 20-document cap) and
versioned push-diagnostic collection (freshness matched against the
currently open document version, explicit missing/unversioned coverage,
a 2,000 raw diagnostic cap, and warm per-path reuse for unchanged source
states). Nothing here interprets or crops diagnostic messages for display,
computes workspace digests, or builds baseline deltas — that is the
toolkit's job (a later task).
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import re
import urllib.parse
from collections import deque
from pathlib import Path
from typing import Any, Mapping

from pydantic import ValidationError

from .models import DiagnosticBatch, LSPConfig, LSPFailure, RawDiagnostic, SourceRange, SourceState
from .protocol import ParsedMessage, build_notification, build_request, build_response, read_message, write_message

__all__ = ["PyrightSession"]

#: Client-initiated request methods this session permits via :meth:`PyrightSession.request`.
#: Anything else — including ``workspace/executeCommand`` — is rejected outright; document
#: synchronization/diagnostics methods are deliberately absent (out of scope for M2).
_ALLOWED_REQUEST_METHODS: frozenset[str] = frozenset(
    {
        "textDocument/definition",
        "textDocument/references",
    }
)

#: Server-to-client notification methods buffered for the next task to consume.
_BUFFERED_NOTIFICATION_METHODS: frozenset[str] = frozenset({"textDocument/publishDiagnostics", "$/progress"})

#: Bound on how many unsolicited server notifications are buffered before the oldest is
#: dropped (spec §2.10 "Bounds" style cap) — a session that is never drained must not grow
#: without limit.
_MAX_BUFFERED_NOTIFICATIONS = 1000

#: Bound on how many stderr bytes are retained for diagnosis; the pipe is drained past this
#: cap too, so a noisy child never blocks on a full stderr buffer.
_MAX_STDERR_CAPTURE_BYTES = 64 * 1024

#: Bound on how many on-disk documents may be open at once (spec §2.5 "Bounds").
_MAX_OPEN_DOCUMENTS = 20

#: Bound on how many raw (uncropped) diagnostics one batch may carry across all
#: matched paths (spec §2.10 "Bounds" — "maximum 2,000 raw diagnostics per snapshot").
_MAX_RAW_DIAGNOSTICS = 2000

#: Default bounded shutdown/terminate/kill timeouts (spec §2 "bounded process shutdown").
_DEFAULT_SHUTDOWN_TIMEOUT_S = 5.0
_DEFAULT_TERMINATE_TIMEOUT_S = 5.0
_DEFAULT_KILL_TIMEOUT_S = 5.0


def _path_to_file_uri(path: Path) -> str:
    """Return a ``file://`` URI for an absolute repository path.

    Args:
        path: An absolute filesystem path.

    Returns:
        A percent-encoded ``file://`` URI for ``path``.
    """
    return "file://" + urllib.parse.quote(path.as_posix())


class PyrightSession:
    """Owns one Pyright child process: startup, JSON-RPC requests, shutdown.

    Each instance owns exactly one process for exactly one ``(config,
    generation)`` pair: call :meth:`start` once, issue zero or more
    :meth:`request` calls, then always call :meth:`close` — a session that
    failed to start or has been closed is never restarted, and a fresh
    ``PyrightSession`` must be constructed for the next generation.

    Args:
        shutdown_timeout_s: Bound on waiting for a ``shutdown`` response
            during :meth:`close` before proceeding straight to
            ``terminate``.
        terminate_timeout_s: Bound on waiting for the process to exit
            after ``SIGTERM`` before escalating to ``SIGKILL``.
        kill_timeout_s: Bound on waiting for the process to exit (be
            reaped) after ``SIGKILL``.
    """

    def __init__(
        self,
        *,
        shutdown_timeout_s: float = _DEFAULT_SHUTDOWN_TIMEOUT_S,
        terminate_timeout_s: float = _DEFAULT_TERMINATE_TIMEOUT_S,
        kill_timeout_s: float = _DEFAULT_KILL_TIMEOUT_S,
    ) -> None:
        self.logger = logging.getLogger(__name__)
        self._shutdown_timeout_s = shutdown_timeout_s
        self._terminate_timeout_s = terminate_timeout_s
        self._kill_timeout_s = kill_timeout_s

        self.generation: int | None = None
        self._config: LSPConfig | None = None
        self._process: asyncio.subprocess.Process | None = None
        self._reader_task: asyncio.Task[None] | None = None
        self._stderr_task: asyncio.Task[None] | None = None
        self._pending: dict[int | str, "asyncio.Future[ParsedMessage]"] = {}
        # Private seam: :meth:`diagnostics` drains this via
        # :meth:`_drain_notifications` instead of re-reading the wire itself.
        self._notifications: deque[ParsedMessage] = deque(maxlen=_MAX_BUFFERED_NOTIFICATIONS)
        # Set whenever a notification is buffered, so :meth:`diagnostics` can
        # wait for new arrivals instead of polling.
        self._notification_event = asyncio.Event()
        self._stderr_tail = bytearray()
        self._id_counter = 1
        self._started = False
        self._crashed = False
        self._server_capabilities: dict[str, Any] | None = None

        # Document synchronization state (path -> ...), all keyed by the
        # repository-relative POSIX path a caller uses in `SourceState.path`.
        self._open_documents: dict[str, int] = {}
        self._open_document_sha: dict[str, str] = {}
        self._open_document_text: dict[str, str] = {}
        # The latest publication known to match the currently open version
        # for a path: (version, uncropped diagnostics). Stale once the
        # document is re-opened/changed to a version this no longer matches.
        self._diagnostic_cache: dict[str, tuple[int, list[RawDiagnostic]]] = {}

    # ------------------------------------------------------------------
    # Public contract
    # ------------------------------------------------------------------

    async def start(self, config: LSPConfig, generation: int) -> None:
        """Start the owned Pyright process for one ``(config, generation)`` pair.

        Verifies ``config.version_command`` reports exactly
        ``config.expected_server_version``, spawns ``config.server_command``
        with an explicit ``cwd``/root and a Node heap option, begins
        continuously draining ``stdout``/``stderr``, then performs the
        ``initialize``/``initialized`` handshake (capabilities and
        ``workspace/configuration`` negotiation). Any failure at any stage
        cleans up whatever was partially started (process killed, tasks
        cancelled, pending futures failed) before raising.

        Args:
            config: Trusted, immutable, already-validated configuration.
                Never mutated by this session.
            generation: The caller's monotonically increasing generation
                identifier for this process instance; stored verbatim on
                :attr:`generation`, never generated internally.

        Raises:
            LSPFailure: ``"server_missing"`` if either command's executable
                cannot be found or the version command exits non-zero;
                ``"server_version_mismatch"`` if the reported version does
                not match ``config.expected_server_version``;
                ``"startup_timeout"`` if the version check or the handshake
                does not complete within ``config.startup_timeout_s``;
                ``"server_crashed"`` if the process exits/EOFs during the
                handshake; ``"protocol_error"`` if ``initialize`` itself
                returns a JSON-RPC error; ``"invalid_request"`` if this
                session has already been started.
        """
        if self._started or self._process is not None:
            raise LSPFailure("invalid_request", "PyrightSession.start() called on an already-started session")
        self._config = config
        self.generation = generation
        try:
            await self._verify_version(config)
            await self._spawn_process(config)
            self._start_draining()
            await self._handshake(config)
        except Exception:
            await self._cleanup_partial_startup()
            raise

    async def request(self, method: str, params: dict[str, Any], timeout_s: float) -> Any:
        """Issue one client-initiated JSON-RPC request and await its response.

        Args:
            method: The LSP method to call. Must be one of the fixed,
                allowlisted methods this session permits — arbitrary
                methods and ``workspace/executeCommand`` are always
                rejected, never forwarded to the server.
            params: The request's JSON-RPC ``params`` object.
            timeout_s: Bound on waiting for the response.

        Returns:
            The response's ``result`` value.

        Raises:
            LSPFailure: ``"unsupported_capability"`` if ``method`` is not
                allowlisted; ``"server_crashed"`` if the session is not
                running; ``"request_timeout"`` if no response arrives
                within ``timeout_s``; ``"protocol_error"`` if the server
                answers with a JSON-RPC error.
            asyncio.CancelledError: If the awaiting task is cancelled; the
                pending future is cleaned up before re-raising.
        """
        if method not in _ALLOWED_REQUEST_METHODS:
            raise LSPFailure("unsupported_capability", f"method is not permitted on this session: {method!r}")
        if not self._started or self._process is None or self._process.stdin is None:
            raise LSPFailure("server_crashed", "session is not running")

        request_id = self._next_id()
        future: "asyncio.Future[ParsedMessage]" = asyncio.get_running_loop().create_future()
        self._pending[request_id] = future
        try:
            await write_message(self._process.stdin, build_request(request_id, method, params))
        except Exception:
            self._pending.pop(request_id, None)
            raise

        try:
            response = await asyncio.wait_for(future, timeout=timeout_s)
        except asyncio.TimeoutError as exc:
            self._pending.pop(request_id, None)
            raise LSPFailure("request_timeout", f"no response for {method!r} within {timeout_s}s") from exc
        except asyncio.CancelledError:
            self._pending.pop(request_id, None)
            raise

        if response.error is not None:
            raise LSPFailure("protocol_error", f"server returned an error for {method!r}: {response.error}")
        return response.result

    async def sync_documents(self, sources: list[SourceState], texts: dict[str, str]) -> None:
        """Open/change/close exact on-disk documents with explicit versions.

        Closes any currently open document not present in ``sources`` (it is
        not needed by the current operation), then opens or updates every
        requested document: a first sighting of a path sends
        ``textDocument/didOpen``; a strictly higher ``document_version``
        for an already-open path sends ``textDocument/didChange`` with the
        full new text; a repeated ``(document_version, sha256)`` pair is a
        no-op that preserves any cached diagnostics for warm reuse.

        Args:
            sources: The exact on-disk identity (path, hash, monotonic
                version) of every document this operation needs open. Must
                not exceed :data:`_MAX_OPEN_DOCUMENTS` distinct paths.
            texts: The exact decoded on-disk text for every path in
                ``sources``, keyed by ``SourceState.path``.

        Raises:
            LSPFailure: ``"server_crashed"`` if the session is not running;
                ``"resource_limit"`` if ``sources`` names more than
                :data:`_MAX_OPEN_DOCUMENTS` distinct paths;
                ``"invalid_request"`` if ``texts`` is missing a requested
                path, a repeated version's hash does not match the
                already-open document, or ``document_version`` regresses.
        """
        if not self._started or self._process is None or self._process.stdin is None:
            raise LSPFailure("server_crashed", "session is not running")
        requested_paths = {source.path for source in sources}
        if len(requested_paths) > _MAX_OPEN_DOCUMENTS:
            raise LSPFailure("resource_limit", f"cannot synchronize more than {_MAX_OPEN_DOCUMENTS} documents at once")
        for path in list(self._open_documents):
            if path not in requested_paths:
                await self._close_document(path)
        for source in sources:
            if source.path not in texts:
                raise LSPFailure("invalid_request", f"missing on-disk text for {source.path!r}")
            await self._sync_one_document(source, texts[source.path])

    async def diagnostics(self, sources: list[SourceState], timeout_s: float) -> DiagnosticBatch:
        """Return version-matched publications and explicit missing/unversioned coverage.

        Waits until every path in ``sources`` has a buffered
        ``textDocument/publishDiagnostics`` publication whose version
        matches that path's currently open document version (via
        :meth:`sync_documents`), or until ``timeout_s`` elapses — never
        inferring completeness from silence, a timer, or any other
        response type. A path whose only publication omitted its version
        is reported as unversioned rather than matched. A path already
        covered by a warm, still-matching per-path cache entry (an
        unchanged source state since the last call) is resolved
        immediately without waiting. The combined raw diagnostic count is
        capped at :data:`_MAX_RAW_DIAGNOSTICS`; paths dropped to respect
        the cap are reported as missing rather than truncated in place.

        Args:
            sources: The exact document identities (path, hash, version)
                to collect diagnostics for; must match what the caller
                most recently passed to :meth:`sync_documents`.
            timeout_s: Bound on waiting for every path's publication.

        Returns:
            A :class:`~parrot_tools.lsp.models.DiagnosticBatch` that is
            ``complete`` only when every requested path has a matched,
            within-cap publication.

        Raises:
            LSPFailure: ``"server_crashed"`` if the session is not running.
        """
        if not self._started or self._process is None:
            raise LSPFailure("server_crashed", "session is not running")
        requested_paths = sorted({source.path for source in sources})
        expected_versions = {source.path: source.document_version for source in sources}
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout_s
        unversioned_seen: set[str] = set()

        while True:
            self._notification_event.clear()
            self._consume_diagnostic_notifications(unversioned_seen)
            pending = [
                path
                for path in requested_paths
                if not self._has_matching_cached_diagnostics(path, expected_versions[path])
            ]
            if not pending or self._crashed:
                break
            remaining = deadline - loop.time()
            if remaining <= 0:
                break
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(self._notification_event.wait(), timeout=remaining)

        return self._build_diagnostic_batch(requested_paths, expected_versions, unversioned_seen)

    async def close(self) -> None:
        """Shut the owned process down through a bounded, idempotent sequence.

        Attempts a graceful ``shutdown`` request followed by an ``exit``
        notification (best-effort, bounded by ``shutdown_timeout_s``),
        then always escalates through ``terminate`` -> ``kill`` -> reap
        (each bounded), cancels the draining tasks, and fails every
        pending request future with ``"server_crashed"``. Calling
        :meth:`close` on a session that never started, or more than once,
        is a no-op.
        """
        if self._process is None:
            self._started = False
            return
        await self._graceful_shutdown()
        await self._terminate_process()
        await self._stop_draining()
        self._fail_all_pending(LSPFailure("server_crashed", "session closed"))
        self._process = None
        self._started = False

    # ------------------------------------------------------------------
    # Startup: version verification, spawn, handshake
    # ------------------------------------------------------------------

    async def _verify_version(self, config: LSPConfig) -> None:
        """Run ``config.version_command`` and enforce the exact expected version."""
        try:
            proc = await asyncio.create_subprocess_exec(
                *config.version_command,
                cwd=str(config.repo_root),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError as exc:
            raise LSPFailure(
                "server_missing", f"version_command executable not found: {config.version_command[0]!r}"
            ) from exc

        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=config.startup_timeout_s)
        except asyncio.TimeoutError as exc:
            with contextlib.suppress(ProcessLookupError):
                proc.kill()
            await proc.wait()
            raise LSPFailure("startup_timeout", "version_command did not complete before the startup deadline") from exc

        if proc.returncode != 0:
            raise LSPFailure(
                "server_missing",
                f"version_command exited with code {proc.returncode}: {stderr.decode('utf-8', 'replace')[:200]}",
            )

        output = stdout.decode("utf-8", "replace")
        match = re.search(r"\d+\.\d+\.\d+", output)
        if match is None or match.group(0) != config.expected_server_version:
            found = match.group(0) if match is not None else output.strip()
            raise LSPFailure(
                "server_version_mismatch",
                f"expected pyright {config.expected_server_version}, got {found!r}",
            )

    async def _spawn_process(self, config: LSPConfig) -> None:
        """Spawn ``config.server_command`` with an explicit cwd and Node heap option."""
        env = dict(os.environ)
        heap_option = f"--max-old-space-size={config.node_heap_mb}"
        existing_options = env.get("NODE_OPTIONS", "")
        env["NODE_OPTIONS"] = f"{existing_options} {heap_option}".strip()
        try:
            self._process = await asyncio.create_subprocess_exec(
                *config.server_command,
                cwd=str(config.repo_root),
                env=env,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError as exc:
            raise LSPFailure(
                "server_missing", f"server_command executable not found: {config.server_command[0]!r}"
            ) from exc

    def _start_draining(self) -> None:
        """Schedule the tasks that continuously drain stdout/stderr."""
        self._reader_task = asyncio.ensure_future(self._reader_loop())
        self._stderr_task = asyncio.ensure_future(self._stderr_loop())

    async def _handshake(self, config: LSPConfig) -> None:
        """Perform ``initialize``/``initialized``, negotiating capabilities."""
        assert self._process is not None and self._process.stdin is not None
        request_id = self._next_id()
        future: "asyncio.Future[ParsedMessage]" = asyncio.get_running_loop().create_future()
        self._pending[request_id] = future
        try:
            await write_message(
                self._process.stdin, build_request(request_id, "initialize", self._build_initialize_params(config))
            )
        except Exception:
            self._pending.pop(request_id, None)
            raise

        try:
            response = await asyncio.wait_for(future, timeout=config.startup_timeout_s)
        except asyncio.TimeoutError as exc:
            self._pending.pop(request_id, None)
            raise LSPFailure(
                "startup_timeout", "server did not respond to initialize before the startup deadline"
            ) from exc

        if response.error is not None:
            raise LSPFailure("protocol_error", f"initialize failed: {response.error}")
        self._server_capabilities = response.result.get("capabilities") if isinstance(response.result, dict) else None

        await write_message(self._process.stdin, build_notification("initialized", {}))
        self._started = True

    def _build_initialize_params(self, config: LSPConfig) -> dict[str, Any]:
        """Build the ``initialize`` request params: explicit root + client capabilities."""
        return {
            "processId": os.getpid(),
            "rootUri": _path_to_file_uri(config.repo_root),
            "rootPath": str(config.repo_root),
            "workspaceFolders": self._workspace_folders(config),
            "capabilities": {
                "workspace": {
                    "configuration": True,
                    "workspaceFolders": True,
                    "applyEdit": False,
                },
                "textDocument": {
                    "synchronization": {"didSave": True, "dynamicRegistration": False},
                    "publishDiagnostics": {"relatedInformation": True},
                },
            },
            "initializationOptions": {},
        }

    def _workspace_folders(self, config: LSPConfig) -> list[dict[str, str]]:
        roots = config.source_roots or [config.repo_root]
        return [{"uri": _path_to_file_uri(root), "name": root.name or str(root)} for root in roots]

    async def _cleanup_partial_startup(self) -> None:
        """Undo whatever :meth:`start` had already done before it failed."""
        self._fail_all_pending(LSPFailure("server_crashed", "session startup failed"))
        await self._stop_draining()
        await self._terminate_process()
        self._process = None
        self._started = False

    # ------------------------------------------------------------------
    # Draining: reader loop (responses/server requests/notifications), stderr
    # ------------------------------------------------------------------

    async def _reader_loop(self) -> None:
        """Continuously read frames from stdout until EOF or a protocol failure."""
        assert self._process is not None and self._process.stdout is not None
        while True:
            try:
                message = await read_message(self._process.stdout)
            except LSPFailure as exc:
                self._crashed = True
                self._fail_all_pending(exc)
                return
            await self._dispatch_message(message)

    async def _dispatch_message(self, message: ParsedMessage) -> None:
        """Route one parsed frame: pending response, server request, or notification."""
        if message.kind == "response":
            future = self._pending.pop(message.id, None)
            if future is not None and not future.done():
                future.set_result(message)
            return
        if message.kind == "request":
            await self._answer_server_request(message)
            return
        if message.method in _BUFFERED_NOTIFICATION_METHODS:
            self._notifications.append(message)
            self._notification_event.set()

    async def _answer_server_request(self, message: ParsedMessage) -> None:
        """Write back the response to one server-to-client request."""
        if self._process is None or self._process.stdin is None:
            return
        response = self._build_server_response(message)
        with contextlib.suppress(LSPFailure):
            await write_message(self._process.stdin, response)

    def _build_server_response(self, message: ParsedMessage) -> dict[str, Any]:
        """Pure dispatch: build the JSON-RPC response for one server request.

        Handles ``workspace/configuration``, ``workspace/workspaceFolders``,
        ``client/registerCapability``/``client/unregisterCapability`` and
        ``window/workDoneProgress/create`` by accepting them;
        ``workspace/applyEdit`` is explicitly rejected with a JSON-RPC
        error, and any other, unrecognized method is answered with a
        ``method not found`` error rather than left hanging.
        """
        method = message.method
        if method == "workspace/configuration":
            items = message.params.get("items", []) if isinstance(message.params, Mapping) else []
            result = [self._resolve_configuration_item(item) for item in items]
            return build_response(message.id, result=result)
        if method == "workspace/workspaceFolders":
            assert self._config is not None
            return build_response(message.id, result=self._workspace_folders(self._config))
        if method in ("client/registerCapability", "client/unregisterCapability"):
            return build_response(message.id, result=None)
        if method == "window/workDoneProgress/create":
            return build_response(message.id, result=None)
        if method == "workspace/applyEdit":
            return build_response(
                message.id,
                error={"code": -32601, "message": "workspace/applyEdit is not supported by this session"},
            )
        return build_response(message.id, error={"code": -32601, "message": f"unsupported server request: {method}"})

    def _resolve_configuration_item(self, item: Any) -> Any:
        """Resolve one ``workspace/configuration`` item to a settings value."""
        section = item.get("section") if isinstance(item, Mapping) else None
        if section == "python" and self._config is not None:
            return {"pythonPath": str(self._config.python_path)}
        return {}

    async def _stderr_loop(self) -> None:
        """Continuously drain stderr, retaining only a capped tail."""
        assert self._process is not None and self._process.stderr is not None
        stream = self._process.stderr
        while True:
            chunk = await stream.read(4096)
            if not chunk:
                return
            remaining = _MAX_STDERR_CAPTURE_BYTES - len(self._stderr_tail)
            if remaining > 0:
                self._stderr_tail.extend(chunk[:remaining])

    async def _stop_draining(self) -> None:
        """Cancel and await the reader/stderr tasks."""
        for task in (self._reader_task, self._stderr_task):
            if task is not None and not task.done():
                task.cancel()
        for task in (self._reader_task, self._stderr_task):
            if task is not None:
                with contextlib.suppress(asyncio.CancelledError):
                    await task
        self._reader_task = None
        self._stderr_task = None

    def _drain_notifications(self) -> list[ParsedMessage]:
        """Return and clear all buffered server notifications.

        Private seam for the next task (document synchronization /
        diagnostics collection) to consume ``textDocument/publishDiagnostics``
        and ``$/progress`` notifications this session has buffered.
        """
        drained = list(self._notifications)
        self._notifications.clear()
        return drained

    def _fail_all_pending(self, exc: LSPFailure) -> None:
        """Fail every pending request future with ``exc`` and clear the map."""
        for future in self._pending.values():
            if not future.done():
                future.set_exception(exc)
        self._pending.clear()

    def _next_id(self) -> int:
        request_id = self._id_counter
        self._id_counter += 1
        return request_id

    # ------------------------------------------------------------------
    # Document synchronization: didOpen/didChange/didClose
    # ------------------------------------------------------------------

    async def _sync_one_document(self, source: SourceState, text: str) -> None:
        """Open, change, or no-op one document per its current open state."""
        path = source.path
        existing_version = self._open_documents.get(path)
        if existing_version is None:
            await self._send_did_open(path, source.document_version, text)
            self._open_documents[path] = source.document_version
            self._open_document_sha[path] = source.sha256
            self._open_document_text[path] = text
            return
        if source.document_version == existing_version:
            if self._open_document_sha.get(path) != source.sha256:
                raise LSPFailure("invalid_request", f"document_version for {path!r} did not change but content did")
            return  # unchanged: no-op, preserves any cached diagnostics for warm reuse
        if source.document_version < existing_version:
            raise LSPFailure("invalid_request", f"document_version for {path!r} must increase monotonically")
        await self._send_did_change(path, source.document_version, text)
        self._open_documents[path] = source.document_version
        self._open_document_sha[path] = source.sha256
        self._open_document_text[path] = text

    async def _send_did_open(self, path: str, version: int, text: str) -> None:
        """Send ``textDocument/didOpen`` for one exact on-disk snapshot."""
        assert self._process is not None and self._process.stdin is not None
        params = {
            "textDocument": {
                "uri": self._uri_for_path(path),
                "languageId": "python",
                "version": version,
                "text": text,
            }
        }
        await write_message(self._process.stdin, build_notification("textDocument/didOpen", params))

    async def _send_did_change(self, path: str, version: int, text: str) -> None:
        """Send ``textDocument/didChange`` with the full new on-disk text."""
        assert self._process is not None and self._process.stdin is not None
        params = {
            "textDocument": {"uri": self._uri_for_path(path), "version": version},
            "contentChanges": [{"text": text}],
        }
        await write_message(self._process.stdin, build_notification("textDocument/didChange", params))

    async def _close_document(self, path: str) -> None:
        """Send ``textDocument/didClose`` and drop all local state for ``path``."""
        if self._process is not None and self._process.stdin is not None:
            with contextlib.suppress(LSPFailure):
                await write_message(
                    self._process.stdin,
                    build_notification("textDocument/didClose", {"textDocument": {"uri": self._uri_for_path(path)}}),
                )
        self._open_documents.pop(path, None)
        self._open_document_sha.pop(path, None)
        self._open_document_text.pop(path, None)
        self._diagnostic_cache.pop(path, None)

    def _uri_for_path(self, path: str) -> str:
        """Return the ``file://`` URI for a repository-relative document path."""
        assert self._config is not None
        return _path_to_file_uri(self._config.repo_root / path)

    def _path_for_uri(self, uri: str) -> str | None:
        """Return the repository-relative POSIX path for a ``file://`` URI.

        Returns ``None`` if ``uri`` is not a ``file://`` URI or does not
        resolve inside this session's confined ``repo_root`` — such a
        notification concerns a file outside this session's workspace and
        is ignored for checkpoint coverage.
        """
        if not uri.startswith("file://"):
            return None
        assert self._config is not None
        raw_path = urllib.parse.unquote(urllib.parse.urlparse(uri).path)
        try:
            relative = Path(raw_path).relative_to(self._config.repo_root)
        except ValueError:
            return None
        return relative.as_posix()

    # ------------------------------------------------------------------
    # Diagnostics: versioned push-notification collection
    # ------------------------------------------------------------------

    def _has_matching_cached_diagnostics(self, path: str, version: int) -> bool:
        """Return whether a warm, still-fresh publication is cached for ``path``."""
        cached = self._diagnostic_cache.get(path)
        return cached is not None and cached[0] == version

    def _consume_diagnostic_notifications(self, unversioned_seen: set[str]) -> None:
        """Drain the shared notification seam, applying every diagnostics publication."""
        for message in self._drain_notifications():
            if message.method == "textDocument/publishDiagnostics":
                self._apply_publish_diagnostics(message, unversioned_seen)
            # "$/progress" and any other buffered method carries no diagnostic
            # coverage; draining still clears the single shared seam for it.

    def _apply_publish_diagnostics(self, message: ParsedMessage, unversioned_seen: set[str]) -> None:
        """Route one ``textDocument/publishDiagnostics`` notification into the cache.

        Ignores publications for a path outside this session's workspace,
        a stale/mismatched version, or a malformed payload. A matching
        version — even with an empty diagnostics list — replaces any prior
        cache entry for that path, so a matching empty publication clears
        earlier findings. A publication that omits its version marks the
        path as unversioned rather than matched.
        """
        params = message.params if isinstance(message.params, Mapping) else {}
        uri = params.get("uri")
        if not isinstance(uri, str):
            return
        path = self._path_for_uri(uri)
        if path is None:
            return
        version = params.get("version")
        if version is None:
            unversioned_seen.add(path)
            return
        if isinstance(version, bool) or not isinstance(version, int):
            return
        if self._open_documents.get(path) != version:
            return  # stale generation/version; ignored for checkpoint coverage
        raw_items = params.get("diagnostics")
        if not isinstance(raw_items, list):
            return
        text = self._open_document_text.get(path, "")
        diagnostics: list[RawDiagnostic] = []
        for item in raw_items:
            if isinstance(item, Mapping):
                parsed = self._to_raw_diagnostic(path, text, item)
                if parsed is not None:
                    diagnostics.append(parsed)
        self._diagnostic_cache[path] = (version, diagnostics)
        unversioned_seen.discard(path)

    def _to_raw_diagnostic(self, path: str, text: str, item: Mapping[str, Any]) -> RawDiagnostic | None:
        """Convert one raw LSP diagnostic wire item into a private :class:`RawDiagnostic`.

        Returns ``None`` for a malformed item (missing/invalid range or
        message) rather than raising, so one bad item never discards an
        otherwise valid publication. ``full_message`` is never truncated.
        """
        range_obj = item.get("range")
        message = item.get("message")
        if not isinstance(range_obj, Mapping) or not isinstance(message, str):
            return None
        try:
            source_range = self._lsp_range_to_source_range(path, text, range_obj)
        except ValueError:
            return None
        severity = item.get("severity")
        code = item.get("code")
        source_field = item.get("source")
        kwargs: dict[str, Any] = {
            "range": source_range,
            "full_message": message,
            "code": str(code) if code is not None else None,
            "source": source_field if isinstance(source_field, str) else None,
        }
        if isinstance(severity, int) and not isinstance(severity, bool):
            kwargs["severity"] = severity
        try:
            return RawDiagnostic(**kwargs)
        except ValidationError:
            return None

    def _lsp_range_to_source_range(self, path: str, text: str, range_obj: Mapping[str, Any]) -> SourceRange:
        """Convert one zero-based UTF-16 LSP range into a one-based Unicode :class:`SourceRange`."""
        start = range_obj.get("start")
        end = range_obj.get("end")
        if not isinstance(start, Mapping) or not isinstance(end, Mapping):
            raise ValueError("range is missing 'start'/'end'")
        start_line, start_col = self._utf16_position_to_unicode(text, start.get("line"), start.get("character"))
        end_line, end_col = self._utf16_position_to_unicode(text, end.get("line"), end.get("character"))
        try:
            return SourceRange(
                path=path, start_line=start_line, start_column=start_col, end_line=end_line, end_column=end_col
            )
        except ValidationError as exc:
            raise ValueError(str(exc)) from exc

    def _utf16_position_to_unicode(self, text: str, line0: Any, utf16_col0: Any) -> tuple[int, int]:
        """Convert one zero-based ``(line, UTF-16 code unit)`` LSP position to one-based Unicode.

        Clamps a position past the last line to the end of the text rather
        than raising, since a diagnostic range may legitimately point at
        end-of-file.
        """
        if not isinstance(line0, int) or isinstance(line0, bool) or line0 < 0:
            raise ValueError(f"invalid LSP line: {line0!r}")
        if not isinstance(utf16_col0, int) or isinstance(utf16_col0, bool) or utf16_col0 < 0:
            raise ValueError(f"invalid LSP character: {utf16_col0!r}")
        lines = text.splitlines()
        if line0 >= len(lines):
            return (max(len(lines), 1), 1)
        line_text = lines[line0]
        codepoint_col = len(line_text)
        utf16_count = 0
        for idx, char in enumerate(line_text):
            if utf16_count >= utf16_col0:
                codepoint_col = idx
                break
            utf16_count += 2 if ord(char) > 0xFFFF else 1
        return (line0 + 1, codepoint_col + 1)

    def _build_diagnostic_batch(
        self,
        requested_paths: list[str],
        expected_versions: dict[str, int],
        unversioned_seen: set[str],
    ) -> DiagnosticBatch:
        """Assemble the final :class:`DiagnosticBatch`, enforcing the raw diagnostic cap.

        A path with a matching cached publication contributes its
        uncropped diagnostics; an unmatched path is reported as
        unversioned (if only an unversioned publication was seen) or
        missing (no matching publication at all — including one dropped
        to respect the cap).
        """
        matched_versions: dict[str, int] = {}
        diagnostics: dict[str, list[RawDiagnostic]] = {}
        missing_paths: list[str] = []
        unversioned_paths: list[str] = []

        for path in requested_paths:
            cached = self._diagnostic_cache.get(path)
            if cached is not None and cached[0] == expected_versions[path]:
                matched_versions[path] = cached[0]
                diagnostics[path] = list(cached[1])
            elif path in unversioned_seen:
                unversioned_paths.append(path)
            else:
                missing_paths.append(path)

        total = sum(len(items) for items in diagnostics.values())
        if total > _MAX_RAW_DIAGNOSTICS:
            kept_total = 0
            for path in list(diagnostics):
                count = len(diagnostics[path])
                if kept_total + count > _MAX_RAW_DIAGNOSTICS:
                    diagnostics.pop(path)
                    matched_versions.pop(path, None)
                    missing_paths.append(path)
                else:
                    kept_total += count
            missing_paths.sort()

        complete = not missing_paths and not unversioned_paths
        return DiagnosticBatch(
            diagnostics=diagnostics,
            matched_versions=matched_versions,
            missing_paths=missing_paths,
            unversioned_paths=unversioned_paths,
            complete=complete,
        )

    # ------------------------------------------------------------------
    # Shutdown: graceful shutdown/exit, then bounded terminate/kill/reap
    # ------------------------------------------------------------------

    async def _graceful_shutdown(self) -> None:
        """Best-effort ``shutdown`` request followed by ``exit``, bounded."""
        if self._process is None or self._process.stdin is None or self._process.returncode is not None:
            return
        request_id = self._next_id()
        future: "asyncio.Future[ParsedMessage]" = asyncio.get_running_loop().create_future()
        self._pending[request_id] = future
        try:
            await write_message(self._process.stdin, build_request(request_id, "shutdown", None))
            await asyncio.wait_for(future, timeout=self._shutdown_timeout_s)
        except Exception:
            self._pending.pop(request_id, None)
            return
        with contextlib.suppress(Exception):
            await write_message(self._process.stdin, build_notification("exit", None))

    async def _terminate_process(self) -> None:
        """Bounded terminate -> kill -> reap of the owned process."""
        proc = self._process
        if proc is None or proc.returncode is not None:
            return
        with contextlib.suppress(ProcessLookupError):
            proc.terminate()
        try:
            await asyncio.wait_for(proc.wait(), timeout=self._terminate_timeout_s)
            return
        except asyncio.TimeoutError:
            pass
        with contextlib.suppress(ProcessLookupError):
            proc.kill()
        try:
            await asyncio.wait_for(proc.wait(), timeout=self._kill_timeout_s)
        except asyncio.TimeoutError:
            self.logger.error("pyright process %s did not exit after SIGKILL", proc.pid)

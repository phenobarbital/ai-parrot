"""Bounded read-only inspection with an instance-wide admission limit (FEAT-584).

:class:`InspectionRunner` executes a bounded batch (1-8) of independent,
read-only operations — file reads/metadata, literal search, path listing and
Git status/diff-names — without a shell and without any model call. Every
item is bounded individually (10s, ~2KiB serialized) and the whole batch is
bounded as a unit (20s, the caller's ``max_output_bytes``); a peer failing,
timing out or being cut off by the batch deadline never removes another
item's identity from the response.

One runner is cached per :class:`BoundedSourceToolkit` instance (see
``reader.py``); its admission semaphore is therefore shared by every batch
dispatched through that toolkit instance, not reset per call.
"""

from __future__ import annotations

import asyncio
import json
import os
import stat
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional, Sequence

from parrot_tools.tool_optimizations.inspection_models import (
    FilesRequest,
    GitDiffNamesRequest,
    GitStatusRequest,
    InfoRequest,
    InspectionBatch,
    InspectionBatchArgs,
    InspectionItem,
    InspectionRequest,
    ReadRequest,
    SearchRequest,
)
from parrot_tools.tool_optimizations.models import OperationResult
from parrot_tools.tool_optimizations.policy import fit_to_budget

if TYPE_CHECKING:
    from parrot_tools.tool_optimizations.reader import BoundedSourceToolkit

__all__ = ("InspectionRunner",)

#: Per-item wall-clock deadline, in seconds.
_ITEM_TIMEOUT_SECONDS = 10.0
#: Whole-batch wall-clock deadline, in seconds.
_BATCH_TIMEOUT_SECONDS = 20.0
#: Deadline given to a single git subprocess; always shorter than the item
#: deadline so the subprocess is reaped by _run_git itself, not by the outer
#: per-item timeout, whenever possible.
_GIT_SUBPROCESS_TIMEOUT_SECONDS = 8.0
#: Deadline for the cheap "git rev-parse HEAD" snapshot taken at batch edges.
_GIT_HEAD_TIMEOUT_SECONDS = 5.0
#: Target serialized byte budget for one item's ``data`` payload.
_ITEM_BYTES_BUDGET = 2048
#: Directory entries collected before a "files" request pages via a cursor.
_MAX_FILES_PER_REQUEST = 200
#: Environment forced onto every git subprocess this runner spawns directly.
_GIT_ENV_OVERRIDES: dict[str, str] = {
    "GIT_TERMINAL_PROMPT": "0",
    "GIT_OPTIONAL_LOCKS": "0",
    "GIT_PAGER": "cat",
    "LC_ALL": "C",
    "LANG": "C",
}
#: Maps a policy exception's class name to a stable, snake_case error code.
#: Names, not classes, are used so this module never imports the confinement
#: exception types directly (those are verified only for ``reader.py``).
_POLICY_ERROR_CODES: dict[str, str] = {
    "SymlinkRejectedError": "symlink_rejected",
    "SecretFileError": "secret_file",
    "PathOutsideRootError": "path_outside_root",
    "NotRegularFileError": "not_a_file",
    "FileNotFoundError": "not_found",
    "PolicyError": "not_found",
    "NotADirectoryError": "not_a_directory",
    "ValueError": "invalid_path",
}


class _ItemTimeout(Exception):
    """Internal signal: a spawned git subprocess exceeded its own timeout."""


class InspectionRunner:
    """Execute independent operations without a shell or model call."""

    def __init__(self, reader: "BoundedSourceToolkit") -> None:
        self.reader = reader
        self._slots = asyncio.Semaphore(4)

    async def run(self, args: InspectionBatchArgs) -> OperationResult:
        """Return ordered items, individual failures and bounded continuations.

        Args:
            args: The validated batch request.

        Returns:
            A bounded :class:`OperationResult` wrapping an
            :class:`~parrot_tools.tool_optimizations.inspection_models.InspectionBatch`.
        """
        started = time.perf_counter()
        head_before = await self._git_head()

        batch_slots = asyncio.Semaphore(args.concurrency)
        pending_tasks = {
            asyncio.ensure_future(self._guarded(request, batch_slots)): request for request in args.requests
        }
        _done, still_pending = await asyncio.wait(pending_tasks, timeout=_BATCH_TIMEOUT_SECONDS)
        for task in still_pending:
            task.cancel()
        if still_pending:
            await asyncio.gather(*still_pending, return_exceptions=True)

        items: list[InspectionItem] = []
        for task, request in pending_tasks.items():
            if task in still_pending:
                items.append(
                    InspectionItem(
                        id=request.id,
                        kind=request.kind,
                        status="cancelled",
                        error_code="batch_deadline_exceeded",
                        elapsed_ms=self._elapsed_ms(started),
                    )
                )
                continue
            try:
                items.append(task.result())
            except Exception as exc:  # noqa: BLE001 -- every peer failure becomes one item
                items.append(
                    InspectionItem(
                        id=request.id,
                        kind=request.kind,
                        status="error",
                        error_code="internal_error",
                        data={"message": str(exc)[:200]},
                        elapsed_ms=self._elapsed_ms(started),
                    )
                )

        order = {request.id: index for index, request in enumerate(args.requests)}
        items.sort(key=lambda item: order[item.id])

        head_after = await self._git_head()
        stale = any(item.error_code == "concurrent_modification" for item in items)
        consistent = head_before == head_after and not stale
        partial = any(item.status != "ok" for item in items)

        batch = InspectionBatch(
            items=items,
            partial=partial,
            consistent=consistent,
            head_before=head_before,
            head_after=head_after,
            elapsed_ms=self._elapsed_ms(started),
            sum_item_ms=sum(item.elapsed_ms for item in items),
            returned_bytes=0,
        )
        batch.returned_bytes = self._json_bytes(batch.model_dump(mode="json"))
        return self._finalize(batch, args.max_output_bytes, started)

    # ------------------------------------------------------------------ #
    # Admission and dispatch
    # ------------------------------------------------------------------ #
    async def _guarded(self, request: InspectionRequest, batch_slots: asyncio.Semaphore) -> InspectionItem:
        """Run one item under the global and per-batch admission limits.

        Args:
            request: The validated item request.
            batch_slots: The per-batch concurrency semaphore.

        Returns:
            The item's bounded result; a per-item timeout is caught here so a
            slow item never fails the batch.
        """
        started = time.perf_counter()
        async with self._slots:
            async with batch_slots:
                try:
                    async with asyncio.timeout(_ITEM_TIMEOUT_SECONDS):
                        return await self._dispatch(request, started)
                except (TimeoutError, asyncio.TimeoutError):
                    return InspectionItem(
                        id=request.id,
                        kind=request.kind,
                        status="error",
                        error_code="item_timeout",
                        elapsed_ms=self._elapsed_ms(started),
                    )

    async def _dispatch(self, request: InspectionRequest, started: float) -> InspectionItem:
        """Route one validated request to its operation handler.

        Args:
            request: The validated item request.
            started: A ``perf_counter()`` reading taken at item start.

        Returns:
            The item's bounded result.
        """
        if isinstance(request, ReadRequest):
            return await self._do_read(request, started)
        if isinstance(request, InfoRequest):
            return await self._do_info(request, started)
        if isinstance(request, SearchRequest):
            return await self._do_search(request, started)
        if isinstance(request, FilesRequest):
            return await self._do_files(request, started)
        if isinstance(request, GitStatusRequest):
            return await self._do_git_status(request, started)
        return await self._do_git_diff_names(request, started)

    # ------------------------------------------------------------------ #
    # read / info -- delegate to the reader, keep its semantics untouched
    # ------------------------------------------------------------------ #
    async def _do_read(self, request: ReadRequest, started: float) -> InspectionItem:
        """Delegate to ``source_read`` and map its result onto one item."""
        result = await self.reader.source_read(
            path=request.path,
            start_line=request.start_line,
            end_line=request.end_line,
            expected_sha256=request.expected_sha256,
        )
        return self._from_reader_result(request, result, started)

    async def _do_info(self, request: InfoRequest, started: float) -> InspectionItem:
        """Delegate to ``source_info`` and map its result onto one item."""
        result = await self.reader.source_info(path=request.path)
        return self._from_reader_result(request, result, started)

    def _from_reader_result(self, request: InspectionRequest, result: Any, started: float) -> InspectionItem:
        """Map a reader ``SourceResult``/``SourceInfo``/``OperationResult`` onto an item.

        Args:
            request: The originating item request.
            result: Whatever the reader method returned.
            started: A ``perf_counter()`` reading taken at item start.

        Returns:
            The bounded item, preserving error code/details or truncation.
        """
        elapsed = self._elapsed_ms(started)
        if isinstance(result, OperationResult):
            if result.status == "ok":
                return self._bound_item(
                    InspectionItem(
                        id=request.id,
                        kind=request.kind,
                        status="ok",
                        data=result.data,
                        truncated=result.truncated,
                        elapsed_ms=elapsed,
                    )
                )
            error = result.error
            return InspectionItem(
                id=request.id,
                kind=request.kind,
                status="error",
                error_code=error.code if error else "read_failed",
                data=dict(error.details) if error else {},
                elapsed_ms=elapsed,
            )
        # A bare Pydantic model: SourceResult or SourceInfo.
        return self._bound_item(
            InspectionItem(
                id=request.id,
                kind=request.kind,
                status="ok",
                data=result.model_dump(mode="json"),
                truncated=bool(getattr(result, "truncated", False)),
                elapsed_ms=elapsed,
            )
        )

    # ------------------------------------------------------------------ #
    # search -- literal substring only, never interpreted as a pattern
    # ------------------------------------------------------------------ #
    async def _do_search(self, request: SearchRequest, started: float) -> InspectionItem:
        """Search literal text across confined files off the event loop."""
        try:
            matches, truncated, cursor, error = await asyncio.to_thread(self._search_blocking, request)
        except Exception as exc:  # noqa: BLE001 -- mapped to a stable item error
            return InspectionItem(
                id=request.id,
                kind=request.kind,
                status="error",
                error_code="search_failed",
                data={"message": str(exc)[:200]},
                elapsed_ms=self._elapsed_ms(started),
            )
        if error is not None:
            code, path = error
            return InspectionItem(
                id=request.id,
                kind=request.kind,
                status="error",
                error_code=code,
                data={"path": path},
                elapsed_ms=self._elapsed_ms(started),
            )
        return self._bound_item(
            InspectionItem(
                id=request.id,
                kind=request.kind,
                status="ok",
                data={"matches": matches},
                truncated=truncated,
                continuation=cursor,
                elapsed_ms=self._elapsed_ms(started),
            )
        )

    def _search_blocking(
        self, request: SearchRequest
    ) -> tuple[list[dict[str, object]], bool, Optional[str], Optional[tuple[str, str]]]:
        """Scan the requested paths for a literal match, off the event loop.

        Args:
            request: The validated search request.

        Returns:
            A ``(matches, truncated, continuation, error)`` tuple, where
            ``error`` is ``(code, path)`` when a path failed policy.
        """
        start_index, start_line = self._decode_cursor(request.continuation)
        matches: list[dict[str, object]] = []
        for path_index, raw_path in enumerate(request.paths):
            if path_index < start_index:
                continue
            try:
                target, relative = self.reader._resolve(raw_path)
            except Exception as exc:  # noqa: BLE001 -- mapped to a stable code
                return [], False, None, (self._policy_error_code(exc), raw_path)
            try:
                with open(target, "rb") as probe:
                    if b"\x00" in probe.read(8192):
                        continue  # binary file: skip, not an error
            except OSError:
                continue
            line_floor = start_line if path_index == start_index else 0
            try:
                with open(target, "r", encoding="utf-8", errors="strict") as handle:
                    for line_no, text in enumerate(handle, start=1):
                        if line_no <= line_floor:
                            continue
                        if request.text in text:
                            matches.append({"path": relative, "line": line_no, "excerpt": text.rstrip("\n")[:200]})
                            if len(matches) >= request.max_matches:
                                return matches, True, f"{path_index}:{line_no}", None
            except UnicodeDecodeError:
                continue
        return matches, False, None, None

    # ------------------------------------------------------------------ #
    # files -- bounded, deterministic directory listing
    # ------------------------------------------------------------------ #
    async def _do_files(self, request: FilesRequest, started: float) -> InspectionItem:
        """List confined repository-relative paths off the event loop."""
        try:
            paths, truncated, cursor, error = await asyncio.to_thread(self._files_blocking, request)
        except Exception as exc:  # noqa: BLE001 -- mapped to a stable item error
            return InspectionItem(
                id=request.id,
                kind=request.kind,
                status="error",
                error_code="files_failed",
                data={"message": str(exc)[:200]},
                elapsed_ms=self._elapsed_ms(started),
            )
        if error is not None:
            code, path = error
            return InspectionItem(
                id=request.id,
                kind=request.kind,
                status="error",
                error_code=code,
                data={"path": path},
                elapsed_ms=self._elapsed_ms(started),
            )
        return self._bound_item(
            InspectionItem(
                id=request.id,
                kind=request.kind,
                status="ok",
                data={"paths": paths},
                truncated=truncated,
                continuation=cursor,
                elapsed_ms=self._elapsed_ms(started),
            )
        )

    def _files_blocking(
        self, request: FilesRequest
    ) -> tuple[list[str], bool, Optional[str], Optional[tuple[str, str]]]:
        """Walk the requested roots for confined files, off the event loop.

        Args:
            request: The validated files request.

        Returns:
            A ``(paths, truncated, continuation, error)`` tuple, where
            ``error`` is ``(code, path)`` when a root failed policy.
        """
        start_root, start_ordinal = self._decode_cursor(request.continuation)
        collected: list[str] = []
        for root_index, raw_root in enumerate(request.paths):
            if root_index < start_root:
                continue
            try:
                root_dir = self._confine_dir(raw_root)
            except Exception as exc:  # noqa: BLE001 -- mapped to a stable code
                return [], False, None, (self._policy_error_code(exc), raw_root)
            ordinal = 0
            for dirpath, dirnames, filenames in os.walk(root_dir, followlinks=False):
                dirnames.sort()
                for name in sorted(filenames):
                    if root_index == start_root and ordinal < start_ordinal:
                        ordinal += 1
                        continue
                    ordinal += 1
                    candidate = Path(dirpath) / name
                    relative = candidate.relative_to(self.reader.policy.repo_root).as_posix()
                    try:
                        self.reader._resolve(relative)
                    except Exception:  # noqa: BLE001 -- excluded from the listing, not an error
                        continue
                    collected.append(relative)
                    if len(collected) >= _MAX_FILES_PER_REQUEST:
                        return collected, True, f"{root_index}:{ordinal}", None
        return collected, False, None, None

    def _confine_dir(self, raw_root: str) -> Path:
        """Resolve one caller-supplied directory root under the reader's policy.

        This duplicates the minimum of the reader's path confinement (no
        traversal, no symlinked component, must stay under ``repo_root``)
        because :meth:`BoundedSourceToolkit._resolve` demands a regular file
        and therefore cannot validate a directory root itself; every file
        discovered below the root is still re-validated through
        :meth:`BoundedSourceToolkit._resolve`.

        Args:
            raw_root: The caller-supplied relative directory path.

        Returns:
            The normalized absolute directory path.

        Raises:
            ValueError: The path is malformed, escapes the root, or a
                component below the root is a symlink.
            NotADirectoryError: The resolved path is not an existing directory.
        """
        if not raw_root or raw_root != raw_root.strip():
            raise ValueError(f"{raw_root!r} is empty or padded with whitespace")
        if "\\" in raw_root:
            raise ValueError(f"{raw_root!r} contains a backslash")
        if Path(raw_root).is_absolute():
            raise ValueError(f"{raw_root!r} must be repository-relative")

        root = self.reader.policy.repo_root
        normalized = Path(os.path.normpath(os.path.join(str(root), raw_root)))
        if normalized != root and not normalized.is_relative_to(root):
            raise ValueError(f"{raw_root!r} normalizes outside the repository root")

        current = root
        for part in normalized.relative_to(root).parts:
            current = current / part
            try:
                mode = os.lstat(current).st_mode
            except FileNotFoundError:
                break
            if stat.S_ISLNK(mode):
                raise ValueError(f"{raw_root!r} traverses a symlinked component")
        if not normalized.is_dir():
            raise NotADirectoryError(f"{raw_root!r} is not a directory")
        return normalized

    @staticmethod
    def _decode_cursor(token: Optional[str]) -> tuple[int, int]:
        """Decode an opaque ``"<index>:<offset>"`` continuation cursor.

        Args:
            token: The caller-supplied cursor, or None.

        Returns:
            A ``(index, offset)`` tuple; ``(0, 0)`` for a missing/malformed
            cursor (Pydantic already rejects a malformed shape at admission).
        """
        if not token:
            return 0, 0
        left, _, right = token.partition(":")
        try:
            return int(left), int(right)
        except ValueError:
            return 0, 0

    @staticmethod
    def _policy_error_code(exc: Exception) -> str:
        """Map a policy/path exception onto a stable snake_case error code.

        Args:
            exc: The raised exception.

        Returns:
            A stable error code; unknown exception types fall back to
            ``"path_error"``.
        """
        return _POLICY_ERROR_CODES.get(type(exc).__name__, "path_error")

    # ------------------------------------------------------------------ #
    # Git -- fixed argv, full sha, no shell, no external diff tool
    # ------------------------------------------------------------------ #
    async def _do_git_status(self, request: GitStatusRequest, started: float) -> InspectionItem:
        """Report working-tree status without an index refresh or writes."""
        try:
            code, out, err = await self._run_git(
                ["status", "--porcelain=v2", "--untracked-files=normal"],
                timeout=_GIT_SUBPROCESS_TIMEOUT_SECONDS,
            )
        except _ItemTimeout:
            return InspectionItem(
                id=request.id,
                kind=request.kind,
                status="error",
                error_code="item_timeout",
                elapsed_ms=self._elapsed_ms(started),
            )
        if code != 0:
            return InspectionItem(
                id=request.id,
                kind=request.kind,
                status="error",
                error_code="git_status_failed",
                data={"stderr": err.decode("utf-8", "replace")[:500]},
                elapsed_ms=self._elapsed_ms(started),
            )
        entries = [line for line in out.decode("utf-8", "replace").splitlines() if line]
        return self._bound_item(
            InspectionItem(
                id=request.id,
                kind=request.kind,
                status="ok",
                data={"entries": entries},
                elapsed_ms=self._elapsed_ms(started),
            )
        )

    async def _do_git_diff_names(self, request: GitDiffNamesRequest, started: float) -> InspectionItem:
        """Compare two immutable full commit ids without an external diff tool."""
        try:
            code, out, err = await self._run_git(
                ["diff", "--name-only", "--end-of-options", request.base_sha, request.head_sha],
                timeout=_GIT_SUBPROCESS_TIMEOUT_SECONDS,
            )
        except _ItemTimeout:
            return InspectionItem(
                id=request.id,
                kind=request.kind,
                status="error",
                error_code="item_timeout",
                elapsed_ms=self._elapsed_ms(started),
            )
        if code != 0:
            return InspectionItem(
                id=request.id,
                kind=request.kind,
                status="error",
                error_code="git_diff_failed",
                data={"stderr": err.decode("utf-8", "replace")[:500]},
                elapsed_ms=self._elapsed_ms(started),
            )
        names = [line for line in out.decode("utf-8", "replace").splitlines() if line]
        return self._bound_item(
            InspectionItem(
                id=request.id,
                kind=request.kind,
                status="ok",
                data={"paths": names},
                elapsed_ms=self._elapsed_ms(started),
            )
        )

    async def _git_head(self) -> Optional[str]:
        """Snapshot the current commit id, or None outside a git repository.

        Returns:
            The 40-hex ``HEAD`` commit id, or None when it cannot be read
            (no repository, unborn HEAD, or the probe itself timed out).
        """
        try:
            code, out, _err = await self._run_git(
                ["rev-parse", "--verify", "--quiet", "HEAD"], timeout=_GIT_HEAD_TIMEOUT_SECONDS
            )
        except (_ItemTimeout, FileNotFoundError, OSError):
            return None
        if code != 0:
            return None
        sha = out.decode("utf-8", "replace").strip()
        return sha if len(sha) == 40 else None

    async def _run_git(self, argv: Sequence[str], *, timeout: float) -> tuple[int, bytes, bytes]:
        """Run one git subprocess with a fixed argv, killing it on timeout/cancel.

        Args:
            argv: Git arguments, without the leading ``git``.
            timeout: Seconds before the child is killed and reaped.

        Returns:
            A ``(exit_code, stdout, stderr)`` tuple.

        Raises:
            _ItemTimeout: The subprocess exceeded ``timeout``; it is killed
                and reaped before this is raised, so no orphan remains.
            asyncio.CancelledError: Re-raised after killing and reaping the
                child, so a cancelled batch leaves no orphan process.
        """
        proc = await asyncio.create_subprocess_exec(
            "git",
            *argv,
            cwd=str(self.reader.policy.repo_root),
            env={**os.environ, **_GIT_ENV_OVERRIDES},
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            async with asyncio.timeout(timeout):
                out, err = await proc.communicate()
        except (TimeoutError, asyncio.TimeoutError):
            proc.kill()
            await proc.wait()
            raise _ItemTimeout(f"git {' '.join(argv)!r} exceeded {timeout}s") from None
        except asyncio.CancelledError:
            proc.kill()
            await proc.wait()
            raise
        return proc.returncode, out, err

    # ------------------------------------------------------------------ #
    # Budgets
    # ------------------------------------------------------------------ #
    def _bound_item(self, item: InspectionItem) -> InspectionItem:
        """Shrink one item's ``data`` until it fits the per-item byte budget.

        Lists are trimmed from the end first, then long strings are halved;
        ``id``/``kind``/``status``/``error_code``/``elapsed_ms``/``continuation``
        are never touched, so an item's identity always survives.

        Args:
            item: The candidate item.

        Returns:
            The same item, mutated in place, with ``truncated`` set when
            anything was dropped.
        """
        if self._json_bytes(item.model_dump(mode="json")) <= _ITEM_BYTES_BUDGET:
            return item
        item.truncated = True
        for key, value in list(item.data.items()):
            if not isinstance(value, list):
                continue
            while value and self._json_bytes(item.model_dump(mode="json")) > _ITEM_BYTES_BUDGET:
                value.pop()
            item.data[key] = value
        if self._json_bytes(item.model_dump(mode="json")) <= _ITEM_BYTES_BUDGET:
            return item
        for key, value in list(item.data.items()):
            if not isinstance(value, str) or not value:
                continue
            while value and self._json_bytes(item.model_dump(mode="json")) > _ITEM_BYTES_BUDGET:
                value = value[: len(value) // 2]
                item.data[key] = value
        if self._json_bytes(item.model_dump(mode="json")) > _ITEM_BYTES_BUDGET:
            item.data = {"omitted": True}
        return item

    def _finalize(self, batch: InspectionBatch, budget: int, started: float) -> OperationResult:
        """Wrap the finished batch in a bounded :class:`OperationResult`.

        Args:
            batch: The fully assembled batch.
            budget: The caller's serialized-envelope byte budget.
            started: A ``perf_counter()`` reading taken at batch start.

        Returns:
            An ``OperationResult`` guaranteed to fit ``budget`` bytes. The
            batch executed successfully as a tool call even when individual
            items failed; ``data.partial``/``data.consistent`` carry that
            nuance instead of the top-level ``status``.
        """
        result = OperationResult(
            status="ok",
            operation="source_inspect_batch",
            data=batch.model_dump(mode="json"),
            truncated=batch.partial or any(item.truncated for item in batch.items),
            elapsed_ms=self._elapsed_ms(started),
        )
        return fit_to_budget(result, budget)

    @staticmethod
    def _elapsed_ms(started: float) -> int:
        """Return elapsed milliseconds since ``started``."""
        return max(0, int((time.perf_counter() - started) * 1000))

    @staticmethod
    def _json_bytes(obj: Any) -> int:
        """Return the UTF-8 byte length of the compact JSON encoding of ``obj``."""
        return len(json.dumps(obj, ensure_ascii=False).encode("utf-8"))

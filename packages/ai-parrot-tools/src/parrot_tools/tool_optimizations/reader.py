"""Bounded, streaming source reading for Claude Code / Codex (FEAT-543).

:class:`BoundedSourceToolkit` replaces "read the whole file into the
context window" with an explicitly bounded read. A file above **350 logical
lines or 64,000 on-disk bytes** (either threshold, both configurable)
requires an explicit inclusive 1-based range; every result carries the
file's SHA-256 revision and a continuation cursor so the caller can page
through it safely.

The reader never holds a whole file in memory and never returns a partial
line. ``ReadOnlyRepoToolkit.read_file`` is deliberately *not* reused: it
reads the entire file and then slices it (`repo/toolkit.py:227-243`). That
API is preserved untouched; this is a separate toolkit.

The helpers above the toolkit class are pure, synchronous and stdlib-only
so they can be reused for reference slices (TASK-3083) and host-side
threshold detection (TASK-3088) without dragging in toolkit state.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import stat
import time
from pathlib import Path
from typing import Any, NamedTuple, Optional

from parrot.tools.decorators import tool_schema
from parrot.tools.repo.confinement import PathOutsideRootError, SecretFileError
from pydantic import BaseModel

from .base import OptimizationToolkitBase
from .models import OperationResult, SourceInfo, SourceInfoArgs, SourceReadArgs, SourceResult
from .policy import PolicyError, SymlinkRejectedError, measure_json_bytes, resolve_operand

__all__ = (
    "FileIdentity",
    "RangeRead",
    "ReaderError",
    "NotRegularFileError",
    "LineTooLargeError",
    "InvalidEncodingError",
    "RangeOutOfBoundsError",
    "ConcurrentModificationError",
    "HashTimeoutError",
    "stat_regular",
    "sniff_binary",
    "count_lines_bounded",
    "sha256_stream",
    "read_line_range",
    "check_identity_unchanged",
    "BoundedSourceToolkit",
)

#: Chunk size for line counting and binary sniffing.
_CHUNK = 1 << 16
#: Chunk size for hashing.
_HASH_CHUNK = 1 << 20


class ReaderError(Exception):
    """Base class for bounded-reader failures."""


class NotRegularFileError(ReaderError):
    """Raised for a device, FIFO, socket or directory."""


class LineTooLargeError(ReaderError):
    """Raised when one line alone exceeds the caller's byte bound."""

    def __init__(self, line_no: int, at_least_bytes: int) -> None:
        """Initialize the error.

        Args:
            line_no: The 1-based line number.
            at_least_bytes: A lower bound on the line's size in bytes.
        """
        super().__init__(f"line {line_no} is at least {at_least_bytes} bytes")
        self.line_no = line_no
        self.at_least_bytes = at_least_bytes


class InvalidEncodingError(ReaderError):
    """Raised when a line is not valid UTF-8 (decoding is strict)."""

    def __init__(self, line_no: int) -> None:
        """Initialize the error.

        Args:
            line_no: The 1-based line number that failed to decode.
        """
        super().__init__(f"line {line_no} is not valid UTF-8")
        self.line_no = line_no


class RangeOutOfBoundsError(ReaderError):
    """Raised when the requested start line is past the end of the file."""

    def __init__(self, start_line: int, total_lines: int) -> None:
        """Initialize the error.

        Args:
            start_line: The requested start line.
            total_lines: The number of lines the file actually has.
        """
        super().__init__(f"start_line {start_line} is past the last line ({total_lines})")
        self.start_line = start_line
        self.total_lines = total_lines


class ConcurrentModificationError(ReaderError):
    """Raised when the file changed identity while it was being scanned."""


class HashTimeoutError(ReaderError):
    """Raised when hashing a very large file exceeded its deadline."""


class FileIdentity(NamedTuple):
    """A file's identity for concurrent-modification detection.

    Attributes:
        inode: The inode number.
        size: The on-disk size in bytes.
        mtime_ns: The modification time in nanoseconds.
    """

    inode: int
    size: int
    mtime_ns: int


class RangeRead(NamedTuple):
    """The outcome of reading an inclusive line range.

    Attributes:
        lines: The complete lines read, with their line endings preserved.
        actual_end: The last line number actually returned.
        eof: True when the file ended at or before the requested end.
    """

    lines: list[str]
    actual_end: int
    eof: bool


def stat_regular(path: Path) -> FileIdentity:
    """Stat ``path``, rejecting symlinks and anything but a regular file.

    ``os.lstat`` is used so a symlink is detected rather than followed.

    Args:
        path: The file to stat.

    Returns:
        The file's identity.

    Raises:
        FileNotFoundError: The path does not exist.
        SymlinkRejectedError: The path is a symlink.
        NotRegularFileError: The path is a device, FIFO, socket or directory.
    """
    info = os.lstat(path)
    if stat.S_ISLNK(info.st_mode):
        raise SymlinkRejectedError(f"{str(path)!r} is a symlink; symlinks are not followed")
    if not stat.S_ISREG(info.st_mode):
        raise NotRegularFileError(f"{str(path)!r} is not a regular file")
    return FileIdentity(inode=info.st_ino, size=info.st_size, mtime_ns=info.st_mtime_ns)


def check_identity_unchanged(before: FileIdentity, path: Path) -> None:
    """Verify the file has not changed identity since ``before`` was taken.

    Args:
        before: The identity captured before the scan.
        path: The file to re-stat.

    Raises:
        ConcurrentModificationError: The file changed while being scanned.
    """
    try:
        current = stat_regular(path)
    except (OSError, ReaderError) as exc:
        raise ConcurrentModificationError(f"{str(path)!r} changed while it was being read") from exc
    if current != before:
        raise ConcurrentModificationError(f"{str(path)!r} changed while it was being read")


def sniff_binary(path: Path, probe: int = 8192) -> bool:
    """Detect a binary file by looking for a NUL byte in its first bytes.

    Args:
        path: The file to sniff.
        probe: How many leading bytes to inspect.

    Returns:
        True when the probe contains a NUL byte.
    """
    with open(path, "rb") as handle:
        return b"\x00" in handle.read(probe)


def count_lines_bounded(path: Path, stop_after: int) -> tuple[int, bool]:
    """Count logical lines, stopping early once the bound is exceeded.

    A final line without a trailing newline still counts as a line.

    Args:
        path: The file to count.
        stop_after: The threshold to compare against.

    Returns:
        A ``(count, exceeded)`` tuple. When ``exceeded`` is True the exact
        count is unknown and ``count`` is ``stop_after + 1``.
    """
    count = 0
    ended_with_newline = True
    saw_any = False
    with open(path, "rb", buffering=_CHUNK) as handle:
        while True:
            chunk = handle.read(_CHUNK)
            if not chunk:
                break
            saw_any = True
            count += chunk.count(b"\n")
            ended_with_newline = chunk.endswith(b"\n")
            if count > stop_after:
                return stop_after + 1, True
    if saw_any and not ended_with_newline:
        count += 1
        if count > stop_after:
            return stop_after + 1, True
    return count, False


def sha256_stream(path: Path, *, deadline_seconds: float) -> str:
    """Hash a file's bytes in bounded memory, under a wall-clock deadline.

    Args:
        path: The file to hash.
        deadline_seconds: Maximum time to spend hashing.

    Returns:
        The lowercase hex SHA-256 digest.

    Raises:
        HashTimeoutError: Hashing exceeded the deadline.
    """
    deadline = time.monotonic() + deadline_seconds
    digest = hashlib.sha256()
    with open(path, "rb", buffering=_HASH_CHUNK) as handle:
        while True:
            chunk = handle.read(_HASH_CHUNK)
            if not chunk:
                break
            digest.update(chunk)
            if time.monotonic() > deadline:
                raise HashTimeoutError(f"hashing {str(path)!r} exceeded {deadline_seconds}s")
    return digest.hexdigest()


def read_line_range(path: Path, start_line: int, end_line: int, *, max_line_bytes: int) -> RangeRead:
    """Read an inclusive 1-based line range without loading the whole file.

    Memory is bounded by ``max_line_bytes`` plus the buffer size, never by
    the file's length: an oversized line is reported by number and size
    rather than being read into memory or silently cut.

    Args:
        path: The file to read.
        start_line: First line to return, 1-based inclusive.
        end_line: Last line to return, 1-based inclusive.
        max_line_bytes: The largest single line that may be materialized.

    Returns:
        The lines read, the last line number returned, and whether the file
        ended at or before ``end_line``.

    Raises:
        LineTooLargeError: A line exceeds ``max_line_bytes``.
        InvalidEncodingError: A line is not valid UTF-8.
        RangeOutOfBoundsError: ``start_line`` is past the last line.
    """
    lines: list[str] = []
    line_no = 0
    eof = False
    with open(path, "rb", buffering=_CHUNK) as handle:
        while True:
            raw = handle.readline(max_line_bytes + 1)
            if not raw:
                eof = True
                break
            line_no += 1
            if len(raw) > max_line_bytes and not raw.endswith(b"\n"):
                raise LineTooLargeError(line_no, len(raw))
            if line_no < start_line:
                continue
            try:
                lines.append(raw.decode("utf-8"))
            except UnicodeDecodeError as exc:
                raise InvalidEncodingError(line_no) from exc
            if line_no >= end_line:
                eof = handle.peek(1) == b""
                break
    if line_no < start_line:
        raise RangeOutOfBoundsError(start_line, line_no)
    return RangeRead(lines=lines, actual_end=min(end_line, line_no), eof=eof)


def _escaped_length(text: str) -> int:
    """Return the JSON-escaped UTF-8 byte cost of ``text``, without quotes.

    Args:
        text: The string to measure.

    Returns:
        The number of bytes the string contributes inside a JSON document.
    """
    return len(json.dumps(text, ensure_ascii=False).encode("utf-8")) - 2


class BoundedSourceToolkit(OptimizationToolkitBase):
    """Read source files under explicit line, byte and revision bounds.

    Example:
        >>> toolkit = BoundedSourceToolkit(repo_root="/path/to/repo")
        >>> info = await toolkit.source_info("src/big_module.py")
        >>> info.range_required
        True
    """

    arg_models: dict[str, type[BaseModel]] = {
        "source_info": SourceInfoArgs,
        "source_read": SourceReadArgs,
    }

    def _resolve(self, path: str) -> tuple[Path, str]:
        """Resolve a caller path under policy and require a regular file.

        Args:
            path: The caller-supplied path.

        Returns:
            A ``(absolute_path, relative_posix)`` tuple.

        Raises:
            PathOutsideRootError: The path escapes the repository root.
            SecretFileError: The path matches the secret deny-list.
            SymlinkRejectedError: The path or a parent is a symlink.
            NotRegularFileError: The path is not a regular file.
            PolicyError: The path does not exist.
        """
        target = resolve_operand(self.policy, path, must_exist=True)
        stat_regular(target)
        return target, target.relative_to(self.policy.repo_root).as_posix()

    def _path_error(self, operation: str, exc: Exception, started: float) -> OperationResult:
        """Map a path/identity exception onto a stable error code.

        Args:
            operation: The operation name.
            exc: The raised exception.
            started: A ``perf_counter()`` reading taken at operation start.

        Returns:
            The bounded error result.
        """
        mapping: list[tuple[type[Exception], str]] = [
            (SymlinkRejectedError, "symlink_rejected"),
            (SecretFileError, "secret_file"),
            (PathOutsideRootError, "path_outside_root"),
            (NotRegularFileError, "not_a_file"),
            (FileNotFoundError, "not_found"),
            (ConcurrentModificationError, "concurrent_modification"),
            (HashTimeoutError, "hash_timeout"),
            (PolicyError, "not_found"),
        ]
        for exc_type, code in mapping:
            if isinstance(exc, exc_type):
                return self._error(operation, code, str(exc), started=started)
        return self._error(operation, "read_failed", str(exc), started=started)

    @tool_schema(SourceInfoArgs)
    async def source_info(self, path: str) -> SourceInfo | OperationResult:
        """Report a file's size, revision and whether a read needs a range.

        No file content is ever returned by this tool.

        Args:
            path: A repository-relative file path.

        Returns:
            The file's bounded metadata, or an error result.
        """
        started = time.perf_counter()
        operation = "source_info"
        try:
            args = SourceInfoArgs(path=path)
        except Exception as exc:  # pydantic ValidationError
            return self._error(operation, "invalid_arguments", str(exc), started=started)

        try:
            return await asyncio.to_thread(self._info_blocking, args.path)
        except Exception as exc:  # noqa: BLE001 — mapped to a domain error
            return self._path_error(operation, exc, started)

    def _info_blocking(self, path: str) -> SourceInfo:
        """Collect file metadata off the event loop.

        Args:
            path: A repository-relative file path.

        Returns:
            The file's bounded metadata.

        Raises:
            ReaderError: The file is unreadable under the reader's rules.
        """
        target, relative = self._resolve(path)
        identity = stat_regular(target)
        if sniff_binary(target):
            raise InvalidEncodingError(0)
        count, exceeded = count_lines_bounded(target, self.policy.max_lines)
        is_large = exceeded or identity.size > self.policy.large_file_bytes
        digest = sha256_stream(target, deadline_seconds=self.policy.command_timeout_seconds)
        check_identity_unchanged(identity, target)
        return SourceInfo(
            path=relative,
            sha256=digest,
            size_bytes=identity.size,
            line_count=None if exceeded else count,
            is_large=is_large,
            max_lines=self.policy.max_lines,
            large_file_bytes=self.policy.large_file_bytes,
            range_required=is_large,
        )

    @tool_schema(SourceReadArgs)
    async def source_read(
        self,
        path: str,
        start_line: Optional[int] = None,
        end_line: Optional[int] = None,
        expected_sha256: Optional[str] = None,
    ) -> SourceResult | OperationResult:
        """Read a small file whole, or an explicit inclusive line range.

        Files above either configured threshold require both range ends.
        Only complete lines are returned; continue with ``next_line`` and
        ``expected_sha256`` to page through a file safely.

        Args:
            path: A repository-relative file path.
            start_line: First line to read, 1-based inclusive.
            end_line: Last line to read, 1-based inclusive.
            expected_sha256: The revision the caller expects; the read is
                refused when the file has changed since.

        Returns:
            The bounded slice, or an error result.
        """
        started = time.perf_counter()
        operation = "source_read"
        try:
            args = SourceReadArgs(path=path, start_line=start_line, end_line=end_line, expected_sha256=expected_sha256)
        except Exception as exc:  # pydantic ValidationError
            return self._error(operation, "invalid_arguments", str(exc), started=started)

        if args.start_line is not None and args.end_line is not None:
            span = args.end_line - args.start_line + 1
            if span > self.policy.max_lines:
                return self._error(
                    operation,
                    "range_too_large",
                    f"a range of {span} lines exceeds the {self.policy.max_lines}-line maximum",
                    details={"max_lines": self.policy.max_lines, "requested": span},
                    started=started,
                )

        try:
            return await asyncio.to_thread(self._read_blocking, args, started)
        except LineTooLargeError as exc:
            return self._error(
                operation,
                "line_too_large",
                str(exc),
                details={"line": exc.line_no, "bytes": exc.at_least_bytes},
                started=started,
            )
        except InvalidEncodingError as exc:
            return self._error(operation, "invalid_encoding", str(exc), details={"line": exc.line_no}, started=started)
        except RangeOutOfBoundsError as exc:
            return self._error(
                operation,
                "range_out_of_bounds",
                str(exc),
                details={"start_line": exc.start_line, "total_lines": exc.total_lines},
                started=started,
            )
        except _RangeRequired as exc:
            return self._error(operation, "range_required", str(exc), details=exc.details, started=started)
        except _StaleRevision as exc:
            return self._error(
                operation, "stale_revision", str(exc), details={"current_sha256": exc.current}, started=started
            )
        except _BinaryFile as exc:
            return self._error(operation, "binary_file", str(exc), started=started)
        except Exception as exc:  # noqa: BLE001 — mapped to a domain error
            return self._path_error(operation, exc, started)

    def _read_blocking(self, args: SourceReadArgs, started: float) -> SourceResult:
        """Perform the bounded read off the event loop.

        Args:
            args: The validated arguments.
            started: A ``perf_counter()`` reading taken at operation start.

        Returns:
            The bounded slice.

        Raises:
            ReaderError: The file is unreadable under the reader's rules.
            _RangeRequired: The file is large and no range was supplied.
            _StaleRevision: The file no longer matches ``expected_sha256``.
            _BinaryFile: The file is binary.
        """
        target, relative = self._resolve(args.path)
        identity = stat_regular(target)
        if sniff_binary(target):
            raise _BinaryFile(f"{relative!r} looks like a binary file")

        _count, exceeded = count_lines_bounded(target, self.policy.max_lines)
        is_large = exceeded or identity.size > self.policy.large_file_bytes
        if is_large and args.start_line is None:
            raise _RangeRequired(
                f"{relative!r} is large; supply both start_line and end_line",
                {
                    "max_lines": self.policy.max_lines,
                    "large_file_bytes": self.policy.large_file_bytes,
                    "size_bytes": identity.size,
                    "example": {"start_line": 1, "end_line": self.policy.max_lines},
                },
            )

        digest = sha256_stream(target, deadline_seconds=self.policy.command_timeout_seconds)
        if args.expected_sha256 is not None and args.expected_sha256 != digest:
            raise _StaleRevision(f"{relative!r} has changed since it was last read", digest)

        if identity.size == 0:
            check_identity_unchanged(identity, target)
            return SourceResult(
                path=relative,
                sha256=digest,
                size_bytes=0,
                start_line=1,
                end_line=0,
                content="",
                truncated=False,
                next_line=None,
                eof=True,
            )

        start = args.start_line if args.start_line is not None else 1
        end = args.end_line if args.end_line is not None else self.policy.max_lines
        span = read_line_range(target, start, end, max_line_bytes=self.policy.max_result_bytes)

        kept, used, envelope_budget = self._fit_lines(relative, digest, identity.size, start, span.lines)
        if not kept:
            first = span.lines[0]
            raise LineTooLargeError(start, len(first.encode("utf-8")))

        returned_end = start + len(kept) - 1
        all_requested_returned = returned_end >= span.actual_end
        eof = span.eof and all_requested_returned
        truncated = not all_requested_returned
        del used, envelope_budget

        check_identity_unchanged(identity, target)
        return SourceResult(
            path=relative,
            sha256=digest,
            size_bytes=identity.size,
            start_line=start,
            end_line=returned_end,
            content="".join(kept),
            truncated=truncated,
            next_line=None if eof else returned_end + 1,
            eof=eof,
        )

    def _fit_lines(
        self, relative: str, digest: str, size: int, start: int, lines: list[str]
    ) -> tuple[list[str], int, int]:
        """Select the complete lines that fit the serialized byte budget.

        Args:
            relative: The repo-relative path.
            digest: The file's SHA-256 revision.
            size: The file's size in bytes.
            start: The first line number.
            lines: The candidate lines.

        Returns:
            A ``(kept_lines, bytes_used, budget)`` tuple. ``kept_lines`` is
            empty when even the first line does not fit.
        """
        envelope = measure_json_bytes(
            SourceResult(
                path=relative,
                sha256=digest,
                size_bytes=size,
                start_line=start,
                end_line=start + max(0, len(lines) - 1),
                content="",
                truncated=True,
                next_line=start + len(lines),
                eof=False,
            ).model_dump(mode="json")
        )
        budget = self.policy.max_result_bytes - envelope
        kept: list[str] = []
        used = 0
        for line in lines:
            cost = _escaped_length(line)
            if used + cost > budget:
                break
            kept.append(line)
            used += cost
        return kept, used, budget


class _RangeRequired(ReaderError):
    """Internal signal: a large file was read without an explicit range."""

    def __init__(self, message: str, details: dict[str, Any]) -> None:
        """Initialize the signal.

        Args:
            message: The human-readable explanation.
            details: Structured guidance, including an example range.
        """
        super().__init__(message)
        self.details = details


class _StaleRevision(ReaderError):
    """Internal signal: the file no longer matches the expected revision."""

    def __init__(self, message: str, current: str) -> None:
        """Initialize the signal.

        Args:
            message: The human-readable explanation.
            current: The file's current SHA-256 digest.
        """
        super().__init__(message)
        self.current = current


class _BinaryFile(ReaderError):
    """Internal signal: the file is binary and has no text representation."""

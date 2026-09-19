"""Bounded workspace snapshots and position conversion for the LSP pilot (FEAT-580, M1).

Two responsibilities live here, both pure/off-event-loop by construction:

- :func:`capture_workspace` builds a deterministic manifest of the files a
  Pyright checkpoint depends on (Git tracked + non-ignored untracked
  ``.py``/``.pyi`` files, plus lock/config files), then hashes and
  optionally reads them **in an owned subprocess** so the event loop never
  blocks on file I/O. The subprocess performs a stable
  open/fstat/read/fstat sequence per file to detect ordinary concurrent
  edits, and is killed/reaped on timeout or cancellation.
- :func:`to_lsp_position` / :func:`from_lsp_range` convert between the
  toolkit's public one-based Unicode coordinates and the zero-based
  UTF-16 coordinates the LSP wire protocol requires, including surrogate
  boundary handling.

Nothing in this module calls into Pyright or the LSP session (``session.py``,
a later task); it only prepares the evidence those modules need.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import os
import stat
import sys
from pathlib import Path, PurePosixPath
from typing import Any

from .models import LSPConfig, LSPFailure, SourceRange, WorkspaceSnapshot

#: Marker argv token that switches this module's ``__main__`` entry point
#: into the synchronous, stdlib-only worker loop instead of doing nothing.
_WORKER_ARGV_MARKER = "--lsp-snapshot-worker"

#: Bounds from spec §2.10 ("Bounds") relevant to M1.
_MAX_FILE_BYTES = 1 * 1024 * 1024  # 1 MiB per file
_MAX_MANIFEST_FILES = 10_000
_MAX_MANIFEST_BYTES = 128 * 1024 * 1024  # 128 MiB
_WORKER_DEADLINE_S = 10.0
_MANIFEST_PASS_DEADLINE_S = 10.0
#: Defensive cap on the worker's own JSON response so a runaway/garbled
#: worker can never make the parent buffer an unbounded amount of memory.
_MAX_WORKER_RESPONSE_BYTES = 64 * 1024 * 1024

#: Config/lock files (by basename) that are part of the deterministic
#: manifest wherever they live in-root, in addition to ``.py``/``.pyi``.
_TRACKED_CONFIG_NAMES = frozenset({"pyrightconfig.json", "pyproject.toml", "uv.lock", ".python-version"})
_SOURCE_SUFFIXES = frozenset({".py", ".pyi"})

#: This distribution's own ``src`` root, resolved once at import time (not
#: inside the async worker-dispatch function) so the owned worker
#: subprocess always imports the exact same ``snapshot.py`` that is
#: running, even across worktrees sharing one editable-installed venv.
_PACKAGE_SRC_ROOT = str(Path(__file__).resolve().parents[2])

__all__ = ["capture_workspace", "to_lsp_position", "from_lsp_range"]


# ---------------------------------------------------------------------------
# Public: workspace snapshot capture
# ---------------------------------------------------------------------------


async def capture_workspace(config: LSPConfig, paths: list[str]) -> WorkspaceSnapshot:
    """Return a bounded, stable workspace snapshot and digest.

    Builds the deterministic manifest (Git tracked + non-ignored untracked
    ``.py``/``.pyi`` files, tracked deletions as tombstones, and in-root
    lock/Pyright-config files), then hashes/reads it off the event loop in
    an owned subprocess.

    Args:
        config: Trusted, validated toolkit configuration.
        paths: Repository-relative paths whose exact source text must be
            returned in ``requested_text`` (e.g. the file(s) a navigation
            or diagnostics call targets). Every entry must already be a
            member of the deterministic manifest.

    Returns:
        A :class:`WorkspaceSnapshot` with a digest sensitive to every
        manifest file's content, tombstoned deletions, and the effective
        configuration.

    Raises:
        LSPFailure: With one fixed operational code — ``path_outside_root``
            for traversal/escaping symlinks, ``unsupported_language`` for a
            requested non-Python/stub path, ``invalid_request`` for an
            ignored/untracked-and-unlisted requested path, ``file_missing``
            for a requested tombstoned path, ``file_too_large``/
            ``workspace_limit`` for exceeded bounds, ``invalid_encoding``
            for undecodable content, ``source_changed`` for a detected
            concurrent edit, ``request_timeout`` for a worker deadline
            miss, or ``resource_limit``/``protocol_error`` for a worker
            process/transport failure.
        asyncio.CancelledError: Propagated after the owned worker process
            is killed and reaped.
    """
    repo_root = config.repo_root
    if not repo_root.is_dir():
        raise LSPFailure("resource_limit", f"repo_root does not exist or is not a directory: {repo_root}")
    canonical_root = repo_root.resolve()

    manifest, deleted = await _build_manifest(repo_root)

    if len(manifest) > _MAX_MANIFEST_FILES:
        raise LSPFailure(
            "workspace_limit", f"workspace manifest has {len(manifest)} files, exceeding {_MAX_MANIFEST_FILES}"
        )

    _validate_requested_paths(manifest, deleted, paths)

    targets = sorted(manifest)
    requested = set(paths)

    response = await _run_snapshot_worker(repo_root, canonical_root, targets, requested)
    file_hashes, requested_text, missing_from_worker, total_bytes = _apply_worker_results(response)

    if total_bytes > _MAX_MANIFEST_BYTES:
        raise LSPFailure(
            "workspace_limit", f"workspace manifest content is {total_bytes} bytes, exceeding {_MAX_MANIFEST_BYTES}"
        )

    missing_paths = sorted(deleted | missing_from_worker)
    config_digest = _compute_config_digest(config)
    digest = _compute_workspace_digest(file_hashes, missing_paths, config_digest)

    return WorkspaceSnapshot(
        digest=digest,
        file_hashes=file_hashes,
        requested_text=requested_text,
        config_digest=config_digest,
        missing_paths=missing_paths,
    )


# ---------------------------------------------------------------------------
# Manifest construction (Git-backed, async, no content I/O)
# ---------------------------------------------------------------------------


async def _build_manifest(repo_root: Path) -> tuple[set[str], set[str]]:
    """Return ``(manifest_paths, deleted_tombstones)`` for ``repo_root``.

    ``manifest_paths`` is every live (non-deleted) tracked file plus every
    non-ignored untracked file that is manifest-relevant (see
    :func:`_is_manifest_relevant`). ``deleted_tombstones`` is every
    manifest-relevant tracked path Git reports as deleted in the worktree.
    """
    tracked = _decode_git_paths(await _run_git(repo_root, ["ls-files", "-z"]))
    deleted = _decode_git_paths(await _run_git(repo_root, ["ls-files", "-z", "--deleted"]))
    untracked = _decode_git_paths(await _run_git(repo_root, ["ls-files", "-z", "--others", "--exclude-standard"]))

    live_tracked = tracked - deleted
    candidates = live_tracked | untracked

    manifest = {path for path in candidates if _is_manifest_relevant(path)}
    deleted_relevant = {path for path in deleted if _is_manifest_relevant(path)}
    return manifest, deleted_relevant


def _is_manifest_relevant(rel_path: str) -> bool:
    """Return whether ``rel_path`` belongs in the deterministic manifest."""
    name = PurePosixPath(rel_path).name
    if name in _TRACKED_CONFIG_NAMES:
        return True
    if name == "pyrightconfig.json":
        return True
    return PurePosixPath(rel_path).suffix in _SOURCE_SUFFIXES


def _decode_git_paths(raw: bytes) -> set[str]:
    """Decode NUL-separated ``git ls-files -z`` output into a path set."""
    decoded: set[str] = set()
    for chunk in raw.split(b"\x00"):
        if not chunk:
            continue
        try:
            decoded.add(chunk.decode("utf-8"))
        except UnicodeDecodeError as exc:
            raise LSPFailure("invalid_encoding", "git manifest contains a non-UTF-8 path") from exc
    return decoded


async def _run_git(repo_root: Path, args: list[str]) -> bytes:
    """Run one bounded, argv-list ``git`` command scoped to ``repo_root``."""
    argv = ["git", "-C", str(repo_root), *args]
    try:
        proc = await asyncio.create_subprocess_exec(
            *argv,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError as exc:
        raise LSPFailure("resource_limit", "git executable not found") from exc

    try:
        stdout_data, stderr_data = await asyncio.wait_for(proc.communicate(), timeout=_MANIFEST_PASS_DEADLINE_S)
    except asyncio.TimeoutError as exc:
        await _kill_and_reap(proc)
        raise LSPFailure("resource_limit", f"git {' '.join(args)} exceeded its manifest-pass deadline") from exc
    except asyncio.CancelledError:
        await _kill_and_reap(proc)
        raise

    if proc.returncode != 0:
        detail = stderr_data.decode("utf-8", errors="replace").strip()
        raise LSPFailure("resource_limit", f"git {' '.join(args)} failed: {detail}")
    return stdout_data


async def _kill_and_reap(proc: "asyncio.subprocess.Process") -> None:
    """Kill an owned child (if still alive) and reap it, swallowing errors."""
    if proc.returncode is None:
        with contextlib.suppress(ProcessLookupError):
            proc.kill()
    with contextlib.suppress(Exception):
        await proc.wait()


# ---------------------------------------------------------------------------
# Requested-path validation (cheap, in-process; no content I/O)
# ---------------------------------------------------------------------------


def _validate_requested_paths(manifest: set[str], deleted: set[str], paths: list[str]) -> None:
    """Reject any requested path outside the deterministic manifest.

    Raises:
        LSPFailure: ``path_outside_root`` for a malformed/traversal shape,
            ``unsupported_language`` for a non-``.py``/``.pyi`` suffix,
            ``file_missing`` for a tracked-but-deleted tombstone, or
            ``invalid_request`` for an ignored/untracked-and-unlisted path.
    """
    for raw_path in paths:
        _validate_relative_shape(raw_path)
        if PurePosixPath(raw_path).suffix not in _SOURCE_SUFFIXES:
            raise LSPFailure("unsupported_language", f"{raw_path} is not a supported Python source/stub file")
        if raw_path in deleted:
            raise LSPFailure("file_missing", f"{raw_path} is a tracked file deleted in the worktree")
        if raw_path not in manifest:
            raise LSPFailure("invalid_request", f"{raw_path} is not part of the tracked/untracked workspace manifest")


def _validate_relative_shape(value: str) -> None:
    """Reject a non-repository-relative or traversal-shaped path string."""
    if not value or "\x00" in value or "\\" in value or value.startswith("/"):
        raise LSPFailure("path_outside_root", f"invalid repository-relative path: {value!r}")
    posix = PurePosixPath(value)
    if posix.is_absolute() or ".." in posix.parts:
        raise LSPFailure("path_outside_root", f"invalid repository-relative path: {value!r}")


# ---------------------------------------------------------------------------
# Owned subprocess worker: dispatch/response handling (parent side)
# ---------------------------------------------------------------------------


async def _run_snapshot_worker(
    repo_root: Path, canonical_root: Path, targets: list[str], requested: set[str]
) -> dict[str, Any]:
    """Spawn the owned hashing/reading worker and return its parsed response.

    The worker is always launched with the *current* interpreter
    (:data:`sys.executable`), not ``config.python_path`` — the latter is an
    operator-provisioned target environment for Pyright's own analysis and
    is not guaranteed to have ``ai-parrot-tools`` installed. ``PYTHONPATH``
    is set from this module's own file location so the worker imports the
    exact same ``snapshot.py`` that is running, even across worktrees.
    """
    request = {
        "repo_root": str(repo_root),
        "canonical_root": str(canonical_root),
        "targets": targets,
        "requested": sorted(requested),
        "max_file_bytes": _MAX_FILE_BYTES,
    }
    payload = (json.dumps(request) + "\n").encode("utf-8")

    env = dict(os.environ)
    existing_path = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = f"{_PACKAGE_SRC_ROOT}{os.pathsep}{existing_path}" if existing_path else _PACKAGE_SRC_ROOT

    argv = [sys.executable, "-m", "parrot_tools.lsp.snapshot", _WORKER_ARGV_MARKER]
    proc = await asyncio.create_subprocess_exec(
        *argv,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=str(repo_root),
        env=env,
    )

    try:
        stdout_data, _stderr_data = await asyncio.wait_for(proc.communicate(input=payload), timeout=_WORKER_DEADLINE_S)
    except asyncio.TimeoutError as exc:
        await _kill_and_reap(proc)
        raise LSPFailure("request_timeout", "workspace snapshot worker exceeded its 10-second deadline") from exc
    except asyncio.CancelledError:
        await _kill_and_reap(proc)
        raise

    if proc.returncode != 0:
        raise LSPFailure("resource_limit", f"workspace snapshot worker exited with code {proc.returncode}")

    if len(stdout_data) > _MAX_WORKER_RESPONSE_BYTES:
        raise LSPFailure("resource_limit", "workspace snapshot worker response exceeded the bounded JSON I/O cap")

    line = stdout_data.splitlines()[0] if stdout_data.strip() else b""
    if not line:
        raise LSPFailure("resource_limit", "workspace snapshot worker returned no output")

    try:
        response = json.loads(line.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise LSPFailure("protocol_error", "workspace snapshot worker returned malformed JSON") from exc

    if not isinstance(response, dict):
        raise LSPFailure("protocol_error", "workspace snapshot worker returned a non-object JSON response")
    return response


def _apply_worker_results(response: dict[str, Any]) -> tuple[dict[str, str], dict[str, str], set[str], int]:
    """Aggregate the worker's per-path results into snapshot fields.

    Returns:
        ``(file_hashes, requested_text, missing_paths, total_bytes_read)``.

    Raises:
        LSPFailure: The lexicographically-first per-path error, or
            ``protocol_error`` for a malformed response shape.
    """
    results = response.get("results")
    if not isinstance(results, list):
        raise LSPFailure("protocol_error", "workspace snapshot worker response is missing a results list")

    file_hashes: dict[str, str] = {}
    requested_text: dict[str, str] = {}
    missing: set[str] = set()
    total_bytes = 0
    errors: list[tuple[str, str, str]] = []

    for entry in results:
        if not isinstance(entry, dict) or "path" not in entry:
            raise LSPFailure("protocol_error", "workspace snapshot worker returned a malformed result entry")
        path = entry["path"]

        if entry.get("missing"):
            missing.add(path)
            continue

        if "error" in entry:
            errors.append((path, entry["error"], entry.get("detail", "")))
            continue

        sha256 = entry.get("sha256")
        if not sha256:
            raise LSPFailure("protocol_error", f"workspace snapshot worker omitted a hash for {path}")
        file_hashes[path] = sha256
        total_bytes += int(entry.get("size", 0))
        if "text" in entry:
            requested_text[path] = entry["text"]

    if errors:
        errors.sort(key=lambda item: item[0])
        _path, code, detail = errors[0]
        raise LSPFailure(code, detail)

    return file_hashes, requested_text, missing, total_bytes


# ---------------------------------------------------------------------------
# Owned subprocess worker: synchronous per-file processing (child side)
# ---------------------------------------------------------------------------


def _process_target(
    repo_root: str, rel_path: str, canonical_root: str, need_text: bool, max_file_bytes: int
) -> dict[str, Any]:
    """Hash/read one manifest file with a stable open/fstat/read/fstat pass.

    Runs entirely with ordinary synchronous ``os`` calls — no thread
    offload, no asyncio — because this function only ever executes inside
    the owned worker subprocess, off the parent's event loop.

    Returns:
        One of ``{"path": ..., "sha256": ..., "size": ..., "text"?: ...}``,
        ``{"path": ..., "missing": True}``, or
        ``{"path": ..., "error": <fixed code>, "detail": str}``.
    """
    try:
        _validate_relative_shape(rel_path)
    except LSPFailure as exc:
        return {"path": rel_path, "error": exc.code, "detail": exc.detail}

    abs_path = os.path.join(repo_root, rel_path)
    real_path = os.path.realpath(abs_path)
    if real_path != canonical_root and not real_path.startswith(canonical_root + os.sep):
        return {"path": rel_path, "error": "path_outside_root", "detail": f"{rel_path} escapes repo_root"}

    try:
        # O_NONBLOCK is essential here: opening a FIFO for reading blocks
        # until a writer connects. It is a no-op for regular files.
        fd = os.open(abs_path, os.O_RDONLY | os.O_NONBLOCK)
    except FileNotFoundError:
        return {"path": rel_path, "missing": True}
    except OSError as exc:
        return {"path": rel_path, "error": "invalid_request", "detail": f"cannot open {rel_path}: {exc}"}

    try:
        st_before = os.fstat(fd)
        if not stat.S_ISREG(st_before.st_mode):
            return {"path": rel_path, "error": "invalid_request", "detail": f"{rel_path} is not a regular file"}
        if st_before.st_size > max_file_bytes:
            return {
                "path": rel_path,
                "error": "file_too_large",
                "detail": f"{rel_path} is {st_before.st_size} bytes, exceeding {max_file_bytes}",
            }

        chunks: list[bytes] = []
        remaining = st_before.st_size
        while remaining > 0:
            chunk = os.read(fd, remaining)
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        data = b"".join(chunks)

        st_after = os.fstat(fd)
        if st_after.st_size != st_before.st_size or st_after.st_mtime_ns != st_before.st_mtime_ns:
            return {"path": rel_path, "error": "source_changed", "detail": f"{rel_path} changed while being read"}
    finally:
        os.close(fd)

    digest = hashlib.sha256(data).hexdigest()
    result: dict[str, Any] = {"path": rel_path, "sha256": digest, "size": len(data)}
    if need_text:
        try:
            result["text"] = data.decode("utf-8", errors="strict")
        except UnicodeDecodeError:
            return {"path": rel_path, "error": "invalid_encoding", "detail": f"{rel_path} is not valid UTF-8"}
    return result


def _run_worker() -> None:
    """Worker entry point: one JSON request on stdin, one JSON response on stdout.

    Never imports anything beyond the stdlib symbols already imported at
    module scope; never touches an event loop.
    """
    raw = sys.stdin.buffer.readline()
    request = json.loads(raw.decode("utf-8")) if raw.strip() else {}

    repo_root = request.get("repo_root", "")
    canonical_root = request.get("canonical_root", repo_root)
    targets: list[str] = request.get("targets", [])
    requested = set(request.get("requested", []))
    max_file_bytes = int(request.get("max_file_bytes", _MAX_FILE_BYTES))

    results = [
        _process_target(repo_root, rel_path, canonical_root, rel_path in requested, max_file_bytes)
        for rel_path in targets
    ]

    sys.stdout.buffer.write(json.dumps({"results": results}).encode("utf-8") + b"\n")
    sys.stdout.buffer.flush()


# ---------------------------------------------------------------------------
# Digests
# ---------------------------------------------------------------------------


def _compute_config_digest(config: LSPConfig) -> str:
    """Hash the effective configuration fields that gate cache reuse."""
    payload = {
        "repo_root": str(config.repo_root),
        "server_command": list(config.server_command),
        "version_command": list(config.version_command),
        "expected_server_version": config.expected_server_version,
        "python_path": str(config.python_path),
        "source_roots": [str(path) for path in config.source_roots],
        "environment_id": config.environment_id,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _compute_workspace_digest(file_hashes: dict[str, str], missing_paths: list[str], config_digest: str) -> str:
    """Deterministically combine file hashes, tombstones, and config digest."""
    hasher = hashlib.sha256()
    hasher.update(config_digest.encode("utf-8"))
    for path in sorted(file_hashes):
        hasher.update(b"\x00F\x00")
        hasher.update(path.encode("utf-8"))
        hasher.update(b"\x00")
        hasher.update(file_hashes[path].encode("utf-8"))
    for path in sorted(set(missing_paths)):
        hasher.update(b"\x00T\x00")
        hasher.update(path.encode("utf-8"))
    return hasher.hexdigest()


# ---------------------------------------------------------------------------
# Position conversion (pure; no I/O)
# ---------------------------------------------------------------------------


def to_lsp_position(text: str, line: int, column: int) -> dict[str, int]:
    """Convert a validated one-based Unicode position to zero-based UTF-16.

    Args:
        text: The exact decoded file content the position is relative to.
        line: One-based line number (a value one past the last line
            denotes the end-of-file position, valid only with ``column=1``).
        column: One-based Unicode code-point column; ``text[:column - 1]``
            on the target line precedes it.

    Returns:
        ``{"line": <zero-based line>, "character": <zero-based UTF-16 code unit>}``.

    Raises:
        LSPFailure: ``position_out_of_range`` for a non-positive line/column
            or a position past the end of the file/line.
    """
    if line < 1 or column < 1:
        raise LSPFailure(
            "position_out_of_range", f"line/column must be 1-based positive integers: line={line}, column={column}"
        )

    lines = text.splitlines(keepends=False)
    total_lines = len(lines)

    if line > total_lines + 1:
        raise LSPFailure("position_out_of_range", f"line {line} is beyond the end of the file ({total_lines} lines)")

    if line == total_lines + 1:
        if column != 1:
            raise LSPFailure("position_out_of_range", f"column {column} is beyond end-of-file at line {line}")
        line_text = ""
    else:
        line_text = lines[line - 1]

    line_length = len(line_text)
    if column - 1 > line_length:
        raise LSPFailure("position_out_of_range", f"column {column} exceeds line {line} length ({line_length})")

    prefix = line_text[: column - 1]
    return {"line": line - 1, "character": _utf16_length(prefix)}


def from_lsp_range(text: str, path: str, lsp_range: dict[str, Any]) -> SourceRange:
    """Convert a zero-based UTF-16 LSP range back to a one-based Unicode :class:`SourceRange`.

    Args:
        text: The exact decoded file content the range is relative to.
        path: Repository-relative POSIX path to attach to the result.
        lsp_range: A raw LSP ``Range`` object: ``{"start": {"line", "character"}, "end": {...}}``.

    Raises:
        LSPFailure: ``position_out_of_range`` past the end of the file/line,
            or ``protocol_error`` for a negative coordinate or a position
            that splits a UTF-16 surrogate pair.
    """
    start = lsp_range["start"]
    end = lsp_range["end"]
    start_line, start_column = _from_lsp_position(text, int(start["line"]), int(start["character"]))
    end_line, end_column = _from_lsp_position(text, int(end["line"]), int(end["character"]))
    return SourceRange(
        path=path,
        start_line=start_line,
        start_column=start_column,
        end_line=end_line,
        end_column=end_column,
    )


def _from_lsp_position(text: str, lsp_line: int, lsp_character: int) -> tuple[int, int]:
    """Convert one zero-based UTF-16 LSP position to a one-based Unicode ``(line, column)``."""
    if lsp_line < 0 or lsp_character < 0:
        raise LSPFailure(
            "protocol_error", f"server returned a negative LSP position: line={lsp_line}, character={lsp_character}"
        )

    lines = text.splitlines(keepends=False)
    total_lines = len(lines)

    if lsp_line > total_lines:
        raise LSPFailure(
            "position_out_of_range", f"server position line {lsp_line} is beyond end of file ({total_lines} lines)"
        )

    line_text = lines[lsp_line] if lsp_line < total_lines else ""
    line = lsp_line + 1

    remaining = lsp_character
    column = 1
    for ch in line_text:
        if remaining == 0:
            break
        units = 2 if ord(ch) > 0xFFFF else 1
        if units > remaining:
            raise LSPFailure("protocol_error", f"server position splits a surrogate pair at line {line}")
        remaining -= units
        column += 1

    if remaining > 0:
        raise LSPFailure("position_out_of_range", f"server character {lsp_character} exceeds line {line} length")

    return line, column


def _utf16_length(value: str) -> int:
    """Return the number of UTF-16 code units ``value`` would occupy."""
    return sum(2 if ord(ch) > 0xFFFF else 1 for ch in value)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == _WORKER_ARGV_MARKER:
        _run_worker()

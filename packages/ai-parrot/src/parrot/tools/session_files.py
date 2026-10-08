"""Agent-facing view of the per-session file store."""

from __future__ import annotations

import asyncio
from pathlib import Path
import shutil
import tempfile
from typing import Any, Dict, Optional

from parrot.interfaces.file.session import SessionFileError, SessionFileStore
from parrot.tools.toolkit import AbstractToolkit
from parrot.utils.helpers import current_context

#: Backends whose namespace is remote — always selectable by the model.
REMOTE_BACKENDS = frozenset({"s3", "gcs", "sharepoint", "onedrive", "gdrive"})

#: Local-filesystem backends — selectable ONLY when the operator configured a root.
#: ``"temp"`` is deliberately absent: ``import_remote_file`` builds a fresh
#: ``FileManagerToolkit`` per call, so a ``TempFileManager``'s private directory is
#: always empty and the backend can never serve a real import (FEAT-643 §3 M1).
LOCAL_BACKENDS = frozenset({"fs"})

#: Every backend this toolkit can ever address.
SUPPORTED_BACKENDS = REMOTE_BACKENDS | LOCAL_BACKENDS

#: Largest single session file accepted by this toolkit, in bytes.
#: Above Jira's 10 MB default attachment limit (jiratoolkit.py:392) so a legitimate
#: document is never blocked, far below FileManagerToolkit's 100 MB.
DEFAULT_MAX_FILE_BYTES = 25 * 1024 * 1024


class NoBoundSession(SessionFileError):
    """No RequestContext is bound to this asyncio task."""

    code = "no_session"


class FileTooLarge(SessionFileError):
    """The file exceeds the toolkit's per-file byte cap."""

    code = "file_too_large"


def _validate_remote_path(remote_path: str) -> str:
    """Return *remote_path* normalized, or raise for an unsafe storage-side path.

    Applies to EVERY backend: a ``..`` segment is meaningless in an S3 key or a
    Graph drive-relative path, and a containment bypass in a local one.

    Args:
        remote_path: Storage-side path supplied by the model.

    Returns:
        The path with ``\\`` normalized to ``/``, a leading ``./`` dropped and
        empty segments collapsed.

    Raises:
        ValueError: If the path is empty, absolute, drive-qualified, UNC,
            contains a NUL byte, or contains a ``..`` segment.
    """
    if not remote_path or not remote_path.strip():
        raise ValueError("remote_path is required and must not be blank")
    if "\x00" in remote_path:
        raise ValueError("remote_path must not contain a NUL byte")

    # Normalize separators BEFORE any check, so a Windows-style traversal cannot
    # slip past a POSIX-only test.
    normalized = remote_path.replace("\\", "/").strip()
    if normalized.startswith("/"):
        raise ValueError(f"remote_path must be relative, not absolute: {remote_path!r}")
    if len(normalized) >= 2 and normalized[1] == ":" and normalized[0].isalpha():
        raise ValueError(f"remote_path must not be drive-qualified: {remote_path!r}")

    segments = [segment for segment in normalized.split("/") if segment not in ("", ".")]
    if any(segment == ".." for segment in segments):
        raise ValueError(f"remote_path must not contain a '..' segment: {remote_path!r}")
    if not segments:
        raise ValueError(f"remote_path resolves to nothing: {remote_path!r}")
    return "/".join(segments)


class SessionFileToolkit(AbstractToolkit):
    """Lists and stages the files of the CURRENT session, addressed by handle."""

    tool_prefix: str = "sf"  # -> sf_list_session_files, sf_store_generated_file

    def __init__(
        self,
        store: Optional[SessionFileStore] = None,
        local_import_root: Optional[Path | str] = None,
        max_file_bytes: int = DEFAULT_MAX_FILE_BYTES,
    ) -> None:
        """Initialize the toolkit.

        Args:
            store: Session file store; defaults to the ``OUTPUT_DIR``-rooted store.
            local_import_root: Directory the ``"fs"`` backend is confined to. When
                ``None`` (the default) ``"fs"`` is refused outright, so no agent can
                read the server's working directory.
            max_file_bytes: Largest single file this toolkit will store, in bytes.

        Raises:
            ValueError: If *local_import_root* is not an existing directory, or
                *max_file_bytes* is not positive.
        """
        super().__init__()
        self.store = store or SessionFileStore()
        if max_file_bytes <= 0:
            raise ValueError(f"max_file_bytes must be positive, got {max_file_bytes!r}")
        self.max_file_bytes = max_file_bytes
        self.local_import_root: Optional[Path] = None
        if local_import_root is not None:
            resolved_root = Path(local_import_root).resolve()
            if not resolved_root.is_dir():
                raise ValueError(f"local_import_root must be an existing directory: {local_import_root!r}")
            self.local_import_root = resolved_root

    def _require_session(self) -> str:
        """Return the bound session id, or raise NoBoundSession.

        Reads current_context(); never falls back to a default session, so two
        concurrent sessions cannot collide on one reusable toolkit instance.

        Raises:
            NoBoundSession: If no context is bound or it carries no session id.
        """
        ctx = current_context()
        session_id = getattr(ctx, "session_id", None) if ctx is not None else None
        if not session_id:
            raise NoBoundSession("No session is bound to this request; session files are unavailable")
        return str(session_id)

    def _check_size(self, size: int, filename: str) -> None:
        """Refuse *size* when it exceeds the configured per-file cap.

        Args:
            size: Byte count about to be stored.
            filename: Name used in the refusal message.

        Raises:
            FileTooLarge: If *size* exceeds ``self.max_file_bytes``.
        """
        if size > self.max_file_bytes:
            raise FileTooLarge(
                f"{filename!r} is {size} bytes, over the {self.max_file_bytes}-byte per-file limit"
            )

    async def list_session_files(self) -> Dict[str, Any]:
        """List the files available in this session.

        Returns {"files": [{"file_id", "filename", "mime_type", "size", "origin"}]}.
        Pass a file_id to jira_add_attachment or jira_add_comment to attach it.
        """
        session_id = self._require_session()
        records = await self.store.list_files(session_id)
        return {
            "files": [
                {
                    "file_id": r.file_id,
                    "filename": r.filename,
                    "mime_type": r.mime_type,
                    "size": r.size,
                    "origin": r.origin,
                }
                for r in records
            ]
        }

    async def store_generated_file(self, filename: str, content: str) -> Dict[str, Any]:
        """Store text this agent produced as a session file, returning its handle.

        Returns {"file_id", "filename", "size"}. The file_id can then be passed to
        jira_add_attachment to attach the file to an issue.

        Args:
            filename: Name for the file, e.g. "report.md".
            content: Text content, stored as UTF-8.
        """
        session_id = self._require_session()
        data = content.encode("utf-8")
        self._check_size(len(data), filename)
        record = await self.store.put_bytes(session_id, filename, data, origin="generated")
        return {"file_id": record.file_id, "filename": record.filename, "size": record.size}

    async def import_remote_file(
        self, backend: str, remote_path: str, filename: Optional[str] = None
    ) -> Dict[str, Any]:
        """Import a file from remote storage into this session, returning its handle.

        backend is one of "s3", "gcs", "sharepoint", "onedrive", "gdrive".
        remote_path is a relative path inside that backend — absolute paths and
        ".." segments are refused.
        Returns {"file_id", "filename", "size"}. Use the file_id to attach the file.
        """
        session_id = self._require_session()
        allowed = REMOTE_BACKENDS if self.local_import_root is None else SUPPORTED_BACKENDS
        if backend not in allowed:
            raise ValueError(f"Unsupported backend {backend!r}; expected one of {sorted(allowed)}")
        safe_path = _validate_remote_path(remote_path)

        from parrot.tools.filemanager import FileManagerToolkit

        temp_dir = Path(await asyncio.to_thread(tempfile.mkdtemp))
        destination = temp_dir / Path(safe_path).name
        try:
            if backend in LOCAL_BACKENDS:
                manager = FileManagerToolkit(
                    manager_type=backend,
                    base_path=str(self.local_import_root),
                    sandboxed=True,
                )
            else:
                manager = FileManagerToolkit(manager_type=backend)
            await manager.download_file(safe_path, str(destination))
            downloaded = await asyncio.to_thread(destination.stat)
            self._check_size(downloaded.st_size, filename or Path(safe_path).name)
            data = await asyncio.to_thread(destination.read_bytes)
            record = await self.store.put_bytes(
                session_id,
                filename or Path(safe_path).name,
                data,
                origin="remote",
            )
            return {"file_id": record.file_id, "filename": record.filename, "size": record.size}
        finally:
            await asyncio.to_thread(shutil.rmtree, temp_dir, ignore_errors=True)

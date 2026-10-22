"""Per-session, sandboxed file store addressed by opaque handles."""

from __future__ import annotations

import asyncio
import json
import logging
import mimetypes
import os
import secrets
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, Optional

from pydantic import BaseModel, Field

from parrot.conf import OUTPUT_DIR

logger = logging.getLogger(__name__)

#: Suffixes used inside a session root.
BLOB_SUFFIX = ".bin"
MANIFEST_SUFFIX = ".json"

#: Per-session total above which a WARNING is logged. Reporting only — never rejects.
SESSION_FILES_WARN_BYTES = 500 * 1024 * 1024


def _new_handle() -> str:
    """Return an opaque, URL-safe handle with >= 128 bits of entropy."""
    return secrets.token_urlsafe(24)


def _sanitize_filename(name: str) -> str:
    """Reduce *name* to a safe basename for display and for Jira."""
    basename = Path(name.replace("\\", "/")).name
    without_controls = "".join(character for character in basename if ord(character) >= 32 and ord(character) != 127)
    sanitized = " ".join(without_controls.split())[:255]
    return sanitized or "file"


def _write_atomic(path: Path, data: bytes) -> None:
    """Write *data* to *path* through a sibling temporary file."""
    temporary_path: Path | None = None
    try:
        descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
        temporary_path = Path(temporary_name)
        with os.fdopen(descriptor, "wb") as temporary_file:
            temporary_file.write(data)
            temporary_file.flush()
            os.fsync(temporary_file.fileno())
        os.replace(temporary_path, path)
    except BaseException:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
        raise


class SessionFileError(Exception):
    """Base for every store refusal; ``code`` is the stable, matchable signal."""

    code: str = "session_file_error"

    def __init__(self, message: str) -> None:
        """Initialize the error with a human-readable message."""
        super().__init__(message)


class UnknownHandle(SessionFileError):
    """No manifest entry for this file_id in this session."""

    code = "unknown_handle"


class OutsideSandbox(SessionFileError):
    """The handle resolved outside its session root (traversal or symlink)."""

    code = "outside_sandbox"


class MissingBlob(SessionFileError):
    """The manifest entry exists but its blob does not."""

    code = "missing_file"


class SessionFileRecord(BaseModel):
    """Manifest entry for one stored session file."""

    file_id: str = Field(description="Opaque, URL-safe handle")
    session_id: str
    filename: str = Field(description="Sanitized original name, for display and Jira")
    mime_type: str = Field(description="Advisory only — never sent to Jira")
    size: int
    origin: Literal["upload", "remote", "generated"]
    created_at: datetime


class SessionFileStore:
    """Sandboxed, manifest-backed per-session file store."""

    def __init__(self, root: Optional[Path] = None) -> None:
        """Initialize the store with ``OUTPUT_DIR / 'sessions'`` as its default root."""
        self.root = Path(root) if root is not None else Path(OUTPUT_DIR) / "sessions"

    def session_root(self, session_id: str) -> Path:
        """Return a canonical, created root for *session_id*.

        Raises:
            ValueError: If *session_id* is empty, dot-only, or contains a path separator.
        """
        if not session_id or set(session_id) == {"."} or "/" in session_id or "\\" in session_id:
            raise ValueError("session_id must be non-empty and must not contain path separators")
        root = self.root / session_id
        root.mkdir(parents=True, exist_ok=True)
        return root.resolve()

    async def resolve(self, session_id: str, file_id: str) -> tuple[SessionFileRecord, Path]:
        """Resolve a handle to its record and a verified-contained blob path.

        Raises:
            UnknownHandle: If the manifest does not exist for *file_id*.
            OutsideSandbox: If a manifest or blob path leaves the session root.
            MissingBlob: If the manifest exists but the blob does not.
        """
        root = await asyncio.to_thread(self.session_root, session_id)
        manifest_path = root / f"{file_id}{MANIFEST_SUFFIX}"
        resolved_manifest = await asyncio.to_thread(manifest_path.resolve)
        if not resolved_manifest.is_relative_to(root):
            self._raise_outside_sandbox(session_id, file_id)

        try:
            manifest = await asyncio.to_thread(manifest_path.read_text, encoding="utf-8")
        except FileNotFoundError as exc:
            raise UnknownHandle(f"No manifest exists for handle {file_id!r}") from exc

        record = SessionFileRecord.model_validate(json.loads(manifest))
        blob_path = root / f"{file_id}{BLOB_SUFFIX}"
        resolved_blob = await asyncio.to_thread(blob_path.resolve)
        is_symlink = await asyncio.to_thread(blob_path.is_symlink)
        if not resolved_blob.is_relative_to(root) or is_symlink:
            self._raise_outside_sandbox(session_id, file_id)
        if not await asyncio.to_thread(blob_path.exists):
            raise MissingBlob(f"No blob exists for handle {file_id!r}")
        return record, resolved_blob

    async def put_bytes(
        self, session_id: str, filename: str, data: bytes, *, origin: str = "upload"
    ) -> SessionFileRecord:
        """Store *data* under a fresh handle; return its manifest record.

        Writes the blob and manifest through temporary files so a partial write
        never yields a resolvable handle.
        """
        root = await asyncio.to_thread(self.session_root, session_id)
        file_id = _new_handle()
        sanitized_filename = _sanitize_filename(filename)
        mime_type = mimetypes.guess_type(sanitized_filename)[0] or "application/octet-stream"
        record = SessionFileRecord(
            file_id=file_id,
            session_id=session_id,
            filename=sanitized_filename,
            mime_type=mime_type,
            size=len(data),
            origin=origin,
            created_at=datetime.now(timezone.utc),
        )
        blob_path = root / f"{file_id}{BLOB_SUFFIX}"
        manifest_path = root / f"{file_id}{MANIFEST_SUFFIX}"
        blob_written = False
        try:
            await asyncio.to_thread(_write_atomic, blob_path, data)
            blob_written = True
            await asyncio.to_thread(_write_atomic, manifest_path, record.model_dump_json().encode("utf-8"))
        except BaseException:
            if blob_written:
                await asyncio.to_thread(blob_path.unlink, missing_ok=True)
            raise

        await self._warn_if_over_threshold(session_id, record.size)
        return record

    async def put_path(
        self, session_id: str, source: Path, *, filename: Optional[str] = None, origin: str = "generated"
    ) -> SessionFileRecord:
        """Copy *source* into the session root under a fresh handle."""
        data = await asyncio.to_thread(source.read_bytes)
        return await self.put_bytes(session_id, filename or source.name, data, origin=origin)

    async def list_files(self, session_id: str) -> list[SessionFileRecord]:
        """Return every record in the session, newest first."""
        root = await asyncio.to_thread(self.session_root, session_id)

        def read_records() -> list[SessionFileRecord]:
            records: list[SessionFileRecord] = []
            for manifest_path in root.glob(f"*{MANIFEST_SUFFIX}"):
                try:
                    records.append(SessionFileRecord.model_validate_json(manifest_path.read_text(encoding="utf-8")))
                except (OSError, ValueError):
                    logger.warning("Skipping unparseable session manifest %s", manifest_path.name)
            return sorted(records, key=lambda record: record.created_at, reverse=True)

        return await asyncio.to_thread(read_records)

    async def usage_bytes(self, session_id: str) -> int:
        """Return the manifest-recorded total bytes stored for the session."""
        return sum(record.size for record in await self.list_files(session_id))

    async def _warn_if_over_threshold(self, session_id: str, stored_size: int) -> None:
        """Log the reporting-only warning when a store operation crosses the threshold."""
        usage = await self.usage_bytes(session_id)
        if usage - stored_size < SESSION_FILES_WARN_BYTES <= usage:
            logger.warning(
                "Session file usage crossed warning threshold for session_id=%s: %s bytes", session_id, usage
            )

    @staticmethod
    def _raise_outside_sandbox(session_id: str, file_id: str) -> None:
        """Log a path-free sandbox refusal and raise its stable error type."""
        logger.warning("Outside sandbox refusal for session_id=%s handle=%s", session_id, file_id)
        raise OutsideSandbox("Handle resolves outside the session sandbox")

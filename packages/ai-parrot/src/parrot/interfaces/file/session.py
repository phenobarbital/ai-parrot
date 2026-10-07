"""Per-session, sandboxed file store addressed by opaque handles."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Literal, Optional

from pydantic import BaseModel, Field

from parrot.conf import OUTPUT_DIR

logger = logging.getLogger(__name__)

#: Suffixes used inside a session root.
BLOB_SUFFIX = ".bin"
MANIFEST_SUFFIX = ".json"


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

    @staticmethod
    def _raise_outside_sandbox(session_id: str, file_id: str) -> None:
        """Log a path-free sandbox refusal and raise its stable error type."""
        logger.warning("Outside sandbox refusal for session_id=%s handle=%s", session_id, file_id)
        raise OutsideSandbox("Handle resolves outside the session sandbox")

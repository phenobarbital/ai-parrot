"""Agent-facing view of the per-session file store."""

from __future__ import annotations

from typing import Any, Dict, Optional

from parrot.interfaces.file.session import SessionFileError, SessionFileStore
from parrot.tools.toolkit import AbstractToolkit
from parrot.utils.helpers import current_context


class NoBoundSession(SessionFileError):
    """No RequestContext is bound to this asyncio task."""

    code = "no_session"


class SessionFileToolkit(AbstractToolkit):
    """Lists and stages the files of the CURRENT session, addressed by handle."""

    tool_prefix: str = "sf"  # -> sf_list_session_files, sf_store_generated_file

    def __init__(self, store: Optional[SessionFileStore] = None) -> None:
        """Initialize the toolkit.

        Args:
            store: Session file store; defaults to the ``OUTPUT_DIR``-rooted store.
        """
        super().__init__()
        self.store = store or SessionFileStore()

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
        record = await self.store.put_bytes(session_id, filename, content.encode("utf-8"), origin="generated")
        return {"file_id": record.file_id, "filename": record.filename, "size": record.size}

"""Tests for jira_add_comment with attachment support."""

import logging
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from parrot.interfaces.file.session import SessionFileStore
from parrot_tools import jiratoolkit as jt
from parrot_tools.jiratoolkit import AddCommentInput, JiraToolkit


@pytest.fixture
def store(tmp_path):
    """Return an isolated session-file store."""
    return SessionFileStore(root=tmp_path / "sessions")


@pytest.fixture
def toolkit(store):
    """Create a JiraToolkit with mocked JIRA client."""
    tk = JiraToolkit.__new__(JiraToolkit)
    tk.jira = MagicMock()
    tk.logger = logging.getLogger("test_jira_add_comment")
    tk.server_url = "https://test.atlassian.net"
    tk.auth_type = "basic_auth"
    tk._tool_manager = None
    tk._session_file_store = store
    tk._template_engine = None
    tk.templates_dir = None
    tk._inline_templates = {}

    async def _limit():
        return 100

    tk._max_attachment_bytes = _limit
    return tk


@pytest.fixture
def bound_session(monkeypatch):
    """Bind a test session to the Jira session-context seam."""
    monkeypatch.setattr(jt, "current_context", lambda: SimpleNamespace(session_id="s1"))


@pytest.mark.asyncio
async def test_add_comment_without_attachments(toolkit):
    """Comment-only call behaves as before."""
    assert set(AddCommentInput.model_fields) == {
        "issue",
        "body",
        "is_internal",
        "file_ids",
        "template",
        "template_params",
    }
    mock_comment = MagicMock()
    mock_comment.raw = {"id": "10001", "body": "hello"}
    toolkit.jira.add_comment.return_value = mock_comment

    result = await toolkit.jira_add_comment(issue="NAV-1", body="hello")

    toolkit.jira.add_comment.assert_called_once_with("NAV-1", "hello", is_internal=False)
    toolkit.jira.add_attachment.assert_not_called()
    assert result["comment"] == {"id": "10001", "body": "hello"}
    assert result["comment_ok"] is True
    assert result["attachments"] == []
    assert result["attached"] == 0
    assert result["failed"] == 0


@pytest.mark.asyncio
async def test_add_comment_internal_is_forwarded(toolkit):
    """is_internal=True reaches the JIRA client (Service Desk internal comment)."""
    mock_comment = MagicMock()
    mock_comment.raw = {"id": "10002", "body": "agent note"}
    toolkit.jira.add_comment.return_value = mock_comment

    result = await toolkit.jira_add_comment(issue="SD-1", body="agent note", is_internal=True)

    toolkit.jira.add_comment.assert_called_once_with("SD-1", "agent note", is_internal=True)
    assert result["comment"] == {"id": "10002", "body": "agent note"}
    assert result["comment_ok"] is True


@pytest.mark.asyncio
async def test_add_comment_with_valid_handles(toolkit, store, bound_session):
    """Comment + valid session-file handle attaches and returns metadata."""
    record = await store.put_bytes("s1", "screenshot.png", b"\x89PNG fake")

    mock_comment = MagicMock()
    mock_comment.raw = {"id": "10001", "body": "see attached"}
    toolkit.jira.add_comment.return_value = mock_comment

    mock_att = MagicMock()
    mock_att.filename = "screenshot.png"
    mock_att.id = "att-42"
    mock_att.size = 9
    mock_att.mimeType = "image/png"
    toolkit.jira.add_attachment.return_value = mock_att

    result = await toolkit.jira_add_comment(issue="NAV-1", body="see attached", file_ids=[record.file_id])

    toolkit.jira.add_comment.assert_called_once()
    toolkit.jira.add_attachment.assert_called_once()
    assert result["comment_ok"] is True
    assert result["attached"] == 1
    assert len(result["attachments"]) == 1
    att = result["attachments"][0]
    assert att["filename"] == "screenshot.png"
    assert att["attachment_id"] == "att-42"


@pytest.mark.asyncio
async def test_bad_handle_prevents_comment_creation(toolkit, bound_session):
    """An unresolvable handle prevents any comment from being created."""
    result = await toolkit.jira_add_comment(issue="NAV-1", body="test", file_ids=["unknown-handle"])

    toolkit.jira.add_comment.assert_not_called()
    toolkit.jira.add_attachment.assert_not_called()
    assert result["comment_ok"] is False
    assert result["comment"] == {}
    assert result["failed"] == 1
    assert len(result["attachments"]) == 1
    assert result["attachments"][0]["error_code"] == "unknown_handle"


@pytest.mark.asyncio
async def test_mixed_handles_are_best_effort(toolkit, store, bound_session):
    """Resolvable handles upload independently after the comment is created."""
    successful = await store.put_bytes("s1", "ok.png", b"data")
    failed = await store.put_bytes("s1", "fail.png", b"data")

    mock_comment = MagicMock()
    mock_comment.raw = {"id": "10001", "body": "mixed"}
    toolkit.jira.add_comment.return_value = mock_comment

    mock_att = MagicMock()
    mock_att.filename = "ok.png"
    mock_att.id = "att-99"
    mock_att.size = 4
    mock_att.mimeType = "image/png"
    toolkit.jira.add_attachment.side_effect = [mock_att, RuntimeError("Network error")]

    result = await toolkit.jira_add_comment(
        issue="NAV-1",
        body="mixed",
        file_ids=[successful.file_id, failed.file_id],
    )

    assert result["comment_ok"] is True
    assert result["attached"] == 1
    assert result["failed"] == 1
    assert len(result["attachments"]) == 2
    assert result["attachments"][0]["ok"] is True
    assert result["attachments"][1]["error_code"] == "transport_error"


@pytest.mark.asyncio
async def test_comment_ok_with_failed_upload(toolkit, store, bound_session):
    """An upload failure after comment creation leaves comment_ok true."""
    record = await store.put_bytes("s1", "fail.png", b"data")

    mock_comment = MagicMock()
    mock_comment.raw = {"id": "10001", "body": "err"}
    toolkit.jira.add_comment.return_value = mock_comment
    toolkit.jira.add_attachment.side_effect = Exception("Network error")

    result = await toolkit.jira_add_comment(issue="NAV-1", body="err", file_ids=[record.file_id])

    toolkit.jira.add_comment.assert_called_once()
    assert result["comment_ok"] is True
    assert result["attached"] == 0
    assert result["failed"] == 1
    assert len(result["attachments"]) == 1
    assert result["attachments"][0]["error_code"] == "transport_error"

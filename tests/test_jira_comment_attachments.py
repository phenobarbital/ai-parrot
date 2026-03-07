"""Tests for jira_add_comment with attachment support."""
import os
from unittest.mock import MagicMock
import pytest
import pytest_asyncio

from parrot.tools.jiratoolkit import JiraToolkit


@pytest.fixture
def toolkit():
    """Create a JiraToolkit with mocked JIRA client."""
    tk = JiraToolkit.__new__(JiraToolkit)
    tk.jira = MagicMock()
    tk.logger = MagicMock()
    tk.server_url = "https://test.atlassian.net"
    tk.auth_type = "basic_auth"
    tk._tool_manager = None
    return tk


@pytest.mark.asyncio
async def test_add_comment_without_attachments(toolkit):
    """Comment-only call behaves as before."""
    mock_comment = MagicMock()
    mock_comment.raw = {"id": "10001", "body": "hello"}
    toolkit.jira.add_comment.return_value = mock_comment

    result = await toolkit.jira_add_comment(issue="NAV-1", body="hello")

    toolkit.jira.add_comment.assert_called_once_with("NAV-1", "hello")
    toolkit.jira.add_attachment.assert_not_called()
    assert result == {"id": "10001", "body": "hello"}
    assert "attachments" not in result


@pytest.mark.asyncio
async def test_add_comment_with_valid_attachments(toolkit, tmp_path):
    """Comment + valid file attaches and returns metadata."""
    img = tmp_path / "screenshot.png"
    img.write_bytes(b"\x89PNG fake")

    mock_comment = MagicMock()
    mock_comment.raw = {"id": "10001", "body": "see attached"}
    toolkit.jira.add_comment.return_value = mock_comment

    mock_att = MagicMock()
    mock_att.filename = "screenshot.png"
    mock_att.id = "att-42"
    mock_att.size = 9
    mock_att.mimeType = "image/png"
    toolkit.jira.add_attachment.return_value = mock_att

    result = await toolkit.jira_add_comment(
        issue="NAV-1", body="see attached", attachments=[str(img)]
    )

    toolkit.jira.add_comment.assert_called_once()
    toolkit.jira.add_attachment.assert_called_once_with(
        issue="NAV-1", attachment=str(img)
    )
    assert "attachments" in result
    assert len(result["attachments"]) == 1
    att = result["attachments"][0]
    assert att["filename"] == "screenshot.png"
    assert att["id"] == "att-42"


@pytest.mark.asyncio
async def test_add_comment_with_missing_file(toolkit):
    """Non-existent file produces error entry, not an exception."""
    mock_comment = MagicMock()
    mock_comment.raw = {"id": "10001", "body": "test"}
    toolkit.jira.add_comment.return_value = mock_comment

    result = await toolkit.jira_add_comment(
        issue="NAV-1", body="test", attachments=["/nonexistent/file.png"]
    )

    toolkit.jira.add_attachment.assert_not_called()
    assert len(result["attachments"]) == 1
    assert result["attachments"][0]["error"] == "File not found"


@pytest.mark.asyncio
async def test_add_comment_with_mixed_files(toolkit, tmp_path):
    """Mix of valid and invalid files: partial success."""
    img = tmp_path / "ok.png"
    img.write_bytes(b"data")

    mock_comment = MagicMock()
    mock_comment.raw = {"id": "10001", "body": "mixed"}
    toolkit.jira.add_comment.return_value = mock_comment

    mock_att = MagicMock()
    mock_att.filename = "ok.png"
    mock_att.id = "att-99"
    mock_att.size = 4
    mock_att.mimeType = "image/png"
    toolkit.jira.add_attachment.return_value = mock_att

    result = await toolkit.jira_add_comment(
        issue="NAV-1",
        body="mixed",
        attachments=["/bad/path.jpg", str(img)],
    )

    assert len(result["attachments"]) == 2
    assert result["attachments"][0]["error"] == "File not found"
    assert result["attachments"][1]["filename"] == "ok.png"


@pytest.mark.asyncio
async def test_add_comment_attachment_upload_error(toolkit, tmp_path):
    """Upload exception is caught and returned as error entry."""
    img = tmp_path / "fail.png"
    img.write_bytes(b"data")

    mock_comment = MagicMock()
    mock_comment.raw = {"id": "10001", "body": "err"}
    toolkit.jira.add_comment.return_value = mock_comment
    toolkit.jira.add_attachment.side_effect = Exception("Network error")

    result = await toolkit.jira_add_comment(
        issue="NAV-1", body="err", attachments=[str(img)]
    )

    assert len(result["attachments"]) == 1
    assert "Network error" in result["attachments"][0]["error"]

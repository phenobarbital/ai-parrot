"""Tests for the handle-based jira_add_attachment public tool."""

import logging
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from parrot.interfaces.file.session import SessionFileStore
from parrot_tools import jiratoolkit as jt
from parrot_tools.jiratoolkit import AddAttachmentInput, JiraToolkit


@pytest.fixture
def store(tmp_path):
    """Return an isolated session-file store."""
    return SessionFileStore(root=tmp_path / "sessions")


@pytest.fixture
def toolkit(store):
    """Return a Jira toolkit with a deterministic fake attachment client."""
    tk = JiraToolkit.__new__(JiraToolkit)
    tk.logger = logging.getLogger("test_jira_add_attachment")
    tk.jira = MagicMock()
    tk.jira.add_attachment.side_effect = lambda issue, attachment, filename=None: SimpleNamespace(id="900", filename=filename or "x", size=3)
    tk._session_file_store = store

    async def _limit():
        return 100

    tk._max_attachment_bytes = _limit
    return tk


@pytest.fixture
def bound_session(monkeypatch):
    """Bind a test session to the helper's request-context seam."""
    monkeypatch.setattr(jt, "current_context", lambda: SimpleNamespace(session_id="s1"))


class TestJiraAddAttachment:
    """Public handle-based attachment tool behavior."""

    async def test_schema_exposes_file_ids_only(self):
        """Spec AC5 — no path or URL field reaches the model."""
        assert set(AddAttachmentInput.model_fields) == {"issue", "file_ids"}

    async def test_returns_report_with_counts(self, toolkit, store, bound_session):
        """Two valid handles produce two successful report entries."""
        first = await store.put_bytes("s1", "first.docx", b"one")
        second = await store.put_bytes("s1", "second.docx", b"two")

        report = await toolkit.jira_add_attachment("NAV-123", [first.file_id, second.file_id])

        assert report["issue"] == "NAV-123"
        assert report["attached"] == 2
        assert report["failed"] == 0
        assert [item["file_id"] for item in report["attachments"]] == [first.file_id, second.file_id]
        assert all(item["ok"] for item in report["attachments"])

    async def test_per_file_failure_is_reported_not_raised(self, toolkit, bound_session):
        """An unknown handle stays in the report with its stable error code."""
        report = await toolkit.jira_add_attachment("NAV-123", ["unknown-handle"])

        assert report["attached"] == 0
        assert report["failed"] == 1
        assert len(report["attachments"]) == 1
        assert report["attachments"][0]["file_id"] == "unknown-handle"
        assert not report["attachments"][0]["ok"]
        assert report["attachments"][0]["error_code"] == "unknown_handle"

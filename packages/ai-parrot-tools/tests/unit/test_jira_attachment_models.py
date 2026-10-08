"""Tests for Jira attachment result models and size-limit discovery (TASK-4138)."""

import logging
from unittest.mock import MagicMock

import pytest

from parrot_tools.jiratoolkit import (
    DEFAULT_MAX_ATTACHMENT_BYTES,
    AttachmentResult,
    JiraAttachmentReport,
    JiraCommentReport,
    JiraToolkit,
    _bounded_detail,
)


def _toolkit(jira):
    tk = JiraToolkit.__new__(JiraToolkit)
    tk.logger = logging.getLogger("test_jira_attachment")
    tk.jira = jira
    return tk


@pytest.fixture(autouse=True)
def _no_env(monkeypatch):
    monkeypatch.delenv("JIRA_MAX_ATTACHMENT_BYTES", raising=False)
    monkeypatch.setattr("parrot_tools.jiratoolkit.nav_config", None)


class TestModels:
    def test_report_validates(self):
        r = AttachmentResult(file_id="f1", ok=False, error_code="too_large")
        rep = JiraAttachmentReport(issue="A-1", attachments=[r], attached=0, failed=1)
        assert rep.attachments[0].error_code == "too_large"
        c = JiraCommentReport(issue="A-1", comment={}, comment_ok=True, attachments=[r], attached=0, failed=1)
        assert c.comment_ok

    def test_invalid_error_code_rejected(self):
        with pytest.raises(Exception):
            AttachmentResult(file_id="f", ok=False, error_code="quota_exceeded")


class TestBoundedDetail:
    def test_truncates_large_html(self):
        assert len(_bounded_detail("<html>" + "x" * 50000 + "</html>")) <= 500

    def test_collapses_newlines(self):
        assert "\n" not in _bounded_detail("a\nb\nc")


class TestMaxAttachmentBytes:
    async def test_config_override_wins(self, monkeypatch):
        monkeypatch.setenv("JIRA_MAX_ATTACHMENT_BYTES", "123")
        jira = MagicMock()
        assert await _toolkit(jira)._max_attachment_bytes() == 123
        jira.attachment_meta.assert_not_called()

    async def test_discovers_upload_limit(self):
        jira = MagicMock()
        jira.attachment_meta.return_value = {"enabled": True, "uploadLimit": 5555}
        tk = _toolkit(jira)
        assert await tk._max_attachment_bytes() == 5555
        assert await tk._max_attachment_bytes() == 5555
        assert jira.attachment_meta.call_count == 1

    async def test_probe_failure_falls_back(self, caplog):
        jira = MagicMock()
        jira.attachment_meta.side_effect = RuntimeError("boom")
        with caplog.at_level(logging.WARNING):
            assert await _toolkit(jira)._max_attachment_bytes() == DEFAULT_MAX_ATTACHMENT_BYTES
        assert any(r.levelno == logging.WARNING for r in caplog.records)

    async def test_no_client_falls_back(self):
        assert await _toolkit(None)._max_attachment_bytes() == DEFAULT_MAX_ATTACHMENT_BYTES

"""Tests for MS Teams document attachment handling (FEAT-639)."""
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from parrot.integrations.msteams.wrapper import MSTeamsAgentWrapper
from parrot.interfaces.file.session import SessionFileStore

DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def _att(content_type, url, name="a.docx"):
    return SimpleNamespace(content_type=content_type, content_url=url, name=name)


def _wrapper(tmp_path):
    w = object.__new__(MSTeamsAgentWrapper)
    w.logger = logging.getLogger("test")
    w._session_file_store = SessionFileStore(tmp_path)
    w._get_attachment_token = AsyncMock(return_value="tok")
    return w


def _ctx():
    return SimpleNamespace(activity=SimpleNamespace(conversation=SimpleNamespace(id="conv1")))


def _http(status, data=b"bytes"):
    resp = MagicMock()
    resp.status = status
    resp.read = AsyncMock(return_value=data)
    get_cm = MagicMock()
    get_cm.__aenter__ = AsyncMock(return_value=resp)
    get_cm.__aexit__ = AsyncMock(return_value=False)
    session = MagicMock()
    session.get = MagicMock(return_value=get_cm)
    sess_cm = MagicMock()
    sess_cm.__aenter__ = AsyncMock(return_value=session)
    sess_cm.__aexit__ = AsyncMock(return_value=False)
    return sess_cm


class TestFindDocumentAttachments:
    def test_skips_audio(self, tmp_path):
        w = _wrapper(tmp_path)
        audio = _att("audio/ogg", "http://x/a", "a.ogg")
        doc = _att(DOCX, "http://x/d")
        act = SimpleNamespace(attachments=[audio, doc])
        assert w._find_document_attachments(act) == [doc]

    def test_skips_attachment_without_content_url(self, tmp_path):
        w = _wrapper(tmp_path)
        card = _att("application/vnd.microsoft.card.adaptive", None, "c")
        assert w._find_document_attachments(SimpleNamespace(attachments=[card])) == []

    def test_returns_all_documents(self, tmp_path):
        w = _wrapper(tmp_path)
        docs = [_att(DOCX, "http://x/1"), _att(DOCX, "http://x/2")]
        assert w._find_document_attachments(SimpleNamespace(attachments=docs)) == docs

    def test_no_attachments(self, tmp_path):
        w = _wrapper(tmp_path)
        assert w._find_document_attachments(SimpleNamespace(attachments=None)) == []


class TestHandleDocumentAttachment:
    async def test_downloads_and_stores(self, tmp_path):
        w = _wrapper(tmp_path)
        with patch("parrot.integrations.msteams.wrapper.aiohttp.ClientSession", return_value=_http(200)):
            file_id = await w._handle_document_attachment(_ctx(), _att(DOCX, "http://x/d"))
        assert file_id
        record, path = await w._session_file_store.resolve("conv1", file_id)
        assert record.filename == "a.docx"
        assert path.read_bytes() == b"bytes"

    async def test_failed_download_returns_none(self, tmp_path, caplog):
        w = _wrapper(tmp_path)
        with patch("parrot.integrations.msteams.wrapper.aiohttp.ClientSession", return_value=_http(403)):
            with caplog.at_level(logging.WARNING):
                result = await w._handle_document_attachment(_ctx(), _att(DOCX, "http://x/d"))
        assert result is None
        assert any(r.levelno == logging.WARNING for r in caplog.records)

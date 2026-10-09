"""FEAT-647 TASK-4187 — Telegram knowledge upload adapter (no network)."""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot.integrations.knowledge_upload.models import (
    UploadOutcome, UploadStatus, UploadTargetKind,
)
from parrot.integrations.telegram.knowledge_upload import TelegramKnowledgeUpload, parse_ingest_args


class FakeService:
    """Records submitted requests; returns ACCEPTED."""

    def __init__(self, targets=(UploadTargetKind.BOOKSTORE, UploadTargetKind.WIKI)):
        self.targets = set(targets)
        self.requests = []
        self.stopped = False

    def available_targets(self):
        return self.targets

    def max_bytes(self, platform_cap_mb=None):
        return 10 * 1024 * 1024

    async def submit(self, request, notify):
        self.requests.append(request)
        return UploadOutcome(job_id="j1", status=UploadStatus.ACCEPTED, target=request.target,
                             filename=request.filename, message="Processing…")

    async def shutdown(self):
        self.stopped = True


_ON = SimpleNamespace()


def _make_wrapper(authenticated=True, bookstore=_ON, wiki=_ON):
    async def download(path, buffer):
        buffer.write(b"%PDF-1.4")

    bot = SimpleNamespace(
        get_file=AsyncMock(return_value=SimpleNamespace(file_path="p/x.pdf")),
        download_file=AsyncMock(side_effect=download),
    )
    session = SimpleNamespace(authenticated=authenticated, nav_user_id="u1" if authenticated else None,
                              nav_email="a@b.c")
    cfg = SimpleNamespace(
        enabled=True, bookstore=bookstore, wiki=wiki,
        allowed_extensions=[".pdf", ".docx", ".md", ".markdown"],
    )
    return SimpleNamespace(
        config=SimpleNamespace(knowledge_upload=cfg), logger=MagicMock(), bot=bot,
        _is_authorized=lambda chat_id: True, _get_user_session=lambda message: session,
    )


@pytest.fixture
def wrapper():
    return _make_wrapper()


def _message(document=None, reply_document=None):
    return SimpleNamespace(
        chat=SimpleNamespace(id=1), from_user=SimpleNamespace(id=42), document=document,
        reply_to_message=SimpleNamespace(document=reply_document) if reply_document else None,
        answer=AsyncMock(),
    )


def _doc(name="book.pdf", size=100):
    return SimpleNamespace(file_name=name, file_size=size, file_id="fid")


def test_parse_ingest_args_quoting():
    opts = parse_ingest_args('--force --title "Odoo 17 Manual" --author A --author B --topic sales')
    assert opts == {"force": True, "title": "Odoo 17 Manual", "authors": ["A", "B"], "topics": ["sales"]}


async def test_caption_submits_in_memory_bytes(wrapper):
    svc = FakeService()
    adapter = TelegramKnowledgeUpload(wrapper, service=svc)
    msg = _message(document=_doc())
    await adapter.handle(msg, UploadTargetKind.BOOKSTORE, msg.document, "--force")
    assert len(svc.requests) == 1
    req = svc.requests[0]
    assert req.data == b"%PDF-1.4" and req.force is True
    assert req.target is UploadTargetKind.BOOKSTORE
    assert req.identity.platform == "telegram"
    assert req.identity.nav_user_id == "u1" and req.identity.email == "a@b.c"


async def test_reply_to_document_submits(wrapper):
    svc = FakeService()
    adapter = TelegramKnowledgeUpload(wrapper, service=svc)
    msg = _message(reply_document=_doc("w.md"))
    await adapter._on_reply(msg, SimpleNamespace(command="ingest_wiki", args="--topic x"))
    assert svc.requests[0].target is UploadTargetKind.WIKI
    assert svc.requests[0].filename == "w.md" and svc.requests[0].topics == ["x"]


async def test_unauthenticated_session_denied():
    svc = FakeService()
    adapter = TelegramKnowledgeUpload(_make_wrapper(authenticated=False), service=svc)
    msg = _message(document=_doc())
    await adapter.handle(msg, UploadTargetKind.BOOKSTORE, msg.document, "")
    assert svc.requests == []
    assert "login" in msg.answer.call_args.args[0]


async def test_oversize_and_bad_extension_rejected_before_download(wrapper):
    svc = FakeService()
    adapter = TelegramKnowledgeUpload(wrapper, service=svc)
    for doc in (_doc("x.exe"), _doc("big.pdf", size=11 * 1024 * 1024)):
        msg = _message(document=doc)
        await adapter.handle(msg, UploadTargetKind.BOOKSTORE, doc, "")
    wrapper.bot.get_file.assert_not_called()
    assert svc.requests == []


async def test_oversize_after_download_rejected(wrapper):
    class Small(FakeService):
        def max_bytes(self, platform_cap_mb=None):
            return 4

    svc = Small()
    adapter = TelegramKnowledgeUpload(wrapper, service=svc)
    msg = _message(document=_doc(size=None))
    await adapter.handle(msg, UploadTargetKind.BOOKSTORE, msg.document, "")
    assert svc.requests == []


def test_register_only_configured_commands():
    adapter = TelegramKnowledgeUpload(_make_wrapper(wiki=None))
    router = MagicMock()
    entries = adapter.register(router)
    assert [e[0] for e in entries] == ["ingest_book"]
    assert router.message.register.call_count == 3
    empty = TelegramKnowledgeUpload(_make_wrapper(bookstore=None, wiki=None))
    assert empty.register(MagicMock()) == []


async def test_shutdown_calls_service(wrapper):
    svc = FakeService()
    await TelegramKnowledgeUpload(wrapper, service=svc).shutdown()
    assert svc.stopped

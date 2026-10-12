"""FEAT-647 TASK-4188 — MS Teams knowledge upload adapter (no network)."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from parrot.integrations.knowledge_upload.models import (
    BookstoreTargetConfig,
    KnowledgeUploadConfig,
    UploadOutcome,
    UploadStatus,
    UploadTargetKind,
)
from parrot.integrations.msteams.commands import MSTeamsCommandRouter
from parrot.integrations.msteams.commands import knowledge_upload as knowledge_upload_module
from parrot.integrations.msteams.commands.knowledge_upload import (
    FILE_DOWNLOAD_INFO,
    TeamsKnowledgeUpload,
    register_knowledge_upload_commands,
)


class FakeService:
    """Record submissions and return an immediate accepted outcome."""

    def __init__(self) -> None:
        self.requests = []
        self.notify = None

    def available_targets(self) -> set[UploadTargetKind]:
        """Return the one configured fake target."""
        return {UploadTargetKind.BOOKSTORE}

    def max_bytes(self) -> int:
        """Return a deliberately small limit for streaming tests."""
        return 4

    async def submit(self, request, notify):
        """Record a request and acknowledge it."""
        self.requests.append(request)
        self.notify = notify
        return UploadOutcome(
            job_id="job-1",
            status=UploadStatus.ACCEPTED,
            target=request.target,
            filename=request.filename,
            message="Processing.",
        )

    async def shutdown(self) -> None:
        """Match the service lifecycle surface."""


@pytest.fixture
def wrapper():
    """Return the minimal wrapper surface consumed by the Teams adapter."""
    knowledge_upload = KnowledgeUploadConfig(
        enabled=True,
        bookstore=BookstoreTargetConfig(library_dir="/library"),
    )
    return SimpleNamespace(
        config=SimpleNamespace(knowledge_upload=knowledge_upload, client_id="app-id"),
        logger=MagicMock(),
        _remove_mentions=lambda activity, text: text,
        _get_attachment_token=AsyncMock(return_value="token"),
        send_text=AsyncMock(),
        adapter=SimpleNamespace(continue_conversation=AsyncMock()),
    )


def test_register_only_configured_commands(wrapper):
    """Only target blocks present in config become router commands."""
    router = MSTeamsCommandRouter()

    register_knowledge_upload_commands(router, wrapper, FakeService())

    assert router.registered_commands == ["ingest_book"]


def test_pick_attachment_prefers_download_info():
    """The pre-authenticated Teams URL wins over generic attachments."""
    html = SimpleNamespace(content_type="text/html", content_url="https://body", content=None)
    info = SimpleNamespace(content_type=FILE_DOWNLOAD_INFO, content_url=None, content={"downloadUrl": "https://file"})
    generic = SimpleNamespace(content_type="application/pdf", content_url="https://generic", content=None)
    activity = SimpleNamespace(attachments=[html, info, generic])

    assert TeamsKnowledgeUpload.pick_attachment(activity) is info


class _Response:
    """Async response fixture carrying chunked test bytes."""

    def __init__(self, chunks) -> None:
        self.status = 200
        self.content = SimpleNamespace(iter_chunked=self._iter_chunks)
        self._chunks = chunks

    async def _iter_chunks(self, size):
        for chunk in self._chunks:
            yield chunk

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False


class _Session:
    """Async aiohttp session fixture recording each GET."""

    def __init__(self, response) -> None:
        self.response = response
        self.get = MagicMock(return_value=response)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False


@pytest.mark.asyncio
async def test_download_variants_and_cap(wrapper):
    """Download metadata omits auth, CDN URLs use bot auth, and caps abort."""
    holder = TeamsKnowledgeUpload(wrapper, FakeService())
    context = SimpleNamespace()
    metadata = SimpleNamespace(
        content_type=FILE_DOWNLOAD_INFO,
        content={"downloadUrl": "https://metadata"},
        content_url=None,
    )
    session = _Session(_Response([b"abcd"]))
    with patch("parrot.integrations.msteams.commands.knowledge_upload.aiohttp.ClientSession", return_value=session):
        assert await holder.download(context, metadata, 4) == b"abcd"
    session.get.assert_called_once_with("https://metadata", headers={})

    generic = SimpleNamespace(content_type="application/pdf", content=None, content_url="https://cdn")
    session = _Session(_Response([b"ab"]))
    with patch("parrot.integrations.msteams.commands.knowledge_upload.aiohttp.ClientSession", return_value=session):
        assert await holder.download(context, generic, 4) == b"ab"
    session.get.assert_called_once_with("https://cdn", headers={"Authorization": "Bearer token"})

    session = _Session(_Response([b"abc", b"de"]))
    with patch("parrot.integrations.msteams.commands.knowledge_upload.aiohttp.ClientSession", return_value=session):
        assert await holder.download(context, generic, 4) is None


def _context(text, attachments=None):
    """Build a minimal activity context for handler tests."""
    return SimpleNamespace(
        activity=SimpleNamespace(
            text=text,
            attachments=attachments or [],
            from_property=SimpleNamespace(id="teams-user"),
        )
    )


@pytest.mark.asyncio
async def test_no_attachment_usage(wrapper):
    """A command without a file replies with usage and does not submit."""
    service = FakeService()
    holder = TeamsKnowledgeUpload(wrapper, service)

    await holder.handle(_context("/ingest_book"), UploadTargetKind.BOOKSTORE)

    assert "Attach a PDF" in wrapper.send_text.await_args.args[0]
    assert service.requests == []


@pytest.mark.asyncio
async def test_identity_failure_denies(wrapper):
    """Roster failures deny before downloading or submitting bytes."""
    service = FakeService()
    holder = TeamsKnowledgeUpload(wrapper, service)
    attachment = SimpleNamespace(name="guide.pdf", content_type=FILE_DOWNLOAD_INFO, content={"downloadUrl": "url"})
    with patch(
        "parrot.integrations.msteams.commands.knowledge_upload.TeamsInfo.get_member",
        new=AsyncMock(side_effect=RuntimeError("unavailable")),
    ):
        await holder.handle(_context("/ingest_book", [attachment]), UploadTargetKind.BOOKSTORE)

    assert "identity could not be verified" in wrapper.send_text.await_args.args[0].lower()
    assert service.requests == []


@pytest.mark.asyncio
async def test_notify_uses_continue_conversation(wrapper):
    """The completion callback is delivered through the proactive adapter API."""
    service = FakeService()
    holder = TeamsKnowledgeUpload(wrapper, service)
    attachment = SimpleNamespace(name="guide.pdf", content_type=FILE_DOWNLOAD_INFO, content={"downloadUrl": "url"})
    context = _context("/ingest_book --force", [attachment])
    with (
        patch(
            "parrot.integrations.msteams.commands.knowledge_upload.TeamsInfo.get_member",
            new=AsyncMock(return_value=SimpleNamespace(email="person@example.test")),
        ),
        patch.object(holder, "download", new=AsyncMock(return_value=b"data")),
        patch.object(knowledge_upload_module.TurnContext, "get_conversation_reference", return_value="reference"),
    ):
        await holder.handle(context, UploadTargetKind.BOOKSTORE)
        await service.notify(
            UploadOutcome(
                job_id="job-1",
                status=UploadStatus.ADDED,
                target=UploadTargetKind.BOOKSTORE,
                filename="guide.pdf",
                message="Done.",
            )
        )

    request = service.requests[0]
    assert request.data == b"data"
    assert request.force is True
    wrapper.adapter.continue_conversation.assert_awaited_once()
    assert wrapper.adapter.continue_conversation.await_args.args[0] == "reference"
    assert wrapper.adapter.continue_conversation.await_args.args[2] == "app-id"

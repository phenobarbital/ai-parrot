"""Unit tests for ``AgentKnowledgeHandler`` (PageIndex / GraphIndex REST surface).

Following the project convention for handler tests, these exercise the handler
*logic* in isolation — dispatch, status codes, parameter parsing and the calls
made into the agent's toolkit — without standing up a full aiohttp/navigator
server. The handler is built via ``__new__`` so navigator's ``BaseView``
initialisation (which needs a live app/auth) is bypassed; ``json_response`` is
stubbed to a plain capture.
"""
from __future__ import annotations

import logging
from types import SimpleNamespace
from typing import Any, Optional
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiohttp import web

from parrot.handlers.knowledge import AgentKnowledgeHandler


# ── helpers ──────────────────────────────────────────────────────────────────


def _make_handler(
    *,
    agent: Any,
    query: Optional[dict] = None,
    match_info: Optional[dict] = None,
    json_body: Optional[dict] = None,
    headers: Optional[dict] = None,
) -> AgentKnowledgeHandler:
    """Construct a handler with a mocked request and a stubbed json_response."""
    handler = AgentKnowledgeHandler.__new__(AgentKnowledgeHandler)
    handler.logger = logging.getLogger("test.knowledge")

    bot_manager = MagicMock()
    bot_manager.get_bot = AsyncMock(return_value=agent)

    request = MagicMock()
    request.app = {"bot_manager": bot_manager}
    request.query = query or {}
    request.match_info = match_info or {"agent_id": "demo"}
    request.headers = headers or {}
    request.json = AsyncMock(return_value=json_body or {})
    # ``request`` is a read-only property on aiohttp's View — set the backing
    # attribute it returns (``self._request``).
    handler._request = request

    # Capture json_response output as (content, status).
    handler.json_response = lambda content, status=200: SimpleNamespace(
        content=content, status=status
    )
    return handler


def _pageindex_agent(**toolkit_methods) -> SimpleNamespace:
    toolkit = MagicMock()
    for name, value in toolkit_methods.items():
        setattr(toolkit, name, value)
    return SimpleNamespace(
        name="demo",
        has_pageindex_tools=True,
        pageindex_toolkit=toolkit,
        has_graphindex_tools=False,
        graphindex_toolkit=None,
        graphindex_builder=None,
    )


# ── GET: status / search ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_status_reports_flags_and_trees():
    agent = _pageindex_agent(list_trees=AsyncMock(return_value=["pageindex", "manuals"]))
    handler = _make_handler(agent=agent, match_info={"agent_id": "demo", "action": ""})
    resp = await handler.get()
    assert resp.content["has_pageindex_tools"] is True
    assert resp.content["trees"] == ["pageindex", "manuals"]


@pytest.mark.asyncio
async def test_search_pageindex_calls_toolkit():
    search = AsyncMock(return_value=[{"node_id": "0001", "score": 0.9}])
    agent = _pageindex_agent(search=search)
    handler = _make_handler(
        agent=agent,
        match_info={"agent_id": "demo", "action": "search"},
        query={"q": "install", "tree": "manuals", "top_k": "5"},
    )
    resp = await handler.get()
    search.assert_awaited_once_with(tree_name="manuals", query="install", top_k=5)
    assert resp.content["results"][0]["node_id"] == "0001"


@pytest.mark.asyncio
async def test_search_requires_query():
    agent = _pageindex_agent(search=AsyncMock())
    handler = _make_handler(
        agent=agent, match_info={"agent_id": "demo", "action": "search"}, query={}
    )
    with pytest.raises(web.HTTPBadRequest):
        await handler.get()


@pytest.mark.asyncio
async def test_search_without_pageindex_returns_conflict():
    agent = SimpleNamespace(
        name="demo",
        has_pageindex_tools=False,
        pageindex_toolkit=None,
        has_graphindex_tools=False,
        graphindex_toolkit=None,
        graphindex_builder=None,
    )
    handler = _make_handler(
        agent=agent,
        match_info={"agent_id": "demo", "action": "search"},
        query={"q": "x"},
    )
    with pytest.raises(web.HTTPConflict):
        await handler.get()


# ── GET: ask (chunked stream) ────────────────────────────────────────────────


class _FakeStreamResponse:
    """Captures chunks written to a streamed response."""

    instances: list = []

    def __init__(self, *args, **kwargs):
        self.chunks: list[bytes] = []
        self.eof = False
        _FakeStreamResponse.instances.append(self)

    async def prepare(self, request):
        self.prepared = True

    async def write(self, data: bytes):
        self.chunks.append(data)

    async def drain(self):
        pass

    async def write_eof(self):
        self.eof = True


@pytest.mark.asyncio
async def test_ask_streams_chunks(monkeypatch):
    from parrot.models.responses import AIMessage

    async def fake_stream(question: str):
        for token in ("Hello", " ", "world"):
            yield token
        yield MagicMock(spec=AIMessage)  # trailing metadata, must be skipped

    agent = _pageindex_agent()
    agent.ask_stream = fake_stream
    handler = _make_handler(
        agent=agent,
        match_info={"agent_id": "demo", "action": "ask"},
        query={"q": "hi"},
    )
    _FakeStreamResponse.instances.clear()
    monkeypatch.setattr(
        "parrot.handlers.knowledge.web.StreamResponse", _FakeStreamResponse
    )
    await handler.get()
    stream = _FakeStreamResponse.instances[-1]
    assert b"".join(stream.chunks) == b"Hello world"
    assert stream.eof is True


# ── PUT: upload ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_put_uploads_text_file_into_pageindex(monkeypatch):
    import_file = AsyncMock(return_value={"new_node_ids": ["0002"], "doc_name": "notes"})
    agent = _pageindex_agent(
        list_trees=AsyncMock(return_value=["pageindex"]),
        import_file=import_file,
    )
    handler = _make_handler(agent=agent, query={})

    # Avoid real multipart parsing; feed a fake uploaded file.
    fake_files = [
        {"filename": "notes.txt", "path": "/tmp/notes.txt", "content_type": "text/plain", "size": 3}
    ]
    handler._read_uploads = AsyncMock(return_value=(fake_files, {}))
    handler._cleanup = MagicMock()

    resp = await handler.put()
    import_file.assert_awaited_once_with(tree_name="pageindex", file_path="/tmp/notes.txt")
    assert resp.status == 201
    assert resp.content["imported"][0]["new_node_ids"] == ["0002"]
    handler._cleanup.assert_called_once()


@pytest.mark.asyncio
async def test_put_graphindex_without_builder_returns_501():
    agent = SimpleNamespace(
        name="demo",
        has_pageindex_tools=False,
        pageindex_toolkit=None,
        has_graphindex_tools=True,
        graphindex_toolkit=MagicMock(),
        graphindex_builder=None,
        tenant_context=None,
    )
    handler = _make_handler(agent=agent, query={"index": "graphindex"})
    handler._read_uploads = AsyncMock(
        return_value=([{"filename": "a.pdf", "path": "/tmp/a.pdf"}], {})
    )
    handler._cleanup = MagicMock()
    with pytest.raises(web.HTTPNotImplemented):
        await handler.put()


# ── POST: edit ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_post_updates_node_content():
    update_content = AsyncMock()
    agent = _pageindex_agent(update_node_content=update_content)
    handler = _make_handler(
        agent=agent,
        query={},
        json_body={"tree": "pageindex", "node_id": "0001", "body": "new text"},
    )
    resp = await handler.post()
    update_content.assert_awaited_once_with(
        tree_name="pageindex", node_id="0001", body="new text"
    )
    assert resp.content["updated"]["content"] is True


@pytest.mark.asyncio
async def test_post_graphindex_returns_501():
    agent = SimpleNamespace(
        name="demo",
        has_pageindex_tools=False,
        pageindex_toolkit=None,
        has_graphindex_tools=True,
        graphindex_toolkit=MagicMock(),
        graphindex_builder=None,
    )
    handler = _make_handler(agent=agent, query={"index": "graphindex"})
    with pytest.raises(web.HTTPNotImplemented):
        await handler.post()


# ── DELETE ───────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_delete_node():
    delete_node = AsyncMock(return_value={"removed": True})
    agent = _pageindex_agent(delete_node=delete_node)
    handler = _make_handler(agent=agent, query={"tree": "pageindex", "node_id": "0003"})
    resp = await handler.delete()
    delete_node.assert_awaited_once_with(tree_name="pageindex", node_id="0003")
    assert resp.content["node_id"] == "0003"


@pytest.mark.asyncio
async def test_delete_whole_tree():
    delete_tree = AsyncMock(return_value={"tree_removed": True})
    agent = _pageindex_agent(delete_tree=delete_tree)
    handler = _make_handler(agent=agent, query={"tree": "manuals"})
    resp = await handler.delete()
    delete_tree.assert_awaited_once_with(tree_name="manuals")
    assert resp.content["tree"] == "manuals"

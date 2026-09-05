"""Tests for the bookstore MCP stdio server factory."""

from __future__ import annotations

import pytest

from parrot.knowledge.bookstore.config import LibraryLocation
from parrot.knowledge.bookstore.library import Bookstore
from parrot.knowledge.bookstore.mcp_server import create_bookstore_mcp_server

from .conftest import SAMPLE_MARKDOWN
from .test_toolkit import EXPECTED_TOOLS


@pytest.fixture
def seeded_locations(tmp_path, fake_adapter):
    locations = [
        LibraryLocation(scope="project", root=tmp_path / "proj" / "library"),
    ]
    store = Bookstore(locations, adapter=fake_adapter)
    book = tmp_path / "synthetic-handbook.md"
    book.write_text(SAMPLE_MARKDOWN, encoding="utf-8")

    import asyncio

    asyncio.run(store.add_book(book))
    return locations


def test_server_registers_expected_tools(seeded_locations, capsys):
    server = create_bookstore_mcp_server(seeded_locations)
    assert set(server.tools) == EXPECTED_TOOLS
    assert server.config.name == "bookstore"
    assert "1 book(s)" in server.config.description
    assert "no LLM configured" in server.config.description
    # stdout purity: nothing may leak into the JSON-RPC channel during
    # construction.
    captured = capsys.readouterr()
    assert captured.out == ""


def test_server_description_with_llm(seeded_locations, fake_adapter, capsys):
    server = create_bookstore_mcp_server(seeded_locations, adapter=fake_adapter)
    assert "no LLM configured" not in server.config.description
    assert capsys.readouterr().out == ""

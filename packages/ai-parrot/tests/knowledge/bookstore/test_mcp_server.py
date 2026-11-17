"""Tests for the bookstore MCP stdio server factory."""

from __future__ import annotations

import os
import subprocess
import sys

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
    assert "agentic retrieval remains visible" in server.config.description
    # stdout purity: nothing may leak into the JSON-RPC channel during
    # construction.
    captured = capsys.readouterr()
    assert captured.out == ""


def test_server_description_with_llm(seeded_locations, fake_adapter, capsys):
    server = create_bookstore_mcp_server(seeded_locations, adapter=fake_adapter)
    assert "no LLM configured" not in server.config.description
    assert "bookstore_agentic_retrieve" in server.config.description
    assert capsys.readouterr().out == ""


def test_server_description_funnel_starts_with_find_books(seeded_locations):
    description = create_bookstore_mcp_server(seeded_locations).config.description
    funnel = description.split("Research funnel:", 1)[1]
    assert funnel.lstrip().startswith("bookstore_find_books")
    assert funnel.index("bookstore_find_books") < funnel.index("bookstore_catalog_search")


@pytest.mark.parametrize("with_model", [False, True])
def test_mcp_tools_list_has_fifteen_tools(seeded_locations, fake_adapter, with_model):
    adapter = fake_adapter if with_model else None
    server = create_bookstore_mcp_server(seeded_locations, adapter=adapter)
    assert len(server.tools) == 15
    assert set(server.tools) == EXPECTED_TOOLS
    assert all(name.startswith("bookstore_") for name in server.tools)


@pytest.mark.asyncio
async def test_no_model_agentic_invocation_returns_explanatory_error(seeded_locations):
    server = create_bookstore_mcp_server(seeded_locations)
    result = await server.handle_tools_call(
        {
            "name": "bookstore_agentic_retrieve",
            "arguments": {"book_id": "synthetic-handbook", "query": "How does vector search work?"},
        }
    )

    assert result["isError"] is True
    assert "agentic retrieval requires an LLM" in result["content"][0]["text"]


def test_mcp_server_does_not_import_wiki(seeded_locations):
    """Verify MCP construction does not import wiki in a fresh interpreter."""
    script = """
import sys
from pathlib import Path
from parrot.knowledge.bookstore.config import LibraryLocation
from parrot.knowledge.bookstore.mcp_server import create_bookstore_mcp_server

create_bookstore_mcp_server([LibraryLocation(scope="project", root=Path(sys.argv[1]))])
imported = any(name == "parrot.knowledge.wiki" or name.startswith("parrot.knowledge.wiki.") for name in sys.modules)
print(f"WIKI_IMPORTED={int(imported)}")
"""
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join(sys.path)

    result = subprocess.run(
        [sys.executable, "-c", script, str(seeded_locations[0].root)],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )

    assert "WIKI_IMPORTED=0" in result.stdout.splitlines()

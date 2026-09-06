"""End-to-end integration tests for the FEAT-533 book graph.

Exercises the whole funnel through every public entry point — the
library API, the CLI, the MCP stdio server, and the exported wiki
plane — on a small synthetic five-book library, offline (fake
adapter). The per-module unit suites (test_relations.py,
test_communities.py, test_export_wiki.py, ...) already prove each
piece in isolation; this file proves they compose.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

import pytest
from click.testing import CliRunner

from parrot.knowledge.bookstore import cli as bookstore_cli
from parrot.knowledge.bookstore.config import resolve_locations
from parrot.knowledge.bookstore.library import Bookstore

from .conftest import SAMPLE_MARKDOWN, make_adapter

#: Two author groups (Calderón de la Barca x2, Cervantes x3) so Stage 1
#: produces real same_author edges; all five otherwise get the fake
#: adapter's fixed classification (genre="essay", traditions=["Estoicismo"],
#: period="Imperio romano"), which is enough to exercise same_tradition/
#: same_genre/same_era too and to make catalog_search("estoicismo") hit.
_BOOK_SPECS = [
    ("calderon-vida", ["Calderón de la Barca"], ["barroco", "honor"]),
    ("calderon-alcalde", ["Calderon de la Barca"], ["barroco", "justicia"]),
    ("cervantes-quijote", ["Miguel de Cervantes"], ["caballeria", "satira"]),
    ("cervantes-novelas", ["Miguel de Cervantes"], ["novela", "picaresca"]),
    ("cervantes-entremeses", ["Miguel de Cervantes"], ["teatro", "comedia"]),
]


@pytest.fixture
async def library_five_books(tmp_path, monkeypatch) -> Bookstore:
    """Five books, two author groups, ingested through the public API only."""
    monkeypatch.setenv("PARROT_LIBRARY_DIR", str(tmp_path / "library"))
    store = Bookstore(resolve_locations(cwd=tmp_path), adapter=make_adapter())
    for stem, authors, topics in _BOOK_SPECS:
        md = tmp_path / f"{stem}.md"
        md.write_text(SAMPLE_MARKDOWN.replace("Synthetic Handbook", stem), encoding="utf-8")
        await store.add_book(md, title=stem, authors=authors, topics=topics)
    return store


def _subprocess_env(library_dir: Path) -> dict:
    """Env for a subprocess MCP server: this worktree's own src roots on
    PYTHONPATH (so it never resolves `parrot` from a different checkout),
    PARROT_LIBRARY_DIR pointing at the seeded library, and no
    PARROT_BOOKSTORE_LLM — the roundtrip must stay hermetic."""
    env = os.environ.copy()
    src_roots = [
        str(Path(__file__).resolve().parents[4] / "ai-parrot" / "src"),
        str(Path(__file__).resolve().parents[4] / "ai-parrot-server" / "src"),
    ]
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = os.pathsep.join([*src_roots, existing]) if existing else os.pathsep.join(src_roots)
    env["PARROT_LIBRARY_DIR"] = str(library_dir)
    env.pop("PARROT_BOOKSTORE_LLM", None)
    return env


@pytest.mark.asyncio
async def test_relate_all_end_to_end_fake_adapter(library_five_books):
    summary = await library_five_books.relate_books(None)

    assert summary.deterministic_edges > 0
    assert summary.llm_prompts > 0
    assert summary.communities is not None and summary.communities > 0

    cards = library_five_books.list_books()
    assert library_five_books.related_books(cards[0].book_id)
    assert library_five_books.communities()
    assert library_five_books.catalog_search("estoicismo")


def test_cli_relate_related_communities_json(library_five_books, monkeypatch):
    library_dir = library_five_books.locations[0].root
    monkeypatch.setenv("PARROT_LIBRARY_DIR", str(library_dir))
    monkeypatch.setenv("PARROT_HOME", str(library_dir.parent / "home"))
    monkeypatch.setattr(bookstore_cli, "_INVOCATION_CWD", str(library_dir.parent))

    relate_result = CliRunner().invoke(bookstore_cli.bookstore, ["relate", "--all", "--no-llm"])
    assert relate_result.exit_code == 0, relate_result.output

    book_id = library_five_books.list_books()[0].book_id
    related_result = CliRunner().invoke(bookstore_cli.bookstore, ["related", book_id, "--json"])
    assert related_result.exit_code == 0, related_result.output
    json.loads(related_result.output)

    communities_result = CliRunner().invoke(bookstore_cli.bookstore, ["communities", "--json"])
    assert communities_result.exit_code == 0, communities_result.output
    json.loads(communities_result.output)


@pytest.mark.asyncio
async def test_mcp_related_books_roundtrip(library_five_books, tmp_path):
    await library_five_books.relate_books(None, use_llm=False)
    library_dir = library_five_books.locations[0].root
    book_id = library_five_books.list_books()[0].book_id

    proc = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "parrot.knowledge.bookstore.mcp_server",
        cwd=str(tmp_path),
        env=_subprocess_env(library_dir),
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:

        async def send(request: dict) -> dict:
            proc.stdin.write((json.dumps(request) + "\n").encode())
            await proc.stdin.drain()
            line = await asyncio.wait_for(proc.stdout.readline(), timeout=10)
            assert line, "no response — server exited early"
            # Every line on stdout MUST be pure JSON-RPC — a stray byte
            # of log/print noise ahead of the payload fails this parse.
            return json.loads(line)

        resp = await send({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
        assert resp["result"]["serverInfo"]["name"] == "bookstore"

        resp = await send({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
        names = {t["name"] for t in resp["result"]["tools"]}
        assert len(names) == 10
        assert "bookstore_related_books" in names

        resp = await send(
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {
                    "name": "bookstore_related_books",
                    "arguments": {"book_id": book_id},
                },
            }
        )
        assert resp["result"]["isError"] is False
    finally:
        proc.terminate()
        try:
            await asyncio.wait_for(proc.wait(), timeout=5)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()


@pytest.mark.asyncio
async def test_export_wiki_then_wiki_reads_it(library_five_books, tmp_path):
    from parrot.knowledge.wiki.cli import _load_graphindex_nodes_edges
    from parrot.knowledge.wiki.store import SQLiteWikiStore

    await library_five_books.relate_books(None, use_llm=False)
    out_dir = tmp_path / "wiki-export"
    result = await library_five_books.export_wiki(out_dir, register=False)

    read_store = SQLiteWikiStore(out_dir / "wiki.db", read_only=True)
    pages = await read_store.dump_pages()
    edges = await read_store.dump_edges()
    assert len(pages) == 5
    assert result["pages"] == len(pages)
    assert result["edges"] == len(edges)

    nodes, graph_edges = await _load_graphindex_nodes_edges(read_store, frozenset({"book"}))
    assert len(nodes) == 5
    assert len(graph_edges) == len(edges)


@pytest.mark.asyncio
async def test_no_llm_full_path(tmp_path, monkeypatch):
    monkeypatch.setenv("PARROT_LIBRARY_DIR", str(tmp_path / "library"))
    store = Bookstore(resolve_locations(cwd=tmp_path))  # no adapter — degraded mode

    specs = [
        ("book-a", ["Same Author"], ["shared-topic"]),
        ("book-b", ["Same Author"], ["shared-topic"]),
        ("book-c", ["Other Author"], ["different-topic"]),
    ]
    for stem, authors, topics in specs:
        md = tmp_path / f"{stem}.md"
        md.write_text(SAMPLE_MARKDOWN.replace("Synthetic Handbook", stem), encoding="utf-8")
        await store.add_book(md, title=stem, authors=authors, topics=topics)

    summary = await store.relate_books(None)

    assert summary.skipped_llm_reason == "no LLM configured"
    assert summary.deterministic_edges > 0
    assert summary.communities is not None

    assert store.related_books("book-a")
    assert store.communities()

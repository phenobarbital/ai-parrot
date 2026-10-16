"""Core wiki operations parity with the tools (FEAT-540 M3)."""

from __future__ import annotations

from pathlib import Path

import pytest

from parrot.knowledge.wiki.operations import (
    OperationResult,
    WikiLintInput,
    WikiNoteInput,
    WikiPageInput,
    WikiQueryInput,
    WikiRelatedInput,
    WikiRememberInput,
    WikiStatusInput,
    op_lint,
    op_note,
    op_page,
    op_query,
    op_related,
    op_remember,
    op_standup,
    op_status,
)
from parrot.knowledge.wiki.project import WikiProjectConfig
from parrot.knowledge.wiki.store import SQLiteWikiStore, WikiPageRecord
from parrot.knowledge.wiki.tools import (
    WikiLintTool,
    WikiNoteTool,
    WikiPageTool,
    WikiQueryTool,
    WikiRelatedTool,
    WikiRememberTool,
    WikiStandupTool,
    WikiStatusTool,
)

from .._support.import_probe import run_import_probe


@pytest.fixture
def store(tmp_path: Path) -> SQLiteWikiStore:
    """A tmp SQLite wiki with two linked pages."""
    wiki = SQLiteWikiStore(tmp_path / "wiki" / "wiki.db", wiki_name="t")
    return wiki


@pytest.fixture
async def seeded(store: SQLiteWikiStore) -> SQLiteWikiStore:
    await store.upsert_pages(
        [
            WikiPageRecord(
                concept_id="file:a.py", title="Alpha module", category="file", summary="alpha parser", body="alpha"
            ),
            WikiPageRecord(
                concept_id="file:b.py", title="Beta module", category="file", summary="beta parser", body="beta"
            ),
        ]
    )
    await store.add_edges([("file:a.py", "file:b.py", "references", "asserted")])
    return store


@pytest.fixture(autouse=True)
def _isolated_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("PARROT_HOME", str(home))
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(home / "xdg"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(home / "xdg-cache"))


@pytest.mark.asyncio
async def test_op_query_matches_tool(seeded: SQLiteWikiStore) -> None:
    op = await op_query(seeded, WikiQueryInput(question="parser"))
    assert isinstance(op, OperationResult) and not op.is_error
    assert "file:a.py" in op.text
    assert op.text == await WikiQueryTool(seeded)._execute(question="parser")


@pytest.mark.asyncio
async def test_op_query_excludes_symbols_by_default(seeded: SQLiteWikiStore) -> None:
    await seeded.upsert_pages(
        [WikiPageRecord(concept_id="sym:x#parser", title="parser sym", category="symbol", summary="parser", body="p")]
    )
    assert "sym:x#parser" not in (await op_query(seeded, WikiQueryInput(question="parser"))).text
    with_syms = await op_query(seeded, WikiQueryInput(question="parser", include_symbols=True))
    assert "sym:x#parser" in with_syms.text


@pytest.mark.asyncio
async def test_op_page_matches_tool(seeded: SQLiteWikiStore) -> None:
    op = await op_page(seeded, WikiPageInput(page_id="file:a.py"))
    tool = await WikiPageTool(seeded)._execute(page_id="file:a.py")
    assert op.data == tool.result and op.data["concept_id"] == "file:a.py"
    missing = await op_page(seeded, WikiPageInput(page_id="nope"))
    tool_missing = await WikiPageTool(seeded)._execute(page_id="nope")
    assert missing.is_error and missing.text == tool_missing.error == "Page not found: nope"


@pytest.mark.asyncio
async def test_op_related_matches_tool(seeded: SQLiteWikiStore) -> None:
    op = await op_related(seeded, WikiRelatedInput(page_id="file:a.py"))
    tool = await WikiRelatedTool(seeded)._execute(page_id="file:a.py")
    assert op.data == tool.result
    assert any(n.get("concept_id") == "file:b.py" for n in op.data["neighbors"])


@pytest.mark.asyncio
async def test_op_remember_matches_tool(seeded: SQLiteWikiStore, tmp_path: Path) -> None:
    params = WikiRememberInput(fact="gotcha about parsing", title="Parsing gotcha", link_page_id="file:a.py")
    op = await op_remember(seeded, params, storage_dir=tmp_path / "wiki")
    tool = await WikiRememberTool(seeded, tmp_path / "wiki")._execute(
        fact="gotcha about parsing", title="Parsing gotcha", link_page_id="file:a.py"
    )
    assert op.data == tool.result and op.data["linked"] is True
    assert op.data["page_id"].startswith("mem-")
    assert "REMEMBER" in (tmp_path / "wiki" / "log.md").read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_op_remember_rejects_foreign_link(seeded: SQLiteWikiStore) -> None:
    op = await op_remember(seeded, WikiRememberInput(fact="x", link_page_id="ghost::file:z.py"))
    tool = await WikiRememberTool(seeded)._execute(fact="x", link_page_id="ghost::file:z.py")
    assert op.is_error and op.text == tool.error


@pytest.mark.asyncio
async def test_op_note_matches_tool(seeded: SQLiteWikiStore, tmp_path: Path) -> None:
    op = await op_note(seeded, WikiNoteInput(page_id="file:a.py", text="hello"), storage_dir=tmp_path / "wiki")
    tool = await WikiNoteTool(seeded)._execute(page_id="file:a.py", text="again")
    assert op.data == tool.result == {"page_id": "file:a.py", "status": "noted"}
    page = await seeded.get_page("file:a.py", include_body=True)
    assert "hello" in page["body"] and "again" in page["body"]
    missing = await op_note(seeded, WikiNoteInput(page_id="nope", text="t"))
    assert missing.is_error and missing.text == "Page not found: nope"
    managed = await op_note(seeded, WikiNoteInput(page_id="adr:new", text="t"))
    assert managed.is_error and "managed ADR" in managed.text


@pytest.mark.asyncio
async def test_op_status_matches_tool(seeded: SQLiteWikiStore) -> None:
    op = await op_status(seeded, WikiStatusInput())
    assert op.data == (await WikiStatusTool(seeded)._execute()).result


@pytest.mark.asyncio
async def test_op_lint_matches_tool(seeded: SQLiteWikiStore, tmp_path: Path) -> None:
    storage = tmp_path / "wiki"
    storage.mkdir(exist_ok=True)
    op = await op_lint(seeded, WikiLintInput(), storage_dir=storage)
    tool = await WikiLintTool(seeded, storage_dir=storage)._execute()
    assert op.data == tool.result
    assert set(op.data) == {"counts", "fixed", "top", "report_dir"}


@pytest.mark.asyncio
async def test_op_standup_invalid_input_matches_tool(tmp_path: Path, store: SQLiteWikiStore) -> None:
    root = tmp_path / "proj"
    root.mkdir()
    config = WikiProjectConfig(wiki_name="t", storage_dir=str(tmp_path / "store"))
    op = await op_standup(store, {"date": "not-a-date"}, root=root, config=config)
    tool = await WikiStandupTool(store, root, config)._execute(date="not-a-date")
    assert op.is_error and "Invalid wiki_standup input" in op.text
    assert op.text == tool.error and tool.success is False


def test_operations_module_is_framework_free() -> None:
    source = (Path(__file__).resolve().parents[3] / "src/parrot/knowledge/wiki/operations.py").read_text("utf-8")
    assert "parrot.tools" not in source
    result = run_import_probe("parrot.knowledge.wiki.operations")
    assert result.error is None
    assert not result.has("parrot.tools.abstract")

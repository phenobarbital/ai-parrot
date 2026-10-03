"""Regression cases for FEAT-627 entity commands and ``remember`` metadata flags."""

import asyncio
import json
from pathlib import Path

import pytest
from click.testing import CliRunner

import parrot.knowledge.wiki.entity_cli as subject
from parrot.knowledge.wiki.store import SQLiteWikiStore, WikiPageRecord, create_wiki_store


@pytest.fixture(autouse=True)
def isolated_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep every test away from the developer's real wiki settings."""
    monkeypatch.setenv("PARROT_HOME", str(tmp_path / "parrot-home"))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    for name in ("WIKI_STORE", "WIKI_STORE_BACKEND", "CLAUDE_AGENT_ID", "PARROT_AGENT_ID"):
        monkeypatch.delenv(name, raising=False)


def _invoke(*args: str) -> object:
    """Invoke the ``entity`` group with an isolated runner."""
    return CliRunner().invoke(subject.entity, list(args))


def _wrapped(content: str, path: str = "docs/note.md") -> str:
    """Build a body exactly as the repo scanner wraps a markdown file."""
    return f"# {path}\n\n## Content\n{content}"


def test_entity_add_list_roundtrip(tmp_path: Path) -> None:
    """Add, list, filter by attrs/date bounds, and strict errors exit 2 with stable codes."""
    store_dir = tmp_path / "store"
    base = ["--store", str(store_dir)]
    result = _invoke(
        "add", "ticket", "Fix login", "--status", "open", "--project", "alpha", "--date", "2026-10-02",
        "--owner", "ana", "--by", "human:test", "--json", *base,
    )
    assert result.exit_code == 0, result.output
    created = json.loads(result.output)
    assert created["page_id"].startswith("entity:ticket:fix-login-")
    assert created["attrs"]["source"] == "authored"
    assert created["status"] == "created"

    again = _invoke("add", "ticket", "Fix login", "--status", "open", "--project", "alpha", "--date", "2026-10-02", "--json", *base)
    assert json.loads(again.output)["status"] == "updated"
    _invoke("add", "ticket", "Old bug", "--status", "closed", "--project", "beta", "--date", "2026-09-01", *base)
    _invoke("add", "person", "Ana", *base)

    listed = json.loads(_invoke("list", "--type", "ticket", "--json", *base).output)
    assert listed["count"] == 2
    only_open = json.loads(_invoke("list", "--type", "ticket", "--status", "open", "--json", *base).output)
    assert [row["title"] for row in only_open["entities"]] == ["Fix login"]
    bounded = json.loads(_invoke("list", "--since", "2026-10-01", "--until", "2026-10-31", "--json", *base).output)
    assert [row["title"] for row in bounded["entities"]] == ["Fix login"]
    by_project = json.loads(_invoke("list", "--project", "beta", "--json", *base).output)
    assert [row["title"] for row in by_project["entities"]] == ["Old bug"]
    assert "Fix login" in _invoke("list", *base).output
    assert "No matching entities." in _invoke("list", "--type", "meeting", *base).output

    for args, code in (
        (("add", "bogus", "x"), "E_ENTITY_TYPE"),
        (("add", "ticket", "x", "--status", "nope"), "E_ENTITY_STATUS"),
        (("add", "ticket", "x", "--date", "not-a-date"), "E_ENTITY_DATE"),
        (("list", "--since", "garbage"), "E_ENTITY_DATE"),
    ):
        failed = _invoke(*args, *base)
        assert failed.exit_code == 2, args
        assert code in failed.output


def test_entity_add_links_use_asserted_edges(tmp_path: Path) -> None:
    """Existing link targets get asserted edges; unknown targets are reported, not created."""
    store_dir = tmp_path / "store"
    base = ["--store", str(store_dir)]
    project = json.loads(_invoke("add", "project", "Alpha", "--json", *base).output)
    result = _invoke(
        "add", "task", "Ship it", "--link", project["page_id"], "--link", "missing", "--json", *base
    )
    payload = json.loads(result.output)
    assert payload["linked"] == [project["page_id"]]
    assert payload["skipped_links"] == ["missing"]
    store = create_wiki_store(store_dir)
    neighbours = asyncio.run(store.neighbors(payload["page_id"], direction="out"))
    assert any(edge.get("concept_id") == project["page_id"] or project["page_id"] in str(edge) for edge in neighbours)


def test_reindex_large_inventory_and_dryrun(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Reindex handles >500 pages exactly once, wrapped markdown, idempotency and dry-run."""
    store_dir = tmp_path / "store"
    store = create_wiki_store(store_dir)
    total = 1203
    pages = []
    for index in range(total):
        content = f"---\ntype: ticket\nstatus: Open\nupdated_at: 2026-10-02\n---\nbody {index}\n"
        pages.append(
            WikiPageRecord(concept_id=f"file:docs/n{index}.md", title=f"n{index}", category="document",
                           body=_wrapped(content, f"docs/n{index}.md"))
        )
    pages.append(WikiPageRecord(concept_id="file:docs/plain.md", title="plain", category="document",
                                body=_wrapped("no frontmatter here\n", "docs/plain.md")))
    pages.append(WikiPageRecord(concept_id="note:vault", title="vault", category="document", body="just text"))
    asyncio.run(store.upsert_pages(pages))

    fetched: list[str] = []
    original = SQLiteWikiStore.get_page

    async def counting_get_page(self: SQLiteWikiStore, concept_id: str, include_body: bool = True):  # type: ignore[no-untyped-def]
        if include_body:
            fetched.append(concept_id)
        return await original(self, concept_id, include_body)

    monkeypatch.setattr(SQLiteWikiStore, "get_page", counting_get_page)
    log_path = store_dir / "log.md"

    dry = _invoke("reindex", "--dry-run", "--store", str(store_dir))
    assert dry.exit_code == 0, dry.output
    assert f"would update {total}" in dry.output
    assert not log_path.exists()
    assert asyncio.run(create_wiki_store(store_dir).stats())["attrs_pages"] == 0

    fetched.clear()
    real = _invoke("reindex", "--store", str(store_dir))
    assert real.exit_code == 0, real.output
    assert f"updated {total}" in real.output
    assert len(fetched) == len(set(fetched)) == total + 2
    assert "REINDEX" in log_path.read_text()
    check = asyncio.run(create_wiki_store(store_dir).get_attrs("file:docs/n7.md"))
    assert check["type"] == "ticket"
    assert check["status"] == "open"
    assert check["status_raw"] == "Open"
    assert check["source"] == "markdown"
    assert check["date"] == "2026-10-02"

    second = _invoke("reindex", "--store", str(store_dir))
    assert f"updated 0, unchanged {total}" in second.output


def test_reindex_refuses_foreign_namespace_and_unsupported_store(tmp_path: Path) -> None:
    """A non-local --ns is refused before anything is opened."""
    store_dir = tmp_path / "store"
    result = _invoke("reindex", "--ns", "other", "--store", str(store_dir))
    assert result.exit_code == 2
    assert "foreign" in result.output
    assert not store_dir.exists()


def test_remember_flags_and_ns_rejection(tmp_path: Path) -> None:
    """remember persists normalized attrs with source=memory; defaults and errors are preserved."""
    from parrot.knowledge.wiki.cli import wiki

    store_dir = tmp_path / "store"
    base = ["--store", str(store_dir)]
    runner = CliRunner()
    ok = runner.invoke(
        wiki,
        ["remember", "Standup moved to 10am", "--title", "Standup", "--type", "meeting", "--status", "Scheduled",
         "--project", "alpha", "--date", "2026-10-03", "--due", "2026-10-04", "--owner", "ana", "--by", "human:t",
         "--json", *base],
    )
    assert ok.exit_code == 0, ok.output
    page_id = json.loads(ok.output)["page_id"]
    attrs = asyncio.run(create_wiki_store(store_dir).get_attrs(page_id))
    assert attrs == {
        "type": "meeting", "status": "scheduled", "status_raw": "Scheduled", "project": "alpha",
        "date": "2026-10-03", "due": "2026-10-04", "owner": "ana", "source": "memory",
    }

    plain = runner.invoke(wiki, ["remember", "Plain fact", "--by", "human:t", "--json", *base])
    assert plain.exit_code == 0, plain.output
    plain_id = json.loads(plain.output)["page_id"]
    assert asyncio.run(create_wiki_store(store_dir).get_attrs(plain_id)) == {}

    bad = runner.invoke(wiki, ["remember", "x", "--type", "meeting", "--status", "open", *base])
    assert bad.exit_code == 2
    assert "E_ENTITY_STATUS" in bad.output

    foreign = runner.invoke(wiki, ["remember", "x", "--ns", "all", *base])
    assert foreign.exit_code != 0

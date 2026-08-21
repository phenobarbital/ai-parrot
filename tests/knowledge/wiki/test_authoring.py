"""Tests for the wiki authoring / persistent-memory surface.

Covers the ``remember`` / ``note`` / ``link`` / ``memories`` / ``audit``
CLI commands, the origin/asserted_by store columns (+ migration of
pre-existing databases), 4-tuple ``add_edges`` provenance, the
``LLMWikiToolkit.update_page`` staleness regression, and the graph
mirror behind ``sync_graph``.
"""

import json
import sqlite3
from pathlib import Path

import pytest
from click.testing import CliRunner

from parrot.knowledge.wiki.cli import wiki
from parrot.knowledge.wiki.project import (
    load_project_config,
    save_project_config,
)
from parrot.knowledge.wiki.store import (
    SQLiteWikiStore,
    WikiPageRecord,
)


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A repo with a built (empty-ish) wiki plane."""
    (tmp_path / "README.md").write_text("# Demo\n\nDemo.", encoding="utf-8")
    runner = CliRunner()
    result = runner.invoke(
        wiki, ["build", "--path", str(tmp_path), "--no-git", "--no-graph"]
    )
    assert result.exit_code == 0, result.output
    return tmp_path


def _remember(runner, repo, text, *extra):
    result = runner.invoke(
        wiki, ["remember", text, "--path", str(repo), "--json", *extra]
    )
    assert result.exit_code == 0, result.output
    return json.loads(result.output[result.output.index("{"):])


# =====================================================================
# Store: origin / asserted_by / provenance edges / migration
# =====================================================================


class TestStoreAuthoringColumns:
    async def test_origin_and_asserted_by_round_trip(self, tmp_path):
        store = SQLiteWikiStore(tmp_path / "wiki.db")
        await store.upsert_pages([
            WikiPageRecord(
                concept_id="m1",
                title="Fact",
                origin="memory",
                asserted_by="agent:x",
            )
        ])
        page = await store.get_page("m1")
        assert page["origin"] == "memory"
        assert page["asserted_by"] == "agent:x"

    async def test_default_origin_is_ingest(self, tmp_path):
        store = SQLiteWikiStore(tmp_path / "wiki.db")
        await store.upsert_pages([WikiPageRecord(concept_id="p1", title="T")])
        page = await store.get_page("p1")
        assert page["origin"] == "ingest"
        assert page["asserted_by"] is None

    async def test_list_pages_origin_filter(self, tmp_path):
        store = SQLiteWikiStore(tmp_path / "wiki.db")
        await store.upsert_pages([
            WikiPageRecord(concept_id="src1", title="Ingested"),
            WikiPageRecord(concept_id="m1", title="Memory", origin="memory"),
            WikiPageRecord(concept_id="a1", title="Authored", origin="authored"),
        ])
        rows = await store.list_pages(origin=["memory", "authored"])
        assert {r["concept_id"] for r in rows} == {"m1", "a1"}

    async def test_add_edges_four_tuple_provenance(self, tmp_path):
        store = SQLiteWikiStore(tmp_path / "wiki.db")
        await store.upsert_pages([
            WikiPageRecord(concept_id="a", title="A"),
            WikiPageRecord(concept_id="b", title="B"),
        ])
        await store.add_edges([
            ("a", "b", "references", "asserted"),
            ("b", "a", "mentions"),
        ])
        with sqlite3.connect(tmp_path / "wiki.db") as conn:
            rows = dict(
                ((src, dst), prov)
                for src, dst, prov in conn.execute(
                    "SELECT src, dst, provenance FROM edges"
                )
            )
        assert rows[("a", "b")] == "asserted"
        assert rows[("b", "a")] == "extracted"

    async def test_old_schema_db_migrates(self, tmp_path):
        # Build a wiki.db WITHOUT the origin/asserted_by columns.
        db = tmp_path / "wiki.db"
        with sqlite3.connect(db) as conn:
            conn.executescript(
                """
                CREATE TABLE pages (
                    concept_id  TEXT PRIMARY KEY,
                    node_id     TEXT,
                    title       TEXT NOT NULL,
                    category    TEXT NOT NULL DEFAULT 'concept',
                    summary     TEXT NOT NULL DEFAULT '',
                    body        TEXT NOT NULL DEFAULT '',
                    source_id   TEXT,
                    token_count INTEGER NOT NULL DEFAULT 0,
                    created_at  TEXT NOT NULL,
                    updated_at  TEXT NOT NULL
                );
                INSERT INTO pages (concept_id, title, created_at, updated_at)
                VALUES ('legacy', 'Old page', 't', 't');
                """
            )
        store = SQLiteWikiStore(db)
        page = await store.get_page("legacy", include_body=False)
        assert page["origin"] == "ingest"
        await store.upsert_pages([
            WikiPageRecord(concept_id="new", title="New", origin="memory")
        ])
        assert (await store.get_page("new"))["origin"] == "memory"


# =====================================================================
# CLI: remember / note / link / memories / audit
# =====================================================================


class TestRememberCommand:
    def test_remember_creates_memory(self, runner, repo):
        data = _remember(
            runner, repo, "Always pin the CI runner version",
            "--category", "lesson", "--by", "agent:tester",
        )
        assert data["status"] == "created"
        assert data["page_id"].startswith("mem-")
        assert data["asserted_by"] == "agent:tester"

    def test_remember_is_idempotent(self, runner, repo):
        first = _remember(runner, repo, "Fact one", "--title", "Fact")
        second = _remember(runner, repo, "Fact one, refined", "--title", "Fact")
        assert first["page_id"] == second["page_id"]
        assert second["status"] == "updated"

    def test_remember_found_by_query(self, runner, repo):
        _remember(runner, repo, "The gateway retries thrice on 502", "--title", "Gateway retries")
        result = runner.invoke(
            wiki, ["query", "gateway retries 502", "--path", str(repo), "--json"]
        )
        assert result.exit_code == 0, result.output
        assert "Gateway retries" in result.output

    def test_remember_links_to_existing_page(self, runner, repo):
        first = _remember(runner, repo, "Base fact", "--title", "Base")
        second = _remember(
            runner, repo, "Derived fact", "--title", "Derived",
            "--link", first["page_id"],
        )
        assert second["linked"] == [first["page_id"]]
        related = runner.invoke(
            wiki, ["related", second["page_id"], "--path", str(repo)]
        )
        assert first["page_id"] in related.output

    def test_remember_skips_unknown_link(self, runner, repo):
        data = _remember(
            runner, repo, "Fact", "--title", "F", "--link", "no-such-page"
        )
        assert data["skipped_links"] == ["no-such-page"]

    def test_env_identity_and_run_id(self, runner, repo, monkeypatch):
        monkeypatch.setenv("CLAUDE_AGENT_ID", "cc-1")
        monkeypatch.setenv("CLAUDE_SESSION_ID", "sess-9")
        data = _remember(runner, repo, "Env fact", "--title", "EnvFact")
        assert data["asserted_by"] == "agent:cc-1"
        config = load_project_config(repo)
        log = (config.storage_path(repo) / "log.md").read_text()
        assert "agent:cc-1" in log
        assert "sess-9" in log


class TestNoteCommand:
    def test_note_appends_attributed_blockquote(self, runner, repo):
        data = _remember(runner, repo, "Original body", "--title", "Page")
        result = runner.invoke(
            wiki,
            ["note", data["page_id"], "Watch out for tz handling",
             "--path", str(repo), "--by", "human:rev"],
        )
        assert result.exit_code == 0, result.output
        page = runner.invoke(
            wiki, ["page", data["page_id"], "--path", str(repo), "--json"]
        )
        body = json.loads(page.output[page.output.index("{"):])["body"]
        assert "Watch out for tz handling" in body
        assert "human:rev" in body
        assert "Original body" in body

    def test_note_unknown_page_errors(self, runner, repo):
        result = runner.invoke(
            wiki, ["note", "missing-id", "text", "--path", str(repo)]
        )
        assert result.exit_code != 0
        assert "not found" in result.output


class TestLinkCommand:
    def test_link_pages(self, runner, repo):
        a = _remember(runner, repo, "A", "--title", "A")
        b = _remember(runner, repo, "B", "--title", "B")
        result = runner.invoke(
            wiki,
            ["link", a["page_id"], b["page_id"], "--rel", "explains",
             "--path", str(repo), "--json"],
        )
        assert result.exit_code == 0, result.output
        config = load_project_config(repo)
        with sqlite3.connect(config.db_path(repo)) as conn:
            row = conn.execute(
                "SELECT provenance FROM edges WHERE src = ? AND dst = ?"
                " AND rel = 'explains'",
                (a["page_id"], b["page_id"]),
            ).fetchone()
        assert row == ("asserted",)

    def test_link_unknown_page_errors(self, runner, repo):
        a = _remember(runner, repo, "A", "--title", "A")
        result = runner.invoke(
            wiki, ["link", a["page_id"], "ghost", "--path", str(repo)]
        )
        assert result.exit_code != 0


class TestMemoriesAndAudit:
    def test_memories_lists_only_authored(self, runner, repo):
        _remember(runner, repo, "Fact", "--title", "OnlyMemory")
        result = runner.invoke(wiki, ["memories", "--path", str(repo)])
        assert result.exit_code == 0, result.output
        assert "OnlyMemory" in result.output
        # Ingested README page must not appear.
        assert "README" not in result.output

    def test_audit_shows_operations(self, runner, repo):
        _remember(runner, repo, "Fact", "--title", "Audited")
        result = runner.invoke(wiki, ["audit", "--path", str(repo)])
        assert result.exit_code == 0, result.output
        assert "REMEMBER" in result.output


# =====================================================================
# sync_graph mirror
# =====================================================================


class TestGraphSync:
    def test_remember_mirrors_into_graph_plane(self, runner, repo):
        config = load_project_config(repo)
        config.sync_graph = True
        save_project_config(repo, config)

        data = _remember(runner, repo, "Graph-synced fact", "--title", "GraphFact")
        assert "graph_commit" in data

        graph_db = config.graph_path(repo) / f"{config.wiki_name}.db"
        assert graph_db.exists()
        with sqlite3.connect(graph_db) as conn:
            titles = [
                r[0] for r in conn.execute("SELECT title FROM nodes")
            ]
            commits = conn.execute(
                "SELECT COUNT(*) FROM graph_commits"
            ).fetchone()[0]
        assert "GraphFact" in titles
        assert commits == 1

        audit = runner.invoke(wiki, ["audit", "--path", str(repo)])
        assert "Graph write commits" in audit.output

    def test_no_sync_by_default(self, runner, repo):
        data = _remember(runner, repo, "Plain fact", "--title", "Plain")
        assert "graph_commit" not in data
        config = load_project_config(repo)
        assert not (config.graph_path(repo)).exists()


# =====================================================================
# LLMWikiToolkit regression: update_page must refresh the store plane
# =====================================================================


class TestUpdatePageRegression:
    @pytest.fixture
    def toolkit(self, tmp_path):
        from parrot.knowledge.wiki.models import WikiConfig
        from parrot.knowledge.wiki.toolkit import LLMWikiToolkit

        class _StubPI:
            async def insert_markdown(self, *a, **k):
                return {"tree_name": "t", "new_node_ids": []}

        config = WikiConfig(
            wiki_name="test-wiki", storage_dir=tmp_path / "wiki"
        )
        return LLMWikiToolkit(
            pageindex_toolkit=_StubPI(),
            graphindex_toolkit=None,
            okf_toolkit=None,
            config=config,
        )

    async def test_update_page_refreshes_store_and_fts(self, toolkit):
        created = await toolkit.create_page(
            "test-wiki", "My Page", "original searchable alpha content"
        )
        page_id = created["page_id"]
        result = await toolkit.update_page(
            "test-wiki", page_id, "completely new bravo content"
        )
        assert result["status"] == "updated"
        page = await toolkit._store.get_page(page_id)
        assert "bravo" in page["body"]
        hits = await toolkit._store.search_fts("bravo")
        assert any(h["concept_id"] == page_id for h in hits)
        stale = await toolkit._store.search_fts("alpha")
        assert not any(h["concept_id"] == page_id for h in stale)

    async def test_update_page_not_found(self, toolkit):
        result = await toolkit.update_page("test-wiki", "ghost", "content")
        assert result["status"] == "not_found"

    async def test_remember_tool_idempotent(self, toolkit):
        first = await toolkit.remember("test-wiki", "A fact", title="Fact")
        second = await toolkit.remember("test-wiki", "A better fact", title="Fact")
        assert first["page_id"] == second["page_id"]
        assert first["status"] == "created"
        assert second["status"] == "updated"
        page = await toolkit._store.get_page(first["page_id"])
        assert page["origin"] == "memory"


class TestCreatePageWithoutAuthoringPlane:
    """``create_page`` composed with ``pageindex_toolkit=None``.

    Regression: the PageIndex insert was called unconditionally, so a
    ``None`` toolkit raised ``AttributeError`` into the best-effort
    except and logged "'NoneType' object has no attribute
    'insert_markdown'" on every page — noise that named neither the cause
    nor the remedy.
    """

    def _toolkit(self, tmp_path, pageindex_toolkit):
        from parrot.knowledge.wiki.models import WikiConfig
        from parrot.knowledge.wiki.toolkit import LLMWikiToolkit

        config = WikiConfig(wiki_name="test-wiki", storage_dir=tmp_path / "wiki")
        return LLMWikiToolkit(
            pageindex_toolkit=pageindex_toolkit,
            graphindex_toolkit=None,
            okf_toolkit=None,
            config=config,
        )

    @pytest.mark.asyncio
    async def test_no_pageindex_still_writes_the_retrieval_plane(
        self, tmp_path, caplog
    ):
        toolkit = self._toolkit(tmp_path, None)

        with caplog.at_level("WARNING"):
            result = await toolkit.create_page("test-wiki", "My Page", "body")

        assert result["status"] == "created"
        # Falls back to a title-derived id, and says nothing alarming.
        assert result["page_id"] == "page-my-page"
        assert not any(
            "NoneType" in rec.message or "insert failed" in rec.message
            for rec in caplog.records
        )
        page = await toolkit._store.get_page(result["page_id"])
        assert page["body"] == "body"

    @pytest.mark.asyncio
    async def test_pageindex_node_id_is_used_when_available(self, tmp_path):
        class _StubPI:
            async def insert_markdown(self, *a, **k):
                return {"tree_name": "t", "new_node_ids": ["node-42"]}

        toolkit = self._toolkit(tmp_path, _StubPI())

        result = await toolkit.create_page("test-wiki", "My Page", "body")

        assert result["page_id"] == "node-42"

    @pytest.mark.asyncio
    async def test_pageindex_failure_still_degrades_with_a_warning(
        self, tmp_path, caplog
    ):
        """A real toolkit that throws keeps the existing warning path."""

        class _BoomPI:
            async def insert_markdown(self, *a, **k):
                raise RuntimeError("tree write failed")

        toolkit = self._toolkit(tmp_path, _BoomPI())

        with caplog.at_level("WARNING"):
            result = await toolkit.create_page("test-wiki", "My Page", "body")

        assert result["status"] == "created"
        assert any(
            "PageIndex insert failed" in rec.message for rec in caplog.records
        )

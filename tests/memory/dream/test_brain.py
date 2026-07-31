"""Unit tests for parrot.memory.dream.brain.BrainStore (TASK-1984)."""
import hashlib

import pytest
from parrot.knowledge.wiki import SQLiteWikiStore
from parrot.memory.dream import BrainStore


@pytest.fixture
def brain(tmp_path):
    return BrainStore(
        tmp_path / "brain", wiki_name="brain-test-agent", asserted_by="agent:test-agent"
    )


class TestBrainStore:
    async def test_remember_idempotent(self, brain):
        r1 = await brain.remember(
            "Always check X before Y", title="Check X", category="lesson"
        )
        r2 = await brain.remember(
            "Always check X before Y (v2)", title="Check X", category="lesson"
        )
        assert r1["page_id"] == r2["page_id"]
        assert r1["status"] == "created"
        assert r2["status"] == "updated"

    async def test_page_id_matches_llmwikitoolkit_scheme(self, brain):
        r = await brain.remember("body", title="T", category="lesson")
        expected = "mem-" + hashlib.sha1(b"T::lesson").hexdigest()[:12]
        assert r["page_id"] == expected

    async def test_search_fts(self, brain):
        await brain.remember(
            "PgVector JSONB merge needs || operator",
            title="JSONB merge",
            category="lesson",
        )
        out = await brain.search("JSONB merge")
        assert "JSONB" in out

    async def test_search_empty(self, brain):
        assert await brain.search("nothing here") == ""

    async def test_copy_page_to(self, brain, tmp_path):
        org = BrainStore(tmp_path / "org", wiki_name="org-test")
        r = await brain.remember(
            "shared insight", title="Insight", category="concept"
        )
        pid = await brain.copy_page_to(r["page_id"], org)
        assert pid == r["page_id"]
        assert "shared insight" in await org.search("shared insight")

    async def test_copy_page_preserves_attribution(self, brain, tmp_path):
        org = BrainStore(tmp_path / "org2", wiki_name="org-test2")
        r = await brain.remember("orig text", title="Orig", category="note")
        await brain.copy_page_to(r["page_id"], org)
        page = await org._store.get_page(r["page_id"], include_body=True)
        assert page["asserted_by"] == "agent:test-agent"

    async def test_copy_missing_page_logs_and_returns_id(self, brain, tmp_path):
        org = BrainStore(tmp_path / "org3", wiki_name="org-test3")
        result = await brain.copy_page_to("mem-doesnotexist", org)
        assert result == "mem-doesnotexist"

    async def test_wiki_db_interop_with_sqlitewikistore(self, brain, tmp_path):
        r = await brain.remember("interop text", title="Interop", category="note")
        direct = SQLiteWikiStore(
            brain.storage_dir / "wiki.db", wiki_name="brain-test-agent"
        )
        page = await direct.get_page(r["page_id"], include_body=True)
        assert page is not None
        assert page["title"] == "Interop"
        assert page["body"] == "interop text"

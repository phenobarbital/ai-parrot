"""Generic writes cannot corrupt a managed ADR page (FEAT-578 M6, AC10)."""

from __future__ import annotations

import hashlib
from unittest.mock import Mock

import pytest

from parrot.knowledge.wiki.decisions.codec import decision_from_page, decision_to_page
from parrot.knowledge.wiki.decisions.models import DecisionRecord, ReviewEvent
from parrot.knowledge.wiki.models import WikiConfig
from parrot.knowledge.wiki.store import SQLiteWikiStore, WikiPageRecord
from parrot.knowledge.wiki.toolkit import LLMWikiToolkit
from parrot.knowledge.wiki.tools import WikiNoteTool, WikiRememberTool


@pytest.fixture
def adr_store(tmp_path):
    """A real SQLite retrieval plane — the guard reads the stored category,
    which a mock store cannot exercise faithfully."""
    return SQLiteWikiStore(tmp_path / "wiki.db")


@pytest.fixture
async def seeded(adr_store):
    """A stored ADR record carrying one review event."""
    record = DecisionRecord(
        decision_id="adr:doc:a", decision="use pgvector", origin="documented", source_status="accepted",
        review_history=[ReviewEvent(revision=1, action="accept", actor="human:m",
                                    timestamp="2026-01-01T00:00:00+00:00", reason="ok",
                                    before_sha1="b", after_sha1="a")],
    )
    await adr_store.upsert_pages([decision_to_page(record)])
    return adr_store, record


class TestManagedPageProtection:
    async def test_note_refuses_an_adr_page(self, seeded):
        store, _ = seeded
        result = await WikiNoteTool(store)._execute(page_id="adr:doc:a", text="a stray note")
        assert result.success is False
        assert "ADR_MANAGED_PAGE" in (result.error or "")

    async def test_refused_note_leaves_the_record_decodable(self, seeded):
        """The point of the guard: history must survive (AC6)."""
        store, record = seeded
        await WikiNoteTool(store)._execute(page_id="adr:doc:a", text="a stray note")
        decoded = decision_from_page(await store.get_page("adr:doc:a"))
        assert decoded == record
        assert len(decoded.review_history) == 1

    async def test_remember_cannot_overwrite_an_adr_page(self, adr_store):
        # WikiRememberTool never accepts a caller-supplied page id — it
        # always derives one deterministically from title+category. Seed an
        # ADR page at exactly the id that title+category will hash to, so
        # the write attempt actually targets a managed page.
        title, category = "collision-check", "note"
        target_id = "mem-" + hashlib.sha1(f"{title}::{category}".encode()).hexdigest()[:12]
        record = DecisionRecord(decision_id=target_id, decision="use pgvector",
                                 origin="documented", source_status="accepted")
        await adr_store.upsert_pages([decision_to_page(record)])

        tool = WikiRememberTool(adr_store)
        result = await tool._execute(fact="a stray fact", title=title, category=category)
        assert result.success is False
        assert "ADR_MANAGED_PAGE" in (result.error or "")

        decoded = decision_from_page(await adr_store.get_page(target_id))
        assert decoded == record

    async def test_toolkit_update_page_refuses(self, seeded, tmp_path):
        store, record = seeded
        toolkit = LLMWikiToolkit(
            pageindex_toolkit=Mock(),
            graphindex_toolkit=Mock(),
            okf_toolkit=Mock(),
            config=WikiConfig(wiki_name="test-wiki", storage_dir=tmp_path / "wiki", storage_backend="memory"),
            store=store,
        )
        result = await toolkit.update_page(wiki_name="test-wiki", page_id="adr:doc:a", content="corrupted")
        assert result["status"] == "refused"
        assert "ADR_MANAGED_PAGE" in (result.get("reason") or "")

        decoded = decision_from_page(await store.get_page("adr:doc:a"))
        assert decoded == record

    async def test_a_nonexistent_adr_id_is_also_refused(self, adr_store):
        """An id-prefix pre-filter closes the create-then-corrupt path."""
        result = await WikiNoteTool(adr_store)._execute(page_id="adr:doc:nope", text="x")
        assert result.success is False and "ADR_MANAGED_PAGE" in (result.error or "")

    async def test_namespaced_adr_id_is_refused(self, adr_store):
        # The foreign-id guard may fire first (unknown namespace) — either
        # refusal is acceptable, a SUCCESS is not.
        result = await WikiNoteTool(adr_store)._execute(page_id="other::adr:doc:a", text="x")
        assert result.success is False


class TestOrdinaryPagesUnaffected:
    async def test_note_still_works_on_a_concept_page(self, adr_store):
        """AC10: existing behaviour is untouched."""
        await adr_store.upsert_pages([WikiPageRecord(concept_id="concept:x", title="X",
                                                     category="concept", body="body")])
        result = await WikiNoteTool(adr_store)._execute(page_id="concept:x", text="a note")
        assert result.success is True
        assert "a note" in (await adr_store.get_page("concept:x"))["body"]

    async def test_remember_still_works(self, adr_store):
        tool = WikiRememberTool(adr_store)
        result = await tool._execute(fact="an ordinary fact", category="note")
        assert result.success is True
        assert result.result["category"] == "note"


class TestIdGrammar:
    @pytest.mark.parametrize("page_id", ["adr:doc:abc123", "adr:candidate:def456", "other::adr:doc:abc123"])
    def test_adr_ids_parse_as_page_ids(self, page_id):
        from parrot.knowledge.wiki.context import split_namespaced_id

        namespace, local = split_namespaced_id(page_id)
        assert local.startswith("adr:")

    def test_adr_stub_lines_keep_their_labels(self):
        """AC9: the generic renderer must not strip the [INFERRED / ...] prefix."""
        from parrot.knowledge.wiki.context import stub_line

        record = DecisionRecord(decision_id="adr:candidate:xyz", decision="maybe use X", origin="inferred")
        row = decision_to_page(record).model_dump()
        line = stub_line(row)
        assert "INFERRED" in line

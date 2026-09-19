"""DecisionRepository bounds, conflicts and backend policy (FEAT-578 M2)."""

from __future__ import annotations

import pytest

from parrot.knowledge.wiki.decisions.codec import decision_to_page
from parrot.knowledge.wiki.decisions.models import ADR_CATEGORY, DecisionError, DecisionRecord
from parrot.knowledge.wiki.decisions.repository import DecisionRepository
from parrot.knowledge.wiki.store import WikiPageRecord


@pytest.fixture
def record() -> DecisionRecord:
    """A minimal valid documented record."""
    return DecisionRecord(decision_id="adr:doc:a", decision="use pgvector", origin="documented")


@pytest.fixture
async def store(tmp_path):
    """A real file-backed plane — CAS semantics must be genuine (TASK-3482)."""
    from parrot.knowledge.wiki.file_store import InMemoryWikiStore

    return InMemoryWikiStore(tmp_path / "pages", wiki_name="t")


class _UnsupportedStore:
    """Minimal duck-typed store whose CAS is not implemented."""

    async def compare_and_swap_page(self, page, expected_content_hash):
        raise NotImplementedError("no conditional write")

    async def get_page(self, concept_id, include_body=True):
        return None

    async def list_pages(self, category=None, limit=100, origin=None):
        return []


class _ReadOnlyStore:
    """Minimal duck-typed store whose CAS refuses writes."""

    async def compare_and_swap_page(self, page, expected_content_hash):
        raise PermissionError("store is read-only")

    async def get_page(self, concept_id, include_body=True):
        return None

    async def list_pages(self, category=None, limit=100, origin=None):
        return []


class _StubListStore:
    """A store whose list_pages omits bodies; only get_page has them."""

    def __init__(self, full_page: dict) -> None:
        self._full_page = full_page

    async def list_pages(self, category=None, limit=100, origin=None):
        stub = dict(self._full_page)
        stub["body"] = ""
        return [stub]

    async def get_page(self, concept_id, include_body=True):
        if concept_id == self._full_page["concept_id"]:
            return dict(self._full_page)
        return None

    async def compare_and_swap_page(self, page, expected_content_hash):
        raise NotImplementedError


class TestSave:
    async def test_insert_then_conflict(self, store, record):
        """A second insert of the same id is ADR_REVISION_CONFLICT."""
        repo = DecisionRepository(store)
        await repo.save(record, None)
        with pytest.raises(DecisionError) as exc:
            await repo.save(record, None)
        assert exc.value.code == "ADR_REVISION_CONFLICT"
        assert exc.value.decision_id == "adr:doc:a"

    async def test_round_trip_through_get(self, store, record):
        """get() returns the record and the hash save() needs next."""
        repo = DecisionRepository(store)
        await repo.save(record, None)
        loaded, page_hash = await repo.get("adr:doc:a")
        assert loaded == record
        assert page_hash == decision_to_page(record).content_hash

        bumped = record.model_copy(update={"revision": 2, "decision": "use pgvector, revised"})
        await repo.save(bumped, page_hash)

        with pytest.raises(DecisionError) as exc:
            await repo.save(bumped, page_hash)
        assert exc.value.code == "ADR_REVISION_CONFLICT"

    async def test_get_missing_returns_none(self, store):
        assert await DecisionRepository(store).get("adr:doc:nope") is None

    async def test_unsupported_backend_is_typed(self, record):
        """A CAS-less backend yields ADR_WRITE_UNSUPPORTED, not NotImplementedError."""
        repo = DecisionRepository(_UnsupportedStore())
        with pytest.raises(DecisionError) as exc:
            await repo.save(record, None)
        assert exc.value.code == "ADR_WRITE_UNSUPPORTED"

    async def test_read_only_backend_is_typed(self, record):
        """A read-only plane yields ADR_READ_ONLY, not PermissionError."""
        repo = DecisionRepository(_ReadOnlyStore())
        with pytest.raises(DecisionError) as exc:
            await repo.save(record, None)
        assert exc.value.code == "ADR_READ_ONLY"


class TestInventory:
    async def test_returns_all_records(self, store):
        """Every stored ADR page is hydrated and decoded."""
        repo = DecisionRepository(store)
        for i in range(3):
            r = DecisionRecord(decision_id=f"adr:doc:{i}", decision=f"decision {i}", origin="documented")
            await repo.save(r, None)
        records = await repo.inventory()
        assert {r.decision_id for r in records} == {"adr:doc:0", "adr:doc:1", "adr:doc:2"}
        assert repo.last_diagnostics == []

    async def test_exceeding_the_bound_is_an_explicit_error(self, store, record):
        """Never a silently incomplete 'no decisions' answer (spec §2, AC14)."""
        repo = DecisionRepository(store, max_records=2)
        for i in range(3):
            r = DecisionRecord(decision_id=f"adr:doc:{i}", decision=f"decision {i}", origin="documented")
            await repo.save(r, None)
        with pytest.raises(DecisionError) as exc:
            await repo.inventory()
        assert exc.value.code == "ADR_INVENTORY_LIMIT"

    async def test_at_the_bound_still_succeeds(self, store):
        """max_records records is fine; max_records + 1 is not."""
        repo = DecisionRepository(store, max_records=2)
        for i in range(2):
            r = DecisionRecord(decision_id=f"adr:doc:{i}", decision=f"decision {i}", origin="documented")
            await repo.save(r, None)
        records = await repo.inventory()
        assert len(records) == 2

    async def test_one_corrupt_page_becomes_a_diagnostic(self, store, record):
        """A single bad page must not blank the whole inventory."""
        repo = DecisionRepository(store)
        await repo.save(record, None)
        await store.upsert_pages(
            [
                WikiPageRecord(
                    concept_id="adr:doc:garbage",
                    title="garbage",
                    category=ADR_CATEGORY,
                    body="not a valid envelope at all",
                )
            ]
        )
        records = await repo.inventory()
        assert [r.decision_id for r in records] == ["adr:doc:a"]
        assert len(repo.last_diagnostics) == 1
        assert repo.last_diagnostics[0].code == "ADR_SCHEMA_UNSUPPORTED"
        assert repo.last_diagnostics[0].decision_id == "adr:doc:garbage"

    async def test_hydrates_bodies_even_when_list_pages_omits_them(self, record):
        """list_pages stubs are not decodable — get_page must be called."""
        full_page = decision_to_page(record).model_dump()
        full_page["concept_id"] = record.decision_id
        stub_store = _StubListStore(full_page)
        repo = DecisionRepository(stub_store)
        records = await repo.inventory()
        assert len(records) == 1
        assert records[0].decision_id == record.decision_id
        assert repo.last_diagnostics == []

"""for_symbol / why retrieval semantics (FEAT-578 Module 4, AC2/AC3/AC5)."""

from __future__ import annotations

import pytest

from parrot.knowledge.wiki.decisions.models import DecisionConfig, DecisionLink, DecisionRecord, EvidenceRef
from parrot.knowledge.wiki.decisions.repository import DecisionRepository
from parrot.knowledge.wiki.decisions.service import DecisionService, tokenize_query


def _record(decision_id, *, origin="documented", links=(), **kw) -> DecisionRecord:
    return DecisionRecord(
        decision_id=decision_id,
        decision=kw.pop("decision", "use pgvector for the primary store"),
        origin=origin,
        source_status=kw.pop("source_status", "accepted" if origin == "documented" else "unknown"),
        links=list(links),
        **kw,
    )


@pytest.fixture
async def service(adr_store, tmp_path):
    """A service over a seeded plane, with no client and no structural service."""
    return DecisionService(adr_store, tmp_path, DecisionConfig(), structural=None, client=None)


class _StubHit:
    def __init__(self, symbol_id: str, qualname: str):
        self.symbol_id = symbol_id
        self.qualname = qualname


class _StubLookupOutput:
    def __init__(self, hits):
        self.hits = hits
        self.total = len(hits)
        self.repaired_files = []


class _StubStructural:
    def __init__(self, hits):
        self._hits = hits

    async def lookup(self, query, **kwargs):
        return _StubLookupOutput(self._hits)


class TestForSymbol:
    async def test_exact_symbol_id_returns_linked_records(self, service, adr_store):
        record = _record(
            "adr:doc:a",
            links=[DecisionLink(target_id="sym:a.py#f", relation="explains", provenance="extracted")],
        )
        await DecisionRepository(adr_store).save(record, None)
        dossier = await service.for_symbol("sym:a.py#f")
        assert dossier.status == "ok"
        assert [h.decision_id for h in dossier.documented] == ["adr:doc:a"]

    async def test_file_scope_links_are_included_and_labeled(self, service, adr_store):
        """Module-level citations apply at file scope, labeled separately (spec §2)."""
        record = _record(
            "adr:doc:a",
            links=[DecisionLink(target_id="file:a.py", relation="explains", provenance="extracted")],
        )
        await DecisionRepository(adr_store).save(record, None)
        dossier = await service.for_symbol("sym:a.py#f")
        assert dossier.status == "ok"
        assert dossier.documented[0].applicability[0].target_id == "file:a.py"

    async def test_duplicate_names_are_ambiguous(self, adr_store, tmp_path):
        """AC2: a bare name matching two symbols never guesses."""
        structural = _StubStructural([_StubHit("sym:a.py#f", "f"), _StubHit("sym:b.py#f", "f")])
        service = DecisionService(adr_store, tmp_path, DecisionConfig(), structural=structural, client=None)
        dossier = await service.for_symbol("f")
        assert dossier.status == "ambiguous"
        assert set(dossier.alternatives) == {"sym:a.py#f", "sym:b.py#f"}

    async def test_no_match_is_empty(self, service):
        dossier = await service.for_symbol("sym:nope.py#gone")
        assert dossier.status == "empty" and not dossier.documented and not dossier.candidates

    async def test_no_call_graph_inheritance(self, service, adr_store):
        """spec §2: applicability does not propagate through callers."""
        record = _record(
            "adr:doc:a",
            links=[DecisionLink(target_id="sym:a.py#callee", relation="explains", provenance="extracted")],
        )
        await DecisionRepository(adr_store).save(record, None)
        await adr_store.add_edges([("sym:a.py#caller", "sym:a.py#callee", "calls")])
        dossier = await service.for_symbol("sym:a.py#caller")
        assert dossier.status == "empty"

    async def test_a_graph_edge_alone_never_establishes_applicability(self, service, adr_store):
        """The edges-are-a-cache rule (spec §2) — the core retrieval guarantee."""
        record = _record("adr:doc:a", links=[])
        await DecisionRepository(adr_store).save(record, None)
        await adr_store.add_edges([("adr:doc:a", "sym:a.py#f", "explains")])
        dossier = await service.for_symbol("sym:a.py#f")
        assert dossier.status == "empty"


class TestWhyRanking:
    def test_score_weights_fields_4_3_1_1(self, service):
        """The weighting is spec text, not a tuning knob."""
        tokens = tokenize_query("pgvector")
        title_hit = _record("adr:doc:t", title="pgvector", decision="x", context="", observations=[])
        decision_hit = _record("adr:doc:d", title="x", decision="pgvector", observations=[])
        assert service._score(title_hit, tokens, set()) > service._score(decision_hit, tokens, set())

    def test_distinct_tokens_count_once_per_field(self, service):
        tokens = tokenize_query("pgvector")
        repeated = _record("adr:doc:r", decision="pgvector pgvector pgvector pgvector pgvector")
        once = _record("adr:doc:o", decision="pgvector")
        assert service._score(repeated, tokens, set()) == service._score(once, tokens, set())

    async def test_documented_current_accepted_ranks_first(self, service, adr_store):
        """The three-tier group order (spec §2)."""
        repo = DecisionRepository(adr_store)
        accepted = _record("adr:doc:accepted", decision="unrelated text", source_status="accepted")
        unknown_high_score = _record("adr:doc:unknown", decision="pgvector pgvector match", source_status="unknown")
        await repo.save(accepted, None)
        await repo.save(unknown_high_score, None)
        dossier = await service.why("pgvector")
        assert [h.decision_id for h in dossier.documented] == ["adr:doc:accepted", "adr:doc:unknown"]

    async def test_candidates_never_enter_the_documented_group(self, service, adr_store):
        """AC3."""
        repo = DecisionRepository(adr_store)
        await repo.save(_record("adr:doc:a", origin="documented"), None)
        await repo.save(_record("adr:candidate:b", origin="inferred"), None)
        dossier = await service.why("pgvector")
        assert [h.decision_id for h in dossier.documented] == ["adr:doc:a"]
        assert [h.decision_id for h in dossier.candidates] == ["adr:candidate:b"]

    async def test_decision_id_breaks_ties_stably(self, service, adr_store):
        repo = DecisionRepository(adr_store)
        await repo.save(_record("adr:doc:zzz", decision="pgvector"), None)
        await repo.save(_record("adr:doc:aaa", decision="pgvector"), None)
        dossier1 = await service.why("pgvector")
        dossier2 = await service.why("pgvector")
        ids1 = [h.decision_id for h in dossier1.documented]
        ids2 = [h.decision_id for h in dossier2.documented]
        assert ids1 == ids2 == sorted(ids1)

    async def test_history_is_hidden_by_default(self, service, adr_store):
        repo = DecisionRepository(adr_store)
        await repo.save(_record("adr:doc:old", decision="pgvector", source_status="superseded"), None)
        dossier = await service.why("pgvector")
        assert dossier.documented == []
        dossier_with_history = await service.why("pgvector", include_history=True)
        assert [h.decision_id for h in dossier_with_history.documented] == ["adr:doc:old"]

    async def test_unknown_status_is_displayed_not_elevated(self, service, adr_store):
        """AC3: unknown shows up, labeled unknown — never as accepted."""
        repo = DecisionRepository(adr_store)
        await repo.save(_record("adr:doc:u", decision="pgvector", source_status="unknown"), None)
        dossier = await service.why("pgvector")
        assert len(dossier.documented) == 1
        assert dossier.documented[0].source_status == "unknown"

    async def test_budget_is_respected(self, service, adr_store):
        repo = DecisionRepository(adr_store)
        for i in range(10):
            await repo.save(_record(f"adr:doc:{i}", decision="pgvector " * 500), None)
        dossier = await service.why("pgvector", budget_tokens=256, limit=50)
        assert dossier.truncated is True
        for hit in dossier.documented:
            assert hit.decision_id and hit.freshness


class TestOffline:
    async def test_lookup_and_why_make_zero_llm_calls(self, service, adr_store, monkeypatch):
        """AC5: no client is constructed or invoked on any read path."""
        from parrot.clients.base import AbstractClient
        from parrot.clients.factory import LLMFactory

        def _fail_create(*args, **kwargs):
            raise AssertionError("read paths must never construct an LLM client")

        async def _fail_invoke(*args, **kwargs):
            raise AssertionError("read paths must never invoke an LLM client")

        monkeypatch.setattr(LLMFactory, "create", staticmethod(_fail_create))
        monkeypatch.setattr(AbstractClient, "invoke", _fail_invoke)

        await service.for_symbol("sym:a.py#f")
        await service.why("pgvector")

    # NOTE (TASK-3493): `sync`/`generate`/`review` were declared here as
    # NotImplementedError stubs by TASK-3490, precisely so retrieval could be
    # built and tested before Module 5's orchestration existed ("TASK-3493
    # fills them in (same file, sequenced after this task)" — TASK-3490's own
    # scope). TASK-3493 has now replaced those stubs with real
    # implementations; the assertion that they raise NotImplementedError no
    # longer holds and is superseded by test_service_generation.py's full
    # dedup/drift/review coverage.

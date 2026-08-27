"""Unit tests for the retrieval DAG stages + answer() orchestration (FEAT-449 TASK-2497)."""

from datetime import date

import pytest
from parrot_tools.legal.boe.hashing import seal_hash
from parrot_tools.legal.librarian.flow import (
    answer,
    build_legal_librarian_crew,
    dossier_build,
    graph_retrieve,
)
from parrot_tools.legal.librarian.models import DraftAnswer, DraftReadingNote, DraftSpan


class FakeLog:
    def __init__(self):
        self.records = []

    async def append(self, record):
        self.records.append(record)


class FakeAgent:
    """Stands in for LegalLibrarianAgent — returns a canned DraftAnswer."""

    def __init__(self, draft):
        self._draft = draft

    async def draft(self, enumerated_dossier, query, as_of):
        return self._draft

    async def ask(self, *a, **k):
        raise AssertionError("as_of fallback must not be needed")


def _version_dict(n, text, valid_from, valid_to, modified_by=None):
    return {
        "n": n,
        "text": text,
        "valid_from": valid_from,
        "valid_to": valid_to,
        "modified_by": modified_by,
        "kind": "redaccion",
        "source": "boe_consolidada",
        "derived": False,
        "content_hash": seal_hash(text) if text is not None else None,
        "hash_norm_version": 1 if text is not None else None,
    }


@pytest.fixture
async def seeded_store(fake_store, legal_tenant_ctx):
    await fake_store.upsert_nodes(
        legal_tenant_ctx,
        "articulo",
        [
            {
                "articulo_key": "BOE-A-2015-10566:50",
                "norma_ref": "BOE-A-2015-10566",
                "numero": "50",
                "versions": [
                    _version_dict(0, "El plazo sera de tres meses.", "2015-01-01", None),
                ],
            }
        ],
        key_field="articulo_key",
    )
    return fake_store


class TestGraphRetrieve:
    async def test_explicit_boe_id_resolved_first(self, seeded_store, legal_tenant_ctx):
        hits = await graph_retrieve(seeded_store, legal_tenant_ctx, "BOE-A-2015-10566:50 que dice", date(2020, 1, 1))
        assert hits[0]["articulo_key"] == "BOE-A-2015-10566:50"
        assert hits[0]["basis"] == "traversal"


class TestDossierBuild:
    async def test_dossier_build_order_and_truncation(self):
        long_text = "x" * 5000
        hits = [
            {
                "articulo_key": "BOE-A-1:1",
                "norma_ref": "BOE-A-1",
                "numero": "1",
                "version": type(
                    "V",
                    (),
                    {
                        "n": 0,
                        "text": long_text,
                        "content_hash": seal_hash(long_text),
                        "valid_from": date(2020, 1, 1),
                        "valid_to": None,
                    },
                )(),
                "basis": "traversal",
                "score": None,
            }
        ]
        retrieval_set, enumerated, scores = dossier_build(hits, date(2021, 1, 1))
        assert "BOE-A-1:1:0" in retrieval_set
        assert retrieval_set["BOE-A-1:1:0"].payload == long_text  # full, untruncated payload
        assert "[...]" in enumerated  # prompt view is truncated
        assert scores["BOE-A-1:1:0"] is None


class TestAnswerFlow:
    async def test_flow_prunes_fabricated_payload_key(self, seeded_store, legal_tenant_ctx):
        fabricated = DraftAnswer(
            reading_order=["BOE-A-9999-1:art99:0"],
            conflicts=[],
            not_found=[],
            reading_guide=[
                DraftReadingNote(
                    text="Dice algo inventado.",
                    basis="llm",
                    spans=[DraftSpan(payload_key="BOE-A-9999-1:art99:0", quote="inventado")],
                )
            ],
        )
        log = FakeLog()
        ans = await answer(
            "plazo de tres meses a 2019-06-01",
            agent=FakeAgent(fabricated),
            store=seeded_store,
            ctx=legal_tenant_ctx,
            log=log,
        )
        assert ans.as_of == date(2019, 6, 1)
        assert all(r.id != "BOE-A-9999-1:art99" for r in ans.dossier)
        assert ans.suppressed_count == 1
        # Single-span note citing an unknown payload_key -> deterministically
        # "span_not_found" per SpanVerifier's rule (single-reason notes keep
        # their span's own reason; "anchor_lost" is only for mixed-reason
        # multi-span notes — see verifier.py's class docstring).
        assert log.records[0].reason == "span_not_found"
        assert all(note.spans for note in ans.reading_guide)

    async def test_flow_prunes_mangled_quote(self, seeded_store, legal_tenant_ctx):
        draft = DraftAnswer(
            reading_order=["BOE-A-2015-10566:50:0"],
            conflicts=[],
            not_found=[],
            reading_guide=[
                DraftReadingNote(
                    text="Dice algo distinto.",
                    basis="llm",
                    spans=[
                        DraftSpan(
                            payload_key="BOE-A-2015-10566:50:0",
                            quote="texto que no existe en el payload",
                        )
                    ],
                )
            ],
        )
        log = FakeLog()
        ans = await answer(
            "BOE-A-2015-10566:50 plazo a 2019-06-01",
            agent=FakeAgent(draft),
            store=seeded_store,
            ctx=legal_tenant_ctx,
            log=log,
        )
        assert ans.dossier == []
        assert log.records[0].reason == "quote_mismatch"

    async def test_flow_no_encontre_on_empty_retrieval(self, fake_store, legal_tenant_ctx):
        empty_draft = DraftAnswer(reading_order=[], conflicts=[], reading_guide=[], not_found=[])
        ans = await answer(
            "jurisprudencia del TC sobre X",
            agent=FakeAgent(empty_draft),
            store=fake_store,
            ctx=legal_tenant_ctx,
            log=FakeLog(),
        )
        assert ans.dossier == []
        assert ans.reading_guide == []
        assert ans.not_found

    async def test_flow_ground_suppresses_contradicted_atom(self, fake_store, legal_tenant_ctx):
        text = "La indemnizacion sera de 1500 euros por dia de retraso."
        await fake_store.upsert_nodes(
            legal_tenant_ctx,
            "articulo",
            [
                {
                    "articulo_key": "BOE-A-2015-10566:50",
                    "norma_ref": "BOE-A-2015-10566",
                    "numero": "50",
                    "versions": [_version_dict(0, text, "2015-01-01", None)],
                }
            ],
            key_field="articulo_key",
        )
        key = "BOE-A-2015-10566:50:0"
        draft = DraftAnswer(
            reading_order=[key],
            conflicts=[],
            not_found=[],
            reading_guide=[
                DraftReadingNote(
                    text="La indemnizacion asciende a 1600 euros por dia.",
                    basis="llm",
                    spans=[DraftSpan(payload_key=key, quote="1500 euros")],
                )
            ],
        )
        log = FakeLog()
        ans = await answer(
            "BOE-A-2015-10566:50 indemnizacion a 2020-01-01",
            agent=FakeAgent(draft),
            store=fake_store,
            ctx=legal_tenant_ctx,
            log=log,
        )
        assert ans.reading_guide == []
        assert any(r.reason == "atom_contradicted" for r in log.records)
        assert ans.dossier  # the span itself remains a valid citation

    async def test_as_of_equals_graph_retrieve_date(self, seeded_store, legal_tenant_ctx):
        draft = DraftAnswer(reading_order=[], conflicts=[], reading_guide=[], not_found=[])
        ans = await answer(
            "plazo de tres meses a 2022-05-05",
            agent=FakeAgent(draft),
            store=seeded_store,
            ctx=legal_tenant_ctx,
            log=FakeLog(),
        )
        assert ans.as_of == date(2022, 5, 5)


class TestBuildLegalLibrarianCrew:
    """Structural-only coverage — see build_legal_librarian_crew's docstring
    Warning: the returned crew is NOT executable via run_flow() (no kwargs
    template wiring on the ToolNodes); answer() is the tested/executed path.
    """

    def test_registers_all_six_nodes_with_expected_dependencies(self, fake_store, legal_tenant_ctx):
        from parrot_tools.legal.librarian.agent import LegalLibrarianAgent

        agent = LegalLibrarianAgent()
        crew = build_legal_librarian_crew(agent, fake_store, legal_tenant_ctx, FakeLog())

        assert set(crew.workflow_graph) == {
            "as_of_extract",
            "graph_retrieve",
            "dossier_build",
            "librarian",
            "span_verify",
            "ground",
        }
        assert crew.workflow_graph["as_of_extract"].dependencies == set()
        assert crew.workflow_graph["graph_retrieve"].dependencies == {"as_of_extract"}
        assert crew.workflow_graph["dossier_build"].dependencies == {
            "as_of_extract",
            "graph_retrieve",
        }
        assert crew.workflow_graph["librarian"].dependencies == {"dossier_build"}
        assert crew.workflow_graph["span_verify"].dependencies == {"librarian", "dossier_build"}
        assert crew.workflow_graph["ground"].dependencies == {"span_verify"}

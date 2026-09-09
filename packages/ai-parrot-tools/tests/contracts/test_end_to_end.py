"""The full contracts vertical slice (TASK-3054).

fake Graph delta -> ingest -> verify -> temporal publish -> both answer
producers -> retire -> refresh -> watcher report, over a **real Postgres
catalog** when one is configured.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Optional
from unittest.mock import MagicMock

import pytest

from parrot.knowledge.contracts.library import ContractLibrary
from parrot.knowledge.contracts.temporal import ContractTemporalPublisher
from parrot_tools.contracts.agent import ContractsAgentProducer
from parrot_tools.contracts.flow import ContractsAnswerFlow, ContractsDraftProducer
from parrot_tools.contracts.jobs import (
    SourceConfig,
    ingest_delta,
    obligations_digest,
    renewals_report,
)
from parrot_tools.contracts.retrieval import ContractRetrieval, RequestContext
from parrot_tools.contracts.service import ContractsAnswerService
from parrot_tools.contracts.toolkit import ContractsToolkit
from parrot_tools.contracts.verifier import CitationVerifier

from .conftest import FROZEN_NOW, PG_DSN, TODAY, requires_pg
from .test_ingest_delta import FakeDeltaTool, FakeIndexer, item, page

pytestmark = pytest.mark.asyncio

MSA = """# ACME Master Services Agreement

Entered into between Troc Global Inc. and ACME, Inc.

## Term

This Agreement is effective as of January 1, 2026 and continues for twelve
(12) months. Either party may give sixty (60) days notice.

## Compliance

Vendor shall maintain SOC 2 Type II certification.
"""


def reader() -> RequestContext:
    """An authenticated reader."""
    return RequestContext(
        user_id="bob@troc",
        roles=("contract_reader",),
        tenant_id="troc",
        employee_id="emp-1",
        employee_graph_id="employees/emp-1",
    )


def owner() -> RequestContext:
    """An authenticated owner with a transport confirmation."""
    return RequestContext(
        user_id="bob@troc",
        roles=("contract_owner",),
        tenant_id="troc",
        employee_id="emp-1",
        confirmed=True,
    )


def principal() -> RequestContext:
    """The unattended service principal the watcher jobs run as."""
    return RequestContext(
        user_id="svc-contracts",
        roles=("contract_reader",),
        tenant_id="troc",
        employee_id="svc",
    )


def build_library(catalog: Any, tmp_path: Path) -> ContractLibrary:
    """A library over the given catalog and the lean fake indexer."""
    indexers: dict[Path, FakeIndexer] = {}
    return ContractLibrary(
        catalog=catalog,
        storage_root=tmp_path / "storage",
        evidence_root=tmp_path / "evidence",
        adapter=None,
        indexer_factory=lambda directory, adapter: indexers.setdefault(
            Path(directory), FakeIndexer(directory, adapter)
        ),
        now=lambda: FROZEN_NOW,
        today=lambda: TODAY,
    )


@requires_pg
async def test_the_full_vertical_slice(live_catalog, tmp_path, pg_pool):
    """Delta -> ingest -> verify -> publish -> answer -> retire -> refresh."""
    from parrot.knowledge.graphindex.persist_postgres import PostgresPersistence

    library = build_library(live_catalog, tmp_path)
    documents = tmp_path / "documents"
    documents.mkdir()
    source_file = documents / "acme-msa.md"
    source_file.write_text(MSA, encoding="utf-8")

    async def downloader(entry):
        return source_file

    # 1. A fake Graph delta page drives ingestion.
    tool = FakeDeltaTool([page([item("a")])])
    ingested = await ingest_delta(
        library=library,
        delta_tool=tool,
        source=SourceConfig(source="sharepoint://legal", drive_id="drive-1"),
        principal=principal(),
        downloader=downloader,
    )
    assert ingested.report.added == 1
    assert ingested.cursor_committed, "the cursor advanced after a durable batch"
    contract_id = ingested.report.items[0].contract_id

    # 2. A human verifies the title.
    verification = await library.verify_card(
        contract_id, {"title": "ACME Master Services Agreement"}, user="bob@troc"
    )
    assert verification.corrected == ["title"]

    # 3. Temporal publication.
    gi_schema = f"gi_e2e_{uuid.uuid4().hex[:8]}"
    persistence = PostgresPersistence(dsn=PG_DSN, schema=gi_schema)
    publisher = ContractTemporalPublisher(catalog=live_catalog, persistence=persistence)
    ctx = MagicMock()
    ctx.tenant_id = "troc"
    try:
        drained = await publisher.drain(ctx)
        # Both the ingestion and the verification queued a revision.
        assert set(drained.published) == {contract_id}
        assert len(drained.published) == 2

        # 4. Both answer producers, over the same service.
        retrieval = ContractRetrieval(catalog=live_catalog, today=lambda: TODAY)
        verifier = CitationVerifier(catalog=live_catalog, evidence=library.evidence)
        service = ContractsAnswerService(retrieval=retrieval, verifier=verifier)
        flow = ContractsAnswerFlow(
            service=service, producer=ContractsDraftProducer(adapter=None)
        )

        question = "What obligations does the acme-msa carry?"
        fixed = await flow.answer(question, request_context=reader())
        assert fixed.answer.answer_kind in {"lookup", "not_found"}
        assert await live_catalog.get_answer(fixed.answer_id) is not None

        class Agent:
            async def ask(self, prompt: str):
                return type("Reply", (), {"output": "Vendor shall maintain SOC 2."})()

        service.producer = ContractsAgentProducer(Agent())
        react = await service.answer(question, request_context=reader())
        assert react.answer.answer_kind in {"lookup", "not_found"}
        assert await live_catalog.get_answer(react.answer_id) is not None

        # 5. The toolkit reads the same data behind the same gate.
        toolkit = ContractsToolkit(
            service=service, request_context=reader(), library=library
        )
        card = await toolkit.get_card(contract_id)
        assert card["title"] == "ACME Master Services Agreement"
        toc = await toolkit.get_toc(contract_id)
        assert toc["toc"]

        # 6. Retirement suppresses whatever the released answer cited.
        released = fixed if fixed.answer.citations else react
        if released.answer.citations:
            await service.retire_answer(
                released.answer_id, request_context=owner(), reason="pilot review"
            )
            suppressed = await live_catalog.retired_citations()
            assert suppressed
            node_id = released.answer.citations[0].node_id
            section = await toolkit.read_section(contract_id, node_id)
            assert section["body"] is None
            assert "retired" in section["reason"]

        # 7. A refresh keeps the human decision and the historical evidence.
        #    A Graph-sourced card has no local path, so the refresh is given
        #    the freshly downloaded bytes explicitly — exactly what the CLI's
        #    `refresh --source` and the delta job's downloader supply.
        source_file.write_text(MSA.replace("(12) months", "(24) months"))
        without_bytes = await library.refresh_card(contract_id)
        assert without_bytes.outcome == "error"
        assert "source not found" in without_bytes.reason

        refreshed = await library.refresh_card(contract_id, source=source_file)
        assert refreshed.outcome == "updated", refreshed.reason
        assert refreshed.card.title == "ACME Master Services Agreement"

        from parrot.knowledge.contracts.evidence import EvidenceRef
        from parrot.knowledge.contracts.models import Citation

        first_version = (await live_catalog.versions(contract_id))[0]
        citation = Citation(
            contract_id=contract_id,
            node_id="0001",
            quote="(12) months",
            version_n=first_version.n,
            source_sha256=first_version.source_sha256,
        )
        lookup = await library.evidence.resolve(
            citation, EvidenceRef.parse(first_version.evidence_ref)
        )
        assert lookup.found is True, "historical evidence survives the refresh"

        # 8. The watcher jobs report deterministically over the same catalog.
        renewals = await renewals_report(
            retrieval=retrieval, principal=principal(), today=TODAY
        )
        assert [bucket.label for bucket in renewals.buckets] == ["0-30", "31-60", "61-90"]
        digest = await obligations_digest(
            retrieval=retrieval, principal=principal(), today=TODAY, days=30
        )
        assert digest.prose is None, "nothing is drafted or delivered implicitly"
    finally:
        pool = await persistence._ensure_pool()
        async with pool.acquire() as connection:
            await connection.execute(f"DROP SCHEMA IF EXISTS {gi_schema} CASCADE")
        await persistence.close()


@requires_pg
async def test_a_second_delta_run_is_idempotent(live_catalog, tmp_path):
    """Unchanged content produces no new revision and re-commits the cursor."""
    library = build_library(live_catalog, tmp_path)
    documents = tmp_path / "documents"
    documents.mkdir()
    source_file = documents / "acme-msa.md"
    source_file.write_text(MSA, encoding="utf-8")

    async def downloader(entry):
        return source_file

    tool = FakeDeltaTool([page([item("a")]), page([item("a")])])
    config = SourceConfig(source="sharepoint://legal", drive_id="drive-1")

    first = await ingest_delta(
        library=library, delta_tool=tool, source=config,
        principal=principal(), downloader=downloader,
    )
    second = await ingest_delta(
        library=library, delta_tool=tool, source=config,
        principal=principal(), downloader=downloader,
    )

    assert first.report.added == 1
    assert second.report.added == 0 and second.report.skipped == 1
    contract_id = first.report.items[0].contract_id
    assert (await live_catalog.get(contract_id)).revision == 1
    assert len(await live_catalog.versions(contract_id)) == 1


@requires_pg
async def test_an_unauthorized_reader_gets_nothing_end_to_end(live_catalog, tmp_path):
    """The whole slice fails closed for a principal with no roles."""
    library = build_library(live_catalog, tmp_path)
    documents = tmp_path / "documents"
    documents.mkdir()
    source_file = documents / "acme-msa.md"
    source_file.write_text(MSA, encoding="utf-8")

    await library.add_contract(source_file)

    retrieval = ContractRetrieval(catalog=live_catalog, today=lambda: TODAY)
    service = ContractsAnswerService(
        retrieval=retrieval,
        verifier=CitationVerifier(catalog=live_catalog, evidence=library.evidence),
        producer=ContractsDraftProducer(adapter=None),
    )
    stranger = RequestContext(user_id="mallory@example", roles=(), tenant_id="troc")

    outcome = await service.answer(
        "What obligations does the acme-msa carry?", request_context=stranger
    )
    assert outcome.answer.answer_kind == "denied"
    assert outcome.answer.citations == []
    record = await live_catalog.get_answer(outcome.answer_id)
    assert record.authorization.allowed is False, "the denial is audited"


CLAUSE = "Vendor shall maintain SOC 2 Type II certification."


def carded_contract(contract_id: str = "acme-msa"):
    """A card carrying one citable obligation, as an LLM carding produces."""
    from parrot.knowledge.contracts.models import (
        ContractCard, Obligation, Party, TermSpec,
    )

    return ContractCard(
        contract_id=contract_id,
        title="ACME Master Services Agreement",
        summary="Compliance obligations for ACME.",
        contract_type="msa",
        status="active",
        source_uri=f"sharepoint://legal/{contract_id}.md",
        source_sha256="a" * 64,
        source_format="md",
        owner_employee_id="emp-1",
        parties=[
            Party(party_id="party-us", name="Troc Global", role="us", is_us=True),
            Party(party_id="party-acme", name="ACME, Inc.", role="vendor"),
        ],
        term=TermSpec(effective_date=date(2026, 1, 1), expiration_date=date(2026, 12, 31)),
        obligations=[
            Obligation(
                obligation_id=f"{contract_id}-ob-001",
                contract_id=contract_id,
                kind="compliance",
                text=CLAUSE,
                node_id="0002",
                page=3,
                standard_id="soc2",
            )
        ],
        added_at=FROZEN_NOW,
        updated_at=FROZEN_NOW,
    )


async def seed_carded_contract(catalog, library, contract_id: str = "acme-msa"):
    """Persist a citable card plus its immutable evidence archive."""
    from parrot.knowledge.contracts.models import ContractVersion, card_snapshot_payload

    card = carded_contract(contract_id)
    ref = library.evidence.reference(
        contract_id, version_n=1, revision=1, source_sha256=card.source_sha256
    )
    await library.evidence.archive(ref, {"0002": CLAUSE}, pages={"0002": 3}, overwrite=True)
    version = ContractVersion(
        n=1,
        revision=1,
        valid_from=card.term.effective_date,
        kind="original",
        source_sha256=card.source_sha256,
        card_snapshot=card_snapshot_payload(card),
        evidence_ref=ref.as_string(),
        recorded_at=FROZEN_NOW,
    )
    await catalog.upsert(card, version=version)
    return card


@requires_pg
async def test_citations_survive_a_revision_bump(live_catalog, tmp_path):
    """An administrative revision must not sever a card from its evidence.

    The evidence archive is immutable and is written once per *version*.
    Card revisions, by contrast, are bumped by ordinary administrative
    operations — Bob verifying a field (AC11), a party merge, a relation
    update. If the release gate rebuilds the archive pointer from the card's
    *current* revision instead of from the pointer stored on the version
    row, every citation stops resolving after the first such operation and
    a fully evidenced answer silently degrades to ``not_found``.

    This is the AC4 promise ("historical citations still resolve to
    immutable evidence") stated as an executable test.
    """
    library = build_library(live_catalog, tmp_path)
    card = await seed_carded_contract(live_catalog, library)

    retrieval = ContractRetrieval(catalog=live_catalog, today=lambda: TODAY)
    service = ContractsAnswerService(
        retrieval=retrieval,
        verifier=CitationVerifier(catalog=live_catalog, evidence=library.evidence),
        producer=ContractsDraftProducer(adapter=None),
    )
    question = f"What obligations does the {card.contract_id} carry?"

    before = await service.answer(question, request_context=reader())
    assert before.answer.answer_kind == "lookup", before.answer.reason
    assert before.answer.citations, "a carded contract releases its evidence"

    # Any administrative write bumps the revision without a new version.
    stored = await live_catalog.get(card.contract_id)
    await live_catalog.upsert(stored, expected_revision=stored.revision)
    bumped = await live_catalog.get(card.contract_id)
    assert bumped.revision > stored.revision

    after = await service.answer(question, request_context=reader())
    assert after.answer.answer_kind == "lookup", after.answer.reason
    assert after.answer.citations, (
        "the evidence archive is immutable and still holds this version; a "
        "revision bump must not change where the gate reads it from"
    )


@requires_pg
async def test_a_verified_card_still_releases_its_citations(live_catalog, tmp_path):
    """The same guarantee through the real ``verify_card`` workflow (AC11)."""
    library = build_library(live_catalog, tmp_path)
    card = await seed_carded_contract(live_catalog, library, "acme-verified")

    retrieval = ContractRetrieval(catalog=live_catalog, today=lambda: TODAY)
    service = ContractsAnswerService(
        retrieval=retrieval,
        verifier=CitationVerifier(catalog=live_catalog, evidence=library.evidence),
        producer=ContractsDraftProducer(adapter=None),
    )
    question = f"What obligations does the {card.contract_id} carry?"

    assert (await service.answer(question, request_context=reader())).answer.citations

    verification = await library.verify_card(
        card.contract_id, {"title": "ACME MSA (verified)"}, user="bob@troc"
    )
    assert verification.corrected == ["title"]

    after = await service.answer(question, request_context=reader())
    assert after.answer.answer_kind == "lookup", after.answer.reason
    assert after.answer.citations, "verifying a field must not silence the citations"

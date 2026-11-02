"""FEAT-784 M11: keep FEAT-778 ADR retrieval compatible with decision eligibility (AC17)."""

from __future__ import annotations

from types import SimpleNamespace

from parrot.experts.knowledge.sources.adr import ADRSource
from parrot.experts.models import KnowledgeMode, KnowledgeSourceKind, KnowledgeSourceSpec
from parrot.knowledge.wiki.decisions.inventory import BATCH_MARKER_CATEGORY, batch_marker_id, is_eligible
from parrot.knowledge.wiki.decisions.models import DecisionConfig, DecisionRecord
from parrot.knowledge.wiki.decisions.repository import DecisionRepository
from parrot.knowledge.wiki.decisions.service import DecisionService
from parrot.knowledge.wiki.store import WikiPageRecord

BATCH = "batch-compat"
QUERY = "pgvector"
SCHEMA2_ID = "adr:spec:compat#active"


class _Counter:
    """Count characters deterministically for ADR inline-layer accounting."""

    def count(self, text: str) -> int:
        """Return the number of characters in ``text``."""
        return len(text)


async def _seed(store) -> list[DecisionRecord]:
    """Write the five compatibility fixtures and their published batch marker."""
    records = [
        DecisionRecord(
            decision_id="adr:doc:legacy-accepted",
            decision=f"Use {QUERY} for legacy accepted records.",
            origin="documented",
            source_status="accepted",
            review_status="unreviewed",
        ),
        DecisionRecord(
            decision_id="adr:doc:legacy-review-rejected",
            decision=f"Use {QUERY} for rejected legacy records.",
            origin="documented",
            source_status="accepted",
            review_status="rejected",
        ),
        DecisionRecord(
            schema_version=2,
            decision_id=SCHEMA2_ID,
            revision=3,
            decision=f"Use {QUERY} for the published schema-2 record.",
            origin="documented",
            source_status="accepted",
            document_id="compat",
            entry_id="active",
            batch_id=BATCH,
        ),
        DecisionRecord(
            schema_version=2,
            decision_id="adr:spec:compat#retired",
            decision=f"Use {QUERY} for the retired schema-2 record.",
            origin="documented",
            source_status="superseded",
            document_id="compat",
            entry_id="retired",
            batch_id=BATCH,
            lifecycle="retired",
        ),
        DecisionRecord(
            decision_id="adr:doc:legacy-proposed",
            decision=f"Use {QUERY} for proposed legacy records.",
            origin="documented",
            source_status="proposed",
        ),
    ]
    repository = DecisionRepository(store)
    for record in records:
        await repository.save(record, None)

    marker_body = (
        '{"batch_id":"batch-compat","decision_ids":'
        '["adr:spec:compat#active","adr:spec:compat#retired"],"state":"published"}'
    )
    marker_id = batch_marker_id(BATCH)
    marker = WikiPageRecord(
        concept_id=marker_id,
        node_id=marker_id,
        title=f"ADR batch {BATCH}",
        category=BATCH_MARKER_CATEGORY,
        summary="published",
        body=marker_body,
        origin="authored",
    )
    assert await store.compare_and_swap_page(marker, None)
    return records


async def test_adr_source_equivalence(adr_store) -> None:
    """ADRSource accepts exactly the eligible records returned by ``why``."""
    records = {record.decision_id: record for record in await _seed(adr_store)}
    service = DecisionService(adr_store, None, DecisionConfig())
    dossier = await service.why(QUERY, limit=50)
    returned = [hit.decision_id for hit in [*dossier.documented, *dossier.candidates]]
    expected = {
        decision_id
        for decision_id in returned
        if is_eligible(records[decision_id], approved_batches=frozenset({BATCH}))
    }
    spec = KnowledgeSourceSpec(source=KnowledgeSourceKind.ADR, mode=KnowledgeMode.INLINE, filter={})
    bundle = SimpleNamespace(manifest=SimpleNamespace(description=QUERY))

    layers = await ADRSource(service).layers(spec, bundle, workspace=None, counter=_Counter())

    assert {layer.source.removeprefix("adr:") for layer in layers} == expected


async def test_schema2_roundtrip_through_why(adr_store) -> None:
    """A published schema-2 envelope reaches ``why`` intact and without diagnostics."""
    records = {record.decision_id: record for record in await _seed(adr_store)}
    dossier = await DecisionService(adr_store, None, DecisionConfig()).why(QUERY, limit=50)
    hits = {hit.decision_id: hit for hit in [*dossier.documented, *dossier.candidates]}

    assert dossier.diagnostics == []
    assert hits[SCHEMA2_ID].decision_id == records[SCHEMA2_ID].decision_id
    assert hits[SCHEMA2_ID].revision == records[SCHEMA2_ID].revision

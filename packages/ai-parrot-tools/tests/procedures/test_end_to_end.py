"""In-process FEAT-601 round trip and technician-tip relinking."""

from __future__ import annotations

from datetime import date
from typing import Any, Optional

import pytest

from parrot.knowledge.common.provenance import Evidence, Extracted
from parrot.knowledge.manuals.models import ManualVersion, Step, StepIdentity, content_hash
from parrot.knowledge.manuals.tips import add_tip, relink_tips
from parrot_tools.procedures.retrieval import ProcedureRetrieval
from parrot_tools.procedures.service import ProceduresAnswerService
from parrot_tools.procedures.verifier import ProcedureVerifier

from ._doubles import FakeCatalog, FakeOntology, FakePattern, make_card, make_context


class ProjectingGraphStore:
    """Store rows and project the procedure traversal used by the answer service."""

    def __init__(self, card: Any = None) -> None:
        self.card = card
        self.nodes: dict[str, dict[str, dict[str, Any]]] = {}
        self.edges: dict[str, list[dict[str, Any]]] = {}

    async def upsert_document(self, ctx: Any, collection: str, document: dict[str, Any]) -> None:
        """Store a document by its collection key."""
        del ctx
        self.nodes.setdefault(collection, {})[document["_key"]] = dict(document)

    async def get_document(self, ctx: Any, collection: str, key: str) -> dict[str, Any] | None:
        """Return a stored document."""
        del ctx
        return self.nodes.get(collection, {}).get(key)

    async def query_documents(self, ctx: Any, collection: str, filters: dict[str, Any]) -> list[dict[str, Any]]:
        """Return documents matching all requested fields."""
        del ctx
        return [
            doc
            for doc in self.nodes.get(collection, {}).values()
            if all(doc.get(key) == value for key, value in filters.items())
        ]

    async def create_edges(self, ctx: Any, collection: str, edges: list[dict[str, Any]]) -> None:
        """Insert each edge once by its endpoint triple."""
        del ctx
        existing = self.edges.setdefault(collection, [])
        for edge in edges:
            if not any(
                (item["_from"], item["_to"], item["kind"]) == (edge["_from"], edge["_to"], edge["kind"])
                for item in existing
            ):
                existing.append(dict(edge))

    async def remove_edge_by_triple(self, ctx: Any, collection: str, source: str, target: str, kind: str) -> None:
        """Remove the matching relinked edge."""
        del ctx
        self.edges[collection] = [
            item
            for item in self.edges.get(collection, [])
            if (item["_from"], item["_to"], item["kind"]) != (source, target, kind)
        ]

    async def execute_traversal(
        self,
        ctx: Any,
        aql: str,
        bind_vars: Optional[dict[str, Any]] = None,
        collection_binds: Optional[dict[str, str]] = None,
    ) -> list[dict[str, Any]]:
        """Project active procedure steps from the stored manual card."""
        del ctx, collection_binds
        if aql != "procedure_steps":
            return []
        procedure_id = (bind_vars or {}).get("procedure_id")
        procedure = next(item for item in self.card.procedures if item.procedure_id == procedure_id)
        return [
            {
                "procedure": {"procedure_id": procedure.procedure_id},
                "step": {"step_id": step.identity.step_id},
                "order": step.order,
            }
            for step in procedure.steps
        ]


class _Evidence:
    """Evidence archive double retaining each verbatim step quote."""

    def __init__(self, card: Any) -> None:
        self.sections = {step.text.evidence.node_id: step.text.evidence.quote for step in card.procedures[0].steps}

    async def load_section(self, manual_id: str, version_n: int, node_id: str) -> str | None:
        """Return the archived body used by the verifier."""
        del manual_id, version_n
        return self.sections.get(node_id)


class _Files:
    """File-manager double that mints deterministic presigned figure URLs."""

    async def get_file_url(self, path: str, expiry: int = 3600) -> str:
        """Return a fake HTTPS URL for a stored media object."""
        del expiry
        return f"https://fake/{path}"


def _service(card: Any) -> ProceduresAnswerService:
    """Wire the production service around projecting in-memory collaborators."""
    version = ManualVersion(n=1, revision=card.revision, valid_from=date(2026, 1, 1), source_sha256="")
    card = card.model_copy(update={"versions": [version]})
    catalog = FakeCatalog(cards=[card])
    retrieval = ProcedureRetrieval(
        catalog=catalog,
        graph_store=ProjectingGraphStore(card),
        tenant_context=None,
        ontology=FakeOntology({"procedure_steps": FakePattern("procedure_steps")}),
        authorization=None,
    )
    return ProceduresAnswerService(
        retrieval=retrieval,
        verifier_factory=lambda selected: ProcedureVerifier(
            catalog=catalog, evidence=_Evidence(card), allowed_revision=selected
        ),
        catalog=catalog,
        file_manager=_Files(),
    )


@pytest.mark.asyncio
async def test_ingest_publish_answer_roundtrip() -> None:
    """A projecting graph returns the five ordered, evidenced procedure steps."""
    card = make_card()
    outcome = await _service(card).answer("How do I assemble Model X?", request_context=make_context())
    assert outcome.answer.answer_kind == "procedure"
    assert [step.order for step in outcome.answer.steps] == [1, 2, 3, 4, 5]
    assert len(outcome.answer.citations) == 5
    assert outcome.image_urls and outcome.image_urls[0].startswith("https://fake/")


@pytest.mark.asyncio
async def test_tip_survives_revision() -> None:
    """Identity relinks, unchanged text hashes relink, and removed steps orphan tips."""
    store = ProjectingGraphStore()
    previous = [
        Step(
            identity=StepIdentity(step_id="m:s3", source_identity="3", content_hash=content_hash("Three")),
            order=3,
            text=Extracted(value="Three", evidence=Evidence(node_id="3", quote="Three", page=3)),
        ),
        Step(
            identity=StepIdentity(step_id="m:s4", source_identity="4", content_hash=content_hash("Four")),
            order=4,
            text=Extracted(value="Four", evidence=Evidence(node_id="4", quote="Four", page=4)),
        ),
        Step(
            identity=StepIdentity(step_id="m:s5", source_identity="5", content_hash=content_hash("Five")),
            order=5,
            text=Extracted(value="Five", evidence=Evidence(node_id="5", quote="Five", page=5)),
        ),
    ]
    tips = [
        await add_tip(
            store, None, step_id=step.identity.step_id, text="tip", author_employee_id="e1", source_revision="A"
        )
        for step in previous
    ]
    current = [
        previous[0].model_copy(
            update={
                "identity": StepIdentity(
                    step_id="m:renumbered", source_identity="3", content_hash=content_hash("Three")
                ),
                "order": 1,
            }
        ),
        previous[1].model_copy(
            update={
                "identity": StepIdentity(
                    step_id="m:moved", source_identity="changed", content_hash=content_hash("Four")
                ),
                "order": 2,
            }
        ),
    ]
    report = await relink_tips(store, None, manual_id="m", previous_steps=previous, current_steps=current)
    assert {item.method for item in report.relinked} == {"source_identity", "content_hash"}
    assert [item.tip_id for item in report.orphaned] == [tips[2].tip_id]

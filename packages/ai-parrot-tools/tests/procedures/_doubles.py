"""Self-contained, data-driven doubles for procedures tests (FEAT-601)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from parrot.knowledge.common.provenance import Evidence, Extracted
from parrot.knowledge.manuals.catalog import SearchHit
from parrot.knowledge.manuals.models import (
    EquipmentRef,
    Hazard,
    ManualCard,
    MediaLink,
    MediaRef,
    Procedure,
    Step,
    StepIdentity,
    content_hash,
)
from parrot_tools.procedures.retrieval import RequestContext

TENANT = "t1"


def make_context(
    *,
    roles: tuple[str, ...] = ("technician",),
    tenant_id: str = TENANT,
    authenticated: bool = True,
    user_id: str = "u1",
    employee_id: Optional[str] = "e1",
    **extra: Any,
) -> RequestContext:
    """Build a trusted technician request context for the supplied tenant."""
    return RequestContext(
        authenticated=authenticated,
        tenant_id=tenant_id,
        user_id=user_id,
        employee_id=employee_id,
        roles=frozenset(roles),
        **extra,
    )


@dataclass
class FakePattern:
    """A traversal pattern exposing only the query template retrieval reads."""

    query_template: str


@dataclass
class FakeOntology:
    """A merged ontology-shaped traversal-pattern mapping."""

    traversal_patterns: dict[str, FakePattern] = field(default_factory=dict)


@dataclass
class FakeGraphStore:
    """A scripted graph store that records traversal inputs."""

    rows_by_aql: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    calls: list[tuple[str, dict[str, Any]]] = field(default_factory=list)

    async def execute_traversal(
        self,
        ctx: Any,
        aql: str,
        bind_vars: Optional[dict[str, Any]] = None,
        collection_binds: Optional[dict[str, str]] = None,
    ) -> list[dict[str, Any]]:
        """Record and return rows configured for ``aql``."""
        self.calls.append((aql, dict(bind_vars or {})))
        return list(self.rows_by_aql.get(aql, []))


class FakeCatalog:
    """A tenant-bound in-memory catalog with deterministic title search."""

    def __init__(
        self,
        *,
        tenant_id: str = TENANT,
        cards: Optional[list[ManualCard]] = None,
        equipment: Optional[list[EquipmentRef]] = None,
        fail_audit: bool = False,
    ) -> None:
        self.tenant_id = tenant_id
        self.cards = {card.manual_id: card for card in (cards or [])}
        self.equipment = list(equipment or [reference for card in self.cards.values() for reference in card.equipment])
        self.fail_audit = fail_audit
        self.answers: list[Any] = []

    async def get(self, manual_id: str) -> ManualCard | None:
        """Return the configured card by manual id."""
        return self.cards.get(manual_id)

    async def list_cards(self, **_: Any) -> list[ManualCard]:
        """Return configured cards in insertion order."""
        return list(self.cards.values())

    async def search(self, query: str, top_k: int = 8) -> list[SearchHit]:
        """Return cards whose equipment or procedure titles occur in ``query``."""
        needle = query.casefold()
        hits: list[SearchHit] = []
        for card in self.cards.values():
            terms = [
                card.manual_id,
                *(item.model for item in card.equipment),
                *(p.title.value for p in card.procedures),
            ]
            rank = sum(term.casefold() in needle for term in terms if term)
            if rank:
                hits.append(SearchHit(card=card, rank=float(rank), matched="procedure"))
        return sorted(hits, key=lambda hit: (-hit.rank, hit.card.manual_id))[:top_k]

    async def resolve_equipment(self, query: str, *, limit: int = 5) -> list[EquipmentRef]:
        """Return equipment whose model or alias occurs in ``query``."""
        needle = query.casefold()
        return [
            item
            for item in self.equipment
            if item.model.casefold() in needle or any(alias.casefold() in needle for alias in item.aliases)
        ][:limit]

    async def record_answer(self, record: Any) -> None:
        """Record an answer unless the double was configured to fail."""
        if self.fail_audit:
            raise RuntimeError("audit store unavailable")
        self.answers.append(record)


class FakePageIndex:
    """A scripted PageIndex search collaborator."""

    def __init__(self, sections: Optional[list[dict[str, Any]]] = None) -> None:
        self.sections = list(sections or [])
        self.calls: list[dict[str, Any]] = []

    async def search(self, tree_name: str, query: str, top_k: int = 10, **kwargs: Any) -> list[dict[str, Any]]:
        """Record the LLM-free search options and return scripted sections."""
        self.calls.append({"tree_name": tree_name, "query": query, "top_k": top_k, **kwargs})
        return list(self.sections)


def make_step(*, manual_id: str = "m1", procedure_slug: str = "assemble", order: int = 1) -> Step:
    """Build one valid evidenced assembly step with a primary figure and hazard."""
    text = f"Install component at assembly step {order}."
    evidence = Evidence(node_id=f"node-{order}", quote=text, page=order)
    return Step(
        identity=StepIdentity(step_id=f"{manual_id}:{procedure_slug}:{order}", content_hash=content_hash(text)),
        order=order,
        text=Extracted[str](value=text, evidence=evidence, confidence=1.0),
        figure_refs=["Fig. 1"],
        hazards=[
            Hazard(
                hazard_id=f"hazard-{order}",
                severity="warning",
                text=Extracted[str](value="Wear gloves", evidence=evidence, confidence=1.0),
            )
        ],
        media=[MediaLink(media_id="figure-1", role="primary", confidence=1.0)],
    )


def make_card(*, manual_id: str = "m1", model: str = "Model X", procedure_id: str = "assemble-x") -> ManualCard:
    """Build a valid manual card with one five-step assembly procedure."""
    steps = [make_step(manual_id=manual_id, order=index) for index in range(1, 6)]
    evidence = Evidence(node_id="node-title", quote="Assemble Model X", page=1)
    return ManualCard(
        manual_id=manual_id,
        revision="A",
        equipment=[EquipmentRef(equipment_id="eq-x", model=model)],
        procedures=[
            Procedure(
                procedure_id=procedure_id,
                slug="assemble",
                kind="assembly",
                title=Extracted[str](value="Assemble Model X", evidence=evidence, confidence=1.0),
                steps=steps,
            )
        ],
        figures=[MediaRef(media_id="figure-1", kind="figure", storage_key="figures/m1.png", page=1, label="Fig. 1")],
    )

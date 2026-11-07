"""Publish a tenant's reviewed concept catalog into the vocabulary store (FEAT-824)."""

from __future__ import annotations

import logging
import re
from typing import Any, Sequence

from parrot.knowledge.ontology.concept_catalog.models import ConceptRow, IsaEdgeRow
from parrot.knowledge.ontology.vocabulary.closure import PARROT_NS, SKOS
from parrot.knowledge.ontology.vocabulary.contracts import (
    OntologyContent,
    OntologyPublisher,
    ParsedConcept,
    ParsedLabel,
    ParsedRelation,
    ParsedStatement,
    PublishResult,
)
from parrot.knowledge.ontology.vocabulary.settings import resolve_ontology_settings

_TENANT_ID = re.compile(r"^[A-Za-z0-9_.-]+$")
FRAMEWORK_NS = "urn:parrot:framework:"


def tenant_ontology_id(tenant_id: str) -> str:
    """Return the vocabulary ontology id for a validated tenant id.

    Args:
        tenant_id: Tenant identifier composed of ASCII letters, digits, dots, underscores, or hyphens.

    Returns:
        The tenant-scoped ontology identifier.

    Raises:
        ValueError: If ``tenant_id`` contains unsupported characters.
    """
    if _TENANT_ID.fullmatch(tenant_id) is None:
        raise ValueError(f"Invalid tenant id {tenant_id!r}")
    return f"tenant.{tenant_id}"


def tenant_base_iri(tenant_id: str) -> str:
    """Return the base IRI for a validated tenant id.

    Args:
        tenant_id: Tenant identifier to encode in the IRI.

    Returns:
        The tenant vocabulary base IRI.
    """
    tenant_ontology_id(tenant_id)
    return f"urn:parrot:tenant:{tenant_id}:"


def content_from_catalog(
    tenant_id: str,
    concepts: Sequence[ConceptRow],
    edges: Sequence[IsaEdgeRow],
    *,
    default_lang: str,
) -> OntologyContent:
    """Project approved tenant catalog rows into vocabulary content.

    Args:
        tenant_id: Tenant whose catalog is being projected.
        concepts: Catalog concept rows, of which approved rows for the tenant are projected.
        edges: Catalog is-a rows, of which approved rows for projected children are projected.
        default_lang: Language tag assigned to preferred and alternate labels.

    Returns:
        Deterministically ordered vocabulary content for the tenant.
    """
    base_iri = tenant_base_iri(tenant_id)
    approved_concepts = sorted(
        (concept for concept in concepts if concept.tenant_id == tenant_id and concept.state == "approved"),
        key=lambda concept: concept.slug,
    )
    iri_by_id = {str(concept.id): f"{base_iri}{concept.slug}" for concept in approved_concepts}

    parsed_concepts = [
        ParsedConcept(
            iri=iri_by_id[str(concept.id)],
            kind="skos_concept",
            pref_label=concept.label,
            definition=concept.description,
        )
        for concept in approved_concepts
    ]
    labels = [
        ParsedLabel(iri=iri_by_id[str(concept.id)], lang=default_lang, kind="pref", text=concept.label)
        for concept in approved_concepts
    ]
    labels.extend(
        ParsedLabel(iri=iri_by_id[str(concept.id)], lang=default_lang, kind="alt", text=synonym)
        for concept in approved_concepts
        for synonym in concept.synonyms
    )
    statements = [
        ParsedStatement(
            subject_iri=iri_by_id[str(concept.id)],
            predicate=f"{PARROT_NS}domain",
            object={"value": concept.domain},
        )
        for concept in approved_concepts
        if concept.domain is not None
    ]

    relations: list[ParsedRelation] = []
    for edge in edges:
        if edge.tenant_id != tenant_id or edge.state != "approved":
            continue
        child_iri = iri_by_id.get(str(edge.child_id))
        if child_iri is None:
            continue
        if edge.parent_tier == "tenant":
            parent_iri = iri_by_id.get(edge.parent_ref)
            if parent_iri is None:
                continue
        else:
            parent_iri = f"{FRAMEWORK_NS}{edge.parent_ref}"
        relations.append(ParsedRelation(subject_iri=child_iri, predicate=f"{SKOS}broader", object_iri=parent_iri))

    return OntologyContent(
        base_iri=base_iri,
        concepts=sorted(parsed_concepts, key=lambda concept: concept.iri),
        labels=sorted(labels, key=lambda label: (label.iri, label.kind, label.lang, label.text)),
        relations=sorted(relations, key=lambda relation: (relation.subject_iri, relation.predicate, relation.object_iri)),
        statements=sorted(statements, key=lambda statement: (statement.subject_iri, statement.predicate)),
    )


class CatalogVocabularyPublisher:
    """Publishes a tenant's reviewed concept catalog as the ontology 'tenant.<tenant_id>'."""

    def __init__(self, pg_pool: Any, publisher: OntologyPublisher, *, default_lang: str | None = None) -> None:
        """Initialize the bridge with a catalog pool and vocabulary publisher.

        Args:
            pg_pool: asyncpg-compatible pool for read-only catalog queries.
            publisher: Vocabulary publishing backend.
            default_lang: Optional language tag used for catalog labels.
        """
        self._pool, self._publisher = pg_pool, publisher
        self._lang = default_lang or resolve_ontology_settings().default_lang
        self.logger = logging.getLogger("parrot.knowledge.ontology.vocabulary.catalog_bridge")

    async def publish_tenant(self, tenant_id: str) -> PublishResult:
        """Read approved catalog data and publish one tenant vocabulary version.

        Args:
            tenant_id: Tenant whose approved catalog is published.

        Returns:
            The vocabulary publication result.
        """
        from parrot.knowledge.ontology.concept_catalog.service import ConceptCatalogService

        ontology_id = tenant_ontology_id(tenant_id)
        base_iri = tenant_base_iri(tenant_id)
        concepts = await ConceptCatalogService(self._pool).get_live_concepts(tenant_id)
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id, tenant_id, child_id, parent_tier, parent_ref, state, asserted_by, reviewed_by, rationale
                FROM ontology_concept_isa
                WHERE tenant_id = $1 AND state = 'approved'
                """,
                tenant_id,
            )
        edges = [IsaEdgeRow(**dict(row)) for row in rows]
        content = content_from_catalog(tenant_id, concepts, edges, default_lang=self._lang)
        await self._publisher.ensure_ontology(
            ontology_id,
            base_iri=base_iri,
            title=f"Tenant {tenant_id} concepts",
        )
        result = await self._publisher.publish_content(
            ontology_id,
            content,
            carry_forward_missing=True,
            notes="concept catalog",
        )
        self.logger.info("published catalog ontology %s version %d changed=%s", ontology_id, result.version, result.changed)
        return result

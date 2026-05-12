"""Multi-tenant ontology resolution and caching.

Resolves the merged ontology for each tenant using the four-layer
YAML chain (base → domain → client → authority) and caches the result in
memory.

FEAT-159 additions:
- Optional ``concept_pipeline`` parameter for ``ConceptEmbeddingPipeline``
  integration (fire-and-forget after merge, failures are logged at WARNING).
- ``authority/`` directory scanning: ``{ontology_dir}/authority/{tenant}.yaml``
  is appended to the YAML chain after the client layer, before merge.
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import TYPE_CHECKING

from .merger import OntologyMerger
from .schema import MergedOntology, TenantContext

if TYPE_CHECKING:
    from .concept_embedding import ConceptEmbeddingPipeline

logger = logging.getLogger("Parrot.Ontology.Tenant")


class TenantOntologyManager:
    """Resolve and cache merged ontology per tenant.

    Resolution process:
        1. Start with the base ontology (ONTOLOGY_BASE_FILE).
        2. If a domain is specified, layer the domain ontology.
        3. Layer the client-specific ontology on top.
        4. Layer the authority ontology (``authority/{tenant}.yaml``) on top
           of the client layer, if it exists.
        5. Merge all layers via OntologyMerger.
        6. Optionally invoke ``ConceptEmbeddingPipeline.sync()`` (fire-and-
           forget; failures are logged at WARNING and do not block resolve).
        7. Cache the result in memory (invalidated on CRON refresh).

    Args:
        ontology_dir: Base directory for ontology YAML files.
        base_file: Filename of the base ontology.
        domains_dir: Subdirectory for domain ontologies.
        clients_dir: Subdirectory for client ontologies.
        db_template: ArangoDB database name template ({tenant} placeholder).
        pgvector_schema_template: PgVector schema name template.
        concept_pipeline: Optional ``ConceptEmbeddingPipeline`` instance.
            When provided, ``sync()`` is called after merge with the tenant's
            concept list.  Failure is logged at WARNING only — resolve always
            succeeds regardless.
    """

    def __init__(
        self,
        ontology_dir: Path | str | None = None,
        base_file: str | None = None,
        domains_dir: str | None = None,
        clients_dir: str | None = None,
        db_template: str | None = None,
        pgvector_schema_template: str | None = None,
        concept_pipeline: "ConceptEmbeddingPipeline | None" = None,
    ) -> None:
        # Resolve config — prefer explicit args, fall back to conf.py
        try:
            from parrot.conf import (
                ONTOLOGY_DIR,
                ONTOLOGY_BASE_FILE,
                ONTOLOGY_DOMAINS_DIR,
                ONTOLOGY_CLIENTS_DIR,
                ONTOLOGY_DB_TEMPLATE,
                ONTOLOGY_PGVECTOR_SCHEMA_TEMPLATE,
            )
        except (ImportError, AttributeError):
            ONTOLOGY_DIR = Path("ontologies")
            ONTOLOGY_BASE_FILE = "base.ontology.yaml"
            ONTOLOGY_DOMAINS_DIR = "domains"
            ONTOLOGY_CLIENTS_DIR = "clients"
            ONTOLOGY_DB_TEMPLATE = "{tenant}_ontology"
            ONTOLOGY_PGVECTOR_SCHEMA_TEMPLATE = "{tenant}"

        self._ontology_dir = Path(ontology_dir) if ontology_dir else ONTOLOGY_DIR
        self._base_file = base_file or ONTOLOGY_BASE_FILE or "base.ontology.yaml"
        self._domains_dir = domains_dir or ONTOLOGY_DOMAINS_DIR or "domains"
        self._clients_dir = clients_dir or ONTOLOGY_CLIENTS_DIR or "clients"
        self._db_template = db_template or ONTOLOGY_DB_TEMPLATE or "{tenant}_ontology"
        self._pgvector_template = pgvector_schema_template or ONTOLOGY_PGVECTOR_SCHEMA_TEMPLATE or "{tenant}"

        self._merger = OntologyMerger()
        self._cache: dict[str, TenantContext] = {}
        self._concept_pipeline = concept_pipeline

    def resolve(
        self, tenant_id: str, domain: str | None = None
    ) -> TenantContext:
        """Resolve the merged ontology for a tenant.

        Args:
            tenant_id: Unique tenant identifier.
            domain: Optional domain name (e.g. "field_services").

        Returns:
            TenantContext with the merged ontology and DB references.
        """
        if tenant_id in self._cache:
            logger.debug("Cache hit for tenant '%s'", tenant_id)
            return self._cache[tenant_id]

        # Build YAML chain
        chain: list[Path] = []

        # 1. Base ontology
        base_path = self._ontology_dir / self._base_file
        if base_path.exists():
            chain.append(base_path)
        else:
            # Try package defaults
            from .parser import OntologyParser
            defaults_dir = OntologyParser.get_defaults_dir()
            default_base = defaults_dir / self._base_file
            if default_base.exists():
                chain.append(default_base)
            else:
                logger.warning(
                    "Base ontology not found at %s or %s",
                    base_path, default_base,
                )

        # 2. Domain ontology (optional)
        if domain:
            domain_path = (
                self._ontology_dir / self._domains_dir
                / f"{domain}.ontology.yaml"
            )
            if domain_path.exists():
                chain.append(domain_path)
            else:
                logger.debug(
                    "Domain ontology '%s' not found at %s",
                    domain, domain_path,
                )

        # 3. Client ontology (optional)
        client_path = (
            self._ontology_dir / self._clients_dir
            / f"{tenant_id}.ontology.yaml"
        )
        if client_path.exists():
            chain.append(client_path)
        else:
            logger.debug(
                "Client ontology for '%s' not found at %s",
                tenant_id, client_path,
            )

        # 4. Authority ontology (optional — FEAT-159)
        # Inserted AFTER the client layer so it can override client-level
        # concepts and traversal patterns with curated authority data.
        authority_path = self._ontology_dir / "authority" / f"{tenant_id}.yaml"
        if authority_path.exists():
            chain.append(authority_path)
            logger.debug(
                "Authority ontology for '%s' found at %s",
                tenant_id, authority_path,
            )
        else:
            logger.debug(
                "No authority ontology for '%s' at %s",
                tenant_id, authority_path,
            )

        if not chain:
            raise FileNotFoundError(
                f"No ontology YAML files found for tenant '{tenant_id}'. "
                f"Searched: {self._ontology_dir}"
            )

        # Merge
        merged = self._merger.merge(chain)

        # Build context
        ctx = TenantContext(
            tenant_id=tenant_id,
            arango_db=self._db_template.format(tenant=tenant_id),
            pgvector_schema=self._pgvector_template.format(tenant=tenant_id),
            ontology=merged,
        )

        self._cache[tenant_id] = ctx
        logger.info(
            "Resolved ontology for tenant '%s': %d entities, %d relations "
            "(from %d layers)",
            tenant_id,
            len(merged.entities),
            len(merged.relations),
            len(chain),
        )

        # FEAT-159: fire-and-forget concept embedding sync.
        # Pipeline failures must NOT block resolve — log WARNING and continue.
        if self._concept_pipeline is not None:
            self._schedule_pipeline_sync(tenant_id, merged)

        return ctx

    def _schedule_pipeline_sync(
        self,
        tenant_id: str,
        merged: MergedOntology,
    ) -> None:
        """Invoke ConceptEmbeddingPipeline.sync() in a non-blocking manner.

        Detects whether an asyncio event loop is already running:

        - **Loop running** (most common — called from async context): schedules
          the coroutine as a ``asyncio.ensure_future`` task (fire-and-forget).
        - **No loop running** (rare — called synchronously outside async
          context): runs the coroutine to completion via
          ``asyncio.get_event_loop().run_until_complete()``.

        In both cases, any exception is caught and logged at WARNING so it
        never propagates back to ``resolve()``.

        Args:
            tenant_id: Tenant identifier forwarded to the pipeline.
            merged: Merged ontology; concepts are extracted from
                ``merged.entities``.
        """
        # Build a flat list of concept dicts from the merged ontology.
        # The "Concept" key in entities holds the EntityDef schema —
        # concept *instances* are stored in its ``instances`` attribute when
        # available, or we fall back to an empty list.
        concept_entity = merged.entities.get("Concept")
        if concept_entity is not None:
            concepts = list(getattr(concept_entity, "instances", []) or [])
        else:
            concepts = []

        async def _run() -> None:
            try:
                result = await self._concept_pipeline.sync(tenant_id, concepts)
                logger.debug(
                    "ConceptEmbeddingPipeline.sync tenant='%s': %r",
                    tenant_id, result,
                )
            except Exception as exc:
                logger.warning(
                    "Concept embedding pipeline failed for tenant '%s': %s",
                    tenant_id, exc,
                )

        try:
            # asyncio.get_running_loop() raises RuntimeError when no loop is
            # active (synchronous call path); that's the correct branch signal.
            try:
                asyncio.get_running_loop()
                # Inside a running event loop — schedule fire-and-forget.
                asyncio.ensure_future(_run())
            except RuntimeError:
                # No running loop (rare sync context) — run synchronously.
                asyncio.run(_run())
        except Exception as exc:
            logger.warning(
                "Could not schedule concept embedding pipeline for tenant '%s': %s",
                tenant_id, exc,
            )

    def invalidate(self, tenant_id: str | None = None) -> None:
        """Invalidate cached ontology for a tenant or all tenants.

        Args:
            tenant_id: Specific tenant to invalidate. If None, clears all.
        """
        if tenant_id:
            removed = self._cache.pop(tenant_id, None)
            if removed:
                logger.info("Invalidated ontology cache for '%s'", tenant_id)
        else:
            count = len(self._cache)
            self._cache.clear()
            logger.info("Invalidated all ontology caches (%d tenants)", count)

    def list_tenants(self) -> list[str]:
        """Return list of currently cached tenant IDs.

        Returns:
            List of tenant ID strings.
        """
        return list(self._cache.keys())

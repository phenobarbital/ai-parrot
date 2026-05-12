"""Multi-tenant ontology resolution and caching.

Resolves the merged ontology for each tenant using the three-layer
YAML chain (base → domain → client) and caches the result in memory.

FEAT-159 (TASK-1098): Extended to compose PG overlay (approved concept rows
and approved schema overlay rows) on top of the YAML chain via the new
async ``resolve_with_overlay()`` method.  The existing synchronous
``resolve()`` is unchanged for backward compatibility.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .merger import OntologyMerger
from .schema import EntityDef, MergedOntology, OntologyDefinition, TenantContext, TraversalPattern

if TYPE_CHECKING:
    from parrot.knowledge.ontology.concept_catalog.models import ConceptRow
    from parrot.knowledge.ontology.concept_catalog.service import ConceptCatalogService
    from parrot.knowledge.ontology.schema import RelationDef
    from parrot.knowledge.ontology.schema_overlay.models import SchemaOverlayRow
    from parrot.knowledge.ontology.schema_overlay.service import SchemaOverlayService

logger = logging.getLogger("Parrot.Ontology.Tenant")


class TenantOntologyManager:
    """Resolve and cache merged ontology per tenant.

    Resolution process:
        1. Start with the base ontology (ONTOLOGY_BASE_FILE).
        2. If a domain is specified, layer the domain ontology.
        3. Layer the client-specific ontology on top.
        4. Merge all layers via OntologyMerger.
        5. Cache the result in memory (invalidated on CRON refresh).

    Args:
        ontology_dir: Base directory for ontology YAML files.
        base_file: Filename of the base ontology.
        domains_dir: Subdirectory for domain ontologies.
        clients_dir: Subdirectory for client ontologies.
        db_template: ArangoDB database name template ({tenant} placeholder).
        pgvector_schema_template: PgVector schema name template.
    """

    def __init__(
        self,
        ontology_dir: Path | str | None = None,
        base_file: str | None = None,
        domains_dir: str | None = None,
        clients_dir: str | None = None,
        db_template: str | None = None,
        pgvector_schema_template: str | None = None,
        # FEAT-159 (TASK-1098): optional PG overlay services
        concept_catalog_service: "ConceptCatalogService | None" = None,
        schema_overlay_service: "SchemaOverlayService | None" = None,
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

        # FEAT-159: optional PG overlay services
        self._concept_service = concept_catalog_service
        self._schema_service = schema_overlay_service

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
        return ctx

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

    # ── FEAT-159: async overlay composition ───────────────────────────────────

    async def resolve_with_overlay(
        self, tenant_id: str, domain: str | None = None
    ) -> TenantContext:
        """Resolve ontology composing YAML chain + PG overlay (async).

        Extends the standard ``resolve()`` flow by fetching:
        1. Approved concept rows from ``ConceptCatalogService`` (if configured).
        2. Approved schema overlays from ``SchemaOverlayService`` (if configured).

        Both are synthesised into ``OntologyDefinition`` objects and passed to
        ``OntologyMerger.merge_with_overlay()`` on top of the YAML chain.

        Falls back to ``resolve()`` (sync, YAML only) when neither service is
        configured.  When the async path completes, the result is stored in
        ``_cache`` using a separate key prefix (``"overlay:{tenant_id}"``) so
        it does not evict YAML-only cached entries.

        Args:
            tenant_id: Unique tenant identifier.
            domain: Optional domain name.

        Returns:
            ``TenantContext`` with the fully composed ontology.
        """
        cache_key = f"overlay:{tenant_id}"
        if cache_key in self._cache:
            logger.debug("Overlay cache hit for tenant '%s'", tenant_id)
            return self._cache[cache_key]

        if not self._concept_service and not self._schema_service:
            # No PG services — delegate to synchronous YAML-only path
            return self.resolve(tenant_id, domain)

        # Build YAML chain (same logic as resolve())
        yaml_paths = self._build_yaml_chain(tenant_id, domain)

        overlay_defs: list[OntologyDefinition] = []

        if self._concept_service:
            concept_rows = await self._concept_service.get_live_concepts(tenant_id, domain=domain)
            overlay_defs.append(self._build_concept_overlay(concept_rows, tenant_id))

        if self._schema_service:
            # C6 fix: use get_approved() — get_pending() only returns proposed/
            # pending_review rows and would always produce an empty approved list.
            approved_schemas = await self._schema_service.get_approved(tenant_id)
            overlay_defs.append(self._build_schema_overlay(approved_schemas, tenant_id))

        if yaml_paths:
            merged = self._merger.merge_with_overlay(yaml_paths, overlay_defs)
        else:
            merged = self._merger.merge_definitions(overlay_defs) if overlay_defs else self._merger.merge(yaml_paths)

        ctx = TenantContext(
            tenant_id=tenant_id,
            arango_db=self._db_template.format(tenant=tenant_id),
            pgvector_schema=self._pgvector_template.format(tenant=tenant_id),
            ontology=merged,
        )

        self._cache[cache_key] = ctx
        logger.info(
            "Resolved overlay ontology for tenant '%s': %d entities, %d relations "
            "(%d PG overlay defs, from %d YAML layers)",
            tenant_id,
            len(merged.entities),
            len(merged.relations),
            len(overlay_defs),
            len(yaml_paths),
        )
        return ctx

    def _build_yaml_chain(
        self, tenant_id: str, domain: str | None = None
    ) -> list[Path]:
        """Build the ordered YAML path chain for a tenant (no file I/O)."""
        chain: list[Path] = []

        base_path = self._ontology_dir / self._base_file
        if base_path.exists():
            chain.append(base_path)
        else:
            from .parser import OntologyParser
            default_base = OntologyParser.get_defaults_dir() / self._base_file
            if default_base.exists():
                chain.append(default_base)

        if domain:
            domain_path = (
                self._ontology_dir / self._domains_dir
                / f"{domain}.ontology.yaml"
            )
            if domain_path.exists():
                chain.append(domain_path)

        client_path = (
            self._ontology_dir / self._clients_dir
            / f"{tenant_id}.ontology.yaml"
        )
        if client_path.exists():
            chain.append(client_path)

        return chain

    def _build_concept_overlay(
        self, concepts: "list[ConceptRow]", tenant_id: str
    ) -> OntologyDefinition:
        """Synthesise an ``OntologyDefinition`` from approved concept rows.

        Each approved concept row is mapped to a minimal ``EntityDef`` whose
        ``collection`` is ``"concepts"`` (the ArangoDB materialized collection).

        Args:
            concepts: List of approved ``ConceptRow`` objects.
            tenant_id: Owning tenant (used in naming).

        Returns:
            ``OntologyDefinition`` with one entry per concept.
        """
        entities: dict[str, EntityDef] = {}
        for concept in concepts:
            entities[concept.slug] = EntityDef(
                collection="concepts",
                key_field="pg_concept_id",
            )
        return OntologyDefinition(
            name=f"pg_concepts_{tenant_id}",
            entities=entities,
        )

    def _build_schema_overlay(
        self, schema_rows: "list[SchemaOverlayRow]", tenant_id: str
    ) -> OntologyDefinition:
        """Synthesise an ``OntologyDefinition`` from approved schema overlay rows.

        Args:
            schema_rows: List of approved ``SchemaOverlayRow`` objects.
            tenant_id: Owning tenant.

        Returns:
            ``OntologyDefinition`` composing all schema overlay items.
        """
        entities: dict[str, EntityDef] = {}
        patterns: dict[str, TraversalPattern] = {}

        for row in schema_rows:
            if row.overlay_kind == "entity_type":
                try:
                    entities[row.name] = EntityDef(**row.definition)
                except Exception as exc:
                    logger.warning(
                        "Skipping schema overlay entity '%s': %s", row.name, exc
                    )
            elif row.overlay_kind == "traversal_pattern":
                try:
                    patterns[row.name] = TraversalPattern(**row.definition)
                except Exception as exc:
                    logger.warning(
                        "Skipping schema overlay pattern '%s': %s", row.name, exc
                    )
            # relation_type: would need RelationDef; skipped in v1
            # (relations require both endpoints to already exist)

        return OntologyDefinition(
            name=f"pg_schema_{tenant_id}",
            entities=entities,
            traversal_patterns=patterns,
        )

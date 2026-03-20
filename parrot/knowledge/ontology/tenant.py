"""Multi-tenant ontology resolution and caching.

Resolves the merged ontology for each tenant using the three-layer
YAML chain (base → domain → client) and caches the result in memory.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from .merger import OntologyMerger
from .schema import MergedOntology, TenantContext

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

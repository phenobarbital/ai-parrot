"""CRON-triggered refresh pipeline for ontology graph delta sync.

Keeps the ontology graph in sync with source data via:
    1. EXTRACT: Pull fresh data from configured sources.
    2. DIFF: Compare new data vs existing graph nodes.
    3. APPLY: Upsert changed nodes, soft-delete removed ones.
    4. REDISCOVER: Re-run relation discovery for changed nodes.
    5. SYNC: Update PgVector embeddings for changed vectorizable fields.
    6. INVALIDATE: Bust Redis cache for the affected tenant.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field

from .cache import OntologyCache
from .discovery import DiscoveryStats, RelationDiscovery
from .graph_store import OntologyGraphStore, UpsertResult
from .tenant import TenantOntologyManager

logger = logging.getLogger("Parrot.Ontology.Refresh")


class DiffResult(BaseModel):
    """Result of computing delta between new and existing data.

    Args:
        to_add: Records present in new data but not existing.
        to_update: Records present in both but with changed values.
        to_remove: Records present in existing but not in new data.
    """

    to_add: list[dict[str, Any]] = Field(default_factory=list)
    to_update: list[dict[str, Any]] = Field(default_factory=list)
    to_remove: list[dict[str, Any]] = Field(default_factory=list)


class RefreshReport(BaseModel):
    """Report from a full refresh pipeline run.

    Args:
        tenant: Tenant identifier.
        started_at: When the refresh started.
        completed_at: When the refresh completed.
        entity_results: Upsert results per entity name.
        discovery_results: Discovery stats per relation name.
        errors: Error messages encountered.
    """

    tenant: str
    started_at: datetime
    completed_at: datetime | None = None
    entity_results: dict[str, UpsertResult] = Field(default_factory=dict)
    discovery_results: dict[str, DiscoveryStats] = Field(default_factory=dict)
    errors: list[str] = Field(default_factory=list)


class OntologyRefreshPipeline:
    """CRON-triggered pipeline that keeps the ontology graph in sync.

    Runs per-tenant and performs delta sync: only changed data is processed.

    Args:
        tenant_manager: TenantOntologyManager instance.
        graph_store: OntologyGraphStore instance.
        discovery: RelationDiscovery instance.
        datasource_factory: DataSourceFactory instance.
        cache: OntologyCache instance.
        vector_store: Optional PgVector store for embedding sync.
        source_configs: Optional dict mapping source names to config dicts.
    """

    def __init__(
        self,
        tenant_manager: TenantOntologyManager,
        graph_store: OntologyGraphStore,
        discovery: RelationDiscovery,
        datasource_factory: Any,
        cache: OntologyCache,
        vector_store: Any = None,
        source_configs: dict[str, dict[str, Any]] | None = None,
    ) -> None:
        self.tenant_manager = tenant_manager
        self.graph_store = graph_store
        self.discovery = discovery
        self.datasource_factory = datasource_factory
        self.cache = cache
        self.vector_store = vector_store
        self.source_configs = source_configs or {}

    async def run(self, tenant_id: str, domain: str | None = None) -> RefreshReport:
        """Execute the full refresh pipeline for a tenant.

        Args:
            tenant_id: Tenant identifier.
            domain: Optional domain for ontology resolution.

        Returns:
            RefreshReport with counts and timing.
        """
        report = RefreshReport(
            tenant=tenant_id,
            started_at=datetime.now(timezone.utc),
        )

        try:
            ctx = self.tenant_manager.resolve(tenant_id, domain=domain)
        except Exception as e:
            report.errors.append(f"Failed to resolve tenant: {e}")
            report.completed_at = datetime.now(timezone.utc)
            return report

        for entity_name, entity_def in ctx.ontology.entities.items():
            if not entity_def.source:
                continue  # Skip entities without a data source

            try:
                await self._refresh_entity(
                    ctx, entity_name, entity_def, report,
                )
            except Exception as e:
                error_msg = f"Entity '{entity_name}' refresh failed: {e}"
                logger.error(error_msg)
                report.errors.append(error_msg)

        # Invalidate cache
        try:
            await self.cache.invalidate_tenant(tenant_id)
            self.tenant_manager.invalidate(tenant_id)
        except Exception as e:
            report.errors.append(f"Cache invalidation failed: {e}")

        report.completed_at = datetime.now(timezone.utc)
        duration = (report.completed_at - report.started_at).total_seconds()
        logger.info(
            "Refresh complete for tenant '%s' in %.1fs: %d entities, %d errors",
            tenant_id, duration,
            len(report.entity_results), len(report.errors),
        )
        return report

    async def _refresh_entity(
        self,
        ctx: Any,
        entity_name: str,
        entity_def: Any,
        report: RefreshReport,
    ) -> None:
        """Refresh a single entity: extract, diff, apply, rediscover.

        Args:
            ctx: TenantContext.
            entity_name: Entity name from the ontology.
            entity_def: EntityDef from the ontology.
            report: RefreshReport to update.
        """
        # 1. EXTRACT
        source_config = self.source_configs.get(entity_def.source, {})
        source = self.datasource_factory.get(
            entity_def.source, source_config,
        )
        property_names = list(entity_def.get_property_names())
        extraction = await source.extract(fields=property_names)

        if extraction.errors:
            for err in extraction.errors:
                report.errors.append(f"{entity_name}: {err}")

        new_data = [record.data for record in extraction.records]
        logger.info(
            "Extracted %d records for entity '%s' from source '%s'",
            len(new_data), entity_name, entity_def.source,
        )

        # 2. DIFF
        existing = await self.graph_store.get_all_nodes(
            ctx, entity_def.collection,
        )
        diff = self._compute_diff(
            new_data, existing, key_field=entity_def.key_field,
        )

        # 3. APPLY
        if diff.to_add or diff.to_update:
            result = await self.graph_store.upsert_nodes(
                ctx, entity_def.collection,
                diff.to_add + diff.to_update,
                key_field=entity_def.key_field,
            )
            report.entity_results[entity_name] = result

        if diff.to_remove:
            keys_to_remove = [
                d.get(entity_def.key_field, d.get("_key", ""))
                for d in diff.to_remove
            ]
            await self.graph_store.soft_delete_nodes(
                ctx, entity_def.collection, keys_to_remove,
            )

        # 4. REDISCOVER EDGES (only for changed nodes)
        changed_nodes = diff.to_add + diff.to_update
        if changed_nodes:
            for rel_name, rel_def in ctx.ontology.relations.items():
                if rel_def.from_entity == entity_name:
                    target_entity = ctx.ontology.entities.get(rel_def.to_entity)
                    if not target_entity:
                        continue
                    target_data = await self.graph_store.get_all_nodes(
                        ctx, target_entity.collection,
                    )
                    discovery_result = await self.discovery.discover(
                        ctx, rel_def, changed_nodes, target_data,
                    )
                    await self.graph_store.create_edges(
                        ctx, rel_def.edge_collection,
                        discovery_result.confirmed,
                    )
                    report.discovery_results[rel_name] = discovery_result.stats

        # 5. SYNC PGVECTOR (only vectorizable fields that changed)
        vec_fields = entity_def.vectorize
        if vec_fields and changed_nodes and self.vector_store:
            await self._sync_vectors(
                ctx, entity_def, changed_nodes, vec_fields,
            )

    @staticmethod
    def _compute_diff(
        new_data: list[dict[str, Any]],
        existing: list[dict[str, Any]],
        key_field: str,
    ) -> DiffResult:
        """Compute delta between new data and existing graph nodes.

        Uses key_field as the identifier for matching. A node is "changed"
        if any of its field values differ. Complexity: O(n + m).

        Args:
            new_data: Fresh records from the data source.
            existing: Current nodes in the graph.
            key_field: Field used as the unique identifier.

        Returns:
            DiffResult with to_add, to_update, to_remove lists.
        """
        existing_map = {
            d.get(key_field, d.get("_key", "")): d for d in existing
        }
        new_map = {
            d.get(key_field, ""): d for d in new_data if d.get(key_field)
        }

        to_add = [d for k, d in new_map.items() if k not in existing_map]
        to_remove = [d for k, d in existing_map.items() if k not in new_map]

        to_update = []
        for k, new_d in new_map.items():
            if k in existing_map:
                old_d = existing_map[k]
                # Compare only the data fields (ignore ArangoDB internal fields)
                changed = any(
                    new_d.get(field) != old_d.get(field)
                    for field in new_d
                    if not field.startswith("_")
                )
                if changed:
                    to_update.append(new_d)

        return DiffResult(
            to_add=to_add,
            to_update=to_update,
            to_remove=to_remove,
        )

    async def _sync_vectors(
        self,
        ctx: Any,
        entity_def: Any,
        changed_nodes: list[dict[str, Any]],
        vec_fields: list[str],
    ) -> None:
        """Sync PgVector embeddings for changed vectorizable fields.

        Args:
            ctx: TenantContext.
            entity_def: EntityDef with vectorize fields.
            changed_nodes: Nodes that were added or updated.
            vec_fields: Fields to embed.
        """
        try:
            for node in changed_nodes:
                texts = [
                    str(node.get(f, ""))
                    for f in vec_fields
                    if node.get(f)
                ]
                if texts:
                    combined = " ".join(texts)
                    await self.vector_store.upsert(
                        text=combined,
                        metadata={
                            "entity": entity_def.collection,
                            "key": node.get(entity_def.key_field, ""),
                        },
                        schema=ctx.pgvector_schema,
                    )
        except Exception as e:
            logger.warning("Vector sync failed: %s", e)

"""``sync_boe`` — thin entrypoint that runs the BOE delta sync for a tenant.

Constructs the ``OntologyRefreshPipeline`` collaborators and calls
``run(tenant_id, domain="legal")``. Deliberately free of any scheduler
import — the deploying agent decides whether to wire this to
``@schedule`` (ai-parrot-server) or an external cron; see ``sync_boe``'s
docstring for the wiring recipe.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from parrot.knowledge.ontology.cache import OntologyCache
from parrot.knowledge.ontology.discovery import DiscoveryStats, RelationDiscovery
from parrot.knowledge.ontology.graph_store import OntologyGraphStore
from parrot.knowledge.ontology.refresh import OntologyRefreshPipeline, RefreshReport
from parrot.knowledge.ontology.schema import TenantContext
from parrot.knowledge.ontology.tenant import TenantOntologyManager
from parrot_loaders.extractors.factory import DataSourceFactory


async def sync_boe(tenant_id: str, since: date | None = None) -> RefreshReport:
    """Run the BOE delta sync for one tenant.

    Constructs a standalone ``OntologyRefreshPipeline`` (tenant manager,
    graph store, relation discovery, the shared ``DataSourceFactory``, and
    an ontology cache — no vector store, since v1 does no embedding) and
    runs it against the ``"legal"`` domain. After the pipeline's node sync
    completes, also bridges the ``modifica``/``deroga`` provenance edges
    parsed by ``BOEDataSource`` directly into
    ``OntologyGraphStore.create_edges`` — see
    ``_sync_provenance_edges``'s docstring for why the generic pipeline
    cannot create them on its own.

    Deployment note: this function has no scheduler dependency (this
    module never imports the ``parrot.scheduler`` package — importing
    the scheduler here would make the legal toolkit depend on the
    ai-parrot-server satellite). It is therefore equally callable from
    an external cron, or wired to ai-parrot-server's autonomous
    scheduler by the *deploying* agent using the ``schedule`` decorator
    and ``ScheduleType`` enum that ``parrot.scheduler`` exposes, e.g.
    (import added by the *consuming* module, not here)::

        @schedule(ScheduleType.DAILY, hour=4, minute=0)
        async def nightly_boe(self):
            await sync_boe(tenant_id="legal_civil")

    Args:
        tenant_id: Tenant identifier to resolve via
            ``TenantOntologyManager.resolve(tenant_id, domain="legal")``.
        since: Optional lower bound for incremental sync. Threaded into
            the ``BOEDataSource`` config as ``source_configs={"boe":
            {"since": since}}``.

    Returns:
        The RefreshReport produced by
        ``OntologyRefreshPipeline.run(tenant_id, domain="legal")``.
    """
    tenant_manager = TenantOntologyManager()
    graph_store = OntologyGraphStore()
    discovery = RelationDiscovery()
    cache = OntologyCache()
    datasource_factory = DataSourceFactory()

    source_configs = {
        "boe": {"since": since.isoformat() if since else None},
    }

    pipeline = OntologyRefreshPipeline(
        tenant_manager=tenant_manager,
        graph_store=graph_store,
        discovery=discovery,
        datasource_factory=datasource_factory,
        cache=cache,
        vector_store=None,
        source_configs=source_configs,
    )
    report = await pipeline.run(tenant_id, domain="legal")

    # Bridge the `modifica`/`deroga` provenance edges parsed alongside the
    # norma/articulo nodes. OntologyRefreshPipeline's generic REDISCOVER
    # stage only creates edges via RelationDiscovery's field-match
    # strategy, and modifica/deroga deliberately declare zero discovery
    # rules in legal.ontology.yaml (they are facts read directly from
    # BOE's XML, not field-matchable) — so those edges are otherwise never
    # written. Never raises: failures degrade into `report.errors`, the
    # same pattern OntologyRefreshPipeline._refresh_entity uses.
    try:
        ctx = tenant_manager.resolve(tenant_id, domain="legal")
        boe_source = datasource_factory.get("boe", source_configs["boe"])
        relation_stats, relation_errors = await _sync_provenance_edges(
            ctx, graph_store, boe_source,
        )
        report.discovery_results.update(relation_stats)
        report.errors.extend(relation_errors)
    except Exception as e:  # noqa: BLE001 — degrade into report.errors, don't raise
        report.errors.append(f"Provenance edge sync failed: {e}")

    return report


async def _sync_provenance_edges(
    ctx: TenantContext,
    graph_store: OntologyGraphStore,
    boe_source: Any,
) -> tuple[dict[str, DiscoveryStats], list[str]]:
    """Create `modifica`/`deroga` edges from the datasource's parsed relations.

    Args:
        ctx: Resolved TenantContext for the "legal" domain, used to map
            each relation's declared ``from``/``to`` entity to its
            collection name (building the ``_from``/``_to`` document IDs
            ``OntologyGraphStore.create_edges`` requires) and its
            ``edge_collection``.
        graph_store: The OntologyGraphStore to write edges to.
        boe_source: A ``BOEDataSource`` instance (same one used for node
            extraction, so its per-instance parse cache is reused —
            avoids re-fetching each configured norm).

    Returns:
        A ``(stats, errors)`` tuple: per-relation-type DiscoveryStats
        (``total_source`` = relation records seen, ``edges_created`` =
        edges written), keyed by relation name (e.g. "modifica",
        "deroga") — merged into ``RefreshReport.discovery_results`` by
        the caller; and any ``boe_source.extract_relations()`` fetch/parse
        errors, so a partial failure (e.g. the modifying norm's own fetch
        fails) is surfaced in ``RefreshReport.errors`` instead of
        silently producing fewer edges than expected.
    """
    relations, errors = await boe_source.extract_relations()

    edges_by_type: dict[str, list[dict[str, Any]]] = {}
    for relation in relations:
        rel_type = relation.get("type")
        rel_def = ctx.ontology.relations.get(rel_type)
        if rel_def is None:
            continue
        from_entity = ctx.ontology.entities.get(rel_def.from_entity)
        to_entity = ctx.ontology.entities.get(rel_def.to_entity)
        if from_entity is None or to_entity is None:
            continue
        edges_by_type.setdefault(rel_type, []).append(
            {
                "_from": f"{from_entity.collection}/{relation['from']}",
                "_to": f"{to_entity.collection}/{relation['to']}",
            }
        )

    stats: dict[str, DiscoveryStats] = {}
    for rel_type, edges in edges_by_type.items():
        rel_def = ctx.ontology.relations[rel_type]
        created = await graph_store.create_edges(ctx, rel_def.edge_collection, edges)
        stats[rel_type] = DiscoveryStats(
            total_source=len(edges),
            edges_created=created,
        )
    return stats, errors

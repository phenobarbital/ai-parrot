"""``sync_boe`` — thin entrypoint that runs the BOE delta sync for a tenant.

Constructs the ``OntologyRefreshPipeline`` collaborators and calls
``run(tenant_id, domain="legal")``. Deliberately free of any scheduler
import — the deploying agent decides whether to wire this to
``@schedule`` (ai-parrot-server) or an external cron; see ``sync_boe``'s
docstring for the wiring recipe.
"""
from __future__ import annotations

from datetime import date

from parrot.knowledge.ontology.cache import OntologyCache
from parrot.knowledge.ontology.discovery import RelationDiscovery
from parrot.knowledge.ontology.graph_store import OntologyGraphStore
from parrot.knowledge.ontology.refresh import OntologyRefreshPipeline, RefreshReport
from parrot.knowledge.ontology.tenant import TenantOntologyManager
from parrot_loaders.extractors.factory import DataSourceFactory


async def sync_boe(tenant_id: str, since: date | None = None) -> RefreshReport:
    """Run the BOE delta sync for one tenant.

    Constructs a standalone ``OntologyRefreshPipeline`` (tenant manager,
    graph store, relation discovery, the shared ``DataSourceFactory``, and
    an ontology cache — no vector store, since v1 does no embedding) and
    runs it against the ``"legal"`` domain.

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
    return await pipeline.run(tenant_id, domain="legal")

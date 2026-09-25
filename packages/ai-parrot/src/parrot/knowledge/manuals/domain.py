"""Procedures ontology domain wiring (FEAT-601 M3).

The packaged ``procedures.ontology.yaml`` only resolves through a
``TenantOntologyManager`` built on the package defaults dir (F011). Never
share that manager with another domain: its resolve cache is keyed by
tenant id only.
"""

from __future__ import annotations

import logging
from pathlib import Path

from parrot.knowledge.ontology.parser import OntologyParser
from parrot.knowledge.ontology.schema import TenantContext
from parrot.knowledge.ontology.tenant import TenantOntologyManager

logger = logging.getLogger(__name__)

PROCEDURES_DOMAIN = "procedures"
OWNED_VERTEX_COLLECTIONS: tuple[str, ...] = (
    "equipment",
    "manual",
    "procedure",
    "step",
    "part",
    "tool",
    "hazard",
    "media",
)
OWNED_EDGE_COLLECTIONS: tuple[str, ...] = (
    "documents",
    "assembles",
    "has_step",
    "precedes",
    "requires_part",
    "requires_tool",
    "warns",
    "illustrated_by",
    "overview_media",
    "depicts",
    "shares_module",
    "supersedes",
)
TECHNICIAN_COLLECTIONS: tuple[str, ...] = ("tech_tip", "tech_tip_on", "tech_tip_by")  # never reconciled by the loader
TECHNICIAN_ROLE = "technician"
CURATOR_ROLE = "manual_curator"
REQUIRED_ENTITIES: frozenset[str] = frozenset({"Procedure", "Step", "Media", "Tip"})


class ProceduresDomainNotLoaded(RuntimeError):
    """The resolved tenant ontology does not contain the procedures domain."""


def default_tenant_manager(ontology_dir: str | Path | None = None) -> TenantOntologyManager:
    """Build a procedures-only tenant manager over the packaged defaults (or ``ontology_dir``).

    Args:
        ontology_dir: Override directory holding ``base.ontology.yaml`` and ``domains/``.

    Returns:
        A new, unshared :class:`TenantOntologyManager`.
    """
    return TenantOntologyManager(ontology_dir=Path(ontology_dir) if ontology_dir else OntologyParser.get_defaults_dir())


def resolve_context(manager: TenantOntologyManager, tenant_id: str) -> TenantContext:
    """Resolve the procedures context for ``tenant_id``.

    Args:
        manager: A dedicated procedures :class:`TenantOntologyManager` (see
            :func:`default_tenant_manager`).
        tenant_id: Unique tenant identifier.

    Returns:
        The resolved :class:`TenantContext` for the procedures domain.

    Raises:
        ProceduresDomainNotLoaded: When the merged ontology lacks :data:`REQUIRED_ENTITIES`
            (misconfigured ontology_dir or a manager shared with another domain).
    """
    ctx = manager.resolve(tenant_id, domain=PROCEDURES_DOMAIN)
    missing = REQUIRED_ENTITIES - set(ctx.ontology.entities)
    if missing:
        raise ProceduresDomainNotLoaded(
            f"tenant {tenant_id!r} resolved an ontology without {sorted(missing)}; "
            "configure the procedures ontology_dir and use a dedicated "
            "TenantOntologyManager (it caches by tenant, not domain)."
        )
    logger.debug(
        "Resolved procedures ontology for tenant %r: %d entities, %d relations",
        tenant_id,
        len(ctx.ontology.entities),
        len(ctx.ontology.relations),
    )
    return ctx

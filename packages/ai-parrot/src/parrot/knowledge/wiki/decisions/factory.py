"""Framework-free namespace-aware service factory for the decision plane."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from parrot.knowledge.wiki.decisions.models import ADR_INVALID_ARGUMENT, DecisionError
from parrot.knowledge.wiki.decisions.service import DecisionService
from parrot.knowledge.wiki.operations import _scoped_store, _unknown_namespace_error
from parrot.knowledge.wiki.structural.service import StructuralService

#: Given a tool's ``namespace`` argument, returns the service to query.
ServiceFactory = Callable[[str | None], DecisionService]


def make_decision_service_factory(store: Any, root: Path | None, config: Any) -> ServiceFactory:
    """Build the namespace-aware ``DecisionService`` resolver for one wiki.

    Args:
        store: The (possibly federated) wiki retrieval-plane store.
        root: Local evidence root, or ``None`` when there is no writable checkout.
        config: Effective project configuration (``config.decisions`` is used).

    Returns:
        A callable mapping a ``namespace`` argument to a ``DecisionService``.
    """
    decisions_config = config.decisions
    local_structural = StructuralService(store, root, config) if root is not None else None

    def service_factory(namespace: str | None) -> DecisionService:
        if namespace == "all":
            raise DecisionError(ADR_INVALID_ARGUMENT, "namespace='all' is not supported for decisions")
        # `namespace` defaults to "local" (never passed through as `None`):
        # `_scoped_store(store, None)` no-ops and returns `store` UNCHANGED,
        # which — when `store` is a `FederatedWikiStore` (the MCP server
        # wraps it in one before this factory ever runs) — is the whole
        # broadcasting federation, not the local plane. Spec §2 Module 6
        # requires why/lookup to target exactly one namespace per call,
        # `local` by default; only an explicit selector should narrow to a
        # named foreign namespace.
        effective_ns = namespace or "local"
        try:
            scoped = _scoped_store(store, effective_ns)
        except KeyError:
            raise ValueError(_unknown_namespace_error(store, str(namespace))) from None
        if effective_ns == "local":
            return DecisionService(scoped, root, decisions_config, structural=local_structural)
        # A foreign/federated namespace has no local evidence root of its
        # own — freshness answers 'unverified' and generation/sync refuse,
        # per spec §2 Module 6 ("cannot generate or sync local code").
        return DecisionService(scoped, None, decisions_config, structural=None)

    return service_factory

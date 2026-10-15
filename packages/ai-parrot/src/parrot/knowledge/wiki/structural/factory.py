"""Framework-free namespace-aware service factory for the structural plane."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from parrot.knowledge.wiki.federation import FederatedWikiStore
from parrot.knowledge.wiki.operations import _scoped_store, _unknown_namespace_error
from parrot.knowledge.wiki.structural.service import StructuralService

#: Given a tool's ``namespace`` argument, returns the service to query.
ServiceFactory = Callable[[str | None], StructuralService]


def make_structural_service_factory(
    store: Any,
    root: Path,
    config: Any,
    *,
    read_repair: bool = True,
) -> ServiceFactory:
    """Build the namespace-aware ``StructuralService`` resolver for one wiki.

    Args:
        store: The (possibly federated) wiki retrieval-plane store.
        root: Repository root the local plane describes; read-repair only ever
            reads/writes under this root.
        config: Effective project configuration for the local plane.
        read_repair: ``False`` runs every service rootless (no disk hashing,
            read-repair or source excerpts); foreign namespaces are always rootless.

    Returns:
        A callable mapping a ``namespace`` argument to a ``StructuralService``.
        It raises ``ValueError`` with a user-facing message for an unknown namespace.
    """
    # A store scoped to ONE foreign namespace (``--ns <name>``) serves that plane as
    # its "local" one; it must never be read-repaired from this checkout.
    scoped_foreign = isinstance(store, FederatedWikiStore) and getattr(store, "_qualify_local", False)
    local_service = StructuralService(store, root, config, read_repair=read_repair and not scoped_foreign)

    def service_factory(namespace: str | None) -> StructuralService:
        try:
            scoped = _scoped_store(store, namespace)
        except KeyError:
            raise ValueError(_unknown_namespace_error(store, str(namespace))) from None
        if scoped is store:
            return local_service
        # A foreign/federated namespace: read-repair is local-root-only
        # (Module 7's own contract) and is now explicitly off (FEAT-609 M5),
        # so a foreign plane is never written.
        return StructuralService(scoped, root, config, read_repair=False)

    return service_factory

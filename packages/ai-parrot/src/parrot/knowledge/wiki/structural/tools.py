"""Structural plane `AbstractTool` wrappers (FEAT-498 Module 8).

Three read-only tools over one shared :class:`StructuralService`, mirroring
:class:`~parrot.knowledge.wiki.tools.WikiQueryTool`'s shape so they register
with a `StdioMCPServer` alongside the other wiki tools (resolved names
``wiki_symbol_lookup``, ``wiki_code_outline``, ``wiki_blast_radius``).
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from parrot.knowledge.wiki.federation import FederatedWikiStore
from parrot.knowledge.wiki.operations import _scoped_store, _unknown_namespace_error
from parrot.knowledge.wiki.project import WikiProjectConfig
from parrot.knowledge.wiki.store import BaseWikiStore
from parrot.knowledge.wiki.structural.operations import (
    BlastRadiusInput,
    CodeOutlineInput,
    SymbolLookupInput,
    op_blast_radius,
    op_code_outline,
    op_symbol_lookup,
)
from parrot.knowledge.wiki.structural.service import StructuralService
from parrot.knowledge.wiki.symbols import SymbolKind
from parrot.tools.abstract import AbstractTool, ToolResult

#: Shared description of the optional ``namespace`` argument — same
#: wording as ``parrot.knowledge.wiki.tools._NAMESPACE_DESC``, copied
#: rather than imported since that name is private to that module.
_NAMESPACE_DESC = (
    "Federated namespace to read: a namespace name, 'all' to broadcast, "
    "'local' for this repo's own wiki. Omit for the default routing "
    "(broadcast when namespaces are configured)."
)

#: A namespace-aware service resolver: given the tool's ``namespace``
#: argument, returns the ``StructuralService`` to query. Raises
#: ``ValueError`` (pre-rendered, user-facing message) for an unknown
#: namespace — mirrors ``_scoped_store``'s ``KeyError`` contract, just
#: pre-formatted since the factory alone doesn't have the base store
#: handy at the tool's call site.
ServiceFactory = Callable[[str | None], StructuralService]


class WikiSymbolLookupTool(AbstractTool):
    """Find a symbol (function/class/method) by name or qualname across the
    codebase. Returns ranked hits with file/line locations. Use before
    grep when you know the symbol's name but not where it lives."""

    name = "wiki_symbol_lookup"
    description = (
        "Find a symbol (function/class/method) by name or qualname across "
        "the codebase. Returns ranked hits with file/line locations. Use "
        "before grep when you know the symbol's name but not where it "
        "lives."
    )
    args_schema = SymbolLookupInput

    def __init__(self, service_factory: ServiceFactory):
        super().__init__(name=self.name, description=self.description)
        self._service_factory = service_factory

    async def _execute(
        self,
        query: str,
        kind: SymbolKind | None = None,
        language: str | None = None,
        path_prefix: str | None = None,
        limit: int = 20,
        namespace: str | None = None,
    ) -> ToolResult:
        result = await op_symbol_lookup(
            None,
            SymbolLookupInput(
                query=query, kind=kind, language=language, path_prefix=path_prefix, limit=limit, namespace=namespace
            ),
            service_factory=self._service_factory,
        )
        if result.is_error:
            return ToolResult(success=False, status="error", result=None, error=result.text)
        return ToolResult(result=result.data)


class WikiCodeOutlineTool(AbstractTool):
    """Get the symbol outline of a file — every top-level (and nested,
    depth-bounded) class/function/method, with line ranges. Use before
    reading a whole file to see its shape first."""

    name = "wiki_code_outline"
    description = (
        "Get the symbol outline of a file — every top-level (and nested, "
        "depth-bounded) class/function/method, with line ranges. Use "
        "before reading a whole file to see its shape first."
    )
    args_schema = CodeOutlineInput

    def __init__(self, service_factory: ServiceFactory):
        super().__init__(name=self.name, description=self.description)
        self._service_factory = service_factory

    async def _execute(
        self,
        target: str,
        depth: int = 2,
        include_source: bool = False,
        namespace: str | None = None,
    ) -> ToolResult:
        result = await op_code_outline(
            None,
            CodeOutlineInput(target=target, depth=depth, include_source=include_source, namespace=namespace),
            service_factory=self._service_factory,
        )
        if result.is_error:
            return ToolResult(success=False, status="error", result=None, error=result.text)
        return ToolResult(result=result.data)


class WikiBlastRadiusTool(AbstractTool):
    """Find every symbol that transitively depends on (calls/extends/
    implements) a given symbol — the "blast radius" of changing it. Use
    before editing a widely-used function or class."""

    name = "wiki_blast_radius"
    description = (
        "Find every symbol that transitively depends on (calls/extends/"
        "implements) a given symbol — the 'blast radius' of changing it. "
        "Use before editing a widely-used function or class."
    )
    args_schema = BlastRadiusInput

    def __init__(self, service_factory: ServiceFactory):
        super().__init__(name=self.name, description=self.description)
        self._service_factory = service_factory

    async def _execute(
        self,
        symbol: str,
        relations: list[str] | None = None,
        depth: int = 2,
        include_inferred: bool = True,
        include_tests: bool = True,
        namespace: str | None = None,
    ) -> ToolResult:
        result = await op_blast_radius(
            None,
            BlastRadiusInput(
                symbol=symbol,
                relations=relations,
                depth=depth,
                include_inferred=include_inferred,
                include_tests=include_tests,
                namespace=namespace,
            ),
            service_factory=self._service_factory,
        )
        if result.is_error:
            return ToolResult(success=False, status="error", result=None, error=result.text)
        return ToolResult(result=result.data)


def create_structural_tools(
    store: BaseWikiStore,
    root: Path,
    config: WikiProjectConfig,
    *,
    read_repair: bool = True,
) -> list[AbstractTool]:
    """Create the three structural tools, sharing one local ``StructuralService``.

    Args:
        store: The (possibly federated) wiki retrieval-plane the tools
            resolve ``namespace`` against.
        root: Repository root the local plane describes — read-repair
            only ever reads/writes under this root.
        config: Effective project configuration for the local plane.
        read_repair: ``False`` runs every service rootless (no disk hashing,
            read-repair or source excerpts); foreign namespaces are always rootless.

    Returns:
        ``[WikiSymbolLookupTool, WikiCodeOutlineTool, WikiBlastRadiusTool]``,
        all three sharing one ``service_factory``.
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

    return [
        WikiSymbolLookupTool(service_factory),
        WikiCodeOutlineTool(service_factory),
        WikiBlastRadiusTool(service_factory),
    ]

"""Structural plane tools and toolkit (moved from parrot.knowledge.wiki.structural — FEAT-540 M3)."""

from __future__ import annotations

from collections.abc import Callable
from parrot.knowledge.wiki.federation import FederatedWikiStore  # noqa: F401 -- shim re-export
from parrot.knowledge.wiki.operations import (
    _scoped_store,  # noqa: F401 -- re-exported through the compatibility shim
    _unknown_namespace_error,  # noqa: F401
)
from parrot.knowledge.wiki.project import (
    WikiProjectConfig,
    find_project_root,
    load_effective_config,
    sqlite_policy_from_config,
)
from parrot.knowledge.wiki.store import (
    BaseWikiStore,
    create_wiki_store,
)
from parrot.knowledge.wiki.structural.operations import (
    BlastRadiusInput,
    CodeOutlineInput,
    SymbolLookupInput,
    op_blast_radius,
    op_code_outline,
    op_symbol_lookup,
)
from parrot.knowledge.wiki.structural.factory import make_structural_service_factory
from parrot.knowledge.wiki.structural.service import StructuralService
from parrot.knowledge.wiki.symbols import SymbolKind
from parrot.tools.abstract import (
    AbstractTool,
    ToolResult,
)
from parrot.tools.toolkit import AbstractToolkit
from pathlib import Path
from typing import Any

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
    service_factory = make_structural_service_factory(store, root, config, read_repair=read_repair)

    return [
        WikiSymbolLookupTool(service_factory),
        WikiCodeOutlineTool(service_factory),
        WikiBlastRadiusTool(service_factory),
    ]


class CodeStructuralToolkit(AbstractToolkit):
    """Query the codebase's structural symbol plane: lookup, outline, blast radius.

    Tool prefix: ``"code"`` — methods are exposed as ``code_symbol_lookup``,
    ``code_outline``, ``code_blast_radius``. All three delegate to one
    shared :class:`StructuralService`.

    Attributes:
        tool_prefix: Set to ``"code"`` to namespace all tools.

    Example::

        toolkit = CodeStructuralToolkit(root=Path("/path/to/repo"))
        tools = toolkit.get_tools_sync()  # code_symbol_lookup, code_outline, code_blast_radius
    """

    tool_prefix: str = "code"

    def __init__(
        self,
        root: Path | None = None,
        store: BaseWikiStore | None = None,
        config: WikiProjectConfig | None = None,
        **kwargs: Any,
    ) -> None:
        """Resolve the project root/config/store, then build one shared service.

        Args:
            root: Wiki project root. Defaults to :func:`find_project_root`
                from the current working directory.
            store: Pre-built retrieval plane. When omitted, one is built
                from ``config`` the same way ``wikitoolkit``'s CLI does.
            config: Effective project configuration. Defaults to
                :func:`load_effective_config` for ``root``.
            **kwargs: Forwarded to :class:`AbstractToolkit`.

        Raises:
            ValueError: When ``root`` is omitted and no project root can
                be found from the current working directory.
        """
        super().__init__(**kwargs)
        resolved_root = root or find_project_root()
        if resolved_root is None:
            raise ValueError(
                "CodeStructuralToolkit: no wiki project root found — pass "
                "root= explicitly, or run inside a repo with "
                ".parrot/wiki.json or a .git root."
            )
        self._root = resolved_root
        self._config = config or load_effective_config(resolved_root).config
        self._store = store if store is not None else self._build_store()
        self._service = StructuralService(self._store, self._root, self._config)

    def _build_store(self) -> BaseWikiStore:
        """Build the retrieval-plane store from ``self._config`` (no store given)."""
        storage = self._config.storage_path(self._root)
        if self._config.backend == "arangodb":
            from parrot.knowledge.wiki.project import resolve_arango_params

            return create_wiki_store(
                storage,
                wiki_name=self._config.wiki_name,
                backend="arangodb",
                arango_params=resolve_arango_params(self._config),
                database=self._config.arango_database or "",
                text_analyzer=self._config.arango_text_analyzer,
            )
        storage.mkdir(parents=True, exist_ok=True)
        return create_wiki_store(
            storage,
            wiki_name=self._config.wiki_name,
            backend=self._config.backend,
            sqlite_policy=sqlite_policy_from_config(self._config),
        )

    async def symbol_lookup(
        self,
        query: str,
        kind: str | None = None,
        language: str | None = None,
        path_prefix: str | None = None,
        limit: int = 20,
    ) -> dict[str, Any]:
        """Find a symbol (function/class/method) by name or qualname.

        Args:
            query: Symbol name or qualname to look up.
            kind: Exact symbol kind filter (e.g. "function", "class").
            language: Exact scanner-name filter (e.g. "python").
            path_prefix: rel_path must start with this prefix.
            limit: Maximum results.

        Returns:
            The ``SymbolLookupOutput`` model, as a dict.
        """
        kind_enum = SymbolKind(kind) if kind else None
        output = await self._service.lookup(
            query, kind=kind_enum, language=language, path_prefix=path_prefix, limit=limit
        )
        return output.model_dump(mode="json")

    async def outline(
        self,
        target: str,
        depth: int = 2,
        include_source: bool = False,
    ) -> dict[str, Any]:
        """Get the symbol outline of a file.

        Args:
            target: A file:<rel>, sym:<rel>#<qualname>, or bare relative path.
            depth: Maximum symbol nesting depth included.
            include_source: Include a capped source excerpt (sym: targets only).

        Returns:
            The ``CodeOutlineOutput`` model, as a dict.
        """
        output = await self._service.outline(target, depth=depth, include_source=include_source)
        return output.model_dump(mode="json")

    async def blast_radius(
        self,
        symbol: str,
        relations: list[str] | None = None,
        depth: int = 2,
        include_inferred: bool = True,
        include_tests: bool = True,
    ) -> dict[str, Any]:
        """Find every symbol that transitively depends on a given symbol.

        Args:
            symbol: A sym: id or an exact qualname.
            relations: Edge relations to follow (default: calls, extends, implements).
            depth: Maximum BFS depth.
            include_inferred: Follow provenance='inferred' edges.
            include_tests: Include symbols under a tests/ path.

        Returns:
            The ``BlastRadiusOutput`` model, as a dict.
        """
        output = await self._service.blast_radius(
            symbol,
            relations=relations,
            depth=depth,
            include_inferred=include_inferred,
            include_tests=include_tests,
        )
        return output.model_dump(mode="json")

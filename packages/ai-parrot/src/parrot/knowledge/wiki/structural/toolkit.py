"""``CodeStructuralToolkit`` — agent-facing surface over ``StructuralService``.

Mirrors :class:`~parrot.knowledge.wiki.toolkit.LLMWikiToolkit`'s
construction style: resolve (or accept) a project root, config, and
store, then expose public async methods that ``AbstractToolkit``
auto-converts into tools (FEAT-498 Module 8).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from parrot.knowledge.wiki.project import (
    WikiProjectConfig,
    find_project_root,
    load_effective_config,
)
from parrot.knowledge.wiki.store import BaseWikiStore, create_wiki_store
from parrot.knowledge.wiki.structural.service import StructuralService
from parrot.knowledge.wiki.symbols import SymbolKind
from parrot.tools.toolkit import AbstractToolkit


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
        return create_wiki_store(storage, wiki_name=self._config.wiki_name, backend=self._config.backend)

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

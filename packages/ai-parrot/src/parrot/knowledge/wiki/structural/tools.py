"""Structural plane `AbstractTool` wrappers (FEAT-498 Module 8).

Three read-only tools over one shared :class:`StructuralService`, mirroring
:class:`~parrot.knowledge.wiki.tools.WikiQueryTool`'s shape so they register
with a `StdioMCPServer` alongside the other wiki tools (resolved names
``wiki_symbol_lookup``, ``wiki_code_outline``, ``wiki_blast_radius``).
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from parrot.knowledge.wiki.context import DEFAULT_BUDGET_TOKENS, truncate_to_tokens
from parrot.knowledge.wiki.project import WikiProjectConfig
from parrot.knowledge.wiki.store import BaseWikiStore
from parrot.knowledge.wiki.structural.service import (
    BlastRadiusOutput,
    CodeOutlineOutput,
    StructuralService,
    SymbolHit,
    SymbolLookupOutput,
)
from parrot.knowledge.wiki.symbols import SymbolKind
from parrot.knowledge.wiki.tools import _scoped_store, _unknown_namespace_error
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


class SymbolLookupInput(BaseModel):
    """Arguments for ``wiki_symbol_lookup`` / ``code_symbol_lookup``."""

    query: str = Field(..., description="Symbol name or qualname to look up")
    kind: SymbolKind | None = Field(default=None, description="Exact symbol kind filter")
    language: str | None = Field(default=None, description="Exact scanner-name filter (e.g. 'python')")
    path_prefix: str | None = Field(default=None, description="rel_path must start with this prefix")
    limit: int = Field(default=20, le=100, description="Maximum results")
    namespace: str | None = Field(default=None, description=_NAMESPACE_DESC)


class CodeOutlineInput(BaseModel):
    """Arguments for ``wiki_code_outline`` / ``code_outline``."""

    target: str = Field(
        ..., description="A file:<rel>, sym:<rel>#<qualname>, or bare relative path"
    )
    depth: int = Field(default=2, ge=1, le=4, description="Maximum symbol nesting depth")
    include_source: bool = Field(
        default=False, description="Include a capped source excerpt (sym: targets only)"
    )
    namespace: str | None = Field(default=None, description=_NAMESPACE_DESC)


class BlastRadiusInput(BaseModel):
    """Arguments for ``wiki_blast_radius`` / ``code_blast_radius``."""

    symbol: str = Field(..., description="A sym: id or an exact qualname")
    relations: list[Literal["calls", "extends", "implements", "references", "contains"]] | None = Field(
        default=None,
        description="Edge relations to follow (default: calls, extends, implements)",
    )
    depth: int = Field(default=2, ge=1, le=5, description="Maximum BFS depth")
    include_inferred: bool = Field(
        default=True, description="Follow provenance='inferred' edges (globally-unique-name resolutions)"
    )
    include_tests: bool = Field(default=True, description="Include symbols under a tests/ path")
    namespace: str | None = Field(default=None, description=_NAMESPACE_DESC)


def _hit_line(hit: SymbolHit) -> str:
    """Render one ``SymbolHit`` as a compact single line.

    Format: ``[sym:<rel>#<q>] — <kind> L<start>-<end>: <doc>``.
    """
    doc = hit.doc.strip()
    suffix = f": {doc}" if doc else ""
    stale = " (stale)" if hit.stale else ""
    return f"[{hit.symbol_id}] — {hit.kind.value} L{hit.start_line}-{hit.end_line}{suffix}{stale}"


def _render_text(lines: list[str], model: BaseModel, budget_tokens: int) -> str:
    """Compact stub-line body + a JSON tail of ``model``, capped at ``budget_tokens``."""
    body = "\n".join(lines) if lines else "(no results)"
    tail = json.dumps(model.model_dump(mode="json"))
    text, _truncated = truncate_to_tokens(f"{body}\n\n{tail}", budget_tokens)
    return text


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
        try:
            service = self._service_factory(namespace)
        except ValueError as exc:
            return ToolResult(success=False, status="error", result=None, error=str(exc))
        output: SymbolLookupOutput = await service.lookup(
            query, kind=kind, language=language, path_prefix=path_prefix, limit=limit
        )
        lines = [_hit_line(hit) for hit in output.hits]
        payload = output.model_dump(mode="json")
        payload["text"] = _render_text(lines, output, DEFAULT_BUDGET_TOKENS)
        return ToolResult(result=payload)


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
        try:
            service = self._service_factory(namespace)
        except ValueError as exc:
            return ToolResult(success=False, status="error", result=None, error=str(exc))
        output: CodeOutlineOutput = await service.outline(
            target, depth=depth, include_source=include_source
        )
        lines = [_hit_line(hit) for hit in output.symbols]
        payload = output.model_dump(mode="json")
        payload["text"] = _render_text(lines, output, DEFAULT_BUDGET_TOKENS)
        return ToolResult(result=payload)


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
        try:
            service = self._service_factory(namespace)
        except ValueError as exc:
            return ToolResult(success=False, status="error", result=None, error=str(exc))
        output: BlastRadiusOutput = await service.blast_radius(
            symbol,
            relations=relations,
            depth=depth,
            include_inferred=include_inferred,
            include_tests=include_tests,
        )
        lines = [_hit_line(imp.symbol) for imp in output.impacted]
        if output.files:
            lines.append(f"files: {', '.join(output.files)}")
        payload = output.model_dump(mode="json")
        payload["text"] = _render_text(lines, output, DEFAULT_BUDGET_TOKENS)
        return ToolResult(result=payload)


def create_structural_tools(
    store: BaseWikiStore,
    root: Path,
    config: WikiProjectConfig,
) -> list[AbstractTool]:
    """Create the three structural tools, sharing one local ``StructuralService``.

    Args:
        store: The (possibly federated) wiki retrieval-plane the tools
            resolve ``namespace`` against.
        root: Repository root the local plane describes — read-repair
            only ever reads/writes under this root.
        config: Effective project configuration for the local plane.

    Returns:
        ``[WikiSymbolLookupTool, WikiCodeOutlineTool, WikiBlastRadiusTool]``,
        all three sharing one ``service_factory``.
    """
    local_service = StructuralService(store, root, config)

    def service_factory(namespace: str | None) -> StructuralService:
        try:
            scoped = _scoped_store(store, namespace)
        except KeyError:
            raise ValueError(_unknown_namespace_error(store, str(namespace))) from None
        if scoped is store:
            return local_service
        # A foreign/federated namespace: read-repair is local-root-only
        # (Module 7's own contract), so this service's _ensure_fresh
        # naturally never finds a matching on-disk file for a foreign
        # store's rel_paths and performs no write — see TASK-2750's
        # Completion Note for the full reasoning.
        return StructuralService(scoped, root, config)

    return [
        WikiSymbolLookupTool(service_factory),
        WikiCodeOutlineTool(service_factory),
        WikiBlastRadiusTool(service_factory),
    ]

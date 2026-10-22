"""Framework-free structural plane operations (FEAT-540 M3)."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, Field

from parrot.knowledge.wiki.context import DEFAULT_BUDGET_TOKENS, truncate_to_tokens
from parrot.knowledge.wiki.operations import OperationResult
from parrot.knowledge.wiki.symbols import SymbolKind

if TYPE_CHECKING:
    from parrot.knowledge.wiki.structural.service import SymbolHit

_NAMESPACE_DESC = (
    "Federated namespace to read: a namespace name, 'all' to broadcast, "
    "'local' for this repo's own wiki. Omit for the default routing "
    "(broadcast when namespaces are configured)."
)


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

    target: str = Field(..., description="A file:<rel>, sym:<rel>#<qualname>, or bare relative path")
    depth: int = Field(default=2, ge=1, le=4, description="Maximum symbol nesting depth")
    include_source: bool = Field(default=False, description="Include a capped source excerpt (sym: targets only)")
    namespace: str | None = Field(default=None, description=_NAMESPACE_DESC)


class BlastRadiusInput(BaseModel):
    """Arguments for ``wiki_blast_radius`` / ``code_blast_radius``."""

    symbol: str = Field(..., description="A sym: id or an exact qualname")
    relations: list[Literal["calls", "extends", "implements", "uses", "references", "contains"]] | None = Field(
        default=None,
        description="Edge relations to follow (default: calls, extends, implements, uses)",
    )
    depth: int = Field(default=2, ge=1, le=5, description="Maximum BFS depth")
    include_inferred: bool = Field(
        default=True, description="Follow provenance='inferred' edges (globally-unique-name resolutions)"
    )
    include_tests: bool = Field(default=True, description="Include symbols under a tests/ path")
    namespace: str | None = Field(default=None, description=_NAMESPACE_DESC)


def _hit_line(hit: SymbolHit) -> str:
    """Render one ``SymbolHit`` as a compact single line."""
    doc = hit.doc.strip()
    suffix = f": {doc}" if doc else ""
    stale = " (stale)" if hit.stale else ""
    return f"[{hit.symbol_id}] — {hit.kind.value} L{hit.start_line}-{hit.end_line}{suffix}{stale}"


def _render_text(lines: list[str], model: BaseModel, budget_tokens: int) -> str:
    """Compact stub-line body plus a JSON tail, capped at ``budget_tokens``."""
    body = "\n".join(lines) if lines else "(no results)"
    tail = json.dumps(model.model_dump(mode="json"))
    text, _truncated = truncate_to_tokens(f"{body}\n\n{tail}", budget_tokens)
    return text


async def op_symbol_lookup(store: Any, params: SymbolLookupInput, **context: Any) -> OperationResult:
    """Run ``wiki_symbol_lookup`` against the context service factory."""
    factory = context["service_factory"]
    try:
        service = factory(params.namespace)
    except ValueError as exc:
        return OperationResult(text=str(exc), is_error=True)
    output = await service.lookup(
        params.query, kind=params.kind, language=params.language, path_prefix=params.path_prefix, limit=params.limit
    )
    payload = output.model_dump(mode="json")
    payload["text"] = _render_text([_hit_line(hit) for hit in output.hits], output, DEFAULT_BUDGET_TOKENS)
    return OperationResult(data=payload)


async def op_code_outline(store: Any, params: CodeOutlineInput, **context: Any) -> OperationResult:
    """Run ``wiki_code_outline`` against the context service factory."""
    factory = context["service_factory"]
    try:
        service = factory(params.namespace)
    except ValueError as exc:
        return OperationResult(text=str(exc), is_error=True)
    output = await service.outline(params.target, depth=params.depth, include_source=params.include_source)
    payload = output.model_dump(mode="json")
    payload["text"] = _render_text([_hit_line(hit) for hit in output.symbols], output, DEFAULT_BUDGET_TOKENS)
    return OperationResult(data=payload)


async def op_blast_radius(store: Any, params: BlastRadiusInput, **context: Any) -> OperationResult:
    """Run ``wiki_blast_radius`` against the context service factory."""
    factory = context["service_factory"]
    try:
        service = factory(params.namespace)
    except ValueError as exc:
        return OperationResult(text=str(exc), is_error=True)
    output = await service.blast_radius(
        params.symbol,
        relations=params.relations,
        depth=params.depth,
        include_inferred=params.include_inferred,
        include_tests=params.include_tests,
    )
    lines = [_hit_line(impact.symbol) for impact in output.impacted]
    if output.files:
        lines.append(f"files: {', '.join(output.files)}")
    payload = output.model_dump(mode="json")
    payload["text"] = _render_text(lines, output, DEFAULT_BUDGET_TOKENS)
    return OperationResult(data=payload)

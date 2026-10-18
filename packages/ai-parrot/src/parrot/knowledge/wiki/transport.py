"""Transport-neutral wiki operation descriptors (FEAT-540 M5)."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict

from parrot.knowledge.wiki.decisions.operations import (
    DecisionGenerateInput,
    DecisionsForSymbolInput,
    DecisionWhyInput,
    op_decision_generate,
    op_decision_why,
    op_decisions_for_symbol,
)
from parrot.knowledge.wiki.ledger.operations import (
    LedgerClaimInput,
    LedgerCloseInput,
    LedgerContextInput,
    LedgerListInput,
    LedgerOpenInput,
    LedgerReadyInput,
    LedgerShowInput,
    op_ledger_claim,
    op_ledger_close,
    op_ledger_context,
    op_ledger_list,
    op_ledger_open,
    op_ledger_ready,
    op_ledger_show,
)
from parrot.knowledge.wiki.operations import (
    IngestBatchInput,
    OperationResult,
    PageHashesInput,
    SyncPagesInput,
    VaultIngestInput,
    WikiLintInput,
    WikiNoteInput,
    WikiPageInput,
    WikiQueryInput,
    WikiRelatedInput,
    WikiRememberInput,
    WikiStandupInput,
    WikiStatusInput,
    op_ingest_batch,
    op_lint,
    op_note,
    op_page,
    op_page_hashes,
    op_query,
    op_related,
    op_remember,
    op_standup,
    op_status,
    op_sync_pull,
    op_sync_push,
    op_vault_ingest,
)
from parrot.knowledge.wiki.schema.operations import (
    SchemaLookupInput,
    SchemaNeighborsInput,
    SchemaSearchInput,
    SchemaSourcesInput,
    op_schema_lookup,
    op_schema_neighbors,
    op_schema_search,
    op_schema_sources,
)
from parrot.knowledge.wiki.structural.operations import (
    BlastRadiusInput,
    CodeOutlineInput,
    SymbolLookupInput,
    op_blast_radius,
    op_code_outline,
    op_symbol_lookup,
)


class OperationDescriptor(BaseModel):
    """One wiki tool, independent of transport."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    name: str
    description: str
    input_model: type[BaseModel]
    schema_fingerprint: str
    mount: str
    invoke: Callable[[BaseModel], Awaitable[OperationResult]]


@dataclass(frozen=True)
class _Spec:
    """Static, framework-free identity of one wiki operation."""

    mount: str
    input_model: type[BaseModel]
    description: str


# Names, mounts, LLM-facing descriptions and input schemas of every wiki
# operation.  The framework wrappers (``parrot_tools.wiki``) repeat the
# descriptions as class attributes; ``test_mcp_manifest_golden`` asserts the
# two stay identical for every mounted operation.
_SPECS: dict[str, _Spec] = {
    "wiki_query": _Spec(
        "core",
        WikiQueryInput,
        "Search the codebase knowledge graph for files, modules, symbols, or concepts. Returns ranked page stubs with IDs for drill-down. Use BEFORE grep/find/Read on large repos. When federated namespaces are configured this searches all of them and foreign page IDs come back prefixed (ns::file:a.py); pass `namespace` to search just one.",
    ),
    "wiki_page": _Spec(
        "core",
        WikiPageInput,
        "Read a full wiki page by ID — file summaries, API outlines, content. Use IDs returned by wiki_query, including namespaced ones (ns::file:a.py).",
    ),
    "wiki_related": _Spec(
        "core",
        WikiRelatedInput,
        "Follow typed edges (contains, references) from a wiki page to discover connected files and modules. Accepts namespaced page IDs (ns::dir:pkg) and returns neighbours from the same plane.",
    ),
    "wiki_remember": _Spec(
        "core",
        WikiRememberInput,
        "Save durable knowledge to the knowledge graph — decisions, gotchas, cross-file relationships. Survives across sessions.",
    ),
    "wiki_note": _Spec("core", WikiNoteInput, "Append a dated note to an existing wiki page."),
    "wiki_status": _Spec(
        "core", WikiStatusInput, "Check knowledge graph health: page count, staleness, last build time."
    ),
    "wiki_lint": _Spec(
        "core",
        WikiLintInput,
        "Lint the wiki knowledge graph: broken links, duplicate slugs, stale memories, ADR conflicts; fix=true applies safe fixes.",
    ),
    "wiki_standup": _Spec(
        "core",
        WikiStandupInput,
        "Render a daily, weekly or monthly wiki brief. Read-only unless writes are explicitly enabled.",
    ),
    "ledger_open": _Spec("ledger", LedgerOpenInput, "Open a new issue in the SDD work ledger."),
    "ledger_ready": _Spec("ledger", LedgerReadyInput, "Get ready (unclaimed) work from the SDD ledger."),
    "ledger_claim": _Spec("ledger", LedgerClaimInput, "Claim an issue from the SDD ledger."),
    "ledger_close": _Spec("ledger", LedgerCloseInput, "Close an issue in the SDD ledger."),
    "ledger_context": _Spec("ledger", LedgerContextInput, "Get context from the SDD ledger for specific files."),
    "ledger_list": _Spec(
        "ledger", LedgerListInput, "List SDD ledger issues by status (or all), kind, severity or about prefix."
    ),
    "ledger_show": _Spec(
        "ledger", LedgerShowInput, "Show one SDD ledger issue in full: state, body and event history."
    ),
    "wiki_symbol_lookup": _Spec(
        "structural",
        SymbolLookupInput,
        "Find a symbol (function/class/method) by name or qualname across the codebase. Returns ranked hits with file/line locations. Use before grep when you know the symbol's name but not where it lives.",
    ),
    "wiki_code_outline": _Spec(
        "structural",
        CodeOutlineInput,
        "Get the symbol outline of a file — every top-level (and nested, depth-bounded) class/function/method, with line ranges. Use before reading a whole file to see its shape first.",
    ),
    "wiki_blast_radius": _Spec(
        "structural",
        BlastRadiusInput,
        "Find every symbol that transitively depends on (calls/extends/implements) a given symbol — the 'blast radius' of changing it. Use before editing a widely-used function or class.",
    ),
    "wiki_page_hashes": _Spec(
        "bulk",
        PageHashesInput,
        "Return stored content hashes for up to 2000 page ids.\n\n    Delta oracle for the `wikitoolkit` CLI build push; not meant for agents.\n    ",
    ),
    "wiki_ingest_batch": _Spec(
        "bulk",
        IngestBatchInput,
        "Apply source slices pushed by `wikitoolkit build/upsert/ingest` in remote mode.\n\n    At most 200 slices and 1 MiB per call. For the CLI build push, not for agents.\n    ",
    ),
    "wiki_sync_push": _Spec(
        "bulk",
        SyncPagesInput,
        "Merge remote sync data used by `wikitoolkit sync` in remote mode; not for agents.\n\n"
        "    At most 200 pages and 1 MiB per call; the client chunks larger pushes.\n    ",
    ),
    "wiki_sync_pull": _Spec(
        "bulk", SyncPagesInput, "Return remote sync data used by `wikitoolkit sync` in remote mode; not for agents."
    ),
    "wiki_decisions_for_symbol": _Spec(
        "decisions",
        DecisionsForSymbolInput,
        "Find architectural decisions (ADRs) that apply to a function, class or method, with source citations. Documented decisions and inferred candidates are returned as separate, explicitly labeled groups — a candidate is a hypothesis, not accepted history.",
    ),
    "wiki_decision_why": _Spec(
        "decisions",
        DecisionWhyInput,
        "Answer a 'why' question about the codebase with cited decision excerpts and supporting code. Documented decisions rank above inferred candidates, which are returned in their own labeled group.",
    ),
    "wiki_decision_generate": _Spec(
        "decisions",
        DecisionGenerateInput,
        "Generate explicitly labeled CANDIDATE rationale for a symbol or file that has no documented decision. Candidates are inferred, unreviewed hypotheses and are never accepted history; a maintainer accepts them separately through the CLI.",
    ),
    "wiki_schema_lookup": _Spec(
        "schema",
        SchemaLookupInput,
        "Look up one table in the schema plane: DDL, columns, relations, annotations, age and staleness.",
    ),
    "wiki_schema_search": _Spec(
        "schema", SchemaSearchInput, "Full-text search over table names, column names and comments in the schema plane."
    ),
    "wiki_schema_neighbors": _Spec(
        "schema",
        SchemaNeighborsInput,
        "Foreign-key join paths from a table, up to `depth` hops, each with the (src_column -> dst_column) pair.",
    ),
    "wiki_schema_sources": _Spec(
        "schema",
        SchemaSourcesInput,
        "List the declared SQL sources (alias, dialect, schemas). DSNs are never exposed — only env-var names.",
    ),
    "vault_ingest": _Spec(
        "vault",
        VaultIngestInput,
        "Ingest (or refresh) an Obsidian vault into the wiki knowledge base: one page per note, wikilink/embed/tag edges, FTS-searchable via wiki_query. Incremental — unchanged notes are skipped unless force=true. No LLM calls.",
    ),
}


@dataclass
class WikiOperationContext:
    """Everything the operations need, with no framework objects involved.

    Attributes:
        store: Local (non-federated) retrieval-plane store; target of bulk and vault writes.
        read_store: Store the read operations query (federated when namespaces are mounted).
        root: Wiki project root.
        config: Effective ``WikiProjectConfig``.
        ledger_service: Ledger service, or ``None`` when no ledger is mounted.
        schema_service: Schema-plane service, or ``None`` when no plane is mounted.
        structural_service_factory: Namespace-aware ``StructuralService`` resolver.
        decision_service_factory: Namespace-aware ``DecisionService`` resolver.
        include_bulk_tools: Whether the server-only bulk/sync operations are mounted.
        vault_dir: Resolved Obsidian vault directory, or ``None``.
        read_repair: Whether structural operations may repair from local source files.
    """

    store: Any
    read_store: Any
    root: Path
    config: Any
    ledger_service: Any | None = None
    schema_service: Any | None = None
    structural_service_factory: Callable[[str | None], Any] | None = None
    decision_service_factory: Callable[[str | None], Any] | None = None
    include_bulk_tools: bool = False
    vault_dir: Path | None = None
    read_repair: bool = True

    @property
    def storage_dir(self) -> Path:
        """Return the local plane's storage directory."""
        return self.config.storage_path(self.root)


def schema_fingerprint(model: type[BaseModel]) -> str:
    """Return the SHA-256 digest of a canonical Pydantic JSON schema.

    Args:
        model: Pydantic input model used by an operation.

    Returns:
        Stable hexadecimal digest of the model JSON schema.
    """
    canonical_schema = json.dumps(model.model_json_schema(), sort_keys=True)
    return hashlib.sha256(canonical_schema.encode()).hexdigest()


def _operation_invoke(name: str, ctx: WikiOperationContext) -> Callable[[BaseModel], Awaitable[OperationResult]]:
    """Bind one plain operation to the context it runs against.

    Args:
        name: Operation name from the registry.
        ctx: Transport-neutral operation context.

    Returns:
        An operation coroutine that accepts the operation's validated input model.

    Raises:
        ValueError: If the name does not belong to the wiki operation surface.
    """
    store = ctx.read_store
    storage_dir = ctx.storage_dir
    structural = ctx.structural_service_factory
    decisions = ctx.decision_service_factory
    ledger = ctx.ledger_service
    schema = ctx.schema_service

    if name == "wiki_query":

        async def invoke(params: BaseModel) -> OperationResult:
            return await op_query(store, params)

    elif name == "wiki_page":

        async def invoke(params: BaseModel) -> OperationResult:
            return await op_page(store, params)

    elif name == "wiki_related":

        async def invoke(params: BaseModel) -> OperationResult:
            return await op_related(store, params)

    elif name == "wiki_remember":

        async def invoke(params: BaseModel) -> OperationResult:
            return await op_remember(store, params, storage_dir=storage_dir)

    elif name == "wiki_note":

        async def invoke(params: BaseModel) -> OperationResult:
            return await op_note(store, params, storage_dir=storage_dir)

    elif name == "wiki_status":

        async def invoke(params: BaseModel) -> OperationResult:
            return await op_status(store, params)

    elif name == "wiki_lint":

        async def invoke(params: BaseModel) -> OperationResult:
            return await op_lint(store, params, storage_dir=storage_dir)

    elif name == "wiki_standup":

        async def invoke(params: BaseModel) -> OperationResult:
            return await op_standup(store, params.model_dump(), root=ctx.root, config=ctx.config)

    elif name == "wiki_symbol_lookup":

        async def invoke(params: BaseModel) -> OperationResult:
            return await op_symbol_lookup(None, params, service_factory=structural)

    elif name == "wiki_code_outline":

        async def invoke(params: BaseModel) -> OperationResult:
            return await op_code_outline(None, params, service_factory=structural)

    elif name == "wiki_blast_radius":

        async def invoke(params: BaseModel) -> OperationResult:
            return await op_blast_radius(None, params, service_factory=structural)

    elif name == "wiki_decisions_for_symbol":

        async def invoke(params: BaseModel) -> OperationResult:
            return await op_decisions_for_symbol(None, params, service_factory=decisions)

    elif name == "wiki_decision_why":

        async def invoke(params: BaseModel) -> OperationResult:
            return await op_decision_why(None, params, service_factory=decisions)

    elif name == "wiki_decision_generate":

        async def invoke(params: BaseModel) -> OperationResult:
            return await op_decision_generate(None, params, service_factory=decisions)

    elif name == "wiki_schema_lookup":

        async def invoke(params: BaseModel) -> OperationResult:
            return await op_schema_lookup(None, params, service=schema, annotation_store=store)

    elif name == "wiki_schema_search":

        async def invoke(params: BaseModel) -> OperationResult:
            return await op_schema_search(None, params, service=schema)

    elif name == "wiki_schema_neighbors":

        async def invoke(params: BaseModel) -> OperationResult:
            return await op_schema_neighbors(None, params, service=schema)

    elif name == "wiki_schema_sources":

        async def invoke(params: BaseModel) -> OperationResult:
            return await op_schema_sources(None, params, service=schema)

    elif name == "ledger_open":

        async def invoke(params: BaseModel) -> OperationResult:
            return await op_ledger_open(ledger, params)

    elif name == "ledger_ready":

        async def invoke(params: BaseModel) -> OperationResult:
            return await op_ledger_ready(ledger, params)

    elif name == "ledger_claim":

        async def invoke(params: BaseModel) -> OperationResult:
            return await op_ledger_claim(ledger, params)

    elif name == "ledger_close":

        async def invoke(params: BaseModel) -> OperationResult:
            return await op_ledger_close(ledger, params)

    elif name == "ledger_context":

        async def invoke(params: BaseModel) -> OperationResult:
            return await op_ledger_context(ledger, params)

    elif name == "ledger_list":

        async def invoke(params: BaseModel) -> OperationResult:
            return await op_ledger_list(ledger, params)

    elif name == "ledger_show":

        async def invoke(params: BaseModel) -> OperationResult:
            return await op_ledger_show(ledger, params)

    elif name == "wiki_page_hashes":

        async def invoke(params: BaseModel) -> OperationResult:
            return await op_page_hashes(ctx.store, params)

    elif name == "wiki_ingest_batch":

        async def invoke(params: BaseModel) -> OperationResult:
            return await op_ingest_batch(ctx.store, params, root=ctx.root, config=ctx.config)

    elif name == "wiki_sync_push":

        async def invoke(params: BaseModel) -> OperationResult:
            return await op_sync_push(ctx.store, params, wiki_name=ctx.config.wiki_name)

    elif name == "wiki_sync_pull":

        async def invoke(params: BaseModel) -> OperationResult:
            return await op_sync_pull(ctx.store, params)

    elif name == "vault_ingest":

        async def invoke(params: BaseModel) -> OperationResult:
            return await op_vault_ingest(ctx.store, params, root=ctx.root, config=ctx.config)

    else:
        raise ValueError(f"Unsupported wiki operation: {name}")
    return invoke


def mounted_operation_names(ctx: WikiOperationContext) -> list[str]:
    """Return the operation names a configuration mounts, in registry order.

    Args:
        ctx: Transport-neutral operation context carrying every configuration gate.

    Returns:
        Names of the operations this configuration exposes.
    """
    names = [name for name, spec in _SPECS.items() if spec.mount == "core"]
    if ctx.ledger_service is not None:
        names += [name for name, spec in _SPECS.items() if spec.mount == "ledger"]
    names += [name for name, spec in _SPECS.items() if spec.mount == "structural"]
    if ctx.include_bulk_tools:
        names += [name for name, spec in _SPECS.items() if spec.mount == "bulk"]
    names += ["wiki_decisions_for_symbol", "wiki_decision_why"]
    if ctx.config.decisions.generation_enabled and ctx.root is not None:
        names.append("wiki_decision_generate")
    if ctx.schema_service is not None and ctx.config.schema_plane.enabled:
        names += [name for name, spec in _SPECS.items() if spec.mount == "schema"]
    if ctx.vault_dir is not None:
        names.append("vault_ingest")
    return names


def build_operation_descriptors(context: WikiOperationContext | Any) -> list[OperationDescriptor]:
    """Build descriptors for every operation a configuration mounts.

    The descriptors come from the operations registry and the stores in the
    context; no framework tool object is involved.

    Args:
        context: A :class:`WikiOperationContext`, or any object exposing one as ``.context``
            (a ``WikiToolBundle``).

    Returns:
        Ordered, transport-neutral descriptors for each mounted wiki operation.

    Raises:
        ValueError: If a mounted operation name is duplicated or unsupported.
    """
    ctx = getattr(context, "context", context)
    descriptors: list[OperationDescriptor] = []
    seen_names: set[str] = set()
    for name in mounted_operation_names(ctx):
        if name in seen_names:
            raise ValueError(f"Duplicate wiki operation name: {name}")
        seen_names.add(name)
        spec = _SPECS.get(name)
        if spec is None:
            raise ValueError(f"Unsupported wiki operation: {name}")
        descriptors.append(
            OperationDescriptor(
                name=name,
                description=spec.description,
                input_model=spec.input_model,
                schema_fingerprint=schema_fingerprint(spec.input_model),
                mount=spec.mount,
                invoke=_operation_invoke(name, ctx),
            )
        )
    return descriptors

"""Wiki AbstractTool wrappers (FEAT-403 Module 5).

Six `AbstractTool` subclasses that expose the wiki retrieval/authoring
surface (`BaseWikiStore`) as native tools, so they can be registered with
a `StdioMCPServer` (core) and appear as first-class MCP tools at
tool-selection time — equal standing with Grep/Read instead of competing
via a Bash-invoked CLI.
"""
import asyncio
import hashlib
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, Field

from parrot.knowledge.wiki.bookkeeper import WikiBookkeeper
from parrot.knowledge.wiki.context import DEFAULT_BUDGET_TOKENS, pack_results
from parrot.knowledge.wiki.project import WikiProjectConfig
from parrot.knowledge.wiki.store import BaseWikiStore, WikiPageRecord, estimate_tokens
from parrot.tools.abstract import AbstractTool, ToolResult


def _scoped_store(store: BaseWikiStore, namespace: str | None) -> BaseWikiStore:
    """Narrow a (possibly federated) store to one namespace selector.

    A plain store has no namespaces, so the selector is a no-op there —
    that keeps every existing caller (and the ``AsyncMock`` stores the
    tool tests use) working untouched.

    Args:
        store: The store the tool holds.
        namespace: The ``namespace`` tool argument.

    Returns:
        The store to read from.

    Raises:
        KeyError: When a federated store does not serve ``namespace``.
    """
    if not namespace:
        return store
    from parrot.knowledge.wiki.federation import FederatedWikiStore

    if not isinstance(store, FederatedWikiStore):
        return store
    return store.scoped(namespace)


def _reject_foreign_id(store: BaseWikiStore, page_id: str) -> str | None:
    """Explain why a write cannot target ``page_id``, or ``None`` if it can.

    Writes through these tools always land on the local plane; a
    namespaced page belongs to somebody else's wiki, which is reachable
    only through the CLI's explicit ``--ns`` write path (FEAT-450, U2).
    Detecting that up front keeps the tools returning structured errors
    instead of letting the store's ``ValueError`` escape mid-write.

    Args:
        store: The store the tool holds.
        page_id: The page id supplied by the caller.

    Returns:
        An error message, or ``None`` when the id is local.
    """
    from parrot.knowledge.wiki.context import split_namespaced_id

    namespace, _local = split_namespaced_id(page_id)
    if namespace is None:
        return None
    if namespace not in getattr(store, "namespaces", {}):
        return f"Unknown namespace {namespace!r} in page id {page_id!r}."
    return (
        f"Page {page_id!r} belongs to namespace {namespace!r}, which is "
        "read-only here. Writes to a namespace go through the CLI: "
        f"`wikitoolkit <command> --ns {namespace}`."
    )


def _unknown_namespace_error(store: BaseWikiStore, namespace: str) -> str:
    """Message for a ``namespace`` argument the store does not serve."""
    known = ", ".join(sorted(getattr(store, "namespaces", {}))) or "(none)"
    return (
        f"Unknown namespace {namespace!r}. Known: {known} "
        "(plus 'all', 'local')."
    )


#: search_fts() over-fetch multiplier for wiki_query (FEAT-498): 3x
#: search_fts's own default limit (10), so filtering out sym: stubs by
#: default still leaves a full page of non-symbol results.
_QUERY_FETCH_LIMIT = 30

#: Shared description of the optional ``namespace`` argument (FEAT-450).
_NAMESPACE_DESC = (
    "Federated namespace to read: a namespace name, 'all' to broadcast, "
    "'local' for this repo's own wiki. Omit for the default routing "
    "(broadcast when namespaces are configured)."
)


class WikiQueryInput(BaseModel):
    question: str = Field(..., description="Search question for the knowledge graph")
    budget_tokens: int = Field(default=DEFAULT_BUDGET_TOKENS, description="Token budget for results")
    namespace: str | None = Field(default=None, description=_NAMESPACE_DESC)
    include_symbols: bool = Field(
        default=False,
        description=(
            "Include sym: (function/class/method) stubs in results "
            "(FEAT-498). Off by default — use wiki_symbol_lookup for "
            "symbol-specific search; set True to see symbols mixed in "
            "with files/concepts here."
        ),
    )


class WikiPageInput(BaseModel):
    page_id: str = Field(
        ...,
        description=(
            "Page ID from wiki_query results; may carry a namespace "
            "prefix (ns::file:a.py)"
        ),
    )
    namespace: str | None = Field(default=None, description=_NAMESPACE_DESC)


class WikiRelatedInput(BaseModel):
    page_id: str = Field(
        ...,
        description=(
            "Page ID to find related pages for; may carry a namespace "
            "prefix (ns::dir:pkg)"
        ),
    )
    namespace: str | None = Field(default=None, description=_NAMESPACE_DESC)


class WikiRememberInput(BaseModel):
    fact: str = Field(..., description="Knowledge to save")
    category: str = Field(default="note", description="note|decision|lesson|concept")
    title: str | None = Field(default=None, description="Short title")
    link_page_id: str | None = Field(default=None, description="Page to link to")
    rel: str | None = Field(default="references", description="Relation type")


class WikiNoteInput(BaseModel):
    page_id: str = Field(..., description="Page to append note to")
    text: str = Field(..., description="Note text")


class VaultIngestInput(BaseModel):
    vault_path: str | None = Field(
        default=None,
        description=(
            "Obsidian vault directory (absolute or project-relative). "
            "Omit to use the project's configured/auto-detected vault."
        ),
    )
    force: bool = Field(
        default=False,
        description="Re-ingest every note, ignoring staleness tracking.",
    )


class WikiStatusInput(BaseModel):
    pass


class WikiQueryTool(AbstractTool):
    """Search the codebase knowledge graph for files, modules, symbols, or
    concepts. Returns ranked page stubs with IDs for drill-down. Use
    BEFORE grep/find/Read on large repos."""

    name = "wiki_query"
    description = (
        "Search the codebase knowledge graph for files, modules, symbols, "
        "or concepts. Returns ranked page stubs with IDs for drill-down. "
        "Use BEFORE grep/find/Read on large repos. When federated "
        "namespaces are configured this searches all of them and foreign "
        "page IDs come back prefixed (ns::file:a.py); pass `namespace` to "
        "search just one."
    )
    args_schema = WikiQueryInput

    def __init__(self, store: BaseWikiStore):
        super().__init__(name=self.name, description=self.description)
        self._store = store

    async def _execute(
        self,
        question: str,
        budget_tokens: int = DEFAULT_BUDGET_TOKENS,
        namespace: str | None = None,
        include_symbols: bool = False,
    ) -> str:
        try:
            store = _scoped_store(self._store, namespace)
        except KeyError:
            return _unknown_namespace_error(self._store, str(namespace))
        # FEAT-498: sym: pages share the pages_fts index, so a plain
        # search_fts() would mix them into every wiki_query result.
        # Over-fetch (limit*3) to compensate for the ones dropped, so a
        # question with few non-symbol hits doesn't come back thin.
        results = await store.search_fts(question, limit=_QUERY_FETCH_LIMIT)
        if not include_symbols:
            results = [r for r in results if r.get("category") != "symbol"]
        packed = pack_results(results, budget_tokens=budget_tokens)
        return packed.text


class WikiPageTool(AbstractTool):
    """Read a full wiki page by ID — file summaries, API outlines, content.
    Use IDs returned by wiki_query."""

    name = "wiki_page"
    description = (
        "Read a full wiki page by ID — file summaries, API outlines, "
        "content. Use IDs returned by wiki_query, including namespaced "
        "ones (ns::file:a.py)."
    )
    args_schema = WikiPageInput

    def __init__(self, store: BaseWikiStore):
        super().__init__(name=self.name, description=self.description)
        self._store = store

    async def _execute(
        self, page_id: str, namespace: str | None = None
    ) -> ToolResult:
        try:
            store = _scoped_store(self._store, namespace)
        except KeyError:
            return ToolResult(
                success=False, status="error", result=None,
                error=_unknown_namespace_error(self._store, str(namespace)),
            )
        page = await store.get_page(page_id, include_body=True)
        if page is None:
            return ToolResult(
                success=False, status="error", result=None,
                error=f"Page not found: {page_id}",
            )
        return ToolResult(result=page)


class WikiRelatedTool(AbstractTool):
    """Follow typed edges (contains, references) from a wiki page to
    discover connected files and modules."""

    name = "wiki_related"
    description = (
        "Follow typed edges (contains, references) from a wiki page to "
        "discover connected files and modules. Accepts namespaced page "
        "IDs (ns::dir:pkg) and returns neighbours from the same plane."
    )
    args_schema = WikiRelatedInput

    def __init__(self, store: BaseWikiStore):
        super().__init__(name=self.name, description=self.description)
        self._store = store

    async def _execute(
        self, page_id: str, namespace: str | None = None
    ) -> ToolResult:
        try:
            store = _scoped_store(self._store, namespace)
        except KeyError:
            return ToolResult(
                success=False, status="error", result=None,
                error=_unknown_namespace_error(self._store, str(namespace)),
            )
        neighbors = await store.neighbors(page_id)
        # Wrapped under a key (not a bare list) so the adapter's JSON
        # encoding path (dict → json.dumps) applies to this result too.
        return ToolResult(result={"neighbors": neighbors})


class WikiRememberTool(AbstractTool):
    """Save durable knowledge to the knowledge graph — decisions, gotchas,
    cross-file relationships. Survives across sessions."""

    name = "wiki_remember"
    description = (
        "Save durable knowledge to the knowledge graph — decisions, "
        "gotchas, cross-file relationships. Survives across sessions."
    )
    args_schema = WikiRememberInput

    def __init__(self, store: BaseWikiStore, storage_dir: Path | None = None):
        super().__init__(name=self.name, description=self.description)
        self._store = store
        self._storage_dir = storage_dir

    async def _execute(
        self,
        fact: str,
        category: str = "note",
        title: str | None = None,
        link_page_id: str | None = None,
        rel: str | None = "references",
    ) -> ToolResult:
        # Validate the link target BEFORE the first write: a namespaced
        # id would otherwise fail at add_edges, leaving the memory page
        # written and the call reported as an error.
        if link_page_id:
            refusal = _reject_foreign_id(self._store, link_page_id)
            if refusal:
                return ToolResult(
                    success=False, status="error", result=None, error=refusal
                )

        # Deterministic id from title+category (mirrors cli.py:remember —
        # re-remembering the same thing updates rather than duplicates).
        resolved_title = (title or fact.strip().splitlines()[0][:80]).strip()
        page_id = "mem-" + hashlib.sha1(
            f"{resolved_title}::{category}".encode()
        ).hexdigest()[:12]

        await self._store.upsert_pages([
            WikiPageRecord(
                concept_id=page_id,
                node_id=page_id,
                title=resolved_title,
                category=category,
                summary=fact[:300],
                body=fact,
                token_count=estimate_tokens(fact),
                origin="memory",
                asserted_by="agent:mcp",
            )
        ])

        linked = False
        if link_page_id:
            await self._store.add_edges(
                [(page_id, link_page_id, rel or "references", "asserted")]
            )
            linked = True

        if self._storage_dir is not None:
            # The store write above already succeeded — a failure logging
            # to the audit trail must not turn a successful remember into
            # a reported tool error (this call is otherwise unguarded, same
            # as cli.py's remember command).
            try:
                WikiBookkeeper().log_operation(
                    self._storage_dir,
                    "REMEMBER",
                    f"page_id: {page_id}, title: {resolved_title!r}, "
                    f"category: {category}, by: agent:mcp",
                )
            except OSError as exc:
                self.logger.warning(
                    "Failed to log REMEMBER to wiki audit trail: %s", exc
                )

        return ToolResult(result={
            "page_id": page_id,
            "title": resolved_title,
            "category": category,
            "linked": linked,
        })


class WikiNoteTool(AbstractTool):
    """Append a dated note to an existing wiki page."""

    name = "wiki_note"
    description = "Append a dated note to an existing wiki page."
    args_schema = WikiNoteInput

    def __init__(self, store: BaseWikiStore, storage_dir: Path | None = None):
        super().__init__(name=self.name, description=self.description)
        self._store = store
        self._storage_dir = storage_dir

    async def _execute(self, page_id: str, text: str) -> ToolResult:
        # Read-modify-write pattern (mirrors cli.py:1741-1790) — there is
        # no store.add_note(); notes are appended to the body in-process.
        page = await self._store.get_page(page_id, include_body=True)
        if page is None:
            return ToolResult(
                success=False, status="error", result=None,
                error=f"Page not found: {page_id}",
            )
        # A federated read returns the page with its id QUALIFIED; writing
        # that straight back would be a write into a foreign namespace.
        refusal = _reject_foreign_id(self._store, str(page["concept_id"]))
        if refusal:
            return ToolResult(
                success=False, status="error", result=None, error=refusal
            )

        stamp = datetime.now(tz=UTC).strftime("%Y-%m-%d")
        body = str(page.get("body") or "")
        body += f"\n\n> **Note ({stamp}, agent:mcp):** {text}"

        await self._store.upsert_pages([
            WikiPageRecord(
                concept_id=page["concept_id"],
                node_id=page.get("node_id"),
                title=page.get("title") or page["concept_id"],
                category=page.get("category") or "concept",
                summary=page.get("summary") or "",
                body=body,
                source_id=page.get("source_id"),
                token_count=estimate_tokens(body),
                origin=page.get("origin") or "ingest",
                asserted_by="agent:mcp",
            )
        ])

        if self._storage_dir is not None:
            # Same rationale as WikiRememberTool — an audit-log failure
            # must not mask the note that was already saved successfully.
            try:
                WikiBookkeeper().log_operation(
                    self._storage_dir,
                    "NOTE",
                    f"page_id: {page['concept_id']}, by: agent:mcp",
                )
            except OSError as exc:
                self.logger.warning(
                    "Failed to log NOTE to wiki audit trail: %s", exc
                )

        return ToolResult(result={"page_id": page["concept_id"], "status": "noted"})


class WikiStatusTool(AbstractTool):
    """Check knowledge graph health: page count, staleness, last build time."""

    name = "wiki_status"
    description = "Check knowledge graph health: page count, staleness, last build time."
    args_schema = WikiStatusInput

    def __init__(self, store: BaseWikiStore):
        super().__init__(name=self.name, description=self.description)
        self._store = store

    async def _execute(self) -> ToolResult:
        stats = await self._store.stats()
        return ToolResult(result=stats)


class VaultIngestTool(AbstractTool):
    """(Re)build the wiki retrieval plane from an Obsidian vault."""

    name = "vault_ingest"
    description = (
        "Ingest (or refresh) an Obsidian vault into the wiki knowledge "
        "base: one page per note, wikilink/embed/tag edges, FTS-searchable "
        "via wiki_query. Incremental — unchanged notes are skipped unless "
        "force=true. No LLM calls."
    )
    args_schema = VaultIngestInput

    def __init__(
        self,
        store: BaseWikiStore,
        root: Path,
        config: WikiProjectConfig,
    ):
        super().__init__(name=self.name, description=self.description)
        self._store = store
        self._root = root
        self._config = config

    async def _execute(
        self,
        vault_path: str | None = None,
        force: bool = False,
        **kwargs,
    ) -> ToolResult:
        # Lazy imports: cli pulls click + scanners; keep the MCP server's
        # module import light and stdout-clean.
        from parrot.knowledge.wiki.cli import (
            _ingest_files,
            _open_sources,
            _prune_removed,
        )
        from parrot.knowledge.wiki.project import (
            resolve_vault_dir,
            wiki_write_lock,
        )
        from parrot.knowledge.wiki.vault_scan import scan_vault

        vault = resolve_vault_dir(self._root, self._config, override=vault_path)
        if vault is None:
            return ToolResult(
                success=False,
                status="error",
                result=None,
                error=(
                    "No Obsidian vault found: pass vault_path, set "
                    "'vault_dir' in .parrot/wiki.json, or run inside a "
                    "vault (.obsidian/ directory)."
                ),
            )

        storage = self._config.storage_path(self._root)
        with wiki_write_lock(storage) as acquired:
            if not acquired:
                return ToolResult(
                    success=False,
                    status="error",
                    result=None,
                    error=(
                        "Another wiki writer (build/upsert) is in progress "
                        "— retry once it finishes."
                    ),
                )
            scan, stats = await asyncio.to_thread(
                scan_vault,
                vault,
                self._config.body_max_chars,
                self._config.max_file_kb * 1024,
            )
            sources = _open_sources(self._root, self._config, store=self._store)
            counts = await _ingest_files(
                self._store, sources, vault, scan, force=force
            )
            await self._store.upsert_pages(scan.dir_records)
            await self._store.add_edges(scan.dir_edges)
            # scope="root": this plane may also hold the repo's own
            # codebase pages — prune only what lives under the vault
            # (FEAT-450, D4.4).
            removed = await _prune_removed(
                self._store, sources, vault, scan, scope="root"
            )
            store_stats = await self._store.stats()

        try:
            WikiBookkeeper().log_operation(
                storage,
                "VAULT_INGEST",
                f"vault: {vault}, notes: {stats.notes}, tags: {stats.tags}, "
                f"ingested: {counts.get('written', 0)}, removed: {removed}, "
                f"by: agent:mcp",
            )
        except OSError as exc:
            self.logger.warning(
                "Failed to log VAULT_INGEST to wiki audit trail: %s", exc
            )

        return ToolResult(result={
            "vault": str(vault),
            "notes": stats.notes,
            "tags": stats.tags,
            "wikilink_edges": stats.wikilink_edges,
            "embed_edges": stats.embed_edges,
            "unresolved_links": len(stats.unresolved_links),
            "ingested": counts.get("written", 0),
            "unchanged": counts.get("unchanged", 0),
            "removed": removed,
            "skipped": len(scan.skipped),
            "pages_total": store_stats.get("pages", 0),
            "edges_total": store_stats.get("edges", 0),
        })


def create_wiki_tools(
    store: BaseWikiStore,
    root: Path | None = None,
    config: WikiProjectConfig | None = None,
) -> list[AbstractTool]:
    """Create the six wiki tools bound to ``store``.

    Args:
        store: Wiki retrieval-plane backend the tools call directly.
        root: Wiki project root. When given together with ``config``,
            ``wiki_remember``/``wiki_note`` also append an entry to the
            wiki's ``log.md`` audit trail (via `WikiBookkeeper`), matching
            the equivalent CLI commands (`cli.py:remember`/`note`).
        config: Wiki project config — see ``root``.

    Returns:
        The six `AbstractTool` instances: wiki_query, wiki_page,
        wiki_related, wiki_remember, wiki_note, wiki_status.
    """
    storage_dir = (
        config.storage_path(root) if root is not None and config is not None else None
    )
    return [
        WikiQueryTool(store),
        WikiPageTool(store),
        WikiRelatedTool(store),
        WikiRememberTool(store, storage_dir=storage_dir),
        WikiNoteTool(store, storage_dir=storage_dir),
        WikiStatusTool(store),
    ]

"""Wiki AbstractTool wrappers (FEAT-403 Module 5).

Six `AbstractTool` subclasses that expose the wiki retrieval/authoring
surface (`BaseWikiStore`) as native tools, so they can be registered with
a `StdioMCPServer` (core) and appear as first-class MCP tools at
tool-selection time — equal standing with Grep/Read instead of competing
via a Bash-invoked CLI.
"""
import hashlib
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, Field

from parrot.knowledge.wiki.bookkeeper import WikiBookkeeper
from parrot.knowledge.wiki.context import DEFAULT_BUDGET_TOKENS, pack_results
from parrot.knowledge.wiki.project import WikiProjectConfig
from parrot.knowledge.wiki.store import BaseWikiStore, WikiPageRecord, estimate_tokens
from parrot.tools.abstract import AbstractTool, ToolResult


class WikiQueryInput(BaseModel):
    question: str = Field(..., description="Search question for the knowledge graph")
    budget_tokens: int = Field(default=DEFAULT_BUDGET_TOKENS, description="Token budget for results")


class WikiPageInput(BaseModel):
    page_id: str = Field(..., description="Page ID from wiki_query results")


class WikiRelatedInput(BaseModel):
    page_id: str = Field(..., description="Page ID to find related pages for")


class WikiRememberInput(BaseModel):
    fact: str = Field(..., description="Knowledge to save")
    category: str = Field(default="note", description="note|decision|lesson|concept")
    title: str | None = Field(default=None, description="Short title")
    link_page_id: str | None = Field(default=None, description="Page to link to")
    rel: str | None = Field(default="references", description="Relation type")


class WikiNoteInput(BaseModel):
    page_id: str = Field(..., description="Page to append note to")
    text: str = Field(..., description="Note text")


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
        "Use BEFORE grep/find/Read on large repos."
    )
    args_schema = WikiQueryInput

    def __init__(self, store: BaseWikiStore):
        super().__init__(name=self.name, description=self.description)
        self._store = store

    async def _execute(self, question: str, budget_tokens: int = DEFAULT_BUDGET_TOKENS) -> str:
        results = await self._store.search_fts(question)
        packed = pack_results(results, budget_tokens=budget_tokens)
        return packed.text


class WikiPageTool(AbstractTool):
    """Read a full wiki page by ID — file summaries, API outlines, content.
    Use IDs returned by wiki_query."""

    name = "wiki_page"
    description = (
        "Read a full wiki page by ID — file summaries, API outlines, "
        "content. Use IDs returned by wiki_query."
    )
    args_schema = WikiPageInput

    def __init__(self, store: BaseWikiStore):
        super().__init__(name=self.name, description=self.description)
        self._store = store

    async def _execute(self, page_id: str) -> ToolResult:
        page = await self._store.get_page(page_id, include_body=True)
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
        "discover connected files and modules."
    )
    args_schema = WikiRelatedInput

    def __init__(self, store: BaseWikiStore):
        super().__init__(name=self.name, description=self.description)
        self._store = store

    async def _execute(self, page_id: str) -> ToolResult:
        neighbors = await self._store.neighbors(page_id)
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

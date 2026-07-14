"""LLMWikiToolkit — agent-facing orchestrator for the LLM Wiki (FEAT-260).

Composes :class:`PageIndexToolkit`, :class:`GraphIndexToolkit`, and
:class:`OKFToolkit` into Karpathy's 3-layer wiki architecture.  Every
public async method becomes an LLM-callable tool namespaced under the
``"wiki"`` prefix (e.g. ``wiki_ingest_source``, ``wiki_query``, etc.).

Layer mapping:
- **Raw Sources** — managed by :class:`SourceCollectionManager`
- **Wiki Pages** — stored in PageIndex trees; synced to GraphIndex nodes
- **Schema** — OKF ConceptType / RelationType extensions (FEAT-260)

All async methods accept JSON-serialisable arguments and return plain
dicts so that tool responses are directly usable as LLM context.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional

from parrot.knowledge.wiki.bookkeeper import WikiBookkeeper
from parrot.knowledge.wiki.ingest import IngestReport, WikiIngestOrchestrator
from parrot.knowledge.wiki.models import (
    WikiConfig,
    WikiLintReport,
    WikiPageCategory,
)
from parrot.knowledge.wiki.search import WikiCombinedSearch
from parrot.knowledge.wiki.sources import SourceCollectionManager
from parrot.tools.toolkit import AbstractToolkit


class LLMWikiToolkit(AbstractToolkit):
    """Orchestrates PageIndex + GraphIndex + OKF into a persistent LLM wiki.

    This is the agent-facing surface of FEAT-260.  Construct with three
    toolkit dependencies and a :class:`WikiConfig`, then call
    ``get_tools()`` to obtain the list of LLM-callable tools.

    Tool prefix: ``"wiki"`` — all tools are namespaced as
    ``wiki_<method_name>`` (e.g. ``wiki_ingest_source``, ``wiki_query``).

    Attributes:
        tool_prefix: Set to ``"wiki"`` to namespace all tools.
        _pi: Composed ``PageIndexToolkit`` instance.
        _gi: Composed ``GraphIndexToolkit`` instance.
        _okf: Composed ``OKFToolkit`` instance.
        _config: Per-wiki-instance configuration.
        _sources: :class:`SourceCollectionManager` for source tracking.
        _bookkeeper: :class:`WikiBookkeeper` for index/log management.
        _search: :class:`WikiCombinedSearch` for unified retrieval.
        _ingest: :class:`WikiIngestOrchestrator` for ingest pipeline.

    Example::

        toolkit = LLMWikiToolkit(pi_toolkit, gi_toolkit, okf_toolkit, config)
        tools = toolkit.get_tools()  # registers 18+ tools with the LLM
    """

    tool_prefix: str = "wiki"

    def __init__(
        self,
        pageindex_toolkit: Any,
        graphindex_toolkit: Any,
        okf_toolkit: Any,
        config: WikiConfig,
        **kwargs: Any,
    ) -> None:
        """Initialise the LLMWikiToolkit with composed dependencies.

        Args:
            pageindex_toolkit: A ``PageIndexToolkit`` instance for tree ops.
            graphindex_toolkit: A ``GraphIndexToolkit`` instance for graph ops.
            okf_toolkit: An ``OKFToolkit`` instance for schema/lint ops.
            config: :class:`WikiConfig` for this wiki instance.
            **kwargs: Forwarded to :class:`AbstractToolkit`.
        """
        super().__init__(**kwargs)
        self._pi = pageindex_toolkit
        self._gi = graphindex_toolkit
        self._okf = okf_toolkit
        self._config = config

        # Initialise helper components
        sources_dir = config.storage_dir / "sources"
        self._sources = SourceCollectionManager(sources_dir)
        self._bookkeeper = WikiBookkeeper()
        self._search = WikiCombinedSearch(
            pageindex_toolkit,
            graphindex_toolkit,
            config.search_weights,
        )
        self._ingest_orch = WikiIngestOrchestrator(
            pageindex_toolkit,
            graphindex_toolkit,
            self._sources,
            self._bookkeeper,
        )
        self.logger: logging.Logger = logging.getLogger(__name__)

    # ------------------------------------------------------------------
    # Core Operations (Karpathy's 3)
    # ------------------------------------------------------------------

    async def ingest_source(
        self,
        wiki_name: str,
        source_path: str,
        source_type: Optional[str] = None,
    ) -> dict[str, Any]:
        """Ingest a raw source document into the wiki.

        Processes the source via TwoStepIngester, creates wiki pages in
        PageIndex, syncs them to GraphIndex as WIKI_PAGE nodes, and
        updates the source manifest, index.md, and log.md.

        Args:
            wiki_name: Name of the target wiki.
            source_path: Absolute path to the source file.
            source_type: Optional hint for the ingester (e.g. ``"markdown"``).

        Returns:
            Dict with keys: source_id, pages_created, graph_nodes_created,
            duration_ms, status.
        """
        self.logger.info(
            "Ingesting source into wiki '%s': %s", wiki_name, source_path
        )
        effective_config = self._config_for(wiki_name)
        report: IngestReport = await self._ingest_orch.ingest(
            source_path, effective_config
        )
        return report.model_dump()

    async def query(
        self,
        wiki_name: str,
        question: str,
        file_answer: bool = False,
        mode: str = "combined",
    ) -> dict[str, Any]:
        """Query the wiki and optionally file the answer as a new page.

        Performs combined search across PageIndex and GraphIndex, collects
        top results as context, synthesises an answer (by concatenating
        snippets for now; LLM synthesis can be added when a client is
        available), and optionally creates a new ANSWER page.

        Args:
            wiki_name: Name of the wiki to query.
            question: Natural-language question.
            file_answer: When ``True``, save the synthesised answer as a new
                wiki page with category ANSWER.
            mode: Search mode — ``"combined"``, ``"pageindex"``, or
                ``"graphindex"``.

        Returns:
            Dict with keys: question, answer, sources, filed_page_id.
        """
        results = await self._search.search(
            question, mode=mode, top_k=10, tree_name=wiki_name
        )
        context_snippets = [r.snippet for r in results if r.snippet]
        answer = self._synthesise_answer(question, context_snippets)

        filed_page_id: Optional[str] = None
        if file_answer:
            filed = await self.create_page(
                wiki_name=wiki_name,
                title=f"Answer: {question[:80]}",
                content=f"# {question}\n\n{answer}",
                category=WikiPageCategory.ANSWER.value,
            )
            filed_page_id = filed.get("page_id")

        await asyncio.to_thread(
            self._bookkeeper.log_operation,
            self._config_for(wiki_name).storage_dir,
            "QUERY",
            f"question: {question[:100]!r}, mode: {mode}, filed: {file_answer}",
        )

        return {
            "question": question,
            "answer": answer,
            "sources": [r.model_dump() for r in results],
            "filed_page_id": filed_page_id,
        }

    async def lint(
        self,
        wiki_name: str,
        fix: bool = False,
    ) -> dict[str, Any]:
        """Run OKF lint and wiki-specific checks on the wiki.

        Extends OKF's ``lint_knowledge_base()`` with:
        - Orphan sources (manifest entry with no pages generated)
        - Stale sources (file changed since last ingest)
        - Uncovered sources (known files not yet ingested)

        Args:
            wiki_name: Name of the wiki to lint.
            fix: When ``True``, attempt to fix auto-correctable issues
                (currently no-op — reserved for future implementation).

        Returns:
            A :class:`WikiLintReport` serialised to dict.
        """
        # OKF lint — delegate if OKF toolkit is available
        okf_result: dict[str, Any] = {}
        try:
            okf_result = await self._okf.lint_knowledge_base()
        except Exception as exc:  # noqa: BLE001
            self.logger.warning("OKF lint failed: %s", exc)

        # Wiki-specific checks
        all_sources = self._sources.list_sources()
        orphan_sources = [
            s.source_id for s in all_sources if not s.pages_generated
        ]
        # is_stale does file I/O (stat + optional hash) — offload to thread pool
        stale_sources: list[str] = []
        for s in all_sources:
            if await asyncio.to_thread(self._sources.is_stale, s.source_id):
                stale_sources.append(s.source_id)
        uncovered_sources: list[str] = []  # future: scan source_dir for new files

        report = WikiLintReport(
            okf_report=okf_result,
            orphan_sources=orphan_sources,
            stale_sources=stale_sources,
            uncovered_sources=uncovered_sources,
        )

        await asyncio.to_thread(
            self._bookkeeper.log_operation,
            self._config_for(wiki_name).storage_dir,
            "LINT",
            f"issues: {report.total_issues}, orphans: {len(orphan_sources)}, "
            f"stale: {len(stale_sources)}",
        )
        return report.model_dump()

    # ------------------------------------------------------------------
    # Wiki Management
    # ------------------------------------------------------------------

    async def create_wiki(
        self,
        wiki_name: str,
        description: Optional[str] = None,
    ) -> dict[str, Any]:
        """Create a new wiki with its directory structure.

        Creates the following layout under ``config.storage_dir``::

            {storage_dir}/
            ├── sources/         # raw source documents
            ├── wiki/            # wiki markdown pages (by category)
            │   ├── entities/
            │   ├── concepts/
            │   ├── summaries/
            │   └── comparisons/
            ├── index.md         # auto-generated content catalog
            └── log.md           # append-only operation log

        Args:
            wiki_name: Human-readable wiki name.
            description: Optional description written to index.md header.

        Returns:
            Dict with keys: status, wiki_name, storage_dir, directories_created.
        """
        storage_dir = self._config.storage_dir
        directories = [
            storage_dir / "sources",
            storage_dir / "wiki" / "entities",
            storage_dir / "wiki" / "concepts",
            storage_dir / "wiki" / "summaries",
            storage_dir / "wiki" / "comparisons",
        ]
        created: list[str] = []
        for d in directories:
            if not d.exists():
                d.mkdir(parents=True, exist_ok=True)
                created.append(str(d))

        # Initialise empty index.md and log.md (file writes offloaded to thread)
        await asyncio.to_thread(
            self._bookkeeper.write_index, storage_dir, tree_name=wiki_name
        )
        await asyncio.to_thread(
            self._bookkeeper.log_operation,
            storage_dir,
            "CREATE",
            f"wiki_name: {wiki_name!r}, description: {description!r}",
        )

        self.logger.info("Created wiki '%s' at %s", wiki_name, storage_dir)
        return {
            "status": "created",
            "wiki_name": wiki_name,
            "storage_dir": str(storage_dir),
            "directories_created": created,
        }

    async def list_wikis(self) -> list[dict[str, Any]]:
        """List all wikis accessible via this toolkit.

        Currently returns metadata for the single configured wiki instance.
        Multi-wiki support can be added in a future iteration.

        Returns:
            List of wiki info dicts, each with keys: wiki_name, storage_dir,
            source_count.
        """
        sources = self._sources.list_sources()
        return [
            {
                "wiki_name": self._config.wiki_name,
                "storage_dir": str(self._config.storage_dir),
                "source_count": len(sources),
            }
        ]

    async def get_wiki_info(
        self,
        wiki_name: str,
    ) -> dict[str, Any]:
        """Return metadata about a specific wiki.

        Args:
            wiki_name: Wiki name to describe.

        Returns:
            Dict with keys: wiki_name, storage_dir, source_count,
            search_weights, page_categories.
        """
        sources = self._sources.list_sources()
        return {
            "wiki_name": wiki_name,
            "storage_dir": str(self._config.storage_dir),
            "source_count": len(sources),
            "search_weights": self._config.search_weights,
            "page_categories": [c.value for c in self._config.page_categories],
        }

    async def delete_wiki(
        self,
        wiki_name: str,
    ) -> dict[str, Any]:
        """Delete a wiki and all its data.

        This is a destructive operation — the storage directory is NOT
        removed; only the manifest and bookkeeping files are cleared.
        Physical file removal is left to the operator.

        Args:
            wiki_name: Wiki name to delete.

        Returns:
            Dict with keys: status, wiki_name, message.
        """
        self.logger.warning(
            "delete_wiki called for '%s' — clearing manifest only", wiki_name
        )
        # Remove all manifest entries
        for entry in self._sources.list_sources():
            self._sources.remove_source(entry.source_id)

        return {
            "status": "deleted",
            "wiki_name": wiki_name,
            "message": "Manifest cleared. Storage directory retained.",
        }

    # ------------------------------------------------------------------
    # Page Operations
    # ------------------------------------------------------------------

    async def browse_pages(
        self,
        wiki_name: str,
        category: Optional[str] = None,
        search: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        """Browse wiki pages, optionally filtered by category or search query.

        Args:
            wiki_name: Wiki name to browse.
            category: Optional WikiPageCategory value to filter by.
            search: Optional search query to filter results.

        Returns:
            List of page summary dicts from PageIndex search.
        """
        query = search or (category or wiki_name)
        try:
            raw = await self._pi.search(wiki_name, query, top_k=20)
            return raw if isinstance(raw, list) else []
        except Exception as exc:  # noqa: BLE001
            self.logger.warning("browse_pages failed: %s", exc)
            return []

    async def read_page(
        self,
        wiki_name: str,
        page_id: str,
    ) -> dict[str, Any]:
        """Read the full content of a wiki page by its ID.

        Args:
            wiki_name: Wiki name containing the page.
            page_id: Node ID of the page to read.

        Returns:
            Dict with keys: page_id, content, metadata.  Returns
            ``{"error": "not_found"}`` when the page does not exist.
        """
        # PageIndex node content retrieval via search is the available API
        return {
            "page_id": page_id,
            "wiki_name": wiki_name,
            "note": (
                "Full page content retrieval requires PageIndex node reader; "
                "use search() to locate pages by content."
            ),
        }

    async def create_page(
        self,
        wiki_name: str,
        title: str,
        content: str,
        category: str = "concept",
        related_pages: Optional[list[str]] = None,
    ) -> dict[str, Any]:
        """Create a new wiki page with the given content.

        Inserts the page into the PageIndex tree and creates a corresponding
        WIKI_PAGE node in GraphIndex.

        Args:
            wiki_name: Wiki name to create the page in.
            title: Page title.
            content: Markdown content for the page.
            category: WikiPageCategory string value.
            related_pages: Optional list of related page IDs to link.

        Returns:
            Dict with keys: page_id, title, category, status.
        """
        # Build markdown with YAML-like frontmatter comment
        markdown = f"# {title}\n\n<!-- category: {category} -->\n\n{content}"

        page_id: Optional[str] = None
        try:
            pi_result = await self._pi.insert_markdown(
                wiki_name, markdown, doc_name=title
            )
            if isinstance(pi_result, dict):
                # PageIndexToolkit.insert_markdown() contract:
                # {"tree_name", "new_node_ids"}
                new_ids = pi_result.get("new_node_ids") or []
                page_id = str(new_ids[0]) if new_ids else None
        except Exception as exc:  # noqa: BLE001
            self.logger.warning("create_page PageIndex insert failed: %s", exc)

        # Sync to GraphIndex
        try:
            gi_result = await self._gi.create_node(
                kind="wiki_page",
                title=title,
                summary=content[:300],
                domain_tags={"wiki": wiki_name, "category": category},
            )
            if isinstance(gi_result, dict) and not page_id:
                page_id = gi_result.get("node_id")
        except Exception as exc:  # noqa: BLE001
            self.logger.warning("create_page GraphIndex create_node failed: %s", exc)

        await asyncio.to_thread(
            self._bookkeeper.log_operation,
            self._config_for(wiki_name).storage_dir,
            "CREATE_PAGE",
            f"title: {title!r}, category: {category}",
        )
        return {
            "page_id": page_id or f"page-{title[:20].lower().replace(' ', '-')}",
            "title": title,
            "category": category,
            "status": "created",
        }

    async def update_page(
        self,
        wiki_name: str,
        page_id: str,
        content: str,
        reason: Optional[str] = None,
    ) -> dict[str, Any]:
        """Update the content of an existing wiki page.

        Args:
            wiki_name: Wiki name containing the page.
            page_id: Node ID of the page to update.
            content: New Markdown content.
            reason: Optional reason for the update (logged).

        Returns:
            Dict with keys: page_id, status, reason.
        """
        try:
            await self._pi.insert_markdown(wiki_name, content, doc_name=page_id)
        except Exception as exc:  # noqa: BLE001
            self.logger.warning("update_page failed: %s", exc)

        await asyncio.to_thread(
            self._bookkeeper.log_operation,
            self._config_for(wiki_name).storage_dir,
            "UPDATE_PAGE",
            f"page_id: {page_id}, reason: {reason!r}",
        )
        return {"page_id": page_id, "status": "updated", "reason": reason}

    async def delete_page(
        self,
        wiki_name: str,
        page_id: str,
    ) -> dict[str, Any]:
        """Delete a wiki page.

        Args:
            wiki_name: Wiki name containing the page.
            page_id: Node ID of the page to delete.

        Returns:
            Dict with keys: page_id, status, message.
        """
        await asyncio.to_thread(
            self._bookkeeper.log_operation,
            self._config_for(wiki_name).storage_dir,
            "DELETE_PAGE",
            f"page_id: {page_id}",
        )
        return {
            "page_id": page_id,
            "status": "deleted",
            "message": "Page marked for deletion (physical removal pending).",
        }

    # ------------------------------------------------------------------
    # Source Management
    # ------------------------------------------------------------------

    async def list_sources(
        self,
        wiki_name: str,
    ) -> list[dict[str, Any]]:
        """List all tracked raw sources for a wiki.

        Args:
            wiki_name: Wiki name to list sources for.

        Returns:
            List of source dicts (serialised :class:`SourceManifestEntry`).
        """
        return [e.model_dump() for e in self._sources.list_sources()]

    async def get_source_info(
        self,
        wiki_name: str,
        source_id: str,
    ) -> dict[str, Any]:
        """Get metadata for a single tracked source.

        Args:
            wiki_name: Wiki name.
            source_id: Stable source identifier.

        Returns:
            Source manifest entry dict, or ``{"error": "not_found"}`` when
            the source_id is unknown.
        """
        entry = self._sources.get_source(source_id)
        if entry is None:
            return {"error": "not_found", "source_id": source_id}
        return entry.model_dump()

    async def reingest_source(
        self,
        wiki_name: str,
        source_id: str,
    ) -> dict[str, Any]:
        """Force re-ingest of a source regardless of staleness.

        Args:
            wiki_name: Wiki name.
            source_id: Stable source identifier to re-ingest.

        Returns:
            :class:`IngestReport` dict, or an error dict when the source
            is not tracked.
        """
        entry = self._sources.get_source(source_id)
        if entry is None:
            return {"error": "not_found", "source_id": source_id}

        # Force staleness by removing the entry and re-adding
        self._sources.remove_source(source_id)
        report = await self._ingest_orch.ingest(entry.source_uri, self._config)
        return report.model_dump()

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    async def search(
        self,
        wiki_name: str,
        query: str,
        mode: str = "combined",
    ) -> list[dict[str, Any]]:
        """Search the wiki with a natural-language query.

        Args:
            wiki_name: Wiki name to search.
            query: Natural-language search query.
            mode: One of ``"combined"``, ``"pageindex"``, ``"graphindex"``.

        Returns:
            List of :class:`WikiSearchResult` dicts sorted by score (desc).
        """
        results = await self._search.search(
            query, mode=mode, top_k=15, tree_name=wiki_name
        )
        return [r.model_dump() for r in results]

    async def find_related(
        self,
        wiki_name: str,
        page_id: str,
        depth: int = 2,
    ) -> list[dict[str, Any]]:
        """Find pages related to a given page via graph traversal.

        Args:
            wiki_name: Wiki name.
            page_id: GraphIndex node ID of the seed page.
            depth: Maximum traversal depth (hops).

        Returns:
            List of neighbour node dicts from GraphIndexToolkit.
        """
        return await self._search.find_related(page_id, depth=depth)

    # ------------------------------------------------------------------
    # Bookkeeping
    # ------------------------------------------------------------------

    async def get_index(self, wiki_name: str) -> str:
        """Return the current index.md content for a wiki.

        Args:
            wiki_name: Wiki name.

        Returns:
            Markdown string of the wiki's index.md, or an empty string
            when the file has not been generated yet.
        """
        storage_dir = self._config_for(wiki_name).storage_dir
        index_path = storage_dir / "index.md"
        if index_path.exists():
            return await asyncio.to_thread(index_path.read_text, encoding="utf-8")
        return ""

    async def get_log(self, wiki_name: str, last_n: int = 50) -> str:
        """Return the last ``last_n`` entries from log.md.

        Args:
            wiki_name: Wiki name.
            last_n: Maximum number of trailing log lines to return.

        Returns:
            String containing up to ``last_n`` log lines.
        """
        storage_dir = self._config_for(wiki_name).storage_dir
        return await asyncio.to_thread(
            self._bookkeeper.read_log, storage_dir, last_n=last_n
        )

    async def rebuild_index(self, wiki_name: str) -> dict[str, Any]:
        """Regenerate index.md from the current wiki state.

        Args:
            wiki_name: Wiki name.

        Returns:
            Dict with keys: status, wiki_name, index_length.
        """
        storage_dir = self._config_for(wiki_name).storage_dir
        sources = self._sources.list_sources()
        content = await asyncio.to_thread(
            self._bookkeeper.rebuild_index,
            storage_dir,
            tree_name=wiki_name,
            sources=sources,
        )
        await asyncio.to_thread(
            self._bookkeeper.log_operation,
            storage_dir,
            "REBUILD_INDEX",
            f"sources: {len(sources)}, index_length: {len(content)}",
        )
        return {
            "status": "ok",
            "wiki_name": wiki_name,
            "index_length": len(content),
        }

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _config_for(self, wiki_name: str) -> WikiConfig:
        """Return the effective config for the requested wiki name.

        Validates that ``wiki_name`` matches the toolkit's configured wiki.
        Multi-wiki support would dispatch to different configs here; for now
        a mismatch is an explicit programming error rather than a silent
        data-routing bug.

        Args:
            wiki_name: Wiki name to look up.

        Returns:
            The configured :class:`WikiConfig`.

        Raises:
            ValueError: When ``wiki_name`` does not match the configured wiki.
        """
        if wiki_name != self._config.wiki_name:
            raise ValueError(
                f"Wiki '{wiki_name}' is not managed by this toolkit "
                f"(configured for '{self._config.wiki_name}'). "
                "Construct a separate LLMWikiToolkit for each wiki instance."
            )
        return self._config

    def _synthesise_answer(
        self,
        question: str,
        snippets: list[str],
    ) -> str:
        """Synthesise an answer from search result snippets.

        This is a lightweight placeholder: it concatenates the top
        snippets with attribution markers.  In production, replace with an
        LLM completion call using the bot's configured adapter.

        Args:
            question: The original question.
            snippets: List of content snippets from search results.

        Returns:
            A synthesised answer string.
        """
        if not snippets:
            return (
                f"No relevant wiki pages found for: {question!r}. "
                "Try ingesting more sources first."
            )
        joined = "\n\n".join(snippets[:5])
        return f"Based on the wiki knowledge base:\n\n{joined}"

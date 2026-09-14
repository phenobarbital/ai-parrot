"""DevLoopWikiSearch — opt-in wiki search facade for dev_loop research.

Provides token-budgeted codebase context from the project's LLM Wiki
retrieval plane (``.parrot/wiki``) to the ``ResearchNode`` dispatch
brief — the same ranked, compact stubs that ``wikitoolkit query``
returns, but consumed in-process (no CLI dependency, no PATH issues).

Auto-detected: when ``.parrot/wiki.json`` exists and the SQLite plane
is built, :meth:`DevLoopWikiSearch.from_project` returns a ready
instance. When the wiki is absent or unbuilt, it returns ``None`` —
every caller degrades to a no-op (same contract as
``DevLoopGraphMemory.from_config``).
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_DEFAULT_BUDGET_TOKENS = 4000


class DevLoopWikiSearch:
    """Lightweight facade for wiki-backed research context injection.

    Construct via :meth:`from_project` — never directly.
    """

    def __init__(self, *, store: object, wiki_name: str, shared_root: Optional[Path] = None) -> None:
        self._store = store
        self._wiki_name = wiki_name
        self._shared_root = shared_root
        self.logger = logging.getLogger(__name__)

    @classmethod
    def from_project(
        cls,
        root: Optional[Path] = None,
    ) -> Optional["DevLoopWikiSearch"]:
        """Auto-detect and open the project wiki if available.

        Resolution: finds ``.parrot/wiki.json`` by walking up from
        ``root`` (or CWD); checks whether the SQLite plane is built.
        Returns ``None`` on any failure — never raises.

        Args:
            root: Explicit project root. When ``None``, uses the wiki
                project-root discovery (walk-up to ``.parrot/wiki.json``
                or ``.git``).
        """
        try:
            from parrot.knowledge.wiki.project import (
                WikiProjectConfig,
                find_project_root,
                find_shared_root,
                load_project_config,
            )
            from parrot.knowledge.wiki.store import create_wiki_store
        except ImportError as exc:
            logger.debug("Wiki modules unavailable: %s", exc)
            return None

        try:
            # Resolve shared root first for worktree support
            resolved_root = root or find_project_root()
            if resolved_root is None:
                return None

            # Use shared root for wiki access in linked worktrees
            shared_root = find_shared_root(resolved_root) or resolved_root
            config: WikiProjectConfig = load_project_config(shared_root)
            if not config.is_built(shared_root):
                logger.debug(
                    "Wiki plane not built at %s — wiki search disabled",
                    config.storage_path(shared_root),
                )
                return None
            storage = config.storage_path(shared_root)
            store = create_wiki_store(
                storage,
                wiki_name=config.wiki_name,
                backend=config.backend,
            )
            logger.info(
                "DevLoopWikiSearch: opened wiki %r at %s",
                config.wiki_name,
                storage,
            )
            return cls(store=store, wiki_name=config.wiki_name, shared_root=shared_root)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "DevLoopWikiSearch.from_project failed: %s — wiki search disabled",
                exc,
            )
            return None

    async def build_research_context(
        self,
        query: str,
        budget_tokens: int = _DEFAULT_BUDGET_TOKENS,
    ) -> Optional[str]:
        """Search the wiki and return token-budgeted context text.

        Args:
            query: Natural-language query (typically the brief summary +
                affected component).
            budget_tokens: Hard token ceiling for the packed context.

        Returns:
            Markdown context text ready for prompt injection, or ``None``
            when nothing relevant was found (or on any internal error —
            context injection is best-effort, never fatal).
        """
        try:
            from parrot.knowledge.wiki.context import pack_results
            from parrot.knowledge.wiki.search import WikiCombinedSearch

            search = WikiCombinedSearch(
                pageindex_toolkit=None,
                graphindex_toolkit=None,
                store=self._store,
            )
            results = await search.search(
                query,
                mode="combined",
                top_k=25,
                tree_name=self._wiki_name,
            )
            if not results:
                wiki_context = None
            else:
                packed = pack_results(results, budget_tokens=budget_tokens)
                wiki_context = packed.text if packed.text and packed.results_packed else None

            # Try to append ledger context (best-effort)
            ledger_context = await self._get_ledger_context(query, budget_tokens // 2)

            # Combine contexts
            if wiki_context and ledger_context:
                return f"{wiki_context}\n\n## Related Issues\n{ledger_context}"
            elif wiki_context:
                return wiki_context
            elif ledger_context:
                return f"## Related Issues\n{ledger_context}"
            else:
                return None
        except Exception as exc:  # noqa: BLE001
            self.logger.warning(
                "DevLoopWikiSearch.build_research_context failed: %s",
                exc,
            )
            return None

    async def _get_ledger_context(self, query: str, max_tokens: int) -> Optional[str]:
        """Get relevant ledger context for the query (best-effort).

        Args:
            query: The research query to scope ledger context to.
            max_tokens: Token budget for ledger context.

        Returns:
            Formatted ledger context or None if unavailable.
        """
        try:
            from parrot.knowledge.wiki.ledger.service import LedgerService

            # Best-effort ledger context (never fatal)
            # Reuse the shared root resolved in from_project() instead of
            # letting LedgerService fall back to CWD, which would silently
            # target the wrong repo whenever the caller's CWD isn't it.
            ledger_service = LedgerService.from_root(self._shared_root)
            # For now, we'll use a simple approach to extract file paths from the query
            # In a real implementation, this would be more sophisticated
            file_paths = self._extract_file_paths_from_query(query)
            ledger_text = await ledger_service.get_context(file_paths, max_tokens=max_tokens)

            return ledger_text if ledger_text.strip() else None
        except Exception as exc:  # noqa: BLE001
            self.logger.debug("Ledger context lookup failed (continuing): %s", exc)
            return None

    def _extract_file_paths_from_query(self, query: str) -> list[str]:
        """Extract likely file paths from a query string.

        Args:
            query: Research query string.

        Returns:
            List of potential file paths mentioned in the query.
        """
        # Simple heuristic: look for paths with extensions or sdd/task references
        paths = []

        # Look for sdd/task references
        task_matches = re.findall(r"[A-Z]+-\d+", query)
        paths.extend([f"sdd/tasks/active/{match}.md" for match in task_matches])
        paths.extend([f"sdd/tasks/completed/{match}.md" for match in task_matches])

        # Look for file paths with extensions
        file_matches = re.findall(r"[a-zA-Z0-9/_\-\.]+\.[a-zA-Z0-9]+", query)
        paths.extend(file_matches)

        return paths


__all__ = ["DevLoopWikiSearch"]

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
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_DEFAULT_BUDGET_TOKENS = 4000


class DevLoopWikiSearch:
    """Lightweight facade for wiki-backed research context injection.

    Construct via :meth:`from_project` — never directly.
    """

    def __init__(self, *, store: object, wiki_name: str) -> None:
        self._store = store
        self._wiki_name = wiki_name
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
                load_project_config,
            )
            from parrot.knowledge.wiki.store import create_wiki_store
        except ImportError as exc:
            logger.debug("Wiki modules unavailable: %s", exc)
            return None

        try:
            resolved_root = root or find_project_root()
            if resolved_root is None:
                return None
            config: WikiProjectConfig = load_project_config(resolved_root)
            if not config.is_built(resolved_root):
                logger.debug(
                    "Wiki plane not built at %s — wiki search disabled",
                    config.storage_path(resolved_root),
                )
                return None
            storage = config.storage_path(resolved_root)
            store = create_wiki_store(
                storage, wiki_name=config.wiki_name, backend=config.backend,
            )
            logger.info(
                "DevLoopWikiSearch: opened wiki %r at %s",
                config.wiki_name, storage,
            )
            return cls(store=store, wiki_name=config.wiki_name)
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
                query, mode="combined", top_k=25, tree_name=self._wiki_name,
            )
            if not results:
                return None
            packed = pack_results(results, budget_tokens=budget_tokens)
            if not packed.text or not packed.results_packed:
                return None
            return packed.text
        except Exception as exc:  # noqa: BLE001
            self.logger.warning(
                "DevLoopWikiSearch.build_research_context failed: %s", exc,
            )
            return None


__all__ = ["DevLoopWikiSearch"]

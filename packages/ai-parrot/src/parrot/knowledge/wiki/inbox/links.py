"""Retrieve, select and reverify document relations."""

import logging
import re

from parrot.knowledge.pageindex.llm_adapter import PageIndexLLMAdapter
from parrot.knowledge.wiki.inbox.models import (
    RELATIONS,
    LinkCandidate,
    LinkSelection,
    ResolvedClassification,
    VerifiedLink,
)
from parrot.knowledge.wiki.review import Claim
from parrot.knowledge.wiki.search import WikiCombinedSearch
from parrot.knowledge.wiki.store import BaseWikiStore

# Matches explicit ``sym:``/``file:`` ids (group ``id``) and backticked file paths (group ``path``).
_VERBATIM_RE = re.compile(
    r"(?P<id>\b(?:sym|file):[^\s`'\",;)\]>]+)|`(?P<path>[\w./\-]+\.[A-Za-z0-9]+)`"
)
_CODE_PREFIXES = ("sym:", "file:")
_VERBATIM_WHY = "verbatim mention"


def _is_code_id(page_id: str) -> bool:
    """Return whether a page id belongs to the code (``sym:``/``file:``) namespace."""
    return page_id.startswith(_CODE_PREFIXES)


class LinkProposer:
    """Select only existing pages from a bounded candidate set."""

    def __init__(
        self,
        store: BaseWikiStore,
        search: WikiCombinedSearch,
        adapter: PageIndexLLMAdapter | None,
        *,
        max_candidates: int = 20,
        top_k: int = 15,
    ) -> None:
        """Bind retrieval and optional model selection dependencies."""
        self.store = store
        self.search = search
        self.adapter = adapter
        self.max_candidates = max_candidates
        self.top_k = top_k
        self.logger = logging.getLogger(__name__)

    @staticmethod
    def _verbatim_ids(text: str) -> list[str]:
        """Extract explicit code page ids mentioned in ``text``, in order of appearance."""
        found: list[str] = []
        for match in _VERBATIM_RE.finditer(text):
            if match.group("id"):
                page_id = match.group("id").rstrip(".:")
            else:
                page_id = f"file:{match.group('path')}"
            if page_id not in found:
                found.append(page_id)
        return found

    async def _build(self, page_id: str, origin: str) -> LinkCandidate | None:
        """Build a candidate through ``get_page``; ``None`` when the page does not exist."""
        page = await self.store.get_page(page_id, include_body=False)
        if not page:
            return None
        return LinkCandidate(
            page_id=str(page.get("concept_id") or page_id),
            title=str(page.get("title") or page_id),
            category=str(page.get("category") or ""),
            summary=str(page.get("summary") or ""),
            origin=origin,  # type: ignore[arg-type]
        )

    async def candidates(
        self,
        text: str,
        classification: ResolvedClassification,
        claims: list[Claim],
        exclude_ids: set[str],
    ) -> list[LinkCandidate]:
        """Retrieve and dedupe candidates, excluding own pages before the cap."""
        ordered: dict[str, LinkCandidate] = {}

        def _admit(candidate: LinkCandidate | None) -> None:
            if candidate is None or candidate.page_id in exclude_ids or candidate.page_id in ordered:
                return
            ordered[candidate.page_id] = candidate

        # Verbatim mentions first: they are the only entry for code pages and must survive the cap.
        for page_id in self._verbatim_ids(text):
            if page_id in exclude_ids:
                continue
            _admit(await self._build(page_id, "verbatim"))

        query = " ".join([classification.title, *classification.tags, *(claim.text for claim in claims)]).strip()
        if query:
            results = await self.search.search(query, top_k=self.top_k, include_archived=False)
            for result in results:
                if _is_code_id(result.node_id) or result.node_id in exclude_ids or result.node_id in ordered:
                    continue
                _admit(await self._build(result.node_id, "search"))

        for tag in classification.tags:
            for row in await self.store.search_fts(tag, limit=self.top_k):
                page_id = str(row.get("concept_id") or "")
                if not page_id or _is_code_id(page_id) or page_id in exclude_ids or page_id in ordered:
                    continue
                candidate = await self._build(page_id, "tag_fts")
                if candidate is not None and candidate.category == "archive":
                    continue
                _admit(candidate)

        return list(ordered.values())[: self.max_candidates]

    async def select(
        self,
        text: str,
        classification: ResolvedClassification,
        candidates: list[LinkCandidate],
    ) -> list[VerifiedLink]:
        """Validate selected relations and re-read targets, degrading on model failure."""
        selection = await self._ask(text, classification, candidates)
        if selection is None:
            proposed = self.deterministic_links(candidates)
        else:
            by_id = {candidate.page_id: candidate for candidate in candidates}
            proposed = []
            seen: set[str] = set()
            for choice in selection.links:
                if choice.page_id not in by_id:
                    self.logger.warning("LINK_DROPPED page_id=%s reason=not_a_candidate", choice.page_id)
                    continue
                if choice.rel not in RELATIONS:
                    self.logger.warning("LINK_DROPPED page_id=%s reason=invalid_relation rel=%s", choice.page_id, choice.rel)
                    continue
                if choice.page_id in seen:
                    self.logger.warning("LINK_DROPPED page_id=%s reason=duplicate", choice.page_id)
                    continue
                seen.add(choice.page_id)
                proposed.append(
                    VerifiedLink(
                        page_id=choice.page_id,
                        rel=choice.rel,
                        why=choice.why,
                        title=by_id[choice.page_id].title,
                    )
                )

        verified: list[VerifiedLink] = []
        for link in proposed:
            page = await self.store.get_page(link.page_id, include_body=False)
            if not page:
                self.logger.warning("LINK_DROPPED page_id=%s reason=missing_target", link.page_id)
                continue
            verified.append(link.model_copy(update={"title": str(page.get("title") or link.title)}))
        return verified

    async def _ask(
        self,
        text: str,
        classification: ResolvedClassification,
        candidates: list[LinkCandidate],
    ) -> LinkSelection | None:
        """Ask the adapter for a selection; ``None`` means degrade to deterministic links."""
        if self.adapter is None or not candidates:
            return None
        listing = "\n".join(
            f"- {candidate.page_id} | {candidate.title} | {candidate.category} | {candidate.summary[:200]}"
            for candidate in candidates
        )
        prompt = (
            "Select which candidate pages the document relates to. Use only candidate page ids and only these "
            f"relations: {', '.join(RELATIONS)}. Give a short reason for each.\n\n"
            f"Document title: {classification.title}\nSummary: {classification.summary}\n\n"
            f"Document excerpt:\n{text[:4000]}\n\nCandidates:\n{listing}"
        )
        try:
            result = await self.adapter.ask_structured(prompt, LinkSelection)
        except Exception as exc:  # noqa: BLE001 - any adapter failure degrades to verbatim links
            self.logger.warning("Link selection failed, using verbatim links: %s", exc)
            return None
        if not isinstance(result, LinkSelection):
            self.logger.warning("Link selection returned %s, using verbatim links", type(result).__name__)
            return None
        return result

    @staticmethod
    def deterministic_links(candidates: list[LinkCandidate]) -> list[VerifiedLink]:
        """Return references for verbatim candidates, with reason verbatim mention."""
        links: list[VerifiedLink] = []
        seen: set[str] = set()
        for candidate in candidates:
            if candidate.origin != "verbatim" or candidate.page_id in seen:
                continue
            seen.add(candidate.page_id)
            links.append(
                VerifiedLink(page_id=candidate.page_id, rel="references", why=_VERBATIM_WHY, title=candidate.title)
            )
        return links

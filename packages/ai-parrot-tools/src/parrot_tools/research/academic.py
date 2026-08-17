"""
AcademicResearchToolkit — direct access to free academic-literature APIs
(FEAT-426 Module 3: Crossref search; PubMed, Semantic Scholar, arXiv, and
`get_paper_details` are added by later tasks in this same module).

Crossref also covers Oxford Academic (OUP) content via DOI prefix
"10.1093" — OUP has no API of its own, so there is no separate Oxford
source anywhere in this feature. See spec §3 Module 3 and §7 "Known
Risks".
"""
import backoff
from navconfig import config
from parrot.tools.toolkit import AbstractToolkit

from .base import BaseResearchToolkit
from .models import PaperResult, ResearchResult

try:
    from habanero import Crossref
except ImportError:
    Crossref = None

_CROSSREF_SOURCE_NAME = "Crossref"
_CROSSREF_MISSING_MESSAGE = (
    "Crossref support requires: pip install 'ai-parrot-tools[research]'"
)
# Papers are slow-changing relative to indicators — cache aggressively.
_CROSSREF_CACHE_TTL = 86400


class AcademicResearchToolkit(BaseResearchToolkit, AbstractToolkit):
    """Direct, structured access to authoritative academic-literature sources.

    Currently covers Crossref (full-text bibliographic search, also
    reaching Oxford Academic content via DOI prefix "10.1093"). PubMed,
    Semantic Scholar, arXiv, and `get_paper_details` are added by later
    tasks in this same module (spec §3 Module 3).
    """

    async def search_crossref(
        self,
        query: str,
        author: str | None = None,
        year_range: str | None = None,
        journal: str | None = None,
        max_results: int = 10,
    ) -> ResearchResult:
        """Search Crossref for scholarly works (articles, books, ...).

        Also reaches Oxford Academic (OUP) content — OUP has no API of its
        own, and its works are indexed in Crossref under DOI prefix
        "10.1093". Best results come from a natural-language bibliographic
        query (title + author + journal combined) rather than bare
        keywords.

        Args:
            query: Bibliographic query (title, authors, journal, etc.).
            author: Optional author name filter.
            year_range: Optional publication year range, e.g. "2020-2023".
            journal: Optional container/journal title filter.
            max_results: Maximum number of works to return.

        Returns:
            A `ResearchResult` with `result_type="papers"`.
        """
        source = "academic.search_crossref"
        if Crossref is None:
            return self._failure(
                query, source, "papers", "error", _CROSSREF_MISSING_MESSAGE
            )

        cache_params = {
            "query": query, "author": author,
            "year_range": year_range, "journal": journal,
            "max_results": max_results,
        }
        cached = await self._cache.get(
            "academic", "search_crossref", **cache_params
        )
        if cached is not None:
            return ResearchResult(**cached)

        # Polite pool: Crossref routes `mailto` traffic to a better-served
        # pool. No registration required — just an identifying address.
        mailto = config.get("CROSSREF_MAILTO", fallback="noreply@example.com")
        filters = self._crossref_filters(year_range)

        try:
            payload = await self._fetch_crossref_works(
                query, author, journal, max_results, mailto, filters
            )
        except Exception as e:  # noqa: BLE001 — never raise into the agent loop
            self.logger.error("Crossref search failed: %s", e)
            return self._failure(
                query, source, "papers", "error", f"Crossref search failed: {e}"
            )

        items = (payload or {}).get("message", {}).get("items", [])
        if not items:
            return self._failure(
                query, source, "papers", "no_data",
                f"No Crossref works matched '{query}'",
            )

        papers = [self._paper_from_item(item) for item in items[:max_results]]
        first_doi = papers[0].doi if papers else None
        citation = self._build_citation(
            source_name=_CROSSREF_SOURCE_NAME,
            source_url=(
                f"https://doi.org/{first_doi}" if first_doi
                else "https://api.crossref.org/works"
            ),
            doi=first_doi,
        )
        result = ResearchResult(
            query=query, source=source, result_type="papers",
            status="success", total_results=len(papers),
            papers=papers, citation=citation,
        )
        await self._cache.set(
            "academic", "search_crossref", result.model_dump(),
            ttl=_CROSSREF_CACHE_TTL, **cache_params,
        )
        return result

    @staticmethod
    def _crossref_filters(year_range: str | None) -> dict | None:
        """Build a Crossref `filter=` dict for a "YYYY-YYYY" year range."""
        if not year_range:
            return None
        parts = year_range.split("-")
        if len(parts) == 2 and all(p.strip().isdigit() for p in parts):
            start, end = (p.strip() for p in parts)
            return {
                "from-pub-date": f"{start}-01-01",
                "until-pub-date": f"{end}-12-31",
            }
        return None

    async def _fetch_crossref_works(
        self,
        query: str,
        author: str | None,
        journal: str | None,
        max_results: int,
        mailto: str,
        filters: dict | None,
    ) -> dict:
        """Run the blocking `habanero.Crossref.works()` call in an executor."""

        @backoff.on_exception(backoff.expo, Exception, max_tries=3)
        def _fetch():
            cr = Crossref(mailto=mailto)
            # Prefer `query_bibliographic` over the generic `query` param —
            # it ranks title/author/journal combinations far better.
            kwargs = {"query_bibliographic": query, "limit": max_results}
            if author:
                kwargs["query_author"] = author
            if journal:
                kwargs["query_container_title"] = journal
            if filters:
                kwargs["filter"] = filters
            return cr.works(**kwargs)

        return await self._run_sync_in_executor(_fetch)

    def _paper_from_item(self, item: dict) -> PaperResult:
        """Convert a raw Crossref `/works` item into a `PaperResult`.

        `title` and `container-title` arrive as lists (possibly empty);
        `author` entries are `{given, family}` dicts; `issued.date-parts`
        is a nested list.
        """
        titles = item.get("title") or []
        title = titles[0] if titles else "Untitled work"

        authors = []
        for a in item.get("author", []) or []:
            name = " ".join(
                part for part in (a.get("given"), a.get("family")) if part
            )
            if name:
                authors.append(name)

        containers = item.get("container-title") or []
        journal = containers[0] if containers else None

        published_date = None
        date_parts = (item.get("issued") or {}).get("date-parts") or []
        if date_parts and date_parts[0]:
            published_date = "-".join(str(p) for p in date_parts[0])

        return PaperResult(
            title=title,
            authors=authors,
            doi=item.get("DOI"),
            url=item.get("URL"),
            journal=journal,
            published_date=published_date,
            citation_count=item.get("is-referenced-by-count"),
            source="crossref",
        )

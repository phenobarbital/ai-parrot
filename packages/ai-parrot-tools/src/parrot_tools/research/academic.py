"""
AcademicResearchToolkit — direct access to free academic-literature APIs
(FEAT-426 Module 3: Crossref, PubMed; Semantic Scholar, arXiv, and
`get_paper_details` are added by later tasks in this same module).

Crossref also covers Oxford Academic (OUP) content via DOI prefix
"10.1093" — OUP has no API of its own, so there is no separate Oxford
source anywhere in this feature. PubMed requires a mandatory two-step
`esearch` -> `efetch` workflow and NCBI's documented rate limits (3 req/s
unkeyed, 10 req/s with a free API key). See spec §3 Module 3 and §7
"Known Risks".
"""
import asyncio

import backoff
from navconfig import config
from parrot.tools.toolkit import AbstractToolkit

from .base import BaseResearchToolkit
from .models import PaperResult, ResearchResult

try:
    from habanero import Crossref
except ImportError:
    Crossref = None

try:
    # PyPI distribution is `biopython`; the importable module is `Bio`.
    from Bio import Entrez
except ImportError:
    Entrez = None

_CROSSREF_SOURCE_NAME = "Crossref"
_CROSSREF_MISSING_MESSAGE = (
    "Crossref support requires: pip install 'ai-parrot-tools[research]'"
)
# Papers are slow-changing relative to indicators — cache aggressively.
_CROSSREF_CACHE_TTL = 86400

_PUBMED_SOURCE_NAME = "PubMed"
_PUBMED_MISSING_MESSAGE = (
    "PubMed support requires: pip install 'ai-parrot-tools[research]'"
)
_PUBMED_CACHE_TTL = 86400
# NCBI documented rate limits: 3 req/s unkeyed, 10 req/s with an API key.
# A small inter-call delay between esearch and efetch is enough at this scale.
_PUBMED_UNKEYED_DELAY = 1.0 / 3
_PUBMED_KEYED_DELAY = 1.0 / 10


class AcademicResearchToolkit(BaseResearchToolkit, AbstractToolkit):
    """Direct, structured access to authoritative academic-literature sources.

    Covers Crossref (full-text bibliographic search, also reaching Oxford
    Academic content via DOI prefix "10.1093") and PubMed (two-step
    `esearch`/`efetch` biomedical literature search). Semantic Scholar,
    arXiv, and `get_paper_details` are added by later tasks in this same
    module (spec §3 Module 3).
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

    async def search_pubmed(
        self,
        query: str,
        mesh_terms: str | None = None,
        date_range: str | None = None,
        max_results: int = 10,
    ) -> ResearchResult:
        """Search PubMed for biomedical literature.

        PubMed requires a mandatory two-step workflow: `esearch` resolves
        the query to a list of PMIDs, then `efetch` retrieves the full
        records for those PMIDs (XML only — no JSON for full records).
        NCBI requires an identifying email and rate-limits to 3 req/s
        unkeyed, 10 req/s with a free `NCBI_API_KEY`.

        Args:
            query: Free-text PubMed query.
            mesh_terms: Optional MeSH term filter, combined with `query`
                as `"<query> AND <mesh_terms>[MeSH Terms]"`.
            date_range: Optional publication date range, e.g. "2020-2026".
            max_results: Maximum number of PMIDs/records to fetch.

        Returns:
            A `ResearchResult` with `result_type="papers"`.
        """
        source = "academic.search_pubmed"
        if Entrez is None:
            return self._failure(
                query, source, "papers", "error", _PUBMED_MISSING_MESSAGE
            )

        cache_params = {
            "query": query, "mesh_terms": mesh_terms,
            "date_range": date_range, "max_results": max_results,
        }
        cached = await self._cache.get("academic", "search_pubmed", **cache_params)
        if cached is not None:
            return ResearchResult(**cached)

        self._configure_entrez()
        term = self._build_pubmed_term(query, mesh_terms, date_range)

        try:
            pmids = await self._pubmed_esearch(term, max_results)
        except Exception as e:  # noqa: BLE001 — never raise into the agent loop
            self.logger.error("PubMed esearch failed: %s", e)
            return self._failure(
                query, source, "papers", "error", f"PubMed esearch failed: {e}"
            )

        if not pmids:
            return self._failure(
                query, source, "papers", "no_data",
                f"No PubMed records matched '{query}'",
            )

        # Space the two calls out to respect NCBI's documented rate limit.
        delay = _PUBMED_KEYED_DELAY if getattr(Entrez, "api_key", None) else _PUBMED_UNKEYED_DELAY
        await asyncio.sleep(delay)

        try:
            records = await self._pubmed_efetch(pmids)
        except Exception as e:  # noqa: BLE001 — never raise into the agent loop
            self.logger.error("PubMed efetch failed: %s", e)
            return self._failure(
                query, source, "papers", "error", f"PubMed efetch failed: {e}"
            )

        papers = [self._paper_from_pubmed_record(r) for r in records]
        first_url = (
            papers[0].url if papers and papers[0].url
            else "https://pubmed.ncbi.nlm.nih.gov/"
        )
        citation = self._build_citation(
            source_name=_PUBMED_SOURCE_NAME, source_url=first_url
        )
        result = ResearchResult(
            query=query, source=source, result_type="papers",
            status="success", total_results=len(papers),
            papers=papers, citation=citation,
        )
        await self._cache.set(
            "academic", "search_pubmed", result.model_dump(),
            ttl=_PUBMED_CACHE_TTL, **cache_params,
        )
        return result

    @staticmethod
    def _configure_entrez() -> None:
        """Set `Entrez.email` (required by NCBI) and optional `api_key`/`tool`."""
        Entrez.email = config.get("NCBI_EMAIL", fallback="noreply@example.com")
        api_key = config.get("NCBI_API_KEY", fallback=None)
        if api_key:
            Entrez.api_key = api_key
        Entrez.tool = "ai-parrot-research"

    @staticmethod
    def _build_pubmed_term(
        query: str, mesh_terms: str | None, date_range: str | None
    ) -> str:
        """Combine `query`/`mesh_terms`/`date_range` into a PubMed search term."""
        term = query
        if mesh_terms:
            term = f"{term} AND {mesh_terms}[MeSH Terms]"
        if date_range:
            parts = date_range.split("-")
            if len(parts) == 2:
                start, end = (p.strip() for p in parts)
                term = (
                    f'{term} AND ("{start}"[Date - Publication] : '
                    f'"{end}"[Date - Publication])'
                )
        return term

    async def _pubmed_esearch(self, term: str, max_results: int) -> list:
        """Resolve a PubMed search term to a list of PMIDs."""

        @backoff.on_exception(backoff.expo, Exception, max_tries=3)
        def _esearch():
            with Entrez.esearch(db="pubmed", term=term, retmax=max_results) as h:
                return Entrez.read(h)

        result = await self._run_sync_in_executor(_esearch)
        return list(result.get("IdList", []))

    async def _pubmed_efetch(self, pmids: list) -> list:
        """Fetch full PubMed records (XML) for a list of PMIDs."""

        @backoff.on_exception(backoff.expo, Exception, max_tries=3)
        def _efetch():
            with Entrez.efetch(db="pubmed", id=",".join(pmids), retmode="xml") as h:
                return Entrez.read(h)

        result = await self._run_sync_in_executor(_efetch)
        return list(result.get("PubmedArticle", []))

    def _paper_from_pubmed_record(self, record: dict) -> PaperResult:
        """Convert a raw PubMed `efetch` record into a `PaperResult`.

        `Abstract.AbstractText` may be a list of labelled parts — joined
        into a single string. DOI is resolved from `ArticleIdList` where
        `IdType == "doi"`.
        """
        citation_node = record.get("MedlineCitation", {}) or {}
        article = citation_node.get("Article", {}) or {}
        pmid = citation_node.get("PMID", "")

        title = str(article.get("ArticleTitle") or "Untitled article")

        authors = []
        for a in article.get("AuthorList", []) or []:
            name = " ".join(
                part for part in (a.get("ForeName"), a.get("LastName")) if part
            )
            if name:
                authors.append(name)

        abstract_parts = (article.get("Abstract") or {}).get("AbstractText") or []
        abstract = " ".join(str(p) for p in abstract_parts) if abstract_parts else None

        journal = (article.get("Journal") or {}).get("Title")

        doi = None
        for aid in (record.get("PubmedData") or {}).get("ArticleIdList", []) or []:
            if getattr(aid, "attributes", {}).get("IdType") == "doi":
                doi = str(aid)
                break

        return PaperResult(
            title=title,
            authors=authors,
            abstract=abstract,
            doi=doi,
            url=f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/" if pmid else None,
            journal=journal,
            source="pubmed",
        )

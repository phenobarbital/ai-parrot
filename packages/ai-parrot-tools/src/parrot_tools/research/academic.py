"""
AcademicResearchToolkit — direct access to free academic-literature APIs
(FEAT-426 Module 3: Crossref, PubMed, Semantic Scholar, arXiv;
`get_paper_details` is added by the tail task in this same module).

Crossref also covers Oxford Academic (OUP) content via DOI prefix
"10.1093" — OUP has no API of its own, so there is no separate Oxford
source anywhere in this feature. PubMed requires a mandatory two-step
`esearch` -> `efetch` workflow and NCBI's documented rate limits (3 req/s
unkeyed, 10 req/s with a free API key). Semantic Scholar requires an
explicit `fields=` parameter (the default response is title-only) and
rejects hyphenated query terms. arXiv search logic is a deliberate,
accepted-debt port of `parrot_tools.arxiv_tool.ArxivTool` — that module
is never imported or modified here so its plain-dict return shape stays
unchanged for backward compatibility. See spec §3 Module 3 and §7 "Known
Risks".
"""
import asyncio
import re
from urllib.error import URLError

import backoff
import requests
from navconfig import config
from parrot.tools.toolkit import AbstractToolkit

from .base import BaseResearchToolkit
from .models import PaperResult, ResearchResult

try:
    from habanero import Crossref
    from habanero.exceptions import RequestError as _CrossrefRequestError
except ImportError:
    Crossref = None
    _CrossrefRequestError = RuntimeError  # placeholder: unused, guarded by `Crossref is None`

try:
    # PyPI distribution is `biopython`; the importable module is `Bio`.
    from Bio import Entrez
except ImportError:
    Entrez = None

try:
    # Extra already exists: arxiv = ["arxiv>=3.0.0"] (pyproject.toml:79).
    import arxiv
except ImportError:
    arxiv = None

# Exception tuples for the @backoff.on_exception retry decorators below —
# each library's own transport/HTTP exception types, not bare `Exception`,
# so a retry never masks a genuine programming error (KeyError, ValueError,
# ...) as a transient failure worth retrying.
#
# - Crossref (habanero): raises its own `RequestError` for HTTP-status
#   errors, or wraps unexpected httpx errors in a bare `RuntimeError`
#   (habanero/request_class.py `_req()`).
# - PubMed (Bio.Entrez): `_open()` retries internally on `urllib.error.
#   HTTPError`/`URLError` and re-raises on final failure; `Entrez.read()`
#   raises `RuntimeError` for an NCBI-side `<ERROR>` in the response.
# - arXiv: `arxiv.Client()._parse_feed()` retries internally, then raises
#   `arxiv.ArxivError` (covers `HTTPError`/`UnexpectedEmptyPageError`) or
#   `requests.exceptions.ConnectionError` after giving up.
_CROSSREF_RETRYABLE_EXCEPTIONS = (_CrossrefRequestError, RuntimeError)
_PUBMED_RETRYABLE_EXCEPTIONS = (URLError, RuntimeError)
_ARXIV_RETRYABLE_EXCEPTIONS = (
    (arxiv.ArxivError, requests.exceptions.RequestException)
    if arxiv is not None else (RuntimeError,)
)

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

# Semantic Scholar: fields= is mandatory — the default response is only
# paperId+title. Free tier + optional SEMANTIC_SCHOLAR_API_KEY (raises
# limits, never required); sent as `x-api-key`, NOT `Authorization`.
_S2_SEARCH_URL = "https://api.semanticscholar.org/graph/v1/paper/search"
_S2_SOURCE_NAME = "Semantic Scholar"
_S2_FIELDS = (
    "title,abstract,authors,year,venue,citationCount,"
    "openAccessPdf,externalIds,fieldsOfStudy"
)
_S2_LIMIT_CAP = 100
_S2_CACHE_TTL = 86400

_ARXIV_SOURCE_NAME = "arXiv"
_ARXIV_MISSING_MESSAGE = (
    "arXiv support requires: pip install 'ai-parrot-tools[research]'"
)
_ARXIV_CACHE_TTL = 86400
_ARXIV_SORT_CRITERION_NAMES = {
    "relevance": "Relevance",
    "lastUpdatedDate": "LastUpdatedDate",
    "submittedDate": "SubmittedDate",
}

# get_paper_details: identifier-format detection (spec §3 Module 3 tail task).
_DOI_RE = re.compile(r"^10\.\d{4,9}/\S+$", re.IGNORECASE)
_PMID_RE = re.compile(r"^\d{6,9}$")
_ARXIV_ID_RE = re.compile(r"^(\d{4}\.\d{4,5}(v\d+)?|[a-z-]+(\.[A-Z]{2})?/\d{7})$", re.IGNORECASE)
_S2_ID_RE = re.compile(r"^[0-9a-f]{40}$", re.IGNORECASE)

# Semantic Scholar's own external-id prefixes (also usable as a shortcut
# for explicit source routing here).
_ID_PREFIX_SOURCES = {
    "DOI": "crossref",
    "PMID": "pubmed",
    "ARXIV": "arxiv",
    "CORPUSID": "semantic_scholar",
}
_VALID_DETAIL_SOURCES = ("crossref", "pubmed", "arxiv", "semantic_scholar")
_DETAILS_CACHE_TTL = 86400
_S2_PAPER_URL = "https://api.semanticscholar.org/graph/v1/paper/"
_SOURCE_DISPLAY_NAMES = {
    "crossref": _CROSSREF_SOURCE_NAME,
    "pubmed": _PUBMED_SOURCE_NAME,
    "arxiv": _ARXIV_SOURCE_NAME,
    "semantic_scholar": _S2_SOURCE_NAME,
}
_SOURCE_DEFAULT_URLS = {
    "crossref": "https://api.crossref.org/works",
    "pubmed": "https://pubmed.ncbi.nlm.nih.gov/",
    "arxiv": "https://arxiv.org",
    "semantic_scholar": "https://www.semanticscholar.org/search",
}


class AcademicResearchToolkit(BaseResearchToolkit, AbstractToolkit):
    """Direct, structured access to authoritative academic-literature sources.

    Covers Crossref (full-text bibliographic search, also reaching Oxford
    Academic content via DOI prefix "10.1093"), PubMed (two-step
    `esearch`/`efetch` biomedical literature search), Semantic Scholar
    (aiohttp full-text search), arXiv (preprint search), and
    `get_paper_details` (single-paper lookup dispatching across all four
    by identifier format). Spec §3 Module 3.
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

    def _crossref_filters(self, year_range: str | None) -> dict | None:
        """Build a Crossref `filter=` dict for a "YYYY-YYYY" year range.

        A malformed `year_range` (wrong shape, non-numeric parts) is not
        silently dropped: it is logged as a warning so the caller can see
        why no date filter was applied, then the search proceeds
        unfiltered rather than failing the whole request.
        """
        if not year_range:
            return None
        parts = year_range.split("-")
        if len(parts) == 2 and all(p.strip().isdigit() for p in parts):
            start, end = (p.strip() for p in parts)
            return {
                "from-pub-date": f"{start}-01-01",
                "until-pub-date": f"{end}-12-31",
            }
        self.logger.warning(
            "Crossref: malformed year_range %r (expected \"YYYY-YYYY\") — "
            "searching without a date filter", year_range,
        )
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

        @backoff.on_exception(backoff.expo, _CROSSREF_RETRYABLE_EXCEPTIONS, max_tries=3)
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

        @backoff.on_exception(backoff.expo, _PUBMED_RETRYABLE_EXCEPTIONS, max_tries=3)
        def _esearch():
            with Entrez.esearch(db="pubmed", term=term, retmax=max_results) as h:
                return Entrez.read(h)

        result = await self._run_sync_in_executor(_esearch)
        return list(result.get("IdList", []))

    async def _pubmed_efetch(self, pmids: list) -> list:
        """Fetch full PubMed records (XML) for a list of PMIDs."""

        @backoff.on_exception(backoff.expo, _PUBMED_RETRYABLE_EXCEPTIONS, max_tries=3)
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

    async def search_semantic_scholar(
        self,
        query: str,
        fields_of_study: str | None = None,
        year: str | None = None,
        open_access_only: bool = False,
        max_results: int = 10,
    ) -> ResearchResult:
        """Search Semantic Scholar for scholarly papers.

        Sends an explicit `fields=` parameter — the default response is
        only `paperId`+`title`. Hyphenated query terms return zero matches
        and are rewritten to spaces. The unauthenticated pool is shared
        globally, so 429s are common; `_make_api_request` already retries
        with backoff. An optional free `SEMANTIC_SCHOLAR_API_KEY` raises
        rate limits but is never required.

        Args:
            query: Free-text search query.
            fields_of_study: Optional comma-separated field-of-study filter
                (e.g. "Computer Science,Medicine").
            year: Optional publication year or range, e.g. "2020-2023".
            open_access_only: When True, keep only papers with an open
                access PDF.
            max_results: Maximum number of papers to return (server caps
                `limit` at 100 per page).

        Returns:
            A `ResearchResult` with `result_type="papers"`.
        """
        source = "academic.search_semantic_scholar"
        cache_params = {
            "query": query, "fields_of_study": fields_of_study, "year": year,
            "open_access_only": open_access_only, "max_results": max_results,
        }
        cached = await self._cache.get(
            "academic", "search_semantic_scholar", **cache_params
        )
        if cached is not None:
            return ResearchResult(**cached)

        # Hyphens kill matching — rewrite to spaces before sending.
        params = {
            "query": query.replace("-", " "),
            "fields": _S2_FIELDS,
            "limit": min(max_results, _S2_LIMIT_CAP),
        }
        if fields_of_study:
            params["fieldsOfStudy"] = fields_of_study
        if year:
            params["year"] = year

        headers = {}
        api_key = config.get("SEMANTIC_SCHOLAR_API_KEY", fallback=None)
        if api_key:
            headers["x-api-key"] = api_key

        payload, err = await self._make_api_request(
            _S2_SEARCH_URL, params=params, headers=headers
        )
        if err:
            return self._failure(query, source, "papers", "error", err)

        items = (payload or {}).get("data", [])
        if open_access_only:
            items = [i for i in items if i.get("openAccessPdf")]
        if not items:
            return self._failure(
                query, source, "papers", "no_data",
                f"No Semantic Scholar papers matched '{query}'",
            )

        papers = [self._paper_from_s2_item(item) for item in items[:max_results]]
        citation = self._build_citation(
            source_name=_S2_SOURCE_NAME,
            source_url="https://www.semanticscholar.org/search",
        )
        result = ResearchResult(
            query=query, source=source, result_type="papers",
            status="success", total_results=len(papers),
            papers=papers, citation=citation,
        )
        await self._cache.set(
            "academic", "search_semantic_scholar", result.model_dump(),
            ttl=_S2_CACHE_TTL, **cache_params,
        )
        return result

    def _paper_from_s2_item(self, item: dict) -> PaperResult:
        """Convert a raw Semantic Scholar `/paper/search` item into a `PaperResult`."""
        authors = [
            a.get("name") for a in (item.get("authors") or []) if a.get("name")
        ]
        external_ids = item.get("externalIds") or {}
        open_access_pdf = item.get("openAccessPdf")

        return PaperResult(
            title=item.get("title") or "Untitled paper",
            authors=authors,
            abstract=item.get("abstract"),
            published_date=str(item["year"]) if item.get("year") else None,
            doi=external_ids.get("DOI"),
            url=(open_access_pdf or {}).get("url"),
            journal=item.get("venue") or None,
            citation_count=item.get("citationCount"),
            fields_of_study=item.get("fieldsOfStudy"),
            open_access=bool(open_access_pdf),
            source="semantic_scholar",
        )

    async def search_arxiv(
        self,
        query: str,
        max_results: int = 10,
        sort_by: str = "relevance",
        category: str | None = None,
    ) -> ResearchResult:
        """Search arXiv for preprints.

        Ported from `parrot_tools.arxiv_tool.ArxivTool`'s mapping logic —
        that module is never imported or modified here, so its plain-dict
        return shape stays unchanged for backward compatibility (accepted
        duplication, see spec §7).

        Args:
            query: arXiv query string (keywords, `au:`, `cat:`, ...).
            max_results: Maximum number of results.
            sort_by: 'relevance' | 'lastUpdatedDate' | 'submittedDate'.
            category: Optional arXiv category to prefix the query with
                (`cat:<category> AND <query>`).

        Returns:
            A `ResearchResult` with `result_type="papers"`.
        """
        source = "academic.search_arxiv"
        if arxiv is None:
            return self._failure(
                query, source, "papers", "error", _ARXIV_MISSING_MESSAGE
            )

        cache_params = {
            "query": query, "max_results": max_results,
            "sort_by": sort_by, "category": category,
        }
        cached = await self._cache.get("academic", "search_arxiv", **cache_params)
        if cached is not None:
            return ResearchResult(**cached)

        full_query = f"cat:{category} AND {query}" if category else query

        try:
            results = await self._fetch_arxiv_results(
                full_query, max_results, sort_by
            )
        except Exception as e:  # noqa: BLE001 — never raise into the agent loop
            self.logger.error("arXiv search failed: %s", e)
            return self._failure(
                query, source, "papers", "error", f"arXiv search failed: {e}"
            )

        if not results:
            return self._failure(
                query, source, "papers", "no_data",
                f"No arXiv results for '{query}'",
            )

        papers = [self._paper_from_arxiv_result(p) for p in results]
        citation = self._build_citation(
            source_name=_ARXIV_SOURCE_NAME, source_url="https://arxiv.org"
        )
        result = ResearchResult(
            query=query, source=source, result_type="papers",
            status="success", total_results=len(papers),
            papers=papers, citation=citation,
        )
        await self._cache.set(
            "academic", "search_arxiv", result.model_dump(),
            ttl=_ARXIV_CACHE_TTL, **cache_params,
        )
        return result

    async def _fetch_arxiv_results(
        self, query: str, max_results: int, sort_by: str
    ) -> list:
        """Run the blocking `arxiv.Client().results()` call in an executor."""
        criterion_name = _ARXIV_SORT_CRITERION_NAMES.get(sort_by, "Relevance")
        sort_criterion = getattr(arxiv.SortCriterion, criterion_name)

        @backoff.on_exception(backoff.expo, _ARXIV_RETRYABLE_EXCEPTIONS, max_tries=3)
        def _fetch():
            search = arxiv.Search(
                query=query,
                max_results=max_results,
                sort_by=sort_criterion,
                sort_order=arxiv.SortOrder.Descending,
            )
            return list(arxiv.Client().results(search))

        return await self._run_sync_in_executor(_fetch)

    def _paper_from_arxiv_result(self, paper) -> PaperResult:
        """Convert an `arxiv.Result` into a `PaperResult`.

        Mirrors `ArxivTool._format_paper()` field-for-field, but produces
        a `PaperResult` instead of a plain dict.
        """
        published = getattr(paper, "published", None)
        published_date = published.strftime("%Y-%m-%d") if published else None
        summary = getattr(paper, "summary", None)

        return PaperResult(
            title=paper.title,
            authors=[a.name for a in getattr(paper, "authors", [])],
            abstract=summary.replace("\n", " ").strip() if summary else None,
            published_date=published_date,
            url=getattr(paper, "pdf_url", None),
            fields_of_study=list(getattr(paper, "categories", []) or []) or None,
            source="arxiv",
            journal=None,
            doi=None,
        )

    async def get_paper_details(
        self,
        doi_or_id: str,
        source: str | None = None,
    ) -> ResearchResult:
        """Resolve a single paper by identifier, across all four sources.

        Accepts a DOI (e.g. "10.1093/nar/gkaa1100" — also reaching Oxford
        Academic content via Crossref), a PubMed PMID, an arXiv id (e.g.
        "2103.14030"), or a Semantic Scholar paperId (40-char hex).
        Prefixed forms ("DOI:...", "PMID:...", "ARXIV:...",
        "CorpusID:...") are also accepted. The source is auto-detected
        from the identifier's shape unless `source` is given explicitly,
        which always overrides detection.

        Args:
            doi_or_id: A DOI, PMID, arXiv id, or Semantic Scholar paperId.
            source: Optional explicit source — one of "crossref",
                "pubmed", "arxiv", "semantic_scholar".

        Returns:
            A `ResearchResult` with `result_type="papers"` containing
            exactly one entry in `.papers` on success.
        """
        method_source = "academic.get_paper_details"

        if source is not None and source not in _VALID_DETAIL_SOURCES:
            return self._failure(
                doi_or_id, method_source, "papers", "error",
                f"Invalid source '{source}'. Valid options: "
                f"{', '.join(_VALID_DETAIL_SOURCES)}",
            )

        ident = self._strip_id_prefix(doi_or_id)
        resolved_source = source or self._detect_source(doi_or_id)
        if resolved_source is None:
            return self._failure(
                doi_or_id, method_source, "papers", "error",
                "Unrecognised identifier — expected a DOI (10.xxxx/...), "
                "PubMed PMID, arXiv id (e.g. 2103.14030), or a Semantic "
                "Scholar paperId (40-char hex).",
            )

        cache_params = {"doi_or_id": doi_or_id, "source": source}
        cached = await self._cache.get(
            "academic", "get_paper_details", **cache_params
        )
        if cached is not None:
            return ResearchResult(**cached)

        try:
            paper = await self._resolve_paper(resolved_source, ident)
        except Exception as e:  # noqa: BLE001 — never raise into the agent loop
            self.logger.error(
                "get_paper_details failed for %s: %s", doi_or_id, e
            )
            return self._failure(
                doi_or_id, method_source, "papers", "error",
                f"Paper lookup failed: {e}",
            )

        if paper is None:
            return self._failure(
                doi_or_id, method_source, "papers", "no_data",
                f"No paper found for '{doi_or_id}'",
            )

        citation = self._build_citation(
            source_name=_SOURCE_DISPLAY_NAMES[resolved_source],
            source_url=paper.url or _SOURCE_DEFAULT_URLS[resolved_source],
            doi=paper.doi,
        )
        result = ResearchResult(
            query=doi_or_id, source=method_source, result_type="papers",
            status="success", total_results=1, papers=[paper], citation=citation,
        )
        await self._cache.set(
            "academic", "get_paper_details", result.model_dump(),
            ttl=_DETAILS_CACHE_TTL, **cache_params,
        )
        return result

    @staticmethod
    def _strip_id_prefix(ident: str) -> str:
        """Strip a Semantic-Scholar-style 'DOI:'/'PMID:'/'ARXIV:'/'CorpusID:' prefix."""
        if ":" in ident:
            prefix, _, rest = ident.partition(":")
            if prefix.strip().upper() in _ID_PREFIX_SOURCES:
                return rest.strip()
        return ident

    def _detect_source(self, ident: str) -> str | None:
        """Return 'crossref' | 'pubmed' | 'arxiv' | 'semantic_scholar' | None."""
        if ":" in ident:
            prefix, _, _rest = ident.partition(":")
            mapped = _ID_PREFIX_SOURCES.get(prefix.strip().upper())
            if mapped:
                return mapped

        bare = self._strip_id_prefix(ident)
        if _DOI_RE.match(bare):
            return "crossref"
        if _PMID_RE.match(bare):
            return "pubmed"
        if _ARXIV_ID_RE.match(bare):
            return "arxiv"
        if _S2_ID_RE.match(bare):
            return "semantic_scholar"
        return None

    async def _resolve_paper(self, resolved_source: str, ident: str) -> PaperResult | None:
        """Dispatch to the per-source single-paper lookup."""
        if resolved_source == "crossref":
            return await self._get_crossref_paper(ident)
        if resolved_source == "pubmed":
            return await self._get_pubmed_paper(ident)
        if resolved_source == "arxiv":
            return await self._get_arxiv_paper(ident)
        if resolved_source == "semantic_scholar":
            return await self._get_s2_paper(ident)
        return None

    async def _get_crossref_paper(self, doi: str) -> PaperResult | None:
        """Look up a single Crossref work by DOI."""
        if Crossref is None:
            raise RuntimeError(_CROSSREF_MISSING_MESSAGE)

        mailto = config.get("CROSSREF_MAILTO", fallback="noreply@example.com")

        @backoff.on_exception(backoff.expo, _CROSSREF_RETRYABLE_EXCEPTIONS, max_tries=3)
        def _fetch():
            cr = Crossref(mailto=mailto)
            return cr.works(ids=doi)

        payload = await self._run_sync_in_executor(_fetch)
        item = (payload or {}).get("message")
        if not item:
            return None
        return self._paper_from_item(item)

    async def _get_pubmed_paper(self, pmid: str) -> PaperResult | None:
        """Look up a single PubMed record by PMID (skips `esearch`)."""
        if Entrez is None:
            raise RuntimeError(_PUBMED_MISSING_MESSAGE)

        self._configure_entrez()
        records = await self._pubmed_efetch([pmid])
        if not records:
            return None
        return self._paper_from_pubmed_record(records[0])

    async def _get_arxiv_paper(self, arxiv_id: str) -> PaperResult | None:
        """Look up a single arXiv paper by id via `arxiv.Search(id_list=...)`."""
        if arxiv is None:
            raise RuntimeError(_ARXIV_MISSING_MESSAGE)

        @backoff.on_exception(backoff.expo, _ARXIV_RETRYABLE_EXCEPTIONS, max_tries=3)
        def _fetch():
            search = arxiv.Search(id_list=[arxiv_id])
            return list(arxiv.Client().results(search))

        results = await self._run_sync_in_executor(_fetch)
        if not results:
            return None
        return self._paper_from_arxiv_result(results[0])

    async def _get_s2_paper(self, paper_id: str) -> PaperResult | None:
        """Look up a single Semantic Scholar paper via `/paper/{paper_id}`."""
        params = {"fields": _S2_FIELDS}
        headers = {}
        api_key = config.get("SEMANTIC_SCHOLAR_API_KEY", fallback=None)
        if api_key:
            headers["x-api-key"] = api_key

        payload, err = await self._make_api_request(
            f"{_S2_PAPER_URL}{paper_id}", params=params, headers=headers
        )
        if err:
            raise RuntimeError(err)
        if not payload:
            return None
        return self._paper_from_s2_item(payload)

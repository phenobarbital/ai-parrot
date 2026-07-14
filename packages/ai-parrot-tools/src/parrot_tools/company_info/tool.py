"""
CompanyInfoToolkit - Unified toolkit for scraping company information from multiple sources.

This toolkit extends AbstractToolkit and provides methods to scrape company data from:
- explorium.ai
- leadiq.com
- rocketreach.co
- siccode.com
- zoominfo.com

Each public async method becomes a tool that:
1. Searches for the company (DDG-first, Google CSE fallback; see
   `_search_company_url`)
2. Fetches the first validated result via the Playwright driver stack
   (`driver_context` + `DriverConfig(driver_type="playwright")`)
3. Parses the page with BeautifulSoup
4. Extracts company information
5. Returns structured data (CompanyInfo model or JSON)

Dependencies:
    - playwright (fetch layer; scraping extra)
    - rapidfuzz (fuzzy company-name validation; scraping extra)
    - ddgs (DDG-first search)
    - beautifulsoup4
    - pydantic
    - google-api-python-client
    - aiohttp

Example usage:
    toolkit = CompanyInfoToolkit(
        google_api_key="your-api-key",
        google_cse_id="your-cse-id",
        use_proxy=False,
        headless=True
    )

    # Get all tools
    tools = toolkit.get_tools()

    # Or use methods directly
    result = await toolkit.scrape_zoominfo("PetSmart")
    print(result.company_name)
"""
from __future__ import annotations

import asyncio
import json
import re
import time
from typing import Dict, List, Any, Optional, Union
from urllib.parse import urlparse
import backoff
from bs4 import BeautifulSoup as bs
from ddgs import DDGS
from ddgs.exceptions import RatelimitException
from rapidfuzz import fuzz
from pydantic import BaseModel, Field
from googleapiclient.discovery import build
from navconfig import config
from navconfig.logging import logging

from ..toolkit import AbstractToolkit
from ..decorators import tool_schema
from ..scraping.driver_context import driver_context
from ..scraping.toolkit_models import DriverConfig


# ===========================
# Pydantic Models
# ===========================

class CompanyInput(BaseModel):
    """Input model for company scraping tools."""
    company_name: str = Field(..., description="Name of the company to search for")
    return_json: bool = Field(
        False,
        description="If True, return JSON string instead of CompanyInfo object"
    )


class ResearchCompanyInput(BaseModel):
    """Input model for the `research_company` aggregate tool."""
    company_name: str = Field(..., description="Name of the company to research")
    sources: Optional[List[str]] = Field(
        None,
        description="Optional subset/order of source names to try (defaults "
        "to the full priority order: leadiq, rocketreach, explorium, "
        "siccode, visualvisitor, zoominfo)"
    )
    return_json: bool = Field(
        False,
        description="If True, return JSON string instead of CompanyInfo object"
    )


class CompanyInfo(BaseModel):
    """
    Structured output model for company information.
    Homogenized across all scraping platforms.
    """
    # Search metadata
    search_term: Optional[str] = Field(None, description="Search term used")
    search_url: Optional[str] = Field(None, description="URL of the scraped page")
    source_platform: Optional[str] = Field(None, description="Source platform (e.g., zoominfo, leadiq)")
    scrape_status: str = Field("pending", description="Status: pending, success, no_data, error")

    # Company basic info
    company_name: Optional[str] = Field(None, description="Company name")
    logo_url: Optional[str] = Field(None, description="Company logo URL")
    company_description: Optional[str] = Field(None, description="Company description")

    # Location info
    headquarters: Optional[str] = Field(None, description="Headquarters address")
    address: Optional[str] = Field(None, description="Street address")
    city: Optional[str] = Field(None, description="City")
    state: Optional[str] = Field(None, description="State/Province")
    zip_code: Optional[str] = Field(None, description="ZIP/Postal code")
    country: Optional[str] = Field(None, description="Country")
    metro_area: Optional[str] = Field(None, description="Metro area")

    # Contact info
    phone_number: Optional[str] = Field(None, description="Phone number")
    website: Optional[str] = Field(None, description="Company website")

    # Business classification
    industry: Optional[Union[str, List[str]]] = Field(None, description="Industry")
    industry_category: Optional[str] = Field(None, description="Industry category")
    category: Optional[str] = Field(None, description="Business category")
    keywords: Optional[List[str]] = Field(None, description="Business keywords")
    naics_code: Optional[str] = Field(None, description="NAICS code(s)")
    sic_code: Optional[str] = Field(None, description="SIC code(s)")

    # Financial & size info
    stock_symbol: Optional[str] = Field(None, description="Stock ticker symbol")
    revenue_range: Optional[str] = Field(None, description="Revenue range")
    employee_count: Optional[str] = Field(None, description="Number of employees")
    number_employees: Optional[str] = Field(None, description="Employee count description")
    company_size: Optional[str] = Field(None, description="Company size category")
    founded: Optional[str] = Field(None, description="Year founded")
    funding: Optional[str] = Field(None, description="Funding information")
    years_in_business: Optional[str] = Field(None, description="Years in business")

    # Additional info
    executives: Optional[List[Dict[str, str]]] = Field(None, description="Executive team")
    similar_companies: Optional[Union[str, List[Dict]]] = Field(None, description="Similar companies")
    social_media: Optional[Dict[str, str]] = Field(None, description="Social media links")

    # Metadata
    timestamp: Optional[str] = Field(None, description="Scrape timestamp")
    error_message: Optional[str] = Field(None, description="Error message if any")

    def to_json(self, **kwargs) -> str:
        """Convert to JSON string."""
        return self.model_dump_json(exclude_none=True, **kwargs)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CompanyInfo":
        """Create from dictionary."""
        return cls(**data)


class GoogleSearchResult(BaseModel):
    """Result from Google site search."""
    query: str = Field(description="Search query used")
    site: str = Field(description="Site searched")
    url: Optional[str] = Field(None, description="First result URL")
    title: Optional[str] = Field(None, description="Result title")
    snippet: Optional[str] = Field(None, description="Result snippet")
    total_results: int = Field(0, description="Total results found")


class SourceConfig(BaseModel):
    """
    Internal per-source search configuration.

    NOT a tool schema — used by `_search_company_url`/`_validate_search_hit`
    to know how to search and validate hits for a given source. Templates and
    title keywords are ported from flowtask's `CompanyScraper` parsers.
    """
    name: str = Field(description="Source identifier (e.g. 'leadiq')")
    site: str = Field(description="Site domain to search within (e.g. 'leadiq.com')")
    search_template: str = Field(
        description="DDG/Google search query template with a single '{}' "
        "placeholder for the (standardized) company name, e.g. 'site:leadiq.com {}'"
    )
    title_keywords: List[str] = Field(
        description="Title keywords used to locate/validate the company-name "
        "portion of a search-result title for this source"
    )


# Registry of all 6 supported sources, ported from flowtask's per-source
# parsers (parsers/leadiq.py, rocket.py, explorium.py, siccode.py,
# visualvisitor.py, zoominfo.py). Keyed by source name; used by
# `_search_company_url` and (eventually) `research_company`'s priority loop.
COMPANY_SOURCES: Dict[str, SourceConfig] = {
    "leadiq": SourceConfig(
        name="leadiq",
        site="leadiq.com",
        search_template="site:leadiq.com {}",
        title_keywords=[
            "Email Formats & Email Address",
            "Company Overview",
            "Employee Directory",
            "Contact Details & Competitors",
            "Email Format",
        ],
    ),
    "rocketreach": SourceConfig(
        name="rocketreach",
        site="rocketreach.co",
        search_template="site:rocketreach.co '{}'",
        title_keywords=[
            " Information",
            " Information - ",
            " Information - RocketReach",
            ": Contact Details",
        ],
    ),
    "explorium": SourceConfig(
        name="explorium",
        site="explorium.ai",
        search_template="site:explorium.ai {}",
        title_keywords=["overview - services"],
    ),
    "siccode": SourceConfig(
        name="siccode",
        site="siccode.com",
        search_template="site:siccode.com '{}' +NAICS",
        title_keywords=[" - ZIP", " - ZIP "],
    ),
    "visualvisitor": SourceConfig(
        name="visualvisitor",
        site="visualvisitor.com",
        search_template="site:visualvisitor.com '{}'",
        title_keywords=[" Phone", " - Phone"],
    ),
    "zoominfo": SourceConfig(
        name="zoominfo",
        site="zoominfo.com",
        search_template="site:zoominfo.com {} Overview",
        title_keywords=[" - Overview, News", "Overview, News"],
    ),
}


# Default priority order for `research_company`'s first-success loop: cheap,
# HTTP-friendly sources first, browser-heavy ZoomInfo last (spec §2).
DEFAULT_SOURCE_PRIORITY: List[str] = [
    "leadiq", "rocketreach", "explorium", "siccode", "visualvisitor", "zoominfo"
]


# ===========================
# Main Toolkit Class
# ===========================

class CompanyInfoToolkit(AbstractToolkit):
    """
    Toolkit for scraping company information from multiple platforms.

    Each public async method is automatically converted to a tool by AbstractToolkit.
    Methods perform:
    1. Google site search for company
    2. Selenium page fetch
    3. BeautifulSoup parsing
    4. Structured data extraction
    """

    def __init__(
        self,
        google_api_key: Optional[str] = None,
        google_cse_id: Optional[str] = None,
        browser: str = 'chrome',
        headless: bool = True,
        timeout: int = 30,
        auto_install: bool = True,
        mobile: bool = False,
        mobile_device: Optional[str] = None,
        use_undetected: bool = False,
        custom_user_agent: Optional[str] = None,
        **kwargs
    ):
        """
        Initialize the CompanyInfoToolkit.

        Args:
            google_api_key: Google Custom Search API key
            google_cse_id: Google Custom Search Engine ID
            browser: Browser type ('chrome', 'firefox', 'edge', 'safari',
                'undetected', 'webkit'). Mapped onto `DriverConfig.browser`
                for the Playwright fetch layer ('undetected' has no
                Playwright equivalent; see `use_undetected`).
            headless: Run browser in headless mode. Mapped onto
                `DriverConfig.headless`.
            timeout: Default timeout for page loads (seconds). Mapped onto
                `DriverConfig.default_timeout`.
            auto_install: Auto-install webdriver if not found. Mapped onto
                `DriverConfig.auto_install`.
            mobile: Enable mobile emulation. Mapped onto `DriverConfig.mobile`.
            mobile_device: Specific mobile device to emulate. Mapped onto
                `DriverConfig.mobile_device`.
            use_undetected: Deprecated. Legacy Selenium-only
                undetected-chromedriver flag, kept for back-compat; it has
                no effect on the Playwright fetch layer (logs a deprecation
                warning instead of being applied).
            custom_user_agent: Optional custom User-Agent string used for
                headless-hardening (e.g. ZoomInfo). Mapped onto
                `DriverConfig.custom_user_agent`.
            **kwargs: Additional arguments passed to `AbstractToolkit`.
        """
        super().__init__(**kwargs)

        # Google Search configuration
        self.google_api_key = google_api_key or config.get('GOOGLE_SEARCH_API_KEY')
        self.google_cse_id = google_cse_id or config.get('GOOGLE_SEARCH_ENGINE_ID')
        # Service Selection:
        self.service = build("customsearch", "v1", developerKey=self.google_api_key)

        # Logger
        self.logger = logging.getLogger(self.__class__.__name__)

        if use_undetected:
            self.logger.warning(
                "CompanyInfoToolkit(use_undetected=True) is deprecated: it "
                "was a Selenium-only undetected-chromedriver flag with no "
                "Playwright equivalent and has no effect on the current "
                "driver_context/Playwright fetch layer."
            )

        if browser == 'undetected':
            self.logger.warning(
                "CompanyInfoToolkit(browser='undetected') has no Playwright "
                "equivalent: DriverConfig.browser is passed through as a "
                "Playwright `browser_type`, and 'undetected' is not a valid "
                "value, so every _fetch_page call will fail (degrading to "
                "scrape_status='error'/'no_data'). Use browser='chrome' "
                "(mapped to Chromium) or another supported value instead."
            )

        # Browser configuration mapped onto the scraping stack's DriverConfig
        # (replaces the legacy SeleniumSetup-based `browser_config` dict).
        self._driver_config = DriverConfig(
            driver_type="playwright",
            browser=browser,
            headless=headless,
            mobile=mobile,
            mobile_device=mobile_device,
            auto_install=auto_install,
            default_timeout=timeout,
            custom_user_agent=custom_user_agent,
        )

    # ===========================
    # Core Utility Methods
    # ===========================
    async def _close_driver(self) -> None:
        """
        No-op kept for back-compat.

        The Playwright fetch layer (`_fetch_page`) creates and tears down a
        fresh browser per call via `driver_context`, so there is no
        persistent driver instance to close anymore. Existing
        `finally: await self._close_driver()` call sites keep working
        unchanged.
        """
        return None

    async def _google_site_search(
        self,
        company_name: str,
        site: str,
        additional_terms: str = "",
        max_results: int = 5
    ) -> GoogleSearchResult:
        """
        Perform Google site search for a company.

        Args:
            company_name: Company name to search for
            site: Site domain to search within (e.g., "zoominfo.com")
            additional_terms: Additional search terms (e.g., "Overview")
            max_results: Maximum number of results

        Returns:
            GoogleSearchResult with first result URL
        """
        # Build search query
        query = f"{company_name} {additional_terms}".strip()
        search_query = f"site:{site} {query}"

        self.logger.info(f"Google search: {search_query}")

        try:
            # Execute search
            loop = asyncio.get_running_loop()
            res = await loop.run_in_executor(
                None,
                lambda: self.service.cse().list(  # pylint: disable=E1101  # noqa
                    q=search_query,
                    cx=self.google_cse_id,
                    num=max_results
                ).execute()
            )

            items = res.get('items', [])

            if not items:
                self.logger.warning(
                    f"No results found for: {search_query}"
                )
                return GoogleSearchResult(
                    query=query,
                    site=site,
                    total_results=0
                )

            # Return first result
            first = items[0]
            return GoogleSearchResult(
                query=query,
                site=site,
                url=first['link'],
                title=first.get('title'),
                snippet=first.get('snippet'),
                total_results=len(items)
            )

        except Exception as e:
            self.logger.error(f"Google search error: {e}")
            return GoogleSearchResult(
                query=query,
                site=site,
                total_results=0
            )

    # ===========================
    # Search layer: DDG-first + validation (FEAT-305)
    # ===========================

    @backoff.on_exception(backoff.expo, RatelimitException, max_tries=3)
    async def _ddg_search(
        self,
        query: str,
        max_results: int = 5
    ) -> List[Dict[str, Any]]:
        """
        Run a DuckDuckGo text search, retrying with backoff on rate limits.

        Mirrors `ddgo.py`'s pattern: the sync `ddgs.DDGS` client is run in an
        executor so the event loop is never blocked.

        Args:
            query: Search query string.
            max_results: Maximum number of results to request.

        Returns:
            List of raw DDG hit dictionaries (each with `title`/`href`/`body`).

        Raises:
            RatelimitException: propagated after `max_tries` backoff attempts
                are exhausted, so the caller can fall back to Google CSE.
        """
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None,
            lambda: list(DDGS().text(query, max_results=max_results))
        )

    def _clean_search_url(self, url: str) -> str:
        """
        Strip noisy suffixes from a candidate search-result URL.

        Mirrors flowtask's URL cleanup (scrapper.py:919-922): search hits
        sometimes point at a sub-page (employee directory, email format)
        instead of the company's main profile page.

        Args:
            url: Raw candidate URL.

        Returns:
            The cleaned URL.
        """
        if '/employee-directory' in url:
            url = url.replace('/employee-directory', '')
        elif '/email-format' in url:
            url = url.replace('/email-format', '')
        return url

    def _validate_search_hit(
        self,
        title: str,
        url: str,
        company_name: str,
        keywords: List[str],
        site: Optional[str] = None
    ) -> bool:
        """
        Validate a search hit before it is accepted for scraping.

        Mirrors flowtask's `_check_company_name` (scrapper.py:741-770): the
        result `title` must contain at least one of `keywords`; the portion
        of the title preceding that keyword match is then compared against
        `company_name` via exact match, first-token match, or `rapidfuzz`
        fuzzy ratio (accepted when strictly greater than 85).

        Before any title/name comparison, `url`'s host is checked against
        `site` (when provided): a hit whose title happens to match but that
        points at a host outside the expected source domain is rejected.
        This closes a gap where a DDG/Google CSE result could otherwise
        pass keyword+fuzzy validation while pointing at an arbitrary,
        untrusted host that Playwright would then navigate to and fetch.

        Args:
            title: Search-result title.
            url: Search-result URL. Its host must match `site` (or a
                subdomain of it) when `site` is given.
            company_name: The company name being searched for.
            keywords: Title keywords for the source being validated.
            site: Expected site domain for this source (e.g. 'leadiq.com').
                When omitted, no domain check is performed (back-compat for
                direct callers that already trust `url`).

        Returns:
            True if the hit is considered a valid match for `company_name`.
        """
        if not title or not keywords or not url:
            return False

        if site:
            host = (urlparse(url).netloc or '').lower().split('@')[-1].split(':')[0]
            expected = site.lower()
            if host != expected and not host.endswith('.' + expected):
                return False

        pattern = r'\b(' + '|'.join(re.escape(kw) for kw in keywords) + r')\b'
        match = re.search(pattern, title, re.IGNORECASE)
        if not match:
            return False

        candidate = title[:match.start()].strip()
        if not candidate:
            return False

        company = company_name.strip()

        # 1. Exact match
        if company.lower() == candidate.lower():
            return True

        # 2. First-token match
        company_tokens = company.split()
        candidate_tokens = candidate.split()
        if company_tokens and candidate_tokens:
            if company_tokens[0].lower() == candidate_tokens[0].lower():
                return True

        # 3. Fuzzy match (strictly > 85, per flowtask semantics)
        score = fuzz.ratio(company.lower(), candidate.lower())
        return score > 85

    async def _search_company_url(
        self,
        company_name: str,
        site_config: SourceConfig
    ) -> Optional[str]:
        """
        Resolve the first validated result URL for a company on a source.

        DDG-first strategy (G3): tries `ddgs.DDGS` first (free, no quota);
        falls back to the existing `_google_site_search` (quota-billed) when
        DDG fails or is rate-limited. Every candidate hit — from either
        engine — is validated via `_validate_search_hit` (G4) before being
        accepted, and accepted URLs are cleaned via `_clean_search_url`.

        Args:
            company_name: Company name to search for.
            site_config: `SourceConfig` describing the target source.

        Returns:
            The first validated, cleaned candidate URL, or `None` if no
            validated hit was found via either engine.
        """
        query = site_config.search_template.format(company_name)

        try:
            hits = await self._ddg_search(query, max_results=5)
            for hit in hits:
                title = hit.get('title') or ''
                hit_url = hit.get('href') or hit.get('url') or ''
                if not hit_url:
                    continue
                if self._validate_search_hit(
                    title, hit_url, company_name, site_config.title_keywords,
                    site=site_config.site
                ):
                    return self._clean_search_url(hit_url)
        except Exception as e:
            self.logger.warning(f"DDG search failed for '{query}': {e}")

        # Fallback: Google CSE (costs quota — log at INFO)
        self.logger.info(
            f"Falling back to Google CSE for '{query}' (source={site_config.name})"
        )
        try:
            search_result = await self._google_site_search(
                company_name=company_name,
                site=site_config.site
            )
            if search_result.url and self._validate_search_hit(
                search_result.title or '',
                search_result.url,
                company_name,
                site_config.title_keywords,
                site=site_config.site
            ):
                return self._clean_search_url(search_result.url)
        except Exception as e:
            self.logger.error(f"Google CSE fallback failed for '{query}': {e}")

        return None

    async def _fetch_page(
        self,
        url: str,
        custom_user_agent: Optional[str] = None
    ) -> Optional[bs]:
        """
        Fetch a page via the Playwright driver stack and parse it with BeautifulSoup.

        Uses the shared scraping-stack lifecycle (`driver_context` +
        `DriverConfig(driver_type="playwright")`), replacing the previous
        direct Selenium usage. A fresh browser instance is created and torn
        down per fetch (mirrors `scraping/toolkit.py:750`).

        Args:
            url: URL to fetch.
            custom_user_agent: Optional per-call User-Agent override (e.g.
                ZoomInfo's headless-hardening). Defaults to the toolkit's
                `_driver_config.custom_user_agent` when not provided.

        Returns:
            BeautifulSoup object, or None if the fetch failed.
        """
        driver_config = self._driver_config
        if custom_user_agent:
            driver_config = driver_config.merge({"custom_user_agent": custom_user_agent})

        try:
            self.logger.info(f"Fetching URL via Playwright: {url}")
            async with driver_context(driver_config) as drv:
                await drv.navigate(url, timeout=driver_config.default_timeout)
                page_source = await drv.get_page_source()
            return bs(page_source, 'html.parser')
        except Exception as e:
            self.logger.error(f"Error fetching page {url}: {e}")
            return None

    async def _fetch_page_with_selenium(
        self,
        url: str,
        custom_user_agent: Optional[str] = None
    ) -> Optional[bs]:
        """
        Legacy alias for `_fetch_page` (back-compat).

        Deprecated: kept temporarily so existing internal callers keep
        working; delegates entirely to the new Playwright-based
        `_fetch_page`. No Selenium is used here despite the method name.

        Args:
            url: URL to fetch.
            custom_user_agent: Optional per-call User-Agent override,
                forwarded to `_fetch_page` (e.g. ZoomInfo's
                headless-hardening; see `scrape_zoominfo`).

        Returns:
            BeautifulSoup object, or None if the fetch failed.
        """
        return await self._fetch_page(url, custom_user_agent=custom_user_agent)

    def _parse_address(self, address_text: str) -> Dict[str, Optional[str]]:
        """
        Parse an address string into components.

        Args:
            address_text: Full address string

        Returns:
            Dictionary with address, city, state, zip_code, country
        """
        result = {
            'address': address_text,
            'city': None,
            'state': None,
            'zip_code': None,
            'country': None
        }

        # Simple parsing logic - can be enhanced
        parts = [p.strip() for p in address_text.split(',')]

        if len(parts) >= 2:
            result['city'] = parts[0]
            result['country'] = parts[-1]

            if len(parts) >= 3:
                # Try to extract state and zip
                state_zip = parts[-2].strip()
                if match := re.search(r'([A-Z]{2})\s+(\d{5}(?:-\d{4})?)', state_zip):
                    result['state'] = match[1]
                    result['zip_code'] = match[2]

        return result

    def _standardize_name(self, name: str) -> str:
        """Standardize company name for searching."""
        # Remove common suffixes
        suffixes = [
            'Inc.', 'Inc', 'LLC', 'Ltd.', 'Ltd', 'Corporation',
            'Corp.', 'Corp', 'Company', 'Co.', 'Co'
        ]

        cleaned = name
        for suffix in suffixes:
            cleaned = re.sub(
                rf'\b{re.escape(suffix)}\b',
                '',
                cleaned,
                flags=re.IGNORECASE
            )

        return cleaned.strip()

    def _extract_codes(self, value: Any) -> List[str]:
        """
        Extract NAICS/SIC codes from a company-info table cell.

        Ported from flowtask's `_extract_codes` helper (used by both
        `parsers/rocket.py` and `parsers/visualvisitor.py`): scans the
        cell's `<a>` tags for the first run of digits in each link's text.

        Args:
            value: BeautifulSoup tag for the table cell containing the code
                links.

        Returns:
            List of extracted code strings (may be empty).
        """
        codes: List[str] = []
        for link in value.find_all("a"):
            if match := re.search(r"\b\d+\b", link.text):
                codes.append(match.group())
        return codes

    # ===========================
    # Platform-Specific Methods (Tools)
    # ===========================

    @tool_schema(CompanyInput)
    async def scrape_zoominfo(
        self,
        company_name: str,
        return_json: bool = False
    ) -> Union[CompanyInfo, str]:
        """
        Scrape company information from ZoomInfo.

        Args:
            company_name: Name of the company to search for
            return_json: If True, return JSON string instead of CompanyInfo object

        Returns:
            CompanyInfo object or JSON string with company data
        """
        site_config = COMPANY_SOURCES["zoominfo"]

        # Initialize result
        result = CompanyInfo(
            search_term=site_config.search_template.format(company_name),
            source_platform='zoominfo',
            scrape_status='pending',
            timestamp=str(time.time())
        )

        try:
            # 1. Search (DDG-first, Google CSE fallback + hit validation)
            url = await self._search_company_url(company_name, site_config)

            if not url:
                result.scrape_status = 'no_data'
                result.error_message = 'No search results found'
                return result.to_json() if return_json else result

            result.search_url = url

            # 2. Fetch page (Playwright; keeps headless-hardening custom UA
            #    override for ZoomInfo per spec Module 2)
            document = await self._fetch_page_with_selenium(
                url, custom_user_agent=self._driver_config.custom_user_agent
            )

            if not document:
                result.scrape_status = 'error'
                result.error_message = 'Failed to fetch page'
                return result.to_json() if return_json else result

            # 3. Parse company information
            # Company name
            if company_header := document.select_one("h2#company-description-text-header"):
                result.company_name = company_header.text.strip()

            # Headquarters
            if hq_elem := document.select_one(".icon-label:-soup-contains('Headquarters') + .content"):
                result.headquarters = hq_elem.text.strip()

            # Phone
            if phone_elem := document.select_one(".icon-label:-soup-contains('Phone Number') + .content"):
                result.phone_number = phone_elem.text.strip()

            # Website
            if website_elem := document.select_one(".icon-label:-soup-contains('Website') + a"):
                result.website = website_elem.get('href')

            # Revenue
            if revenue_elem := document.select_one(".icon-label:-soup-contains('Revenue') + .content"):
                result.revenue_range = revenue_elem.text.strip()

            # Stock symbol
            if stock_elem := document.select_one(".icon-label:-soup-contains('Stock Symbol') + .content"):
                result.stock_symbol = stock_elem.text.strip()

            # Industry
            if industry_elems := document.select("#company-chips-wrapper a"):
                result.industry = [i.text.strip() for i in industry_elems]

            # Description
            if desc_elem := document.select_one("#company-description-text-content .company-desc"):
                result.company_description = desc_elem.text.strip()

            # NAICS and SIC codes
            codes_section = document.select("#codes-wrapper .codes-content")
            for code in codes_section:
                text = code.text.strip()
                if "NAICS Code" in text:
                    result.naics_code = text.replace("NAICS Code", "").strip()
                elif "SIC Code" in text:
                    result.sic_code = text.replace("SIC Code", "").strip()

            # Executives
            exec_elems = document.select(".org-chart .person-right-content")
            executives = []
            for exec_elem in exec_elems:
                if name_elem := exec_elem.select_one(".person-name"):
                    executives.append({
                        "name": name_elem.text.strip(),
                        "title": exec_elem.select_one(".job-title").text.strip() if exec_elem.select_one(".job-title") else "",
                        "profile_link": name_elem.get('href', '')
                    })
            if executives:
                result.executives = executives

            # Check if we found meaningful data
            has_data = any([
                result.company_name,
                result.headquarters,
                result.phone_number,
                result.website,
                result.revenue_range
            ])

            result.scrape_status = 'success' if has_data else 'no_data'

        except Exception as e:
            self.logger.error(f"Error scraping ZoomInfo: {e}")
            result.scrape_status = 'error'
            result.error_message = str(e)[:100]
        finally:
            await self._close_driver()

        return result.to_json() if return_json else result

    @tool_schema(CompanyInput)
    async def scrape_explorium(
        self,
        company_name: str,
        return_json: bool = False
    ) -> Union[CompanyInfo, str]:
        """
        Scrape company information from Explorium.ai.

        Args:
            company_name: Name of the company to search for
            return_json: If True, return JSON string instead of CompanyInfo object

        Returns:
            CompanyInfo object or JSON string with company data
        """
        site_config = COMPANY_SOURCES["explorium"]

        result = CompanyInfo(
            search_term=site_config.search_template.format(company_name),
            source_platform='explorium',
            scrape_status='pending',
            timestamp=str(time.time())
        )

        try:
            # Search (DDG-first, Google CSE fallback + hit validation)
            url = await self._search_company_url(company_name, site_config)

            if not url:
                result.scrape_status = 'no_data'
                result.error_message = 'No search results found'
                return result.to_json() if return_json else result

            result.search_url = url

            # Fetch page
            document = await self._fetch_page_with_selenium(url)

            if not document:
                result.scrape_status = 'error'
                result.error_message = 'Failed to fetch page'
                return result.to_json() if return_json else result

            # Parse data
            # Company name from header
            name_elem = document.find('h1', {'data-id': 'txt-company-name'})
            if name_elem:
                result.company_name = name_elem.text.strip()

            # Address
            if address_section := document.find('div', {'data-id': 'info-address'}):
                if address_elem := address_section.find('p', {'aria-label': True}):
                    address_text = address_elem.get('aria-label', '').strip()
                    result.headquarters = address_text

                    # Extract country
                    country = address_text.split(',')[-1].strip()
                    result.country = country or None

            # Company description
            desc_elem = document.find('p', {'class': 'ExpTypography-root ExpTypography-body1'})
            if desc_elem and name_elem:
                result.company_description = f"{name_elem.text.strip()}: {desc_elem.text.strip()}"

            # Logo
            if logo_elem := document.find('img', {'alt': True, 'src': True}):
                result.logo_url = logo_elem['src']

            # NAICS codes
            if naics_section := document.find('div', {'data-id': 'company-stat-naics'}):
                naics_entries = naics_section.find_all('p', {'class': 'ExpTypography-root'})
                naics_codes = []
                industries = []
                for entry in naics_entries:
                    code = entry.text.strip().strip(',')
                    industry_desc = entry.get('aria-label', '').strip()
                    if code:
                        naics_codes.append(code)
                    if industry_desc:
                        industries.append(industry_desc)

                if naics_codes:
                    result.naics_code = ', '.join(naics_codes)
                if industries:
                    result.industry = ', '.join(industries)

            # SIC codes
            if sic_section := document.find('div', {'data-id': 'company-stat-sic'}):
                sic_entries = sic_section.find_all('p', {'class': 'ExpTypography-root'})
                sic_codes = []
                for entry in sic_entries:
                    if code := entry.text.strip().strip(','):
                        sic_codes.append(code)

                if sic_codes:
                    result.sic_code = ', '.join(sic_codes)

            # Check for data
            has_data = any([
                result.company_name,
                result.headquarters,
                result.naics_code,
                result.sic_code
            ])

            result.scrape_status = 'success' if has_data else 'no_data'

        except Exception as e:
            self.logger.error(f"Error scraping Explorium: {e}")
            result.scrape_status = 'error'
            result.error_message = str(e)[:100]
        finally:
            await self._close_driver()

        return result.to_json() if return_json else result

    @tool_schema(CompanyInput)
    async def scrape_leadiq(
        self,
        company_name: str,
        return_json: bool = False
    ) -> Union[CompanyInfo, str]:
        """
        Scrape company information from LeadIQ.

        Args:
            company_name: Name of the company to search for
            return_json: If True, return JSON string instead of CompanyInfo object

        Returns:
            CompanyInfo object or JSON string with company data
        """
        site_config = COMPANY_SOURCES["leadiq"]
        standardized_name = self._standardize_name(company_name)

        result = CompanyInfo(
            search_term=site_config.search_template.format(standardized_name),
            source_platform='leadiq',
            scrape_status='pending',
            timestamp=str(time.time())
        )

        try:
            # Search (DDG-first, Google CSE fallback + hit validation)
            url = await self._search_company_url(standardized_name, site_config)

            if not url:
                result.scrape_status = 'no_data'
                result.error_message = 'No search results found'
                return result.to_json() if return_json else result

            result.search_url = url

            # Fetch page
            document = await self._fetch_page_with_selenium(url)

            if not document:
                result.scrape_status = 'error'
                result.error_message = 'Failed to fetch page'
                return result.to_json() if return_json else result

            # Parse data
            # Company logo and name
            if logo := document.find('img', {'alt': True, 'width': '76.747'}):
                result.company_name = logo.get('alt')
                result.logo_url = logo.get('src')

            # Revenue range
            if highlight_right := document.find('div', {'class': 'highlight-right'}):
                if revenue_span := highlight_right.find('span', {'class': 'start'}):
                    start_value = revenue_span.text.strip()
                    if end_span := revenue_span.find_next_sibling('span', {'class': 'end'}):
                        end_value = end_span.text.strip()
                        result.revenue_range = f"{start_value} - {end_value}"
                    else:
                        result.revenue_range = start_value

            # Company details
            if highlight_left := document.find('div', {'class': 'highlight-left'}):
                if overview_section := highlight_left.find('div', {'class': 'card span'}):
                    if dl_element := overview_section.find('dl'):
                        for item in dl_element.find_all('div', {'class': 'item'}):
                            dt = item.find('dt')
                            dd = item.find('dd')
                            if dt and dd:
                                field = dt.text.strip().lower()
                                value = dd.text.strip()

                                if field == 'headquarters':
                                    address_info = self._parse_address(value)
                                    result.headquarters = value
                                    result.address = address_info.get('address')
                                    result.city = address_info.get('city')
                                    result.state = address_info.get('state')
                                    result.zip_code = address_info.get('zip_code')
                                    result.country = address_info.get('country')
                                elif field == 'phone number':
                                    result.phone_number = value.replace('****', '0000')
                                elif field == 'website':
                                    website = dd.find('a')
                                    result.website = website['href'] if website else value
                                elif field == 'stock symbol':
                                    result.stock_symbol = value
                                elif field == 'naics code':
                                    result.naics_code = value
                                elif field == 'employees':
                                    result.employee_count = value
                                elif field == 'sic code':
                                    result.sic_code = value

            # Hero section
            if hero_section := document.find('div', {'class': 'card hero snug'}):
                # Company name
                if company_name_elem := hero_section.find('h1'):
                    result.company_name = company_name_elem.text.strip()

                # Industry, location, employees
                if info_p := hero_section.find('p', {'class': 'info'}):
                    spans = info_p.find_all('span')
                    if len(spans) >= 3:
                        if not result.industry:
                            result.industry = spans[0].text.strip()
                        result.number_employees = spans[2].text.strip()

                # Description
                if description_p := hero_section.find('pre'):
                    result.company_description = description_p.text.strip()

            # Similar companies
            similar_companies = []
            if similar_section := document.find('div', {'id': 'similar'}):
                for company in similar_section.find_all('li'):
                    company_link = company.find('a')
                    if not company_link:
                        continue

                    company_logo = company_link.find('img')
                    if company_name_elem := company_link.find('h3'):
                        similar_company = {
                            'name': company_name_elem.text.strip(),
                            'leadiq_url': company_link['href'],
                            'logo_url': company_logo['src'] if company_logo else None
                        }
                        similar_companies.append(similar_company)

            if similar_companies:
                result.similar_companies = json.dumps(
                    similar_companies,
                    ensure_ascii=False
                )

            # Check for data
            has_data = any([
                result.company_name,
                result.logo_url,
                result.headquarters,
                result.phone_number,
                result.website
            ])

            result.scrape_status = 'success' if has_data else 'no_data'

        except Exception as e:
            self.logger.error(f"Error scraping LeadIQ: {e}")
            result.scrape_status = 'error'
            result.error_message = str(e)[:100]
        finally:
            await self._close_driver()

        return result.to_json() if return_json else result

    @tool_schema(CompanyInput)
    async def scrape_rocketreach(
        self,
        company_name: str,
        return_json: bool = False
    ) -> Union[CompanyInfo, str]:
        """
        Scrape company information from RocketReach.

        Args:
            company_name: Name of the company to search for
            return_json: If True, return JSON string instead of CompanyInfo object

        Returns:
            CompanyInfo object or JSON string with company data
        """
        site_config = COMPANY_SOURCES["rocketreach"]

        result = CompanyInfo(
            search_term=site_config.search_template.format(company_name),
            source_platform='rocketreach',
            scrape_status='pending',
            timestamp=str(time.time())
        )

        try:
            # Search (DDG-first, Google CSE fallback + hit validation)
            url = await self._search_company_url(company_name, site_config)

            if not url:
                result.scrape_status = 'no_data'
                result.error_message = 'No search results found'
                return result.to_json() if return_json else result

            result.search_url = url

            # Fetch page
            document = await self._fetch_page_with_selenium(url)

            if not document:
                result.scrape_status = 'error'
                result.error_message = 'Failed to fetch page'
                return result.to_json() if return_json else result

            # Parse data
            # Company header
            if company_header := document.select_one(".company-header"):
                # Logo
                img_tag = company_header.select_one(".company-logo")
                result.logo_url = img_tag["src"] if img_tag else None

                # Company name
                if title_tag := company_header.select_one(".company-title"):
                    result.company_name = title_tag.text.replace(" Information", "").strip()

            # Description
            headline_summary = document.select_one(".headline-summary p")
            result.company_description = headline_summary.text.strip() if headline_summary else None

            # Information table
            info_table = document.select(".headline-summary table tbody tr")
            for row in info_table:
                key = row.select_one("td strong")
                value = row.select_one("td:nth-of-type(2)")

                if key and value:
                    key_text = key.text.strip().lower()
                    value_text = value.text.strip()

                    if "website" in key_text:
                        result.website = value.select_one("a")["href"] if value.select_one("a") else value_text
                    elif "ticker" in key_text:
                        result.stock_symbol = value_text
                    elif "revenue" in key_text:
                        result.revenue_range = value_text
                    elif "funding" in key_text:
                        result.funding = value_text
                    elif "employees" in key_text:
                        result.employee_count = value_text.split()[0]
                        result.number_employees = value_text
                    elif "founded" in key_text:
                        result.founded = value_text
                    elif "address" in key_text:
                        result.headquarters = value.select_one("a").text.strip() if value.select_one("a") else value_text
                    elif "phone" in key_text:
                        result.phone_number = value.select_one("a").text.strip() if value.select_one("a") else value_text
                    elif "industry" in key_text:
                        result.industry = [i.strip() for i in value_text.split(",")]
                    elif "keywords" in key_text:
                        result.keywords = [i.strip() for i in value_text.split(",")]
                    elif "sic" in key_text:
                        # Extract codes
                        codes = []
                        for link in value.find_all("a"):
                            if match := re.search(r"\b\d+\b", link.text):
                                codes.append(match.group())
                        result.sic_code = ', '.join(codes) if codes else None
                    elif "naics" in key_text:
                        # Extract codes
                        codes = []
                        for link in value.find_all("a"):
                            if match := re.search(r"\b\d+\b", link.text):
                                codes.append(match.group())
                        result.naics_code = ', '.join(codes) if codes else None

            # Check for data
            has_data = any([
                result.company_name,
                result.logo_url,
                result.headquarters,
                result.phone_number,
                result.website
            ])

            result.scrape_status = 'success' if has_data else 'no_data'

        except Exception as e:
            self.logger.error(f"Error scraping RocketReach: {e}")
            result.scrape_status = 'error'
            result.error_message = str(e)[:100]
        finally:
            await self._close_driver()

        return result.to_json() if return_json else result

    @tool_schema(CompanyInput)
    async def scrape_siccode(
        self,
        company_name: str,
        return_json: bool = False
    ) -> Union[CompanyInfo, str]:
        """
        Scrape company information from SICCode.com.

        Args:
            company_name: Name of the company to search for
            return_json: If True, return JSON string instead of CompanyInfo object

        Returns:
            CompanyInfo object or JSON string with company data
        """
        site_config = COMPANY_SOURCES["siccode"]

        result = CompanyInfo(
            search_term=site_config.search_template.format(company_name),
            source_platform='siccode',
            scrape_status='pending',
            timestamp=str(time.time())
        )

        try:
            # Search (DDG-first, Google CSE fallback + hit validation)
            url = await self._search_company_url(company_name, site_config)

            if not url:
                result.scrape_status = 'no_data'
                result.error_message = 'No search results found'
                return result.to_json() if return_json else result

            result.search_url = url

            # Fetch page
            document = await self._fetch_page_with_selenium(url)

            if not document:
                result.scrape_status = 'error'
                result.error_message = 'Failed to fetch page'
                return result.to_json() if return_json else result

            # Parse data
            if header := document.select_one("div.main-title"):
                # Company name
                if name_elem := header.select_one("h1.size-h2 a span"):
                    result.company_name = name_elem.text.strip()

                # Industry category
                if cat_elem := header.select_one("b.p-category"):
                    result.industry_category = cat_elem.text.strip()

            # SIC and NAICS codes
            if desc := document.find('div', {'id': 'description'}):
                sic_code_elem = desc.select_one("a.sic")
                naics_code_elem = desc.select_one("a.naics")

                if sic_code_elem:
                    sic_text = sic_code_elem.text.split("SIC CODE")[-1].strip()
                    if ' - ' in sic_text:
                        parts = sic_text.split(' - ')
                        result.sic_code = parts[0].strip()
                        result.industry = parts[1].strip() if len(parts) > 1 else None

                if naics_code_elem:
                    naics_text = naics_code_elem.text.split("NAICS CODE")[-1].strip()
                    if ' - ' in naics_text:
                        parts = naics_text.split(' - ')
                        result.naics_code = parts[0].strip()
                        result.category = parts[1].strip() if len(parts) > 1 else None

            # Location details
            if overview := document.find('div', {'id': 'overview'}):
                # Description
                if desc_elem := overview.select_one("p.p-note"):
                    result.company_description = desc_elem.text.strip()

                # Location fields
                city_elem = overview.select_one(".p-locality")
                state_elem = overview.select_one(".p-region")
                zip_elem = overview.select_one(".p-postal-code")
                country_elem = overview.select_one(".p-country-name")
                metro_elem = overview.select_one("div[title]")

                if city_elem:
                    result.city = city_elem.text.strip()
                if state_elem:
                    result.state = state_elem.text.strip()
                if zip_elem:
                    result.zip_code = zip_elem.text.strip()
                if country_elem:
                    result.country = country_elem.text.strip()
                if metro_elem:
                    result.metro_area = metro_elem.text.strip()

                # Construct headquarters
                parts = [result.city, result.state, result.zip_code, result.country]
                result.headquarters = ", ".join(filter(None, parts))

            # Check for data
            has_data = any([
                result.company_name,
                result.sic_code,
                result.naics_code,
                result.headquarters
            ])

            result.scrape_status = 'success' if has_data else 'no_data'

        except Exception as e:
            self.logger.error(f"Error scraping SICCode: {e}")
            result.scrape_status = 'error'
            result.error_message = str(e)[:100]
        finally:
            await self._close_driver()

        return result.to_json() if return_json else result

    @tool_schema(CompanyInput)
    async def scrape_visualvisitor(
        self,
        company_name: str,
        return_json: bool = False
    ) -> Union[CompanyInfo, str]:
        """
        Scrape company information from VisualVisitor.

        Args:
            company_name: Name of the company to search for
            return_json: If True, return JSON string instead of CompanyInfo object

        Returns:
            CompanyInfo object or JSON string with company data
        """
        site_config = COMPANY_SOURCES["visualvisitor"]

        result = CompanyInfo(
            search_term=site_config.search_template.format(company_name),
            source_platform='visualvisitor',
            scrape_status='pending',
            timestamp=str(time.time())
        )

        try:
            # Search (DDG-first, Google CSE fallback + hit validation)
            url = await self._search_company_url(company_name, site_config)

            if not url:
                result.scrape_status = 'no_data'
                result.error_message = 'No search results found'
                return result.to_json() if return_json else result

            result.search_url = url

            # Fetch page (Playwright driver stack)
            document = await self._fetch_page(url)

            if not document:
                result.scrape_status = 'error'
                result.error_message = 'Failed to fetch page'
                return result.to_json() if return_json else result

            # Parse data (selectors ported from flowtask
            # parsers/visualvisitor.py:32-125 — NOTE: flowtask's version
            # mislabels source_platform as 'rocketreach' at :42; fixed here)
            if company_header := document.select_one(".company-header"):
                img_tag = company_header.select_one(".company-logo")
                result.logo_url = img_tag["src"] if img_tag else None

                if title_tag := company_header.select_one(".company-title"):
                    result.company_name = title_tag.text.replace(" Information", "").strip()

            headline_summary = document.select_one(".headline-summary p")
            result.company_description = headline_summary.text.strip() if headline_summary else None

            info_table = document.select(".headline-summary table tbody tr")
            for row in info_table:
                key = row.select_one("td strong")
                value = row.select_one("td:nth-of-type(2)")

                if key and value:
                    key_text = key.text.strip().lower()
                    value_text = value.text.strip()

                    if "website" in key_text:
                        result.website = value.select_one("a")["href"] if value.select_one("a") else value_text
                    elif "ticker" in key_text:
                        result.stock_symbol = value_text
                    elif "revenue" in key_text:
                        result.revenue_range = value_text
                    elif "funding" in key_text:
                        result.funding = value_text
                    elif "employees" in key_text:
                        result.employee_count = value_text.split()[0]
                        result.number_employees = value_text
                    elif "founded" in key_text:
                        result.founded = value_text
                    elif "address" in key_text:
                        result.headquarters = value.select_one("a").text.strip() if value.select_one("a") else value_text
                    elif "phone" in key_text:
                        result.phone_number = value.select_one("a").text.strip() if value.select_one("a") else value_text
                    elif "industry" in key_text:
                        result.industry = [i.strip() for i in value_text.split(",")]
                    elif "keywords" in key_text:
                        result.keywords = [i.strip() for i in value_text.split(",")]
                    elif "sic" in key_text:
                        codes = self._extract_codes(value)
                        result.sic_code = ', '.join(codes) if codes else None
                    elif "naics" in key_text:
                        codes = self._extract_codes(value)
                        result.naics_code = ', '.join(codes) if codes else None

            has_data = any([
                result.company_name,
                result.logo_url,
                result.headquarters,
                result.phone_number,
                result.website
            ])

            result.scrape_status = 'success' if has_data else 'no_data'

        except Exception as e:
            self.logger.error(f"Error scraping VisualVisitor: {e}")
            result.scrape_status = 'error'
            result.error_message = str(e)[:100]
        finally:
            await self._close_driver()

        return result.to_json() if return_json else result

    @tool_schema(CompanyInput)
    async def scrape_all_sources(
        self,
        company_name: str,
        return_json: bool = False
    ) -> Union[List[CompanyInfo], str]:
        """
        Scrape company information from ALL available sources.

        This method runs all scraping tools in parallel and returns
        aggregated results from all platforms.

        Args:
            company_name: Name of the company to search for
            return_json: If True, return JSON string instead of list of CompanyInfo objects

        Returns:
            List of CompanyInfo objects or JSON string with all results
        """
        self.logger.info(f"Scraping all sources for: {company_name}")

        # Run all scraping methods in parallel
        tasks = [
            self.scrape_zoominfo(company_name, return_json=False),
            self.scrape_explorium(company_name, return_json=False),
            self.scrape_leadiq(company_name, return_json=False),
            self.scrape_rocketreach(company_name, return_json=False),
            self.scrape_siccode(company_name, return_json=False)
        ]

        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Filter out exceptions and failed results
        valid_results = []
        for result in results:
            if isinstance(result, Exception):
                self.logger.error(f"Scraping error: {result}")
            elif isinstance(result, CompanyInfo):
                valid_results.append(result)

        if return_json:
            return json.dumps(
                [r.model_dump(exclude_none=True) for r in valid_results],
                ensure_ascii=False,
                indent=2
            )

        return valid_results

    @tool_schema(ResearchCompanyInput)
    async def research_company(
        self,
        company_name: str,
        sources: Optional[List[str]] = None,
        return_json: bool = False
    ) -> Union[CompanyInfo, str]:
        """
        Research a company across sources, returning the first successful profile.

        Tries each source in priority order (default: leadiq, rocketreach,
        explorium, siccode, visualvisitor, zoominfo — cheap HTTP-friendly
        sources first, browser-heavy ZoomInfo last) by calling the matching
        `scrape_<source>` method, and returns the FIRST `CompanyInfo` whose
        `scrape_status == "success"`. Later sources are never called once a
        success is found. If every source fails, returns a `CompanyInfo`
        with `scrape_status="no_data"` and an `error_message` summarizing
        each source's failure. This method never raises into the agent loop.

        Args:
            company_name: Name of the company to research.
            sources: Optional subset/order of source names to try (must be
                a subset of leadiq, rocketreach, explorium, siccode,
                visualvisitor, zoominfo). `None` (default) uses the full
                priority order; an explicit empty list (`[]`) tries no
                sources and returns a `no_data` result immediately.
            return_json: If True, return a JSON string instead of a
                `CompanyInfo` object.

        Returns:
            CompanyInfo object (or JSON string) for the first successful
            source, or a `no_data`/`error` CompanyInfo if none succeeded.
        """
        # `sources is None` -> full default priority order. An explicit
        # empty list is a deliberate "try nothing" request (distinct from
        # "unset"), not a fallback to the default order.
        order = DEFAULT_SOURCE_PRIORITY if sources is None else sources

        unknown = [name for name in order if name not in COMPANY_SOURCES]
        if unknown:
            info = CompanyInfo(
                search_term=company_name,
                scrape_status='error',
                error_message=(
                    f"Unknown source(s) {unknown}; valid sources: "
                    f"{list(COMPANY_SOURCES.keys())}"
                ),
                timestamp=str(time.time())
            )
            return info.to_json() if return_json else info

        failures: Dict[str, str] = {}
        for name in order:
            scrape_method = getattr(self, f"scrape_{name}")
            try:
                result = await scrape_method(company_name, return_json=False)
            except Exception as e:
                self.logger.error(f"research_company: {name} raised unexpectedly: {e}")
                failures[name] = f"error: {e}"
                continue

            if isinstance(result, CompanyInfo) and result.scrape_status == 'success':
                return result.to_json() if return_json else result

            failures[name] = result.scrape_status if isinstance(result, CompanyInfo) else 'error'

        info = CompanyInfo(
            search_term=company_name,
            scrape_status='no_data',
            error_message=f"All sources failed: {failures}",
            timestamp=str(time.time())
        )
        return info.to_json() if return_json else info

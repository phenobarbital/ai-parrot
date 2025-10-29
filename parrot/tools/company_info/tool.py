"""
CompanyInfoToolkit - Unified toolkit for scraping company information from multiple sources.

This toolkit extends AbstractToolkit and provides methods to scrape company data from:
- explorium.ai
- leadiq.com
- rocketreach.co
- siccode.com
- zoominfo.com

Each public async method becomes a tool that:
1. Performs a Google site search for the company
2. Fetches the first result using Selenium
3. Parses the page with BeautifulSoup
4. Extracts company information
5. Returns structured data (CompanyInfo model or JSON)

Dependencies:
    - selenium
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
from urllib.parse import urljoin
from bs4 import BeautifulSoup as bs
from pydantic import BaseModel, Field, model_validator
from googleapiclient.discovery import build
from navconfig import config
from navconfig.logging import logging
try:
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.common.exceptions import (
        TimeoutException,
        NoSuchElementException,
        WebDriverException
    )
except ImportError as e:
    raise ImportError("Please install selenium: pip install selenium") from e

from ..toolkit import AbstractToolkit
from ..decorators import tool_schema
from ..scraping.driver import SeleniumSetup


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
        **kwargs
    ):
        """
        Initialize the CompanyInfoToolkit.

        Args:
            google_api_key: Google Custom Search API key
            google_cse_id: Google Custom Search Engine ID
            browser: Browser type ('chrome', 'firefox', 'edge', 'safari', 'undetected')
            headless: Run browser in headless mode
            timeout: Default timeout for page loads (seconds)
            auto_install: Auto-install webdriver if not found
            mobile: Enable mobile emulation (Chrome only)
            mobile_device: Specific mobile device to emulate
            use_undetected: Use undetected-chromedriver (requires package)
            **kwargs: Additional arguments passed to AbstractToolkit and SeleniumSetup
        """
        super().__init__(**kwargs)

        # Google Search configuration
        self.google_api_key = google_api_key or config.get('GOOGLE_SEARCH_API_KEY')
        self.google_cse_id = google_cse_id or config.get('GOOGLE_SEARCH_ENGINE_ID')
        # Service Selection:
        self.service = build("customsearch", "v1", developerKey=self.google_api_key)

        # Browser configuration for SeleniumSetup
        self.browser_config = {
            'browser': 'undetected' if use_undetected else browser,
            'headless': headless,
            'auto_install': auto_install,
            'mobile': mobile,
            'mobile_device': mobile_device,
            'timeout': timeout,
            **kwargs  # Pass through any additional kwargs
        }
        # Selenium setup instance and driver
        self._selenium_setup: Optional[SeleniumSetup] = None

        # Current driver instance
        self._driver = None

        # Logger
        self.logger = logging.getLogger(self.__class__.__name__)

    # ===========================
    # Core Utility Methods
    # ===========================
    async def _get_driver(self) -> webdriver.Chrome:
        """Get or create Selenium WebDriver instance using SeleniumSetup."""
        if self._driver is None:
            if SeleniumSetup is None:
                raise ImportError(
                    "SeleniumSetup not available. Please ensure parrot.tools.scraping.driver is installed."
                )

            self.logger.info("Initializing Selenium WebDriver...")

            # Create SeleniumSetup instance
            self._selenium_setup = SeleniumSetup(**self.browser_config)

            # Get driver using SeleniumSetup's async method
            self._driver = await self._selenium_setup.get_driver()

            self.logger.info("Selenium WebDriver initialized successfully")

        return self._driver

    async def _close_driver(self):
        """Close the Selenium driver if open."""
        if self._driver is not None:
            try:
                loop = asyncio.get_running_loop()
                await loop.run_in_executor(None, self._driver.quit)
                self.logger.info("Selenium WebDriver closed")
            except Exception as e:
                self.logger.warning(f"Error closing driver: {e}")
            finally:
                self._driver = None
                self._selenium_setup = None

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

    async def _fetch_page_with_selenium(self, url: str) -> Optional[bs]:
        """
        Fetch a page using Selenium and return BeautifulSoup object.

        Args:
            url: URL to fetch

        Returns:
            BeautifulSoup object or None if failed
        """
        driver = await self._get_driver()

        try:
            self.logger.info(f"Fetching URL: {url}")

            # Navigate to URL
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, driver.get, url)

            # Wait for page to load
            await asyncio.sleep(2)

            # Get page source
            page_source = await loop.run_in_executor(
                None,
                lambda: driver.page_source
            )
            # Parse with BeautifulSoup
            return bs(page_source, 'html.parser')

        except TimeoutException:
            self.logger.error(f"Timeout fetching: {url}")
            return None
        except Exception as e:
            self.logger.error(f"Error fetching page: {e}")
            return None

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
        site = "zoominfo.com"
        search_term = f"site:zoominfo.com {company_name} Overview"

        # Initialize result
        result = CompanyInfo(
            search_term=search_term,
            source_platform='zoominfo',
            scrape_status='pending',
            timestamp=str(time.time())
        )

        try:
            # 1. Google site search
            search_result = await self._google_site_search(
                company_name=company_name,
                site=site,
                additional_terms="Overview"
            )

            if not search_result.url:
                result.scrape_status = 'no_data'
                result.error_message = 'No search results found'
                return result.to_json() if return_json else result

            result.search_url = search_result.url

            # 2. Fetch page with Selenium
            document = await self._fetch_page_with_selenium(search_result.url)

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
        site = "explorium.ai"
        search_term = f"site:explorium.ai {company_name}"

        result = CompanyInfo(
            search_term=search_term,
            source_platform='explorium',
            scrape_status='pending',
            timestamp=str(time.time())
        )

        try:
            # Google site search
            search_result = await self._google_site_search(
                company_name=company_name,
                site=site,
                additional_terms="overview - services"
            )

            if not search_result.url:
                result.scrape_status = 'no_data'
                result.error_message = 'No search results found'
                return result.to_json() if return_json else result

            result.search_url = search_result.url

            # Fetch page
            document = await self._fetch_page_with_selenium(search_result.url)

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
        site = "leadiq.com"
        standardized_name = self._standardize_name(company_name)
        search_term = f"site:leadiq.com {standardized_name}"

        result = CompanyInfo(
            search_term=search_term,
            source_platform='leadiq',
            scrape_status='pending',
            timestamp=str(time.time())
        )

        try:
            # Google site search
            search_result = await self._google_site_search(
                company_name=standardized_name,
                site=site,
                additional_terms="Company Overview"
            )

            if not search_result.url:
                result.scrape_status = 'no_data'
                result.error_message = 'No search results found'
                return result.to_json() if return_json else result

            result.search_url = search_result.url

            # Fetch page
            document = await self._fetch_page_with_selenium(search_result.url)

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
        site = "rocketreach.co"
        search_term = f"site:rocketreach.co '{company_name}'"

        result = CompanyInfo(
            search_term=search_term,
            source_platform='rocketreach',
            scrape_status='pending',
            timestamp=str(time.time())
        )

        try:
            # Google site search
            search_result = await self._google_site_search(
                company_name=company_name,
                site=site,
                additional_terms=" Information - RocketReach"
            )

            if not search_result.url:
                result.scrape_status = 'no_data'
                result.error_message = 'No search results found'
                return result.to_json() if return_json else result

            result.search_url = search_result.url

            # Fetch page
            document = await self._fetch_page_with_selenium(search_result.url)

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
        site = "siccode.com"
        search_term = f"site:siccode.com '{company_name}' +NAICS"

        result = CompanyInfo(
            search_term=search_term,
            source_platform='siccode',
            scrape_status='pending',
            timestamp=str(time.time())
        )

        try:
            # Google site search
            search_result = await self._google_site_search(
                company_name=company_name,
                site=site,
                additional_terms="+NAICS"
            )

            if not search_result.url:
                result.scrape_status = 'no_data'
                result.error_message = 'No search results found'
                return result.to_json() if return_json else result

            result.search_url = search_result.url

            # Fetch page
            document = await self._fetch_page_with_selenium(search_result.url)

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

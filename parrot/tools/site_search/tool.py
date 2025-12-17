"""SiteSearch tool for site-specific crawling with markdown output."""
from __future__ import annotations

import asyncio
import tempfile
import urllib.parse
from pathlib import Path
from typing import Any, Dict, List, Optional

import aiohttp
from bs4 import BeautifulSoup
from markitdown import MarkItDown
from pydantic import BaseModel, Field, model_validator

from ..google.tools import GoogleSiteSearchTool
from ..scraping.driver import SeleniumSetup
from .presets import SITE_PRESETS


class SiteSearchArgs(BaseModel):
    """Arguments schema for :class:`SiteSearch`."""

    url: Optional[str] = Field(
        default=None,
        description=(
            "Base URL of the site to explore (e.g., https://www.statista.com/). "
            "Required if preset is not provided."
        ),
    )
    query: Optional[str] = Field(
        default=None,
        description="Terms to search for within the provided site",
    )
    preset: Optional[str] = Field(
        default=None,
        description=(
            "Preset name for predefined search configurations. "
            "Use 'site_presets_list' tool to discover available presets. "
            "If provided, url and selectors will be taken from preset configuration."
        ),
    )
    selectors: Optional[List[str]] = Field(
        default=None,
        description="Optional CSS selectors to extract specific page areas after rendering",
    )
    max_results: int = Field(
        default=3,
        ge=1,
        le=10,
        description="Maximum number of search results to process",
    )

    @model_validator(mode="after")
    def validate_url_or_preset(self) -> "SiteSearchArgs":
        """Validate that either url or preset is provided."""
        if not self.url and not self.preset:
            raise ValueError("Either 'url' or 'preset' must be provided")
        return self


class SiteSearch(GoogleSiteSearchTool):
    """Perform Google-powered site searches and return rendered content as markdown."""

    name = "site_search"
    description = (
        "Search within a given site and return fully-rendered page content as markdown, "
        "including PDF conversion when encountered. "
        "Supports presets for common searches (e.g., 'best_buy_deals' for trending Best Buy deals). "
        "Use 'site_presets_list' tool to discover available presets before using this tool."
    )
    args_schema = SiteSearchArgs

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._markitdown = MarkItDown()
        self._selenium_setup: Optional[SeleniumSetup] = None
        self._driver = None

    async def _execute(
        self,
        url: Optional[str] = None,
        query: Optional[str] = None,
        preset: Optional[str] = None,
        selectors: Optional[List[str]] = None,
        max_results: int = 3,
        **_: Any,
    ) -> Dict[str, Any]:
        # Apply preset if provided
        if preset:
            preset_config = SITE_PRESETS.get(preset)
            if preset_config:
                url = preset_config.get("url", url)
                selectors = preset_config.get("selectors", selectors)
                # Preset overrides url and selectors
                self.logger.info(f"Using preset '{preset}': url={url}")
            else:
                raise ValueError(
                    f"Unknown preset: '{preset}'. Use 'site_presets_list' to see available presets."
                )

        if not url:
            raise ValueError("URL is required when preset is not provided or preset has no URL")

        site = self._extract_site(url)
        if not site:
            raise ValueError(f"Could not extract site from URL: {url}")

        # If query is provided, use Google search within site
        if query:
            search_results = await super()._execute(
                query=query,
                site=site,
                max_results=max_results,
                preview=False,
                preview_method="aiohttp",
            )
            urls_to_process = [
                item.get("link") for item in search_results.get("results", [])[:max_results]
                if item.get("link")
            ]
        else:
            # No query - just render the provided URL directly
            urls_to_process = [url]

        processed_results = []
        try:
            for link in urls_to_process:
                if await self._is_pdf(link):
                    markdown, content_type = await self._convert_pdf(link)
                else:
                    markdown, content_type = await self._render_with_selenium(
                        link, selectors
                    )

                processed_results.append(
                    {
                        "url": link,
                        "content_type": content_type,
                        "markdown": markdown,
                    }
                )
        finally:
            await self._close_driver()

        return {
            "site": site,
            "search_terms": query,
            "preset_used": preset,
            "total_results": len(processed_results),
            "results": processed_results,
        }

    async def _render_with_selenium(
        self, url: str, selectors: Optional[List[str]]
    ) -> tuple[str, str]:
        driver = await self._get_driver()
        loop = asyncio.get_running_loop()

        await loop.run_in_executor(None, driver.get, url)
        await asyncio.sleep(2)
        page_source = await loop.run_in_executor(None, lambda: driver.page_source)

        soup = BeautifulSoup(page_source, "html.parser")
        if selectors:
            selected_html = []
            for selector in selectors:
                selected_html.extend([str(elem) for elem in soup.select(selector)])
            html_content = "\n".join(selected_html) if selected_html else str(soup)
        else:
            html_content = str(soup)

        markdown = await self._convert_html_to_markdown(html_content)
        return markdown, "text/html"

    async def _convert_pdf(self, url: str) -> tuple[str, str]:
        timeout = aiohttp.ClientTimeout(total=60)
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        }
        async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
            async with session.get(url) as response:
                if response.status != 200:
                    return (f"Failed to download PDF (HTTP {response.status})", "application/pdf")

                pdf_bytes = await response.read()
                loop = asyncio.get_running_loop()

                def convert() -> str:
                    with tempfile.NamedTemporaryFile(
                        mode="wb", suffix=".pdf", delete=False
                    ) as tmp_file:
                        tmp_file.write(pdf_bytes)
                        tmp_path = Path(tmp_file.name)

                    try:
                        result = self._markitdown.convert(str(tmp_path))
                        markdown_content = getattr(result, "text_content", "") or ""
                    finally:
                        tmp_path.unlink(missing_ok=True)
                    return markdown_content

                markdown_content = await loop.run_in_executor(None, convert)
                return markdown_content, "application/pdf"

    async def _convert_html_to_markdown(self, html: str) -> str:
        loop = asyncio.get_running_loop()

        def convert() -> str:
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".html", delete=False, encoding="utf-8"
            ) as tmp_file:
                tmp_file.write(html)
                tmp_path = Path(tmp_file.name)

            try:
                result = self._markitdown.convert(str(tmp_path))
                markdown_content = getattr(result, "text_content", "") or ""
            finally:
                tmp_path.unlink(missing_ok=True)

            return markdown_content

        return await loop.run_in_executor(None, convert)

    async def _is_pdf(self, url: str) -> bool:
        if url.lower().endswith(".pdf"):
            return True

        timeout = aiohttp.ClientTimeout(total=10)
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.head(url, allow_redirects=True) as response:
                    content_type = response.headers.get("Content-Type", "").lower()
                    return "pdf" in content_type
        except Exception:
            return False

    async def _get_driver(self):
        if self._driver is None:
            self._selenium_setup = SeleniumSetup()
            self._driver = await self._selenium_setup.get_driver()
        return self._driver

    async def _close_driver(self):
        if self._driver is not None:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, self._driver.quit)
            self._driver = None
            self._selenium_setup = None

    @staticmethod
    def _extract_site(url: str) -> str:
        parsed = urllib.parse.urlparse(url)
        return parsed.netloc or parsed.path


__all__ = ["SiteSearch", "SiteSearchArgs"]

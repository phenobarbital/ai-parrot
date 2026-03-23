"""REST API data source for structured record extraction."""
from __future__ import annotations

from abc import abstractmethod
from typing import Any

import aiohttp

from .base import ExtractDataSource, ExtractionResult


class APIDataSource(ExtractDataSource):
    """Base class for REST API data extraction.

    Subclass this for specific APIs (Workday, Jira, etc.). Handles pagination,
    authentication, and rate limiting.

    Config:
        base_url: str — API base URL.
        auth_type: str — "bearer", "basic", "oauth2".
        credentials: dict — Auth credentials (token, username/password, etc.).
        headers: dict — Additional HTTP headers.
        page_size: int — Records per page (default: 100).
        max_pages: int — Safety limit on pagination (default: 100).

    Args:
        name: Human-readable name for logging and reporting.
        config: Source-specific configuration.
    """

    @abstractmethod
    async def _build_request(
        self,
        fields: list[str] | None,
        filters: dict[str, Any] | None,
        page_token: str | None,
    ) -> tuple[str, dict[str, Any]]:
        """Construct the API request URL and parameters.

        Args:
            fields: Optional field projection.
            filters: Optional filters to pass as query params.
            page_token: Pagination token (None for first page).

        Returns:
            Tuple of (url, params) for the HTTP request.
        """
        ...

    @abstractmethod
    def _parse_response(self, response_data: dict[str, Any]) -> list[dict[str, Any]]:
        """Extract records from the API response body.

        Args:
            response_data: Parsed JSON response.

        Returns:
            List of record dicts.
        """
        ...

    @abstractmethod
    def _get_next_page(self, response_data: dict[str, Any]) -> str | None:
        """Return next page token, or None if no more pages.

        Args:
            response_data: Parsed JSON response.

        Returns:
            Next page token string, or None.
        """
        ...

    def _build_headers(self) -> dict[str, str]:
        """Build HTTP headers including authentication.

        Returns:
            Dict of HTTP headers.
        """
        headers = dict(self.config.get("headers", {}))
        headers.setdefault("Accept", "application/json")

        auth_type = self.config.get("auth_type", "")
        credentials = self.config.get("credentials", {})

        if auth_type == "bearer":
            token = credentials.get("token", "")
            if token:
                headers["Authorization"] = f"Bearer {token}"
        elif auth_type == "basic":
            import base64

            username = credentials.get("username", "")
            password = credentials.get("password", "")
            encoded = base64.b64encode(
                f"{username}:{password}".encode()
            ).decode()
            headers["Authorization"] = f"Basic {encoded}"

        return headers

    async def extract(
        self,
        fields: list[str] | None = None,
        filters: dict[str, Any] | None = None,
    ) -> ExtractionResult:
        """Paginated extraction from the API.

        Args:
            fields: Optional field projection (applied post-fetch).
            filters: Optional filters (passed to _build_request).

        Returns:
            ExtractionResult with all paginated records.
        """
        all_records: list[dict[str, Any]] = []
        errors: list[str] = []
        page_token: str | None = None
        page_count = 0
        max_pages = self.config.get("max_pages", 100)
        headers = self._build_headers()

        async with aiohttp.ClientSession(headers=headers) as session:
            while page_count < max_pages:
                url, params = await self._build_request(
                    fields, filters, page_token,
                )
                try:
                    async with session.get(url, params=params) as resp:
                        if resp.status != 200:
                            errors.append(
                                f"API returned status {resp.status} for {url}"
                            )
                            break
                        response_data = await resp.json()
                except Exception as e:
                    errors.append(f"API request failed: {e}")
                    break

                records = self._parse_response(response_data)
                all_records.extend(records)

                page_token = self._get_next_page(response_data)
                if not page_token:
                    break
                page_count += 1

        self.logger.debug(
            "Extracted %d records from API in %d pages",
            len(all_records), page_count + 1,
        )
        return self._build_result(
            all_records, fields=fields, errors=errors,
        )

    async def list_fields(self) -> list[str]:
        """Fetch first page and return keys from first record.

        Returns:
            List of field names from first record.
        """
        result = await self.extract()
        if result.records:
            return list(result.records[0].data.keys())
        return []

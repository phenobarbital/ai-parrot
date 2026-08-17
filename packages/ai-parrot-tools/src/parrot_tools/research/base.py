"""
BaseResearchToolkit — cooperative mixin shared by every research toolkit
(FEAT-426).

Provides aiohttp session lifecycle management (FEAT-391 ``auto_open``
protocol), ``ToolCache`` integration, and citation/failure construction
helpers used by ``OpenDataToolkit`` and ``AcademicResearchToolkit``.

MUST be listed BEFORE ``AbstractToolkit`` in a subclass's bases, e.g.::

    class OpenDataToolkit(BaseResearchToolkit, AbstractToolkit):
        ...

so that ``super().__init__(**kwargs)`` / ``await super()._close()`` reach
``AbstractToolkit`` and initialise ``_opened``, ``_open_lock``, ``logger``,
and ``_tool_cache``.
"""
import asyncio
from datetime import UTC, datetime
from typing import Any

import aiohttp
import backoff

from parrot_tools.cache import ToolCache

from .models import Citation, ResearchResult


class BaseResearchToolkit:
    """Cooperative mixin. MUST be listed BEFORE AbstractToolkit in bases."""

    #: FEAT-391: opt in to lazy resource lifecycle — the first tool call
    #: triggers ``_ensure_open()`` before ``_pre_execute()`` runs.
    auto_open: bool = True

    def __init__(self, *, cache_ttl: int = 3600, **kwargs):
        """Initialize the mixin and forward to the cooperative base.

        Args:
            cache_ttl: Default TTL (seconds) for ``ToolCache`` entries.
            **kwargs: Forwarded to ``AbstractToolkit.__init__`` — MUST be
                forwarded via ``super().__init__(**kwargs)`` or ``_opened``,
                ``_open_lock``, ``logger``, and ``_tool_cache`` are never
                initialised.
        """
        super().__init__(**kwargs)
        self.cache_ttl = cache_ttl
        self._cache = ToolCache(prefix="research_cache", ttl=cache_ttl)
        self._session: aiohttp.ClientSession | None = None

    async def _open(self) -> None:
        """Create the shared aiohttp session used by all API calls."""
        self._session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=30),
            headers={"User-Agent": "ai-parrot-research/1.0"},
        )

    async def _close(self) -> None:
        """Close the aiohttp session, then reset ``_opened`` via super()."""
        if self._session is not None:
            await self._session.close()
            self._session = None
        await super()._close()

    async def _make_api_request(
        self,
        url: str,
        params: dict | None = None,
        headers: dict | None = None,
    ) -> tuple[dict | None, str | None]:
        """Perform a GET request and return ``(payload, error)``.

        Never raises: network errors, timeouts, and non-2xx responses are
        caught and returned as the ``error`` string in the tuple so callers
        can build a :meth:`_failure` result instead of propagating an
        exception (see spec §2 "Error Contract"). HTTP 429 is retried with
        exponential backoff (:meth:`_request_with_retry`); if retries are
        exhausted the resulting exception is still caught here and reported
        as a tuple, never raised.

        Args:
            url: Full request URL.
            params: Optional query parameters.
            headers: Optional additional headers.

        Returns:
            A ``(payload, error)`` tuple — exactly one of the two is
            populated on any given call.
        """
        await self._ensure_open()
        try:
            return await self._request_with_retry(url, params, headers)
        except TimeoutError:
            return None, f"Timeout requesting {url}"
        except aiohttp.ClientError as e:
            return None, f"Request error: {e}"

    @backoff.on_exception(
        backoff.expo,
        (aiohttp.ClientError, asyncio.TimeoutError),
        max_tries=3,
    )
    async def _request_with_retry(
        self,
        url: str,
        params: dict | None,
        headers: dict | None,
    ) -> tuple[dict | None, str | None]:
        """Single GET attempt, retried on 429/network errors via backoff.

        Raises ``aiohttp.ClientResponseError`` on HTTP 429 so ``backoff``
        retries the request; all raises are ultimately caught by the
        caller, :meth:`_make_api_request`.
        """
        async with self._session.get(
            url, params=params, headers=headers
        ) as response:
            if response.status == 429:
                raise aiohttp.ClientResponseError(
                    request_info=response.request_info,
                    history=response.history,
                    status=429,
                    message="Rate limited",
                )
            if response.status >= 400:
                text = await response.text()
                return None, f"HTTP {response.status}: {text[:500]}"
            payload = await response.json(content_type=None)
            return payload, None

    async def _run_sync_in_executor(self, func, *args, **kwargs) -> Any:
        """Run a blocking sync callable in the default executor.

        Args:
            func: The blocking callable (e.g. a ``wbgapi``/``sdmx1``/
                ``habanero``/``Bio.Entrez``/``arxiv`` call).
            *args: Positional arguments for ``func``.
            **kwargs: Keyword arguments for ``func``.

        Returns:
            The callable's return value.
        """
        loop = asyncio.get_running_loop()

        def _call():
            return func(*args, **kwargs)

        return await loop.run_in_executor(None, _call)

    def _build_citation(
        self,
        source_name: str,
        source_url: str,
        data_vintage: str | None = None,
        doi: str | None = None,
        license: str | None = None,
    ) -> Citation:
        """Build a :class:`Citation` for a successful result.

        Args:
            source_name: Human-readable source name.
            source_url: Direct URL to the data/paper.
            data_vintage: Best-effort source publish/update date.
            doi: DOI, if applicable.
            license: Data/content license, if known.

        Returns:
            A populated :class:`Citation`.
        """
        access_date = datetime.now(UTC).date().isoformat()
        formatted_citation = f"{source_name}. Retrieved {access_date} from {source_url}."
        return Citation(
            source_name=source_name,
            source_url=source_url,
            access_date=access_date,
            formatted_citation=formatted_citation,
            data_vintage=data_vintage,
            doi=doi,
            license=license,
        )

    def _failure(
        self,
        query: str,
        source: str,
        result_type: str,
        status: str,
        message: str,
    ) -> ResearchResult:
        """Canonical no_data / error result factory.

        Args:
            query: The original query string.
            source: Toolkit + method identifier.
            result_type: 'indicators' | 'papers' | 'datasets'.
            status: 'no_data' | 'error' (never 'success'/'partial' here).
            message: Human-readable failure reason.

        Returns:
            A :class:`ResearchResult` with ``citation is None`` and
            ``error_message`` populated.
        """
        return ResearchResult(
            query=query,
            source=source,
            result_type=result_type,
            status=status,
            error_message=message,
            total_results=0,
        )

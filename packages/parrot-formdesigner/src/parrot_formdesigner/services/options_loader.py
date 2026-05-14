"""OptionsLoader service for dynamic field option fetching.

Fetches ``FieldOption`` lists from remote ``OptionsSource`` endpoints using
``aiohttp.ClientSession``. Features:

- In-memory TTL cache (keyed by ``(source_ref, auth_ref)``)
- Single-flight per cache key — concurrent calls share one in-flight request
- Failure-safe — returns ``[]`` and logs a warning on any error, never raises

Pattern mirrors ``SubmissionForwarder`` for session lifecycle.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

import aiohttp

from ..core.options import FieldOption, OptionsSource
from .auth_context import AuthContext

logger = logging.getLogger(__name__)

# Cache key type: (source_ref, auth_ref)
_CacheKey = tuple[str, str | None]


class OptionsLoader:
    """Async service that fetches and caches ``FieldOption`` lists.

    Uses ``aiohttp.ClientSession`` for all HTTP requests. Auth headers are
    resolved via ``AuthContext.resolve_for(source.auth_ref)`` if an auth
    context is provided.

    Caching: in-memory dict keyed by ``(source_ref, auth_ref)`` with per-entry
    expiry timestamps derived from ``OptionsSource.cache_ttl_seconds``.

    Single-flight: concurrent calls for the same cache key share exactly one
    in-flight HTTP request via ``asyncio.Event`` + result sharing.

    Args:
        timeout: Request timeout in seconds. Defaults to ``DEFAULT_TIMEOUT``.
    """

    DEFAULT_TIMEOUT: int = 30

    def __init__(self, timeout: int = DEFAULT_TIMEOUT) -> None:
        """Initialise the loader with a configurable timeout.

        Args:
            timeout: HTTP request timeout in seconds.
        """
        self.timeout = timeout
        self.logger = logging.getLogger(__name__)
        # In-memory TTL cache: key → (options_list, expiry_timestamp)
        self._cache: dict[_CacheKey, tuple[list[FieldOption], float]] = {}
        # Single-flight coordination
        self._in_flight: dict[_CacheKey, asyncio.Event] = {}
        self._in_flight_results: dict[_CacheKey, list[FieldOption]] = {}

    async def fetch(
        self,
        source: OptionsSource,
        *,
        auth_context: AuthContext | None = None,
    ) -> list[FieldOption]:
        """Fetch and normalise options from the given ``OptionsSource``.

        Cache hit within TTL returns the cached list immediately. Cache miss
        triggers a single HTTP request; concurrent callers for the same key
        wait for that single request to complete.

        On any error (timeout, HTTP 4xx/5xx, parse failure), logs a warning
        and returns ``[]`` — never raises.

        Args:
            source: The ``OptionsSource`` describing the remote endpoint.
            auth_context: Optional runtime auth context for header resolution.

        Returns:
            List of ``FieldOption`` parsed from the response, or ``[]`` on error.
        """
        cache_key: _CacheKey = (source.source_ref, source.auth_ref)

        # 1. Check TTL cache
        cached = self._cache.get(cache_key)
        if cached is not None:
            options, expiry = cached
            if expiry == 0.0 or time.monotonic() < expiry:
                return list(options)

        # 2. Single-flight: if another coroutine is fetching this key, wait
        if cache_key in self._in_flight:
            event = self._in_flight[cache_key]
            await event.wait()
            return list(self._in_flight_results.get(cache_key, []))

        # 3. Mark as in-flight, perform the HTTP request
        event = asyncio.Event()
        self._in_flight[cache_key] = event
        try:
            options = await self._do_fetch(source, auth_context=auth_context)
        except Exception as exc:  # noqa: BLE001
            self.logger.warning(
                "OptionsLoader: unexpected error fetching '%s': %s",
                source.source_ref,
                exc,
            )
            options = []
        finally:
            # Store result for waiting coroutines before setting event
            self._in_flight_results[cache_key] = options
            event.set()
            # Clean up in-flight tracking
            self._in_flight.pop(cache_key, None)

        # 4. Cache result
        if source.cache_ttl_seconds and source.cache_ttl_seconds > 0:
            expiry = time.monotonic() + source.cache_ttl_seconds
        else:
            expiry = 0.0  # no expiry — cache until next cold miss
        self._cache[cache_key] = (options, expiry)

        # Clean up shared result after storing in proper cache
        self._in_flight_results.pop(cache_key, None)

        return list(options)

    async def _do_fetch(
        self,
        source: OptionsSource,
        *,
        auth_context: AuthContext | None,
    ) -> list[FieldOption]:
        """Perform the actual HTTP request and parse the response.

        Args:
            source: The ``OptionsSource`` describing the endpoint.
            auth_context: Optional auth context for header injection.

        Returns:
            Parsed ``FieldOption`` list.
        """
        headers: dict[str, str] = {}
        if auth_context is not None:
            headers.update(auth_context.resolve_for(source.auth_ref))

        timeout = aiohttp.ClientTimeout(total=self.timeout)
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                method = source.http_method.upper()
                if method == "POST":
                    request_cm = session.post(source.source_ref, headers=headers)
                else:
                    request_cm = session.get(source.source_ref, headers=headers)

                async with request_cm as response:
                    if response.status >= 400:
                        self.logger.warning(
                            "OptionsLoader: endpoint '%s' returned HTTP %d — returning []",
                            source.source_ref,
                            response.status,
                        )
                        return []
                    try:
                        raw: Any = await response.json(content_type=None)
                    except Exception as exc:
                        self.logger.warning(
                            "OptionsLoader: failed to decode JSON from '%s': %s",
                            source.source_ref,
                            exc,
                        )
                        return []

                    if not isinstance(raw, list):
                        self.logger.warning(
                            "OptionsLoader: expected list from '%s', got %s — returning []",
                            source.source_ref,
                            type(raw).__name__,
                        )
                        return []

                    return self._normalise(raw, source)

        except aiohttp.ClientError as exc:
            self.logger.warning(
                "OptionsLoader: HTTP error fetching '%s': %s",
                source.source_ref,
                exc,
            )
            return []
        except asyncio.TimeoutError:
            self.logger.warning(
                "OptionsLoader: timeout fetching '%s'",
                source.source_ref,
            )
            return []

    def _normalise(
        self,
        raw: list[Any],
        source: OptionsSource,
    ) -> list[FieldOption]:
        """Map raw API response items to ``FieldOption`` using field mappings.

        Args:
            raw: List of dicts from the remote API.
            source: The ``OptionsSource`` providing ``value_field`` and
                ``label_field`` mappings.

        Returns:
            Normalised list of ``FieldOption``.
        """
        options: list[FieldOption] = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            value = str(item.get(source.value_field, ""))
            label = str(item.get(source.label_field, value))
            options.append(FieldOption(value=value, label=label))
        return options

    def invalidate(self, source_ref: str, auth_ref: str | None = None) -> None:
        """Remove a specific cache entry.

        Args:
            source_ref: The endpoint URL to invalidate.
            auth_ref: The auth reference to invalidate (or None).
        """
        self._cache.pop((source_ref, auth_ref), None)

    def clear_cache(self) -> None:
        """Clear all cached option lists."""
        self._cache.clear()

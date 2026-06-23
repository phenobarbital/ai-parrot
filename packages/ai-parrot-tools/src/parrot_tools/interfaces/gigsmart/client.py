"""GigSmart GraphQL client — aiohttp-based transport with retry and error classification.

Features:
- GraphQL POST via aiohttp.ClientSession with OAuth 2.1 header injection
- Error classification: maps ``extensions.code`` to typed exceptions
- Relay auto-pagination: fetch all nodes from a paginated connection
- Retry with exponential backoff for transient errors (5xx, 429)
- Concurrency limiting via asyncio.Semaphore
- PII scrubbing in log output (controlled by config.log_pii)
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any

import aiohttp

from parrot_tools.interfaces.gigsmart.auth import GigSmartAuth
from parrot_tools.interfaces.gigsmart.config import GigSmartConfig
from parrot_tools.interfaces.gigsmart.exceptions import (
    GigSmartAuthError,
    GigSmartConflictError,
    GigSmartError,
    GigSmartGraphQLError,
    GigSmartNotFoundError,
    GigSmartRateLimitError,
    GigSmartTransportError,
    GigSmartValidationError,
)

# ---------------------------------------------------------------------------
# Error code → exception class mapping
# ---------------------------------------------------------------------------

_ERROR_CODE_MAP: dict[str, type[GigSmartError]] = {
    "UNAUTHENTICATED": GigSmartAuthError,
    "FORBIDDEN": GigSmartAuthError,
    "BAD_USER_INPUT": GigSmartValidationError,
    "NOT_FOUND": GigSmartNotFoundError,
    "CONFLICT": GigSmartConflictError,
    "RATE_LIMITED": GigSmartRateLimitError,
}

# These status codes or error codes are retryable
_RETRYABLE_STATUS_CODES = frozenset({500, 502, 503, 504})

# ---------------------------------------------------------------------------
# PII scrubbing patterns
# ---------------------------------------------------------------------------

_PII_FIELD_PATTERNS = [
    re.compile(r'"workerDisplayName"\s*:\s*"[^"]*"', re.IGNORECASE),
    re.compile(r'"displayName"\s*:\s*"[^"]*"', re.IGNORECASE),
    re.compile(r'"address"\s*:\s*"[^"]*"', re.IGNORECASE),
    re.compile(r'"email"\s*:\s*"[^"]*"', re.IGNORECASE),
    re.compile(r'"phoneNumber"\s*:\s*"[^"]*"', re.IGNORECASE),
]

_AUTH_HEADER_PATTERN = re.compile(r"Bearer\s+[A-Za-z0-9._\-]+")


def _scrub_pii(text: str) -> str:
    """Replace PII values in *text* with ``<redacted>``."""
    for pattern in _PII_FIELD_PATTERNS:
        text = pattern.sub(lambda m: m.group(0).split(":")[0] + ': "<redacted>"', text)
    text = _AUTH_HEADER_PATTERN.sub("Bearer <token>", text)
    return text


def _extract_path(data: dict, path: str) -> dict:
    """Navigate a nested dict following a dot-separated *path*.

    Args:
        data: The GraphQL ``data`` dict.
        path: Dot-separated key path, e.g. ``"organization.gigs"``.

    Returns:
        The nested dict at the path.

    Raises:
        KeyError: If the path does not exist in the data.
        TypeError: If a node along the path is None.
    """
    node = data
    for key in path.split("."):
        node = node[key]
    return node


# ---------------------------------------------------------------------------
# GigSmartClient
# ---------------------------------------------------------------------------


class GigSmartClient:
    """aiohttp-based GraphQL client for the GigSmart API.

    Usage::

        config = GigSmartConfig(client_id="...", client_secret="...")
        async with GigSmartClient(config) as client:
            data = await client.execute("query { viewer { id } }")

    Args:
        config: GigSmartConfig carrying endpoint URLs and credentials.
    """

    # Retry configuration
    _MAX_RETRIES = 3
    _BACKOFF_BASE = 1.0  # seconds — backoff: 1s, 2s, 4s

    def __init__(self, config: GigSmartConfig) -> None:
        self._config = config
        self._auth = GigSmartAuth(config)
        self._session: aiohttp.ClientSession | None = None
        self._semaphore = asyncio.Semaphore(config.max_concurrent_requests)
        self._session_lock = asyncio.Lock()
        self.logger = logging.getLogger(__name__)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Open the underlying aiohttp.ClientSession."""
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=self._config.request_timeout)
            self._session = aiohttp.ClientSession(timeout=timeout)

    async def close(self) -> None:
        """Close the underlying aiohttp.ClientSession."""
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None

    async def __aenter__(self) -> "GigSmartClient":
        await self.start()
        return self

    async def __aexit__(self, *exc_info: Any) -> None:
        await self.close()

    # ------------------------------------------------------------------
    # Core execute
    # ------------------------------------------------------------------

    async def execute(
        self,
        document: str,
        variables: dict | None = None,
        *,
        operation_name: str | None = None,
        is_mutation: bool = False,
    ) -> dict:
        """Execute a GraphQL operation against the GigSmart API.

        Handles authentication header injection, error classification,
        partial-success policy (queries warn; mutations raise), and
        concurrency limiting.

        Args:
            document: The GraphQL query or mutation string.
            variables: Optional dict of GraphQL variables.
            operation_name: Optional operation name hint (for logging).
            is_mutation: When True, any errors in the response raise
                immediately (no partial-success tolerance).

        Returns:
            The ``data`` dict from the GraphQL response.

        Raises:
            GigSmartAuthError: On UNAUTHENTICATED or FORBIDDEN errors.
            GigSmartValidationError: On BAD_USER_INPUT errors.
            GigSmartNotFoundError: On NOT_FOUND errors.
            GigSmartRateLimitError: On HTTP 429.
            GigSmartTransportError: On HTTP 5xx or network failures.
            GigSmartConflictError: On CONFLICT errors.
            GigSmartGraphQLError: On any other GraphQL error.
        """
        session = await self._ensure_session()
        headers = await self._auth.build_headers()
        headers["Content-Type"] = "application/json"

        payload: dict[str, Any] = {"query": document}
        if variables:
            payload["variables"] = variables
        if operation_name:
            payload["operationName"] = operation_name

        async with self._semaphore:
            return await self._execute_with_retry(
                session, headers, payload, is_mutation=is_mutation
            )

    # ------------------------------------------------------------------
    # Relay auto-pagination
    # ------------------------------------------------------------------

    async def paginate(
        self,
        document: str,
        variables: dict,
        extract_path: str,
        page_size: int = 25,
    ) -> list[dict]:
        """Fetch all pages of a Relay connection and return all nodes.

        Args:
            document: A GraphQL list query using Relay pagination.
            variables: Base variables dict (``first`` and ``after`` will be
                injected / overwritten by this method).
            extract_path: Dot-separated path from the ``data`` dict to the
                Relay connection field, e.g. ``"organization.gigs"``.
            page_size: Number of items to request per page.

        Returns:
            A flat list of all node dicts across all pages.
        """
        all_nodes: list[dict] = []
        after: str | None = None

        while True:
            page_vars = {**variables, "first": page_size, "after": after}
            data = await self.execute(document, page_vars)

            try:
                connection = _extract_path(data, extract_path)
            except (KeyError, TypeError) as exc:
                raise GigSmartError(
                    f"paginate: path '{extract_path}' not found in response data. "
                    f"Available keys: {list(data.keys())}"
                ) from exc

            edges = connection.get("edges", [])
            all_nodes.extend(edge["node"] for edge in edges if "node" in edge)

            page_info = connection.get("pageInfo", {})
            if not page_info.get("hasNextPage", False):
                break
            after = page_info.get("endCursor")
            if not after:
                break

        return all_nodes

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _ensure_session(self) -> aiohttp.ClientSession:
        """Return the active session, opening one if necessary."""
        if self._session is not None and not self._session.closed:
            return self._session
        async with self._session_lock:
            # Double-check after acquiring lock
            if self._session is None or self._session.closed:
                await self.start()
        return self._session  # type: ignore[return-value]

    async def _execute_with_retry(
        self,
        session: aiohttp.ClientSession,
        headers: dict[str, str],
        payload: dict,
        is_mutation: bool,
    ) -> dict:
        """Execute *payload* with retry logic for transient errors.

        Retries up to _MAX_RETRIES times with exponential backoff on
        5xx responses and rate-limit errors. Does not retry 4xx.

        Args:
            session: The aiohttp.ClientSession to use.
            headers: Request headers (including Authorization).
            payload: The JSON body dict.
            is_mutation: Determines partial-success policy.

        Returns:
            The parsed ``data`` dict.
        """
        last_exc: Exception | None = None

        for attempt in range(self._MAX_RETRIES + 1):
            try:
                return await self._do_request(session, headers, payload, is_mutation)
            except GigSmartRateLimitError as exc:
                last_exc = exc
                wait = exc.retry_after
                log_msg = f"Rate limited; retrying in {wait}s (attempt {attempt + 1})"
                if not self._config.log_pii:
                    log_msg = _scrub_pii(log_msg)
                self.logger.warning(log_msg)
                if attempt < self._MAX_RETRIES:
                    await asyncio.sleep(wait)
                else:
                    raise
            except GigSmartTransportError as exc:
                last_exc = exc
                backoff = self._BACKOFF_BASE * (2 ** attempt)
                self.logger.warning(
                    "Transient error on attempt %d/%d; retrying in %.1fs: %s",
                    attempt + 1,
                    self._MAX_RETRIES + 1,
                    backoff,
                    exc,
                )
                if attempt < self._MAX_RETRIES:
                    await asyncio.sleep(backoff)
                else:
                    raise

        # Should not reach here
        raise last_exc or GigSmartError("Unknown retry failure")

    async def _do_request(
        self,
        session: aiohttp.ClientSession,
        headers: dict[str, str],
        payload: dict,
        is_mutation: bool,
    ) -> dict:
        """Perform a single HTTP POST and classify the response.

        Args:
            session: Active aiohttp.ClientSession.
            headers: Request headers.
            payload: JSON body.
            is_mutation: Partial-success policy flag.

        Returns:
            The ``data`` dict from the response.

        Raises:
            Appropriate GigSmartError subclass based on status or error codes.
        """
        try:
            async with session.post(
                self._config.endpoint_url,
                json=payload,
                headers=headers,
            ) as resp:
                if resp.status == 429:
                    retry_after_str = resp.headers.get("Retry-After", "60")
                    try:
                        retry_after = int(retry_after_str)
                    except ValueError:
                        retry_after = 60
                    raise GigSmartRateLimitError(
                        "GigSmart API rate limit exceeded (429)",
                        retry_after=retry_after,
                    )

                if resp.status in _RETRYABLE_STATUS_CODES:
                    raise GigSmartTransportError(
                        f"GigSmart API server error (HTTP {resp.status})",
                        status_code=resp.status,
                    )

                if resp.status >= 400:
                    body_text = await resp.text()
                    raise GigSmartError(
                        f"GigSmart API unexpected HTTP {resp.status}: {body_text[:200]}",
                        status_code=resp.status,
                    )

                body: dict = await resp.json(content_type=None)

        except aiohttp.ClientError as exc:
            raise GigSmartTransportError(
                f"Network error communicating with GigSmart API: {exc}"
            ) from exc

        errors = body.get("errors")
        data = body.get("data")

        if errors:
            if is_mutation or data is None:
                # Mutations raise on any error; queries with no data also raise
                self._raise_from_errors(errors)
            else:
                # Partial success on queries: log and return degraded data
                log_payload = str(errors)
                if not self._config.log_pii:
                    log_payload = _scrub_pii(log_payload)
                self.logger.warning("GigSmart partial query errors: %s", log_payload)

        return data or {}

    def _raise_from_errors(self, errors: list[dict]) -> None:
        """Classify and raise the appropriate exception for *errors*.

        Uses the first error's ``extensions.code`` for classification.
        Falls back to ``GigSmartGraphQLError`` for unrecognised codes.

        Args:
            errors: The raw ``errors`` list from the GraphQL response.

        Raises:
            An appropriate GigSmartError subclass.
        """
        first = errors[0] if errors else {}
        message = first.get("message", "GraphQL error")
        code = first.get("extensions", {}).get("code", "")

        exc_class = _ERROR_CODE_MAP.get(code, GigSmartGraphQLError)

        if exc_class is GigSmartRateLimitError:
            raise GigSmartRateLimitError(message, retry_after=60)
        elif exc_class is GigSmartGraphQLError:
            raise GigSmartGraphQLError(message, errors=errors)
        else:
            raise exc_class(message)

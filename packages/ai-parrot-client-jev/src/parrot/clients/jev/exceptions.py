"""Exceptions raised by :class:`~parrot.clients.jev.JevClient`.

The HTTP status → exception mapping mirrors the official ``typesafe-sdk``
(``TypeSafeBadRequestError`` for 400, ``TypeSafeAuthenticationError`` for 401,
… ``TypeSafeInternalServerError`` for 5xx) so callers migrating from the
vendor SDK find the same categories under the ``parrot`` namespace.
"""

from __future__ import annotations

import math
import time
from email.utils import parsedate_to_datetime
from typing import Any, Mapping, Optional

from parrot.exceptions import ParrotError

#: Header carrying the server-assigned id of a request (useful in support tickets).
REQUEST_ID_HEADER = "x-typesafe-request-id"
_RETRY_AFTER_HEADER = "retry-after"
_RETRY_AFTER_MS_HEADER = "retry-after-ms"
_MAX_ERROR_BODY_LENGTH = 200


class JevError(ParrotError):
    """Base class for every error raised by the Jev client."""


class JevConfigurationError(JevError):
    """A request could not be built: missing API key, no questions, bad state."""


class JevSchemaError(JevError):
    """A Pydantic output type cannot be mapped onto System One questions (or back)."""


class JevConnectionError(JevError):
    """The request never produced an HTTP response (connection failure or timeout)."""


class JevAPIError(JevError):
    """An unsuccessful HTTP response from the TypeSafe API.

    Attributes:
        status: HTTP status code.
        body: Decoded JSON error body, raw text, or ``None`` when empty.
        request_id: The ``x-typesafe-request-id`` header when present.
        retry_after: Server-requested wait in seconds, parsed from
            ``retry-after-ms`` / ``retry-after``; ``None`` when absent.
    """

    def __init__(
        self,
        message: str,
        *,
        status: int,
        body: Any = None,
        request_id: Optional[str] = None,
        retry_after: Optional[float] = None,
    ) -> None:
        text = f"{status} {message}" if message else str(status)
        if request_id:
            text = f"{text} (request_id={request_id})"
        super().__init__(text)
        self.status: int = status
        self.body: Any = body
        self.request_id: Optional[str] = request_id
        self.retry_after: Optional[float] = retry_after


class JevBadRequestError(JevAPIError):
    """The request was rejected as invalid (400) or failed server validation (422)."""


class JevAuthenticationError(JevAPIError):
    """Authentication failed (401) or access was denied (403)."""


class JevNotFoundError(JevAPIError):
    """The endpoint or model was not found (404)."""


class JevRateLimitError(JevAPIError):
    """The rate limit was exceeded (429)."""


class JevServerError(JevAPIError):
    """The server failed to process the request (5xx)."""


_STATUS_ERROR_TYPES: dict[int, type[JevAPIError]] = {
    400: JevBadRequestError,
    401: JevAuthenticationError,
    403: JevAuthenticationError,
    404: JevNotFoundError,
    422: JevBadRequestError,
    429: JevRateLimitError,
}


def parse_retry_after(headers: Mapping[str, str]) -> Optional[float]:
    """Read the server's requested wait from the response headers.

    Honors ``retry-after-ms`` first, then ``retry-after`` (seconds or an
    HTTP-date), mirroring the vendor SDK.

    Args:
        headers: Response headers (case-insensitive mapping preferred).

    Returns:
        The wait in **seconds**, or ``None`` when no usable header is present.
    """
    for name, divisor in ((_RETRY_AFTER_MS_HEADER, 1000.0), (_RETRY_AFTER_HEADER, 1.0)):
        raw = headers.get(name)
        if raw is None:
            continue
        raw = raw.strip()
        try:
            value = float(raw or "0")
        except ValueError:
            if name == _RETRY_AFTER_HEADER:
                try:
                    return max(0.0, parsedate_to_datetime(raw).timestamp() - time.time())
                except (ValueError, TypeError, OverflowError):
                    continue
            continue
        if math.isfinite(value) and value >= 0:
            return value / divisor
    return None


def extract_message(body: Any) -> Optional[str]:
    """Pull a human-readable message out of an API error body.

    Understands the shapes the TypeSafe API emits: a bare string, ``{"error":
    ...}``, ``{"message": ...}``, ``{"detail": ...}`` and FastAPI-style
    ``{"detail": [{"loc": [...], "msg": ...}, ...]}`` validation lists.

    Args:
        body: Decoded JSON body or raw text.

    Returns:
        The extracted message, or ``None`` when nothing usable was found.
    """
    if isinstance(body, str):
        return body or None
    if not isinstance(body, dict):
        return None
    error, message, detail = body.get("error"), body.get("message"), body.get("detail")
    if isinstance(error, str):
        return error
    if isinstance(error, dict) and isinstance(error.get("message"), str):
        return error["message"]
    if isinstance(message, str):
        return message
    if isinstance(detail, str):
        return detail
    if isinstance(detail, dict) and isinstance(detail.get("message"), str):
        return detail["message"]
    if isinstance(detail, list):
        parts = []
        for entry in detail:
            if not isinstance(entry, dict) or not isinstance(entry.get("msg"), str):
                continue
            location = entry.get("loc")
            path = ".".join(str(item) for item in location if item != "body") if isinstance(location, list) else ""
            parts.append(f"{path}: {entry['msg']}" if path else entry["msg"])
        return "; ".join(parts) or None
    return None


def api_error(
    status: int,
    body: Any,
    headers: Optional[Mapping[str, str]] = None,
) -> JevAPIError:
    """Build the :class:`JevAPIError` subclass matching an HTTP status.

    Args:
        status: HTTP status code of the failed response.
        body: Decoded JSON body, raw text, or ``None``.
        headers: Response headers, used for the request id and retry hints.

    Returns:
        A ready-to-raise :class:`JevAPIError` (or subclass) instance.
    """
    headers = headers or {}
    message = extract_message(body)
    if message is None:
        if body is None:
            message = "status code (no body)"
        else:
            raw = body if isinstance(body, str) else repr(body)
            message = raw[:_MAX_ERROR_BODY_LENGTH] + "…" if len(raw) > _MAX_ERROR_BODY_LENGTH else raw
    error_type = _STATUS_ERROR_TYPES.get(status, JevServerError if status >= 500 else JevAPIError)
    return error_type(
        message,
        status=status,
        body=body,
        request_id=headers.get(REQUEST_ID_HEADER),
        retry_after=parse_retry_after(headers),
    )

"""RemoteResponseResolver service for REMOTE_RESPONSE field type.

Calls an external API on behalf of a ``REMOTE_RESPONSE`` form field and
returns the API response as the field value. Mirrors ``SubmissionForwarder``
pattern from ``services/forwarder.py``.

No memoisation — every call hits the endpoint. Callers must ensure endpoint
idempotency when repeated calls are a concern.
"""

from __future__ import annotations

import logging
from typing import Any, Literal

import aiohttp
from pydantic import BaseModel, ConfigDict

from .auth_context import AuthContext

logger = logging.getLogger(__name__)


class RemoteResponseSpec(BaseModel):
    """Configuration for a REMOTE_RESPONSE field embedded in ``FormField.meta``.

    Attributes:
        endpoint: URL of the external API to call.
        http_method: HTTP verb to use. Defaults to "POST".
        content_field: Other field ID whose value is sent as request body
            (resolved by the caller before invoking the resolver).
        prompt: Optional prompt string sent alongside content.
        auth_ref: Reference key into the ``AuthContext`` credentials store.
        timeout_seconds: Per-request timeout in seconds. Defaults to 30.
        response_schema: Optional JSON Schema dict to validate the API response.
            Validation is informational — the resolver never rejects a valid 2xx.
    """

    model_config = ConfigDict(extra="forbid")

    endpoint: str
    http_method: Literal["GET", "POST"] = "POST"
    content_field: str | None = None
    prompt: str | None = None
    auth_ref: str | None = None
    timeout_seconds: int = 30
    response_schema: dict[str, Any] | None = None


class RemoteResponseResult(BaseModel):
    """Result of a ``RemoteResponseResolver.resolve()`` call.

    Attributes:
        success: True when the endpoint returned a 2xx response.
        value: Parsed response value (JSON) from the endpoint.
        status_code: HTTP status code received from the endpoint (if any).
        error: Human-readable error message when ``success`` is False.
    """

    success: bool
    value: Any | None = None
    status_code: int | None = None
    error: str | None = None


class RemoteResponseResolver:
    """Resolve REMOTE_RESPONSE fields by calling an external API.

    Mirrors ``SubmissionForwarder`` aiohttp + auth pattern. Every call hits
    the endpoint — no memoisation. Callers must ensure endpoint idempotency
    if needed.

    Attributes:
        DEFAULT_TIMEOUT: Default request timeout in seconds (30).
        timeout: Configured timeout for this resolver instance.

    Args:
        timeout: Request timeout in seconds. Defaults to ``DEFAULT_TIMEOUT``.
    """

    DEFAULT_TIMEOUT: int = 30

    def __init__(self, timeout: int = DEFAULT_TIMEOUT) -> None:
        """Initialise the resolver with a configurable timeout.

        Args:
            timeout: HTTP request timeout in seconds.
        """
        self.timeout = timeout
        self.logger = logging.getLogger(__name__)

    async def resolve(
        self,
        spec: RemoteResponseSpec,
        content: Any,
        *,
        auth_context: AuthContext | None = None,
    ) -> RemoteResponseResult:
        """Call the external API and return its response as the field value.

        Sends ``{"content": content}`` (plus ``"prompt"`` if present in spec)
        as the JSON request body for POST, or as query parameters for GET.

        Args:
            spec: The ``RemoteResponseSpec`` from ``FormField.meta``.
            content: The content to send (typically from the ``content_field``
                value resolved by the caller).
            auth_context: Optional runtime auth context for header injection.

        Returns:
            ``RemoteResponseResult`` — never raises, captures all errors.
        """
        headers: dict[str, str] = {}
        if auth_context is not None:
            headers.update(auth_context.resolve_for(spec.auth_ref))

        payload: dict[str, Any] = {"content": content}
        if spec.prompt:
            payload["prompt"] = spec.prompt

        effective_timeout = spec.timeout_seconds if spec.timeout_seconds else self.timeout
        timeout = aiohttp.ClientTimeout(total=effective_timeout)

        try:
            async with aiohttp.ClientSession(headers=headers, timeout=timeout) as session:
                method_name = spec.http_method.lower()
                http_method = getattr(session, method_name)

                if spec.http_method == "GET":
                    request_kwargs: dict[str, Any] = {"params": payload}
                else:
                    request_kwargs = {"json": payload}

                async with http_method(spec.endpoint, **request_kwargs) as resp:
                    status = resp.status
                    if 200 <= status < 400:
                        try:
                            value = await resp.json(content_type=None)
                        except Exception:
                            value = await resp.text()
                        return RemoteResponseResult(
                            success=True,
                            value=value,
                            status_code=status,
                        )
                    else:
                        try:
                            text = await resp.text()
                            error_detail = text[:200] if text else f"HTTP {status}"
                        except Exception:
                            error_detail = f"HTTP {status}"
                        self.logger.warning(
                            "RemoteResponseResolver: endpoint '%s' returned HTTP %d",
                            spec.endpoint,
                            status,
                        )
                        return RemoteResponseResult(
                            success=False,
                            status_code=status,
                            error=error_detail,
                        )

        except aiohttp.ClientError as exc:
            self.logger.warning(
                "RemoteResponseResolver: HTTP client error for '%s': %s",
                spec.endpoint,
                exc,
            )
            return RemoteResponseResult(success=False, error=str(exc))

        except Exception as exc:  # noqa: BLE001
            self.logger.warning(
                "RemoteResponseResolver: unexpected error for '%s': %s",
                spec.endpoint,
                exc,
            )
            return RemoteResponseResult(success=False, error=str(exc))

"""Submission forwarding service.

Sends validated form submission data to the external URL configured in a
``SubmitAction`` using ``aiohttp.ClientSession``. Authentication headers are
resolved at forwarding time via ``AuthConfig.resolve()`` — credentials are
never stored in the form schema.

The ``forward()`` method never raises — it always returns a ``ForwardResult``.
"""

from __future__ import annotations

import logging
from typing import Any

import aiohttp
from pydantic import BaseModel

from ..core.schema import SubmitAction


class ForwardResult(BaseModel):
    """Result of a submission forwarding attempt.

    Attributes:
        success: ``True`` when the remote endpoint returned a 2xx/3xx response.
        status_code: HTTP status code received from the remote endpoint (if any).
        error: Human-readable error message when ``success`` is ``False``.
    """

    success: bool
    status_code: int | None = None
    error: str | None = None


class SubmissionForwarder:
    """Forward form submission data to configured SubmitAction endpoints.

    Uses ``aiohttp.ClientSession`` for all HTTP requests. Auth headers are
    resolved via ``submit_action.auth.resolve()`` if auth is configured.

    Attributes:
        DEFAULT_TIMEOUT: Default request timeout in seconds (30).
        timeout: Configured timeout for this forwarder instance.

    Args:
        timeout: Request timeout in seconds. Defaults to ``DEFAULT_TIMEOUT``.
    """

    DEFAULT_TIMEOUT: int = 30

    def __init__(self, timeout: int = DEFAULT_TIMEOUT) -> None:
        """Initialise the forwarder with a configurable timeout.

        Args:
            timeout: HTTP request timeout in seconds.
        """
        self.timeout = timeout
        self.logger = logging.getLogger(__name__)

    async def forward(
        self,
        data: dict[str, Any],
        submit_action: SubmitAction,
    ) -> ForwardResult:
        """Forward submission data to the endpoint configured in ``submit_action``.

        Only forwards when ``submit_action.action_type == "endpoint"``.
        Auth headers are resolved from ``submit_action.auth`` if set.
        Network errors are caught and returned as a failed ``ForwardResult``.

        Args:
            data: The validated (sanitized) submission data to send as JSON.
            submit_action: The ``SubmitAction`` defining URL, method, and auth.

        Returns:
            A ``ForwardResult`` describing the outcome. Never raises.
        """
        if submit_action.action_type != "endpoint":
            return ForwardResult(
                success=False,
                error=f"Cannot forward: action_type is '{submit_action.action_type}', expected 'endpoint'",
            )

        headers: dict[str, str] = {"Content-Type": "application/json"}

        # Resolve auth headers (if configured)
        if submit_action.auth is not None:
            try:
                auth_headers = submit_action.auth.resolve()
                headers.update(auth_headers)
            except ValueError as exc:
                self.logger.warning(
                    "Auth resolution failed for %s: %s",
                    submit_action.action_ref,
                    exc,
                )
                return ForwardResult(
                    success=False,
                    error=f"Auth resolution failed: {exc}",
                )

        # Send the HTTP request
        try:
            timeout = aiohttp.ClientTimeout(total=self.timeout)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.request(
                    method=submit_action.method,
                    url=submit_action.action_ref,
                    json=data,
                    headers=headers,
                ) as resp:
                    success = resp.status < 400
                    if not success:
                        self.logger.warning(
                            "Forward to %s returned status %d",
                            submit_action.action_ref,
                            resp.status,
                        )
                    return ForwardResult(
                        success=success,
                        status_code=resp.status,
                    )
        except Exception as exc:  # noqa: BLE001
            self.logger.warning(
                "Forward to %s failed: %s",
                submit_action.action_ref,
                exc,
            )
            return ForwardResult(success=False, error=str(exc))

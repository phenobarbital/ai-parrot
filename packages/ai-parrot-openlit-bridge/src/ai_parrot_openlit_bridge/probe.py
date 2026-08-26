"""OTLP endpoint validation probe.

FEAT-462 — Unified Telemetry Bus. Replaces the `openlit` SDK's monkey-
patching init with a best-effort, non-blocking OTLP endpoint reachability
check — used at boot time (optionally) to surface a friendly diagnostic
when the configured OpenLIT/OTLP collector endpoint is unreachable.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import aiohttp

logger = logging.getLogger(__name__)


@dataclass
class EndpointStatus:
    """Result of an OTLP endpoint probe.

    Attributes:
        reachable: Whether the endpoint responded to the probe request.
        status_code: HTTP status code returned by the endpoint, when
            reachable.
        collector_info: Value of the response's ``Server`` header, when
            present — a hint at which collector is listening (e.g.
            ``"otel-collector"``).
        error: String representation of the exception raised while
            probing, when unreachable.
    """

    reachable: bool
    status_code: int | None = None
    collector_info: str | None = None
    error: str | None = None


async def validate_endpoint(
    url: str,
    *,
    timeout: float = 5.0,
    headers: dict[str, str] | None = None,
) -> EndpointStatus:
    """Probe an OTLP endpoint for reachability.

    Sends a lightweight, empty-body POST to the standard OTLP HTTP traces
    path (``/v1/traces``) and reports whether the endpoint responded. This
    is a best-effort diagnostic — it never raises; any error (connection
    refused, timeout, DNS failure, …) is captured in the returned
    ``EndpointStatus.error`` instead.

    Args:
        url: OTLP base URL (e.g. ``"http://localhost:4318"``).
        timeout: Request timeout in seconds. Default ``5.0``.
        headers: Optional extra headers (e.g. auth) forwarded to the probe
            request.

    Returns:
        An ``EndpointStatus`` describing the probe outcome.
    """
    health_url = f"{url.rstrip('/')}/v1/traces"
    try:
        async with (
            aiohttp.ClientSession() as session,
            session.post(
                health_url,
                headers=headers or {},
                timeout=aiohttp.ClientTimeout(total=timeout),
                data=b"",  # empty POST — we only care about reachability
            ) as resp,
        ):
            return EndpointStatus(
                reachable=True,
                status_code=resp.status,
                collector_info=resp.headers.get("server"),
            )
    except Exception as exc:  # noqa: BLE001 — best-effort probe, never raises
        logger.debug("validate_endpoint: %s unreachable: %s", url, exc)
        return EndpointStatus(
            reachable=False,
            error=str(exc),
        )

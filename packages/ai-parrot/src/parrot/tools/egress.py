"""Egress guard for the HTTP sessions tools open themselves (PA-13, defence in depth).

A host that lets tenants offer tools which fetch URLs (RSS item links, Word documents, wiki sources) enables the guard
with ``app[STUDIO_EGRESS_GUARD] = True`` (``parrot.handlers.studio`` copies it to this process on startup). While it
is off every factory here returns a plain ``aiohttp.ClientSession``: behaviour is unchanged.

When it is on, :func:`egress_session` returns a session whose connector

* resolves names itself (:class:`GuardedResolver`), REFUSES every address that is not globally routable (private,
  loopback, link-local incl. the cloud metadata address, unspecified, reserved, multicast) and hands aiohttp only the
  vetted addresses, so the socket connects to the address that was checked (no second lookup, no DNS rebinding);
* checks literal IP hosts (which aiohttp never resolves) and ``localhost`` names on the first request and on EVERY
  redirect hop, through trace hooks.

This does not cover browser-driven tools (Selenium/Playwright resolve and follow redirects on their own); for those the
cluster NetworkPolicy / egress proxy is the only control.
"""

from __future__ import annotations

import ipaddress
import socket
from typing import Any, Optional
from urllib.parse import urlparse

import aiohttp
from aiohttp.abc import AbstractResolver, ResolveResult
from yarl import URL

STUDIO_EGRESS_GUARD = "studio_egress_guard"
FEATURES = frozenset({"egress_guard"})

_ENABLED = False


class EgressBlocked(aiohttp.ClientError, OSError):
    """A fetch was refused because its target is not a public address (a transport error to callers: ``ClientError``)."""


def configure(enabled: bool) -> None:
    """Turn the guard on or off for this process (the host's ``app[STUDIO_EGRESS_GUARD]``)."""
    global _ENABLED
    _ENABLED = bool(enabled)


def is_enabled() -> bool:
    """Whether :func:`egress_session` currently returns guarded sessions."""
    return _ENABLED


def is_public_address(address: str) -> bool:
    """``True`` only for a globally routable IP literal; anything unparsable is refused."""
    try:
        ip = ipaddress.ip_address(address.split("%", 1)[0])
    except ValueError:
        return False
    if getattr(ip, "ipv4_mapped", None) is not None:
        ip = ip.ipv4_mapped
    return not (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_unspecified
        or ip.is_reserved
        or ip.is_multicast
        or not ip.is_global
    )


def _coerce_literal(host: str) -> Optional[str]:
    """The IP a literal or numeric-encoded host stands for (``2130706433``, ``0x7f000001``), else ``None``."""
    try:
        return str(ipaddress.ip_address(host))
    except ValueError:
        pass
    try:
        if host.isdigit():
            return str(ipaddress.ip_address(int(host)))
        if host.lower().startswith("0x"):
            return str(ipaddress.ip_address(int(host, 16)))
    except ValueError:
        pass
    return None


def check_url(url: Any) -> None:
    """Raise :class:`EgressBlocked` when ``url`` names ``localhost`` or a non-public IP literal.

    Hostnames are NOT resolved here (the connector's :class:`GuardedResolver` does that, once, for the real connect).
    """
    parsed = urlparse(str(url))
    host = (parsed.hostname or "").lower()
    if not host:
        raise EgressBlocked(f"egress refused: no host in {str(url)!r}")
    if host == "localhost" or host.endswith(".localhost"):
        raise EgressBlocked(f"egress refused: loopback host {host!r}")
    literal = _coerce_literal(host)
    if literal is not None and not is_public_address(literal):
        raise EgressBlocked(f"egress refused: non-public address {host!r}")


class GuardedResolver(AbstractResolver):
    """Resolve with the system resolver and drop (or refuse) every non-public answer.

    aiohttp connects to the addresses returned here and never looks the name up again. A name that has ANY
    non-public answer is refused outright (a mixed answer is how rebinding tricks try to slip a private address in).
    """

    def __init__(self, inner: Optional[AbstractResolver] = None) -> None:
        self._inner = inner or aiohttp.ThreadedResolver()

    async def resolve(self, host: str, port: int = 0, family: int = socket.AF_INET) -> list[ResolveResult]:
        """Resolved addresses of ``host``, all public; :class:`EgressBlocked` otherwise."""
        check_url(f"//{host}")
        results = await self._inner.resolve(host, port, family)
        if not results:
            raise EgressBlocked(f"egress refused: {host!r} did not resolve")
        blocked = [r["host"] for r in results if not is_public_address(r["host"])]
        if blocked:
            raise EgressBlocked(f"egress refused: {host!r} resolves to non-public {blocked[0]!r}")
        return results

    async def close(self) -> None:
        """Close the wrapped resolver."""
        await self._inner.close()


def _trace_config() -> aiohttp.TraceConfig:
    """Trace hooks that vet literal hosts on the first request and on every redirect hop."""
    trace = aiohttp.TraceConfig()

    async def _on_start(_session, _ctx, params) -> None:
        check_url(params.url)

    async def _on_redirect(_session, _ctx, params) -> None:
        location = params.response.headers.get("Location", "")
        check_url(params.url.join(URL(location)) if location else params.url)

    trace.on_request_start.append(_on_start)
    trace.on_request_redirect.append(_on_redirect)
    return trace


def guarded_session(**kwargs: Any) -> aiohttp.ClientSession:
    """A guarded ``ClientSession`` regardless of the host switch (used by :func:`egress_session` and tests)."""
    connector = kwargs.pop("connector", None) or aiohttp.TCPConnector(resolver=GuardedResolver())
    traces = list(kwargs.pop("trace_configs", None) or [])
    traces.append(_trace_config())
    return aiohttp.ClientSession(connector=connector, trace_configs=traces, **kwargs)


def egress_session(**kwargs: Any) -> aiohttp.ClientSession:
    """The one factory tools use for their own HTTP sessions: guarded when the host enabled it, plain otherwise."""
    if _ENABLED:
        return guarded_session(**kwargs)
    return aiohttp.ClientSession(**kwargs)


__all__ = [
    "EgressBlocked",
    "FEATURES",
    "GuardedResolver",
    "STUDIO_EGRESS_GUARD",
    "check_url",
    "configure",
    "egress_session",
    "guarded_session",
    "is_enabled",
    "is_public_address",
]

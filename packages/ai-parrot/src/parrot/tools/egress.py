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
import re
import socket
import unicodedata
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


_INTERNAL_SUFFIXES = (".localhost", ".local", ".localdomain", ".internal", ".intranet", ".lan", ".home", ".corp", ".svc")
_NUMERIC_HOST = re.compile(r"^[0-9a-fx.]+$", re.IGNORECASE)


def _canonical_host(host: str) -> str:
    """The host as a browser/stack sees it: NFKC + IDNA folded (full-width digits), lower-cased, no trailing dots.

    ``ValueError`` when it cannot be put in canonical ASCII form (refused by the caller).
    """
    folded = unicodedata.normalize("NFKC", host).strip().lower().rstrip(".")
    try:
        return folded.encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise ValueError(f"host {host!r} is not a valid name") from exc


def _coerce_literal(host: str) -> Optional[str]:
    """The IP a literal or numeric-encoded host stands for, else ``None``.

    Covers every spelling the platform IPv4 parser accepts (``127.1``, ``0x7f.0.0.1``, ``0177.0.0.1``,
    ``2130706433``, ``0x7f000001``) besides plain IPv4/IPv6 literals.
    """
    try:
        return str(ipaddress.ip_address(host.split("%", 1)[0]))
    except ValueError:
        pass
    if _NUMERIC_HOST.match(host):
        try:
            return socket.inet_ntoa(socket.inet_aton(host))
        except (OSError, ValueError):
            pass
    return None


def check_url(url: Any) -> None:
    """Raise :class:`EgressBlocked` when ``url`` names ``localhost``, an internal-only name or a non-public IP literal.

    The host is canonicalised first (trailing dots, full-width digits, ``127.1``/octal/hex IPv4 spellings), and names
    under internal-only suffixes (``.internal``, ``.local``, ``.svc``, ``.localhost`` …) are refused outright.
    Other hostnames are NOT resolved here (the connector's :class:`GuardedResolver` does that, once, for the real
    connect; browser callers use :func:`resolve_check`).
    """
    text = str(url)
    if any(ch in text.split("?", 1)[0].split("#", 1)[0] for ch in ("\\", "\x00", "\t", "\r", "\n")):
        raise EgressBlocked("egress refused: malformed URL")  # parsers disagree about these: never guess the host
    parsed = urlparse(text)
    try:
        host = _canonical_host(parsed.hostname or "")
    except ValueError as exc:
        raise EgressBlocked(f"egress refused: {exc}") from exc
    if not host:
        raise EgressBlocked(f"egress refused: no host in {text!r}")
    if host == "localhost" or host.endswith(_INTERNAL_SUFFIXES):
        raise EgressBlocked(f"egress refused: internal host {host!r}")
    literal = _coerce_literal(host)
    if literal is not None and not is_public_address(literal):
        raise EgressBlocked(f"egress refused: non-public address {host!r}")


async def resolve_check(url: Any, resolver: Optional[AbstractResolver] = None) -> None:
    """:func:`check_url`, then resolve a NAME and refuse it when any answer is non-public (for browser navigation).

    A browser resolves the name again on its own, so this is a check, not a pin (the cluster NetworkPolicy remains the
    real control); it still stops the plain cases (``metadata.google.internal``, a name pointing at ``10.x``).
    """
    check_url(url)
    host = _canonical_host(urlparse(str(url)).hostname or "")
    if _coerce_literal(host) is not None:
        return
    inner = resolver or GuardedResolver()
    try:
        await inner.resolve(host, 0, socket.AF_UNSPEC)
    except socket.gaierror as exc:
        raise EgressBlocked(f"egress refused: {host!r} did not resolve") from exc
    finally:
        if resolver is None:
            await inner.close()


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
    """A guarded ``ClientSession`` regardless of the host switch (used by :func:`egress_session` and tests).

    ``trust_env=True`` is refused: it would route the request through the environment's proxy, so the connector would
    resolve the PROXY and never the target and the guard would see nothing.
    """
    if kwargs.get("trust_env"):
        raise ValueError("a guarded session cannot trust the environment's proxy settings (trust_env=True)")
    kwargs["trust_env"] = False
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
    "resolve_check",
]

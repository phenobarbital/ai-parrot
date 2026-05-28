"""Content-Security-Policy header builder for infographic HTML serving (FEAT-197).

This helper constructs the full CSP header set required by the public
artifact-HTML endpoint (TASK-1322).  The policy is:

    default-src 'self';
    script-src 'self' 'unsafe-inline' [<cdn origins from js_bundles>];
    style-src 'self' 'unsafe-inline';
    img-src 'self' data:;
    frame-ancestors [<INFOGRAPHIC_FRAME_ANCESTORS env var or 'self'>];

Plus the non-negotiable security headers:
    X-Content-Type-Options: nosniff
    Referrer-Policy: no-referrer

The ``frame-ancestors`` value is driven by the ``INFOGRAPHIC_FRAME_ANCESTORS``
environment variable (comma-separated list, default ``'self'``).  The
``script-src`` CDN origins are derived from the template's ``JSBundle``
entries whose ``scope == 'cdn'``.

CSP MUST be set via HTTP *response header*, not via ``<meta http-equiv>`` —
this is the only way to ensure the policy is enforced before the page parses.
"""
from __future__ import annotations

import os
from typing import Iterable, Mapping
from urllib.parse import urlparse


def _origin_of(url: str) -> str:
    """Extract the origin (scheme + host + optional port) from a URL.

    Args:
        url: Fully-qualified URL, e.g. ``https://cdn.jsdelivr.net/...``.

    Returns:
        Origin string, e.g. ``https://cdn.jsdelivr.net``.
    """
    parsed = urlparse(url)
    if parsed.port:
        return f"{parsed.scheme}://{parsed.hostname}:{parsed.port}"
    return f"{parsed.scheme}://{parsed.hostname}"


def build_csp_headers(
    *,
    js_bundles: Iterable[object] = (),
    frame_ancestors: str = "'self'",
) -> Mapping[str, str]:
    """Build the full CSP + security header set.

    Args:
        js_bundles: Iterable of ``JSBundle`` instances (may be empty).
            Only bundles with ``scope='cdn'`` and a non-empty ``url``
            contribute to ``script-src``.
        frame_ancestors: Space-separated ``frame-ancestors`` value.
            Defaults to ``'self'`` which prevents all embedding.
            Pass the value of ``INFOGRAPHIC_FRAME_ANCESTORS`` from env.

    Returns:
        Dict mapping header name → header value.  All keys are ready to
        be passed to ``web.Response(headers=...)``.
    """
    cdn_origins = " ".join(
        sorted({
            _origin_of(b.url)  # type: ignore[union-attr]
            for b in js_bundles
            if getattr(b, "scope", None) == "cdn" and getattr(b, "url", None)
        })
    )
    script_src = "'self' 'unsafe-inline'"
    if cdn_origins:
        script_src = f"{script_src} {cdn_origins}"

    csp = (
        f"default-src 'self'; "
        f"script-src {script_src}; "
        f"style-src 'self' 'unsafe-inline'; "
        f"img-src 'self' data:; "
        f"frame-ancestors {frame_ancestors}; "
    )
    return {
        "Content-Security-Policy": csp,
        "X-Content-Type-Options": "nosniff",
        "Referrer-Policy": "no-referrer",
    }


def frame_ancestors_from_env(
    env_var: str = "INFOGRAPHIC_FRAME_ANCESTORS",
    default: str = "'self'",
) -> str:
    """Read ``INFOGRAPHIC_FRAME_ANCESTORS`` and normalise to space-separated.

    Args:
        env_var: Environment variable name.
        default: Value to use when the env var is unset or empty.

    Returns:
        Space-separated ``frame-ancestors`` value, e.g.
        ``"https://a.example https://b.example"``.
    """
    raw = os.getenv(env_var, "").strip()
    if not raw:
        return default
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    return " ".join(parts) if parts else default

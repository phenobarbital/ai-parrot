"""Shared signing helpers for public infographic artifact URLs (FEAT-197).

The public HTML serving route
``GET /api/v1/artifacts/public/{signature}/{artifact_id}.html`` authorises
requests with an HMAC signature instead of a session, so the frontend can
embed a frozen infographic in an ``<iframe>`` without an auth round-trip.

This module is the **single source of truth** for that signature scheme so
that both producers (the core ``InfographicToolkit`` that mints the URL when
it persists an artifact) and consumers (the server-side
``ArtifactPublicHTMLView`` that verifies it) agree byte-for-byte.

Signature format::

    {expiry}.{hmac_sha256_base64url}

where ``hmac_sha256_base64url = HMAC-SHA256(key=INFOGRAPHIC_SIGNING_KEY,
msg='{artifact_id}|{expiry}')`` base64url-encoded without padding and
``expiry`` is an absolute UNIX timestamp (seconds).

Environment variables:
    INFOGRAPHIC_SIGNING_KEY:        HMAC secret; required in production.
    INFOGRAPHIC_URL_EXPIRY_SECONDS: Default URL validity (seconds, 7 days).
"""
from __future__ import annotations

import hashlib
import hmac
import os
import time
from base64 import urlsafe_b64encode
from urllib.parse import quote

# Insecure fallback used only when INFOGRAPHIC_SIGNING_KEY is unset. The
# server view logs a loud warning when it sees this value.
_DEV_INSECURE_KEY: bytes = b"dev-insecure-key-change-in-prod"

# Default URL validity (7 days), overridable via env. Shared with
# ``parrot.storage.artifacts`` which reads the same variable.
_DEFAULT_EXPIRY_SECONDS: int = int(
    os.environ.get("INFOGRAPHIC_URL_EXPIRY_SECONDS", "604800")
)

# Public HTML route prefix (must match the route registered by the server).
_PUBLIC_HTML_PREFIX: str = "/api/v1/artifacts/public"


def get_signing_key() -> bytes:
    """Read ``INFOGRAPHIC_SIGNING_KEY`` from the environment.

    Returns:
        The configured key as bytes, or a deterministic insecure fallback
        when the variable is unset (development only).
    """
    raw = os.getenv("INFOGRAPHIC_SIGNING_KEY", "")
    return raw.encode() if raw else _DEV_INSECURE_KEY


def sign_artifact(artifact_id: str, expiry: int, key: bytes) -> str:
    """Compute the base64url HMAC digest over ``'{artifact_id}|{expiry}'``.

    Args:
        artifact_id: Artifact identifier being signed.
        expiry: Absolute UNIX expiry timestamp (seconds).
        key: HMAC secret key.

    Returns:
        base64url-encoded digest without ``=`` padding.
    """
    msg = f"{artifact_id}|{expiry}".encode()
    digest = hmac.new(key, msg, hashlib.sha256).digest()
    return urlsafe_b64encode(digest).decode().rstrip("=")


def verify_signature(
    artifact_id: str, signature_segment: str, key: bytes,
) -> bool:
    """Verify a ``{expiry}.{sig}`` signature segment.

    Args:
        artifact_id: Artifact identifier the signature should authorise.
        signature_segment: The ``{expiry}.{hmac}`` path segment.
        key: HMAC secret key.

    Returns:
        True when the signature is valid AND the expiry is in the future.
    """
    try:
        expiry_str, sig = signature_segment.split(".", 1)
        expiry = int(expiry_str)
    except ValueError:
        return False
    if expiry < int(time.time()):
        return False
    expected = sign_artifact(artifact_id, expiry, key)
    return hmac.compare_digest(expected, sig)


def build_public_html_url(
    artifact_id: str,
    *,
    user_id: str | None = None,
    agent_id: str | None = None,
    session_id: str | None = None,
    expiry_seconds: int | None = None,
    key: bytes | None = None,
) -> str:
    """Build a signed, relative public-HTML URL for an infographic artifact.

    The result targets the server's ``ArtifactPublicHTMLView`` which streams
    rendered HTML from ``Artifact.definition.html`` — unlike the S3 presigned
    URL produced by ``ArtifactStore.get_public_url`` (which points at the raw
    overflow JSON object, not servable HTML).

    Scope query params (``user_id`` / ``agent_id`` / ``session_id``) are
    appended when provided so that scope-partitioned backends (e.g. the local
    filesystem store, whose objects live under
    ``USER#…/AGENT#…/THREAD#…``) can locate the artifact without session
    context. They are NOT covered by the signature; on backends that support
    global lookup by ``artifact_id`` they can be omitted to avoid leaking
    scope into the URL.

    Args:
        artifact_id: Artifact identifier.
        user_id: Owning user (storage scope).
        agent_id: Producing agent (storage scope).
        session_id: Owning session/thread (storage scope).
        expiry_seconds: URL validity window; defaults to
            ``INFOGRAPHIC_URL_EXPIRY_SECONDS`` (7 days).
        key: Override signing key (defaults to ``get_signing_key()``).

    Returns:
        A relative URL string, e.g.
        ``/api/v1/artifacts/public/1717100000.AbCd/infographic-x.html?...``.
    """
    signing_key = key if key is not None else get_signing_key()
    window = expiry_seconds if expiry_seconds is not None else _DEFAULT_EXPIRY_SECONDS
    expiry = int(time.time()) + int(window)
    sig = sign_artifact(artifact_id, expiry, signing_key)
    url = f"{_PUBLIC_HTML_PREFIX}/{expiry}.{sig}/{artifact_id}.html"

    params = []
    if user_id:
        params.append(f"user_id={quote(str(user_id), safe='')}")
    if agent_id:
        params.append(f"agent_id={quote(str(agent_id), safe='')}")
    if session_id:
        params.append(f"session_id={quote(str(session_id), safe='')}")
    if params:
        url = f"{url}?{'&'.join(params)}"
    return url

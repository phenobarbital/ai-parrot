"""Runtime authentication context for per-request credential resolution.

This module defines `AuthContext`, the runtime auth context constructed by
the aiohttp handler on each request. It is distinct from `core.auth.AuthConfig`
(the schema-side declaration) — `AuthContext` carries resolved credentials
and is passed explicitly to `OptionsLoader.fetch()`,
`RemoteResponseResolver.resolve()`, and renderers.

Cascade behaviour: the same `AuthContext` instance flows into nested GROUP
and ARRAY field rendering without re-resolution.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict


class AuthContext(BaseModel):
    """Runtime auth context constructed by the aiohttp handler per request.

    Distinct from ``core.auth.AuthConfig`` which is the schema-side declaration.
    ``AuthContext`` carries resolved credentials and is passed explicitly to
    ``OptionsLoader.fetch()`` / ``RemoteResponseResolver.resolve()`` / renderers.

    Cascade: the same AuthContext flows into nested GROUP / ARRAY field
    rendering without re-resolution.

    Attributes:
        scheme: Auth scheme identifier — "none", "bearer", "api_key", or "custom".
        token: Bearer token or API key value. None if not applicable.
        headers: Raw outbound HTTP headers (pre-built for "custom" scheme).
        claims: Parsed JWT claims if available (e.g., for scope-checking).
    """

    model_config = ConfigDict(extra="forbid")

    scheme: Literal["none", "bearer", "api_key", "custom"]
    token: str | None = None
    headers: dict[str, str] = {}
    claims: dict[str, Any] = {}

    def resolve_for(self, auth_ref: str | None) -> dict[str, str]:
        """Return outbound HTTP headers for the given auth_ref.

        If ``auth_ref`` matches one of the known token env-var references
        in ``self.claims``, returns the appropriate header. Falls back to
        ``self.headers`` if ``auth_ref`` is None or unrecognized.

        Args:
            auth_ref: Optional string key identifying which auth credentials
                to use. Typically matches the ``auth_ref`` field on an
                ``OptionsSource`` or ``RemoteResponseField``.

        Returns:
            Dict of HTTP headers to include in outbound requests.
            Returns ``{}`` if scheme is "none" or ``auth_ref`` is None.
        """
        if auth_ref is None or self.scheme == "none":
            return {}
        if self.scheme == "bearer" and self.token:
            return {"Authorization": f"Bearer {self.token}"}
        if self.scheme == "api_key" and self.token:
            return {"X-API-Key": self.token}
        # For "custom" scheme, return pre-built headers
        return dict(self.headers)

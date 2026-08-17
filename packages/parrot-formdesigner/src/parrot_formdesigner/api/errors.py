"""Typed tenant error responses for parrot-formdesigner (FEAT-421).

Every tenant-aware call site raises one of these instead of hand-rolling
``JSONResponse({"error": ...}, status=...)`` inline. Each exception renders
the stable JSON body contract navigator-svelte branches on:

```json
{
  "error": "tenant_not_declared",
  "message": "This endpoint requires an explicit tenant.",
  "expected": "/api/v1/t/{tenant}/forms/{form_uid}"
}
```

These classes subclass ``aiohttp.web.HTTPException`` so they can be
``raise``d directly from a decorator or handler and aiohttp will render
them as the HTTP response.
"""

from __future__ import annotations

import json

from aiohttp import web


class TenantNotDeclaredError(web.HTTPBadRequest):
    """400 — the request carried no tenant segment.

    Raised when a forms route is reached without a ``tenant`` value in
    ``request.match_info`` (absent or empty).
    """

    error_slug = "tenant_not_declared"

    def __init__(self, *, expected: str | None = None) -> None:
        """Build the 400 response body.

        Args:
            expected: Optional hint describing the expected URL shape,
                e.g. ``"/api/v1/t/{tenant}/forms/{form_uid}"``.
        """
        body: dict[str, str] = {
            "error": self.error_slug,
            "message": "This endpoint requires an explicit tenant.",
        }
        if expected:
            body["expected"] = expected
        super().__init__(
            text=json.dumps(body),
            content_type="application/json",
        )


class TenantForbiddenError(web.HTTPForbidden):
    """403 — the caller is not entitled to the declared tenant.

    Raised when the declared tenant is not among the caller's
    ``session["session"]["programs"]`` and the caller is not a superuser.
    """

    error_slug = "tenant_forbidden"

    def __init__(self, *, expected: str | None = None) -> None:
        """Build the 403 response body.

        Args:
            expected: Optional hint describing the expected URL shape.
        """
        body: dict[str, str] = {
            "error": self.error_slug,
            "message": "You are not authorized for the declared tenant.",
        }
        if expected:
            body["expected"] = expected
        super().__init__(
            text=json.dumps(body),
            content_type="application/json",
        )


class TenantConflictError(web.HTTPBadRequest):
    """400 — the body declared a tenant differing from the URL.

    Raised when a POST/PUT/PATCH body carries a ``tenant`` value that does
    not match the tenant declared in the URL path.
    """

    error_slug = "tenant_conflict"

    def __init__(self, *, expected: str | None = None) -> None:
        """Build the 400 response body.

        Args:
            expected: Optional hint describing the expected URL shape.
        """
        body: dict[str, str] = {
            "error": self.error_slug,
            "message": "The body tenant does not match the URL tenant.",
        }
        if expected:
            body["expected"] = expected
        super().__init__(
            text=json.dumps(body),
            content_type="application/json",
        )

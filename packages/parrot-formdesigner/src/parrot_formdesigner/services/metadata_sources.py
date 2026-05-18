"""Built-in resolvers for ``FormMetadataField`` sources.

This module owns the dispatch table that maps a ``MetadataSource``
literal (e.g. ``"user_id"``, ``"locale"``) to an async resolver that
extracts the corresponding value from the inbound aiohttp request,
the in-flight ``FormSubmission`` record, and the parent ``FormSchema``.

The resolvers deliberately stay tolerant of missing context (returning
``None`` rather than raising) so the enricher can apply the field's
``default`` substitution and ``required`` semantics uniformly.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

from aiohttp import web

if TYPE_CHECKING:
    from ..core.schema import FormMetadataField, FormSchema
    from .submissions import FormSubmission


BuiltinResolver = Callable[
    [web.Request, "FormSubmission", "FormSchema", "FormMetadataField"],
    Awaitable[Any],
]


def _extract_org_id(request: web.Request) -> int | None:
    """Read ``org_id`` from the navigator-auth user session as an integer.

    Mirrors the original logic in ``FormAPIHandler._get_org_id`` so the
    handler and the metadata-source resolver share a single
    implementation.

    Args:
        request: Incoming aiohttp request with ``user`` attribute set by
            the navigator-auth ``user_session`` decorator.

    Returns:
        The first organization's ``org_id`` coerced to ``int``, or
        ``None`` if the user has no organizations, ``user`` is missing,
        or the value cannot be coerced.
    """
    user = getattr(request, "user", None)
    if not user:
        return None
    orgs = getattr(user, "organizations", None) or []
    if not orgs:
        return None
    try:
        return int(orgs[0].org_id)
    except (AttributeError, TypeError, ValueError):
        return None


def _extract_programs(request: web.Request) -> list[str]:
    """Read the programs list from the navigator-auth session."""
    session = getattr(request, "session", None)
    if session is None:
        return []
    try:
        userinfo = session.get("session", {}) or {}
    except AttributeError:
        return []
    programs = userinfo.get("programs", []) or []
    return [str(p) for p in programs]


def _user_attr(request: web.Request, name: str) -> Any:
    user = getattr(request, "user", None)
    if user is None:
        return None
    return getattr(user, name, None)


async def _resolve_user_id(
    request: web.Request,
    submission: "FormSubmission",
    form: "FormSchema",
    field: "FormMetadataField",
) -> Any:
    raw = _user_attr(request, "user_id")
    if raw is None:
        raw = _user_attr(request, "id")
    return None if raw is None else str(raw)


async def _resolve_username(
    request: web.Request,
    submission: "FormSubmission",
    form: "FormSchema",
    field: "FormMetadataField",
) -> Any:
    raw = _user_attr(request, "username")
    if raw is None:
        raw = _user_attr(request, "email")
    return None if raw is None else str(raw)


async def _resolve_org_id(
    request: web.Request,
    submission: "FormSubmission",
    form: "FormSchema",
    field: "FormMetadataField",
) -> Any:
    return _extract_org_id(request)


async def _resolve_submitted_at(
    request: web.Request,
    submission: "FormSubmission",
    form: "FormSchema",
    field: "FormMetadataField",
) -> Any:
    return submission.created_at


async def _resolve_submission_id(
    request: web.Request,
    submission: "FormSubmission",
    form: "FormSchema",
    field: "FormMetadataField",
) -> Any:
    return submission.submission_id


async def _resolve_tenant(
    request: web.Request,
    submission: "FormSubmission",
    form: "FormSchema",
    field: "FormMetadataField",
) -> Any:
    if submission.tenant is not None:
        return submission.tenant
    if form.tenant is not None:
        return form.tenant
    header = request.headers.get("X-Parrot-Tenant")
    return header or None


async def _resolve_programs(
    request: web.Request,
    submission: "FormSubmission",
    form: "FormSchema",
    field: "FormMetadataField",
) -> Any:
    return _extract_programs(request)


async def _resolve_ip(
    request: web.Request,
    submission: "FormSubmission",
    form: "FormSchema",
    field: "FormMetadataField",
) -> Any:
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.remote


async def _resolve_user_agent(
    request: web.Request,
    submission: "FormSubmission",
    form: "FormSchema",
    field: "FormMetadataField",
) -> Any:
    return request.headers.get("User-Agent")


async def _resolve_locale(
    request: web.Request,
    submission: "FormSubmission",
    form: "FormSchema",
    field: "FormMetadataField",
) -> Any:
    opts = field.options or {}
    header_name = opts.get("header", "Accept-Language")
    value = request.headers.get(header_name)
    if not value:
        return None
    # Strip quality params: "en-US,en;q=0.9" -> "en-US".
    primary = value.split(",")[0].strip()
    return primary or None


async def _resolve_constant(
    request: web.Request,
    submission: "FormSubmission",
    form: "FormSchema",
    field: "FormMetadataField",
) -> Any:
    return field.default


BUILTIN_METADATA_SOURCES: dict[str, BuiltinResolver] = {
    "user_id": _resolve_user_id,
    "username": _resolve_username,
    "org_id": _resolve_org_id,
    "submitted_at": _resolve_submitted_at,
    "submission_id": _resolve_submission_id,
    "tenant": _resolve_tenant,
    "programs": _resolve_programs,
    "ip": _resolve_ip,
    "user_agent": _resolve_user_agent,
    "locale": _resolve_locale,
    "constant": _resolve_constant,
}

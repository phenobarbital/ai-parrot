"""Shared utility helpers for the JSON REST API surface.

Migrated verbatim from ``handlers/api.py:36-103`` as part of FEAT-152.
The helpers are pure functions; importing this module triggers no side
effects.
"""

from __future__ import annotations

import re
import uuid
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from aiohttp import web


#: Accepted shape for a ``form_id`` supplied by a client. Deliberately
#: narrower than "any string": form ids are interpolated into URLs
#: (``/api/v1/forms/{form_id}``) and used as storage keys, so slashes,
#: spaces, dots and path traversal sequences are rejected up-front.
#: Anchored with ``\Z`` rather than ``$`` — ``$`` also matches just before a
#: trailing newline, which would let ``"my-form\n"`` through.
FORM_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}\Z")


def _get_request_tenant(request: "web.Request") -> str | None:
    """Extract the effective tenant from an aiohttp request.

    Resolution order:

    1. First program slug from the navigator-auth session
       (``request.session["session"]["programs"][0]``).
    2. ``request.app["form_registry"].default_tenant`` when the registry
       has self-registered (FEAT-185) — covers anonymous and session-less
       paths so ``register(require_tenant=True)`` doesn't bite.
    3. ``None`` only when both sources are absent (unusual test setups).

    This is the shared implementation of the pattern established by
    ``FormAPIHandler._get_tenant`` (TASK-1243) for use in module-level
    handlers that do not inherit from ``FormAPIHandler``.

    Args:
        request: Incoming aiohttp web.Request.

    Returns:
        Tenant slug string, or ``None`` if neither the session nor the
        application registry can provide one.
    """
    session = getattr(request, "session", None)
    if session is not None:
        userinfo = session.get("session", {})
        programs: list[str] = userinfo.get("programs", [])
        if programs:
            return programs[0]

    registry = request.app.get("form_registry") if request.app is not None else None
    if registry is not None:
        default = getattr(registry, "default_tenant", None)
        if default is not None:
            return default
    return None


def _deep_merge(base: dict, patch: dict) -> dict:
    """RFC 7396 JSON merge-patch: recursively merge patch onto base.

    Rules:
    - ``dict`` values are merged recursively.
    - ``None`` (null) values remove the corresponding key from the base.
    - All other values (including lists) replace the base value entirely.

    Args:
        base: The original dict to merge into.
        patch: The partial update to apply.

    Returns:
        A new dict with the patch applied to the base.
    """
    result = base.copy()
    for key, value in patch.items():
        if value is None:
            result.pop(key, None)
        elif isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _loc_to_str(value: object) -> str | None:
    """Flatten a LocalizedString (str | dict[str, str]) to a plain str.

    Mirrors the title-extraction pattern used in
    ``PostgresFormStorage.list_forms`` so the API and storage layers
    agree on rendering.

    Args:
        value: Raw value — string, ``{lang: text}`` dict, or ``None``.

    Returns:
        Plain string if a non-empty value was provided; ``None`` if the
        input is ``None``, an empty string/dict, or any falsy scalar
        value (e.g., ``0``, ``False``).
    """
    if value is None:
        return None
    if isinstance(value, dict):
        value = next(iter(value.values()), None)
    if not value:
        return None
    return str(value)


def is_valid_form_id(value: object) -> bool:
    """Return ``True`` when ``value`` is a safe, URL-embeddable form id.

    Args:
        value: Candidate form id (any type — non-strings return ``False``).

    Returns:
        ``True`` if the value matches :data:`FORM_ID_RE`.
    """
    return isinstance(value, str) and bool(FORM_ID_RE.match(value))


def slugify_form_id(text: str) -> str:
    """Derive a URL-safe ``form_id`` slug from free-form text.

    Mirrors ``parrot_formdesigner.tools.create_form._slugify`` so the
    manual (no-LLM) creation path and the natural-language path produce
    ids of the same shape. Falls back to a random slug when ``text``
    contains no usable characters.

    Examples:
        ``"Store Visit 2026"`` → ``"store-visit-2026"``
        ``"¿Encuesta?"`` → ``"encuesta"``
        ``"!!!"`` → ``"form-1a2b3c4d"``

    Args:
        text: Arbitrary human-entered text (typically the form title).

    Returns:
        A lowercase hyphenated slug of at most 50 characters, guaranteed
        to match :data:`FORM_ID_RE`.
    """
    slug = text.lower().strip()
    slug = re.sub(r"[^a-z0-9\s-]", "", slug)
    slug = re.sub(r"[\s-]+", "-", slug).strip("-")
    slug = slug[:50].strip("-")
    if not is_valid_form_id(slug):
        return f"form-{uuid.uuid4().hex[:8]}"
    return slug


def _bump_version(version: str) -> str:
    """Increment the minor component of a version string.

    Examples:
        ``"1.0"`` → ``"1.1"``
        ``"1.5"`` → ``"1.6"``
        ``"1"`` → ``"1.1"``
        ``"1.2.3"`` → ``"1.2.4"``

    Args:
        version: Current version string.

    Returns:
        Version string with the last numeric component incremented by 1.
    """
    parts = version.split(".")
    if len(parts) >= 2:
        parts[-1] = str(int(parts[-1]) + 1)
    else:
        parts.append("1")
    return ".".join(parts)

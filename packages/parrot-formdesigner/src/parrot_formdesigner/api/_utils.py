"""Shared utility helpers for the JSON REST API surface.

Migrated verbatim from ``handlers/api.py:36-103`` as part of FEAT-152.
The helpers are pure functions; importing this module triggers no side
effects.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from aiohttp import web


def _get_request_tenant(request: "web.Request") -> str | None:
    """Extract the effective tenant from an aiohttp request.

    Reads the first program slug from the navigator-auth session
    (``request.session["session"]["programs"][0]``). Returns ``None``
    when no session is present or the programs list is empty, allowing
    :class:`~parrot_formdesigner.services.registry.FormRegistry` to fall
    back to its configured ``default_tenant``.

    This is the shared implementation of the pattern established by
    ``FormAPIHandler._get_tenant`` (TASK-1243) for use in module-level
    handlers that do not inherit from ``FormAPIHandler``.

    Args:
        request: Incoming aiohttp web.Request.

    Returns:
        First program slug string, or ``None`` if not available.
    """
    session = getattr(request, "session", None)
    if session is None:
        return None
    userinfo = session.get("session", {})
    programs: list[str] = userinfo.get("programs", [])
    return programs[0] if programs else None


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

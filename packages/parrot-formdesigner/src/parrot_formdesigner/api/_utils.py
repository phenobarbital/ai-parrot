"""Shared utility helpers for the JSON REST API surface.

Migrated verbatim from ``handlers/api.py:36-103`` as part of FEAT-152.
The helpers are pure functions; importing this module triggers no side
effects.
"""

from __future__ import annotations


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
    """Increment the minor (or last) component of a version string.

    FEAT-433 TASK-2267: delegates to the single bump grammar in
    ``services.form_version._bump`` (``bump="minor"``, the only mode this
    call site ever used) — see that function's docstring for the full
    grammar. Kept as a thin wrapper so the 21 forms call sites that import
    ``_bump_version`` from here are untouched.

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
    from ..services.form_version import _bump

    return _bump(version, bump="minor")

"""One MIME matcher for every upload gate in the form API.

``FieldConstraints.allowed_mime_types`` holds what the Form Designer's presets
write, and **those presets are wildcards**: "Images only" writes ``image/*``
and "Images or PDF" writes ``image/*`` plus ``application/pdf``. An exact
membership test (``content_type not in allowed_mimes``) rejects every real
file against one, because a picked photo arrives as ``image/jpeg`` and nothing
is ever literally ``image/*``.

That is exactly what the three upload gates did, so a field configured with
either of those two presets refused every file with a 415 — while the client
had already accepted it, since navigator-svelte's own matcher
(``domain/mime-match.ts``) understands the wildcard. The two ends disagreed
about what the field accepts, and the one the author configured through the
UI was the one that could never work.

Kept as a module rather than a local helper for the same reason the frontend
extracted its own: there are three call sites, and the last time each wrote
its own check they all wrote the same bug.
"""

from __future__ import annotations

__all__ = ["mime_matches"]


def _extension_of(file_name: str | None) -> str:
    """The lowercased extension of ``file_name``, without the dot."""
    if not file_name:
        return ""
    _, _, ext = file_name.rpartition(".")
    # `rpartition` returns ('', '', whole) when there is no dot at all.
    return ext.lower() if "." in file_name else ""


def mime_matches(
    allowed_mime_types: list[str] | None,
    mime_type: str | None,
    file_name: str | None = None,
) -> bool:
    """Does this file satisfy any of the allowed patterns?

    Three pattern shapes are accepted, matching what the Form Designer can
    write and what ``domain/mime-match.ts`` accepts on the client:

    * an exact type — ``image/png``
    * a wildcard — ``image/*``
    * a bare extension — ``.heic``, for the types a browser reports with an
      empty content type

    Args:
        allowed_mime_types: The configured patterns. ``None`` or empty means
            no restriction, and returns ``True`` — the caller does not have to
            remember which way an empty list goes.
        mime_type: The file's reported content type, if any.
        file_name: The file's name, used only for a bare-extension pattern.

    Returns:
        ``True`` when the file is allowed.
    """
    if not allowed_mime_types:
        return True

    ext = _extension_of(file_name)

    for allowed in allowed_mime_types:
        if allowed.startswith("."):
            if ext and ext == allowed[1:].lower():
                return True
            continue

        if not mime_type:
            continue
        if allowed == mime_type:
            return True
        if allowed.endswith("/*"):
            prefix = allowed.split("/", 1)[0]
            # `prefix + "/"`, not a bare prefix: `image/*` must not swallow
            # `imagex/png`.
            if mime_type.startswith(prefix + "/"):
                return True

    return False

"""Filesystem path helpers with path-traversal protection.

Several identifiers used to build on-disk paths (``agent_id``,
``chatbot_id``, filenames, …) reach the framework straight from an HTTP
payload, which makes every ``base / identifier`` join a path-traversal sink
(CWE-22 / CodeQL ``py/path-injection``). The helpers here apply two
independent barriers:

1. every untrusted segment must match :data:`SAFE_SEGMENT_RE` — a single
   path component: no separators, no ``..``, no leading dot;
2. the joined path is normalised and verified to stay inside ``base``
   **before** it is used for any filesystem access.

The containment check deliberately uses :func:`os.path.normpath` (pure
string normalisation) instead of :meth:`pathlib.Path.resolve`: ``resolve()``
touches the filesystem, so calling it on a not-yet-validated path would be
the very access the guard is meant to prevent.
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Union

#: A single, safe path component: starts alphanumeric, then alphanumerics,
#: dot, dash or underscore. Rejects ``/``, ``\``, ``..`` and absolute paths.
#: Always applied with :meth:`re.Pattern.fullmatch` — ``match()`` would accept a
#: trailing newline, since Python's ``$`` also matches just before one.
SAFE_SEGMENT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def validate_path_segment(value: str, name: str = "path segment") -> str:
    """Validate that ``value`` is a safe single path component.

    Args:
        value: The candidate path component (typically untrusted input).
        name: Human-readable name of the value, used in the error message.

    Returns:
        The validated ``value``, unchanged.

    Raises:
        ValueError: If ``value`` is not a string or does not match
            :data:`SAFE_SEGMENT_RE`.
    """
    if not isinstance(value, str) or not SAFE_SEGMENT_RE.fullmatch(value):
        raise ValueError(f"Unsafe {name} for path construction: {value!r}")
    return value


def secure_path(
    base: Union[str, Path],
    *segments: str,
    name: str = "path segment",
) -> Path:
    """Join ``segments`` under ``base``, refusing anything that escapes it.

    Args:
        base: Trusted root directory the result must stay within.
        *segments: Path components to append. Each one is validated with
            :func:`validate_path_segment`.
        name: Human-readable name of the untrusted value, used in error
            messages.

    Returns:
        The canonical path — normalised and symlink-resolved, as
        :meth:`pathlib.Path.resolve` would return — guaranteed to be ``base``
        itself or a descendant of it.

    Raises:
        ValueError: If a segment is unsafe or the joined path would escape
            ``base``.
    """
    base_path = str(Path(base).expanduser().resolve())
    safe_segments = [validate_path_segment(segment, name=name) for segment in segments]
    candidate = os.path.normpath(os.path.join(base_path, *safe_segments))
    if candidate != base_path and not candidate.startswith(base_path + os.sep):
        raise ValueError(
            f"Path traversal detected: {os.path.join(*safe_segments)!r} "
            f"escapes {base_path!r}"
        )
    # Second barrier: the string check above cannot see symlinks, so an
    # already-existing component could still point outside ``base``. Following
    # the links here is safe — ``candidate`` has passed the containment check,
    # so this is no longer an access driven by unvalidated input.
    resolved = Path(candidate).resolve()
    if str(resolved) != base_path and not str(resolved).startswith(base_path + os.sep):
        raise ValueError(
            f"Path traversal detected: {candidate!r} resolves outside {base_path!r}"
        )
    return resolved

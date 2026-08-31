"""Path confinement and secret deny-list — the security boundary of FEAT-484.

This module is the single code path every path-taking tool in
``parrot.tools.repo`` funnels through. Two independent checks are composed
here on purpose (spec §7: "a second implementation is a second chance to
get it wrong"):

1. Containment — ``resolve_within_root()`` resolves a caller-supplied path
   to its real (symlink-following) absolute form and asserts it lives
   inside ``root``.
2. Secret deny-list — ``is_secret_path()`` (spec §8 Q1) rejects paths that
   look like credentials, even when they are safely inside the root.

``resolve_readable_path()`` composes both and is what tools should call.

This module is deliberately dependency-free beyond the standard library —
no ``AbstractToolkit``, no ``pydantic`` models are imported here so it can
be exercised in isolation.
"""
from __future__ import annotations

import fnmatch
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# Deny patterns matched case-insensitively against each path segment of the
# repo-relative POSIX path (spec §8 Q1 — implement exactly).
_SECRET_DENY: tuple[str, ...] = (
    ".env", ".env.*", "*.pem", "*.key", "*.p12", "*.pfx",
    "id_rsa*", "id_dsa*", "id_ecdsa*", "id_ed25519*",
    "*.local.json", "credentials", ".netrc", ".pgpass",
    "*.keystore", "*.jks",
)

# A deny-list match is overridden (the file becomes readable) when the
# filename ends in one of these suffixes.
_SECRET_ALLOW_SUFFIXES: tuple[str, ...] = (".example", ".sample", ".template", ".dist")


class PathOutsideRootError(ValueError):
    """Raised when a resolved path is not contained within the repo root."""


class SecretFileError(ValueError):
    """Raised when a path matches the secret deny-list (spec §8 Q1)."""


def resolve_within_root(root: Path, candidate: str) -> Path:
    """Resolve ``candidate`` and assert containment in ``root``.

    ``root`` is resolved too, so a root reached via a symlink does not make
    every containment check wrong. The join happens before resolution, so
    that ``..`` traversal and a symlink *inside* the root that points
    outside it are both collapsed by the same ``Path.resolve()`` call.

    Args:
        root: The repository root to confine reads/writes to.
        candidate: A caller-supplied path, relative or absolute.

    Returns:
        The resolved, absolute, real path — guaranteed to be inside
        ``root``.

    Raises:
        PathOutsideRootError: The resolved path (after following symlinks)
            is not inside ``root``.
    """
    real_root = root.resolve()
    # Joining an absolute `candidate` onto `real_root` discards the left
    # operand (pathlib semantics), which then correctly fails containment
    # below — no special-casing needed.
    target = (real_root / candidate).resolve()
    if target != real_root and not target.is_relative_to(real_root):
        raise PathOutsideRootError(
            f"{candidate!r} resolves outside the repository root"
        )
    return target


def is_secret_path(rel_path: str) -> bool:
    """True when ``rel_path`` matches the secret deny-list (spec §8 Q1).

    Matched case-insensitively on the repo-relative path. Any path segment
    matching a deny pattern counts, so ``config/.env`` and ``.env`` both
    match. A match is overridden — the path is treated as readable — when
    the filename ends in ``.example``, ``.sample``, ``.template`` or
    ``.dist``.

    Args:
        rel_path: A repo-relative path (relative or absolute string form is
            accepted; only the POSIX representation is inspected).

    Returns:
        True if the path should be denied, False otherwise.
    """
    posix = Path(rel_path).as_posix().lower()
    if posix.endswith(_SECRET_ALLOW_SUFFIXES):
        return False
    return any(
        fnmatch.fnmatch(segment, pattern)
        for segment in Path(posix).parts
        for pattern in _SECRET_DENY
    )


def resolve_readable_path(root: Path, candidate: str) -> Path:
    """Resolve ``candidate`` within ``root`` and enforce the secret deny-list.

    This is the composed entry point tools should call: containment first,
    then the deny-list. Both checks raise; converting the exception to a
    ``RepoToolError`` is the caller's responsibility, so each tool can
    attach its own error code and context.

    Args:
        root: The repository root to confine reads to.
        candidate: A caller-supplied path, relative or absolute.

    Returns:
        The resolved, absolute, real path.

    Raises:
        PathOutsideRootError: The resolved path escapes ``root``.
        SecretFileError: The path matches the secret deny-list.
    """
    target = resolve_within_root(root, candidate)
    rel_path = target.relative_to(root.resolve()).as_posix()
    if is_secret_path(rel_path):
        raise SecretFileError(f"{rel_path!r} matches the secret deny-list")
    return target

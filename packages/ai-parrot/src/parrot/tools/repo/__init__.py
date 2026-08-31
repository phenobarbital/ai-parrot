"""Read-only, cwd-confined repository access for any ``AbstractClient``.

See ``sdd/specs/readonly-repo-toolkit.spec.md`` (FEAT-484) for the full
design. This package exposes ``ReadOnlyRepoToolkit`` plus the confinement
core and shared data contracts used across every tool.
"""
from __future__ import annotations

from .confinement import (
    PathOutsideRootError,
    SecretFileError,
    is_secret_path,
    resolve_readable_path,
    resolve_within_root,
)
from .models import (
    RepoReadResult,
    RepoSearchHit,
    RepoSearchResult,
    RepoToolError,
)
from .toolkit import ReadOnlyRepoToolkit

__all__ = [
    "PathOutsideRootError",
    "ReadOnlyRepoToolkit",
    "RepoReadResult",
    "RepoSearchHit",
    "RepoSearchResult",
    "RepoToolError",
    "SecretFileError",
    "is_secret_path",
    "resolve_readable_path",
    "resolve_within_root",
]

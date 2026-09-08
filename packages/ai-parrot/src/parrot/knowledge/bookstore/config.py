"""Library directory resolution for the Bookstore.

Precedence (first match becomes the ``project`` scope):

1. ``PARROT_LIBRARY_DIR`` environment variable — explicit override.
2. ``<git root>/.parrot/library`` — repo-local library.
3. ``parrot_home()/library`` (``~/.parrot/library``, relocatable via
   ``PARROT_HOME``) — always appended as the ``global`` scope.

Environment variables are read on every call — never cached at import
time — so test ``monkeypatch.setenv`` is always seen (same contract as
:func:`parrot.knowledge.wiki.project.parrot_home`).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Optional

ENV_LIBRARY_DIR = "PARROT_LIBRARY_DIR"
LIBRARY_SUBPATH = Path(".parrot") / "library"
DB_FILENAME = "library.db"
TREES_DIRNAME = "trees"

Scope = Literal["project", "global"]


@dataclass(frozen=True)
class LibraryLocation:
    """One resolved library directory with its precedence scope.

    Args:
        scope: ``"project"`` (wins collisions) or ``"global"``.
        root: The ``.../library`` directory itself.
    """

    scope: Scope
    root: Path

    @property
    def db_path(self) -> Path:
        """Path of the catalog database (``library.db``)."""
        return self.root / DB_FILENAME

    @property
    def trees_dir(self) -> Path:
        """PageIndex ``storage_dir`` for this location (``trees/``)."""
        return self.root / TREES_DIRNAME

    def exists(self) -> bool:
        """Whether this location holds an initialized catalog."""
        return self.db_path.is_file()


def _find_git_root(start: Path) -> Optional[Path]:
    """Walk upwards from ``start`` to the nearest ``.git`` root."""
    current = start.resolve()
    for candidate in (current, *current.parents):
        if (candidate / ".git").exists():
            return candidate
    return None


def _parrot_home() -> Path:
    """Per-user parrot state dir (``~/.parrot``), ``PARROT_HOME``-overridable.

    Kept local (instead of importing
    :func:`parrot.knowledge.wiki.project.parrot_home`) so that importing
    ``bookstore.config`` never drags the wiki module chain in — but the
    contract is identical.
    """
    raw = os.environ.get("PARROT_HOME") or "~/.parrot"
    return Path(raw).expanduser()


def resolve_locations(
    cwd: Optional[Path] = None,
    include_global: bool = True,
    require_exists: bool = False,
) -> list[LibraryLocation]:
    """Resolve the ordered list of library locations.

    Args:
        cwd: Directory to resolve the project scope from (defaults to
            the process CWD).
        include_global: Append the ``~/.parrot/library`` global scope.
        require_exists: Drop locations without an initialized
            ``library.db`` (used by the read-only MCP server).

    Returns:
        Ordered locations, project scope first. May be empty when
        ``require_exists=True`` and no catalog exists anywhere.
    """
    locations: list[LibraryLocation] = []

    env_dir = os.environ.get(ENV_LIBRARY_DIR)
    if env_dir:
        locations.append(
            LibraryLocation(scope="project", root=Path(env_dir).expanduser())
        )
    else:
        git_root = _find_git_root(cwd or Path.cwd())
        if git_root is not None:
            locations.append(
                LibraryLocation(scope="project", root=git_root / LIBRARY_SUBPATH)
            )

    if include_global:
        locations.append(
            LibraryLocation(scope="global", root=_parrot_home() / "library")
        )

    # De-duplicate by resolved path (e.g. PARROT_LIBRARY_DIR pointing at
    # the global dir must not list it twice); first occurrence wins so
    # the project scope keeps precedence.
    seen: set[Path] = set()
    unique: list[LibraryLocation] = []
    for loc in locations:
        key = loc.root.resolve()
        if key in seen:
            continue
        seen.add(key)
        unique.append(loc)

    if require_exists:
        unique = [loc for loc in unique if loc.exists()]
    return unique

"""In-memory vault index: wikilink resolution, backlinks, tags, aliases.

One resolution engine shared by every Obsidian consumer (toolkit search,
FEAT-392 graph bridge, wikitoolkit vault scan) so a ``[[wikilink]]`` always
resolves to the same note everywhere.

Resolution replicates Obsidian's semantics (FEAT-392 §7 gotcha):
an exact vault-relative path wins, then a basename match (shortest path on
duplicates — Obsidian's tiebreak), then an alias match.
"""
import logging
import posixpath
from collections import defaultdict
from pathlib import Path
from typing import Optional

from .models import ObsidianLink, ObsidianNote

logger = logging.getLogger(__name__)


def _norm(path: str | Path) -> str:
    """Normalize a vault path to POSIX form without the .md suffix."""
    text = Path(path).as_posix()
    if text.lower().endswith(".md"):
        text = text[: -len(".md")]
    return text


class VaultIndex:
    """Immutable index over a parsed vault snapshot.

    Build with :meth:`build`; rebuild after any note mutation (the toolkit
    invalidates its cached index after write/delete/move operations).
    """

    def __init__(self) -> None:
        self._notes: dict[str, ObsidianNote] = {}          # norm path -> note
        self._by_basename: dict[str, list[str]] = defaultdict(list)
        self._by_alias: dict[str, str] = {}
        self._by_tag: dict[str, set[str]] = defaultdict(set)
        self._outlinks: dict[str, list[ObsidianLink]] = defaultdict(list)
        self._backlinks: dict[str, set[str]] = defaultdict(set)
        self._unresolved: list[tuple[str, str]] = []

    @classmethod
    def build(cls, notes: list[ObsidianNote]) -> "VaultIndex":
        """Build the index from parsed notes.

        Args:
            notes: All parsed markdown notes of the vault.

        Returns:
            A fully populated :class:`VaultIndex` (links resolved, backlink
            map computed, unresolved links recorded).
        """
        index = cls()
        for note in notes:
            key = _norm(note.path)
            index._notes[key] = note
            index._by_basename[posixpath.basename(key).lower()].append(key)
            for alias in note.aliases:
                index._by_alias.setdefault(alias.lower(), key)
            for tag in note.tags:
                index._by_tag[tag.lower()].add(key)

        for key, note in index._notes.items():
            index._outlinks[key] = list(note.links)
            for link in note.links:
                resolved = index.resolve(link.target, from_path=key)
                if resolved is None:
                    index._unresolved.append((key, link.target))
                else:
                    index._backlinks[resolved].add(key)
        return index

    def resolve(
        self, target: str, from_path: Optional[str] = None
    ) -> Optional[str]:
        """Resolve a wikilink target to a normalized vault path.

        Args:
            target: Raw wikilink target (``note``, ``folder/note``, alias).
            from_path: Path of the linking note (reserved for future
                relative-resolution rules; Obsidian's default "shortest path
                when ambiguous" does not depend on it).

        Returns:
            Normalized vault-relative path (no ``.md``), or ``None`` when
            the target does not resolve to any note.
        """
        wanted = _norm(target.strip())
        if not wanted:
            return None
        # 1. Exact vault-relative path.
        if wanted in self._notes:
            return wanted
        exact_ci = wanted.lower()
        for key in self._notes:
            if key.lower() == exact_ci:
                return key
        # 2. Basename match; shortest path wins on duplicates.
        candidates = self._by_basename.get(posixpath.basename(exact_ci), [])
        if candidates:
            return min(candidates, key=lambda p: (len(p.split("/")), p))
        # 3. Alias match.
        return self._by_alias.get(exact_ci)

    def note(self, path: str | Path) -> Optional[ObsidianNote]:
        """Return the parsed note at a vault path, or None."""
        return self._notes.get(_norm(path))

    def paths(self) -> list[str]:
        """All indexed note paths (normalized, sorted)."""
        return sorted(self._notes)

    def backlinks(self, path: str | Path) -> list[str]:
        """Notes whose wikilinks resolve to this note (sorted paths)."""
        return sorted(self._backlinks.get(_norm(path), set()))

    def outlinks(self, path: str | Path) -> list[ObsidianLink]:
        """This note's outgoing wikilinks/embeds (resolved or not)."""
        return list(self._outlinks.get(_norm(path), []))

    def notes_by_tag(self, tag: str) -> list[str]:
        """Notes carrying a tag; nested tags match by prefix (``a`` ⊇ ``a/b``)."""
        wanted = tag.lstrip("#").lower()
        found: set[str] = set()
        for candidate, paths in self._by_tag.items():
            if candidate == wanted or candidate.startswith(f"{wanted}/"):
                found.update(paths)
        return sorted(found)

    def tags(self) -> dict[str, int]:
        """Tag -> note count over the whole vault."""
        return {tag: len(paths) for tag, paths in sorted(self._by_tag.items())}

    def aliases(self) -> dict[str, str]:
        """Alias (lowercased) -> normalized note path."""
        return dict(self._by_alias)

    def orphans(self) -> list[str]:
        """Notes with no resolved incoming and no outgoing links."""
        return sorted(
            key
            for key in self._notes
            if not self._backlinks.get(key) and not self._outlinks.get(key)
        )

    def unresolved(self) -> list[tuple[str, str]]:
        """(from_path, raw_target) pairs for broken wikilinks."""
        return list(self._unresolved)
